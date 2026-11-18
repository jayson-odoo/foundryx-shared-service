# 68a - Google Ads receiver + guided path: test execution report

Lane META-LEADS-R2-GOOGLE, part 1. Card: `68a-lead-capture-google-receiver-card.md`. ACs: AC-64-40/41/44 + card
rules R1-R10. Run 18/11/2026 in the lane's cloud sandbox: local Postgres 16 + Redis, backend on 8001, a fresh
production frontend build on 3001, Playwright Chromium. Fake data only. Google's POST was simulated with Google's
documented body (no Google account involved on this path).

## Automated

| Suite | Result |
|---|---|
| `tests/test_lead_capture_google.py` (22: create, receive, map, repeat, refusals, throttle, 410, module off, rotate, wizard) | 22 passed |
| All lead-capture pytest (`tests/test_lead_capture_*.py`) | 160 passed |
| vitest lead-capture + embedded-signup (incl. `lib/lead-capture-wizard-google.test.ts`, 5) | 32 passed |
| tsc + eslint on changed files | clean (2 pre-existing a11y warnings on the Sources list actions cell) |

Red proof: `ec009179` (16 receiver tests failing before the code), `7d286cb1` (5 wizard tests failing).

## Browser (real clicks)

| ID | Scenario | Precondition | Steps | Expected | Actual | Result |
|---|---|---|---|---|---|---|
| AC-64-40 | Copy step | Gateway key with origin localhost:3001, connect session URL | Open URL, click "Google Ads" | URL + key shown, each with Copy; Continue blocked until both copied | As expected, reason "Copy the URL and the key first." | PASS |
| AC-64-41 / R5 | Google test data passes Test | Copy done | Continue; POST Google's body with the copied key to the copied URL | 200; Test step ticks; source LIVE | 200; "Test lead received"; LIVE in the Sources list | PASS |
| R7 | Fields from the test lead | Test passed | Look at the Fields step | Google's labels; Full Name/User Email/User Phone auto-matched; custom question to Lead notes | As expected (evidence 02, 05) | PASS |
| AC-64-17 | Done screen | Fields saved | Finish setup | Channel "Google Ads", who, when (dd/mm/yyyy, h:mm am/pm), waiting for first real lead | As expected (evidence 03, 06) | PASS |
| AC-64-18 | 375 / 1280, light / dark | - | Same run at 1280 light and 375 dark | No horizontal scroll on every step | First run measured the Done screen only and missed the Copy step (704 px at 375, crew pass 8fc0c469); fixed and re-measured on every step, see the fix round below | PASS (after fix) |
| R10 | Staff Sources list | Two Google sources | Sign in as staff, open Lead Capture > Sources | Channel "Google Ads", status Live | As expected (evidence 07) | PASS |
| R8 | New key action | Google row | Open the row's actions | "New key" only (no Reconnect / Map fields for Google) | `["New key"]` (evidence 08) | PASS |
| AC-64-44 | Old key refused after rotate | - | pytest `test_rotate_key_kills_the_old_key_at_once`, `test_wizard_creates_its_google_source_once_and_binds_it` | old key 403, new key 200 | As expected | PASS |

## Crew pass 8fc0c469 fix round (18/11/2026)

| Item | Red (build of 8fc0c469) | Green (fix build) |
|---|---|---|
| 375 px, Copy step: `document.documentElement.scrollWidth` (plain-http origin, real clicks) | 704 | 375 |
| 375 px sweep, every step: Channel, Copy, Test, Fields (long custom question), Done, Facebook sign-in | Copy 704, Fields 469 | all 375 |
| Google test lead sent BEFORE Continue | stayed on "Waiting for the test data" | Fields opens about 3 s after Continue (hook test red first, then green) |

Cause: `<body>` is a flex row and the public page shell (`app/(public)/public-branded-shell.tsx`) had no
`min-w-0`, so the one-line URL's natural width widened the whole page; fixed at the shell (every public page) and on
the wizard wrapper. Test baseline: taken when the URL + key are shown, not at Continue.

## Open (logged, not in this part)

- Two Google sources both show the name "Google Ads"; there is no rename yet (the Facebook path names the source
  after the Page). Follow-on: let the Copy step or the Sources list rename a source.
- "Map fields" for a Google source after setup is not offered in the staff list (the gateway
  `PUT /sources/{id}/field-map` works). Follow-on: open the wizard straight on Fields for a Google source.
- The Done screen's "Test lead form" reads "-" for Google (Google sends no form name on this path).
