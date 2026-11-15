# S-META result: Meta lead facts on the Foundryx Page

Lane META-S-META, 14-15/11/2026. Every row comes from a real Graph API call from the owner's Mac against the
existing app "Foundryx WA App" (id 1425562942670564, Live) and the Foundryx Page (id 1407353105803175, owned by the
"Foundryx" portfolio). Calls ran through a probe that sends the key in a header and redacts every token from its
output. Plan: `S-META-spike-plan.md`. Fixtures: `fixtures/` (ids and personal values replaced by fakes).

Legend: **Confirmed** = matches section 3. **Changed** = section 3 was wrong or incomplete; plan 64 edit named.
**Open** = not answered in this lane (reason named).

| # | Fact | Result | Evidence |
|---|---|---|---|
| F1 | Graph API version | **Changed.** Latest served is **v27.0**; v28.0 and up answer "Unknown path components". This app's default (unversioned) is **v25.0**. Calls on v18.0 to v24.0, including the backend's v19.0 and the frontend's v23.0, are silently run as v25.0 (`facebook-api-version` response header). New webhook fields take v25.0 | `GET /v{18..29}.0/{app}` |
| F2 | App webhooks before the test | **New.** The app had **no Page webhook**; only `whatsapp_business_account` (callback = production omnichannel). Messenger on this app receives no webhooks today | `GET /{app}/subscriptions` |
| F3 | Permissions | **Changed.** Before the test the app had no Page or lead permission (approved: `email`, `public_profile`, `whatsapp_business_management`, `whatsapp_business_messaging`; also no `pages_messaging`). The owner added use case **"Capture & manage ad leads with Marketing API"**: `leads_retrieval`, `pages_manage_ads`, `pages_read_engagement`, `pages_show_list` then read "Ready for testing"; `pages_manage_metadata` had to be added by hand. `GET /{app}/permissions` lists approved (`live`) permissions only. All five go into App Review. Whether `business_management` / `ads_management` are needed is **Open**: the owner's token carries both, and the five-scope token (optional step B) was skipped | `GET /{app}/permissions`; owner's App Review screen; `debug_token` |
| F4 | System-user token for Page leads (decision 2) | **Confirmed, with two conditions.** A `SYSTEM_USER` token works: Page token via `GET /{page}?fields=access_token`, form list, subscribe, test lead, and lead read with full `field_data`. (1) The Page must be **assigned to the system user as an asset** in the portfolio; scopes alone give nothing (`/me/accounts` empty, `(#10) User has insufficient privileges on the page.`). (2) Page edges need the **Page token**: `leadgen_forms` with the system-user token = `(#190) This method must be called with a Page Access Token`. The lead itself (`GET /{lead}`) reads with either token. Tested with a token the owner generated for a system user in the Foundryx portfolio; the Login for Business "system-user" config that a customer would go through is **not tested yet** (needs a config id in the dashboard) | `debug_token`; `/me/assigned_pages`; calls above |
| F5 | R1: does `POST /{page}/subscribed_apps` replace the list | **Confirmed: it replaces.** Before: no app subscribed. `subscribed_fields=leadgen,feed` gave `[leadgen, feed]`; then `subscribed_fields=leadgen` gave `[leadgen]` (feed dropped). The shared subscribe function (D15) must read and send the union | `GET`/`POST /{page}/subscribed_apps` |
| F6 | Webhook carries ids only | **Confirmed.** `object: page`, `changes[].field: leadgen`, value = `leadgen_id, page_id, form_id, created_time` only; `ad_id` / `adgroup_id` are absent for a test lead (no ad). `X-Hub-Signature-256` verified with the app secret on all 3 deliveries; `X-Hub-Signature` (SHA-1) is sent too; User-Agent `Webhooks/1.0`. Delivered within about 5 s | `fixtures/leadgen-webhook-test-lead.json` |
| F7 | Test-lead API, one at a time | **Confirmed, plus a quirk.** `POST /{form}/test_leads` (Page token, no body) creates a lead with Meta dummy values. A second POST = error 2 / subcode **1892058** "Test lead already exists for this form." `DELETE /{lead}` with the Page token answers error 2 / subcode **1892035** "Could Not Delete Lead" **but the lead is deleted** (seen twice; `GET /{form}/test_leads` empty, then a new POST works). With the system-user token DELETE = `(#110) Can only delete leads owned by session user.` E7 must re-read `GET /{form}/test_leads` after a delete error instead of trusting it | `fixtures/meta-errors.json` |
| F8 | New forms deliver with no action | **Confirmed.** Form "S-META test 2" was created after the Page was subscribed; its test lead arrived by webhook with no new subscribe call. Forms can be created by API with the Page token (`POST /{page}/leadgen_forms`) | receiver log |
| F9 | Instagram leads via the Page | **Open.** The Foundryx Page has no linked Instagram account, and an Instagram-placement lead needs a running ad (spend = owner's call). Test leads return `is_organic: true` and no `platform` value | `GET /{page}?fields=instagram_business_account` (absent) |
| F10 | Token lifetime | System-user token and the Page token made from it: `expires_at 0`, `data_access_expires_at 0` (never). Person-based token **Open** (step 4 not done) | `debug_token` |
| F11 | Leads Access error 103 | **Confirmed default.** Both tokens read leads with no Leads Access setup; no 103 seen. Restricting access on purpose was not tested | lead reads |
| F12 | Rate-limit headers | **Confirmed.** Lead and form reads return `x-business-use-case-usage: {"<page_id>":[{"type":"leadgen","call_count":..,"total_cputime":..,"total_time":..,"estimated_time_to_regain_access":0}]}`, a per-Page `leadgen` bucket; app calls return `x-app-usage` | response headers |
| F13 | Lead Ads Terms | **New.** `GET /{page}?fields=leadgen_tos_accepted` = `false` on the Foundryx Page, yet forms and test leads work. Real ad leads need the Page to accept Meta's Lead Ads Terms; the wizard can read this field and show a "accept the terms" step | `GET /{page}` |

App roles: 2 administrators, 1 developer (`GET /{app}/roles`); only they get real data while permissions are at
Standard access.

## State left behind (to clean up after the lane)

- App: `page` webhook object, field `leadgen`, callback = temporary tunnel. Removed at lane end with
  `DELETE /{app}/subscriptions?object=page` (back to WhatsApp only).
- Page: Foundryx WA App subscribed with `[leadgen]`; forms "S-META test 1" and "S-META test 2"; one test lead on
  form 2. Kept for lanes 2 and 6 unless the owner wants them gone.
