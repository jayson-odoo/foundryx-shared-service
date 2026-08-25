# 13 - AutoCount ESB (integration spine)

> **UAC:** `13-autocount-esb-acceptance-criteria.md` - read first; it is the contract.
> **Counterpart:** `sorento_crm` → `documentation/plans/autocount/PLAN-autocount-integration.md`
> **Status:** DRAFT

## 1. Why this lives in the shared service

Not because "other products might reuse it." Four concrete reasons, in order of weight:

1. **One whitelisted egress IP, forever.** AutoCount is on-prem; customers grant access by whitelisting
   our IP. Every IP we ask them to whitelist costs an IT ticket and a security review, per customer,
   and again whenever it changes. Centralising means **one IP, whitelisted once, reused by every
   Foundryx product**. Point-to-point in Sorento would mean re-negotiating with every customer for
   every product, forever.
2. **Anti-corruption layer.** The API is a vendor wrapper with inconsistent casing (`Dtlkey` vs
   `DtlKey`), string booleans (`"T"`/`"F"`), two coexisting API generations, and per-line UDF arrays
   that differ per customer. One place absorbs that; consumers never see it.
3. **Per-customer version skew.** Each customer runs their own on-prem wrapper version. Without a
   central adapter this becomes `if customer == "X"` scattered through product business logic.
4. **Credential vault + multi-company.** N customers × M company databases, each with its own
   credentials, watermarks and mappings.

**Consequence to design around:** the ESB must have a **pinned, stable egress IP** that survives
redeploys and blue/green. Treat the IP as a published, versioned contract - changing it is a breaking
change requiring customer coordination.

## 2. Topology

```
AutoCount (on-prem, per customer, per company)
    ▲  HTTPS, we always initiate; customer whitelists our IP
    │  POST /api/{Entity}/Get{Entity}  - reads, LastModifiedFrom/To
    │  POST /api/{Entity}               - writes, requestId/externalId
    │
Foundryx shared service - module `autocount` (schema app_autocount)
    │  hop 1: AutoCount shape → canonical      (mapping config, per company)
    │  staging + approval gate                  (background_jobs.needs_review)
    │  hop 2: canonical → consumer shape        (near-identity for Sorento)
    ▼
Sorento CRM (cloud)   ── lifecycle events ──▶ back to ESB for writes
```

AutoCount **never** calls us - no webhooks exist. Every read is a scheduled pull.

## 3. Decision log

| # | Decision |
|---|---|
| D1 | AutoCount on-prem per customer; Sorento cloud → real network gap |
| D2 | Customer whitelists our **static egress IP**; ESB always initiates |
| D3 | Lives in the shared service (§1) |
| D4 | Reads use native `LastModifiedFrom`/`LastModifiedTo` - present on ~40 endpoints. No direct SQL, no vendor negotiation, no N+1 (lines nest in the header response) |
| D5 | **Field mapping is data**, not code - forced by per-customer UDF arrays |
| D6 | Fetch/write behind a pluggable interface - two API generations coexist |
| D7 | **Two hops**, canonical middle. Matches Sorento's own `SCM_Module_Build_Plan.md:11-21` |
| D8 | AutoCount is system of record for masters; ownership defined **per field** |
| D9 | ESB pushes to Sorento; Sorento pushes events to ESB |
| D10 | Staging + approval gate as a **per-entity mode** (`MANUAL`/`SCHEDULED_REVIEW`/`AUTO`) |
| D11 | Sorento exposes read endpoints too - diffs need current values |
| D12 | PO write in scope; Sorento's "never transmit PO" hard rule is overturned (needs doc update + sign-off) |
| D12a | Trigger event is **per-doc-type config** |
| D12b | Sorento emits a **generic lifecycle event**; the ESB filters |
| **D13** | **Masters: quarantine invalid, import valid. Transactions: strict all-or-nothing per document.** *(revised - supersedes the earlier per-batch all-or-nothing)* |
| D14 | Gate applies to reads only; writes are `PENDING`/`SYNCED`/`FAILED` |
| D15 | No per-record rejection ⇒ no suppression semantics |
| D16 | **Multiple companies per tenant**; company is part of connection, watermark, staging and mapping identity |
| D17 | `uq_connection_tenant_type` needs an `erp` carve-out |
| D18 | Failed batch: hold watermark, **auto-narrow to isolate**, alarm |
| D19 | ESB is multi-company; each consumer takes exactly one, explicitly configured |
| D20 | **Initial load ≠ ongoing delta** - initial is supervised reconciliation |
| D21 | Sync mode per entity; **stock is `AUTO`, never staged** |
| D22 | Unsplittable paging window ⇒ hard failure, never silent truncation |
| D23 | Transaction referencing a quarantined master ⇒ `RETRY`, auto-drains on fix |
| D24 | Quarantine is a first-class, actionable surface with aged-quarantine alerts |

## 4. What the vendor API actually gives us

Verified against `documentation/api/autocount/SL AutoCount API.postman_collection.json` (215 requests,
107 substantive example payloads) and a live demo instance.

**Uniform grammar** - this is what makes config-driven viable:

```
POST /api/{Entity}                    create
POST /api/{Entity}/Get{Entity}        read
POST /api/{Entity}/Update{Entity}     update
POST /api/{Entity}/Cancel{Entity}     cancel
POST /api/{Entity}/Delete{Entity}     delete
```

**Uniform read filter**, on ~40 endpoints:

```json
{ "DocNo": [],                              // or AccNo[] / ItemCode[]
  "RecordCount": 1,
  "DateFrom": "…", "DateTo": "…",           // document date
  "CreatedTimeFrom": "…", "CreatedTimeTo": "…",
  "LastModifiedFrom": "…", "LastModifiedTo": "…" }   // ← delta driver
```

**Uniform response:** `{ "ResultTable": [ … ] }`, header with nested detail array (`DODTL`, etc.),
plus `LastModified` and `LastModifiedUserID` per record - so watermark advance is exact.

### 4a. Verified against the live instance (2026-07-21) - supersedes the collection

The Postman collection is stale and partly wrong. The following was confirmed by direct read-only
probe of the demo instance and **overrides §4 wherever they disagree**.

**Auth - single step, JWT.** `POST /api/Server/Login`, header `AppId`, body `{UserID, Password}`.
There is no `/api/Auth/Login` and **no AppSecret**. The response is a bare array whose object carries
BOTH `Token` (a GUID) and `JWTToken`.

> **Use `JWTToken`, sent as a bare `Authorization: <JWTToken>` header** - no `Bearer` prefix, not
> `X-API-Key`. The `Token` GUID is what the collection stores in `{{token}}` and it is rejected by
> every endpoint with a misleading `HTTP 500 "Stream was not readable."`. This one mistake looks
> exactly like a broken server; it cost a full diagnostic cycle.

**Company is discovered, never selected.** Login returns `DatabaseName` (`AED_VSOFT`) and
`CompanyName`. There is no company parameter anywhere - the server resolves it from the `AppId`
header. So **AppId IS the company selector**, and D16 multi-company means one connection per AppId.

**There is no 401.** An invalid/expired token returns the same `HTTP 500 "Stream was not readable."`
as any other relay fault. Token expiry is not reliably detectable → proactive age-based re-login plus
a single retry on that error (AC-13-03).

**Two failure shapes, neither using HTTP status meaningfully:**
- app-level: `HTTP 200` + `{"Status":"Fail","Message":…,"ResultTable":[]}` - note `ResultTable` is
  **present but empty**, so success must be read from `Status == "Success"`, never from its presence
- relay-level: `HTTP 500` + a .NET exception object (`ClassName`/`Message`/`StackTraceString`)

**`LastModifiedFrom`/`To` genuinely filters** - 11 rows unfiltered → 2 rows for a one-month window →
0 rows for a future window. Delta fetch is viable as designed.

**GRN does return `LastModified`, `LastModifiedUserID`, `CreatedTimeStamp`, `CreatedUserID`** (the
collection examples simply omit them). Watermark advance on GRN is exact; slice 1 stays GRN.

**A malformed filter is silently ignored** - `{"DocNo":"not-an-array"}` returns the whole table with
`Status:"Success"`. Validate filter shape client-side and assert the returned window (AC-13-04a).

**Writes have no vendor idempotency.** `requestId` / `externalSystem` / `externalId` and
`GET /api/requests/{requestId}` **do not exist**. Writes are synchronous, returning the persisted
document with server-assigned `DocKey`/`DocNo`. Idempotency is entirely ours (AC-13-32).

**Known hazards:**

| Hazard | Handling |
|---|---|
| No offset pagination - only `RecordCount` | Page by narrowing the `LastModified` window (§7) |
| Response `RecordCount` marker (`"N of TOTAL"`) is **post-cap** | Never use as a total; `len == CAP` is the only truncation signal |
| Malformed filter silently ignored → full scan | Validate before send; assert returned window |
| Booleans as `"T"`/`"F"`, some real bools | Declarative coercion in mapping |
| Casing inconsistent (`Dtlkey` DO vs `DtlKey` GRN) | Map literally; never assume normalisation |
| GRN detail key is `GRDTL` (not `GRNDTL`) | Per-entity detail key in config |
| Three date formats (`2023/12/01`, `2024/08/05 16:37:34`, `2024-09-15`) | Declarative per-field parsing |
| Numerics inconsistently typed (`2` vs `"10"`) | DTOs accept both |
| `DocNo` mutable (`NewDocNo` exists) | Correlate on `DocKey`; display `DocNo` |
| UDF arrays vary per customer | Data-driven mapping (D5) |
| Dev tunnel URLs in the collection | Never let a tunnel URL reach production config |
| Collection unreliable for AP + PO-update | Do not codegen those from it; re-probe live |

## 5. Reuse - what already exists

Do **not** build these; they are present and load-bearing elsewhere.

| Need | Existing primitive |
|---|---|
| Approval gate | `background_jobs.status = needs_review` - non-terminal, never pruned |
| Resume / progress / abort | `background_jobs.cursor_json`, `progress_*`, cooperative abort |
| Connection + encrypted creds | `connections` (`type` already includes `erp`), `app/secrets.py` Fernet |
| Provider contract | `app/integrations/base.py` `IntegrationProvider` - `fields()` / `test()` |
| Idempotency ledger | `integration_logs` UNIQUE `(tenant_id, provider, external_event_id)` |
| Retryable-missing-reference | `integration_logs.RETRY` - **a declared constant with NO implementation** (see below) |
| Observability | `integration_activity` - `trace_id`, `external_ref`, latency, Developer Logs console. **`ACTIVITY_SOURCES` is a closed tuple - add an `autocount` value or ESB calls won't render** |
| Mapping vocabulary | Import engine `ImportColumn` - `validators`, `transform`, batched `ResolverDef` |
| Scheduling | `compute_next_run_at` (pure), guarded-UPDATE claim, single beat host |
| Module scaffolding | `modules/ideation/` - the current reference (note: `modules/ems/` does not exist) |

**Blocker to clear first (D17):** `uq_connection_tenant_type` is unique `(tenant_id, type)` where
`type != 'payment' AND is_active`. Multi-company needs `erp` carved out too.

**`integration_logs.RETRY` is not reusable machinery.** The constant is defined and exported but has
**zero write sites in service code** - there is no existing re-drive loop. AC-13-25's quarantine-drain
must be **built** in slice 3, not inherited. (Audited 2026-07-21.)

**Two known traps:** the Celery worker boots no FastAPI lifespan, so a handler must **explicitly
re-register** what it needs and the worker module must import handler modules or tasks are silently
discarded - omitting the import line in `app/workflow_engine/worker.py` leaves the job Pending forever
with no error. And plain JSON columns **do not track in-place mutation** - reassign a fresh object.
Cooperative abort is per-handler, not framework-provided: copy the fresh-status-read `_aborted()`
pattern from `app/storage_migration/service.py`.

## 6. Module shape

```
modules/autocount/
  manifest.json              schema app_autocount, alembic_version_autocount, routers, permissions_csv
  db.py                      AutocountBase, SCHEMA = "app_autocount"
  models.py                  §7
  provider.py                IntegrationProvider - fields(), test()
  client.py                  session auth, envelope, retry, re-login
  sources.py                 EntitySource implementations
  sinks.py                   EntitySink implementations
  mapping.py                 mapping engine (hop 1 and hop 2)
  canonical/                 canonical schemas
  sync.py                    job handler: fetch → map → stage → commit
  reconcile.py               initial-load reconciliation
  routers/, services/, alembic/, permissions/permissions.csv
```

### Pluggable seams (D6)

```python
class EntitySource(Protocol):
    """One entity, one company. Returns canonical records changed since the watermark."""
    def fetch_changes(self, since: Watermark) -> tuple[list[CanonicalRecord], Watermark]: ...

class EntitySink(Protocol):
    """One entity, one company. Writes a canonical record out to AutoCount."""
    def write(self, record: CanonicalRecord, *, request_id: str, external_id: str) -> WriteResult: ...
```

Implementations are chosen **per entity, per company, by config**. Everything downstream - mapping,
staging, approval, push, retry, observability - is identical regardless of which is selected.
This is what "cater for every scenario" means concretely: pluggability sits on the axis of
uncertainty (how data is fetched), not on endpoint topology (which is known and fixed).

## 7. Data model (`app_autocount`)

| Table | Purpose |
|---|---|
| `ac_company` | One AutoCount company DB. FK to `connections`. Name, database name, active |
| `ac_entity_config` | Per (company, entity): sync mode, schedule, source impl, record cap, enabled |
| `ac_watermark` | Per (company, entity): `last_modified_at`, `cursor_json`, `last_success_at`, `consecutive_failures` |
| `ac_field_mapping` | Per (company, entity): source path → canonical field, transform, ownership flag |
| `ac_staged_record` | Canonical record awaiting approval. Raw payload, diff, job FK, status |
| `ac_quarantine` | Failed master row: identity, failing field, reason, first-seen, retry count |
| `ac_write_queue` | Outbound doc: consumer id, doc type, status, `request_id`, AutoCount doc no, error, attempts |
| `ac_sync_run` | Per-run audit: window, counts, duration, outcome |

**Every table carries `tenant_id` and `company_id`.** Every query filters both (AC-13-41).

### Watermark advance rules

- Advance **only** on batch success, to the max `LastModified` observed.
- Masters: advance past successfully imported rows even when siblings quarantine (D13).
- Transactions: a failed document holds the watermark for that entity (D18).
- Never advance on an unsplittable window (D22).

### Window paging (D22)

```
fetch(window):
    records = call(LastModifiedFrom=window.start, LastModifiedTo=window.end, RecordCount=CAP)
    if len(records) == CAP:                  # possibly truncated
        if window.can_split():
            return fetch(left) + fetch(right)
        raise UnsplittableWindow(window)     # HARD FAIL - never truncate silently
    return records
```

Real risk at 10k products: a bulk edit stamps thousands of rows with near-identical timestamps.
The hard failure is deliberate - silent partial data is far worse than a stopped sync.

### Failure isolation (D18)

On batch failure, binary-search the window until a single record fails alone, then report record,
field and reason. Watermark stays put. Raise an alert. Combined with the stale-sync monitor
(AC-13-19), a blocked sync is always visible.

## 8. The two hops

**Hop 1 - AutoCount → canonical.** Owns every vendor quirk: `"F"`→`false`, `"2025/11/22"`→date,
8-dp strings→`Decimal`, `DODTL`→`lines`, UDF extraction, casing. Configured per company.

**Hop 2 - canonical → consumer.** Near-identity for Sorento, since canonical is derived from
Sorento's proven shapes (and from `SCM_Module_Build_Plan.md`, which already specifies
`source_system`/`source_ref`).

Why two: the `"F"`→`false` rule is an *AutoCount-is-weird* rule, not an *AutoCount-to-Sorento* rule.
Written once in hop 1, every future consumer inherits it. With a single direct map, each new consumer
re-authors it - that is the N×M growth this avoids. **A mapping engine makes translation
configurable; a canonical model makes it reusable.**

Canonical shapes are **derived from Sorento's existing models**, not designed fresh - designing a
"product-neutral" abstraction from a sample size of one produces something that fits nobody.

## 9. Sync modes and volumes

Observed customer volumes: ~10k products, ≥10k stock rows, ~5k DO/month, ~100 GRN/month.

| Entity | Mode | Frequency | Rationale |
|---|---|---|---|
| Stock | `AUTO` | ≤15 min | 10k rows, changes every transaction - staging is not sensible |
| Product / Supplier / Debtor | `SCHEDULED_REVIEW` | daily | ~10-50 changes/day is reviewable |
| Warehouse / Tax / Terms | `SCHEDULED_REVIEW` | daily | Low churn |
| DO | `AUTO` (after slice 2) | hourly | ~167/day |
| GRN | `SCHEDULED_REVIEW` → `AUTO` | hourly | ~3/day |

**Initial load is a different problem (D20).** 10,000 products cannot be reviewed record-by-record -
a reviewer will rubber-stamp, which manufactures false confidence. Initial load is a **one-time
supervised reconciliation**: summary counts, an exception list of conflicts and failures only,
sampling for spot-checks, then commit. Attention goes to the rows that need it.

## 10. Slices

| Slice | Scope | ACs | Proves |
|---|---|---|---|
| 1 | Provider, session auth, GRN read → canonical → stage → approve → push | 01-15 | Whole pipeline on the lowest-risk entity |
| 2 | DO read, window paging, isolation, alerts, resume, abort | 16-21 | Change detection under volume |
| 3 | Masters, quarantine, reconciliation UI, per-field ownership, stock AUTO | 22-30 | The hard part - overwriting live data |
| 4 | Writes SQ/PR/RFQ/SO, `on_approved`, create-only | 31-35 | Write path + idempotency |
| 5 | PO write behind a per-tenant switch + doc updates | 36-37 | The overturned hard rule, deliberately last |
| 6 | `on_draft_created` + update/cancel mirroring | 38-40 | Lifecycle mirroring, once stable |

**Masters are slice 3, not slice 1**, despite the requirement diagram's ordering. They are the
highest-risk read - they overwrite live production data users depend on. They should land on
machinery already proven by GRN and DO, not be the thing that proves it.

**`on_draft_created` is deferred to slice 6 deliberately.** Push-on-approval is a one-shot write.
Push-on-draft commits us to mirroring the entire lifecycle (update, cancel, and conflict resolution
when AutoCount edits the same document). Until slice 6 exists, that option must be **unselectable in
config** (AC-13-35) - never offer a mode that silently loses edits.

## 11. Security

- Static egress IP is a published contract; document it and treat changes as breaking.
- IP whitelisting is network-level authentication only - credentials and TLS still required.
- Credentials Fernet-encrypted, write-only over the API, never echoed; blank on update = keep.
- Masked payloads in all stored request/response records (`app/integrations/masking.py`).
- Every query tenant- **and** company-scoped; cross-tenant leakage is a critical defect.
- Customer endpoints may be plain HTTP or self-signed - TLS policy is explicit per connection, never
  silently downgraded.
- Write failures must never break the consumer's originating request (AC-13-43).

## 12. Open items

| # | Item | Needed by |
|---|---|---|
| 1 | Confirm AutoCount wrapper version range in the field (skew scope) | Slice 1 |
| 2 | Confirm per-customer whitelist process and who owns the IP contract | Slice 1 |
| 3 | Sign-off owner for overturning the PO hard rule (D12) | Slice 5 |
| 4 | Conflict policy when a document is edited in both systems | Slice 6 |
| 5 | Whether a second consumer product is on the roadmap (validates hop 2's value) | Informational |

## 13. Testing

Backend: provider + auth + re-login; watermark advance/hold; window split and unsplittable failure;
isolation walk; mapping and coercion matrix; per-document atomicity; masters quarantine; RETRY drain;
approval idempotency; tenant/company scoping; resume and cooperative abort (**with a real interleave -
eager mode hides abort bugs**).

E2E: the AC-13-14 journey by real clicks, at 375px and 1280px, on a freshly rebuilt frontend.

A test report keyed to AC ids (PASS/FAIL/DEFERRED) is required before merge.
