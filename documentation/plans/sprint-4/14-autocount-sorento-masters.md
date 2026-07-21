# 14 — AutoCount → Sorento masters (hop 2, end-to-end)

> **Contract:** `14-autocount-sorento-masters-acceptance-criteria.md` (29 ACs). That file governs;
> this one is the design that fulfils it.
> **Builds on:** `13-autocount-esb.md` (MERGED, PR #4). Reuses its client, mapping engine, watermark,
> staging and approval machinery.
> **Companion repo:** `/Users/tehjayson/Documents/foundryx/sorento_crm-autocount` @ `feat/autocount-integration`
> **Branch:** `sprint-4/14-autocount-sorento-masters`

## 1. What this slice proves

Slice 1 built hop 1 (AutoCount → canonical) and left hop 2 (canonical → consumer) as a registered
no-op sink — BL-133. This slice makes hop 2 real against Sorento's live ingest API, so `PUSHED`
finally means *delivered* rather than *handed to a stub*.

It does that on **masters**, not documents, because Sorento's `ENTITY_SPECS` admits only six master
entities and no documents at all. Slice 1's GRN pipeline has nowhere to land. That inverts plan 13's
risk ordering (masters were slice 3, deliberately last) and the UAC preamble records why.

## 2. Architecture — what changes and what does not

```
AutoCount (live demo, :9696)          FoundryX ESB (:8001)                 Sorento (:8000)
  Creditor  106 rows  ──┐                                                   suppliers
  Debtor    172 rows  ──┴──► hop 1 ──► canonical ──► stage ──► DRY RUN ──►  (predict)
                             (built)   (new shapes)  (built)      │              │
                                                                  ▼              ▼
                                                            operator approves ──► ingest
                                                                                 (real write)
```

**Unchanged from slice 1:** `AutoCountClient` session auth and retry, the `MappingEngine` and its
data-driven `ac_field_mapping` rows, `Watermark`, `background_jobs` + the `needs_review` approval
gate, the activity log with masked payloads, the Entities tab.

**New:** two canonical master shapes, a per-entity response-envelope strategy, a real Sorento sink,
a company-qualified ref scheme, an unbounded initial load, and the dry-run review surface.

## 3. Decisions

Nine from the grill (UAC §Decision Log, G1–G9). Design consequences of each:

| # | Decision | What it forces in code |
|---|----------|------------------------|
| G1 | Suppliers + customers only | Two canonical shapes. Entity picker offers only these two (AC-14-01). |
| G2 | `source_ref = {DatabaseName}:{AutoKey}` | Ref built at map time, not push time — it is part of canonical identity. |
| G3 | No payment-terms field | Mapping rows for terms simply do not exist. Not "mapped then stripped". |
| G4 | Supervised first load | The staging gate renders Sorento's dry-run verdict, not our own prediction. |
| G5 | AutoCount owns both; overwrite | No ownership columns. Conflict = overwrite, made visible, not resolved. |
| G6 | MANUAL only | No scheduler. Reuses slice 1's Sync-now. |
| G7 | Fix Sorento's `AppException` ordering | Cross-repo PR, six sites + a route-level test. |
| G8 | Dry run lives in Sorento | We call `?dry_run=true`; we never re-implement adoption matching. |
| G9 | Two envelopes, one client | Per-entity unwrap strategy selected by config. |

### D1 — The envelope strategy is a function on the entity config, not a branch in `read()`

GRN returns `{"Status": "...", ...}`. Masters return a bare array whose rows carry `Status`,
`Message`, `RecordCount` *per row*, with the real record nested under `Data[0]`.

`read()` keeps one signature. The entity config names an unwrap strategy; `_unwrap` becomes a
lookup rather than a hardcoded rule. Two strategies ship: `envelope_status_dict` (GRN) and
`envelope_row_array` (masters). Adding a third must not touch `read()` or its callers.

The `ok`-rule fix from `6d3e21c` — the log's success rule must mirror the client's — applies per
strategy. Each strategy owns both, together, so they cannot drift apart again.

### D2 — `source_ref` is minted in the canonical shape

`{DatabaseName}:{AutoKey}` is identity, not transport. It belongs in `CanonicalSupplier`/
`CanonicalCustomer` so that staging, the activity log and the dry-run diff all key on the same
string the sink will use. Minting it at push time would let a staged record and its pushed
counterpart disagree.

`DatabaseName` comes from the session (already captured in slice 1's `Session`), not from operator
input.

### D3 — Initial load bypasses the watermark entirely

`Watermark.start()` returns `last_modified_at` if set, else `now - initial_lookback_days`. For
masters the else-branch is wrong: measured live, a 30-day window yields 1 of 106 suppliers and 2 of
172 customers, and even 365 days misses 4 and 15.

So the source declares `initial_load: full | windowed`. Masters use `full` — first fetch sends no
`LastModifiedFrom` at all. Once a watermark exists, delta proceeds exactly as before. This is a
property of the entity, not a setting to get wrong: `initial_lookback_days` stays visible only for
windowed entities.

### D4 — The staging gate renders a verdict it did not compute

Slice 1's gate shows *our* canonical records awaiting approval. Here it must additionally show what
Sorento says will happen to them. So the approval payload gains a `prediction` block fetched from
`?dry_run=true` immediately before the operator is asked.

Deliberately **not** cached from an earlier dry run: the target can change between staging and
approval, and a stale prediction is worse than none — it would show a clean create for a row someone
hand-created in the meantime.

If the dry run itself fails, the gate shows that and **refuses to offer approval**. An operator must
never be able to approve blind.

### D5 — Adoption is surfaced, never resolved

We do not merge, prefer, or reconcile. Sorento reports which rows it would adopt and what fields
change; we render that faithfully and let a human decide to proceed or not. Per-field ownership is
explicitly out of scope (G5) — inventing a merge rule here would be a silent policy nobody agreed to.

## 4. Data model

No new core tables. Additions inside `app_autocount`:

| Table | Change |
|-------|--------|
| `ac_entity_config` | `+ envelope` (`status_dict`/`row_array`), `+ initial_load` (`full`/`windowed`) |
| `ac_field_mapping` | Seeded rows for the two new entities (data, not code) |

New core `connections` row type for the outbound consumer:

- `type = 'consumer'`, `provider = 'sorento'`, credentials `{apiKey}` Fernet-encrypted, write-only.
- Distinct from slice 1's `erp` connection pointing *at* AutoCount. Direction differs, so identity
  must too.
- `erp` was carved out of both unique indexes in slice 1; `consumer` needs the same treatment only
  if multiple Sorento targets per tenant become a requirement. **v1: one per tenant**, so the
  existing `(tenant, type)` uniqueness is correct and no migration to the indexes is needed.

## 5. Canonical shapes

Derived from Sorento's `canonical_masters.py` — the real spec, read from the repo, **not inferred**.
`extra="forbid"` there means our shape must be a subset of theirs, exactly.

**`CanonicalSupplier`** → Sorento `suppliers`: `source_ref`, `source_doc_no`, `code`, `name`,
`email`, `is_active`.
Creditor has no phone field. Sorento accepts-then-discards seven address fields
(`_supplier_columns`), so we do not send them and do not report them as synced (AC-14-13).

**`CanonicalCustomer`** → Sorento `customers`: `source_ref`, `source_doc_no`, `code`, `name`,
`email`, `phone_number`, `credit_limit`, `tax_id`, `is_active`.
No `country` source exists; `registration_number` exists on Creditor but not Debtor. Both omitted.

Field mapping (`ac_field_mapping` rows, per AC — data not code):

| Canonical | Creditor | Debtor |
|-----------|----------|--------|
| `code` | `AccNo` | `AccNo` |
| `name` | `CompanyName` | `CompanyName` |
| `email` | `EmailAddress` | `EmailAddress` |
| `phone_number` | — | `Mobile` |
| `credit_limit` | — | `CreditLimit` |
| `tax_id` | — | `TIN` |
| `is_active` | `IsActive` `"T"/"F"` → bool | same |
| `source_ref` | `{db}:{Data[0].AutoKey}` | same |
| `source_doc_no` | `AccNo` | `AccNo` |

Coercions are declared transforms (AC-14-05): `t_f_bool`, and `slash_datetime` for `LastModified`
(`"2026/03/18 16:03:21"`, no timezone → aware UTC). An unrecognised value fails **that record only**,
naming the field. A silent `False` from an unparsed active-flag would deactivate a live supplier.

## 6. The Sorento sink

`SorentoSink` implements slice 1's consumer-push seam, replacing the no-op.

- `POST {base}/api/v1/external/ingest/{entity}` with `{"records": [...]}`, header `X-API-Key`.
- **Never** `Authorization: Bearer`, and **never** the legacy `EXTERNAL_API_KEY` — its hash is
  seeded onto the *n8n* integration, so it would misattribute every write (AC-14-15).
- Batches capped at 1000 (their `MAX_BATCH`); we chunk below it.
- **HTTP 200 is not success.** Parse `records[]` per record; map `created`/`updated` → PUSHED,
  `failed` → quarantine, `retryable` → defect signal (AC-14-24 asserts it cannot occur here).
- 429 → honour `Retry-After`. No `X-RateLimit-*` headers exist to pre-empt with. Their limiter
  **fails open with no Redis**, so a clean local run proves nothing about production throttling.
- Guard-rail errors currently return 500 rather than 422/413 (their bug, AC-14-30). Until the
  cross-repo fix lands, an unexpected 500 is logged with the full masked request so it is
  diagnosable rather than mysterious.

## 7. Cross-repo work in Sorento

Separate PR in `sorento_crm-autocount`, landing before or with this slice:

1. **`AppException` argument order** — six sites in `app/api/v1/external/ingest.py` pass the message
   positionally *and* `status_code=` as a keyword → `TypeError` → 500. One line each.
2. **A route-level test** — their ingest tests call `MasterIngestService` directly and never touch
   HTTP, which is exactly why (1) shipped. Fixing the bug without closing the gap that hid it leaves
   the next one free to ship too.
3. **`?dry_run=true`** on ingest — full per-record resolution including adoption matching, reporting
   the outcome each record *would* get plus field-level diffs for adoptions, then rolling back.
   Their savepoint-per-record design already isolates each record; dry run rolls back the outer
   transaction. Must assert row **and** reference counts unchanged.

## 8. Build order

Frontend-first is the house rule, but this slice is ~80% backend contract against two live systems,
and its risky surface is the dry-run review — which cannot be designed honestly until the real
prediction payload shape exists. So:

| Phase | Work | Gate |
|-------|------|------|
| 0 | Sorento cross-repo PR (§7) | Their suite green; dry run verified to write nothing |
| 1 | Envelope strategy + the two canonical shapes + mapping rows | Unit tests; live probe maps 106+172 with 0 failures |
| 2 | `SorentoSink` + outbound connection + per-record outcome handling | Integration test against local Sorento |
| 3 | Unbounded initial load + watermark handover | Test that first fetch sends no window and second does |
| 4 | Dry-run review surface (FE) | Mock the prediction payload first, then bind real |
| 5 | E2E: real AutoCount → real Sorento, both local | AC-14-40 |

Phase 4 is where frontend-first still applies — the review UI is built against a mocked prediction
payload before binding, so its states are tunable. The mock is deleted in the same phase, per the
Definition-of-Done gate.

## 9. Testing

- **Unit:** envelope strategies (both, incl. the `ok`-rule mirror), coercions, ref minting incl.
  cross-company collision, per-record outcome mapping, chunking.
- **Integration:** against local Sorento — push, re-push idempotency, dry-run-writes-nothing,
  adoption diff, 429 handling.
- **Live probe:** the 106 + 172 real records through the real mapping, asserting zero failures. This
  is what caught slice 1's coercion assumptions; keep it.
- **E2E:** AC-14-40, real clicks, both backends live.

**Not provable locally:** Sorento's rate limiter fails open without Redis, so throttle behaviour must
be tested with Redis up or not claimed at all.

## 10. Security

- Sorento API key: Fernet-encrypted, write-only over the API, never echoed, masked in all logs.
- Slice 1's masking already covers `Authorization`; extend `_SENSITIVE_KEY_PARTS` to `x-api-key`.
  BL-138 (over-masking `"pan"` in `CompanyName`) becomes user-visible here since `CompanyName` is a
  mapped field — fix it in this slice rather than carrying it.
- Every query tenant- and company-scoped; cross-tenant leakage is critical.
- The dry run writes nothing — asserted by count, not assumed from the flag.

## 11. Open items

| # | Item | Needed by |
|---|------|-----------|
| 1 | Mint the `foundryx-esb` API key (admin JWT, shown once) | Phase 2 — blocking |
| 2 | Does a production AutoCount wrapper expose stock/item/UOM? | Deciding if products ever land |
| 3 | Sorento's supplier address columns exist but are unwritten | Their fix; AC-14-13 stops us mis-reporting meanwhile |
| 4 | BL-131 (JWT decodes to password) still open | Before a real (non-demo) AutoCount tenant |
