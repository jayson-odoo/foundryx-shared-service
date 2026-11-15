# S-META result: Meta lead facts on the Foundryx Page

Lane META-S-META, 14-15/11/2026. Every row comes from a real Graph API call from the owner's Mac against the
existing app "Foundryx WA App" (id 1425562942670564, Live). Calls ran through a probe that sends the key in a header
and redacts every token from its output. Plan: `S-META-spike-plan.md`. Fixtures: `fixtures/` (personal data fake).

Legend: **Confirmed** = matches section 3. **Changed** = section 3 was wrong or incomplete; plan 64 edit named.
**Pending** = waiting on an owner step. **Not testable** = needs something outside this lane (named).

| # | Fact | Result | Evidence |
|---|---|---|---|
| F1 | Graph API version | **Changed.** Latest served version is **v27.0**; v28.0 and up answer "Unknown path components". This app's default (unversioned) is **v25.0**. Calls on v18.0 to v24.0, including the backend's v19.0 and the frontend's v23.0, are silently run as v25.0 (`facebook-api-version: v25.0` response header). The WhatsApp webhook fields are on v25.0 | `GET /v{18..29}.0/{app}?fields=name`, response header per version |
| F2 | App webhooks today | **New fact.** The app has **no Page webhook**. Its only webhook object is `whatsapp_business_account` (fields `messages`, `phone_number_name_update`, `message_template_status_update`, callback = production omnichannel). So Messenger on this app receives no webhooks today, and R1 cannot hit a running Messenger | `GET /{app}/subscriptions` |
| F3 | Permissions on the app | **Changed.** Before the test the app had no Page or lead permission at all; only `email`, `public_profile`, `whatsapp_business_management`, `whatsapp_business_messaging` (status `live`). The owner added use case **"Capture & manage ad leads with Marketing API"** (14/11 23:25): `leads_retrieval`, `pages_manage_ads`, `pages_read_engagement`, `pages_show_list` then read "Ready for testing"; `pages_manage_metadata` was not in that use case and needed "+ Add to app review" by hand. `GET /{app}/permissions` still lists only the four `live` ones after the add, so that edge shows Advanced (approved) access only, not Standard. All five lead permissions go into App Review. Pending: scopes per token kind | `GET /{app}/permissions` before and after; owner's App Review screen; `debug_token` pending |
| F4 | System-user token reads Page leads (decision 2) | Partly. The owner's token (15/11 ~13:08) is `SYSTEM_USER` for Foundryx WA App with all five lead scopes. A system user must also be **given the Page as an asset** in the portfolio: with no Page assigned, `GET /me/accounts` is empty and `GET /{page}/leadgen_forms` answers `(#10) User has insufficient privileges on the page.` Ticking scopes when generating the token does not give access to a Page. Plan 64 note: a system-user connection needs the Page shared to that system user, which in a customer's case means a business-to-business step on the customer's side. Lead read pending the asset | `debug_token`; `GET /me/accounts`, `/me/assigned_pages`, `/{page}/leadgen_forms` |
| F5 | R1: subscribe replaces the field list | Pending (Page token) | |
| F6 | Webhook carries ids only | Setup done, payload pending (Page token). Owner yes 15/11 ~09:00. `POST /{app}/subscriptions object=page fields=leadgen` with the app token, callback = a temporary cloudflared tunnel to a local receiver: Meta sent the GET handshake (`hub.mode=subscribe`, our verify token, challenge echoed) and the app now lists `page` active with `leadgen@v25.0`; the `whatsapp_business_account` object was untouched. The new field took the app's default version (v25.0), not the latest. There is no API to fire a sample (`POST /{app}/subscriptions_sample` = "Unknown path components") | `POST` + `GET /{app}/subscriptions`; receiver log |
| F7 | Test-lead API, one at a time | Pending (Page token) | |
| F8 | New forms deliver with no action | Pending | |
| F9 | Instagram leads via the Page | Pending | |
| F10 | Token lifetime and what breaks it | System-user token: `expires_at 0`, `data_access_expires_at 0` (never expires, no 90-day data-access window). Person-based token pending (step 4) | `debug_token` |
| F11 | Leads Access error 103 | Pending | |
| F12 | Rate-limit headers on lead reads | Pending | |

App roles today: 2 administrators, 1 developer (`GET /{app}/roles`). Only these people get real data while a
permission is at Standard access.
