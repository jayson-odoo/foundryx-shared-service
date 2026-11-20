# Plan 28 S0 - agent-browser evidence run

Lane s28 (`sprint-4/28-teams`), backend `:8007` on `foundryx_service_s28`,
frontend `:3006`. Run 2026-09-06, `agent-browser --session s28`, real clicks
from `/` (sidebar navigation, no typed URLs except the two documented reload
checks below). Signed in as `demo@example.com` / `demo1234`.

## Pre-req: manual permission seed (documented, not code)

Backend slice S1 (core `teams` table + `teams.read`/`teams.manage`
permission rows + grant sweep) has not landed yet - this is the S0
frontend-mock slice. To exercise the gated menu entry + pages against the
live lane backend, the two permission catalog rows and an Admin-role grant
were inserted directly in Postgres (`foundryx_service_s28`, not touching any
backend code):

```sql
INSERT INTO permissions (id, key, module, resource, resource_label, action, action_label, description)
VALUES
  (gen_random_uuid()::text, 'teams.read', 'core', 'teams', 'Teams', 'read', 'Read', 'View teams'),
  (gen_random_uuid()::text, 'teams.manage', 'core', 'teams', 'Teams', 'manage', 'Manage', 'Create, edit and delete teams')
ON CONFLICT (key) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id, tenant_id)
SELECT r.id, p.id, r.tenant_id
FROM roles r JOIN permissions p ON p.key IN ('teams.read','teams.manage')
WHERE r.name = 'Admin'
ON CONFLICT DO NOTHING;
```

S1 will land the real migration + `PermissionService.sync_core()` +
`sweep_tenant_admin_grants` path; this manual seed is throwaway and scoped
only to the `foundryx_service_s28` database.

## Journey 1 - Teams admin CRUD (AC-TEM-39..43)

1. Sidebar -> User Management (expand) -> **Teams** entry visible next to
   Roles (`01-teams-list-1280.png`) - Resource-shell list (Name, Description,
   Members, Status, Created columns), members drawn from the REAL tenant
   users list (Demo User, Admin User, Event Staff, Event Manager, KT Demo).
2. **Add team** -> filled Name "Support 1788637229", Description, picked
   Members (Admin User, KT Demo) -> Leads picker enables and ONLY offers
   those two (`02-team-create-form-1280.png`) -> picked Admin User as lead
   -> **Create team**.
3. Detail page renders the saved record (`03-team-detail-1280.png`) ->
   **Edit** -> removed KT Demo from Members -> Leads unaffected (still Admin
   User, who remained a member) -> **Save team** -> re-verified read view.
4. Back to teams list shows the updated row.
5. Re-verified at 375px: list (`04-teams-list-375.png`), team detail
   (`05-team-detail-375.png`), and the Members `MultiSelect` popover stays
   inside the viewport while editing (`06-team-form-multiselect-375.png`).

## Journey 2 - Team Inbox + assign-to-team (AC-TEM-45, slice-content rail)

Repeated with a fresh team ("Support 20260906A") after a frontend restart
(see "Known S0-mock limitation" below) so the walkthrough is self-contained:

6. Omnichannel -> Inbox: the rail (`07-inbox-rail-1280.png`) shows a
   **Teams** section - "My teams" (Sales, Support - both carry the demo user
   as a seeded member) each with a nested **Unassigned** entry, then an
   **All teams** group (Onboarding, Support 20260906A) for the
   `conversations.assign` holder.
7. Opened the "Sarah Chen" thread -> assignee dropdown -> **Teams** group
   lists all active teams -> picked "Support 20260906A" -> header updates to
   "Support 20260906A · Admin User" (team + the mock's picked member,
   `08-drawer-team-assigned-1280.png`).
8. Clicked the rail's "Support 20260906A" entry -> the thread is listed
   (`09-team-scoped-inbox-1280.png`, URL `?team=<id>`) -> clicked its nested
   **Unassigned** entry -> empty (`10-team-unassigned-empty-1280.png`, URL
   `?team=<id>&assignee=unassigned`).
9. From the still-open drawer, clicked **Unassign** (the existing, REAL
   user-assignee action) -> header now reads "Support 20260906A · Unassigned"
   - the TEAM stays, only the user clears (D-A8-12/26,
   `11-unassign-keeps-team-1280.png`). This caught a real bug during the run
   (see "Fix found during verification" below).
10. Rail's team-Unassigned entry now lists the thread
    (`12-team-unassigned-queue-1280.png`).
11. 375px: inbox layout with the rail's mobile `SearchSelect` in place of the
    column (`13-inbox-375.png`); selecting "Onboarding - Unassigned" from
    that select updates the URL and scopes the list
    (`14-inbox-mobile-team-select-375.png`); a full navigation reload to
    `?team=team-003&assignee=unassigned` (Onboarding is a permanently-seeded
    team, unlike the one created mid-run) restores the exact same select
    value and empty-Unassigned view - confirms AC-TEM-44's "a reload
    restores it" for the URL/filter side of the feature.

## Fix found during verification

Assigning a team then clicking the pre-existing **Unassign** action (which
calls the REAL `conversationService.assign(id, null)`, unrelated to the S0
team mock) initially dropped the team overlay entirely - the header fell
back to plain "Unassigned" instead of "Support 20260906A · Unassigned".
Root cause: `useMessages`'s `commitThreadIfActive` set the thread straight
from whatever the backend/mock call returned, and only `assignTeam`'s own
call site re-applied the S0 team overlay - every OTHER mutation
(`assign`/`assignToMe`/`setStatus`/`setPriority`/`patchContact`/
`moveLifecycle`) skipped it. Fixed by moving the overlay re-application
INTO `commitThreadIfActive` itself (`hooks/use-messages.ts`), so every
commit re-merges the team overlay - re-verified live (step 9 above) and
covered by `services/team-assignment-service` design notes; vitest suite
re-run green after the fix.

## Known S0-mock limitation (documented, not a defect)

`team-service.mock.ts`'s team list lives in an in-memory module variable; a
GENUINE full-page navigation (`agent-browser open <url>`, as opposed to an
in-app link click) reinitializes the JS bundle and resets it back to the 4
seeded teams (Sales/Support/Onboarding/Billing) - a team created mid-session
does not survive a hard reload. This is the same characteristic every other
S0-mock entity in this codebase has (e.g. `workspace-service.mock.ts`) and
resolves once S1 wires the real `teams` table. The team-ASSIGNMENT overlay
(`team-assignment-service.mock.ts`) DOES survive a hard reload (stored in
`sessionStorage`, keyed by contact id) and, per the fix above, correctly
degrades a since-vanished team id to `assignedTeamName: null` rather than
showing a stale name (mirrors AC-TEM-29's "a foreign/stale id renders null,
never a name"). Journey 2 above therefore re-created its team once (step 6)
rather than reusing the one from Journey 1, and the reload check in step 11
deliberately targets a PERMANENT seeded team (Onboarding) to demonstrate the
URL/filter restore cleanly.

## Not covered in this run (deferred to S5)

- Cross-tenant isolation (a second tenant's session seeing neither the team
  nor the thread) - there is no real backend teams table yet to isolate; S1
  lands the tenant-scoped repository + 404 semantics, S5's E2E covers it for
  real.
- A user without `teams.read` seeing no Teams menu entry - covered by the
  existing `filterMenu`/`MenuItem.permission` mechanism (same code path as
  every other gated entry, e.g. Roles) rather than a redundant live check;
  not re-verified manually here for time.
