# S-META spike plan (release 1, lane 1)

Lane META-S-META, 14/11/2026. Goal: confirm or correct every "(unconfirmed)" Meta fact in
`PLAN-meta-lead-ads-14nov.md` section 3 (and 10.2) with real Graph API calls from the owner's Mac, on the Foundryx
Page, with the existing app ("Foundryx WA App", id 1425562942670564, Live) in its current mode.

Result goes to `S-META-result.md` (one row per fact: confirmed / changed / not testable, with the evidence call).
Payload fixtures go to `documentation/plans/meta-leads/fixtures/` with every personal value replaced by a fake one.
Plan 64 (`documentation/plans/sprint-5/64-lead-capture*.md`) is edited only where a fact changed.

## Facts and how each is checked

| # | Fact (section 3 row) | Check | Needs |
|---|---|---|---|
| F1 | Current Graph API version; repo default v19.0 still served? | Call the same read on v19.0 .. v26.0, read the `facebook-api-version` response header and errors | App token |
| F2 | App's Page webhook fields today (callback, fields) | `GET /{app}/subscriptions` (read only) | App token |
| F3 | Permission list per use, access level per permission | `debug_token` on the owner's token (scopes, granular scopes); access level from the dashboard (Review > Permissions and features) if no API exposes it | Owner token |
| F4 | System-user token reads Page leads (decision 2) | System-user token -> Page token -> `GET /{page}/leadgen_forms`, `GET /{lead}` | Owner: system-user token |
| F5 | R1: does `POST /{page}/subscribed_apps` replace the field list | Read the list, POST union + `leadgen`, read; POST union without `leadgen`, read; POST union + `leadgen` again. The fields already there are in every POST, so Messenger is never dropped | Page token |
| F6 | Webhook carries ids only (`leadgen_id, page_id, form_id, ad_id, adgroup_id, created_time`) | Receive one real `leadgen` delivery, check `X-Hub-Signature-256` | App field `leadgen` (owner yes) + receipt (see below) |
| F7 | Test-lead API and one-at-a-time limit | `POST /{form}/test_leads` twice; read the error; `DELETE /{lead}`; POST again | Page token, one form |
| F8 | New forms on a subscribed Page deliver with no action | Create a new form (API, or owner), submit a test lead, see the webhook | F6 receipt |
| F9 | Instagram leads arrive through the Page | Lead node fields (`platform`); a real IG-placement lead needs a running ad (spend = owner decision) | Page token |
| F10 | Token lifetime and what breaks it | `debug_token` `expires_at` / `data_access_expires_at` per token kind | Owner token |
| F11 | Leads Access restriction error 103 | Read `GET /{page}/leadgen_forms` and lead with each token; note any 103. Restricting access on purpose is not done | Page token |
| F12 | Rate-limit headers on lead reads | Record `x-business-use-case-usage` / `x-app-usage` / `x-page-usage` | Page token |

## Safety

- App id and secret come only from `~/.config/crew/meta-app.env`; tokens live in chmod 600 files under
  `~/.config/crew/` or the session scratchpad, never in argv, logs, commits, PRs or crew notes. The probe script
  redacts every token-shaped string before printing.
- Every Page subscribe call sends the union of the fields already there plus the test field.
- No change to the app's settings, products, mode or webhook callback URL without the owner's yes relayed by crew.
- Webhook receipt: the app has one Page callback URL (production). Receiving at a local tunnel means either the
  owner switches that URL for the test window (production Messenger inbound must be forwarded or paused), or the
  owner confirms delivery in the Lead Ads Testing Tool's status view while production keeps the URL. Crew decides
  with the owner; see the crew ask.

## Owner steps (one crew ask, target 20 minutes)

Written as click-by-click steps in the ask: Page id + one Instant Form, a system-user token saved to a chmod 600
file, his yes for the `leadgen` app field, one Lead Ads Testing Tool submission, one new form.
