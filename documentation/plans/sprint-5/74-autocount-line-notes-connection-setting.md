# Plan 74: AutoCount line notes database connection, set in the app

Lane PO-LINK-KEEP-FURTHER-DESC (crew ruling s18, 24 Nov). Follows plan 73 (#344, reverted by #348).

## Why
Plan 73 makes every PO / SPO write read the PO from a read-only AutoCount database connection and refuse when it cannot.
The live company reads AutoCount through the API, so it needs that connection set explicitly, in the app (owner: feature
settings live in the app, not .env). The setting must exist and be set BEFORE plan 73 is live, so the work ships in two PRs:
- B1 (this plan): the setting only. No write behaviour changes.
- B2: re-land plan 73 + a release guard that refuses the deploy while an active write-enabled company has no readable
  line notes connection.

## Acceptance criteria
- AC-74-01 [BE][T] `ac_company.line_notes_connection_id` (nullable) exists: module migration 0049 (revision id <= 32 chars,
  single head, down_revision 0048).
- AC-74-02 [BE][T] `PATCH /autocount/companies/{id}/line-notes-connection` `{connectionId: string | null}` needs
  `autocount.companies.manage`; sets or clears the company's line notes connection; the connection must be a same-tenant,
  `sql_database` connection (resolved with the JWT tenant), else 422 with a plain message and nothing changes; another
  tenant's company is 404. Router -> service (`set_line_notes_connection`) -> repository; no DB in the router.
- AC-74-03 [BE][T] `CompanyItem` carries `lineNotesConnectionId` (null when unset) and `writeEnabled` (true when the company
  is active and has a write connection; names only, never a URL or key).
- AC-74-04 [FE][T] Company detail screen: a "Line notes database" `SearchSelect` listing the tenant's `sql_database`
  connections (existing `listSqlConnections`), plus a clear option; saving calls the new route and shows the saved value
  after reload; a 422 shows its plain message next to the field. Shown only when `writeEnabled`. No hint copy. Works at
  375px and 1280px.
- AC-74-05 [BE] No permission row is new (reuses `autocount.companies.manage`), so no grant sweep. New column is nullable
  and set by a person per company, so no backfill.
- AC-74-06 Plan 73 behaviour is NOT in this PR: no write reads the DB, nothing is refused.

## Release (B1, then B2)
1. Merge + release B1 (GitHub deploy workflow). 2. A person sets "Line notes database" on the live company in the app.
3. Merge + release B2; its guard refuses the deploy (old colour stays live) if step 2 is missing or the connection cannot read.
