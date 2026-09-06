# Plan 28 (Teams core + omnichannel team assignment) - formal E2E evidence run

Recorded with the `agent-browser` CLI (sessions `s28t` = tenant Admin lane,
`s28ta` = agent / reader / second-tenant lane). No Playwright. Real clicks
from `/` for every in-app move; the only typed URLs are the three
`open http://<host>:3006` roots (tenant sign-in pages, which a real user
does type) and one `reload`.

## Provenance (read this before trusting a row)

| | |
|---|---|
| Commit under test | `7814fcf` (`sprint-4/28-teams`) |
| Backend | `:8007`, restarted 16:37 by this run from `7814fcf` with `CORS_ORIGIN_REGEX='^http://[a-z0-9-]+\.localhost:3006$'` (the default regex only covers ports 3000-3005, so tenant subdomains at `:3006` were CORS-blocked before the restart) |
| Frontend | `:3006`, pre-existing prod build (pid 65175, cwd `.../worktrees/s28/service_frontend`) |
| DB | `foundryx_service_s28` |
| Celery | eager inline |

**A concurrent fix-round coder modified product source at 16:57**, i.e.
AFTER the servers under test were started. Those edits are UNCOMMITTED and
are NOT in the running build. Every observation below therefore describes
`7814fcf`, which is what the brief asked for. Where a known review finding
is already being repaired in that uncommitted work, the row says so.

## Setup (not part of the flow under test)

Operator-API / direct-DB provisioning is sanctioned setup; the flow under
test stays real clicks.

- Tenant **`p28-1788683909`** ("P28 Teams 1788683909") - created through the
  Platform Console UI by real clicks (Tenant Management -> Tenants -> Add
  tenant). Admin `p28admin1788683909@example.com` / `P28admin!2345`.
  - Setup gotcha: the first create 422'd because `admin@p28-<ts>.test` is
    rejected - `.test` is an IANA special-use TLD the `EmailStr` validator
    refuses. Re-filled with an `@example.com` address. Environment/test-data
    issue, not a product defect.
- **Omnichannel installed via the Services UI** (operator tenant detail ->
  Modules tab -> Omnichannel -> Actions -> Install) -> ACTIVE at **v0.5.0**
  (evidence 01, 02; the version AC-TEM-18 requires).
- Users created via the API (the user form has no password field - it
  invites): `P28 Agent 1`, `P28 Agent 2` on a purpose-made role
  **`P28 Agent <ts>`** holding ONLY `conversations.read` +
  `conversations.reply` (deliberately NO `conversations.assign`, NO
  `teams.read`, so the rail gating in AC-TEM-08/41/44 is actually exercised),
  plus `P28 Reader` on role `P28 TeamsReader <ts>` holding only `teams.read`
  (for AC-TEM-42). Passwords set through `POST /auth/set-password` using the
  invite token read from `invite_tokens` - recorded as setup.
- Both agents + the Admin added as members of workspace `General`.
- Dev-cred channel `chn-p28-<ts>` + threads `p28-<ts>-c1..c3` seeded by a
  setup script (`seed_demo_conversations` is hard-gated to the default
  tenant). `c4`/`c5` added later, pre-assigned to Agent 1, purely to create
  a deterministic `least_open` discriminator.
- Second tenant **`p28b-1788683909`** provisioned with NO modules, for the
  "core Teams without omnichannel" check.
- Tenant **`default`** (`demo@example.com`) is tenant B for the isolation
  probes.

## Run log

1. **01-02** Operator installs omnichannel on the dedicated tenant (v0.5.0).
2. **03** Sign in as the tenant Admin -> sidebar shows **Teams next to
   Roles** under User Management (AC-TEM-41).
3. **04** User Management -> Teams. Resource-shell list, columns exactly
   Name / Description / Members / Status / Created (AC-TEM-39).
4. **05-06** Add team -> `Support 1788683909`, both agents as Members, one
   lead. The **Leads control is disabled ("Add members first") until Members
   are picked**, and once picked it offers ONLY those two users
   (AC-TEM-40, foolproof-UI). Create -> `POST /teams` -> real UUID detail
   page; API read-back confirms `role: lead` / `role: member`.
5. **07** Edit -> keep BOTH members, swap the lead from Agent 1 to Agent 2 ->
   Save -> **`PATCH /teams/{id}` 200**. This is the exact
   retained-member case that 422'd as a mislabelled name conflict in the S5
   smoke run; the `7814fcf` member-diff fix holds (AC-TEM-05).
6. **08** Teams list -> Filters -> `Name contains "ZZZ-no-match"` -> Apply.
   The list refetches but `GET /teams?page=0&page_size=25&sort_by=name&sort_dir=asc`
   carries **no filter param** and the non-matching row stays on screen.
   Search (`&search=`) and sort (`sort_by`/`sort_dir`) ARE server-served -
   only the Filters clause of AC-TEM-39 is broken. Known review finding,
   under repair in the uncommitted fix round.
7. **09** Omnichannel -> Workspaces -> General -> **Team assignment** tab ->
   the team defaults to **Round robin** with no settings row yet
   (AC-TEM-28 default-when-unconfigured).
8. **10** Inbox. The plan-27 rail carries **MY TEAMS** (empty - the Admin is
   not a member) and **ALL TEAMS** (the team + a nested Unassigned),
   the `conversations.assign` gating (AC-TEM-44).
9. **11** Thread 1 (Ana) -> assignee dropdown has a **Teams** group under the
   member list -> pick the team -> `PATCH /omnichannel/contacts/...c1` 200 ->
   header and row both read "Support 1788683909 - P28 Agent 1". Round robin
   picked the first eligible member (AC-TEM-45, AC-TEM-20).
10. **12** Thread 2 (Ben) -> same flow -> picks **P28 Agent 2**: the cursor
    advanced and persisted (AC-TEM-21).
11. **13** Back to the Team assignment tab: the cursor timestamp is now
    shown. Switch to **Least open threads** -> `PUT .../team-settings/{teamId}`
    200, persisted (AC-TEM-28).
12. **14** Deterministic discriminator set up first (Agent 1 = 3 open
    threads, Agent 2 = 1). Thread 3 (Cara) -> assign to team -> picks
    **P28 Agent 2** (fewest open). Round robin would have picked Agent 1
    here (cursor sat on Agent 2), so the strategy switch is proven, not
    coincidental (AC-TEM-22).
13. **15** Rail -> click the team entry -> URL gains `?team=<id>` and the
    server call is `GET /omnichannel/contacts?...&teamId=<id>` -> exactly the
    3 team threads (c4/c5 correctly excluded) (AC-TEM-30).
14. **16** Click the nested **Unassigned** -> `&assignee=unassigned` ->
    "No conversations here." (correct - all 3 have assignees). **Reload** ->
    both params and the filtered view survive (AC-TEM-44).
15. **17-20** Signed in as **P28 Agent 1** (no `teams.read`, no
    `conversations.assign`): sidebar has NO User Management / Teams entry and
    the mega menu has no Teams link either (AC-TEM-41); the rail shows
    **MY TEAMS only**, populated from `GET /teams/mine` **200 without
    `teams.read`** (AC-TEM-08), with no ALL TEAMS section. At 375px the same
    entries collapse into the **View** SearchSelect under a "My teams"
    group and selecting one sets `?team=` (AC-TEM-44 mobile, AC-TEM-48);
    `scrollWidth == clientWidth == 375` (no horizontal overflow).
    Observed alongside: the rail ALSO fires `GET /teams` which **403s** for
    this agent - harmless (My teams still renders from `/teams/mine`) but it
    is the known "rail sources teams from the `teams.read` endpoint" finding.
16. **21** Tenant `p28b-<ts>` (no modules): **Teams is present and fully
    functional as CORE** (list + Add team + the same five columns) while
    there is **no Omnichannel section at all**.
17. **22-23** Teams list -> row Actions -> **Delete**. What renders at
    `7814fcf` is the **plain-confirm AlertDialog** ("Delete this team?" /
    "This cannot be undone. A team still assigned to conversations cannot be
    deleted.") - the disclosed carve-out, NOT a deferred action. Confirm ->
    **409** `{"error":"team_in_use","counts":{"conversations":3}}` -> toast
    "Could not delete: ... is in use by 3 conversations. Reassign them
    first." and the row is untouched (AC-TEM-06, AC-TEM-42).
18. **24** Workflow `omnichannel.assign_conversation` run against thread
    `c5`: the conversation-events feed row carries
    `{"teamId":..., "teamName":..., "assignedVia":"workflow",
    "change":"team", "workflowId":..., "runId":...}` (AC-TEM-31/32).
    The workflow had to be created through the API because the action is
    **absent from the frontend node catalog** - see the defect note below.
    A first run against an already-identically-assigned thread wrote **no
    event**, which is the AC-TEM-31 no-op rule.
19. **25** Drawer assignee menu has separate **Unassign** and **Clear team**
    items: Unassign clears only the user and the team stays (Team
    Unassigned); Clear team clears only the team and the user stays
    (AC-TEM-26).
20. **26** All references cleared -> Delete again -> **204** and the list is
    empty (AC-TEM-06).
21. **27-29** 375px pass on the Teams surfaces: list and detail both report
    `scrollWidth == clientWidth == 375`; the Members MultiSelect popover
    measures left 37 / right 253 inside a 375 viewport, fully clamped
    (AC-TEM-43).
22. **30** Terminology override `team -> Squad/Squads` relabels the **menu
    entry**, the page `h1`, the "Add squad" button and the "Search squads..."
    placeholder; reset afterwards (AC-TEM-17).
23. **31-32** Signed in as **P28 Reader** (`teams.read` only): the list has
    no "Add team" button and no row Actions cell, and the detail page has no
    Edit, no Save, no Actions and zero editable inputs (AC-TEM-42).

## Isolation probes (tenant B = `default` JWT against tenant A ids)

| Probe | Result |
|---|---|
| `GET /teams/{A-team}` | 404 `Team not found.` |
| `PATCH /teams/{A-team}` | 404 |
| `DELETE /teams/{A-team}` | 404 |
| `GET /omnichannel/contacts?teamId=<A-team>` | 200, `data: []`, `total: 0` |
| `PUT /omnichannel/workspaces/<A-ws>/team-settings/<A-team>` | 404 `Workspace not found.` |
| `GET /workflows/metadata` as B | only B's teams; A's team absent |
| `GET /workflows/metadata` as A | only A's team |

Uniform 404 / empty page throughout - no existence oracle (AC-TEM-09,
AC-TEM-50).

## Defects observed at `7814fcf`

1. **`omnichannel.assign_conversation` is unreachable from the workflow
   editor.** Registered backend-side
   (`modules/omnichannel/workflow_nodes.py:212`) but **missing from
   `service_frontend/lib/workflow-catalog.ts`**, which carries the other
   three omnichannel nodes (`message_received`, `get_contact`,
   `send_message`). Repro: Workflows -> New workflow -> palette ->
   ACTIONS / search "assign" -> no result; search "conversation" returns only
   "Send Message". `lib/workflow-catalog.ts` is NOT among the fix round's
   modified files, so this is an open gap, not something already in repair.
2. **Teams list Filters is a no-op against the API** (step 6 above). Known
   review finding, under repair.
3. **`GET /teams/mine` returns member email addresses** to a caller who does
   not hold `teams.read` (verified as P28 Agent 1). Known review finding,
   under repair.
4. **Saved inbox views reject `teamIds`** at `7814fcf`:
   `POST .../inbox-views {"filter":{"teamIds":[...]}}` -> 422
   `extra_forbidden`. The uncommitted fix round adds the field to
   `InboxViewFilter`. `extra="forbid"` still 422s a genuinely unknown key and
   a legacy view with no `teamIds` still saves 201.

## Non-defects checked and dismissed

- **The team form's dirty-guard does not fire** on Cancel or on navigating
  away with an unsaved name change. The **Users reference form behaves
  identically** (verified side by side in the same session), so this is
  shell-wide behaviour on this build, not a Teams regression.
- The Activities feed renders the workflow assignment as "System assigned to
  P28 Agent 1" - the team name and `assignedVia` are not surfaced in the
  copy. The payload is correct and AC-TEM-31 is a `[BE]` id about the
  payload, so this is a presentation observation only.

## Console

No JavaScript console errors surfaced at any step. The only non-2xx
responses were the deliberately provoked ones (the 409 delete guard, the
validation 422s) plus the agent's spurious `GET /teams` 403 noted above.

---

# Round 2 - re-run on the fix commit `c6706b3c`

Recorded 2026-09-06 21:2x-21:5x local. Sessions `s28t2` (tenant Admin),
`s28t2a` (P28 Agent 1), `s28t2b` (P28 Agent 2). Closed individually, never
`close --all`.

## Provenance

| | |
|---|---|
| Commit under test | **`c6706b3c`** (round 1 `0e5dfbb3` + round 2 `c6706b3c` on top of the round-1 evidence commit `8f3dd01b`); worktree clean at start |
| Backend | `:8007` PID 24933, rebuilt by the coordinator on `c6706b3c` (s28 DB override + CORS regex for `:3006`); log `/private/tmp/s28-uvicorn-round2.log` |
| Frontend | `:3006` PID 27764, fresh `.next` build of `c6706b3c`; cwd verified = `.claude/worktrees/s28/service_frontend` |
| Not restarted / not rebuilt | nothing - both PIDs unchanged throughout |

The round-1 provenance caveat (servers predating the fix-round edits) is
**resolved**: this run is on the committed fix and a build of it.

## What survived the migration down/up cycle (and what was recreated)

Tenants `p28-1788683909` / `p28b-1788683909`, all five users, the workspace
`General` (+ members), the five threads `c1..c5`, the workspace API key and
the admin JWT all survived. **All `teams` / `team_members` rows and every
`assigned_team_id` were gone**, as the coder warned. Recreated with the
round-2 stamp `1788700982`:

- `R2 Support 1788700982` - Agent 1 (member), Agent 2 (lead); later Agent 2
  removed so Agent 2 becomes a no-teams user for the hidden-heading check.
- `R2 Dormant 1788700982` - Agent 1 only; deactivated for the inactive-team
  checks. **Accidentally deleted** mid-run (see step 5), replaced by
  `R2 Dormant2 1788700982` (same shape, deactivated).
- `R2 Throwaway 1788700982` - no members; the Cancel-case target.

Setup (sanctioned, outside the flow under test): the P28 Agent role gained
`conversations.assign` (so the drawer's Teams group - gated on that key -
renders for an agent who belongs to an inactive team, the brief's exact
case) and `workspaces.read` (the agent's Inbox made no thread-list request
at all without it - `GET /omnichannel/workspaces` 403 - which is a
test-role artefact; round 1 never opened a thread as the agent). `teams.read`
was never granted to any agent.

## Run log

1. **33** Teams -> Filters -> `Name` `contains` `ZZZ-nomatch` -> Apply. The
   refetch is now `GET /teams?...&filter={"kind":"group","combinator":"and",
   "rules":[{"kind":"condition","field":"name","operator":"contains","value":
   "ZZZ-nomatch"}]}` and the list reads "No data available" (AC-TEM-39).
2. **35** Filters -> field `Active`, operator `is no` -> Apply ->
   `filter=...{"field":"isActive","operator":"is_false"}...` -> only the
   deactivated `R2 Dormant` remains. Curl: an unknown field ->
   `422 {"detail":"field not filterable: bogusField"}`; a malformed value ->
   `422 Invalid filter.`; `isActive eq false` and `name contains "R2 Support"`
   each return exactly the expected row.
3. **34** Signed in as Agent 1 (no `teams.read`): Inbox rail shows **MY
   TEAMS only**, no ALL TEAMS, and the backend log shows ONLY
   `GET /teams/mine 200` - the round-1 `GET /teams` 403 chatter is gone
   (AC-TEM-44 amended). `GET /teams/mine` now returns members as
   `{userId, name, role}` - **no `email`** (round-1 D3 resolved).
4. **22 (replaces the round-1 22)** Teams -> row Actions -> Delete on
   `R2 Dormant`: **no AlertDialog**; a toast "Deleting in 9s | Cancel"
   appears (deferred action, destructive window).
5. My Cancel click missed the window (screenshot + eval overhead ran past
   10s), so this first attempt **committed**: `pending_actions` row
   `teams.delete` = `committed`, the team 404s, and the backend log shows
   **zero HTTP `DELETE /teams`** - the delete runs inside the deferred
   commit. Unintended, but it is direct evidence of "the destructive call
   fires at COMMIT". The Cancel case was then redone properly:
6. **36** Delete on `R2 Throwaway` with the Cancel click inside the same
   eval chain 1.2s after Delete: toast "Deleting in 9s | Cancel" ->
   Cancel -> toast gone, `pending_actions` row = **`cancelled`**, the team
   still `GET`s 200, still zero `DELETE /teams`. **Cancel fires nothing.**
7. **23 (replaces the round-1 23)** `R2 Support` made referenced three ways
   (a `PUT team-settings` row, a saved view with `teamIds`, threads c1+c2
   assigned) -> Delete -> let the 10s window commit -> toast **"This team
   is still assigned to 2 conversations and cannot be deleted."**,
   `pending_actions` = `failed` with that `error_text`, team still 200
   (AC-TEM-42 amended). Note: the reference guard registers exactly ONE
   source - `register_reference_guard("team", "conversations", ...)` in
   `modules/omnichannel/bootstrap.py:120` - so "2 conversations" IS the
   complete per-source output; team-settings rows and saved-view `teamIds`
   are not guard sources (see the integrity check below).
8. **37** Agent 1 (now holding `conversations.assign`, member of the
   inactive `R2 Dormant2`) -> thread Ana -> assignee dropdown -> Teams group
   lists **`R2 Support` only**; the inactive team the agent belongs to is
   absent (round 2 N1).
9. **38** Admin -> Inbox -> rail `R2 Support` (`?team=<id>`) -> **Save
   view** "R2 Team view 1788700982" -> `POST inbox-views 201` and the
   stored filter carries `"teamIds": ["ce431a47-..."]`. Reload -> click
   **All** (`?view=all`, no team) -> click the saved view -> URL regains
   `&team=ce431a47-...`, the list shows exactly Ana + Ben, and the request
   is `GET /omnichannel/contacts?...&viewId=...&teamId=ce431a47-...`
   (AC-TEM-46). Curl: a cross-tenant team id in `teamIds` -> `422
   {"fieldErrors":{"filter":"One or more teams do not belong to this
   tenant."}}`; an unknown key still `422 extra_forbidden`; a legacy filter
   with no `teamIds` still saves 201.
10. **39** Agent 1 (no `teams.read`) -> Omnichannel -> Workspaces -> General
    -> **Team assignment** tab: `GET .../team-settings 200` and the tab
    lists **every ACTIVE team** - `R2 Throwaway` (Round robin,
    `isConfigured: false`, `updatedAt: null`) and `R2 Support` (Least open
    threads, `isConfigured: true`, timestamp); the inactive `R2 Dormant2` is
    absent. The same user's `GET /teams` is 403, so the tab is populated
    without it (AC-TEM-28 amended).
11. **41** Agent 2 (removed from every team) -> Inbox: neither "MY TEAMS"
    nor "ALL TEAMS" renders; `/teams/mine` 200 with an empty list
    (AC-TEM-44 amended, hidden heading).
12. **40, 42** Workflows -> New workflow -> palette search "assign" ->
    **Assign Conversation** with `lucide-user-round-cog` (not the Zap
    fallback). Click it -> node on canvas -> drawer: Contact, **Assign to**
    = `A user | A team | Unassign`; choose `A team` -> **Team** ("Choose a
    team...") and **Strategy** appear; the Team picker lists only the two
    ACTIVE teams (round-1 D1 resolved).
13. **43-46** 375px pass: Agent 1's View SearchSelect carries the "My teams"
    group with each team plus its "- Unassigned" entry; Teams list Filters
    no-match at 375 (filter param present, list empties); the deferred
    toast at 375 measures 16..359 inside 375 with Cancel -> `cancelled`;
    the Team assignment tab at 375. Every 375 page reports
    `scrollWidth == clientWidth == 375`.

## Post-delete integrity check (not an AC - for the reviewer)

After clearing c1/c2 and deleting `R2 Support` for real (`DELETE /teams`
204; the plain HTTP route still exists alongside the deferred action):
`GET team-settings` no longer lists it; the two saved views **retain the
dangling `teamIds`** but `GET inbox-views` is 200 and loading the view
returns an empty page (200) - graceful, no cleanup.

## Observations (not defects against the amended UAC)

- The rail's **My teams** (and the 375 View select) lists a team the agent
  belongs to even when that team is **inactive** (`R2 Dormant`,
  `R2 Dormant2`). Round 2 scoped active-only to assignment *targets* (the
  drawer and the workflow picker); a rail entry is a read filter over
  threads still carrying that team, so this may be intended - flagging it
  for the reviewer to rule on.
- For the admin's 375 Teams pass I typed the list URL once
  (`open .../user-management/teams`) instead of clicking from `/` - every
  other move in both rounds is a real click.

## Suites (round 2)

- Targeted backend: `tests/test_teams.py tests/test_omnichannel_team_assignment.py
  tests/test_omnichannel_inbox_views.py tests/test_deferred_actions.py` ->
  **159 passed** (329s). The full suite was NOT re-run (coder ran 3136 on
  `0e5dfbb3`; round 2 was targeted).
- Full vitest: **2184 passed, 2 failed** (293 files, 178s). The two -
  `account/components/timezone-card.test.tsx` (9.8s) and
  `resource-form/resource-form.deferred.test.tsx` (a grace-window countdown
  test) - **both pass in isolation (6/6)**; neither is a Teams file. Round
  1's `inbox-view-rail.test.tsx` flake passed this time. Same class as
  round-1 D5: load-sensitive timers under full-suite CPU contention.
