# EcoHub: receive Meta leads (simple version)

One page for the EcoHub team. Foundryx does all the Facebook setup. EcoHub only collects the leads. All data below is
fake. Full contract, if you ever need more: `documentation/lead-capture/consumer-integration-guide.md`.

## What Foundryx does for you

- Connects your customer's Facebook Page.
- Gives ecohub-backend one key: `fxl_live_...`. Keep it in the backend environment only, never in the browser.

## What EcoHub builds: one scheduled job

Every minute, ecohub-backend asks Shared Service for new leads and creates them in Leads.

```
GET https://<shared-service-host>/be/api/v1/lead-capture/leads?cursor=<saved cursor>
Authorization: Bearer fxl_live_...
```

On the very first run use `?since=2026-11-17T00:00:00Z` instead of `cursor`.

The answer:

```json
{
  "data": [{
    "id": "e3a10000-0000-0000-0000-000000000001",
    "formName": "Year-end promo",
    "createdAt": "2026-11-17T03:20:00Z",
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

That is all. No public endpoint, no signatures, no field setup. Leads show in EcoHub within about a minute.

## Optional, later

- **Your own field names.** Send your lead fields once, e.g. Property Type and Budget Range. Foundryx then maps the
  form's questions onto them, so they stop arriving in `notes`.
- **Instant delivery instead of every minute.** Foundryx pushes each lead to one ecohub-backend URL the moment it
  arrives. This needs one endpoint plus a signature check (about 10 lines; example in the full guide, section 5).
- **"Connect a source" button inside EcoHub.** Customers connect their own Page without Foundryx. Coming in a later
  release.

## Test it

Ask Foundryx for a test lead. It arrives with `isTest: true` and Meta's dummy answers.
