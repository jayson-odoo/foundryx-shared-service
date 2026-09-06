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
