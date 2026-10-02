# Plan 28 S5 - wire smoke evidence

Recorded with `agent-browser --session s28b` against the LIVE backend (`:8007`,
DB `foundryx_service_s28`) and a freshly-built frontend (`:3006`). Signed in
as `demo@example.com` (tenant `default`). Real clicks from `/` throughout;
no typed URLs except the plain `open http://localhost:3006` root and one
`reload` (both explicitly allowed - navigation-by-click is the rule for
in-app moves).

## Run log

1. **01** - Sign in -> User Management -> Teams. List is real (`GET /teams`,
   empty on this fresh tenant).
2. **02-03** - Add team -> filled `Support <ts>` (`ts` = unix seconds),
   description, 2 members (Demo User, Admin User) via the MultiSelect,
   1 lead (Demo User) via the Leads MultiSelect (options correctly limited to
   the 2 selected Members - AC-TEM-40). Create team -> `POST /teams` 201 ->
   real UUID id in the URL -> detail page renders the real row.
3. **04-05** - Edit -> Members swapped to a NON-overlapping pair (Event
   Staff + Event Manager) -> Leads cleared automatically when the prior lead
   left the Members set (AC-TEM-40) -> picked Event Manager as the new lead
   -> Save -> `PATCH /teams/{id}` 200. See "Backend defect found" below for
   why the swap was non-overlapping.
   Reset back to Admin User + Demo User(lead) via 2 direct API calls
   (`members:[]` then the original pair) so Demo User is a member again for
   the inbox/assignment steps - **flagged as an S1 backend bug, not
   something this slice's UI could avoid**, see below.
4. **06** - Inbox -> rail "MY TEAMS" section shows "Support &lt;ts&gt;" with a
   nested "Unassigned" entry, from the real `GET /teams/mine`.
5. **07** - Opened the Sarah Chen thread (`cnt-001`) -> Assign dropdown shows
   a "Teams" group with "Support &lt;ts&gt;" -> clicked it -> `PATCH
   /omnichannel/contacts/cnt-001 {assignedTeamId}` 200 -> header AND the row
   both update to "Support &lt;ts&gt; · Demo User" over the ONE PATCH
   response (no extra `getThread` round trip, no WS needed for the
   assigning tab itself) - round_robin picked Demo User (the only member who
   is ALSO a `WorkspaceMember` of `wsp-001`).
6. **08** - Clicked the rail's "Support &lt;ts&gt;" entry -> URL gains
   `?team=<id>` -> list server-filtered to exactly that thread (AC-TEM-30,
   real `teamId` query param, no client-side filtering).
7. **09** - Clicked the nested "Unassigned" entry -> URL gains
   `&assignee=unassigned` -> empty ("No conversations here.") - correct,
   since the thread currently HAS an assigned user.
8. **10** - From the drawer, "Unassign" (user only) -> thread now appears
   under the team's Unassigned queue (D-A8-12/AC-TEM-26 - team stays, user
   clears) -> header shows "Support &lt;ts&gt; · Unassigned".
9. **11** - Reloaded the page -> `?team=&assignee=unassigned` survives ->
   the same filtered view + selected thread render identically (AC-TEM-44).
10. **12-13** - Omnichannel -> Workspaces -> General -> "Team assignment" tab
    (new in S5) -> shows "Support &lt;ts&gt;" defaulted to "Round robin"
    (no settings row existed yet - the default-when-unconfigured rule,
    AC-TEM-28) -> changed to "Least open threads" -> `PUT
    /omnichannel/workspaces/{wsId}/team-settings/{teamId}` 200 -> persisted
    (cursor timestamp updates, value survives).
11. **14-22** - 375px pass: Team assignment tab, Teams list (horizontal
    scroll contained, no page overflow), team detail (stacked fields), the
    Members MultiSelect popover (stays inside the viewport, no clipping),
    the Inbox (below-1024px collapses into the "View" `SearchSelect` per
    plan - both "Support &lt;ts&gt;" and "Support &lt;ts&gt; - Unassigned"
    entries are present and selecting one sets `?team=` exactly like the
    desktop rail).
12. **23-24** - Delete flow: Actions -> Delete -> the S0 PLAIN-confirm
    dialog (title "Delete this team?", body naming the "still assigned to
    conversations" rule) - no deferred action exists on the backend for
    core teams (confirmed: `grep -i team app/deferred_actions/handlers.py`
    -> no hits), so this stays the disclosed carve-out
    (`confirm-carve-outs.inventory.test.ts` already lists
    `use-team-actions.tsx` with the reason). Confirmed Delete -> `DELETE
    /teams/{id}` -> 409 `team_in_use` -> toast "Could not delete: 'Support
    &lt;ts&gt;' is in use by 1 conversations. Reassign them first." - the
    row is untouched (no destructive call took effect, AC-TEM-06/42).
13. **25** - 375px final detail view (post 409, team still present).

## Mock-vs-backend differences reconciled (S0 -> S5)

- `services/team-service.ts` bound to `team-service.real.ts` (new). List
  params are SNAKE_CASE (`page`/`page_size`/`search`/`sort_by`/`sort_dir`)
  to match the router, NOT the plan's `q`/`sort`/`pageSize` shorthand; the
  shell's `created` column id maps to the backend's `createdAt` sort key.
- `services/team-assignment-service.{ts,mock}.ts` DELETED - the real
  backend returns `assignedTeamId`/`assignedTeamName` directly on every
  `ThreadItem`, so the S0 client-side overlay (`sessionStorage`-keyed) is
  gone. `hooks/use-messages.ts`'s `assignTeam` now calls
  `conversationService.patchContact(contactId, {assignedTeamId})` directly
  and commits the ONE resolved response - no follow-up `getThread`.
- `hooks/use-conversations.ts`'s `teamId` filter is now a real server-side
  query param (`GET /omnichannel/contacts?teamId=`) - the S0
  `merged.filter(...)` client-side scoping is gone.
- `types/omnichannel.ts` `PatchContactInput` gained `assignedTeamId?: string
  | null`.
- `hooks/use-teams.ts`/`use-my-teams.ts`/the rail/the drawer's Teams group
  needed ZERO changes - they were already written against the `TeamService`
  interface, so binding `teamService` to real was transparent to them.
- `services/workflow-metadata-service.ts` was ALREADY real-bound (Phase B of
  an earlier plan) - the canvas `team` NodeField (`node-config-drawer.tsx`)
  needed no change; `metadata.teams` comes straight from
  `GET /workflows/metadata` (gated `teams.read` server-side).
- NEW (not in S0 at all): `services/team-settings-service.{ts,real}.ts`,
  `hooks/use-team-settings.ts`, and the workspace "Team assignment" tab
  (`workspace-team-settings-tab.tsx`) - the plan's §2.2 didn't specify a
  frontend surface for the per-team strategy PUT, so this slice added one on
  the workspace form (a `SearchSelect` per active team), gated
  `conversations.read`/`conversations.assign` (mirroring the backend gate
  exactly, not the brief's `workspaces.manage` shorthand).

## WS/realtime behaviour observed

`contact.updated` is published by the backend on every `patch_thread` call
(confirmed via the existing pipeline - not separately re-verified with a
second browser tab in this run since the PATCH response itself already
carries the authoritative team+assignee state and the row/header update was
instant with no reload). A second-session cross-tenant/WS reconciliation
check is deferred to the tester's formal E2E pass.

## Console errors

None observed during the run (network tab checked after every mutating
step; no 4xx/5xx surfaced except the deliberately-provoked 409 and the ONE
422 from the backend defect below, which is not part of the pass/fail
evidence).

## Backend defect found (NOT fixed - out of scope per the brief; reported for follow-up)

**`TeamService.update()` / `_apply_members()` 422s "A team with this name
already exists" on ANY member-set PATCH that RETAINS at least one existing
`(team_id, user_id)` pair** (e.g. keep Demo User as lead, add a new member).
Reproduced directly against `:8007` with `curl` (bypassing the browser to
isolate it):

```
PATCH /teams/{id} {"members":[{"userId":"<existing-lead>","role":"lead"},{"userId":"<new-user>","role":"member"}]}
-> 422 {"detail":{"fieldErrors":{"name":"A team with this name already exists."}}}
```

- A FULL member-set swap (zero overlap with the prior set) succeeds (200).
- A description-only or name-only (unchanged value) PATCH succeeds (200).
- Only a partial-overlap members PATCH fails, and it fails with the WRONG
  error - the name is untouched and unique; this is a mislabeled
  `IntegrityError`.
- Root cause (read-only inspection, not fixed):
  `_apply_members` does `team.members = [TeamMember(...) for m in
  resolved]` - a blind collection REPLACE, not a diff. When the new list
  still contains a retained `(team_id, user_id)` pair, SQLAlchemy's flush
  ordering for the collection re-assignment appears to attempt inserting the
  new `TeamMember` row before the old one (same team_id+user_id) is
  deleted, tripping the `(team_id, user_id)` UNIQUE constraint - and
  `update()`'s blanket `except IntegrityError: raise
  TeamValidationError({"name": ...})` mislabels ANY integrity violation as a
  name conflict.
- **Impact: this breaks the single most common real edit pattern** (adding
  or removing ONE member while keeping the rest) - AC-TEM-05 ("adds
  inserted, removals deleted, role changes updated... one transaction")
  is not actually met for the retained-member case. The S5 smoke run above
  worked around it with non-overlapping swaps; a tester's formal E2E for
  AC-TEM-50's "edit members" step should use the SAME workaround until this
  is fixed, or the recorded run will 422 unexpectedly.
- Recommended fix (for whoever picks this up - NOT implemented here per the
  explicit "no backend edits" instruction for this slice): `_apply_members`
  should diff by `user_id` (delete removed rows, update role-changed rows in
  place, insert only genuinely new rows) instead of a blind list-replace;
  separately, `update()`'s `except IntegrityError` should not assume
  "name" - either re-check `name_taken` explicitly before mapping the error,
  or inspect the constraint name.

## Deferred-action decision (team delete)

No core deferred action exists for team delete (`grep -i team
service_backend/app/deferred_actions/handlers.py` -> no hits). Per the
brief, this was NOT added (no backend edits). The S0 plain-confirm carve-out
in `use-team-actions.tsx` stays, already disclosed and pinned in
`confirm-carve-outs.inventory.test.ts` with the exact reasoning. Verified
live: the dialog reads "Delete this team?" / "This cannot be undone. A team
still assigned to conversations cannot be deleted." and a blocked delete
(409) surfaces the per-source count via `toast.error` with NO destructive
call taking effect (evidence 23-24).
