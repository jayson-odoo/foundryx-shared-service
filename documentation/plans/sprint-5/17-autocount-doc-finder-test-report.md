# Test report: Find an AutoCount document by number (sprint-5/17, AC-DOC-FINDER)

UAC: `17-autocount-doc-finder-acceptance-criteria.md`. Plan: `17-autocount-doc-finder.md`.
Evidence: `17-evidence/` (screenshots of the live click-through).

## Environment

- Sandbox only. Postgres 16 + Redis started inside the sandbox (db `foundryx_s17`, built by
  `scripts.bootstrap_db`). Backend `uvicorn :8001`, `ENVIRONMENT=development`, eager jobs.
- AutoCount = a local fake (`127.0.0.1:9900/api/db1`) serving the two DO day doors. The real
  host was never called. Fake data: PS202610-0004 dated today+4 (05/10/2026) with
  `LastModified` today 07:39 by AIN; a snapshot built 3 h earlier holds it with DocDate today
  (01/10/2026). PS202610-0010 is forward-dated today+9. The company has a DO feed connection and
  no GRN connection.
- Frontend: `rm -rf .next && npm run build && npm start` on :3001. Driven with Playwright
  (Chromium) by real clicks: sign in, sidebar AutoCount, Find document, company picker, number, Find.
- The fake server logged 55 requests, all GET (no non-GET reached it).

## Automated suites

| Suite | Result |
|---|---|
| `tests/test_s17_doc_lookup.py` | 50 passed |
| AutoCount + s1x backend regression (`-n 4`), final code | 2,666 passed, 3 skipped (the AC-12-32 migration-ceiling guard moved 23 -> 24 for this plan's migration) |
| Vitest: find page, hook, lib, real service | 28 passed |
| Vitest: existing autocount + menu suites | 670 passed |
| eslint (lane files) | clean |
| Migration 0024 on Postgres 16 | fresh bootstrap and upgrade-from-0023 both build both tables + both indexes; EXPLAIN shows both stored queries using the new indexes |
| Kill tests (mutations, each must fail a test) | GET-only guard, abort check, hint ordering, step dedupe, stop overwrite, re-date source: all caught |

## Results by AC

| AC | Result | Evidence |
|---|---|---|
| 17-01 types | PASS | `test_types_lists_registered_doc_types`, `test_types_for_company_report_connection` |
| 17-02 genericity (fake invoice type) | PASS | `test_generic_doc_type_plugs_in_without_code_change` |
| 17-03 registry drift / duplicates | PASS | `test_registry_*` |
| 17-04 prefix detection | PASS | `test_detect_doc_type_by_prefix`, FE `detectType` test |
| 17-05 feed doors unchanged | PASS | `test_existing_feed_doors_unchanged` + s14 suite green |
| 17-06..09 stored search | PASS | `test_stored_*` (zero vendor calls asserted) |
| 17-10 step plan order / no duplicates | PASS | `test_step_plan_order_and_no_duplicates`, `test_step_dedupe_one_read_per_door_and_day` |
| 17-11 re-date case | PASS | `test_redated_doc_found_by_last_modified`; live: banner "DocDate changed from 01 Oct 2026 to 05 Oct 2026 ... by AIN on 01 Oct 2026, 07:39" (`02-found-redated-1280.png`) |
| 17-12 forward-dated doc | PASS | `test_forward_dated_doc_found_by_doc_date` |
| 17-13 stop at first hit | PASS | read list asserted; live steps tab shows "found" then "skipped" (`04-steps-tab-1280.png`) |
| 17-14/15 hint (1 read next time, stale hint replaced) | PASS | `test_hit_saves_hint_*`, `test_stale_hint_*`; live 2nd search found by DocDate 05 Oct in one read |
| 17-16 not found, no hint | PASS | tests + live "PS202610-0099 was not found ... (23 AutoCount reads)" (`05-not-found-1280.png`) |
| 17-17 per-day errors, all-fail, no connection | PASS | `test_vendor_error_*`, `test_every_step_failing_*`, `test_no_feed_connection_is_409` |
| 17-18 re-attach / in flight | PASS | `test_reattach_and_in_flight`, `test_in_flight_409_names_the_running_job` |
| 17-19 stop | PASS | `test_stop_aborts_at_next_step`, `test_stop_route_aborts_a_pending_job` |
| 17-20 header/lines verbatim | PASS | `test_redated_doc_found_by_last_modified` |
| 17-21 windows + aroundDay | PASS | `test_windows_settings_and_around_day`, `test_settings_put_needs_companies_manage` |
| 17-22 activity log | PASS | `test_vendor_calls_are_activity_logged` (23 rows) |
| 17-23 read-only kill test | PASS | `test_kill_lookup_is_read_only`, `test_kill_non_get_vendor_request_is_refused`; live fake server saw only GETs |
| 17-24 permission / module gate | PASS | `test_routes_need_pull_read`, `test_routes_403_when_module_inactive` |
| 17-25 input validation | PASS | `test_doc_no_validation`, `test_unknown_doc_type_is_422` |
| 17-26 tenant-scoped jobs | PASS | `test_job_lookup_is_tenant_scoped` |
| 17-27 menu entry | PASS | clicked AutoCount > Find document in the sidebar (all three menu arrays carry it) |
| 17-28 stored first, then progress + Stop | PASS | hook tests; JobProgress with Stop while searching |
| 17-29 found view | PASS | `doc-result.test.tsx`; live 1280 + 375 |
| 17-30 re-date banner + history in-range | PASS | live snapshots tab: "01 Oct 2026 to 01 Oct 2026 · DocDate then 01 Oct 2026 · in range: No" (`03-snapshots-tab-1280.png`) |
| 17-31 not found + around date | PASS | live (`05-not-found-1280.png`) |
| 17-32 datetimes + SearchSelect | PASS | `lib/autocount-doc-lookup.test.ts` (vendor wall clock shown as written); system timestamps via `useDatetime` |
| 17-33 E2E real clicks 1280 + 375 | PASS | scrollWidth 1280 = 1280, 375 = 375; `06-found-redated-375.png` |
| 17-34 re-date survives 2nd lookup | PASS | `test_redate_warning_survives_a_second_lookup`; live 2nd search at 375 still shows the banner |
| 17-35 GRN needs sync.read | PASS | `test_grn_needs_sync_read` |
| 17-36 caps + blocking jobId | PASS | `test_running_lookups_capped_per_tenant`, `test_in_flight_409_names_the_running_job`, hook `stopBlocking` test |
| 17-37 host-free step errors | PASS | `test_step_errors_never_carry_the_host` |
| 17-38 aroundDay bound | PASS | `test_around_day_is_bounded` |
| 17-39 stop during hit read | PASS | `test_stop_during_the_hit_read_is_not_overwritten` |
| 17-40 missing-connection warning | PASS | `doc-search-form.test.tsx`; live GRN-0001 warning, Find disabled (`07-grn-no-connection-375.png`) |

## Remarks

- The broken "Default Logo" image in the screenshots is the sandbox checkout missing static
  brand assets under `public/media/`; unrelated to this lane.
- Not verified here: the real AutoCount host (sandbox must not call it). The hand test on a crew
  copy covers that.
