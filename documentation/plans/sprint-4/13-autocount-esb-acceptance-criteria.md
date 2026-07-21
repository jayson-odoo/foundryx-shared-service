# 13 — AutoCount ESB (integration spine) — User Acceptance Criteria

> **Status:** DRAFT — contract for `documentation/plans/sprint-4/13-autocount-esb.md`
> **Companion repo:** `sorento_crm` → `documentation/plans/autocount/autocount-integration-acceptance-criteria.md`
> **Source of decisions:** grill session 2026-07-21 (24 decisions, reproduced in the plan's Decision Log)

## Scope

A new **`autocount` module** in the FoundryX shared service that syncs data between customer-hosted
AutoCount installations and FoundryX consumer products (first consumer: Sorento CRM).

**Read** (AutoCount → FoundryX → consumer): Product, Stock, Warehouse, Creditor/Supplier, Debtor/Customer,
Payment Terms, Tax, Delivery Order (+lines), Goods Received Note (+lines).
**Write** (consumer → FoundryX → AutoCount): Purchase Order, Sales Quotation, Purchase Request / RFQ, Sales Order.

**Out of scope v1:** AR/AP documents, GL, e-invoice, consolidated e-invoice, stock adjustments/transfers/issues,
report endpoints beyond what paging requires.

## Definitions

- **Company** — one AutoCount company database (`DatabaseName` in the `GetToken` response). A tenant may have several.
- **Canonical record** — the FoundryX-neutral shape a record takes inside the ESB (hop 1 output, hop 2 input).
- **Staged change** — a canonical record awaiting human approval before being pushed to a consumer.
- **Quarantine** — a master row that failed validation and was withheld while its siblings imported.
- **Watermark** — the per (connection, entity) `LastModified` high-water mark driving delta fetch.

---

## Slice 1 — Connection, auth, and the GRN read pipeline

### AC-13-01 `[BE]` AutoCount registers as an `erp` connection provider
**Given** the integrations registry
**When** the `autocount` provider is registered
**Then** it appears in `GET /integrations/providers` with `type: "erp"`
**And** `fields()` returns: base URL, AppId, UserID, Password (secret)
**And** credentials persist to `connections.credentials_json` Fernet-encrypted, never echoed on read
**And** the company (`DatabaseName` / `CompanyName`) is **discovered from the login response and stored read-only**, never entered by the operator.
> Revised against the live demo instance 2026-07-21. There is no AppSecret and no company-selection
> parameter — the company is resolved server-side from the `AppId` header, so **AppId IS the company
> selector** (D16: multi-company = one connection per AppId).

### AC-13-02 `[BE]` Multiple AutoCount companies per tenant
**Given** a tenant with an existing active `autocount` connection for company `AED_VSOFT`
**When** a second connection is created for company `AED_OTHER`
**Then** it is accepted
**And** `uq_connection_tenant_type` no longer blocks it (`erp` carved out alongside `payment`)
**And** each connection carries its own credentials, watermarks, sync modes and field mappings.
> Guards D16/D17. Regression risk: the storage/email one-active-per-type rule must be unaffected.

### AC-13-03 `[BE]` Single-step session auth, JWT-bearing, with proactive + reactive re-login
**Given** a configured connection
**When** `test()` runs
**Then** `POST /api/Server/Login` is called ONCE with header `AppId` and body `{UserID, Password}`
**And** the response's **`JWTToken`** (not the `Token` GUID) is held and sent on every subsequent call
    as a bare **`Authorization: <JWTToken>`** header — no `Bearer` prefix, not `X-API-Key`
**And** the session is **proactively re-logged-in** once the held token exceeds its configured max age
**And** a call failing with the ambiguous `HTTP 500 "Stream was not readable."` triggers **exactly one**
    re-login and retry before the batch fails.
> Revised against the live demo instance 2026-07-21, replacing the two-step `Auth/Login`→`Server/Login`
> design (no such endpoint exists). **There is no 401**: an invalid or expired token returns the same
> HTTP 500 `"Stream was not readable."` as every other relay-level fault, so expiry is not reliably
> distinguishable. Hence both mechanisms — proactive age-based renewal is the primary defence; the
> single retry is the backstop. The retry is safe because all slice-1 calls are reads (idempotent).
> **Trap:** the login response carries BOTH `Token` (a GUID) and `JWTToken`. The GUID is what the vendor
> Postman collection stores in `{{token}}` and it is rejected by every endpoint. Use `JWTToken`.

### AC-13-04 `[BE]` Connection test reports actionable failures
**Given** an unreachable host, bad credentials, or a bad AppId
**When** `test()` runs
**Then** each returns a distinct, human-readable message naming the failing step
**And** a network timeout is distinguishable from an auth rejection
**And** the two distinct wire-level failure shapes are both handled:
  - **app-level** — `HTTP 200` + `{"Status":"Fail","Message":…,"ResultTable":[]}`; surface `Message`
  - **relay-level** — `HTTP 500` + a .NET exception object (`ClassName`/`Message`/`StackTraceString`);
    surface a mapped message, never the raw stack trace
**And** success is determined by **`Status == "Success"`**, never by HTTP status and never by the
    presence of `ResultTable` (which is present-but-empty on failure).
> No "Connection failed" catch-alls — the operator must know which to fix. HTTP status is meaningless
> here: the API returns 200 for business failures.

### AC-13-04a `[BE]` A filter that the API silently ignores must not read as a narrow fetch
**Given** a malformed filter payload (verified live: `{"DocNo":"not-an-array"}`)
**When** it is sent
**Then** AutoCount returns `Status:"Success"` with the **entire unfiltered table** and no error
**And** therefore the client must validate filter shape before sending
**And** a delta fetch must assert the returned set is consistent with the requested window
    (every record's `LastModified` falls inside it), failing loudly otherwise.
> Discovered live 2026-07-21. This is the silent-wrong-data failure mode AC-13-46 exists to prevent:
> a bad filter degrades to a full table scan that is indistinguishable from a successful delta.

### AC-13-05 `[BE]` GRN delta fetch honours the watermark
**Given** a watermark of `2026-07-01T00:00:00Z` for (connection, `goods_received_note`)
**When** a sync runs
**Then** `POST /api/GoodsReceivedNote/GetGoodsReceivedNote` is called with `LastModifiedFrom`/`LastModifiedTo`
**And** only documents modified in that window are returned
**And** the watermark advances to the max `LastModified` observed **only on batch success**.

### AC-13-06 `[BE]` Header and lines arrive in one call
**Given** a GRN with 5 detail lines
**When** it is fetched
**Then** the header and all 5 lines come from a single request (no per-document fan-out)
**And** the canonical record nests lines under the header.

### AC-13-07 `[BE]` Raw payload is retained alongside the canonical record
**Given** any fetched record
**When** it is stored
**Then** the raw `ResultTable` entry is persisted with it
**And** it is retrievable for debugging and for retroactive re-mapping.
> Enables mapping a field discovered later without re-fetching history.

### AC-13-08 `[BE]` Field mapping is data, not code
**Given** a customer whose GRN lines carry `UDF_DriverName`
**When** a mapping row maps it to a canonical field
**Then** the value flows through with no code change
**And** removing the mapping row stops it flowing, again with no code change.

### AC-13-09 `[BE]` Type coercion is declarative
**Given** AutoCount returns `Cancelled: "F"`, `DocDate: "2025/11/22"`, `Qty: 120.00000000`
**When** mapping applies the configured transforms
**Then** they become `false`, a date, and a `Decimal` respectively
**And** an unconvertible value produces a named per-field error, never a silent null.

### AC-13-10 `[BE]` Transactions are strictly all-or-nothing per document
**Given** a GRN whose line 3 fails validation
**When** the batch commits
**Then** **no part** of that GRN is pushed to the consumer
**And** other GRNs in the same batch are unaffected
**And** the failure names the document, the line, and the field.
> D13 (revised).

### AC-13-11 `[BE]` Staged changes await approval in `SCHEDULED_REVIEW` mode
**Given** entity `goods_received_note` in `SCHEDULED_REVIEW`
**When** a sync fetches 3 changed GRNs
**Then** a `background_jobs` row reaches status `needs_review`
**And** nothing is pushed to the consumer
**And** the job is never auto-pruned while in `needs_review`.

### AC-13-12 `[FE]` Review surface shows a per-record diff
**Given** a job in `needs_review`
**When** the operator opens it
**Then** each staged record shows before → after per changed field
**And** unchanged fields are not shown as changes
**And** Approve pushes to the consumer; Discard closes the job without pushing.

### AC-13-13 `[BE]` Approval is idempotent
**Given** an approved batch
**When** Approve is submitted twice (double-click, retry, replay)
**Then** records are pushed exactly once
**And** the second call is a no-op returning the original result.

### AC-13-14 `[E2E]` Full read pipeline, real clicks
**Given** a configured AutoCount connection against the demo instance
**When** the operator clicks Test → Sync now → reviews → Approve
**Then** the GRN appears in the consumer with correct header and line values
**And** the whole flow is driven by clicking, never by direct URL navigation.

### AC-13-15 `[T]` Suite green
Backend tests cover: provider registration, two-step auth + re-login, watermark advance/hold,
mapping + coercion, per-document atomicity, `needs_review` gating, approval idempotency.

---

## Slice 2 — Delta hardening

### AC-13-16 `[BE]` Paging by window narrowing
**Given** a window returning exactly `RecordCount` records
**When** the fetcher detects a possibly-truncated page
**Then** it splits the window and re-fetches
**And** all records are eventually retrieved with no duplicates in the canonical output.
> **Do not use the response's `RecordCount` marker as a total.** Each record carries a `"N of TOTAL"`
> string, but TOTAL is computed **after** the cap is applied — verified live: an uncapped fetch reports
> `"1 of 11"` (the true total) while `RecordCount:5` reports `"1 of 5"`. It looks like a free total and
> is not one. `len(records) == CAP` remains the only truncation signal (D22).

### AC-13-17 `[BE]` Unsplittable window fails loudly
**Given** more records share one `LastModified` instant than `RecordCount` allows
**When** the window cannot be narrowed further
**Then** the batch **fails with a named error**
**And** the watermark does **not** advance
**And** no partial data is delivered.
> D22. Silent truncation is the failure mode this exists to prevent.

### AC-13-18 `[BE]` Failed batch auto-narrows to isolate the offender
**Given** a batch of 200 records that fails
**When** the isolation walk runs
**Then** it binary-searches the window until a single failing record is identified
**And** the error names that record, field and reason
**And** the watermark stays put.
> D18.

### AC-13-19 `[BE]` Stale-sync alert
**Given** entity `stock` has not synced successfully for longer than its configured threshold
**When** the monitor runs
**Then** an alert is raised naming connection, company and entity
**And** it clears automatically on the next success.
> A blocked sync nobody notices is worse than a visible failure.

### AC-13-20 `[BE]` Sync is resumable
**Given** a sync interrupted mid-run (worker restart)
**When** it resumes
**Then** it continues from `cursor_json`, not from the beginning
**And** no record is delivered twice.

### AC-13-21 `[BE]` Abort is cooperative
**Given** a running sync
**When** the operator aborts it
**Then** the worker stops at its next checkpoint
**And** the job ends `aborted`, not `done`
**And** the watermark reflects only fully-committed work.
> Eager mode hides this — must be tested with a real interleave.

---

## Slice 3 — Masters and reconciliation

### AC-13-22 `[BE]` Masters quarantine invalid rows, import valid ones
**Given** 10,000 products of which 12 fail validation
**When** the batch commits
**Then** 9,988 import
**And** 12 are quarantined with the failing field named
**And** the watermark advances past the successful rows only.
> D13 (revised) — masters differ from transactions deliberately.

### AC-13-23 `[FE]` Quarantine is actionable
**Given** quarantined rows
**When** the operator opens the quarantine list
**Then** each shows record identity, failing field, and reason
**And** offers Re-validate
**And** the list is filterable and survives across syncs until resolved.

### AC-13-24 `[BE]` Aged quarantine raises an alert
**Given** a row quarantined longer than the configured threshold
**When** the monitor runs
**Then** an alert is raised.
> Downstream transactions are failing silently while it sits there.

### AC-13-25 `[BE]` Transactions referencing quarantined masters go to RETRY
**Given** a GRN referencing product `X` which is quarantined
**When** the GRN is processed
**Then** it is recorded `RETRY`, not `FAILED`
**And** when `X` is fixed, the GRN drains automatically with no manual re-trigger.
> D23, reusing the existing `integration_logs.RETRY` semantics.

### AC-13-26 `[FE]` Initial load is a supervised reconciliation, not per-record review
**Given** a first sync of 10,000 products
**When** the operator opens it
**Then** they see summary counts (matched / new / conflicted / failed)
**And** an exception list of only conflicts and failures
**And** a sampling view for spot-checks
**And** they are **not** asked to approve 10,000 rows individually.
> D20.

### AC-13-27 `[BE]` Matching uses natural keys
**Given** AutoCount product `001` and an existing consumer product with the same code
**When** reconciliation runs
**Then** they are proposed as a match on natural key
**And** ambiguous matches are surfaced as conflicts for human decision, never auto-merged.

### AC-13-28 `[BE]` Per-field ownership is enforced
**Given** a supplier whose `lead_time_days` is AutoCount-owned and `account_owner` is consumer-owned
**When** a sync applies changes
**Then** `lead_time_days` is overwritten
**And** `account_owner` is untouched
**And** ownership is read from mapping config, not hardcoded.
> D8.

### AC-13-29 `[BE]` Stock runs in AUTO with no staging
**Given** entity `stock` in `AUTO`
**When** a sync runs
**Then** changes push straight through with no `needs_review` stop
**And** the pipeline sustains ≥10,000 rows within the configured window.
> D21.

### AC-13-30 `[BE]` Deactivation, never deletion
**Given** AutoCount reports a creditor deleted or deactivated
**When** it syncs
**Then** the consumer record is marked inactive
**And** is never hard-deleted
**And** documents referencing it remain intact.

---

## Slice 4 — Writes (SQ / PR / RFQ / SO, create-only)

### AC-13-31 `[BE]` Consumer events trigger writes per config
**Given** doc type `sales_order` configured to trigger `on_approved`
**When** the consumer emits a lifecycle event for a different transition
**Then** no write occurs
**And** when it emits `approved`, exactly one write occurs.
> D12a/D12b — the ESB filters; the consumer emits broadly.

### AC-13-32 `[BE]` Writes are idempotent via an ESB-owned ledger
**Given** a document pushed to AutoCount
**When** the write is attempted
**Then** the ESB records the (consumer record id → AutoCount `DocKey`/`DocNo`) correlation on success
**And** a replay of the same consumer record id is a no-op returning the original correlation
**And** the write is never retried blind after an ambiguous failure without first reading back
    by correlation to check whether it actually landed.
> **Revised.** The original wording assumed vendor-supplied `requestId` / `externalSystem` /
> `externalId` fields and a `GET /api/requests/{requestId}` status endpoint. **None of these exist** —
> zero occurrences in the vendor collection, confirmed against the live instance. Writes are synchronous
> and return the persisted document inline; the only correlation handle AutoCount gives us is the
> returned `DocKey`/`DocNo`. Idempotency is therefore **entirely ours to build** (slice 4), and the
> read-back-before-retry rule matters because a timed-out write may still have committed.

### AC-13-33 `[BE]` Write status is observable
**Given** a queued write
**When** the consumer inspects it
**Then** status is one of `PENDING` / `SYNCED` / `FAILED`
**And** `SYNCED` carries the AutoCount document number
**And** `FAILED` carries the AutoCount error verbatim.
> D14 — no approval gate on writes.

### AC-13-34 `[BE]` Failed writes retry with backoff, then dead-letter
**Given** AutoCount is unreachable
**When** a write is attempted
**Then** it retries with backoff
**And** after exhausting retries it dead-letters with the last error
**And** no document is silently dropped.

### AC-13-35 `[BE]` `on_draft_created` is unselectable until lifecycle mirroring ships
**Given** the trigger config UI
**When** the operator opens the trigger picker for a doc type
**Then** `on_draft_created` is present but disabled with a stated reason
**And** the backend rejects it if submitted directly.
> D12a + foolproof-UI: never offer a mode that silently loses edits.

---

## Slice 5 — PO write

### AC-13-36 `[BE]` PO write is gated by an explicit per-tenant switch, default off
**Given** a tenant that has not enabled PO transmission
**When** a PO approval event arrives
**Then** no write occurs and the skip is logged
**And** enabling requires a deliberate configuration action.

### AC-13-37 `[T]` Binding docs updated
**Given** Sorento's documented hard rule "AutoCount PO transmission (never)"
**When** this slice merges
**Then** `SCM_Module_Build_Plan.md:37` and `scm-m4-cash-copilot-acceptance-criteria.md:64` are updated
**And** the change records a named sign-off owner.
> D12. A silent contradiction of a binding doc is a review hard-fail.

---

## Slice 6 — Lifecycle mirroring

### AC-13-38 `[BE]` Update propagation
**Given** a document already pushed to AutoCount
**When** it is edited in the consumer
**Then** `Update<Doc>` is called against the same AutoCount document
**And** the correlation is resolved via `externalId`, never by re-matching on content.

### AC-13-39 `[BE]` Cancel propagation
**Given** a pushed document
**When** it is cancelled/rejected in the consumer
**Then** `Cancel<Doc>` is called
**And** failure to cancel raises an alert (a live financial document is now divergent).

### AC-13-40 `[BE]` Divergence is detected, not silently overwritten
**Given** a document edited in AutoCount after we pushed it
**When** the consumer edits it again
**Then** the conflict is surfaced
**And** the ESB does not blindly overwrite AutoCount's version.

---

## Cross-cutting

### AC-13-41 `[BE]` Every call is tenant- and company-scoped
**Given** any repository query or capability handler in this module
**When** it executes
**Then** it filters by tenant **and** company
**And** no query can read or write another tenant's or company's rows.
> Cross-tenant leakage is a critical defect.

### AC-13-42 `[BE]` Secrets never surface
**Given** logs, activity records, error messages and API responses
**When** they are produced
**Then** AppSecret, Password and Token never appear in plaintext
**And** stored request/response payloads are masked.

### AC-13-43 `[BE]` Sync failure never breaks the triggering request
**Given** a consumer event that triggers a write
**When** the write path throws
**Then** the consumer's originating request still succeeds
**And** the failure is isolated and logged.

### AC-13-44 `[FE]` Responsive at 375px and 1280px
Review, quarantine and reconciliation surfaces are usable at both widths — no horizontal scroll,
no clipped controls, tables scroll within their own container.

### AC-13-45 `[BE]` Module hygiene
Module owns schema `app_autocount`, has per-module Alembic, declares `permissions.csv`,
implements `install` / `install_tenant` / `update_tenant` / `uninstall_tenant`,
registers `StorageKeyLocation` for any stored blob keys, and tags every registry item with its module.

### AC-13-46 `[T]` No silent caps
Any bound applied to a sync (record cap, page cap, retry cap) is logged when hit.
A truncated sync must never read as a complete one.

---

## Explicitly deferred

| Item | Reason |
|---|---|
| AR/AP, GL, e-invoice entities | Not in the requirement diagram |
| Cross-company reporting in a consumer | Consumers take one company each (D19) |
| Bidirectional master editing (consumer → AutoCount masters) | AutoCount is system of record (D8) |
| Direct SQL Server read path | Unnecessary — `LastModifiedFrom` covers it (D4) |
| Second consumer product | Canonical model exists to make it cheap; not built until demanded |
