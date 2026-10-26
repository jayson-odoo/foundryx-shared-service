# Plan 35 - AutoCount billing preset fixes (lane SS-BILLING-PRESET-FIX, size S)

Source: scout report `AC-BILLING-ACCESS-CHECK` (27 Oct 00:35 MYT, read-only queries on `AED_SORENTO` with the
`FXView` grant). Verdict: the plan-32 billing presets are not activatable as built. No wire change: the CRM
contract (section 13 / 14.3) already says "NULL `FromDocDtlKey` -> `from_doc_type` / `from_doc_no`, no ref".

## Fixes (`service_backend/modules/autocount/presets.py`)

| # | Finding (scout) | Fix |
|---|---|---|
| F1 | 19 IV + 3 CN drafts (`DocStatus='D'`, Oct 2026, no AR row) would push as `posted` (`filter_formula=None`) | Billing presets carry `filterFormula = DocStatus != "D"`. `E` (5 IV in 2025, 1 with an AR row) is KEPT; meaning asked of the owner, logged in the backlog |
| F2 | `CS` has no `DocStatus` column: Preview fails with "Invalid column" | CS header selects `NULL AS DocStatus` (the filter keeps a NULL) |
| F3 | `DNDTL` has no `FromDocType` / `FromDocNo` / `FromDocDtlKey`: DN Preview fails | DN variant: no `COUNT(d.FromDocDtlKey)` fingerprint column (`LineFpLinked` dropped from header + sweep), no `FromDoc*` line columns or mapping fields |
| F4 | `_AR_ITEMS` and the AR line query net 333 cancelled ARCN (RM 1,384,734.44) and add 15 cancelled ARDN (RM 74,620.55) | `COALESCE(Cancelled, 'F') <> 'T'` on ARDN and ARCN in both |
| F5 | The DODTL grant now exists; 2023-24 IV lines carry `FromDocDtlKey`, 2025-26 lines carry only `FromDocNo` | Crew ruling (b), matching the 20 Oct "exact link" ruling: restore the PR #127 `DODTL` join (`LinkDODocKey`); a DO line with a key mints `{book}:DO:{DO DocKey}:{DtlKey}`; a line with only `FromDocNo` sends `from_doc_type` + `from_doc_no` (the DO header link) and no line ref; an unresolved key sends no ref (never guessed). The PR #130 ledger lookup (`billing_do_doc_keys`) is removed |

## Backfill (DoD 2): module Alembic `0033_autocount_billing_fix` + `update_tenant` below 0.19.0

`backfill_billing_preset_fix` over every `invoice` / `cash_sale` / `credit_note` / `debit_note` /
`ar_outstanding` task, frozen texts only, company resolved with the config's own `tenant_id`:
- each stored query byte-identical to the FROZEN previous preset text (company-substituted) becomes the new text;
  anything else is customised: left untouched, one WARNING;
- IV/CS line query rewritten -> `LinkDODocKey` back in `line_result_columns` (NULL stays NULL) and its line
  mapping row enabled (created when absent);
- DN rewritten -> `LineFpLinked` leaves `result_columns`, the three `FromDoc*` line columns leave
  `line_result_columns`, their enabled line rows are disabled;
- `filterFormula` blank on a billing task -> the preset formula; a hand-written formula is left with a WARNING.

## Tests (red first)
`tests/test_autocount_billing_preset_fix.py`: SQL-shape asserts per fix (F1-F5), mapping engine DO link (key +
DODTL hit -> ref; FromDocNo only -> no ref, no error; key but DODTL miss -> no ref; key + no book -> named
error), the filter keeps `A`/`E`/NULL and drops `D`, backfill rewrite/skip/warn cases. Existing
`test_autocount_billing_feed.py` / `test_autocount_billing_do_link*.py` updated to the restored join.

## Verify
Read-only replay 22-26 Oct through the tunnel: IV/CN/DN/CS counts + `NetTotal` vs raw tables; AR total vs raw
IV + DN - CN excluding cancelled. CRM docs (sorento-crm `RUNBOOK-billing-backfill.md`,
`REF-autocount-billing-schema.md`) corrected in a small CRM docs PR or a crew note.
