# 3D module contract (PLANNER-3D-S0)

Status: contract v0.3, written 20/11/2026 against `main` at `9fe0099c`. No module code exists yet.
v0.2 applied the review of v0.1; v0.3 takes in the C1 lane's draft shape (section 7.2). Section 13 lists
what changed for lanes that read an earlier version.
S1 builds the module to this document; S2, S3, S4 and the CRM slices C1, C3, C4, C5 build against it.
A change to any wire shape here is a change to this file in the same commit (the same rule the
omnichannel guide carries, `documentation/engineering/omnichannel-service.md`).

Words used here:

- **SS**: this repository, the Foundryx Shared Service.
- **CRM**: the consuming system (Sorento CRM first, EcoHub next). It owns the catalogue, prices, leads
  and quotations. SS never stores a product record or a price.
- **Tenant**: one SS tenant per consuming company. A key, a webhook receiver, the caps and the usage
  all belong to one tenant.
- **Planner code**: the opaque code the CRM issues to a salesperson or a dealer stand. SS carries it
  and never interprets it.

Owner rulings this contract rests on:

- **D7**: SS holds the GPU jobs and the planner; the catalogue and prices stay in the CRM and reach
  SS through an integration API, never copied; leads and quotations stay in the CRM.
- **D8**: the GPU worker is host-agnostic behind one endpoint (`GPU_WORKER_URL`), with a CPU stub so
  everything runs with no GPU.
- **D9**: open models on our own GPU by default; a paid API only as a switch per client, off by default.
- Render only after Save. Catalogue products only. The AI never changes a product. Save creates a lead
  (channel `planner`) and never creates or renames a contact.

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
| `staff` | `/planner3d` | session JWT + `require_permission` | SS settings screens (keys, receiver, caps, usage, deliveries) |
| `gateway` | `/api/v1/planner3d` (`"public": true`) | tenant key | CRM server (C5, C3 reads) |
| `planner_public` | `/public/planner3d` (`"public": true`) | none, tenant slug in the path | the hosted planner page (S2, S4) |
| `files` | `/planner3d/files` (`"public": true`) | signed link | anyone holding a result link (section 3.1) |

A `"public": true` router skips the session and module gate in the loader, so each of the three public
routers checks "tenant may sign in and the module is ACTIVE for it" itself, as
`modules/lead_capture/gateway_auth.py:49-53` does.

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
| 403 | `service_not_enabled` | tenant suspended or the module is not ACTIVE for it |
| 403 | `paid_engine_off` | `engine: "paid"` asked for while the tenant's paid switch is off |
| 404 | `not_found` | unknown id, or an id that belongs to another tenant (same answer) |
| 409 | `design_not_saved` | a render asked for a design or revision that is not saved |
| 409 | `idempotency_conflict` | same `Idempotency-Key`, different body |
| 413 | `file_too_large` | upload above the cap |
| 415 | `unsupported_file` | the file's real type (magic bytes) is not allowed |
| 422 | `invalid_request` | a field failed validation; `details` lists the fields as the core handler emits them (`app/api_errors.py`) |
| 429 | `rate_limited` | request budget; carries `Retry-After` |
| 429 | `spend_cap_reached` | the monthly cap is reached; no job is created |
| 429 | `queue_full` | too many jobs already waiting for this tenant |
| 503 | `catalogue_unavailable` | the CRM catalogue API did not answer (public planner only) |

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
| `kind` | `render`, `model` |
| `status` | `queued`, `running`, `succeeded`, `failed`, `cancelled` |
| `engine` | `stub` (CPU stub), `gpu` (open models behind `GPU_WORKER_URL`), `paid` (paid API, per-tenant switch) |
| `error` | `null`, or `{"code", "message"}` with a fixed sentence, never an exception text |
| `usage.paidCost` | `null` unless `engine` is `paid`; then `{"amount": "0.42", "currency": "USD"}` |

The module's own `p3_job` row is the only source of the job object and of usage: it holds the
status, the times, the error and the usage itself. Core `background_jobs` rows are pruned after 30
days and only carry the short work steps (section 4.1), so nothing on the wire reads them.

`error.code` values: `gpu_unavailable`, `worker_failed`, `timeout`, `product_changed` (render only, see 3.4),
`input_unreadable`, `cancelled`.

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
- `uploadIds`: 1 to 6 photos of the one product.
- `dimensionsMm` is required. The model is scaled so its bounding box equals these three values.
- `engine`: `default` (the tenant's default: `gpu`, or `stub` when no worker is configured) or `paid`.
- Answer `202` with the job object, `status: "queued"`. A submit only records the job; a separate tick
  starts it (section 4.1), so the answer is `queued` in every environment, tests included.
- Result: one file, `role: "model"`, GLB, Y up, metres, origin at the centre of the base.

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
- The AI never changes a product. The worker returns the generated image; SS pastes the product pixels
  from the stored `scene` capture back over it wherever the `mask` marks a product, then sets
  `unchanged: true` per product. If the paste-back cannot be done the job fails with `product_changed`;
  a render with an altered product is never delivered.
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
- `GET /jobs?kind=&status=&productCode=&designId=&page=&pageSize=`: newest first, `pageSize` at most 100,
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
| Result files | 30 days after the job finished; the newest model per `productCode` and the newest render per saved design revision are kept until replaced |

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
| `publicDailyRenders` | 20 | renders all visitors of this tenant's planner may start per UTC day |
| `publicDailySaves` | 200 | Saves (so leads) this tenant's planner accepts per UTC day |

Rules:

- A cap is checked when a job is submitted. A job that is already running or waiting is never cut off
  by the cap, so a month can end above it by at most the jobs that were waiting (accepted).
- The public planner has its own budgets (`publicDailyRenders`, `publicDailySaves`, plus per-IP limits,
  section 7.3), so strangers on the public page cannot use up the month and block the CRM's `/models` jobs.
- Stub jobs use 0 GPU seconds and no money, so development and tests never reach a cap.
- With `paidEngineEnabled` off, `engine: "paid"` answers `403 paid_engine_off` and `default` never
  falls back to the paid engine. With no GPU worker configured, `default` is the stub; it is never the paid engine.
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
   - **start**: for each tenant below `maxConcurrentJobs`, take its oldest `queued` job, send it to the
     worker (or run the stub), store `workerJobId`, set `running`;
   - **poll**: for each `running` job, read the worker's status and store progress;
   - **finish**: for each job the worker reports done, create one core `background_jobs` job of type
     `planner3d.finish`. Its handler downloads the outputs, does the paste-back, stores the files,
     writes usage, sets the final status and queues the event.
3. Every step is short (well under a minute) and safe to run twice. A deploy that kills a step loses
   nothing: the `p3_job` row still says where the job is and the next tick carries on, because the
   long wait happens on the GPU worker, not inside an SS process. A `planner3d.finish` job that the
   core orphan sweep fails is simply created again by the next tick (the `p3_job` is still `running`).
4. A job is `running` from the moment it is sent to the worker until `planner3d.finish` ends, and that
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
    "plannerCode": "K7QX2",
    "savedAt": "2026-11-21T02:10:00Z",
    "shareUrl": "https://<ss planner host>/p/sorento/planner?design=dsn_77aa...&ref=K7QX2",
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

- `plannerCode` is the `ref` the page was opened with, or `null`. The CRM decides the lead owner from it.
- `shareUrl` keeps the `ref`, so a design passed on to someone else still opens under the same
  salesperson. The planner code is not a secret (it is printed in the QR).
- `person` is exactly what the customer typed. `mobile` is normalised to E.164 when it parses, else sent as typed.
- `lines` hold catalogue codes and quantities only. There is no price, no name and no free-text line:
  the CRM prices the lead from its own catalogue.
- `consent.text` is the sentence the customer saw, so the CRM stores what was agreed to.

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

### 5.7 `model.ready`

Sent when a model job reaches a final state.

```json
{
  "id": "evt_...", "type": "model.ready", "occurredAt": "2026-11-21T02:20:00Z",
  "data": {
    "jobId": "job_...", "productCode": "ABC-123",
    "status": "succeeded", "engine": "gpu",
    "dimensionsMm": {"length": 600, "width": 450, "height": 850},
    "files": [{"role": "model", "name": "model.glb", "mime": "model/gltf-binary", "size": 184320, "sha256": "...", "url": "...", "expiresAt": "..."}],
    "error": null
  }
}
```

The CRM stores the GLB as the product's model attachment, a person approves it, and C1 then returns
its URL. SS does not decide which model is approved.

---

## 6. GPU worker endpoint and the CPU stub

### 6.1 Configuration

| Variable | Default | Meaning |
|---|---|---|
| `GPU_WORKER_URL` | empty | base URL of the worker, any host. Empty means the CPU stub runs every job. |
| `GPU_WORKER_TOKEN` | empty | bearer token SS sends to the worker |
| `GPU_WORKER_TIMEOUT_SECONDS` | 900 | wall-clock limit for one job on the worker |
| `PLANNER3D_PAID_API_KEY` | empty | key for the paid engine; without it the paid switch cannot be turned on |

These follow the code-runner pattern (`CODE_RUNNER_URL`, `CODE_RUNNER_TOKEN`, `app/config.py:246-247`,
`DEPLOY.md` "Topology"): an operator-set URL and token rendered into `.env` by CI from GitHub
Variables and Secrets. They are never tenant data.

### 6.2 SS to worker protocol (S3 implements the worker side)

SS always calls the worker; the worker never calls SS and needs no SS credentials. This keeps the worker
host-agnostic: it needs one reachable URL and outbound access to fetch inputs.

| Call | Purpose |
|---|---|
| `GET /health` | `{"status": "ok", "engines": {"render": "<pipeline name>", "model": "<pipeline name>"}, "version": "..."}` |
| `POST /v1/jobs` | start a job; answer `202 {"workerJobId": "..."}` |
| `GET /v1/jobs/{workerJobId}` | `{"status": "queued|running|succeeded|failed", "progress": 0-100, "gpuSeconds": 12.5, "outputs": [{"role", "name", "mime", "size", "sha256"}], "error": {"code", "message"}}` |
| `GET /v1/jobs/{workerJobId}/outputs/{name}` | the output bytes |
| `DELETE /v1/jobs/{workerJobId}` | cancel and free the outputs |

`POST /v1/jobs` body:

```json
{
  "jobId": "job_...", "kind": "render",
  "inputs": [
    {"role": "scene", "url": "<signed SS url>", "mime": "image/png"},
    {"role": "depth", "url": "<signed SS url>", "mime": "image/png"},
    {"role": "mask", "url": "<signed SS url>", "mime": "image/png"}
  ],
  "params": {"prompt": "warm evening light", "width": 1536, "height": 1024, "seed": 1234}
}
```

For `kind: "model"` the inputs are `role: "photo"` (1 to 6) and `params` is
`{"dimensionsMm": {"length", "width", "height"}}`.

- All calls carry `Authorization: Bearer <GPU_WORKER_TOKEN>`.
- `jobId` is the worker's idempotency key: a second `POST` with the same `jobId` returns the same `workerJobId`.
- Inputs are signed SS links valid for 1 hour. The worker holds no tenant data after `DELETE`.
- SS polls `GET /v1/jobs/{id}` from the 5 second tick (section 4.1). When the worker reports done, the
  `planner3d.finish` job downloads the outputs, stores them through `storage_for_tenant`, then deletes
  the worker job.
- SS does not trust the worker's own description of an output. Each download is read with a cap (40 MB
  for an image, 100 MB for a GLB), its real type is taken from its first bytes (PNG for a render,
  binary glTF for a model), and its sha256 is computed by SS. Anything else fails the job with
  `worker_failed`.
- Outside development `GPU_WORKER_URL` must be `https`. Outputs are always fetched from that base URL,
  never from a URL the worker names.
- For a render, the worker returns the generated image only. The paste-back of product pixels (section
  3.4) is done by SS, so the "product never changes" rule does not depend on the worker.
- Worker unreachable or 5xx: 3 tries, 10 seconds apart, then the job fails with `gpu_unavailable`.
  Past `GPU_WORKER_TIMEOUT_SECONDS` the job fails with `timeout` and SS sends `DELETE`.

### 6.3 CPU stub

With `GPU_WORKER_URL` empty, the same job handler runs the stub in process instead of calling a worker.
Everything else is the real path: caps, queue, storage, signed links, events.

| Kind | Stub output |
|---|---|
| `model` | a fixture GLB (a plain box) scaled to `dimensionsMm` |
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
https://<ss planner host>/p/<tenant>/planner?ref=<planner code>
```

| Part | Rule |
|---|---|
| `<ss planner host>` | the SS frontend host (`APP_DOMAIN`). The frontend serves at the root and the backend under `/be` on the same host (`DEPLOY.md` "Topology"), so the page calls its API same-origin. |
| `<tenant>` | the SS tenant slug: lowercase kebab, 3 to 63 characters, fixed after creation. The slug is in the path, not the subdomain, as the public forms route does. |
| `ref` | optional planner code, `[A-Za-z0-9_-]{1,64}`. Kept for the visit and sent in `design.saved`. SS never checks it against anything; a wrong or missing code still saves, with `plannerCode: null` when missing. |
| `design` | optional saved design id; opens that design (the share link). |

An unknown tenant, a suspended tenant and a tenant without the module all show the same not-found page
(no tenant enumeration). The page is public, no login, and carries the tenant's branding; it never
shows the word Foundryx (white-label rule).

Frontend route: `service_frontend/app/(public)/p/[tenant]/planner/page.tsx`. The `(public)` group is
invisible in the URL and no `p` segment exists today, so there is no collision.

Two things S2 must build, because today's public pages take the tenant from the host name, not the path
(the public forms page is `/public/forms/[slug]` and its branding comes from the host):

- branding, page title and favicon for this route are resolved from the `<tenant>` path part;
- `/p/:path*` is added to `service_frontend/middleware.ts` with `frame-ancestors 'none'`, so the page
  that collects a name and a mobile number cannot be framed by another site.

C4 builds the salesperson link and QR as exactly this URL from two values: the tenant slug (one CRM
setting) and the user's planner code.

### 7.2 Catalogue (the CRM API from C1)

The browser never calls the CRM and never sees the CRM key. The page calls SS, and SS calls the CRM
server to server:

```
browser  -> GET /be/public/planner3d/<tenant>/catalogue/products?query=&category=&codes=&limit=&offset=
SS       -> GET <crm base url>/api/v1/external/planner/products     header X-API-Key: <key>
SS       -> GET <crm base url>/api/v1/external/planner/categories   header X-API-Key: <key>
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
  fall-back to the platform tenant's connection must NOT be used here: it would show one company's
  catalogue on another company's planner. No connection answers `503 catalogue_unavailable`.
- The base URL is typed in by a tenant admin, so every call to it goes through `app/services/url_guard.py`:
  public `https` only, the address re-checked on every call, redirects not followed.
- What SS forwards to C1, under C1's own names: `query` (part of a name or code), `category` (a category
  code), `codes` (repeatable, exact match, at most 200 per call), `limit` (1 to 200, default 100) and
  `offset`. SS uses `codes` at Save to check that every line is a catalogue product, and the share link
  uses it to load a saved design's products. A code missing from C1's answer is not in this tenant's
  catalogue.
- C1's draft shape (the C1 lane owns it; final after its open questions are answered). SS passes the
  body through unchanged, so the planner page reads C1's snake_case names on these two routes only:
  - products: `{"data": [...], "total", "limit", "offset"}`, each product `code`, `name`,
    `category_code`, `category_name`, `length_mm`, `width_mm`, `height_mm`, `thumbnail_url`, `model_url`,
    `list_price` (decimal string), `currency`. The sizes, both links and the price can be `null`;
    `model_url` is `null` until C5 ships.
  - categories: `{"data": [{"code", "name", "parent_code", "display_order"}]}`.
- `thumbnail_url` and `model_url` are signed links that expire after 1 hour. SS never stores them on a
  design and never caches them; the page asks again when it needs a fresh one.
- C1 sends no `ETag` for now. One CRM key belongs to one CRM company, which matches one key per SS tenant.
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

### 7.3 Public planner routes (`/public/planner3d/{tenant}`)

No key. Own per-IP throttle scope. Tenant from the path slug.

| Route | Purpose |
|---|---|
| `GET /config` | tenant display name, branding, consent sentences, `rendersEnabled` |
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

Each new permission needs a grant sweep for tenants that already exist (`AGENTS.md`, RBAC). The job
handler names `planner3d.jobs.read` as its `read_permission` so the jobs also show in the core Jobs
drawer (`app/jobs/registry.py:41-43`).

---

## 9. Security rules that are part of the contract

- Tenant isolation: every query carries `tenant_id`; an id from another tenant answers 404, and a stored
  id is resolved with the tenant at use time, never with an unscoped lookup.
- Secrets: tenant keys hashed; receiver secrets and the CRM catalogue key Fernet-encrypted; none is
  ever returned after creation or written to a log.
- Uploads: type from magic bytes, capped read, images only; served back only through signed links with
  `Content-Security-Policy: sandbox` and `nosniff`.
- Receiver URLs and the catalogue base URL are tenant input: public `https` only, re-checked before
  every call, redirects not followed (sections 5.1 and 7.2).
- The catalogue connection is resolved for the calling tenant only, never the platform fall-back.
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
| S1 module skeleton | M-L, 3-4 days | L, 4-6 days | Reusable: key service, gateway auth and audit, signed delivery with retry, URL guard, `background_jobs`, storage, signed links (all exist in lead capture, omnichannel and core). Not counted in the split: four staff screens on the Resource shell built mock first, the catalogue connection provider, module Alembic checked on real Postgres, conftest wiring in four places, permission CSV plus grant sweep, storage-key registration, a dedicated worker queue, and a design store (`p3_design`) that S2's Save and the render rule both need. Suggest S1a backend with the stub (3-4 days, unblocks C3 and C5) and S1b staff screens (1-2 days). |
| S2 planner UI | L, 6-8 days | L, 7-9 days | The frontend has no three.js today (`service_frontend/package.json` has `konva` and `react-konva` only), so the port adds the dependency and its bundle. The public route, the catalogue proxy and tenant branding by path slug are new. Browser checks are recorded `agent-browser` runs at 375 and 1280 px; there is no automated browser suite in this repo. The public Save routes (section 7.3) fit S2 better than S1 because their fields come from the approved screens. |
| S3 GPU worker image | L, 4-6 days + test | unchanged | The worker is outside this repo's compose stack by design (the production host has one vCPU and no GPU). Precedents: `service_backend/code_runner/` (own image, URL plus token) and the meetings pilot-host workers. CI does not build a worker image today; add that or build it by hand. |
| S4 render in the planner | M, 2 days | M, 2-3 days | The paste-back, the masks and the "products unchanged" list are SS work in the job handler (section 3.4), not only screens. If S1 ships the paste-back with the stub, S4 stays at 2 days. |

SS total moves from about 17-23 to about 19-26 lane-days plus the test.

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

---

## 12. Open points

None of these blocks S1. Each has a default written into the contract above; a different answer changes
only the named section.

| # | Point | Default in this contract | Owner of the answer |
|---|---|---|---|
| 1 | May stub output reach a real customer while no GPU server exists? | CLOSED by crew ruling 20/11/2026: no. Render is hidden on the public planner until a worker is configured; test tenants get labelled stub output (section 6.3). | closed |
| 2 | Exact fields the customer fills at Save and the consent sentences | name, mobile, email, contact consent (required), marketing consent (optional), from the build split. The acceptance criteria file (AC-1..10) was not readable from this lane. | S2 lane, against the approved screens |
| 3 | Default caps | 1 running job, 20 waiting, 10 GPU hours a month per tenant | ops, once the GPU server is known |
| 4 | Exact response shape of C1 | C1's draft is in section 7.2; final after the C1 lane's own open questions | C1 lane |
| 5 | Paid engine vendor and its cost unit | `paidCost` is `{amount, currency}`; no vendor is named and no paid call is built in S1 | owner, after the side-by-side test |
| 6 | CORS on the file host for the planner host | `codes` is agreed (7.2); CORS still to confirm | C1 lane |
| 8 | What the customer sees for a product that left the catalogue | marked as no longer available, removable, Save blocked until removed (7.2) | owner (customer-visible), S2 lane |
| 7 | Captcha on the public Save | none in v0.2; per-IP and per-tenant limits plus the honeypot | owner, only if the limits prove too weak |

---

## 13. Changes from v0.1

For lanes that started from v0.1 (C1, C3, C6 were sent it):

| Lane | Change |
|---|---|
| C3 | 5.4: create the lead on the first `design.saved` seen for a `designId`, whatever its `revision`; apply an event only when its `revision` is higher than the stored one; full rule list for late and early events. |
| C3 | 5.3: SS sends one `v1` only. The verifier is unchanged. |
| C3, C5 | 5.6 and 3.4: `products[]` carries `productCode` and `unchanged` only, no name. |
| C1 | 7.2: SS needs a `codes` filter; the file host needs CORS for the planner host; SS keeps no cache at all, so every planner page request is one C1 request (size the rate limit for that). |
| C5 | 3.3 and 4.1: a submit always answers `queued`; a job starts within about 5 seconds. `stubOutcome` is gateway only. |
| C4 | no change. |
| C1 | v0.3: section 7.2 now uses C1's own parameter and field names (`query`, `category`, `codes`, `limit`, `offset`; snake_case body); 403 and 429 from C1 also become `catalogue_unavailable`; signed links are never stored. SS still keeps no cache (v0.1 said 5 minutes), so the 600 calls a minute per key is the real ceiling for a tenant's planner traffic. |
| S1 | new 4.1 (dispatcher tick), `files` router and its signature, error envelope on the public prefix, `p3_job` as the only job record, tenant-only catalogue connection with URL guard, public budgets. |
| S2, S4 | 3.4 and 7.3: the page captures `scene`, `depth` and `mask` per view at Save; no free camera; branding from the path; framing forbidden; Render hidden while no GPU worker is configured. |
