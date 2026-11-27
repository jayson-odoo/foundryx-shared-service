# 3D module contract (PLANNER-3D-S0)

Status: contract v0.7, written 20/11/2026, updated 27/11/2026, against `main` at `9fe0099c`. No module
code exists yet. v0.2 applied the review of v0.1; v0.3 takes in the C1 lane's draft shape (section 7.2);
v0.4 takes in the owner's ruling on the CRM key (one key for the whole Sorento CRM product) and C1's
`company` parameter, so the planner path now names a CRM company (section 7.1); v0.5 closes open point
11 (the company code stays in the URL and QR only); v0.6 applies the crew ruling of 26/11/2026 (the
GPU worker pulls its jobs, a model job yields candidates, convert exports). Section 13 lists what changed for lanes that read
an earlier version.
S1 builds the module to this document; S2, S3, S4 and the CRM slices C1, C3, C4, C5 build against it.
A change to any wire shape here is a change to this file in the same commit (the same rule the
omnichannel guide carries, `documentation/engineering/omnichannel-service.md`).

Words used here:

- **SS**: this repository, the Foundryx Shared Service.
- **CRM**: the consuming system (Sorento CRM first, EcoHub next). It owns the catalogue, prices, leads
  and quotations. SS never stores a product record or a price.
- **Tenant**: one SS tenant per consuming system. The whole Sorento CRM product is one tenant, however
  many companies it holds. A key, a webhook receiver, the caps and the usage all belong to one tenant.
- **Company**: a company inside the consuming CRM (Sorento CRM holds several). Its code names the
  planner page (section 7.1), goes to C1 on every catalogue call and comes back on `design.saved`.
- **Planner code**: the opaque code the CRM issues to a salesperson or a dealer stand. SS carries it
  and never interprets it.

Owner rulings this contract rests on:

- **D7**: SS holds the GPU jobs and the planner; the catalogue and prices stay in the CRM and reach
  SS through an integration API, never copied; leads and quotations stay in the CRM.
- **D8**: the GPU worker is host-agnostic: it pulls its jobs from SS (section 6.2, crew ruling 26/11/2026),
  with a CPU stub so everything runs with no GPU.
- **D9**: open models on our own GPU by default; a paid API only as a switch per client, off by default.
- Render only after Save. Catalogue products only. The AI never changes a product. Save creates a lead
  (channel `planner`) and never creates or renames a contact.
- **CRM key (21/11/2026)**: one CRM key for the whole Sorento CRM product, held by the planner in SS.
  SS keeps one key per SS tenant, never one per CRM company (section 7.2).

Sections 1 to 9 are the contract. Section 10 is what the SS repository requires of the module.
Section 11 is the sizing delta and the SS-side risks. Section 12 lists the points still open.

---

## 1. Module identity

| Item | Value | Why |
|---|---|---|
| Module name | `planner3d` | `service_backend/modules/planner3d/`, one folder per Service (`AGENTS.md`) |
| Schema | `app_planner3d` | per-module schema, never `public` |
| Alembic version table | `alembic_version_planner3d` | per-module history |
| Table prefix | `p3_` | sibling style: `lc_` in lead capture, `ac_` in autocount |
| Permission resource prefix | `planner3d.` | module keys must not collide with a core key; `sync_permissions` deletes by module on a global unique key |
| Key scheme | `fx3_live_` + secret | sibling: `fxl_live_` (`modules/lead_capture/services/key_service.py:19`) |
| Webhook header prefix | `X-Planner3d-` | sibling: `X-Lead-Capture-` |

Routers in `manifest.json`:

| Router | Prefix | Auth | Used by |
|---|---|---|---|
| `staff` | `/planner3d` | session JWT + `require_permission` | SS settings screens (keys, receiver, caps, usage, deliveries, companies) |
| `operator` | `/planner3d/platform` (`"public": true`) | session JWT + `require_platform_permission("tenants.manage_modules")`, declared in the router | the platform console: register, change and remove a tenant's company codes (section 8) |
| `gateway` | `/api/v1/planner3d` (`"public": true`) | tenant key | CRM server (C5, C3 reads) |
| `planner_public` | `/public/planner3d` (`"public": true`) | none, company code in the path (section 7.1) | the hosted planner page (S2, S4) |
| `files` | `/planner3d/files` (`"public": true`) | signed link | anyone holding a result link (section 3.1) |

A `"public": true` router skips the session and module gate in the loader (`app/module_loader.py:88`),
so `gateway`, `planner_public` and `files` each check "tenant may sign in and the module is ACTIVE for
it" themselves, as `modules/lead_capture/gateway_auth.py:49-53` does; `planner_public` also checks that
the company is active. The `operator` router is `"public": true` because the loader's gate asks whether
the module is ACTIVE for the CALLER's tenant, and the platform tenant never installs modules. It
declares the platform gate itself (`app/dependencies.py:295`, the existing key in
`app/permissions/platform_permissions.csv`, so no new permission) and acts only on a tenant named in
its path that has the module ACTIVE.

---

## 2. Authentication and errors

### 2.1 Tenant key (gateway)

```
Authorization: Bearer fx3_live_<secret>
```

- One key resolves to exactly one tenant. Nothing in the path, query or body ever chooses the tenant.
- A key is shown once at issue. SS stores a sha256 hash and an 8-character lookup prefix and compares
  with `hmac.compare_digest`. The screens show `fx3_live_****` plus the last four characters.
- A tenant may hold several active keys (rotation: issue the new one, switch the CRM, revoke the old one).
- Check order per request: per-IP throttle (counts 401 only), key, tenant may sign in and module ACTIVE,
  per-key request budget. Every call with a resolved key writes one audit row (tenant, key, method,
  route, status). No payload is stored in the audit.

### 2.2 Error envelope

Every gateway and public-planner error uses the structured envelope from `app/api_errors.py`:

```json
{"error": {"code": "spend_cap_reached", "message": "This month's limit is used up.", "details": {}}}
```

| Status | `code` | When |
|---|---|---|
| 400 | `invalid_request` | malformed JSON or multipart |
| 401 | `invalid_api_key` | missing, malformed, unknown or revoked key |
| 403 | `service_not_enabled` | gateway only: tenant suspended or the module is not ACTIVE for it |
| 403 | `paid_engine_off` | `engine: "paid"` asked for while the tenant's paid switch is off |
| 404 | `not_found` | unknown id, or an id that belongs to another tenant (same answer); on the public planner also an unknown or inactive company code, a suspended tenant, a tenant without the module, and a design saved under another company (section 7.3) |
| 409 | `design_not_saved` | a render asked for a design or revision that is not saved |
| 409 | `idempotency_conflict` | same `Idempotency-Key`, different body |
| 413 | `file_too_large` | upload above the cap |
| 415 | `unsupported_file` | the file's real type (magic bytes) is not allowed |
| 422 | `invalid_request` | a field failed validation; `details` lists the fields as the core handler emits them (`app/api_errors.py`) |
| 429 | `rate_limited` | request budget; carries `Retry-After` |
| 429 | `spend_cap_reached` | the monthly cap is reached; no job is created |
| 429 | `queue_full` | too many jobs already waiting for this tenant |
| 503 | `catalogue_unavailable` | the CRM catalogue API did not answer or refused (public planner only) |

The core handler wraps validation errors only for paths under `/api/v1/`. S1 makes the
`/public/planner3d/` routes answer with the same envelope (validate in the route and raise
`ApiError`), so the planner page never has to read FastAPI's default `{detail}` shape.

Wire style: camelCase fields, UTC times as ISO 8601 with `Z`, ids as opaque strings.

---

## 3. Job API (`/api/v1/planner3d`)

All routes take the tenant key. All ids are tenant-scoped; another tenant's id answers 404.

### 3.1 The job object

```json
{
  "id": "job_9f2c...",
  "kind": "model",
  "status": "succeeded",
  "engine": "stub",
  "createdAt": "2026-11-21T02:10:00Z",
  "startedAt": "2026-11-21T02:10:01Z",
  "finishedAt": "2026-11-21T02:10:03Z",
  "progress": 100,
  "input": {"productCode": "ABC-123", "uploadIds": ["upl_1a..."], "dimensionsMm": {"length": 600, "width": 450, "height": 850}},
  "result": {
    "files": [
      {"role": "model", "name": "model.glb", "mime": "model/gltf-binary", "size": 184320,
       "sha256": "...", "url": "https://<ss host>/be/planner3d/files/<file id>?exp=...&sig=...", "expiresAt": "2026-11-21T03:10:03Z"}
    ]
  },
  "error": null,
  "usage": {"gpuSeconds": 0, "paidCost": null}
}
```

| Field | Values |
|---|---|
| `kind` | `render`, `model`, `convert` (the exports of one approved candidate, 3.3) |
| `status` | `queued`, `running`, `succeeded`, `failed`, `cancelled` |
| `engine` | `stub` (CPU stub), `gpu` (open models on a worker that pulls the job, section 6.2), `paid` (paid API, per-tenant switch) |
| `error` | `null`, or `{"code", "message"}` with a fixed sentence, never an exception text |
| `usage.paidCost` | `null` unless `engine` is `paid`; then `{"amount": "0.42", "currency": "USD"}` |

The module's own `p3_job` row is the only source of the job object and of usage: it holds the
status, the times, the error and the usage itself. Core `background_jobs` rows are pruned after 30
days and only carry the short work steps (section 4.1), so nothing on the wire reads them.

`error.code` values: `gpu_unavailable`, `worker_failed`, `timeout`, `product_changed` (render only, see 3.4),
`input_unreadable`, `cancelled`, `worker_lost` (the worker stopped answering three times, section 6.2).

`usage.gpuSeconds` is a whole number, the worker's figure rounded up.

Result file `url` is a signed, time-limited link (1 hour) that opens without the key, the same design
as the omnichannel signed media link (`modules/omnichannel/security.py:58-82`). A consumer downloads
the file and keeps its own copy (C5 attaches the GLB to the product; C3 copies the render onto the
lead). Reading `GET /jobs/{id}` again returns a fresh link while the file is retained (section 3.8).

The link is served by the `files` router. Its signature is HMAC-SHA256 over `p3file:<file id>:<exp>`;
the `p3file:` prefix keeps it apart from the omnichannel media signature, which uses the same server
secret. The route checks the expiry first, compares in constant time, and answers 404 when the
file's tenant is suspended or no longer has the module.

### 3.2 `POST /uploads`

Multipart, one part named `file`. Stores an input image for a later job.

- Allowed real types: PNG, JPEG, WebP. The type is taken from the bytes (`app/uploads.py`), the
  declared content type is ignored. Cap 20 MB, read with a capped read.
- Answer `201`: `{"id": "upl_...", "mime": "image/jpeg", "size": 734003, "sha256": "...", "expiresAt": "..."}`.
- An upload that no job references is removed after 24 hours.

### 3.3 `POST /models` (product photo to 3D model, used by C5)

```json
{
  "productCode": "ABC-123",
  "uploadIds": ["upl_1a..."],
  "dimensionsMm": {"length": 600, "width": 450, "height": 850},
  "engine": "default"
}
```

- `productCode` is the CRM's code, opaque to SS, 1 to 100 characters. It is echoed on the job and the event.
- `company` is optional: the CRM company code the product belongs to, opaque to SS, echoed on the job
  and on `model.ready`, and part of the retention key (3.8). C5 sends it whenever product codes can
  repeat across companies (open point 10); SS never checks it against the company registry.
- `uploadIds`: 1 to 3 photos of the one product (v0.7: the worker and the CRM picker take at most 3).
- `dimensionsMm` is required. The model is scaled so its bounding box equals these three values.
- `engine`: `default` (the tenant's default: `gpu`, or `stub` when no worker is configured, section 6.1) or `paid`.
- Answer `202` with the job object, `status: "queued"`. A submit only records the job; a separate tick
  starts it (section 4.1), so the answer is `queued` in every environment, tests included.
- Result, two steps (crew ruling 26/11/2026). The model job finishes with 2 or 3 candidates:
  `candidate-1.glb` to `candidate-3.glb`, each `role: "candidate"`, GLB, Y up, metres, origin at the centre
  of the base, scaled to `dimensionsMm`. SS sends `model.candidates_ready` (5.7). A person approves one
  candidate (in SS, or through the staff route the module offers); SS never picks one. Approval queues a
  `convert` job (kind `convert`, `sourceJobId` = the model job) whose result is `model.glb` (`role: "model"`)
  plus `model.gltf`, `model.obj`, `model.mtl`, `model.fbx` and `model.stl` (each `role: "export"`). The
  convert job's own `model.ready` (5.7) is the one a CRM stores from. `kind` therefore also takes `convert`
  on a job object.

### 3.4 `POST /renders` (render of a saved design)

```json
{
  "designId": "dsn_77aa...",
  "revision": 3,
  "view": "hero",
  "prompt": "warm evening light",
  "engine": "default"
}
```

- Render only after Save: `designId` and `revision` must name a saved revision, else `409 design_not_saved`.
- `view` names one of the views captured at Save: `hero`, `top` or `current` (the view the customer was
  looking at when they saved). A view that the saved revision does not hold answers `422`. There is no
  free camera: SS has no 3D renderer, so it can only render a view the planner page captured.
- **Where the pictures come from.** At Save the planner page draws each view three times in the browser
  and sends the three PNGs with the Save (section 7.3): `scene` (the plain 3D picture), `depth` (the
  depth picture that guides the model) and `mask` (one flat colour per product line, so every product
  pixel is known). SS stores them with the revision. A render job uses only these stored captures.
- `prompt` is optional free text for mood and finish, at most 300 characters. It never adds, removes or
  replaces a product.
- Result files: `role: "render"` (the final image, PNG, 1536 px on the long side), `role: "before"`
  (the plain scene image the render was guided by), and `result.products`, the list behind the
  "products unchanged" screen:

```json
"products": [{"productCode": "ABC-123", "unchanged": true}]
```

  The list carries codes only; the page reads names from the live catalogue.
- The AI never changes a product. The worker composites the product pixels from the `scene` capture back
  over the generated image wherever the `mask` marks a product, and returns `render.png` and `diff.json`
  (its own product diff). SS does not trust that: it re-runs `product_diff` on the stored `render.png`
  against the `scene` and `mask` it sent, and any non-zero product diff fails the job with
  `product_changed`. A render with an altered product is never delivered; `unchanged: true` per product is
  set only from SS's own result (crew ruling 26/11/2026).
- Staff render jobs (section 6.2): `scene`, `mask` and `depth` are PNGs of at most 4096 px per side, else `422` at submit.
- Checks SS makes on the captures at Save (a failure answers `422`): the three PNGs of a view have the
  same size, at most 1536 px on the long side; every colour in the `mask` belongs to a line of the
  saved design; every line that is in the view has pixels in the `mask`.
- Limit of this rule, stated openly: the captures come from the customer's own browser. A person who
  tampers with their browser can only spoil their own render; they cannot affect another design, the
  lead's product lines (those are checked against the catalogue, section 9) or any price.
- The hosted planner starts a render through its own public route (section 7.3), which calls the same
  service. The gateway route exists so a CRM can ask for a render of a saved design as well.

### 3.5 `GET /jobs/{id}` and `GET /jobs`

- `GET /jobs/{id}`: the job object.
- `GET /jobs?kind=&status=&productCode=&company=&designId=&page=&pageSize=`: newest first, `pageSize` at most 100,
  answer `{"data": [...], "total": 0, "page": 1, "pageSize": 25}`.
- `POST /jobs/{id}/cancel`: a `queued` job is cancelled at once; a `running` job stops at its next
  checkpoint. Answer is the job object. Cancelling a finished job answers the job unchanged.

### 3.6 `GET /usage`

`GET /usage?from=2026-11-01&to=2026-11-30` (dates are UTC days, both inclusive, default the current month):

```json
{
  "from": "2026-11-01", "to": "2026-11-30",
  "totals": {"jobs": 42, "succeeded": 39, "failed": 3, "gpuSeconds": 1260, "paidCost": {"amount": "0.00", "currency": "USD"}},
  "byKind": {"render": {"jobs": 30, "gpuSeconds": 900}, "model": {"jobs": 12, "gpuSeconds": 360}},
  "byEngine": {"stub": {"jobs": 0}, "gpu": {"jobs": 42}, "paid": {"jobs": 0}},
  "limits": {"maxConcurrentJobs": 1, "maxQueuedJobs": 20, "monthlyGpuSeconds": 36000, "monthlyPaidCap": null, "paidEngineEnabled": false},
  "remaining": {"gpuSeconds": 34740, "paidCap": null}
}
```

A value that does not exist is `null`, never `0` (no paid cap set, paid engine off).

### 3.7 Idempotency on submit

`POST /models` and `POST /renders` accept an `Idempotency-Key` header (1 to 128 characters). Within 24
hours the same key and the same body return the first job (`200` instead of `202`, same job id); the
same key with a different body answers `409 idempotency_conflict`. A consumer that retries after a
timeout must reuse its key so it is never charged twice.

### 3.8 Retention

| What | Kept |
|---|---|
| Unreferenced uploads | 24 hours |
| Job rows and usage (`p3_job`) | 13 months |
| Result files | 30 days after the job finished; the newest model per `company` and `productCode` (an absent `company` counts as its own value) and the newest render per saved design revision are kept until replaced |

---

## 4. Tenant settings, caps and concurrency

One `p3_settings` row per tenant, edited by SS staff on the module's settings screen:

| Setting | Default | Meaning |
|---|---|---|
| `maxConcurrentJobs` | 1 | jobs of this tenant running at once; the rest wait as `queued` |
| `maxQueuedJobs` | 20 | waiting jobs; one more answers `429 queue_full` |
| `monthlyGpuSeconds` | 36000 (10 hours) | GPU time per UTC calendar month; at the cap a submit answers `429 spend_cap_reached` |
| `paidEngineEnabled` | `false` | D9: the paid API is a per-client switch and is OFF by default |
| `monthlyPaidCap` | not set | money cap for the paid engine; required before `paidEngineEnabled` can be turned on |
| `publicRendersPerDesign` | 3 | renders one saved design may start from the hosted planner |
| `publicDailyRenders` | 20 | renders all visitors of this tenant's planner may start per UTC day, all its companies together |
| `publicDailySaves` | 200 | Saves (so leads) this tenant's planner accepts per UTC day, all its companies together |

Rules:

- A cap is checked when a job is submitted. A job that is already running or waiting is never cut off
  by the cap, so a month can end above it by at most the jobs that were waiting (accepted).
- The public planner has its own budgets (`publicDailyRenders`, `publicDailySaves`, plus per-IP limits,
  section 7.3), so strangers on the public page cannot use up the month and block the CRM's `/models` jobs.
- Stub jobs use 0 GPU seconds and no money, so development and tests never reach a cap.
- With `paidEngineEnabled` off, `engine: "paid"` answers `403 paid_engine_off` and `default` never
  falls back to the paid engine. With no worker configured (6.1), `default` is the stub; it is never the paid engine.
- Per-key request budget: 600 requests per 5 minutes, the lead-capture defaults
  (`app/config.py:146-147`), with its own throttle scope.
- Across tenants the queue is fair: the next job is taken from the tenant that has waited longest among
  those below their `maxConcurrentJobs`.

### 4.1 How a job moves (the dispatcher S1 builds)

Core `background_jobs` starts a job the moment it is created and has no waiting line, no per-tenant
limit and no way to pick up a job again after a deploy. So the waiting line lives in the module:

1. A submit writes a `p3_job` row with status `queued` and returns. Nothing else happens in the request.
2. One beat task, `planner3d.tick`, runs every 5 seconds. Each run does three things, each claimed with
   a guarded `UPDATE` so two runs never take the same row:
   - **start**: for each tenant below `maxConcurrentJobs`, run its oldest `queued` job on the stub when
     the stub is the engine (6.3). On the pull path SS does not start anything: the worker claims the job
     (6.2) and the claim sets `running`; the per-tenant limit is applied inside the claim;
   - **poll**: for each `running` job, requeue it when its lease ran out (6.2);
   - **finish**: for each job the worker reports done (its `finish` call, 6.2), create one core `background_jobs` job of type
     `planner3d.finish`. Its handler checks the outputs, re-runs `product_diff` for a render, stores the files,
     writes usage, sets the final status and queues the event.
3. Every step is short (well under a minute) and safe to run twice. A deploy that kills a step loses
   nothing: the `p3_job` row still says where the job is and the next tick carries on, because the
   long wait happens on the GPU worker, not inside an SS process; jobs simply wait as `queued` while the worker is off. A `planner3d.finish` job that the
   core orphan sweep fails is simply created again by the next tick (the `p3_job` is still `running`).
4. A job is `running` from the moment it is claimed (or started on the stub) until `planner3d.finish` ends, and that
   whole span counts against `maxConcurrentJobs`.
5. With `CELERY_TASK_ALWAYS_EAGER=true` (dev and tests) there is no beat; tests call the tick function
   directly, as the workflow scheduler tests do. A consumer must still accept that an event can reach
   it before it has read the answer to its own submit.

---

## 5. Webhook events (SS to the tenant's receiver)

### 5.1 Receiver

A tenant registers up to 5 receivers (URL plus the events it wants). Each receiver has its own signing
secret, shown once. The URL must be public `https`; it is re-checked before every attempt and the
connection opens only to an address that passed the check (`app/services/url_guard.py`,
`app/services/webhook_post.py`, the same functions the lead-capture and omnichannel pushes use).

For Sorento CRM the receiver is C3: `POST <crm>/api/v1/public/planner/events`.

In v0.2 receivers are managed only on the SS staff screen (section 8): add, remove, test push, and
"send again" for a failed delivery. There is no gateway route for them yet.

### 5.2 Delivery

```
POST <receiver url>
Content-Type: application/json
User-Agent: Foundryx-Planner3d/1.0
X-Planner3d-Event: design.saved
X-Planner3d-Delivery: <delivery id>
X-Planner3d-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, t + "." + raw body)>
```

Body envelope, the same four fields as the lead-capture push
(`modules/lead_capture/services/delivery_service.py:174-182`):

```json
{"id": "<event id>", "type": "design.saved", "occurredAt": "2026-11-21T02:10:00Z", "data": {}}
```

### 5.3 Signature

Identical to the lead-capture push; only the header name differs. The SS signer is
`modules/lead_capture/services/delivery_service.py:76-79`; the CRM verifier is
`sorento_crm_backend/app/services/lead_capture_signature.py` (`verify_signature`), which C3 can call
unchanged with the `X-Planner3d-Signature` header value.

1. `t` is unix seconds as ASCII digits. The signed string uses the `t` text exactly as sent.
2. The signed bytes are `t`, a dot, then the RAW request body bytes (never re-serialised JSON).
3. `v1` is lowercase hex HMAC-SHA256 of those bytes with the receiver's secret (UTF-8).
4. The receiver rejects when `t` is more than 300 seconds from its clock, and compares in constant time.
5. SS sends exactly one `v1`. A receiver should still accept a header with several `v1=` entries and
   pass when any one matches (the CRM verifier does), so secret rotation can be added later without a
   receiver change. To change a secret today: add a second receiver with the same URL, let the CRM
   accept both secrets, then remove the old receiver.

Signature failure is answered `401` by the receiver; SS treats it as a failed attempt and retries.

### 5.4 Answer, retries and idempotency

- Answer any `2xx` once the event is committed. Anything else, or no answer inside 10 seconds, is a
  failed attempt. Redirects are not followed.
- Retries: 1 minute, 5 minutes, 30 minutes, 2 hours, 6 hours, 24 hours after the previous attempt, then
  the delivery is `FAILED` (7 attempts, the lead-capture ladder, `delivery_service.py:58`). A failed
  delivery can be sent again from the SS deliveries screen (staff route
  `POST /planner3d/deliveries/{id}/redeliver`): same body, new `t` and signature.
- The envelope `id` is the event id. It is the same on every retry, on a redelivery, and on every
  receiver of the same event. `X-Planner3d-Delivery` names one receiver's delivery.
- **The receiver is idempotent on the envelope `id`.** A second arrival of an `id` already committed
  answers `2xx` and changes nothing. C3 stores the event id with a unique constraint.
- Order is not guaranteed: a retry can land after a newer event. The receiver therefore follows these
  rules, keyed on `designId` and `revision`, never on arrival order:
  - `design.saved` for a `designId` it has never seen: create the lead, whatever the `revision`.
  - `design.saved` with a `revision` higher than the one stored: update the same lead's design.
  - `design.saved` with a `revision` equal or lower: answer `2xx`, change nothing.
  - `render.ready` for a `designId` it has never seen, or a `revision` higher than the one stored:
    answer `409`. SS retries on the ladder, by which time the `design.saved` has landed.
  - `render.ready` for the stored `revision`: attach the render. For a lower `revision`: answer `2xx`,
    change nothing (the customer has saved again since).
  - `model.ready` is keyed on `jobId`; an unknown `jobId` answers `2xx` and is ignored.
- Bodies hold personal data. SS stores each body encrypted (Fernet) and decrypts only to sign and
  send, and never logs a body, a secret or a receiver URL.

### 5.5 `design.saved`

Sent each time a customer saves in the hosted planner (the first Save and every later Save of the same
design; `revision` goes up by one). The receiver creates the lead the first time it sees the
`designId` and updates the same lead on a higher `revision` (rules in 5.4). It never creates or
renames a contact.

```json
{
  "id": "evt_...", "type": "design.saved", "occurredAt": "2026-11-21T02:10:00Z",
  "data": {
    "designId": "dsn_77aa...",
    "revision": 1,
    "tenant": "sorento",
    "company": "CO1",
    "plannerCode": "K7QX2",
    "savedAt": "2026-11-21T02:10:00Z",
    "shareUrl": "https://<ss planner host>/p/CO1/planner?design=dsn_77aa...&ref=K7QX2",
    "person": {"name": "Test Person", "mobile": "+60120000000", "email": "person@example.com"},
    "consent": {"contact": true, "marketing": false, "text": "<the consent sentence shown>", "acceptedAt": "2026-11-21T02:09:58Z"},
    "room": {"shape": "rectangle", "widthMm": 2400, "lengthMm": 1800, "heightMm": 2600},
    "lines": [
      {"productCode": "ABC-123", "quantity": 1, "zone": "vanity"},
      {"productCode": "DEF-456", "quantity": 2, "zone": "shower"}
    ]
  }
}
```

- `tenant` is the SS tenant slug, the same for every company of the Sorento CRM product. `company` is
  the CRM company code from the page's path (section 7.1), spelt as registered in SS (`CO1` here is a
  made-up code); the CRM files the lead under that company and matches the code trimmed and in any
  letter case, as C1 does.
- `plannerCode` is the `ref` the page was opened with, or `null`. The CRM decides the lead owner from it.
- `shareUrl` keeps the `ref`, so a design passed on to someone else still opens under the same
  salesperson. The planner code is not a secret (it is printed in the QR).
- `person` is exactly what the customer typed. `mobile` is normalised to E.164 when it parses, else sent as typed.
- `lines` hold catalogue codes and quantities only. There is no price, no name and no free-text line:
  the CRM prices the lead from its own catalogue.
- `consent.text` is the sentence the customer saw, so the CRM stores what was agreed to. It names the
  company that will contact the customer (section 7.1).

### 5.6 `render.ready`

Sent when a render job reaches a final state. The receiver checks `status`.

```json
{
  "id": "evt_...", "type": "render.ready", "occurredAt": "2026-11-21T02:14:00Z",
  "data": {
    "jobId": "job_...", "designId": "dsn_77aa...", "revision": 1, "plannerCode": "K7QX2",
    "status": "succeeded", "engine": "gpu",
    "files": [
      {"role": "render", "name": "render.png", "mime": "image/png", "size": 2100345, "sha256": "...", "url": "...", "expiresAt": "..."},
      {"role": "before", "name": "before.png", "mime": "image/png", "size": 1400221, "sha256": "...", "url": "...", "expiresAt": "..."}
    ],
    "products": [{"productCode": "ABC-123", "unchanged": true}],
    "error": null
  }
}
```

With `status: "failed"` or `"cancelled"`, `files` is empty and `error` is `{"code", "message"}`. The
receiver downloads `files[].url` inside the hour and keeps its own copy; after that it reads
`GET /jobs/{jobId}` for a fresh link.

### 5.7 `model.candidates_ready` and `model.ready`

Two events, one per step of a model (3.3; crew ruling 26/11/2026).

`model.candidates_ready` is sent when a `model` job reaches a final state. On success `files` lists the 2
or 3 candidates, role `candidate`; the receiver shows them to a person, who approves one.

```json
{
  "id": "evt_...", "type": "model.candidates_ready", "occurredAt": "2026-11-21T02:20:00Z",
  "data": {
    "jobId": "job_...", "productCode": "ABC-123", "company": null,
    "status": "succeeded", "engine": "gpu",
    "dimensionsMm": {"length": 600, "width": 450, "height": 850},
    "files": [
      {"role": "candidate", "name": "candidate-1.glb", "mime": "model/gltf-binary", "size": 184320, "sha256": "...", "url": "...", "expiresAt": "..."},
      {"role": "candidate", "name": "candidate-2.glb", "mime": "model/gltf-binary", "size": 190112, "sha256": "...", "url": "...", "expiresAt": "..."}
    ],
    "error": null
  }
}
```

`model.ready` is sent when the `convert` job queued by an approval reaches a final state. `jobId` is the
convert job's id; `sourceJobId` names the model job and `approvedCandidate` the candidate chosen.

```json
{
  "id": "evt_...", "type": "model.ready", "occurredAt": "2026-11-21T02:25:00Z",
  "data": {
    "jobId": "job_...", "sourceJobId": "job_...", "approvedCandidate": "candidate-2.glb",
    "productCode": "ABC-123", "company": null,
    "status": "succeeded", "engine": "gpu",
    "dimensionsMm": {"length": 600, "width": 450, "height": 850},
    "files": [
      {"role": "model", "name": "model.glb", "mime": "model/gltf-binary", "size": 190112, "sha256": "...", "url": "...", "expiresAt": "..."},
      {"role": "export", "name": "model.gltf", "mime": "model/gltf+json", "size": 1200, "sha256": "...", "url": "...", "expiresAt": "..."},
      {"role": "export", "name": "model.obj", "mime": "text/plain", "size": 5000, "sha256": "...", "url": "...", "expiresAt": "..."},
      {"role": "export", "name": "model.mtl", "mime": "text/plain", "size": 300, "sha256": "...", "url": "...", "expiresAt": "..."},
      {"role": "export", "name": "model.fbx", "mime": "application/octet-stream", "size": 90000, "sha256": "...", "url": "...", "expiresAt": "..."},
      {"role": "export", "name": "model.stl", "mime": "model/stl", "size": 40000, "sha256": "...", "url": "...", "expiresAt": "..."}
    ],
    "error": null
  }
}
```

On success `files` lists all six files (`model.glb` is the one with `role: "model"`, the rest `role: "export"`).
With `status: "failed"` or `"cancelled"`, `files` is empty and `error` is `{"code", "message"}`. Both events
are keyed on `jobId` (5.4): an unknown `jobId` answers `2xx` and is ignored. The CRM stores `model.glb` as
the product's model attachment (and may keep the exports); because a person already approved the candidate,
C1 may return the URL once `model.ready` has landed. SS does not decide which candidate is approved.

---

## 6. GPU worker endpoint and the CPU stub

### 6.1 Configuration

Transport is PULL (crew ruling 26/11/2026). The worker calls SS over the tailnet; SS never calls the
worker, so the worker host needs no inbound port and SS needs no worker URL.

| Variable | Default | Meaning |
|---|---|---|
| `PLANNER3D_WORKER_TOKEN_SHA256` | empty | sha256 (hex) of the worker's bearer token. SS stores only the hash. Empty means NO worker is configured: the CPU stub runs every job in process (6.3) and every worker call answers 401. |
| `planner3d_lease_minutes` | 10 | a `running` job with no heartbeat for this long is requeued (6.2) |
| `PLANNER3D_PAID_API_KEY` | empty | key for the paid engine; without it the paid switch cannot be turned on |

`GPU_WORKER_URL` and `GPU_WORKER_TOKEN` no longer exist; `GPU_WORKER_TIMEOUT_SECONDS` is replaced by the
lease. "No worker configured" now means only that `PLANNER3D_WORKER_TOKEN_SHA256` is unset. A worker that
is configured but off or slow is NOT the stub trigger: no claim inside the lease window changes nothing,
and the jobs stay `queued` until the worker comes back. The plaintext token lives only on the worker host
(its login keychain). The hash is operator config rendered into `.env` by CI from a secret, like
`CODE_RUNNER_TOKEN` (`app/config.py:246-247`, `DEPLOY.md` "Topology"). It is never tenant data.

### 6.2 Worker pull API (S3 implements both sides)

Router `worker`, prefix `/planner3d/worker`, `"public": true`. Every call carries
`Authorization: Bearer <token>` and `X-Planner3d-Worker: <worker name>`. SS hashes the token and compares
it with `PLANNER3D_WORKER_TOKEN_SHA256` in constant time; a missing or wrong token, or an unset hash, answers
`401`. The worker name identifies who holds a job. One job runs on a worker at a time.

| Call | Purpose |
|---|---|
| `POST /planner3d/worker/claim` | body `{"kinds": ["model","render","convert"]}`. Answer `200 {"jobId", "kind", "params", "inputs": [{"role", "name", "mime", "size", "sha256"}]}`, or `204` when nothing waits. Takes the oldest `queued` job of an accepted kind across all tenants (per-tenant fairness and the queue caps of section 4 are S1 scope), with `FOR UPDATE SKIP LOCKED` and a guarded `UPDATE`; sets `running`, the worker name and `claimed_at`. |
| `GET /planner3d/worker/jobs/{id}/inputs/{name}` | the input bytes. `404` unless the job is `running` and held by this worker name. |
| `POST /planner3d/worker/jobs/{id}/heartbeat` | body `{"progress": 0-100}`; the worker sends it about every 15 seconds. `200`, or `409 {"detail": {"code": "cancelled", "message": "..."}}` (the house error envelope) when the job was cancelled (the worker stops). |
| `PUT /planner3d/worker/jobs/{id}/outputs/{name}?role=<role>` | raw body. `201 {"name", "size", "sha256"}`. |
| `POST /planner3d/worker/jobs/{id}/finish` | body `{"status": "succeeded"\|"failed", "error": {"code", "message"}, "gpuSeconds", "peakRssMb"}`. Answer: the job. |

Inputs and params by kind: `render` has inputs `scene.png`, `mask.png`, `depth.png` and params
`{"prompt", "seed"}`; `model` has inputs `photo-N.<png|jpg|webp>` (role `photo`) and params
`{"dimensionsMm": {"length", "width", "height"}}`; `convert` has the input `model.glb` (role `model`, a copy
of the approved candidate).

Outputs allowed per kind (any other name answers `422`):

| Kind | Output names |
|---|---|
| `model` | `candidate-N.glb` with N 1 to 3, and optionally `candidate-N.json` |
| `render` | `render.png` (at most 4096 px per side, else `422` on upload) and `diff.json` |
| `convert` | `model.glb`, `model.gltf`, `model.obj`, `model.mtl`, `model.fbx`, `model.stl` |

`finish` with `succeeded` needs: for `model`, 2 or 3 candidate GLBs; for `convert`, all six files; for
`render`, `render.png`, after which SS re-runs `product_diff` (3.4).

- **SS does not trust the worker's description of an output.** Each upload is read with a cap (GLB and
  export files 100 MB, PNG 40 MB, JSON 1 MB), its real type is taken from its first bytes and must match
  the name, and its sha256 is computed by SS. A mismatch answers `422` and stores nothing.
- **Lease and requeue.** On every claim and every tick, a `running` job with no heartbeat for
  `planner3d_lease_minutes` is requeued (`attempts` + 1, back to `queued`). At 3 attempts it fails with
  `worker_lost`. A cancelled job is never requeued.
- **Queueing.** While the worker is off, jobs stay `queued`; nothing times out into the stub. The caps and
  the per-tenant queue of section 4 still apply at submit.
- The worker holds no tenant data after a job: it deletes its working files after `finish`.
- Outside development the worker reaches SS over `https` (or the tailnet address). SS never fetches from a
  URL the worker names.
- For a render the worker composites the product pixels and returns `render.png` and `diff.json`; SS
  re-checks (3.4), so the "product never changes" rule does not depend on the worker.

### 6.3 CPU stub

With `PLANNER3D_WORKER_TOKEN_SHA256` unset (no worker configured, 6.1), the same job handler runs the stub
in process; no worker ever claims anything. The stub is the in-process engine for development and for a
tenant with no worker, not a fallback for a slow or absent worker. Everything else is the real path: caps, queue, storage, signed links, events.

| Kind | Stub output |
|---|---|
| `model` | two fixture candidate GLBs (`candidate-1.glb`, `candidate-2.glb`, plain boxes) scaled to `dimensionsMm`; the `convert` job the approval queues also runs on the stub and writes the six files |
| `render` | `before` is the plain scene image as received; `render` is a fixture image of the same size with the product pixels pasted back, so the paste-back step and the "products unchanged" list are exercised |

- Stub jobs finish inside 2 seconds, set `engine: "stub"` on the job and on the event, and use 0 GPU seconds.
- A request field `stubOutcome` (`"failed"` or `"timeout"`) is accepted on the gateway only, and only
  when the engine is the stub, so C3, C5 and S4 can test their failure handling. With a real worker the
  field is ignored. The public planner routes never accept it.
- Stub output is labelled wherever a person sees it: the SS Jobs screen shows the engine, and the
  planner page shows "Sample picture" on a stub render.
- **A customer never sees a stub render (crew ruling, 20/11/2026).** While no GPU worker is
  configured, `GET /config` answers `rendersEnabled: false` and the public planner hides Render; Save,
  the share link and the lead work as normal. A tenant marked as a test tenant (a staff-only setting,
  `stubRendersOnPublicPage`, default off) keeps Render on the page with the stub, for S4 and for demos.
  Model jobs on the gateway always run on the stub when no worker is configured.
- The stub is deterministic: the same input gives the same bytes and the same sha256.

---

## 7. Planner page and its public API

### 7.1 URL

```
https://<ss planner host>/p/<company>/planner?ref=<planner code>
```

| Part | Rule |
|---|---|
| `<ss planner host>` | the SS frontend host (`APP_DOMAIN`). The frontend serves at the root and the backend under `/be` on the same host (`DEPLOY.md` "Topology"), so the page calls its API same-origin. |
| `<company>` | the CRM company code the link belongs to, as the CRM spells it (C1 note of 21/11/2026). SS stores each registered code as the CRM spells it plus a lookup form (trimmed, lower case). The lookup form is unique across SS (one unique index) and the path is matched on that form only, so the code alone finds both the tenant and the company. Only a platform operator registers, changes or removes a code (section 8); a code is fixed once registered, and a removed code stays reserved to its tenant until an operator releases it. Codes are 1 to 32 characters of letters, digits, `-` and `_`; a CRM code outside that is raised with C1, never renamed. |
| `ref` | optional planner code, `[A-Za-z0-9_-]{1,64}`. Kept for the visit and sent in `design.saved`. SS never checks it against anything; a wrong or missing code still saves, with `plannerCode: null` when missing. |
| `design` | optional saved design id; opens that design (the share link). A design opens only under the company it was saved under; under another company's code it is not found. |

Why a company and not a tenant in the path: the whole Sorento CRM product is one SS tenant (owner ruling,
21/11/2026), and production SS serves one domain with no tenant subdomains (`DEPLOY.md` "Topology"),
so the one path segment names the company and SS finds the tenant from it.

An unknown company code, a company not active for the planner, a suspended tenant and a tenant without
the module all show the same not-found page (no enumeration). The page is public, no login, and carries
the tenant's logo and colours with the company's own display name and consent sentence, each falling
back to the tenant's when the company leaves it empty (crew ruling, 21/11/2026). The consent sentence
names the company that will contact the customer. The page never shows the word Foundryx (white-label rule).

The company code is only ever inside the URL and the QR (crew ruling, 21/11/2026). The homeowner never
sees it as on-screen text: no label, heading, title, message or error names the company by its code;
the page names it by its display name, which falls back to the tenant's and so always exists. A share
link shown as a link still carries the code inside its URL; that is the only place it appears.

Frontend route: `service_frontend/app/(public)/p/[company]/planner/page.tsx`. The `(public)` group is
invisible in the URL and no `p` segment exists today, so there is no collision.

Two things S2 must build, because today's public pages take the tenant from the host name, not the path
(the public forms page is `/public/forms/[slug]` and its branding comes from the host):

- branding, page title and favicon for this route are resolved from the `<company>` path part (the
  company, then its tenant);
- `/p/:path*` is added to `service_frontend/middleware.ts` with `frame-ancestors 'none'`, so the page
  that collects a name and a mobile number cannot be framed by another site.

C4 builds the salesperson link and QR as exactly this URL from three values: the SS planner host (one
CRM setting), the code of the salesperson's company and the user's planner code.

### 7.2 Catalogue (the CRM API from C1)

The browser never calls the CRM and never sees the CRM key. The page calls SS, and SS calls the CRM
server to server:

```
browser  -> GET /be/public/planner3d/<company>/catalogue/products?query=&category=&codes=&limit=&offset=
SS       -> GET <crm base url>/api/v1/external/planner/products?company=<code>&...     header X-API-Key: <key>
SS       -> GET <crm base url>/api/v1/external/planner/categories?company=<code>       header X-API-Key: <key>
```

- The CRM base URL and key are one SS connection per tenant (`connections` table, key Fernet-encrypted
  and write-only), provider `planner_catalogue`, connection type `catalogue`, registered by this module.
  It appears on Settings > Integrations with a Test button like every other connection. The autocount
  module's `sorento` provider is a different connection with a different key and is not reused: one key
  per integration, as that provider's own note requires (`modules/autocount/sorento_provider.py:16-19`).
- Never copied: SS has no product or price table and keeps no cache of a CRM answer, in Redis or
  anywhere else. Each page request is one CRM request. If C1 later sends `ETag` or
  `Cache-Control`, SS forwards them unchanged so the customer's own browser can avoid repeat downloads. A saved design stores product
  codes and positions only.
- The connection is read for this tenant only (`get_by_type(tenant_id, "catalogue")`). The usual
  fall-back to the platform tenant's connection must NOT be used here: it would show one tenant's
  catalogue on another tenant's planner. No connection answers `503 catalogue_unavailable`.
- The base URL is typed in by a tenant admin, so every call to it goes through `app/services/url_guard.py`:
  public `https` only, the address re-checked on every call, redirects not followed.
- What SS sends to C1, under C1's own names: `company` (on both calls, always: the code of the page's
  company, spelt as registered in SS, even when the key reads only one company), `query` (part of a
  name or code), `category` (one or more category codes, comma-separated), `codes` (repeatable, exact
  match, at most 200 per call), `limit` (1 to 200, default 100) and `offset`. SS uses `codes` at Save to
  check that every line is a product of that company's catalogue, and the share link uses it to load a
  saved design's products. A code missing from C1's answer is not in that company's catalogue.
- C1's shape (the C1 lane owns it: its v0.2 notes plus the company change of 21/11/2026). SS passes the
  body through unchanged, so the planner page reads C1's snake_case names on these two routes only:
  - products: `{"data": [...], "total", "limit", "offset"}`, each product `code`, `name`,
    `category_code`, `category_name`, `length_mm`, `width_mm`, `height_mm`, `thumbnail_url`, `model_url`,
    `list_price` (decimal string), `currency`. The sizes, both links and the price can be `null`;
    `model_url` is `null` until C5 ships. C1 returns only products whose category has a product type.
  - categories: `{"data": [{"code", "name", "parent_code", "display_order"}]}`; `name` is the readable
    product type.
- `thumbnail_url` and `model_url` are signed links that expire after 1 hour. SS never stores them on a
  design and never caches them; the page asks again when it needs a fresh one.
- C1 sends no `ETag` for now.
- One CRM key covers the whole Sorento CRM product, not one company (owner ruling, 21/11/2026). SS holds
  it as the single `planner_catalogue` connection of that product's SS tenant: one key per SS tenant,
  never one per CRM company. C1's rate limit on that key is therefore the ceiling for all of the
  tenant's planner traffic, every company together. CRM-side setup (C1): the planner integration's
  act-as user is granted every company the planner serves and holds a role that can view products; it
  is not an admin.
- The page downloads thumbnails and GLB files straight from the URLs C1 returns. C1's file host must
  allow cross-origin reads (CORS) from the planner host, or three.js cannot load the models.
- A `list_price` of `null` or 0 shows as no price. A product with no `model_url` is shown as a plain box
  of its three sizes; a product with a size missing cannot be placed and is not offered.
- A product can leave the catalogue after a design was saved. When a Save holds a code C1 no longer
  returns, the Save answers `422` with `details.unavailableCodes`, and the page marks those products as
  no longer available so the customer can remove them and save (the wording is S2's, see section 12).
  Opening a share link never fails for this reason: the missing product is shown as unavailable.
- CRM down, slow (over 8 seconds) or answering 401, 403 or 429: the page gets `503 catalogue_unavailable` and shows
  an error with Try again. SS has no older copy to fall back to. If the CRM is down at Save, the Save
  answers `503 catalogue_unavailable`, nothing is stored, and the page keeps the design on screen so
  the customer can press Save again.
- C1's 403 with `detail.code` `planner_company_unresolved` (the company is unknown or inactive in the
  CRM, the key is not granted it, or `company` is missing while the key reads several companies) is
  mapped the same way, to `503 catalogue_unavailable`. A customer cannot fix it, so the connection's
  Test button calls `/categories` once for each active registered company and names every company C1
  refuses; that is where staff see it.

### 7.3 Public planner routes (`/public/planner3d/{company}`)

No key. Own per-IP throttle scope. The company code in the path gives the tenant and the company (7.1).
An unknown or inactive company code, a suspended tenant and a tenant without the module answer the
identical `404 not_found` on every route below, before any tenant budget is counted (the per-IP limit
still counts them). Every design id below is checked against the tenant and the company: a design saved
under another company answers the same `404`.

| Route | Purpose |
|---|---|
| `GET /config` | the company's display name and consent sentences (the tenant's when the company leaves them empty), the tenant's logo and colours, `rendersEnabled` |
| `GET /catalogue/products`, `GET /catalogue/categories` | section 7.2 |
| `POST /designs` | Save (body below). Answer `{designId, revision, editToken, shareUrl}`. Queues `design.saved`. |
| `PUT /designs/{id}` | Save again; needs the `editToken`; `revision` goes up; queues `design.saved` |
| `GET /designs/{id}` | the saved scene for the share link. Never returns `person` or `consent`. |
| `POST /designs/{id}/renders` | start a render of the saved revision (S4); needs the `editToken`; limited by `publicRendersPerDesign` |
| `GET /designs/{id}/renders/{jobId}` | status and files of that render; needs the `editToken` |

`POST /designs` and `PUT /designs/{id}` are multipart: one JSON part `payload` and the capture PNGs.

```json
{
  "ref": "K7QX2",
  "person": {"name": "Test Person", "mobile": "+60120000000", "email": "person@example.com"},
  "consent": {"contact": true, "marketing": false},
  "room": {"shape": "rectangle", "widthMm": 2400, "lengthMm": 1800, "heightMm": 2600},
  "lines": [{"lineId": "l1", "productCode": "ABC-123", "quantity": 1, "zone": "vanity"}],
  "scene": {},
  "views": [{"name": "hero", "maskColours": {"l1": "#ff0000"}}]
}
```

- File parts are named `capture:<view>:scene`, `capture:<view>:depth`, `capture:<view>:mask`, PNG only,
  at most 5 MB each, at most three views (`hero`, `top`, `current`). `hero` is required.
- `scene` is the planner's own scene document (positions, rotations, finishes); S2 owns its shape and SS
  stores it as is, capped at 512 KB. It holds no price and no product name.
- `POST /designs/{id}/renders` body: `{"view": "hero", "prompt": "..."}`. A public caller can send only
  these two fields; `engine` and `stubOutcome` are not accepted here, and the paid engine is never used
  for a public render.
- `designId` is the only thing the share link needs, so it carries at least 128 bits of randomness.
- `editToken` is a random secret (at least 128 bits) returned once at the first Save and kept by the
  page in the browser. It is sent as the header `X-Planner3d-Edit-Token`, stored only as a hash, and
  stays valid as long as the design exists.
  The share link carries no token: it opens the design read-only, and saving from it makes a new design.
- Save requires the contact consent to be ticked; without it the answer is `422`.
- Limits on this unauthenticated surface: Save at most 10 per IP per hour and `publicDailySaves` per
  tenant per day; render at most 5 per IP per hour, `publicRendersPerDesign` per design and
  `publicDailyRenders` per tenant per day. Over a limit answers `429 rate_limited`.
- Save carries the hidden honeypot field used by the public forms. A filled honeypot stores nothing and
  sends no event, and answers `201` with a made-up `designId`, `editToken` and `shareUrl` of the normal
  shape; any later call with them answers `404` like any unknown design.
- There is no captcha in v0.2. If the limits above prove too weak, a captcha is the next step and is a
  customer-visible change (crew-ask first).

---

## 8. Staff screens in SS (for S1)

One "3D Planner" entry under the Services menu, tagged `module: "planner3d"` and the read permission,
in all three menu arrays. Built on the Resource shell and the design language
(`docs/reference/design-language.md`):

| Screen | Permission | Content |
|---|---|---|
| Jobs | `planner3d.jobs.read` | list of jobs: kind, status, engine, product code or design, created, duration; row opens the job |
| Keys | `planner3d.keys.manage` | issue (shown once), name, last used, revoke |
| Receivers and deliveries | `planner3d.webhooks.manage` | receivers, events, test push, delivery history, send again |
| Limits and usage | `planner3d.settings.manage` | section 4 settings and the month's usage |
| Companies | `planner3d.settings.manage` | the company codes an operator registered for this tenant (7.1). Tenant staff set each company's active flag, display name and consent sentence; an empty name or sentence falls back to the tenant's, and the consent sentence names the company that will contact the customer. Codes cannot be added, changed or removed here. |

One operator screen, the module's own page in the platform console menu (`MenuItem.platformOnly` plus
the platform key `tenants.manage_modules`; the module adds no tab to the core tenant page), through the
`operator` router (section 1): pick a tenant, then register, change or remove its company codes. The
refusal of a code that another tenant already holds is shown there only, so a tenant never learns
which codes other tenants hold.

Each new permission needs a grant sweep for tenants that already exist (`AGENTS.md`, RBAC). The job
handler names `planner3d.jobs.read` as its `read_permission` so the jobs also show in the core Jobs
drawer (`app/jobs/registry.py:41-43`).

---

## 9. Security rules that are part of the contract

- Tenant isolation: every query carries `tenant_id` (the one exception is the company lookup below); an id from another tenant answers 404, and a stored
  id is resolved with the tenant at use time, never with an unscoped lookup.
- Secrets: tenant keys hashed; receiver secrets and the CRM catalogue key Fernet-encrypted; none is
  ever returned after creation or written to a log.
- Uploads: type from magic bytes, capped read, images only; served back only through signed links with
  `Content-Security-Policy: sandbox` and `nosniff`.
- Receiver URLs and the catalogue base URL are tenant input: public `https` only, re-checked before
  every call, redirects not followed (sections 5.1 and 7.2).
- The catalogue connection is resolved for the calling tenant only, never the platform fall-back.
- A company code resolves to exactly one tenant and one company. That lookup is the one query in the
  module that carries no `tenant_id`, because it is how the public planner finds the tenant: it reads
  the unique lookup form only (7.1), and everything after it is scoped to the tenant it returns.
- Catalogue calls carry the page's company only, and a design opens, saves again and renders only
  under the company it was saved under, because its catalogue check and its lead belong to that
  company. Share links always carry the right code, so only a hand-edited link meets this refusal.
- Only a platform operator registers, changes or removes a company code (section 8), so one tenant's
  admin can never take over another tenant's printed links and QR codes.
- The public planner API takes no key and so trusts nothing from the browser: prices are never accepted
  from the page, product codes are checked against the CRM catalogue at Save, and a code the catalogue
  does not return fails the Save with `422`.
- No paid API call happens unless the tenant's switch is on and its money cap is set (D9).

---

## 10. What the SS repository requires of the module

Read on `main` at `9fe0099c`. Each line is something S1 or S2 must follow; the reviewer checks them.

**Stack.** Backend FastAPI + SQLAlchemy + Pydantic v2 on Postgres, Redis and Celery
(`service_backend/`). Frontend Next.js 15 App Router, React 19, Tailwind 4 (`service_frontend/`).
`AGENTS.md` is the index, `PRINCIPLES.md` governs, `documentation/engineering/` holds the per-engine rules.

**Module layout.** `service_backend/modules/planner3d/` with `manifest.json`, `bootstrap.py`
(`install`, `install_tenant`, `update_tenant`, `uninstall_tenant`, `register_engine_entities`), `db.py`
(own declarative base and schema), `models.py`, `schemas.py`, `routers/`, `services/`,
`permissions/permissions.csv`, `alembic/`. Lead capture is the closest sibling and the template
(`modules/lead_capture/`). Layering is Router, Service, Repository; no query in a router.

**Tests.** A new module schema must be wired into `service_backend/tests/conftest.py` in four places
(the lead-capture schema appears at lines 177, 334, 652 and 763). The suite runs on in-memory SQLite
with `create_all`, so a migration is never exercised by pytest: run the module migration on a real
Postgres before calling S1 done.

**Auth and tenancy.** Staff routes use `get_current_user` and `require_permission`. The tenant comes from
the JWT, never from input. Gateway keys repeat the lead-capture key service (cross-module table reads
are not allowed; the repeat is known debt BL-SS-210).

**Queue.** Every new async job uses the core `background_jobs` table with a registered handler
(`app/jobs/registry.py:62`), not a new job table. Here that is the `planner3d.finish` step; the
module's `p3_job` row is the 3D job's own record and waiting line (section 4.1), because core starts a
job at creation and never re-dispatches one. The handler stamps `JobService.heartbeat` at every
checkpoint and declares `heartbeats=True`: a deploy stops the old colour after a 30 second drain, and
the orphan sweep fails a silent `running` job after 15 minutes and does not start it again
(`documentation/engineering/storage-and-background-jobs.md`, job liveness). Dev and tests run jobs
inline (`CELERY_TASK_ALWAYS_EAGER=true`), so a cancel that does not stop a job is invisible to the
suite: each step re-reads the `p3_job` status before it writes.

**Scheduler.** The 5 second `planner3d.tick`, delivery retries and retention run from the one beat
schedule in `app/workflow_engine/worker.py`, as `lead_capture.deliveries_due` does. Exactly one beat
process runs.

**Storage.** Files go through `storage_for_tenant(db, tenant_id)`; rows store the storage key, never a
URL (presigned links expire). Every `*_key` column is declared under `storage_locations` in the
manifest, or the storage drift test fails CI.

**Webhooks out.** Reuse `app/services/webhook_post.py` and `app/services/url_guard.py`; do not write a
second sender.

**Frontend.** UI component, hook, `services/<x>-service.{ts,mock.ts,real.ts}`, `lib/api-client`; a
component never fetches. Lists and forms use the Resource shell; no `<style>` tags and no raw CSS.
Public pages live under `app/(public)/`. Frontend-first: screens are built on a mock service, then the
mock is swapped for the real one, and a slice that still serves a mock is not done.

**Deploy.** One host, Caddy in front, blue/green for the API and the frontend, Celery workers recreated
in place (`DEPLOY.md` "Topology"). Config is GitHub Secrets and Variables rendered into `.env` by CI;
nothing is edited on the server. `NEXT_PUBLIC_*` values are baked at build time. CI runs six gates on
every PR (convention lint, backend and frontend build, pytest, vitest, one alembic head per module).

---

## 11. Sizing delta for S1 to S4 and SS-side risks

### 11.1 Sizing against the build split

| Slice | Build split | After reading SS | Why |
|---|---|---|---|
| S1 module skeleton | M-L, 3-4 days | L, 5-7 days | Reusable: key service, gateway auth and audit, signed delivery with retry, URL guard, `background_jobs`, storage, signed links (all exist in lead capture, omnichannel and core). Not counted in the split: five staff screens on the Resource shell built mock first, the company registry with its operator route and console screen (v0.4, about one day with the Companies screen), the catalogue connection provider, module Alembic checked on real Postgres, conftest wiring in four places, permission CSV plus grant sweep, storage-key registration, a dedicated worker queue, and a design store (`p3_design`) that S2's Save and the render rule both need. Suggest S1a backend with the stub (3.5-4.5 days, unblocks C3 and C5) and S1b staff and operator screens (1.5-2.5 days). |
| S2 planner UI | L, 6-8 days | L, 7-9 days | The frontend has no three.js today (`service_frontend/package.json` has `konva` and `react-konva` only), so the port adds the dependency and its bundle. The public route, the catalogue proxy and branding by the company code in the path are new. Browser checks are recorded `agent-browser` runs at 375 and 1280 px; there is no automated browser suite in this repo. The public Save routes (section 7.3) fit S2 better than S1 because their fields come from the approved screens. |
| S3 GPU worker image | L, 4-6 days + test | unchanged | The worker is outside this repo's compose stack by design (the production host has one vCPU and no GPU). Precedents: `service_backend/code_runner/` (own image, URL plus token) and the meetings pilot-host workers. CI does not build a worker image today; add that or build it by hand. |
| S4 render in the planner | M, 2 days | M, 2-3 days | The paste-back, the masks and the "products unchanged" list are SS work in the job handler (section 3.4), not only screens. If S1 ships the paste-back with the stub, S4 stays at 2 days. |

SS total moves from about 17-23 to about 20-27 lane-days plus the test.

### 11.2 SS-side risks

1. **One small production host.** The API, the frontend, Postgres, Redis, four workers and beat share a
   one-vCPU machine. A stuck `jobs.run` once starved every scheduled task for 8 hours (`DEPLOY.md`,
   `worker_jobs`). The `planner3d.finish` step needs its own queue (`queue="planner3d"`) and worker and a
   task time limit. A new worker service is three changes, not one: the service in `docker-compose.yml`,
   its name in the deploy's recreate list, and a per-queue liveness ping (`DEPLOY.md`, `worker_jobs`).
   The paste-back of a 1536 px image is the one CPU step; measure it on the host.
2. **Deploys interrupt long jobs.** Blue/green drains for 30 seconds and core never restarts a job it
   swept. That is why the wait is on the GPU worker and SS only runs short steps from a tick
   (section 4.1). The cost is a dispatcher S1 has to write and test; it is the largest new piece in S1.
3. **Migrations are invisible to the test suite.** A broken module migration passes CI and fails the
   deploy. S1 runs it on real Postgres and records the result.
4. **Full pytest is slow and has a timing-sensitive test.** The suite is about 14,800 tests and 14
   minutes in CI. On this PR one unrelated AutoCount test failed on wall-clock timing
   (`tests/test_autocount_write_back_transfer_values.py:123`, a 0.2 second budget). Lanes should expect
   an occasional red run that is not theirs.
5. **Public, unauthenticated surface.** The planner page saves personal data with no login. It needs its
   own throttle scope, the honeypot, consent stored with its text, and a security review before S2 merges.
6. **Catalogue dependency.** S2 cannot show real products until C1 is live and a key is issued. Until
   then S2 runs on a mock catalogue service behind the service layer, and the swap to C1 is part of S2's
   done gate.
7. **Signed links expire.** A receiver that does not download inside the hour must read the job again.
   C3 and C5 must copy the file, not store the link.
8. **Duplicated key and delivery code.** The module rule against cross-module table reads means the key
   service and delivery tables are repeated once more (omnichannel, autocount and lead capture each
   have their own already). Moving them to core is the better fix but is
   larger than S1; it is logged debt (BL-SS-210), not part of this build.
9. **Frontend container is read-only.** Only `/tmp` (64 MB) and the Next cache are writable
   (`DEPLOY.md` "Frontend container"). The planner must not write files server-side.
10. **Embedding.** The page is served top-level. If a tenant later wants it inside an iframe on its own
    site, that needs a frame-ancestors rule in `service_frontend/middleware.ts` and a public CORS prefix
    (`register_public_cors_prefix`); neither is in this contract. v0.2 forbids framing outright (7.1).
11. **Company codes are one namespace across SS.** The planner path holds only the company code (7.1),
    so a later consuming system whose company code another tenant already holds cannot register it.
    That needs a contract change (crew-ask first), never a workaround such as a renamed code the CRM
    does not know.

---

## 12. Open points

None of these blocks S1. Each has a default written into the contract above; a different answer changes
only the named section.

| # | Point | Default in this contract | Owner of the answer |
|---|---|---|---|
| 1 | May stub output reach a real customer while no GPU server exists? | CLOSED by crew ruling 20/11/2026: no. Render is hidden on the public planner until a worker is configured; test tenants get labelled stub output (section 6.3). | closed |
| 2 | Exact fields the customer fills at Save and the default consent sentences | name, mobile, email, contact consent (required), marketing consent (optional), from the build split; each company can replace the consent text (point 9). The acceptance criteria file (AC-1..10) was not readable from this lane. | S2 lane, against the approved screens |
| 3 | Default caps, and whether the public daily budgets stay shared by a tenant's companies | 1 running job, 20 waiting, 10 GPU hours a month per tenant; `publicDailySaves` and `publicDailyRenders` are shared by all of a tenant's companies, so one busy company can use up the day for the others | ops for the numbers, once the GPU server is known; owner for a budget per company (customer-visible), only if sharing proves a problem |
| 4 | Exact response shape of C1 | C1's shape is in section 7.2 (its v0.2 notes plus the company change of 21/11/2026); the C1 lane says when it is final | C1 lane |
| 5 | Paid engine vendor and its cost unit | `paidCost` is `{amount, currency}`; no vendor is named and no paid call is built in S1 | owner, after the side-by-side test |
| 6 | CORS on the file host for the planner host | `codes` is agreed (7.2); CORS still to confirm | C1 lane |
| 7 | Captcha on the public Save | none in v0.2; per-IP and per-tenant limits plus the honeypot | owner, only if the limits prove too weak |
| 8 | What the customer sees for a product that left the catalogue | CLOSED by crew ruling (a) 20/11/2026: it stays in the room marked as no longer available, the customer removes it, and Save is blocked until then (7.2). S2 writes the wording. | closed |
| 9 | Name and consent sentence a customer sees on a company's planner page, now that one SS tenant holds several companies | CLOSED by crew ruling (a) 21/11/2026: each company has its own display name and consent sentence (Companies screen, section 8), falling back to the tenant's when empty; logo and colours stay the tenant's; the consent sentence names the company that will contact the customer. | closed |
| 10 | Are CRM product codes unique across companies? | not assumed: `company` is optional on `POST /models` and `model.ready` and is part of the model retention key (3.3, 3.8) | C1 and C5 lanes |
| 11 | The customer's link and QR now show the CRM company code (`/p/<company code>/planner`) where v0.3 showed the SS tenant slug | CLOSED by crew ruling (a) 21/11/2026: the company code, as C1 reads the link and C4 builds it, in the URL and QR only and never as on-screen text to the homeowner (7.1). The owner can change it later. | closed |

---

## 13. Changes from earlier versions

For lanes that started from an earlier version (C1, C3, C6 were sent v0.1):

| Lane | Change |
|---|---|
| C3 | v0.2, 5.4: create the lead on the first `design.saved` seen for a `designId`, whatever its `revision`; apply an event only when its `revision` is higher than the stored one; full rule list for late and early events. |
| C3 | v0.2, 5.3: SS sends one `v1` only. The verifier is unchanged. |
| C3, C5 | v0.2, 5.6 and 3.4: `products[]` carries `productCode` and `unchanged` only, no name. |
| C1 | v0.2, 7.2: SS needs a `codes` filter; the file host needs CORS for the planner host; SS keeps no cache at all, so every planner page request is one C1 request (size the rate limit for that). |
| C5 | v0.2, 3.3 and 4.1: a submit always answers `queued`; a job starts within about 5 seconds. `stubOutcome` is gateway only. |
| C4 | v0.2: no change. |
| S1 | v0.2: new 4.1 (dispatcher tick), `files` router and its signature, error envelope on the public prefix, `p3_job` as the only job record, tenant-only catalogue connection with URL guard, public budgets. |
| S2, S4 | v0.2, 3.4 and 7.3: the page captures `scene`, `depth` and `mask` per view at Save; no free camera; branding from the path; framing forbidden; Render hidden while no GPU worker is configured. |
| C1 | v0.3: section 7.2 now uses C1's own parameter and field names (`query`, `category`, `codes`, `limit`, `offset`; snake_case body); 403 and 429 from C1 also become `catalogue_unavailable`; signed links are never stored. SS still keeps no cache (v0.1 said 5 minutes), so the 600 calls a minute per key is the real ceiling for a tenant's planner traffic. |
| C1 | v0.4 (owner, 21/11/2026: one CRM key for the whole Sorento CRM product): SS holds one key per SS tenant, never one per company, so C1's limit on that key covers every company's planner traffic; SS sends `company=<code>` on both calls, always; `category` may hold several codes, comma-separated; `planner_company_unresolved` becomes `503 catalogue_unavailable`, and the connection Test names each active company C1 refuses (7.2). Company codes must be 1 to 32 letters, digits, `-` or `_` (7.1); open point 10 asks whether product codes repeat across companies. |
| C3 | v0.4: `design.saved` gains `data.company`, the CRM company code the design was saved under; file the lead under that company, matching the code trimmed and in any letter case. `data.tenant` is the same for every company. `consent.text` names the company that will contact the customer (5.5). |
| C4 | v0.4: the link is `/p/<company code>/planner?ref=<planner code>`, C1's reading: the SS planner host (one CRM setting), the code of the salesperson's company and the planner code (7.1; open point 11). |
| C5 | v0.4: optional `company` on `POST /models`, echoed on the job and `model.ready`, filter `company` on `GET /jobs`; send it if product codes can repeat across companies (open point 10). |
| S1 | v0.4: one SS tenant per consuming system; the company registry behind the planner path (lookup form unique across SS, the one query without `tenant_id`); codes registered only by a platform operator through a new `operator` router on the existing key `tenants.manage_modules`; the tenant's Companies screen edits active, name and consent only (1, 7.1, 8, 9). |
| S2 | v0.4: the route is `app/(public)/p/[company]/planner/page.tsx`; config, branding and the catalogue resolve from the company; every bad code, suspended tenant or missing module answers the same `404`; a design opens only under its own company; the company's own name and consent sentence, falling back to the tenant's (crew ruling (a), 21/11/2026). Open point 8 is closed (crew ruling (a), 20/11/2026); the behaviour in 7.2 is unchanged. |
| C4, S2 | v0.5 (crew ruling (a) on open point 11, 21/11/2026): the company code stays in the link and QR. It is never on-screen text to the homeowner: the planner page names the company by its display name only (7.1). |
| S1, S3 | v0.6 (crew ruling 26/11/2026): transport is PULL. Section 6.1 replaces `GPU_WORKER_URL`, `GPU_WORKER_TOKEN` and `GPU_WORKER_TIMEOUT_SECONDS` with `PLANNER3D_WORKER_TOKEN_SHA256` (SS stores the hash only) and a lease (`planner3d_lease_minutes`, default 10). Section 6.2 replaces the push table with the worker pull API (`claim`, `inputs`, `heartbeat`, `outputs`, `finish` under `/planner3d/worker`, bearer token plus `X-Planner3d-Worker`), stale-lease requeue, `worker_lost` after 3 attempts, jobs queue while the worker is off. Section 6.3: the stub is the in-process engine only while the hash is unset; a worker that is off is not a stub trigger. Section 4.1: no SS-side start or poll on the pull path; the tick requeues stale leases and finishes. SS-side caps, sniffing and its own sha256 stay. |
| C3, S4 | v0.6, 3.4: the worker composites and returns `render.png` and `diff.json`; SS re-runs `product_diff` on the stored PNG and fails `product_changed` on any non-zero product diff. The wire (`render.ready`) is unchanged. |
| C5 | v0.6, 3.3 and 5.7: a model job yields 2 or 3 `candidate-N.glb` (role `candidate`) and sends the NEW event `model.candidates_ready`; a person approves one; approval queues a `convert` job (new `kind: "convert"`, `sourceJobId`, `approvedCandidate`). `model.ready` now fires for the convert result only, with `model.glb` (role `model`) plus `model.gltf`, `model.obj`, `model.mtl`, `model.fbx`, `model.stl` (role `export`). A receiver that stored the single GLB from `model.ready` keeps working; it now gets `jobId` of the convert job and the extra `sourceJobId`, `approvedCandidate` fields. |
| C5, S1 | v0.7 (lane PLANNER-3D-S1, crew answers 27/11/2026): S1 ships the gateway subset the CRM uses: `POST /uploads`, `POST /models`, `GET /jobs/{id}`, the `files` signed links, tenant keys, webhook receivers and the `model.candidates_ready` / `model.ready` push. 3.3 `uploadIds` is 1 to 3 (was 1 to 6). The job object also carries `sourceJobId` and `approvedCandidate` (null on a model job). On a model job `result.files` lists only the candidate GLBs (the worker's `candidate-N.json` reports stay internal). With no worker configured jobs wait `queued`; the CPU stub (6.3), `POST /renders`, `GET /jobs`, cancel on the gateway, `/usage`, the monthly GPU cap and the paid engine are later slices. Limits shipped: 600 requests per 5 minutes per key, 20 failed keys per IP per 15 minutes, 20 waiting jobs per tenant (`429 queue_full`), uploads 20 MB, PNG / JPEG / WebP by their bytes. |
