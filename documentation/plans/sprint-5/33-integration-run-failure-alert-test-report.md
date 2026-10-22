# 33 - Integration run-failure alert - test execution report

Lane SS-INTEGRATION-ALERT, head a5367677 (round 2 amended UAC, commit 7ca7f862). Crew test copy http://localhost:3109 (API :8109, DB `foundryx_service_ssintegrationalert`). Evidence: `documentation/plans/sprint-5/33-evidence/`.

Test files: BE `service_backend/tests/test_s33_integration_alerts.py` (evaluator), `test_s33_integration_alert_api.py` (settings + wire), `test_s33_round2.py` (round 2 + round 3); FE `task-editor-view.incident-banner.test.tsx`, `schedule-tab.failure-alerts.test.tsx`, `schedule-tab.failure-alerts.round2.test.tsx`, `use-entities-list-config.failing-badge.test.tsx` (under `service_frontend/app/(protected)/autocount/`).

## Verdicts

| AC | Verdict | Evidence |
|---|---|---|
| AC-33-01 | PASS | `test_s33_integration_alerts.py::test_ac_33_01_*` (consecutive, clean reset, manual / skipped / aborted ignored, push-error-on-SUCCESS, orphaned FAILED, per-integration N, draft / paused); amended terms: `test_s33_round2.py::test_ac_33_01_*` (budget cut-short run is NOT failed and counts as clean; real Sorento push error and budget-note-plus-push-error still failed) |
| AC-33-02 | PASS | `::test_ac_33_02_*` (60 min floor, M x interval, per-integration multiple, activation clock, fresh activation, wedged run); `round2::test_ac_33_07_resume_keeps_activated_at_sets_resumed_at_and_restarts_the_clock` |
| AC-33-03 | PASS | `::test_ac_33_03_*` (sweep runs the check, evaluator crash leaves the sweep result unchanged, one integration's error isolated, second tenant in the same call, deactivated service, suspended and archived tenant) |
| AC-33-04 | PASS | `::test_ac_33_04_*` |
| AC-33-05 | PASS | `::test_ac_33_05_*` (one alert, reminder after 4 h, every 4 h); amended claim: `round2::test_ac_33_05_*` (two overlapping checks send the reminder / recovered notice once; `claim_notice` / `claim_close` guards pinned at repo and evaluator level; kill-tested by mutating `won = True` in each, both fail) |
| AC-33-06 | PASS | `::test_ac_33_06_*` (scheduled and manual clean run, one recovered email, failed manual run does not close); `round2::test_ac_33_06_a_budget_cut_short_run_after_a_failing_streak_closes_the_incident`. Live recovered: DEFERRED (see below) |
| AC-33-07 | PASS | `::test_ac_33_07_*` (pause, deactivate, re-activate fresh); amended: `round2::test_ac_33_07_*` (pause + resume between two checks closes silently as `paused` and a new streak opens a NEW incident; open incident whose integration was deleted is closed; resume leaves `activated_at` alone and sets `resumed_at`) |
| AC-33-08 | PASS | `::test_ac_33_08_*` (same-tenant ACTIVE managers + Also email, case-insensitive dedupe, never another tenant, no recipients) |
| AC-33-09 | PASS (BE) / PASS (live, alert) | `::test_ac_33_09_*` (subjects, body fields, first error line, Runs link, recipient timezone, no "Foundryx"). Live: `live-ac-33-09-email-log-1280.png`, Email log shows 2 rows "Stock balance (SRT) has had no successful run since 26 Sep 05:58 UTC" (stale-rule subject). Reminder and recovered wording: BE only |
| AC-33-10 | PASS | `::test_ac_33_10_*` (outbox only, SMTP monkeypatched to raise, constants) |
| AC-33-11 | PASS (round 1 + 2) / round 3 PENDING | `test_s33_integration_alert_api.py::test_ac_33_11_*` (defaults, save and echo, keep when omitted, boundaries, 422 per field, 403 without manage); `round2::test_ac_33_11_an_alert_only_save_keeps_the_task_active_and_the_gate_stamp`; `round2::test_ac_33_11_unsafe_also_email_addresses_*` (non-ASCII, angle brackets, CR/LF, trailing CRLF). Round 3, red at a5367677 and awaiting the fix: `round2::test_ac_33_11_an_empty_put_body_is_a_422_and_stores_nothing`, `..._a_non_alert_put_without_source_config_is_a_422_not_silently_dropped`, `..._an_also_email_with_a_65_character_local_part_is_a_422` |
| AC-33-12 | PASS | `test_s33_integration_alert_api.py::test_ac_33_12_*` (null when none, etl-task and company detail rows, closed not reported, tenant-scoped, same-id other-tenant row does not leak) |
| AC-33-13 | PASS (vitest + live) | `task-editor-view.incident-banner.test.tsx` 5/5. Live with a real incident (SRT > Stock balance, stale, 6 failed runs): `live-ac-33-13-banner-1280.png`, `live-ac-33-13-banner-375.png`, `live-ac-33-13-view-runs-1280.png` (Runs tab selected, Failed rows) |
| AC-33-14 | PASS (vitest + live) | `use-entities-list-config.failing-badge.test.tsx` 4/4. Live: `live-ac-33-14-failing-badge-1280.png`, `live-ac-33-14-failing-badge-375.png` (scrollWidth 375 = clientWidth) |
| AC-33-15 | PASS (vitest + live) / alert-only save PENDING | `schedule-tab.failure-alerts.test.tsx` 7/7 (load, edit, payload, dirty guard). Amended: `schedule-tab.failure-alerts.round2.test.tsx` 7 tests: cleared field stays empty and Save with an empty field shows the error and does not save were red at the round 2 head and are now in the 23/23 green run; alert-only save not resending the source config likewise. Live: `live-ac-33-15-cleared-field-1280.png` (cleared field value "", Cancel restored 2, no save). Earlier non-mutating pass on the copy: `ac-33-15-schedule-*.png` (1280 and 375, no overflow) |
| AC-33-16 | PASS | Module migration `0031_autocount_task_incident.py` (id 28 chars, single head off 0030, guarded, downgrade) verified by the coder on a throwaway Postgres (upgrade from 0030 with rows; crew SQL first then 0031, no error) and by the reviewer (crew SQL run twice in a rolled-back transaction on the lane Postgres). The crew SQL lives outside the repo by design at `/Users/tehjayson/Documents/foundryx/crew/state/migrations/SS-INTEGRATION-ALERT.sql` (idempotent, additive). The copy DB has `ac_task_incident` (4 indexes) and `resumed_at`. The two guard tests named in the crew brief do not exist in this repo. |
| AC-33-17 | PARTIAL | Live run covers banner, row badge, View runs, cleared-field validation and the outbox / Email log row on the copy. Settings SAVE and the recovered email were not exercised live (non-mutating pass; recovered deferred) |
| AC-33-18 | PASS | `round2::test_ac_33_18_*` (off / on inside 4 h opens silently and its first email follows the cadence from the last notice; flapping sends one alert + one recovered per 4 h; silent incident that recovers sends no recovered email; after 4 h a new incident alerts normally) |
| AC-33-19 | PASS | `round2::test_ac_33_19_*` (CR / LF / control chars collapse to single spaces in the subject; company name and error line HTML-escaped in the body) |
| AC-33-20 | PASS (BE) / copy pending | Index `ix_ac_sync_run_finished` ships in 0031 and the crew SQL; aggregate queries in `TaskIncidentRepository` (reviewer round 2 verified). The copy DB was migrated before the index was added to 0031, so it is missing there until crew re-applies the crew SQL (asked 22 Oct). |

## Suites at a5367677

- `cd service_backend && .venv/bin/python -m pytest -q -n 2 tests/test_s33_integration_alerts.py tests/test_s33_integration_alert_api.py tests/test_s33_round2.py` : 87 passed, 3 failed. The 3 failures are the round 3 red tests (PUT `{}` returns 200, PUT `{"sourceImpl": ...}` returns 200, 65-character local part is accepted), written ahead of the fix.
- `cd service_frontend && npx vitest run incident-banner failure-alerts failing-badge` : 23 passed (4 files).

## Browser commands

`agent-browser --session <own>`: sign in demo@example.com; AutoCount > Companies > SRT > Stock balance; viewports 1280x900 and 375x800; `eval document.documentElement.scrollWidth/clientWidth` after each surface (375/375 on every surface checked); Settings > Email log. Read-only SQL on the copy DB for incident and outbox rows.

## Deferred / pending

- Recovered email and incident close live: DEFERRED pending the crew clearing the copy's row hashes (DELETE_GUARD blocks a clean run).
- AC-33-11 round 3 (empty body, non-alert body, 65-character local part): tests red, fix pending.
- AC-33-20 live index on the copy: after crew re-applies the crew SQL.
