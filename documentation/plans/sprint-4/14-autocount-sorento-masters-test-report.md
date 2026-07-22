# 14 — AutoCount → Sorento masters (hop 2) — Test Execution Report

> **Contract:** `14-autocount-sorento-masters-acceptance-criteria.md`
> **Branch:** `sprint-4/14-autocount-sorento-masters`
> **Date:** 2026-07-22
> **Stack under test:** FastAPI :8001 + Postgres (backend suites), and a MANUAL live run of the
> full ESB → real Sorento path (the slice's headline verification, recorded during build).

## How this slice was verified

Slice 14 is a **backend/data slice** (source envelopes, identity, the Sorento sink, the overwrite
gate). Its two cross-repo fixes and the real push live in the companion Sorento repo. It was
**live-verified end-to-end against a real AutoCount demo instance and a real local Sorento** during
build (real Creditor rows landed as Sorento suppliers carrying the company-qualified `source_ref`, and
a re-run reported `updated` not duplicates). This report keys every AC to that manual verification
and/or the automated backend tests.

**No automated Sorento-dependent E2E was written**, by design: Sorento is a separate cross-repo
service (currently down on :8010), and an E2E that stands up a real consumer would be flaky and
out-of-repo. The FoundryX-side surfaces are covered by slices 15/16's E2E (`e2e/autocount-mapping.spec.ts`)
and unit suites; the Sorento delivery is covered by the manual live run + the sink unit suite.

## Automated evidence (green)

| Suite | Result |
|-------|--------|
| `tests/test_autocount.py` + `tests/test_autocount_pipeline.py` + `tests/test_sorento_sink.py` | **295 passed** (`python -m pytest`, 94.76s) |
| `services/autocount-service.test.ts` + autocount FE unit files | green in the full vitest run (**1079 passed**) |

## AC verdicts

| AC | Verdict | Evidence |
|----|---------|----------|
| AC-14-01 Only confirmed-source entities offered | **PASS** | `test_autocount_pipeline.py` AC-14-01 (`:2740`) — only `Creditor`/`Debtor` selectable; absent-route entities not shown-and-disabled. |
| AC-14-02 Creditor/Debtor read from `Data[0]` | **PASS** | `test_autocount_pipeline.py` AC-14-02 list-index path resolution (`:2199`, `:2677`) — nested `Data[0]` read; top-level read finds nothing. |
| AC-14-03 Two envelopes, one client | **PASS** | `test_autocount_pipeline.py` AC-14-03 (`:2259`, `:2268`, `:2338`) — per-entity unwrap registry, master row never through the GRN `_unwrap`. |
| AC-14-04 Delta filtering for masters | **PASS** | Manual live verification (2026 window → 11/69, 2099 window → 0/0, per the AC note); delta filter exercised in pipeline sync tests. |
| AC-14-05 Vendor scalars coerce at boundary | **PASS** | `test_autocount_pipeline.py` AC-14-05 (`:2373`, `:2385`, `:2556`) — `"T"/"F"`→bool, slash datetime→aware-UTC, unparsed value fails that record named. |
| AC-14-10 `source_ref` company-qualified | **PASS** | `test_autocount_pipeline.py` AC-14-10 (`:2437`, `:2445`, `:2771`, `:2778`) — `"{DatabaseName}:{AutoKey}"`, `source_doc_no`=AccNo. |
| AC-14-11 Identity survives AccNo renumber | **PASS** | `test_autocount_pipeline.py` AC-14-11 (`:2467`) — stable ref across AccNo change → updated, not duplicated. |
| AC-14-12 Payment terms never sent | **PASS** | `test_autocount_pipeline.py` AC-14-12 (`:2516`) — no `payment_terms_*` in payload. |
| AC-14-13 Only persisted fields claimed synced | **PASS** | `test_sorento_sink.py` `test_only_sink_fields_cross_the_wire` (`:72`), `test_customer_projection_carries_its_extra_fields` (`:88`); pipeline AC-14-13 (`:2497`, `:2501`). |
| AC-14-14 Unknown fields rejected pre-wire | **PASS** | `test_sorento_sink.py` projection (`:69`); pipeline AC-14-14 (`:2526`) — caught by our validation, no round-trip. |
| AC-14-15 Auth uses the integration's own key | **PASS** | `test_sorento_sink.py` `test_auth_is_x_api_key_never_bearer` (`:101`); `test_autocount.py` AC-14-15 (`:498`, `:574` — `x_api_key == "sk_live"`). |
| AC-14-16 Per-record outcomes honoured | **PASS** | `test_sorento_sink.py` `test_created_and_updated_are_delivered` (`:131`), `test_failed_record_is_not_delivered_and_names_the_error` (`:141`), `test_a_missing_verdict_is_never_treated_as_success` (`:174`). |
| AC-14-17 429 honoured | **PASS** | `test_sorento_sink.py` `test_429_waits_the_retry_after_then_succeeds` (`:188`), `test_429_beyond_the_wait_budget_raises` (`:207`). Live not provable (Sorento limiter fails open locally, per AC note). |
| AC-14-18 Re-push idempotent | **PASS** | `test_sorento_sink.py` `test_created_and_updated_are_delivered` (`updated` outcome); manual live re-run reported `updated`, no duplicates. |
| AC-14-20 First load supervised reconciliation | **PASS** | `test_autocount_pipeline.py` dry-run preview (Task D, `:3246`) — executes as dry run, per-record + field-level before/after, nothing written until approve. |
| AC-14-21 Dry run authoritative (Sorento's own) | **PASS** | `test_autocount_pipeline.py` AC-14-21 (`:3255`) — prediction from Sorento's `?dry_run=true`, not re-implemented locally. |
| AC-14-22 Adoption visible, never silent | **PASS** | `test_sorento_sink.py` dry run (`:228`) surfaces per-record outcome incl. adoption; prediction-diff FE component + `preview-panel.test.tsx`. |
| AC-14-23 Ongoing syncs manual + staged | **PASS** | Pipeline staging tests + slice-13/15 review surface (manual sync → staged → approve); no scheduler this slice. |
| AC-14-24 `retryable` cannot occur, asserted | **PASS** | `test_sorento_sink.py` `test_retryable_is_a_loud_failure_not_a_silent_requeue` (`:157`), `test_a_missing_verdict...` (`:174`). |
| AC-14-25 Initial master load unbounded | **PASS** | `test_autocount_pipeline.py` AC-14-25 (`:2597`, `:2621`) — first master sync has no `LastModifiedFrom`; lookback does not apply to masters. |
| AC-14-26 Partial/empty never a clean success | **PASS** | `test_autocount_pipeline.py` AC-14-26 (`:2698`, `:2722`); `test_autocount.py` (`:213` — fetched vs vendor `RecordCount`). |
| AC-14-30 Ingest guard-rail status codes (Sorento) | **PASS (cross-repo + live)** | Sorento-repo fix (`AppException` ordering); confirmed by the live push succeeding and Sorento's own route test (AC-14-31). Not a FoundryX code path. |
| AC-14-31 Ingest route tested over HTTP (Sorento) | **PASS (cross-repo)** | Sorento `tests/test_master_ingest.py` route-level test — lives in the companion repo, not this one. |
| AC-14-32 Dry-run mode on ingest (Sorento) | **PASS (cross-repo + live)** | Sorento `?dry_run=true` — consumed by AC-14-21's dry run; verified live during the supervised first load. |
| AC-14-40 Real AutoCount → real Sorento, locally | **PASS (manual live verification)** | Verified during build: real Creditor rows appeared as Sorento suppliers with the company-qualified `source_ref`; re-run → `updated`. **No automated E2E** (Sorento cross-repo, deliberate — see above). |
| AC-14-41 Push state is honest | **PASS** | `test_autocount_pipeline.py` approve-via-real-sink (`:3338`, `:3357` — `delivered is True`); FE staged-status registry distinguishes PUSHED/delivered. Closes BL-133. |

## Verdict

All 26 slice-14 ACs **PASS**. The Sorento cross-repo ACs (14-30/31/32) and the headline E2E (14-40)
are verified via the manual live run + the companion repo's tests rather than an in-repo automated
spec — a deliberate scope decision (Sorento is a separate service). No FAIL. No DoD-gate violation on
this slice: the sink is real (no mock), identity/coercion are backfilled at the mapping boundary, no
tenant-editable key is hardcoded, and no new permission was introduced.
