# 3D Planner gateway runbook (PLANNER-3D-S1)

How crew wires a CRM copy to the Shared Service (SS) so a product's 3D model tab gets real TripoSR
candidates. Contract: `module-contract.md` v0.7. Never paste a real key, token or secret into a PR,
an issue or a chat; each one below is shown once on screen or lives in a keychain / secret store.

## 0. What talks to what

```
CRM copy ──Bearer fx3_live_…──▶ SS /api/v1/planner3d  (uploads, models, jobs)
Mac worker ──Bearer worker token──▶ SS /planner3d/worker  (claim, inputs, outputs, finish)
SS ──signed model.candidates_ready──▶ CRM /api/v1/public/planner/events
CRM ──signed link, no key──▶ SS /planner3d/files/<id>?exp=&sig=  (candidate GLBs)
```

Both directions must reach each other over public `https`: SS pushes only to public https receivers
and the CRM downloads only from public hosts. A CRM copy on a laptop needs a tunnel (for example
`cloudflared tunnel --url http://localhost:<crm port>`) and that tunnel URL is the receiver URL.

## 1. SS settings (operator, once per SS host)

| Setting | Value |
|---|---|
| `PUBLIC_BASE_URL` | the public backend base, e.g. `https://<ss host>/be`. Candidate links are built from it. |
| `PLANNER3D_WORKER_TOKEN_SHA256` | the sha256 of the worker token, computed on the Mac (step 3). SS stores only the hash. |

Both are GitHub Secrets / Variables rendered into `.env` by CI (`DEPLOY.md`); nothing is edited on the server.

## 2. Mint a dev key and add the receiver (SS screens)

Sign in to SS as an Admin of the tenant the CRM belongs to.

1. Services: install **Planner 3D** if it is not installed.
2. **3D Planner > Keys > Create**: name it after the CRM copy (e.g. `CRM test copy`). Copy the
   `fx3_live_…` key from the dialog; it is shown once. Revoke from the row menu when done.
3. **3D Planner > Receivers > Create**: URL `https://<crm copy host>/api/v1/public/planner/events`,
   events **Candidate models ready**. Copy the signing secret (`whsec_…`); it is shown once.
4. In the CRM copy: Settings > Integrations > 3D planner card, save that signing secret (or set
   `PLANNER_WEBHOOK_SECRET`). The CRM refuses unsigned or wrongly signed events with 401.

## 3. Start the worker on the Mac

Keychain items (login keychain, account `planner3d`; `-w` with no value prompts, so nothing lands in
shell history):

```bash
security add-generic-password -a planner3d -s planner3d-worker-token -w     # once
security add-generic-password -a planner3d -s huggingface-read-token -w     # once
# the hash for PLANNER3D_WORKER_TOKEN_SHA256 (step 1), straight from the keychain:
security find-generic-password -a planner3d -s planner3d-worker-token -w | tr -d '\n' | shasum -a 256
```

Run (setup of the venv and TripoSR: `planner3d_worker/README.md`):

```bash
~/planner3d/venv/bin/python -m planner3d_worker --base-url https://<ss host>/be --name mac-mini --engine stub --once     # smoke: box candidates
~/planner3d/venv/bin/python -m planner3d_worker --base-url https://<ss host>/be --name mac-mini --engine triposr --loop # real
```

The worker reads both tokens from the keychain at runtime and never prints them. While it is off,
jobs wait `queued` and nothing fails; at 20 waiting jobs per tenant a new one answers `429 queue_full`.

## 4. Point the CRM copy at SS

| CRM env | Value |
|---|---|
| `PLANNER_SS_URL` | `https://<ss host>/be/api/v1/planner3d` (the client appends `/uploads`, `/models`, `/jobs/{id}`) |
| `PLANNER_SS_API_KEY` | the `fx3_live_…` key from step 2 |

Restart the CRM API and its RQ worker. With `PLANNER_SS_URL` empty the CRM uses its in-process stub
(boxes) instead.

## 5. Check it end to end

1. On a product with dimensions, 3D model tab: pick 1 to 3 photos, start. The CRM shows Processing.
2. SS: the job shows `queued`, then `running` once the Mac claims it.
3. When the worker finishes, SS pushes `model.candidates_ready`; the CRM downloads the candidate GLBs
   through the signed links and shows them for review.

If it stalls:

| Symptom | Look at |
|---|---|
| CRM: "The model service could not be reached" | `PLANNER_SS_URL` / key; SS answers `401 invalid_api_key` (wrong or revoked key), `403 service_not_enabled` (module off or tenant suspended), `429` (budget, `Retry-After`) |
| Job stays `queued` | the worker is off, or its token hash does not match (`401` in the worker log) |
| Job `succeeded` but the CRM stays Processing | the receiver: URL not public https, wrong signing secret (CRM 401), CRM copy unreachable; SS retries 1m, 5m, 30m, 2h, 6h, 24h. The CRM marks a job Failed after 15 minutes |
| CRM fetch fails | `PUBLIC_BASE_URL` is not the public host, or the link expired (1 hour; the CRM reads `GET /jobs/{id}` for a fresh one; links inside a RETRIED event are the ones signed when the event was queued) |

Dev only: with `CELERY_TASK_ALWAYS_EAGER=true` the event is sent inline, so the worker's `finish` call
waits for the receiver (up to 10 seconds per receiver). Production sends it from the Celery worker.
