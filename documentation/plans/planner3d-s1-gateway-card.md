# Behaviour card: PLANNER-3D-S1 gateway (keys, upload, model job, get job)

Lane PLANNER-3D-S1-GATEWAY. Size M. Contract: `documentation/planner3d/module-contract.md` v0.6
(sections 2, 3.1 to 3.3, 3.5, 3.7, 5, 8). CRM client: sorento-crm PR #2789 head `f952f276d`,
`sorento_crm_backend/app/services/planner_ss_client.py`.

## What the CRM calls (must match exactly)

`PLANNER_SS_URL` is the gateway base, e.g. `https://<ss host>/be/api/v1/planner3d`; every call sends
`Authorization: Bearer fx3_live_...` (`planner_ss_client.py:50-52`).

| Call | CRM line | SS answer the CRM reads |
|---|---|---|
| `POST {base}/uploads`, multipart part `file` | `planner_ss_client.py:64-69` | `201 {"id": "upl_...", "mime", "size", "sha256", "expiresAt"}`; CRM reads `id` |
| `POST {base}/models`, JSON `{productCode, uploadIds, dimensionsMm{length,width,height}, company}`, header `Idempotency-Key` = CRM job id | `planner_ss_client.py:72-91`, test `test_planner_ss_client.py:89-121` | `202` job object (`200` + same job on an idempotent repeat); CRM reads `id` |
| `GET {base}/jobs/{id}` | `planner_ss_client.py:94-102` | job object; CRM reads `status` and `result.files[]` with `role` `candidate`, `name` `*.glb`, `url`, `size`, `sha256` (`product_model_service.py:649-666` on the PR) |
| webhook `model.candidates_ready` to the CRM receiver `POST <crm>/api/v1/public/planner/events` | `product_model_service.py:574-590`, `planner_event_service.py` (C3) | this is what starts the CRM's fetch; without it a job sits in Processing and turns Failed after 15 minutes |

Any non-2xx, or a transport error, the CRM shows as "The model service could not be reached, try
again" (`planner_ss_client.py:39-60`), so SS's error codes matter for logs and support, not for the CRM screen.

## Behaviour

Key lifecycle (Services > 3D Planner > Keys, Resource list copied from Lead Capture > Keys):

1. An admin clicks Create, types a name, and sees the full `fx3_live_...` key ONCE in the dialog with Copy.
   Afterwards the list shows only `fx3_live_****` + last 4, name, created, last used, status.
2. A tenant may hold several active keys (rotation). Revoke is a row action (right-click and the `...`
   menu); a revoked key answers 401 on its next call. SS stores only a sha256 hash and an 8-character prefix.
3. A key resolves to exactly one tenant; nothing in the path, query or body picks the tenant. Another
   tenant's upload or job id answers 404, the same as an unknown id.

Limits and errors (envelope `{"error": {"code", "message", "details"}}`, contract 2.2):

| When | Answer |
|---|---|
| no key, malformed, unknown or revoked | `401 invalid_api_key` |
| 20 failed keys from one IP inside the window | `429 rate_limited` + `Retry-After` |
| tenant suspended or 3D Planner not installed / inactive | `403 service_not_enabled` |
| more than 600 requests per key per 5 minutes | `429 rate_limited` + `Retry-After` |
| upload over 20 MB | `413 file_too_large` |
| upload not PNG, JPEG or WebP by its first bytes | `415 unsupported_file` |
| `uploadIds` empty, more than 3, unknown, another tenant's or expired | `422 invalid_request` |
| `dimensionsMm` missing or not positive, `productCode` not 1 to 100 characters | `422 invalid_request` |
| same `Idempotency-Key` + same body inside 24 hours | `200`, the first job |
| same `Idempotency-Key`, different body | `409 idempotency_conflict` |
| 20 jobs of this tenant already waiting | `429 queue_full` |

Job states: `queued` (submitted, waiting for the Mac worker) -> `running` (worker claimed it) ->
`succeeded` (2 or 3 candidates) or `failed` (`error.code`) or `cancelled`. On `succeeded` / `failed`
SS sends `model.candidates_ready` to each receiver subscribed to it, signed `X-Planner3d-Signature`
(contract 5.3), retried 1m, 5m, 30m, 2h, 6h, 24h. Candidate `url` is a signed link valid 1 hour that
opens without the key; `GET /jobs/{id}` always hands out a fresh link.

## Questions (each with a recommendation)

1. **Events in this lane?** (a) SS pushes `model.candidates_ready` to a receiver URL + signing secret the
   admin sets on a "Receivers" tab next to Keys (reusing the Lead Capture delivery sender and its retry
   ladder), or (b) leave events out and change the CRM to poll `GET /jobs/{id}`.
   Recommendation: (a), because the CRM (C3 receiver + C5) is already built to wait for that event and
   the contract (5.7) says SS sends it; (b) means a second CRM change before the owner can re-test.
2. **No worker configured.** (a) Jobs wait as `queued` until the Mac worker claims them (S3 behaviour
   today), or (b) also build the in-process CPU stub (contract 6.3) in this lane.
   Recommendation: (a), the owner's re-test runs the real TripoSR worker; the stub is a separate slice.
3. **Caps in this lane.** (a) Only the request budget (600 per 5 minutes per key), the failed-key IP
   throttle and the 20-waiting-jobs queue cap; monthly GPU cap, paid engine and `/usage` later, or
   (b) the whole section 4 settings screen now.
   Recommendation: (a), nothing paid exists yet and the GPU is our own Mac.
4. **Photos per job.** (a) 1 to 3 photos (what the S3 worker and the CRM's picker use), or (b) 1 to 6
   as contract 3.3 says. Recommendation: (a), and amend the contract line, because the worker and
   `submit_model` already cap at 3 (`job_service.py:46`).
5. **Unused uploads.** (a) An upload no job used is deleted after 24 hours by the delivery tick, or
   (b) kept until a later retention slice. Recommendation: (a), it is a few lines and keeps product
   photos from lingering in storage.
