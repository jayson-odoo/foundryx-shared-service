# Plan 68 - Lead Capture release 2: Google sign-in in the hosted wizard

Lane META-LEADS-R2-GOOGLE. UAC: `68-lead-capture-google-signin-acceptance-criteria.md` (the contract; this plan
fulfils it). Builds on plan 64 (on PR #236, branch `claude/meta-leads-integration-whxmlv`) and lane L-C (#262,
merged as b0a55d2a).

## 1. Why

Owner D5 (plan 64): release 1 = Facebook + Instagram, Google sign-in in release 2. Owner 17 Nov: "meta google sign in
we can add that". Plan 64 section F only has a guided Google Ads path: the customer pastes our inbound URL and a key
into each Google Ads lead form by hand (AC-64-40/41). This lane adds the automatic path: on the wizard's Sign in step
the customer picks Google, signs in with Google, picks the Google Ads account, ticks lead forms, and the Shared
Service writes the webhook URL + key into those forms for them. No copy and paste.

## 2. What L-C already gives us (reused, not rebuilt)

| Piece | Where | Reuse |
|---|---|---|
| Step engine (Channel, Sign in, Page, Forms, Fields, Test) | `service_frontend/lib/lead-capture-wizard.ts:11-28` | Step labels/questions become per channel; no new engine |
| Connect session + scoped wizard token | `services/connect_session_service.py:186,245,305`, `app/scoped_tokens.py` | Unchanged: Google steps ride the same `lead_capture_embed` token and `WizardPrincipal` |
| Login token stored Fernet on the session row, opaque id on the wire | `connect_session_service.py:354-417`, `models.py:272-304` | Same rule for the Google refresh token |
| Channel list (only channels configured on this server) | `connect_session_service.py:345` | Google added when its OAuth client is set (or simulated) |
| The ONE OAuth popup with random `state` + callback relay | `service_frontend/lib/embedded-signup.ts:103`, `app/wa-callback/page.tsx` | Split into a provider-free `launchOAuthPopup(dialogUrl)`; `launchMetaOAuth` and the new `launchGoogleOAuth` only build the dialog URL. Same callback page, same state check |
| Gateway "own wizard" login door (`loginId`) | `connect_session_service.py:428-470`, `routers/gateway.py` | Google gets the same two calls so a product can build its own wizard |
| Field map, test lead, done screen, postMessage contract | `routers/wizard.py:176-235`, `lib/lead-capture-post-message.ts` | Unchanged; Google questions feed the same field-map step |
| Fernet secrets | `app/secrets.py` | Unchanged |

## 3. Decisions (proposed, owner go needed)

- **G-D1 Hard dependency on the Google Ads receiver (plan 64 L5, AC-64-40/41/44).** The sign-in only automates
  writing our URL + key into the forms. The receiver (`POST /public/lead-capture/in/{sourceKey}`, `google_key` check,
  Google payload parse, `is_test`) must exist first. It is not in this lane. See section 7 for the order ask.
- **G-D2 Scope.** OAuth scope `https://www.googleapis.com/auth/adwords` only (plus `openid email` to show who signed
  in on the done screen). `access_type=offline` + `prompt=consent` so a refresh token is issued. No other Google API.
- **G-D3 Storage.** New nullable columns on `lc_connect_session`: `google_encrypted` (Fernet `{refreshToken,
  email, dev}`) + `google_expires_at` (same 30 min TTL as the Facebook login). The connected `lc_source` (platform
  `google`) keeps the refresh token Fernet in its existing encrypted credentials column, used later for health and
  re-apply. Migration 0006 (module Alembic, id under 32 chars), `ADD COLUMN IF NOT EXISTS` style. No core table
  change. No backfill needed: new nullable columns on a short-lived session table.
- **G-D4 Steps for Google.** Channel = Google -> Sign in ("Continue with Google") -> Account (which Google Ads
  account; one account = chosen automatically and folded, like AC-64-21) -> Forms (tick lead forms; "All forms,
  including new ones" is NOT offered, because Google sends no "new form" event: the option list shows only what
  works, foolproof-UI) -> Fields -> Test -> Done. The step engine gets the step names per channel; Page is renamed
  Account for Google.
- **G-D5 Writing the webhook.** On Connect, for each ticked lead form, a Google Ads API mutate sets the form's
  webhook delivery to `https://<host>/public/lead-capture/in/{sourceKey}` with the source's `google_key`. A form
  that refuses (no edit right, policy) is named in the result and the rest go through (standing rule: one bad line
  never fails a batch); the source stays connected with that form listed as "Not connected" + "Try again".
- **G-D6 Test step.** The Google Ads API has no "send a test lead" call (to confirm in the spike, G5). The Test step
  for Google waits for Google's own "Send test data" (button in the Google Ads form editor) and shows the guide
  player for it; the received `is_test: true` lead passes the step (AC-64-41 behaviour).
- **G-D7 Simulated mode.** Without `GOOGLE_ADS_CLIENT_ID` the Google flow is simulated (any code works, two demo
  accounts, two demo forms), the same rule as Facebook without `META_APP_ID`. Dev, CI and the crew test copy run
  simulated; no Google call ever leaves the sandbox.
- **G-D8 Config.** Backend `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_DEVELOPER_TOKEN`,
  `GOOGLE_ADS_LOGIN_CUSTOMER_ID` (optional, manager account) in `Settings`, `.env.example`, compose and deploy. The
  wizard gets the client id through `GET /wizard/context` (like Facebook's app id), never from a build-time env.
- **G-D9 Guided fallback stays.** If the customer has no edit rights or declines the scope, the wizard offers the
  guided path from L5 (paste URL + key). One main button per step; the fallback is the secondary action.

## 4. Backend

`modules/lead_capture/`:
- `google_ads.py` (new, mirrors `meta_leads.py`): `GoogleAdsClient` over httpx (MockTransport in tests) with
  `exchange_code`, `refresh`, `userinfo_email`, `list_accessible_customers`, `customer_names`, `list_lead_forms`
  (GAQL on `asset` where type = LEAD_FORM), `form_questions`, `set_webhook(form, url, key)`. Dev stubs when
  simulated. Errors map to typed `GoogleAdsError(code)`.
- `connect_session_service.py`: `google_login_config()`, `_google_login` (exchange, scope check -> `PERMISSION_DECLINED`
  E1 wording for Google, store Fernet), `wizard_google_accounts`, `wizard_google_connect(account, form_ids)` which
  creates the source through the L5 source function (ONE shared connect function, like `connect_facebook`) and then
  calls `set_webhook` per form. `channels()` adds Google.
- `routers/wizard.py`: `POST /wizard/google/login`, `GET /wizard/google/accounts`, `GET /wizard/google/accounts/{id}/forms`,
  `POST /wizard/google/connect`. All under the existing `get_wizard` dependency; the account id is checked against
  the signed-in person's accessible customers on every call (never trusted from the client).
- `routers/gateway.py`: `POST /logins/google` + the account/forms/connect calls with `loginId` (own-wizard door).
- Guide: `documentation/lead-capture/consumer-integration-guide.md` section 7 gains Google (same commit as the
  routes; the guide-names-every-route test AC-64-66 enforces it).

## 5. Frontend

- `lib/embedded-signup.ts`: extract `launchOAuthPopup`; new `lib/google-oauth.ts` builds Google's dialog URL
  (`accounts.google.com/o/oauth2/v2/auth`, `response_type=code`, scopes, `state`, `access_type=offline`,
  `prompt=consent`) and calls it. The callback page accepts Google's redirect too (same relay, same state check;
  Google origins are never trusted for messages, only our own callback).
- `lib/lead-capture-wizard.ts`: per-channel step defs (`stepsFor(channel)`), Account step answer, Google forms rule
  (at least one ticked).
- `hooks/use-lead-capture-wizard.ts`: `signIn` branches on channel; `services/lead-capture-wizard-service.ts` gains
  the four Google calls.
- `wizard-steps.tsx`: "Continue with Google" button (Google's own mark is not shipped; a neutral icon + the word
  Google, white-label rule), Account step (`SearchSelect`), Google forms checklist with per-form result, Google Test
  guide.
- No new page, no new list. Sources/Leads lists already show any platform (verify Google rows show "Google").

## 6. Tests

- Backend red first (`tests/test_lead_capture_google.py`): code exchange + store Fernet, scope declined = E1,
  expired login = `LOGIN_REQUIRED`, account not in the person's list = 404, connect writes the webhook per form,
  one refusing form does not fail the rest, cross-tenant/cross-session isolation, gateway `loginId` door, simulated
  mode makes zero network calls.
- Frontend vitest: `stepsFor('google')`, forms rule, `launchOAuthPopup` state check (shared by Meta + Google),
  Google dialog URL.
- Browser: real clicks through the simulated Google path at 375 px and 1280 px, light and dark.

## 7. Follow-on lanes (not this lane)

| Lane | What | Needs |
|---|---|---|
| S-GOOGLE (spike, S) | Confirm G1 webhook delivery is writable on an existing lead form via the API, G2 developer token level needed (Basic), G3 OAuth consent screen verification for the `adwords` scope (unverified = 100-user cap + warning screen), G4 manager-account `login-customer-id`, G5 no API test lead, G6 `lead_form_submission_data` usable for backfill | Owner: Google Cloud project, OAuth client, Google Ads developer token application, a test Google Ads account with a lead form |
| L5-GOOGLE (M) | Google Ads receiver + guided paste path (AC-64-40, 41, 44) | Plan 64 |
| R2-GOOGLE (this, M) | Google sign-in on top of L5-GOOGLE | S-GOOGLE, L5-GOOGLE |
| L5-WEB (M) | Website form: embed snippet + JSON POST + rate limit (AC-64-42, 73) | L5-GOOGLE receiver shape |
| L6 (L) | WhatsApp ads (Click-to-WhatsApp) | Plan 64 L6 |

## 8. Risks

- Google's OAuth verification for the `adwords` scope can take weeks; until verified, the consent screen warns and
  caps users. Release to real customers is gated on it (spike G3), not on this code.
- If G1 fails (webhook not writable by API), G-D5 falls back to: sign-in reads accounts and forms (no typing of
  ids), then the guided copy step per form. The UAC marks the affected ACs.
