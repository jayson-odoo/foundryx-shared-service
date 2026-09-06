# 28 - Teams (core) + omnichannel team assignment - Test Execution Report

Format: `documentation/development_process/AI_Agent_Orchestration_Guide.md` §6.
Contract: `28-teams-core-and-omnichannel-assignment-acceptance-criteria.md`
(AC-TEM-01..50). Plan: `28-teams-core-and-omnichannel-assignment.md`.

## 1. Environment

| Item | Value |
|---|---|
| Branch / commit under test | `sprint-4/28-teams` @ **`7814fcf`** |
| Backend | `uvicorn app.main:app --port 8007`, restarted at 16:37 by this run with `CORS_ORIGIN_REGEX='^http://[a-z0-9-]+\.localhost:3006$'` |
| Frontend | prod build on `:3006` (pid 65175, cwd `.claude/worktrees/s28/service_frontend`) |
| Database | `foundryx_service_s28` (Postgres, native) |
| Celery | `CELERY_TASK_ALWAYS_EAGER=true` |
| Browser tooling | `agent-browser` CLI, sessions `s28t` + `s28ta`. No Playwright. |
| Evidence | `documentation/plans/sprint-4/28-evidence/E2E/` (32 screenshots + `README.md` run log) |

**Why the backend was restarted.** `Settings.cors_origin_regex` defaults to
`http://[a-z0-9-]+\.localhost:300[0-5]`, which does not match `:3006`, so every
tenant-subdomain request from `p28-<ts>.localhost:3006` was CORS-blocked. One
restart with the explicit regex, cwd-verified against the s28 worktree.

**Build provenance caveat (load-bearing).** A concurrent fix-round coder
modified product source in this worktree at **16:57**, after the servers under
test were started (16:37) and after the pytest run was launched. Those changes
are uncommitted and are NOT in the running build or in the suite result. Every
result in this report describes **`7814fcf`**. Rows whose finding is already
being repaired in that uncommitted work say so explicitly.

### Suite results

| Suite | Command | Result |
|---|---|---|
| Backend | `.venv/bin/python -m pytest -q` | **3123 passed, 1 skipped, 18 deselected** in 2629s |
| Frontend | `npx vitest run` | **2176 passed, 1 failed** (293 files) - run twice, same single failure |

The one vitest failure is
`app/(protected)/omnichannel/inbox/components/inbox-view-rail.test.tsx >
"Delete parks 'inbox_views.delete' via the pending-actions service"`. It
**passes in isolation** (13/13) and fails only under full-suite CPU
contention: the test arms a **real 50 ms** deferred-action window
(`setMockWindowSeconds('destructive', 0.05)`) against a real 1 s poll tick, so
under load the action auto-commits before the assertion reads `pending`. The
`describe` block is plan-27 code inherited from `main`; plan 28 lengthened the
file (it appended a Teams `describe`), which is why the race now loses
consistently. Recorded as a test-infrastructure defect (D5), not a product
defect, and not attributable to any AC-TEM id.

### Tenants, users and setup calls

| Thing | Value |
|---|---|
| Tenant A (dedicated) | `p28-1788683909` / "P28 Teams 1788683909", id `7d6089ea-...` |
| Tenant A Admin | `p28admin1788683909@example.com` / `P28admin!2345` |
| Agents | `p28agent11788683909@example.com`, `p28agent21788683909@example.com` / `P28agent!2345`, role `P28 Agent 1788683909` (`conversations.read` + `conversations.reply` only) |
| Read-only user | `p28reader1788683909@example.com` / `P28read!2345`, role `P28 TeamsReader 1788683909` (`teams.read` only) |
| Tenant A2 (no modules) | `p28b-1788683909`, admin `p28badmin1788683909@example.com` / `P28admin!2345` |
| Tenant B (isolation) | `default`, `demo@example.com` / `demo1234` |
| Team under test | `Support 1788683909` (`fe3a7184-...`), later deleted; `Mobile Check 1788683909`, `Empty Roster 1788683909` |

Setup performed outside real clicks (sanctioned by the brief; the flow under
test stayed clicks): agent/reader user creation + role grants via the API (the
user form is invite-only, no password field); passwords set via
`POST /auth/set-password` with the invite token read from `invite_tokens`;
workspace membership via `POST /omnichannel/workspaces/{id}/members`; a
dev-cred channel and five threads seeded by script because
`seed_demo_conversations` is hard-gated to the default tenant; the
`assign_conversation` workflow created via `POST /workflows` (see D1 - it
cannot be built on the canvas). Tenant creation and the omnichannel install
were done by **real clicks** in the Platform Console.

Setup note: the first tenant create 422'd on `admin@p28-<ts>.test` because
`.test` is an IANA special-use TLD the `EmailStr` validator rejects. Re-filled
with `@example.com`. Environment issue, not a product defect.

## 2. Results by acceptance criterion

Legend: PASS / FAIL / DEFERRED. "E2E n" = screenshot `n` in
`28-evidence/E2E/`.

### Slice A - core backend: teams + membership

| ID | Tag | Result | Evidence |
|---|---|---|---|
| AC-TEM-01 | BE | PASS | `test_teams.py::test_create_list_get_team_with_members`. E2E: team created by clicks, API read-back shows both members with correct roles (E2E 05, 06). |
| AC-TEM-02 | BE | PASS | `test_name_blank_too_long_and_duplicate_ci_rejected`. Live: blank -> 422 `{"fieldErrors":{"name":"Name is required."}}`; 121 chars -> `"Name is too long."`; `mObIlE cHeCk <ts>` vs `Mobile Check <ts>` -> `"A team with this name already exists."` |
| AC-TEM-03 | BE | PASS | `test_members_unknown_or_foreign_or_platform_user_rejects_whole_write`. Live: foreign `userId` -> 422 `{"fieldErrors":{"members":"One of the selected members is invalid."}}` and a follow-up `GET /teams?search=Foreign` returns **0 rows** - nothing partially written. |
| AC-TEM-04 | BE | PASS | `test_member_role_must_be_member_or_lead`, `test_duplicate_member_in_payload_rejected`. E2E: one lead + one member on one row each. |
| AC-TEM-05 | BE | PASS | `test_patch_diffs_members_retain_plus_role_change_plus_add_plus_remove`, `test_update_replaces_membership_set_atomically_and_rolls_back_on_bad_member`. **E2E 07 is the regression proof**: retain BOTH members and swap the lead -> `PATCH /teams/{id}` **200**. The same edit 422'd as a mislabelled name conflict in the S5 smoke run; `7814fcf`'s member-diff fixes it. |
| AC-TEM-06 | BE | PASS | `test_delete_succeeds_with_no_guard_registered`, `test_delete_blocked_by_reference_guard_returns_409_with_counts`. Live: while referenced -> **409** `{"error":"team_in_use","counts":{"conversations":3}}`, row survives (`GET` 200); after clearing all references -> **204** and the list empties (E2E 23, 26). |
| AC-TEM-07 | BE | PASS | `test_is_active_false_still_readable_and_editable`. Live: inactive team still `GET`-able and `PATCH`-able (description edited, 200); assigning it -> 422 `{"fieldErrors":{"assignedTeamId":"Team not found or inactive."}}`; `GET /workflows/metadata` returns `teams: []`. |
| AC-TEM-08 | BE | PASS | `test_list_search_sort_pagination`, `test_mine_returns_only_callers_teams_no_teams_read_needed`. Live: list served by `search` / `sort_by` / `sort_dir` / `page` / `page_size`; **`GET /teams/mine` 200 for an agent with no `teams.read`** and the rail renders from it (E2E 17). See D3 - the response also carries emails. |
| AC-TEM-09 | BE | PASS | `test_tenant_isolation_uniform_404`. Live with tenant B's JWT: `GET`, `PATCH`, `DELETE` on A's team id all **404 `Team not found.`** - never 403, never data. |
| AC-TEM-10 | BE | PASS | `test_permission_403_matrix`, `test_teams_manage_alone_implies_teams_read`, `test_teams_read_only_cannot_write`. Live: the reader role holds only `teams.read` and reads fine but gets no write affordance (E2E 31, 32). |
| AC-TEM-11 | BE | PASS | `test_bootstrap_sync_and_sweep_grants_teams_keys_to_existing_admin`. E2E corroboration: the freshly provisioned tenant's Admin holds both keys with no slice-specific grant. |
| AC-TEM-12 | BE | PASS | `test_migration_revision_id_and_parent_and_no_collision`. |

### Slice B - capability seam, reference guard, terminology

| ID | Tag | Result | Evidence |
|---|---|---|---|
| AC-TEM-13 | BE | PASS | `test_capabilities_registered_and_resolve_tenant_scoped`, `test_capabilities_registered_via_boot_module_hooks`, `test_capability_registration_idempotent`. |
| AC-TEM-14 | BE | PASS | `test_foreign_tenant_capability_calls_return_none_never_cross_tenant`. Live: `assignedTeamId` from another tenant -> 422, never resolved. |
| AC-TEM-15 | BE | PASS | `test_capability_absent_degrades_instead_of_raising` (core), `test_omnichannel_team_assignment.py::test_capability_absent_degrades_never_500s` (module). |
| AC-TEM-16 | BE | PASS | `test_core_team_delete_blocked_by_real_conversations_guard`, `test_broken_reference_guard_never_wedges_the_delete_decision`. Live 409 counts `{"conversations":3}` came from the real guard (E2E 23). |
| AC-TEM-17 | BE | PASS | `test_terminology_team_key_registered_with_defaults`, `test_terminology_override_relabels_team`. **E2E 30**: override `team -> Squad/Squads` relabels the sidebar entry ("Squads"), the page `h1`, the "Add squad" button and the "Search squads..." placeholder. Reset afterwards. |

### Slice C - module backend: team assignment + strategies

| ID | Tag | Result | Evidence |
|---|---|---|---|
| AC-TEM-18 | BE | PASS | `test_manifest_version_and_model_shape`. E2E 01/02: the Services UI shows **Omnichannel v0.5.0** and installs to ACTIVE at 0.5.0. |
| AC-TEM-19 | BE | PASS | `test_patch_assign_team_validates_unknown_and_inactive`, `test_patch_assign_team_foreign_tenant_id_rejected`. Live: unknown, foreign and inactive team ids each -> 422 `{"fieldErrors":{"assignedTeamId":"Team not found or inactive."}}`. |
| AC-TEM-20 | BE | PASS | `test_round_robin_rotation_persists_across_fresh_sessions`. E2E 11: first team assign picks the first eligible member and sets team + user in one PATCH. |
| AC-TEM-21 | BE | PASS | `test_round_robin_settings_row_survives_a_fresh_service_instance`. E2E 12: thread 2 picks **Agent 2**, and the Team assignment tab then shows a persisted "Last picked cursor updated" timestamp (E2E 13). |
| AC-TEM-22 | BE | PASS | `test_least_open_picks_fewest_open_threads_in_workspace`, `test_least_open_ties_break_by_deterministic_order`. **E2E 14 is a clean discriminator**: with Agent 1 on 3 open threads and Agent 2 on 1, and the round-robin cursor parked on Agent 2 (so round robin would have chosen Agent 1), `least_open` chose **Agent 2**. |
| AC-TEM-23 | BE | PASS | `test_ineligible_members_never_picked`. E2E corroboration: the Admin, a non-member, was never picked. |
| AC-TEM-24 | BE | PASS | `test_empty_roster_team_assigned_user_null`. Live: assigning `Empty Roster <ts>` -> **200**, `assignedTeamName` set, `assignedUserName` null, and the thread appears in that team's Unassigned queue. |
| AC-TEM-25 | BE | PASS | `test_team_plus_user_requires_membership`, `test_user_only_not_member_of_current_team_clears_team`, `test_user_only_still_member_of_current_team_keeps_team`. Live: team + non-member user -> 422 `{"fieldErrors":{"assignedUserId":"User is not a member of this team."}}`; user-only assign to a member kept the team. |
| AC-TEM-26 | BE | PASS | `test_team_null_user_sets_team_unassigned`, `test_null_team_clears_team_keeps_user`. **E2E 25**: the drawer exposes separate **Unassign** (clears user, team stays) and **Clear team** (clears team, user stays) items; both verified against the API. |
| AC-TEM-27 | BE | PASS | `test_embed_principal_cannot_send_team`. |
| AC-TEM-28 | BE | PASS | `test_team_settings_crud_and_gates`. **E2E 09/13**: unconfigured team defaults to Round robin; switching to Least open fires `PUT .../team-settings/{teamId}` 200 and persists. |
| AC-TEM-29 | BE | PASS | `test_thread_item_team_fields_batched`. E2E 15: every list row carries the team name; the list render made one batched call. |
| AC-TEM-30 | BE | PASS | `test_team_id_list_filter`. **E2E 15**: rail click -> `GET /omnichannel/contacts?...&teamId=<id>` -> exactly the 3 team threads (c4/c5 excluded). Live: `teamId` + `assignee=unassigned` returned exactly the team's Unassigned thread; a foreign team id returned an empty page, not a 404. |

### Slice D - events + workflow action

| ID | Tag | Result | Evidence |
|---|---|---|---|
| AC-TEM-31 | BE | PASS | `test_assignment_event_payload_carries_team`, `test_assignment_event_manual_via_carries_assigneekind`. Live feed rows: manual team assign -> `assignedVia: "team_strategy"`, `change: "both"`; workflow assign -> `assignedVia: "workflow"`, `change: "team"`, plus `workflowId` + `runId`. A run re-sending the same team and assignee wrote **no event** (verified: the feed's newest row was still the earlier manual one). |
| AC-TEM-32 | BE | PASS (backend) - see D1 | `test_assign_conversation_action_registered_with_fields` and the six sibling executor tests. E2E 24: a real run routed through `patch_thread` and produced the event row. **The action is not reachable from the workflow editor** - defect D1; AC-TEM-32 is tagged `[BE]` so the registration/executor contract itself passes. |
| AC-TEM-33 | BE | PASS | `test_assign_conversation_module_inactive_rejected`, `test_assign_conversation_cross_tenant_rejected`, `test_assign_conversation_foreign_team_is_action_error`. |
| AC-TEM-34 | BE | PASS | `test_workflow_service_metadata_includes_teams_when_requested`, `test_workflow_metadata_endpoint_gates_teams_on_permission`, `test_workflow_metadata_teams_tenant_scoped`. Live: tenant A's metadata lists only A's team, tenant B's only B's. |
| AC-TEM-35 | BE | PASS | `test_assign_conversation_mode_team_no_eligible_member_succeeds`. |

### Slice E - public gateway + consumer guide

| ID | Tag | Result | Evidence |
|---|---|---|---|
| AC-TEM-36 | BE | PASS | `test_gateway_default_and_rio_shapes_carry_team_fields`, `test_gateway_webhook_contact_updated_payload_carries_team_fields`. Live with a real workspace API key: `GET /api/v1/omnichannel/contacts/{id}` and `GET /api/v1/omnichannel/contacts` both carry `assignedTeamId` + `assignedTeamName`, populated on the three team threads and `null` on the two others. |
| AC-TEM-37 | BE | PASS | `test_gateway_patch_team_plus_user_combinations`, `test_gateway_patch_unknown_team_id_is_422`, `test_gateway_rio_message_sender_team_id_stays_null`. Live: `?format=rio` carries both keys; gateway `PATCH assignedTeamId` by id -> 200 and ran the strategy; unknown id -> 422 `invalid_request`; a **foreign-tenant** team id -> the same 422. |
| AC-TEM-38 | BE T | PASS | `test_consumer_guide_documents_the_team_fields`. `documentation/omnichannel/consumer-integration-guide.md` carries 14 `assignedTeam*` references: a changelog row, the contact shape, the PATCH field table with all four user/team interaction cases, the rio field-mapping table and the `contact.updated` trigger note. |

### Slice F - frontend: core Teams admin surface

| ID | Tag | Result | Evidence |
|---|---|---|---|
| AC-TEM-39 | FE | **FAIL** (filter clause only) | Columns are exactly Name / Description / Members / Status / Created and row click opens the form (E2E 04). Search and sort ARE server-served (`&search=`, `sort_by`/`sort_dir` observed). **Filters is a no-op**: applying `Name contains "ZZZ-no-match"` refetches as `GET /teams?page=0&page_size=25&sort_by=name&sort_dir=asc` with no filter param and the non-matching row stays (E2E 08). Known review finding, under repair in the uncommitted fix round; reported as **D2**. |
| AC-TEM-40 | FE | PASS | `use-team-form.test.tsx`, `team-form-fields.test.tsx`. E2E 05: Leads is **disabled with "Add members first"** until Members are picked and then offers only the selected Members. Dirty-guard clause: no AlertDialog fires on Cancel or on navigating away - but the **Users reference form behaves identically** (verified side by side), so this is shell-wide behaviour on this build, not a Teams regression. |
| AC-TEM-41 | FE | PASS | E2E 03: Teams sits next to Roles in the sidebar. As P28 Agent 1 (no `teams.read`) a DOM sweep found **zero** `/user-management/teams` links in the sidebar and zero in the mega menu. |
| AC-TEM-42 | FE | PASS | E2E 31/32: as the `teams.read`-only user the list has no "Add team" and no row Actions cell, and the detail page reports `editBtn:false, saveBtn:false, actionsBtn:false, editableInputs:0`. A guard-blocked delete surfaces the per-source count with no destructive effect (E2E 23). No instructional copy and no stale-brand string on any Teams surface (the AC-TEM-42 white-label clause); pinned by `lib/white-label.guard.test.ts`. |
| AC-TEM-43 | FE | PASS | E2E 27/28/29: list and detail at 375px both report `scrollWidth == clientWidth == 375`; the Members MultiSelect popover measures left 37 / right 253 in a 375 viewport - fully clamped. |

### Slice G - frontend: Team Inbox + assign-to-team

| ID | Tag | Result | Evidence |
|---|---|---|---|
| AC-TEM-44 | FE | PASS | `inbox-view-rail.test.tsx` Teams block, `inbox-rail-entries.test.ts`, `use-inbox-rail-selection.test.ts`. E2E 10: MY TEAMS + ALL TEAMS with nested Unassigned, ALL TEAMS gated on `conversations.assign` (absent for the agent, E2E 17). E2E 15/16: selection sets `?team=` (+`&assignee=unassigned`) and both survive a reload. E2E 19/20: below 1024px the same entries appear in the View SearchSelect under a "My teams" group - no new layout. |
| AC-TEM-45 | FE | PASS | `conversation-drawer.teams.test.tsx`. E2E 11: the assignee dropdown gains a **Teams** group under the member list; picking it sends `assignedTeamId` and the header reads "Support 1788683909 - P28 Agent 1". E2E 24/25 cover the "team + Unassigned" header when no member is eligible. |
| AC-TEM-46 | FE | **DEFERRED** | At `7814fcf` the running backend rejects `teamIds`: `POST .../inbox-views {"filter":{"teamIds":[...]}}` -> 422 `extra_forbidden`. `extra="forbid"` still 422s a genuinely unknown key and a legacy view with no `teamIds` still saves 201, so the back-compat half holds. The uncommitted fix round adds `teamIds` to `InboxViewFilter` with tenant-scoped save-time validation; per the brief this is deferred to that round rather than failed. |
| AC-TEM-47 | FE | PASS | E2E 11/12/14: the thread row, the drawer header and the rail bucket all update off the single PATCH response with no manual refresh. `use-conversations.test.ts` covers the optimistic-revert-on-422 path; live 422s (inactive team, non-member user) left the UI on the server state with the server message surfaced. |
| AC-TEM-48 | FE | PASS | E2E 18/19/20 at 375px, E2E 10/15 at 1280px; `scrollWidth == clientWidth == 375` on the inbox. Plan-23 hard-fails: `lib/white-label.guard.test.ts` and the inventory tests are green in the vitest run. |

### Slice H - tests + evidence

| ID | Tag | Result | Evidence |
|---|---|---|---|
| AC-TEM-49 | T | PASS | `tests/test_teams.py` (32 tests) + `tests/test_omnichannel_team_assignment.py` (32 tests) + the 6 gateway team tests in `tests/test_omnichannel_api_gateway.py` cover every enumerated item: CRUD, ci-unique name, member-validation rollback, tenant_id derivation, delete 204/409, `/teams/mine` without `teams.read`, isolation, the 403 matrix, migration ids, capability resolution in both boot paths, foreign-tenant None, the absent-capability degrade, round-robin across fresh instances, `least_open` scoping, eligibility, empty roster, precedence and clearing, embed 403, team-settings CRUD, the `teamId` filter, event payloads, the workflow action, and the gateway shapes plus the guide-drift test. Full suite **3123 passed, 1 skipped**. |
| AC-TEM-50 | T E2E | PASS | vitest: `use-teams-list-config.test.tsx`, `use-team-form.test.tsx`, `team-form-fields.test.tsx`, `inbox-view-rail.test.tsx` (Teams block), `conversation-drawer.teams.test.tsx`, `use-conversations.test.ts`, `use-my-teams.ts`/`use-teams.ts`/`use-team-settings.ts` tests, `node-config-drawer.team-field.test.tsx`, `workspace-team-settings-tab.test.tsx`. E2E: the full recorded run in `28-evidence/E2E/` on the dedicated timestamped tenant `p28-1788683909`, real clicks from `/`, 32 screenshots at 1280 and 375, plus the cross-tenant probe table (uniform 404 / empty) and the no-`teams.read` menu sweep. |

## 3. Score

| Result | Count | IDs |
|---|---|---|
| PASS | 48 | all except the two below |
| FAIL | 1 | AC-TEM-39 (Filters clause) |
| DEFERRED | 1 | AC-TEM-46 |

## 4. Defects

**D1 - `omnichannel.assign_conversation` is unreachable from the workflow editor.** NEW.
- Registered backend-side at `service_backend/modules/omnichannel/workflow_nodes.py:212` with the full field set, but **absent from `service_frontend/lib/workflow-catalog.ts`**, which carries the other three omnichannel nodes (`omnichannel.message_received` line 149, `omnichannel.get_contact` line 340, `omnichannel.send_message` line 368).
- Repro: sign in as the tenant Admin -> Workflows -> New workflow -> palette search "assign" -> no results; search "conversation" -> only "Send Message". Expanding ACTIONS lists 13 entries, none of them Assign Conversation.
- Impact: a tenant cannot build the plan's headline automation through the UI. The action is only invocable by writing the node into `draftDefinition` over the API (which is how E2E 24 was produced).
- `lib/workflow-catalog.ts` is **not** among the concurrent fix round's modified files, so this is an open gap rather than work already in flight.
- Backlog candidate: plan 28 range (082-091); main's numbering is authoritative at merge.

**D2 - Teams list Filters does not reach the API.** Known review finding, under repair.
- Repro: Teams -> Filters -> `Name` `contains` `ZZZ-no-match` -> Apply. The list refetches as `GET /teams?page=0&page_size=25&sort_by=name&sort_dir=asc` (no filter param) and the non-matching row remains visible. `search` and `sort` on the same list are correctly server-served.
- Breaks the "filter ... served by the API" clause of AC-TEM-39. Evidence E2E 08.

**D3 - `GET /teams/mine` returns member email addresses.** Known review finding, under repair.
- Repro: as P28 Agent 1 (holds neither `teams.read` nor `teams.manage`), `GET /teams/mine` returns 200 with each member's `email` populated. The endpoint exists precisely so an inbox agent can render the rail without `teams.read`, so it should not carry PII the caller is not entitled to.

**D4 - the agent's inbox rail fires a `teams.read`-gated call it cannot make.** Known review finding, under repair.
- Repro: as P28 Agent 1, opening the Inbox issues `GET /teams?page=0&page_size=200&...` which **403s** (twice per load), alongside the successful `GET /teams/mine`. The surface degrades correctly (MY TEAMS still renders, ALL TEAMS is correctly hidden), so this is wasted requests and log noise rather than a broken screen.

**D5 - `inbox-view-rail.test.tsx` deferred-action test is load-sensitive.** Test infrastructure.
- Repro: `npx vitest run` (full suite) -> `Delete parks 'inbox_views.delete' ...` fails `expected undefined to be 'inbox_views.delete'`. Reproduced 2/2. `npx vitest run "app/(protected)/omnichannel/inbox/components/inbox-view-rail.test.tsx"` -> 13/13 pass.
- Cause: the test arms a real 50 ms deferred-action window against a real 1 s poll tick, so under full-suite CPU contention the action commits before the assertion reads `pending`. The block is plan-27 code from `main`; plan 28 appended a Teams `describe` to the same file, which lengthened it enough for the race to lose consistently.
- Backlog candidate: plan 28 range.

## 5. Deferred

**AC-TEM-46 - saved inbox views cannot store a team scope (at `7814fcf`).**
- Observed: `POST /omnichannel/workspaces/{ws}/inbox-views` with `{"filter":{"teamIds":[<valid team>]}}` -> **422 `extra_forbidden`** on `body.filter.teamIds`. The same 422 shape is returned for a genuinely unknown key (`bogusKey`), and a legacy filter with no `teamIds` still saves **201**, so the `extra="forbid"` and back-compat halves of the AC hold.
- Reason for DEFERRED rather than FAIL: the concurrent fix round has already added `teamIds: Optional[List[str]]` to `InboxViewFilter` (`modules/omnichannel/schemas.py`, with a comment citing AC-TEM-46 and tenant-scoped validation via `team.resolve@1`), together with `services/inbox_view_service.py` changes. That work is uncommitted and therefore absent from the build under test. Per the brief, this is deferred to the fix round for re-verification.
- Re-verify after the fix round lands: save a view with a valid `teamIds`, confirm a foreign/unknown team id is rejected tenant-scoped, confirm an unknown key still 422s, and confirm pre-existing views still load.

## 6. Not verified

- **Multi-tab WebSocket reconciliation** of `contact.updated` for a team assignment was not re-verified with a second concurrent browser tab. The single-tab path was verified end to end (row + drawer header updated off the one PATCH response, no refresh), and the publish path is covered by the existing pipeline, but the cross-session push itself was not independently observed this run.
- **The uncommitted fix round.** Everything in this report describes `7814fcf`. The 40 modified files in the working tree at the time of writing (team service/repository/schemas, the deferred-action handlers, the rail, `use-teams-list-config.tsx`, `use-team-actions.tsx`, the inbox view service) are **not** covered here and need their own pass.
- **Team delete as a deferred action.** At `7814fcf` the delete is the disclosed plain-confirm `AlertDialog` carve-out, which is what E2E 22 records. `app/deferred_actions/handlers.py`, `use-team-actions.tsx` and `lib/deferred-verb.ts` are modified in the uncommitted fix round, so the deferred-action variant is unverified.

## 7. Alembic up/down/up transcript (review round 1 finding 12 / round 2)

Real run on the lane DB (`foundryx_service_s28`) by the round-2 coder, 2026-09-06, from
`.claude/worktrees/s28/service_backend` with
`DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_s28` and
`PYTHONPATH=.` exported. Core = `alembic` CLI (`alembic/env.py` reads `settings.database_url`);
module = the same `alembic.command` calls `app/module_platform/migrations.py::run_module_migrations`
issues, driven from a small script (`/tmp/s28_module_mig.py`) that builds the identical `Config`
(`script_location=modules/omnichannel/alembic`, version table
`app_omnichannel.alembic_version_omnichannel`, `target_metadata=_module_metadata("omnichannel")`)
so `downgrade` can be exercised (the loader only ever runs `upgrade head`/`stamp`). Order: module
down -> core down -> core up -> module up (the module column/table hold plain string ids, no
cross-schema FK, so either order works; this one mirrors a real rollback). The `:8007` backend was
restarted afterwards (PID 64904 -> 24933, cwd-verified) because the cycle drops and recreates the
`teams`/`team_members`/`team_assignment_settings` tables and the `contacts.assigned_team_id`
column (existing rows in those are lost - expected for a down/up on a lane DB).

Migrations under test: core `teams_core_s428` (`alembic/versions/teams_core_s428_teams_core.py`,
down_revision `b7c1d2e3f4a5`) and module `0011_omni_team_assignment`
(`modules/omnichannel/alembic/versions/0011_omni_team_assignment.py`, down_revision
`0010_omni_contacts_module`). Both were head before and after.

```text
$ alembic current (core)
teams_core_s428 (head)

$ python /tmp/s28_module_mig.py current (omnichannel, version table app_omnichannel.alembic_version_omnichannel)
0011_omni_team_assignment (head)

$ psql schema check (before)
teams|team_members|app_omnichannel.team_assignment_settings|1

$ python /tmp/s28_module_mig.py downgrade 0010_omni_contacts_module
0010_omni_contacts_module

$ alembic downgrade b7c1d2e3f4a5 (core)
INFO  [alembic.runtime.migration] Running downgrade teams_core_s428 -> b7c1d2e3f4a5, Teams (core) - plan 28 S1, roadmap A8 D-A8-1.

$ psql schema check (after down)
<absent>|<absent>|<absent>|0

$ alembic upgrade head (core)
INFO  [alembic.runtime.migration] Running upgrade b7c1d2e3f4a5 -> teams_core_s428, Teams (core) - plan 28 S1, roadmap A8 D-A8-1.

$ python /tmp/s28_module_mig.py upgrade head
0011_omni_team_assignment (head)

$ psql schema check (after up)
teams|team_members|app_omnichannel.team_assignment_settings|1
```

Schema-check columns: `teams | team_members | team_assignment_settings | contacts.assigned_team_id
column count`. `<absent>`/`0` after the downgrade and all four back after the upgrade is the
pass condition. Result: **PASS** (cycle clean, no residue, both version tables back at head).
