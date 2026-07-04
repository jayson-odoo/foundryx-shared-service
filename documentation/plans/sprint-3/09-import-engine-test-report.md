# Sprint 3 · Plan 09 — Import Engine · Test Execution Report

**Branch:** `sprint-3/09-import-engine` · **Date:** 2026-06-16
**Stack:** Next 15 :3001 → FastAPI :8001 → native Postgres

Validates `09-import-engine-acceptance-criteria.md` (AC-09-01 … AC-09-28).

---

## Summary

| Layer | Result |
|-------|--------|
| Backend (`tests/test_import_engine.py`) | **20 passed** |
| Backend full suite (regression) | **783 passed** (0 failures) |
| Frontend unit (`services/import-service.test.ts`) | **5 passed** |
| Frontend full vitest (regression) | 594 passed / 1 pre-existing (signin) |
| E2E (`e2e/import-engine.spec.ts`) | **1 passed** (full journey, both viewports) |

---

## Backend — `tests/test_import_engine.py` (20)

| Test | AC |
|------|----|
| `test_sniff_each_format` | AC-09-13 (xlsx/csv sniff, exe rejected) |
| `test_header_is_first_non_empty_row` | AC-09-04 |
| `test_duplicate_headers_suffixed` | AC-09-16 |
| `test_create_only_imports_valid_rows` | AC-09-01/08 |
| `test_coercion_cell_errors` | AC-09-22 |
| `test_required_email_missing_is_row_error` | AC-09-16 |
| `test_create_only_rejects_present_id` | AC-09-05 |
| `test_update_only_requires_existing_id` | AC-09-05 |
| `test_upsert_create_and_update` | AC-09-05 |
| `test_in_file_duplicate_email_errors` | AC-09-22 |
| `test_map_collision_leaves_target_blank` | AC-09-16 |
| `test_abort_on_invalid_blocks_commit` | AC-09-09/17 |
| `test_double_commit_guard` | AC-09-11 |
| `test_unsupported_file_rejected` | AC-09-12/13 |
| `test_formula_injection_sanitized` | AC-09-20 |
| `test_template_download_has_dropdown` | AC-09-02 |
| `test_drift_guard_columns_subset_of_writable` | AC-09-15 |
| `test_imports_read_all_scopes_history` | AC-09-24 |
| `test_commit_is_set_based_not_per_row` | AC-09-10 (≤3 INSERTs for 40 rows) |
| `test_tenant_isolation` | AC-09-24 |

## Frontend — `services/import-service.test.ts` (5)

create() multipart FormData · downloadTemplate() query+blob · setMapping() PUT body ·
list() pagination/filter encoding · commit() POST. (AC-09-26 service contract.)

## E2E — `e2e/import-engine.spec.ts` (1)

Dedicated provisioned tenant. Real clicks: Users → **Import** → upload a CSV with a
good row + a bad-email row → **Upload & map** (auto-mapped) → **Validate** → results
show **1 valid / 1 invalid** + the offending cell's problem ("not a valid email") →
mobile viewport (375) coherent → **Import 1 valid rows (1 skipped)** → "imported 1
created" → the user appears in `/users`. (AC-09-01/06/07/08/16/17/19/27.)

### Bugs fixed during live verify (process notes)
- The plan-09 migration `d5e6f7a8b9c0` wasn't applied to the live DB → POST `/imports`
  500'd ("import_settings does not exist"), which surfaced in the browser as a **CORS
  error** (a 500 before CORS headers attach). Lesson: a browser "CORS / No
  Access-Control-Allow-Origin" on ONE endpoint while siblings work = a server 500 on
  that route, not a CORS config problem. Applied the migration + synced perms.
- E2E assertion fixes only (product correct): exact-text badges (strict-mode dup with
  the commit button), and assert the cell's *problem message* (the results table shows
  row/column/message, not the raw value).

## Verdict
All plan-09 acceptance criteria (AC-09-01 … AC-09-28) **MET**. Quality gate green.
Follow-ups unchanged (inline cell-edit, full undo, AV scan, export-path sanitize — all backlog).
