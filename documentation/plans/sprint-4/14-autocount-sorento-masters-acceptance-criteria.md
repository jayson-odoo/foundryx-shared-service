# 14 — AutoCount → Sorento masters (hop 2, end-to-end) — User Acceptance Criteria

> **Status:** DRAFT — contract for `documentation/plans/sprint-4/14-autocount-sorento-masters.md` (not yet written)
> **Builds on:** `13-autocount-esb.md` (slice 1, MERGED — PR #4). Reuses its client, mapping engine,
> watermark, staging and approval machinery unchanged.
> **Companion repo:** `/Users/tehjayson/Documents/foundryx/sorento_crm-autocount`, branch `feat/autocount-integration`
> **Source of decisions:** grill session 2026-07-21 (9 decisions, §Decision Log below)

## Why this slice exists, and why it is not the slice the plan predicted

Plan 13 sequenced masters as **slice 3**, on the reasoning that they are the highest-risk read —
they overwrite live production data — and should land on machinery already proven by GRN and DO.

That sequencing assumed the consumer could accept documents. It cannot. Sorento's `ENTITY_SPECS`
(`app/services/master_ingest_service.py:233-247`) admits exactly six entities, all masters:
`product_categories`, `units_of_measure`, `warehouses`, `suppliers`, `customers`, `products`.
**There is no document ingest.** Slice 1's GRN pipeline therefore has nowhere to land, and BL-133
(the no-op consumer sink) cannot be closed against documents at all.

So masters move forward — not because the risk argument was wrong, but because the alternative is
leaving hop 2 unproven against a stub indefinitely. The risk is mitigated differently instead: by
AC-14-20's supervised reconciliation, which did not exist when the original sequencing was chosen.

## Scope

**In:** AutoCount `Creditor` → Sorento `suppliers`; AutoCount `Debtor` → Sorento `customers`.
Manual sync only. Supervised first load. Two cross-repo fixes in Sorento.

**Out:** The other four Sorento entities (`products`, `product_categories`, `units_of_measure`,
`warehouses`) — no AutoCount source exists on this wrapper build; see AC-14-01. Scheduling. Per-field
ownership. Any write back to AutoCount. Payment terms (AC-14-12).

## Definitions

- **Adoption** — Sorento claiming a pre-existing unclaimed local row by business-code match on first
  push, and thereafter treating it as ours. Reports `updated`, not `created`.
- **Dry run** — a full ingest resolution that reports the outcome each record *would* receive, then
  rolls back without writing.
- **Company-qualified ref** — `"{DatabaseName}:{AutoKey}"`, the `source_ref` sent to Sorento.
- **Envelope** — the outer JSON shape a vendor endpoint returns. AutoCount uses two (AC-14-03).

---

## Group A — Source: AutoCount masters

### AC-14-01 `[BE]` Only entities with a confirmed source are offered
**Given** the AutoCount entity catalogue
**When** an operator configures which entities to sync
**Then** only `Creditor` and `Debtor` are selectable
**And** entities with no working vendor route are **absent from the picker, not shown-and-disabled**
**And** no canonical shape exists in code for an entity whose vendor payload has never been observed.
> Probed live 2026-07-21: `Stock`, `StockItem`, `Item`, `UOM`, `StockGroup`, `StockCategory`,
> `StockLocation`, `StockUOM` all return HTTP 500 with an **empty** `Message` — distinct from the
> wrong-credential signature (`"Stream was not readable."`), and consistent with the route being
> absent from this wrapper build. Foolproof-UI: offer only what will work.
> **This AC is a standing guard, not a one-off.** If a production wrapper exposes stock, the entity
> is added only after its real payload is captured — never designed from inference. (See the slice-1
> retro: a whole canonical shape was once derived by guesswork against a spec that was readable all along.)

### AC-14-02 `[BE]` Creditor and Debtor read from the live instance
**Given** a valid `autocount` connection
**When** the source fetches `Creditor` and `Debtor`
**Then** both return rows (demo: 106 and 172 respectively)
**And** each row's real record is read from the nested `Data[0]`, not from the flat top level
**And** `LastModified` is read from `Data[0]`, where it actually lives.

### AC-14-03 `[BE]` Two envelopes, one client
**Given** GRN returns a dict carrying `Status`, and masters return a **bare array** whose rows carry
`Status`/`Message`/`RecordCount` per row
**When** either is read
**Then** the client selects the unwrap strategy **per entity** from config
**And** a master response is never passed through the GRN `_unwrap` (which requires a top-level
`Status` and would raise on every master row)
**And** adding a third envelope requires no change to `read()`'s signature or callers.

### AC-14-04 `[BE]` Delta filtering works for masters
**Given** a watermark
**When** the source fetches with `LastModifiedFrom`/`LastModifiedTo`
**Then** the vendor genuinely filters
**And** a window in the future returns zero rows.
> Verified live: 2026 window → 11 Creditor / 69 Debtor; 2099 window → 0 / 0. Contrast AC-13-04a,
> where a **malformed** filter is silently ignored and returns everything — so a zero-row result
> proves filtering, but a full-set result does not disprove it.

### AC-14-05 `[BE]` Vendor scalars coerce at the mapping boundary
**Given** AutoCount emits `IsActive` as `"T"`/`"F"` and `LastModified` as `"2026/03/18 16:03:21"`
(slash-separated, no timezone)
**When** a record is mapped
**Then** `"T"`/`"F"` become real booleans
**And** the timestamp is parsed and stored as aware UTC per house datetime rules
**And** an unrecognised value fails **that record only**, with the field named — never a silent default.
> A silent `False` from an unparsed active-flag would deactivate a live supplier in Sorento.

---

## Group B — Identity

### AC-14-10 `[BE]` `source_ref` is company-qualified
**Given** AutoCount's `AutoKey` is a per-company primary key, so `AutoKey=1` exists in every company
**And** Sorento's uniqueness is `(source_system, entity_type, source_ref)` with **no company dimension**
**When** a record is pushed
**Then** `source_ref` is `"{DatabaseName}:{AutoKey}"` (e.g. `"AED_VSOFT:1"`)
**And** connecting a second company never collides with the first
**And** `source_doc_no` carries `AccNo` so the record is recognisable to a human reading Sorento.

### AC-14-11 `[BE]` Identity survives a business-code renumber
**Given** a supplier synced as `AED_VSOFT:1` with `AccNo` `400-J001`
**When** the AccNo is renumbered in AutoCount and the record re-syncs
**Then** the existing Sorento row is **updated**, not duplicated
**And** `source_doc_no` reflects the new AccNo.
> Sorento's own reference design (`301_integration_references.py:52-55`) requires an immutable ref
> for exactly this reason. `AutoKey` is that; `AccNo` is not.
> Note `Guid` is **not** usable: Debtor rows carry one, Creditor rows do not.

---

## Group C — Sink: Sorento ingest

### AC-14-12 `[BE]` Payment terms are never sent
**Given** AutoCount supplies `DisplayTerm` as a code (`"C.O.D."`), not a number of days
**When** a supplier or customer is pushed
**Then** neither `payment_terms_code` nor `payment_terms_days` appears in the payload
**And** no code→days mapping is invented anywhere in this slice.
> `payment_terms_code` is an **unconditional** `MissingReference` in Sorento
> (`master_ingest_service.py:165-171`) — it performs no lookup. Any value makes the record
> permanently `retryable` until Sorento's Phase D. Sending it would build an undrainable queue.

### AC-14-13 `[BE]` Only fields Sorento actually persists are claimed as synced
**Given** Sorento's `CanonicalSupplier` accepts `contact_name`, `address_line1`, `address_line2`,
`city`, `state`, `postal_code`, `country` but `_supplier_columns` writes none of them
**When** the mapping is defined
**Then** the operator-facing field list shows only fields Sorento persists
**And** a synced supplier is documented as carrying code, name, email and active-flag **only**
**And** if a discarded field is sent for forward-compatibility, it is recorded as not-yet-persisted,
never reported to the operator as synced.
> This is the failure Sorento's own canonical layer says it exists to prevent: "a field the ESB
> believed it sent and Sorento silently dropped is the worst kind of mapping bug"
> (`canonical_masters.py:8-11`). Our side must not re-create it by reporting success.

### AC-14-14 `[BE]` Unknown fields are rejected before they reach the wire
**Given** Sorento's canonical models set `extra="forbid"`
**When** the mapping produces a field Sorento does not define
**Then** it is caught by our own validation with the field named
**And** it never costs a round-trip to discover.

### AC-14-15 `[BE]` Auth uses the integration's own key
**Given** Sorento authenticates external callers by `X-API-Key`
**When** the ESB pushes
**Then** it sends `X-API-Key`, never `Authorization: Bearer`
**And** the key is the one minted for the `foundryx-esb` integration
**And** the legacy `EXTERNAL_API_KEY` is **never** used — its hash is seeded onto the *n8n*
integration, so presenting it would authenticate us as n8n and misattribute every write
(`integration_seed.py:54`)
**And** the key is stored Fernet-encrypted in its own outbound connection, distinct from the `erp`
connection pointing at AutoCount.

### AC-14-16 `[BE]` Per-record outcomes are honoured, not the HTTP status
**Given** Sorento returns HTTP 200 even when every record failed
**When** a push completes
**Then** each record's `created`/`updated`/`failed`/`retryable` outcome is recorded individually
**And** `retryable` is treated as **nothing was written** — no row, no reference
**And** a batch reporting failures is never summarised to the operator as a success.

### AC-14-17 `[BE]` 429 is honoured
**Given** Sorento rate-limits per integration and returns `Retry-After`
**When** the ESB receives 429
**Then** it waits at least `Retry-After` seconds before retrying
**And** it does not infer remaining quota from headers (none are sent).
> Note Sorento's limiter **fails open** when Redis is absent — a clean local run proves nothing
> about throttling behaviour in production.

### AC-14-18 `[T]` A re-push is idempotent
**Given** a batch already pushed
**When** the identical batch is pushed again
**Then** no duplicate rows are created
**And** records report `updated`
**And** `created` counts are never used as the source of truth for "new in this run" (a retried HTTP
call after a timeout re-runs the whole batch).

---

## Group D — The overwrite gate

### AC-14-20 `[BE][FE]` First load is a supervised reconciliation
**Given** the Sorento target holds **real hand-entered masters**
**And** AutoCount is the source of truth, so sync overwrites
**When** the first sync runs
**Then** it executes as a **dry run** and writes nothing
**And** the operator sees per record the outcome it would receive
**And** for every record whose values would **change** — whether newly **adopted** or already
linked and re-synced — the field-level before/after is shown
**And** nothing is written until the operator explicitly approves.
> Broadened from "adopted only" during build. An already-linked record overwrites live values just
> as destructively as an adoption, and it is the **commoner** case — restricting the diff to
> adoptions would show an operator nothing at all on a routine sync, which is when they are most
> likely to approve without looking.
> This is the AC that makes ERP-as-source-of-truth safe against a populated target. Without it the
> first sync silently overwrites work people typed in, and reports it as a routine `updated`.

### AC-14-21 `[BE]` The dry run is authoritative, not reconstructed
**Given** the adoption rule lives in Sorento
**When** the ESB predicts outcomes
**Then** the prediction comes from Sorento's own `?dry_run=true` resolution
**And** the ESB does **not** re-implement adoption matching locally.
> Two copies of one rule will drift, and the copy that is wrong is the one holding the safety gate.
> Sorento's read API cannot be used for this: `current_state` resolves only via
> `refs.resolve(source_ref)` (`master_read_service.py:96-99`), so an unclaimed hand-entered row —
> exactly the at-risk case — reports `not_found`. A dry run built on it would report "new" for
> records about to be overwritten.

### AC-14-22 `[FE]` Adoption is visible, never silent
**Given** a push where Sorento adopted pre-existing rows
**When** the operator reviews the result
**Then** adopted records are distinguished from genuinely-updated ones
**And** a first-ever push returning `updated` is explained, not flagged as an anomaly.

### AC-14-23 `[BE]` Ongoing syncs are manual and staged
**Given** the initial load is committed
**When** a subsequent sync runs
**Then** it is triggered manually (no scheduler this slice)
**And** it stages for approval exactly as slice 1's GRN pipeline does
**And** no unattended overwrite of live master data is possible.

### AC-14-24 `[BE]` `retryable` cannot occur, and is asserted so
**Given** suppliers and customers have no category/UoM dependency
**And** `payment_terms_code` is never sent (AC-14-12)
**When** any batch is pushed
**Then** no record returns `retryable`
**And** a `retryable` outcome is treated as a **defect signal**, not a routine re-drain.
> Stated as an AC so no re-drain machinery is built for a state that cannot arise. If this ever
> fires, an assumption above has broken and that is the thing to investigate.

### AC-14-25 `[BE]` The initial master load is unbounded, not lookback-windowed
**Given** a master entity with no watermark yet
**When** the first sync runs
**Then** it fetches the **entire** current set, with no `LastModifiedFrom` bound
**And** `initial_lookback_days` does **not** apply to masters
**And** only *subsequent* syncs use the watermark for delta.
> Measured live 2026-07-21 against slice 1's 30-day default: Creditor 106 total → **1** in window;
> Debtor 172 → **2**. A 365-day window still misses 4 and 15. So no window is correct — only an
> unbounded first pull mirrors the set.
> This is a **category error inherited from slice 1**, worth stating plainly so it is not repeated:
> a document stream (GRN) is naturally time-bounded and a lookback is right for it; a master list is
> a standing set whose purpose is to mirror current state. Applying document semantics to masters
> produces a sync that reports success while importing ~1% of the data — the most dangerous
> possible failure, because nothing looks wrong.

### AC-14-26 `[FE]` A partial or empty master sync is never reported as a clean success
**Given** a master sync returns far fewer records than the entity's known total
**When** the result is shown
**Then** the count fetched is stated alongside what the vendor reports available (`RecordCount`)
**And** an operator can tell "nothing changed" apart from "the window excluded almost everything".
> Slice 1 already surfaced this class of confusion once (the second-sync empty result). There the
> answer was correct behaviour; here it would have been silent data loss.

---

## Group E — Cross-repo fixes in Sorento

### AC-14-30 `[BE]` Ingest guard-rail errors return their intended status
**Given** `AppException.__init__` is `(status_code, message, detail, code)`
**And** all six raise sites in `app/api/v1/external/ingest.py` pass the message positionally **and**
`status_code=` as a keyword
**When** a malformed envelope or oversized batch is posted
**Then** the caller receives 422 / 413 as intended, not `TypeError` → HTTP 500.
> Confirmed by reading the signature (`error_handler.py:9-15`) against the call sites
> (`ingest.py:70,94,96,106,140,142`): `TypeError: got multiple values for argument 'status_code'`.

### AC-14-31 `[T]` The ingest route is tested over HTTP
**Given** `tests/test_master_ingest.py` exercises `MasterIngestService` directly and never the route
**When** the fix in AC-14-30 lands
**Then** at least one test posts to `/api/v1/external/ingest/{entity}` over HTTP
**And** it covers the malformed-envelope and oversized-batch paths.
> The absence of any route-level test is precisely why AC-14-30 shipped. Fixing the bug without
> closing the gap that hid it leaves the next one free to ship too.

### AC-14-32 `[BE]` Dry-run mode on ingest
**Given** `POST /api/v1/external/ingest/{entity}`
**When** called with `?dry_run=true`
**Then** every record is resolved exactly as a real ingest would, including adoption matching
**And** the response reports the outcome each record would receive
**And** for adoptions it reports the field-level diff against the existing row
**And** **nothing is committed** — verified by asserting row counts and reference counts are
unchanged afterwards
**And** the flag defaults to false, so existing callers are unaffected.

---

## Group F — End-to-end

### AC-14-40 `[E2E]` Real AutoCount to real Sorento, locally
**Given** FoundryX on :8001 and Sorento on :8000, both live
**And** a minted `foundryx-esb` API key
**When** an operator clicks Sync now, reviews the dry run, and approves
**Then** real Creditor rows from the live AutoCount demo appear as Sorento suppliers
**And** each carries the company-qualified `source_ref`
**And** re-running produces `updated`, not duplicates.
> This closes **BL-133**: `PUSHED` finally means delivered to a real consumer, not handed to a no-op.

### AC-14-41 `[FE]` Push state is honest
**Given** hop 2 now has a real sink
**When** a record's state is displayed
**Then** delivered is distinguishable from accepted-but-not-yet-delivered
**And** no record shows a state implying delivery that has not occurred.

---

## Prerequisites (blocking, not deliverable by this slice)

| # | Item | Owner | Why blocking |
|---|------|-------|--------------|
| 1 | Mint the `foundryx-esb` API key in Sorento | needs an admin JWT | Nothing is seeded (`integration_seed.py:173-174`); plaintext is shown **once**. Ingest is unreachable without it. |
| 2 | Sorento running locally on :8000 with migrations `296`–`301` | — | `297` seeds the integration, principal and role. |
| 3 | Confirm whether a production AutoCount wrapper exposes stock/item/UOM | — | Not blocking this slice, but decides whether products are a later slice or never. |

## Decision Log (grill, 2026-07-21)

| # | Decision | Rationale |
|---|----------|-----------|
| G1 | Scope = suppliers + customers only | The only two Sorento entities with a confirmed AutoCount source. |
| G2 | `source_ref` = `{DatabaseName}:{AutoKey}` | Immutable; survives AccNo renumber; collision-free across companies. Guid unusable — Creditor has none. |
| G3 | Send no payment-terms field | `payment_terms_code` is an unconditional permanent-`retryable`; days cannot be derived from `"C.O.D."`. |
| G4 | Supervised reconciliation on first load | Target holds real hand-entered data; adoption is silent by default. |
| G5 | AutoCount owns both entities; overwrite | ERP as system of record. Per-field ownership deferred. |
| G6 | MANUAL sync only | Consistent with slice 1; keeps every overwrite human-gated while new. |
| G7 | Fix `AppException` ordering in Sorento | One line per site; leaves a correct contract to build against. |
| G8 | Dry run lives in Sorento's ingest, not in our read-back | The component owning the adoption rule is the only one that can predict it truthfully. |
| G9 | Two envelopes, one client | Masters return a bare array; GRN a dict. Per-entity strategy, not a second client. |

## Open items

| # | Item | Needed by |
|---|------|-----------|
| 1 | Does a production AutoCount wrapper expose stock/item/UOM routes? | Deciding whether products are ever in scope |
| 2 | Sorento has no `country` source for customers, and Creditor has no phone field | Accepted gaps — confirm no one expects them |
| 3 | Sorento's supplier address columns exist but are unwritten | Their fix, not ours; AC-14-13 stops us mis-reporting meanwhile |
