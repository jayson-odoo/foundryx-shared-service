# Plan 28 (Teams) - merge-main evidence

Merge of `origin/main` (`58759ed` = A2 plan 26 PR #45 + A3 plan 27 PR #43) into
`sprint-4/28-teams` (S0 FE mock + S1 core teams backend). Real-click
`agent-browser` smoke run against the merged build, session `s28a`, backend
`:8007` / frontend `:3006`, DB `foundryx_service_s28`.

## Run log

1. Signed in as `demo@example.com` / `demo1234` at `localhost:3006`.
2. Sidebar User Management -> Teams (`28-teams-list-1280.png`, `28-teams-list-375.png`)
   - real S1 backend list: Billing / Onboarding / Sales / Support with real
     members, description, status.
3. Add team -> filled name/description, picked a member (Admin User) ->
   Create team -> real record created at `/user-management/teams/team-w5g6ed4u`
   (`28-teams-created-1280.png`) - confirms the S1 backend end-to-end (not a
   mock).
4. Sidebar Omnichannel -> Inbox (`28-inbox-1280.png`) - the rail now folds
   Team Inbox into the SAME `InboxViewRail` used by plan 27's saved views
   (All/Mine/Unassigned, Lifecycle, **My teams** [Sales, Support + nested
   Unassigned], **All teams** [Onboarding + nested Unassigned], Views) - no
   parallel `TeamRail` column, per plan 28 D-A8-4.
5. Clicked "Sales" in the rail - list scoped via the S0 client-side overlay,
   URL became `?team=team-001` (`28-inbox-team-selected-1280.png`); clicked
   "All" - URL fell back to the rail's own `?view=all` key, `teamId` cleared.
6. **Bug found + fixed during this smoke** (see commit): selecting a team
   left a stale `?view=` param that clobbered the team scope back to the
   pre-team rail entry on the NEXT reload (a Team Inbox scope must survive a
   refresh, AC-TEM-44). Also, `InboxPage` always mounts `useConversations`
   with `workspaceId=null` first (resolves the default workspace via its own
   effect); the plan-27 F10 "workspace switch" reset was firing on that
   null->real transition too and wiping the `?team=`/`?assignee=` values
   `readInitialFilters` had just seeded from the URL, before anyone ever saw
   them. Fixed both (`use-inbox-rail-selection.ts` clears the stale `?view=`
   on a team pick and never restores it once a team scope is active;
   `use-conversations.ts`'s workspace-switch reset now only fires on a REAL
   workspace-to-workspace change, not the initial null resolution) +
   covered by new Vitest cases. Re-verified: reload with `?team=team-001`
   correctly keeps "Sales" selected (`28-inbox-reload-team-fixed.png`).
7. Mobile (375px) inbox single-pane + the View `SearchSelect` collapses the
   SAME rail entries including the Teams groups (`28-inbox-375.png`).
8. Contacts (A2) list loads with real seeded contacts, Filters/Import/Export/
   Columns toolbar intact (`28-contacts-1280.png`).
9. Opened Sarah Chen's thread (`28-drawer.png`) - Messages/Activities tabs,
   internal note, CSW-aware composer all render (plan 27 rail/drawer intact
   after the merge).
10. Clicked the assignee dropdown - it shows "Assign to" / "Assign to me" /
    "Unassign" PLUS a **Teams** group (Onboarding, Sales, Support) folded
    into the same menu (`28-assignee-menu.png`, per plan 28's assignee-teams
    group merge into the existing picker). Picked "Sales" -> the header now
    reads "Sales · Demo User" (the S0 mock overlay auto-picked a team member
    and assigned them via the REAL `conversationService.assign` endpoint),
    and the thread dropped out of the Unassigned rail bucket
    (`28-team-assigned.png`).

No console errors/warnings observed at any step (`agent-browser errors`/`console`).

## Screenshots

- `28-teams-list-1280.png` / `28-teams-list-375.png` - Teams Resource list (real S1 backend)
- `28-teams-created-1280.png` - a newly created team's detail page
- `28-inbox-1280.png` - inbox rail with My teams / All teams folded in
- `28-inbox-team-selected-1280.png` - "Sales" selected, `?team=team-001`
- `28-inbox-reload-team-fixed.png` - team scope survives a full reload (post-fix)
- `28-inbox-375.png` - mobile single-pane inbox
- `28-contacts-1280.png` - A2 Contacts list
- `28-drawer.png` - conversation drawer (A3 shape)
- `28-assignee-menu.png` - assignee dropdown with the Teams group
- `28-team-assigned.png` - thread assigned to Sales (+ auto-picked member)
