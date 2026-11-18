# EcoHub: receive Facebook leads

One page for the EcoHub team. All data below is fake. Full contract, if you ever need more:
`documentation/lead-capture/consumer-integration-guide.md` (section 7 covers the Connect button).

## How a lead reaches EcoHub

1. Someone fills in a lead form on a Facebook ad.
2. Facebook tells Foundryx Shared Service within seconds. The Shared Service reads the answers and keeps them.
3. EcoHub collects it, either within a minute (the job below) or at once (a push, optional).

## Once, done by Foundryx

1. Turns on Lead Capture for the EcoHub account.
2. Gives ecohub-backend one key, `fxl_live_...`. Keep it in the backend environment only, never in the browser.
3. Registers EcoHub's web address on that key (for example `https://app.ecohub.example`), so the Connect window can
   report back to EcoHub.

## What EcoHub builds

### A. A "Connect Facebook Page" button (in EcoHub settings)

When the user clicks it:

1. ecohub-backend asks for a one-time link:

   ```
   POST https://<shared-service-host>/be/api/v1/lead-capture/connect-sessions
   Authorization: Bearer fxl_live_...
   {"returnOrigin": "https://app.ecohub.example"}
   -> 201 {"url": "https://<shared-service-host>/public/lead-capture/connect#s=...", "expiresAt": "..."}
   ```

   The link works once, for 10 minutes. Ask for a new one on every click.
2. The EcoHub page opens `url` in a popup and waits for one message from the Shared Service:

   ```js
   const popup = window.open(url, 'lead_capture', 'popup,width=720,height=860');
   window.addEventListener('message', (event) => {
     if (event.origin !== 'https://<shared-service-host>') return;
     if (event.data?.type === 'lead-capture:done' || event.data?.type === 'lead-capture:closed') {
       refreshConnectedPages();   // GET /be/api/v1/lead-capture/sources
     }
   });
   ```
3. Show the connected Pages from `GET /be/api/v1/lead-capture/sources`: the Page name and its state (Live, Waiting
   for test lead, Needs reconnect, Disconnected).

### B. One scheduled job that collects leads

Every minute, ecohub-backend asks for new leads and creates them in Leads.

```
GET https://<shared-service-host>/be/api/v1/lead-capture/leads?cursor=<saved cursor>
Authorization: Bearer fxl_live_...
```

On the very first run use `?since=2026-11-18T00:00:00Z` instead of `cursor`.

The answer:

```json
{
  "data": [{
    "id": "e3a10000-0000-0000-0000-000000000001",
    "formName": "Year-end promo",
    "createdAt": "2026-11-18T03:20:00Z",
    "isTest": false,
    "fields": {"name": "Test Person", "phone": "+60120000000", "email": "test.person@example.com",
               "notes": "property_type: Condominium\nbudget: RM 500k - 800k"}
  }],
  "nextCursor": "c_000123",
  "hasMore": false
}
```

The job, in four steps:

1. For each item, create a Lead (status New, source Facebook):
   - `name` -> Client Name;
   - `phone` -> Phone;
   - `email` -> Email;
   - `notes` -> Remarks.
2. Save `id` on the Lead with a unique constraint. If the id already exists, skip the item. This means a re-run
   never creates a duplicate.
3. Save `nextCursor` and use it on the next run.
4. If `hasMore` is true, call again straight away.

Leads marked `isTest: true` are Meta's dummy answers: show them, or skip them, as EcoHub prefers.

## What the EcoHub customer does (about 2 minutes)

**Who:** the person at the customer's company who is an admin of the Facebook Page that runs the ads. They use
their own Facebook account.

1. In EcoHub settings, click **Connect Facebook Page**. A window opens with EcoHub's name and logo.
2. **Facebook.** Click Continue with Facebook and sign in. Facebook asks to share their Pages and lead forms with
   the app. They leave every box ticked and click Save.
3. **Page.** They pick the Page that runs the ads and click Connect Page.
4. **Forms.** They keep "All forms, including new ones", or tick only some forms, and click Save forms.
5. **Fields.** They match form questions to EcoHub fields and click Save fields. Anything not matched goes into
   Remarks.
6. **Test.** They click Send test lead. Within about a minute a test lead shows in EcoHub Leads, and the Page turns
   Live.
7. **Done.** The window closes and the Page shows in EcoHub as Live. From then on every lead from every ad on that
   Page arrives by itself. Nothing is needed per new ad.

What they might see instead:

| Screen | What to do |
|---|---|
| "Facebook did not give permission to read leads" | Click Try again and leave every box ticked |
| "No Page was shared" | Sign in with a Facebook account that is an admin of the Page |
| "The Page only lets chosen apps read its leads" | In Facebook Business settings > Integrations > Leads Access, add the app, then click Check again |
| "This Page is already connected to another account" | It is connected to another product. Choose another Page, or ask Foundryx to move it |
| "Needs reconnect" in EcoHub (later) | Facebook stopped sharing (password change, admin removed). Click Reconnect and sign in again. Leads from the gap are caught up automatically |

**Until Meta approves the app for all businesses** (Foundryx submits it), only people Foundryx adds as testers on
its Facebook app can connect. For a pilot customer, send Foundryx the Page admin's Facebook name first.

## Optional, later

- **Instant delivery instead of every minute.** The Shared Service pushes each lead to one ecohub-backend URL the
  moment it arrives. This needs one endpoint plus a signature check (about 10 lines; example in the full guide,
  section 5). Same lead shape, same `id`.
- **Your own field names.** Send your lead fields once (`PUT /be/api/v1/lead-capture/fields`), for example
  Property Type and Budget Range, so the Fields step can map onto them instead of Remarks.
