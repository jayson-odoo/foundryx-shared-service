# 68 - Google sign-in in the hosted wizard: test execution report

PR #282 (lane META-LEADS-R2-GOOGLE, part 2), stacked on #280 (part 1, card 68a). UAC:
`68-lead-capture-google-signin-acceptance-criteria.md`. Run 18/11/2026 in the lane's cloud sandbox: local Postgres 16
+ Redis, backend on 8001 with `LEAD_CAPTURE_GOOGLE_SIGNIN=true` and no `GOOGLE_ADS_CLIENT_ID` (simulated Google), a
fresh production frontend build on 3001, Playwright Chromium. The live Google shape is covered by pytest against a
MockTransport Google; nothing left the sandbox. Fake data only.

## Automated

| Suite | Result |
|---|---|
| `tests/test_lead_capture_google_signin.py` (19) | 19 passed (red first: 3208a91e, the one-source-per-account 409 test and the done-screen test each red before their fix) |
| All lead-capture pytest | 179 passed |
| vitest: `lib/google-oauth.test.ts`, `lib/lead-capture-wizard-google-signin.test.ts`, `lib/clipboard.test.ts`, lead-capture + embedded-signup + copy hook | 49 passed |
| tsc / eslint on changed files | clean |
| Migration 0006 on live Postgres (`bootstrap_db`) | applied; `alembic_version_lead_capture` = `0006_lc_google_login` |

## By AC

| ID | Result | Evidence |
|---|---|---|
| AC-68-01 | PASS | Off by default (`test_google_signin_is_off_unless_switched_on`); Google is offered with its sign-in only when the switch is on |
| AC-68-02 | PASS | Steps Channel, Sign in, Account, Forms, Test, Fields; "Sign in to Google" (vitest + evidence 11) |
| AC-68-03 | PASS | Code flow, offline + consent, scopes, random `state`; a code with another state or origin is ignored (`google-oauth.test.ts`); ONE popup shared with Meta |
| AC-68-04 | PASS | Tokens Fernet on the session, never returned or logged (`test_signin_stores_tokens_encrypted_and_returns_accounts_only`) |
| AC-68-05 | PASS | Declined Ads permission = `PERMISSION_DECLINED` with Google wording + Try again |
| AC-68-06 | PASS | No / expired / undecryptable login = `LOGIN_REQUIRED` |
| AC-68-10 | PASS | Only reachable accounts listed; Continue blocked until one is picked (browser) |
| AC-68-11 | PASS | Unknown account = 404 (`test_forms_of_an_account_the_person_cannot_reach_is_404`) |
| AC-68-12 | PASS | Forms by name, no "all forms" option, Connect blocked until one is ticked (browser, evidence 12, 15) |
| AC-68-13 | PASS | One source via the ONE create function; the URL + key written into each ticked form are exactly what the receiver accepts (`test_connect_writes_the_webhook_into_each_ticked_form`) |
| AC-68-14 | PASS | A refused form is named, the rest connect; Try again keeps the same key (`test_one_refusing_form_never_fails_the_rest_and_try_again_keeps_the_key`) |
| AC-68-15 | PASS | Second wizard on the same account = 409 `source_exists` with a plain message (evidence 17). Found in the browser pass on Postgres: it was a 500 on `uq_lc_source_live_account`; fixed to one source per account (like one per Facebook Page), and a reopened source adds forms |
| AC-68-20 | PASS | Fields from the test lead's columns, standard ones matched (part 1 path, reused) |
| AC-68-21 | PASS | Test step guide without the paste frame; passes on Google's test data (evidence 13) |
| AC-68-22 | PASS | Done: account name, Channel Google Ads, Signed in as, dd/mm/yyyy h:mm am/pm (evidence 14, 16) |
| AC-68-30 | PASS | Gateway door `/google/login`, `/google/logins/{loginId}/accounts/{accountId}/forms`, `/sources/google/connect`; loginId key- and tenant-scoped |
| AC-68-31 | PASS | Another session cannot use this session's Google login |
| AC-68-32 | PASS | Consumer guide section 8b names every new route (guide test) |
| AC-68-40 | PASS | 1280 light + 375 dark, no horizontal scroll, tenant branding only |
| AC-68-41 | PASS | Every step ends in content, a warning ("no lead forms yet" + Check again) or an error with an action |
| AC-68-42 | OPEN | Owner hand test (after #280's) |
| AC-68-43 | DEFERRED | Live Google Ads account, after spike S-GOOGLE and the owner's Google setup |

## Open

- Live Google facts G1-G6 (plan 68 section 7) are unconfirmed until S-GOOGLE; the switch stays off until then.
- The source keeps the Google refresh token (Fernet) for later health checks; no health check runs yet.
