# META-LIVE-RUN plan: live run of the Lead Capture prototype (PR #245)

Owner, 15 Nov: "i need the prototype working". Goal: one Meta TEST lead from the Foundryx Page lands (1) stored in
FSS and (2) pushed into the Sorento CRM Project Leads with Channel = Meta. Fix round on PR #245, same branch.

## Inputs
- PR #245 head (lane P), its crew-handtest steps, `documentation/lead-capture/consumer-integration-guide.md`.
- S-META result (`documentation/plans/meta-leads/S-META-result.md` on the plan branch): F4 (system-user token +
  Page asset, Page edges need the Page token), F5 (`subscribed_apps` replaces the field list), F6 (leadgen = ids
  only, sha256 signature), F7 (one test lead per form, DELETE quirk 1892035).
- CRM receiver: sorento-crm PR #2449 (META-CRM-RECEIVER), used for step 6 once crew says its head is ready.

## Steps (PASS/FAIL table goes to a crew-note on #245)
1. FSS test copy on the #245 head (crew testenv for this lane), `bootstrap_db` migrates `app_lead_capture`;
   Meta app id + secret and a fresh verify token added to the copy's backend `.env` only; public HTTPS tunnel
   (cloudflared quick tunnel) to the copy's backend.
2. App `page` webhook object -> `https://<tunnel>/omnichannel/webhooks/lead`, field `leadgen` (app token by API).
   Record the app's subscription list before; restore it after (S-META left it WhatsApp-only).
3. Install Lead Capture on the test tenant, mint the `fxl_live_` key, register the consumer webhook, connect the
   Foundryx Page via `POST /lead-capture/sources/facebook` with the system-user token.
4. Clear the old test lead on the test form, then `POST /{form}/test_leads` (Meta dummy answers).
5. Lead stored in FSS: row id + mapped fields (masked) from the pull API and the DB row.
6. Point the Sorento endpoint (per-product URL + `whsec_` secret) at the CRM copy of #2449; show the lead in
   Project Leads (Channel = Meta) + the in-app notification.

## Rules
- TEST leads only; real ad leads are never read or touched.
- Secrets (app secret, system-user token, Page token, `fxl_live_` key, `whsec_` secret) come through crew's secret
  channel or live only in the copy's `.env` / process memory; never in files under git, logs, PR comments or chat.
- Leads are PII: PR comments show masked values only.
- Any Meta dashboard click -> ONE crew-ask with the exact click path.

## Cleanup
- `DELETE /{app}/subscriptions?object=page` once the copy goes away (Meta stops calling a dead URL); verify the app
  list matches the recorded "before" state.
- Tunnel stopped; Page token and captures removed from the scratchpad; copy `.env` Meta lines removed.

## Code changes
Only if the live run finds a defect in #245: red test first, then the fix, pushed to this branch.
