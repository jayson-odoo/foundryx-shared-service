# Issue #94 - Ideation round 2: merge and unmerge, form fixes, priority rank, engine statuses, requester status updates · Acceptance Criteria

**Source plan:** `PLAN-ideation-round-2-merge-unmerge.md`
**Issue:** [jayson-odoo/foundryx-shared-service#94](https://github.com/jayson-odoo/foundryx-shared-service/issues/94) (owner rulings in the issue comments bind; ruling of 28 Sep 2026: merge/unmerge, engine statuses, priority fix and a status update on every stage change are all confirmed)
**Build branch:** ONE PR against `main` (owner rule). Plan branch: `plan/ideation-round-2-merge-unmerge`.
**Cross-repo:** the status-update WhatsApp SEND ships in the CRM (sorento) PR; this repo ships the event feed only (plan section 7).

Format: each AC is independently verifiable (Given/When/Then). `[BE]` backend · `[FE]` frontend · `[E2E]` recorded agent-browser run (real clicks from the sidebar, 375px AND 1280px, evidence under `documentation/plans/ideation/94-evidence/<slice>/`) · `[T]` automated test (pytest or Vitest). The Test Execution Report keys PASS/FAIL/DEFERRED back to these ids.

Unless stated otherwise, "the list" means both the operator list (`/ideation/ideas`) and the embed list (`/embed/ideas`); every operator route named below has an embed twin that behaves the same, scoped to the embed token's tenant AND product.

---

## A. Merge and unmerge - data and API (AC-94-01..20)

### AC-94-01 - merge collapses the group onto the chosen survivor [BE][T]
- **Given** captured ideas A, B, C in one tenant, one product, all real (`is_test` false), none archived, **when** `POST /ideation/ideas/merge {survivorId: A, ideaIds: [A, B, C]}` is called by a user holding `ideation.triage.manage`, **then** B and C carry `merged_into_id = A` and a `merged_at` timestamp, A carries none, and the response is A's `IdeaOut` with `mergedCount = 2`.
- Test: `test_merge_sets_pointer_and_count` (`tests/test_ideation_merge.py`).

### AC-94-02 - the list and board show survivors only [BE][T]
- **Given** AC-94-01, **when** `GET /ideation/ideas` (any `filter`) and `GET /ideation/ideas/board` are called, **then** A appears with `mergedCount = 2` and B and C never appear.
- Test: `test_list_and_board_hide_merged_children`.

### AC-94-03 - a merged child is still readable [BE][T]
- **Given** AC-94-01, **when** `GET /ideation/ideas/{B}` is called, **then** 200 with `mergedIntoId = A` and `mergedInto = {id, ideaNumber, title}` of A; and `GET /ideation/ideas/{A}/merged` returns exactly [B, C] (oldest merge first).
- Test: `test_child_detail_and_merged_listing`.

### AC-94-04 - merge refuses invalid selections [BE][T]
- **Given** each of: fewer than 2 ids; `survivorId` not in `ideaIds`; ideas on two products; a mix of `is_test` true and false; any selected idea in an `is_archived` status; any selected id that is already a merged child; an id from another tenant, **when** merge is called, **then** 422 (404 for the other-tenant id, uniform with "not found") and NOTHING is written.
- Test: `test_merge_rejects_invalid_selection` (parametrized, 7 cases, each asserting zero rows changed).

### AC-94-05 - merging a survivor flattens (one level only) [BE][T]
- **Given** A is the survivor of B, **when** A and D are merged with survivor D, **then** A AND B both carry `merged_into_id = D` (no chain: no row points at a row that itself points somewhere).
- Test: `test_merge_flattens_existing_group`.

### AC-94-06 - votes follow the merge and come back on unmerge [BE][T]
- **Given** voter v1 upvoted B only, voter v2 upvoted both A and B, **when** B is merged into A, **then** v1's vote row moves to A with `origin_idea_id = B`; v2's B row stays on B (shadowed, A already has v2); A's tallies are recomputed from its rows (A: 2 up); **when** B is unmerged, **then** v1's row returns to B, and both A and B tallies are recomputed.
- Test: `test_votes_move_and_return`.

### AC-94-07 - unmerge a single child [BE][T]
- **Given** AC-94-01, **when** `POST /ideation/ideas/{B}/unmerge` is called, **then** B's `merged_into_id` and `merged_at` are cleared, B is back in the list with its pre-merge status, A's `mergedCount` is 1, and the response lists [B].
- Test: `test_unmerge_child`.

### AC-94-08 - unmerge a survivor dissolves its group [BE][T]
- **Given** AC-94-01, **when** `POST /ideation/ideas/{A}/unmerge` is called, **then** B and C are both restored and A's `mergedCount` is 0.
- **Given** an idea that is neither a child nor a survivor, **then** 422 and nothing changes.
- Test: `test_unmerge_survivor_dissolves_group`, `test_unmerge_plain_idea_422`.

### AC-94-09 - a merged child is frozen [BE][T]
- **Given** B is merged into A, **when** `POST /{B}/status`, `POST /{B}/vote`, or a BR promote/link including B is called, **then** 409 (status, vote) or 422 (BR link) with a message naming A's idea number, and B is unchanged. `PATCH /{B}` (text fields) still succeeds.
- Test: `test_merged_child_is_frozen`.

### AC-94-10 - deleting a survivor restores its children first [BE][T]
- **Given** A is the survivor of B and C, **when** A is deleted (direct route or the `ideation_ideas.delete` deferred action), **then** B and C are restored (unmerged, votes moved back) BEFORE A's rows are removed.
- Test: `test_delete_survivor_restores_children`.

### AC-94-11 - dedup and clustering ignore merged children [BE][T]
- **Given** B is merged into A, **then** `DedupService.find_duplicate` never returns B as a candidate, the intake duplicate-vote path resolves a candidate to its survivor, and `GET /ideation/ideas/clusters` never includes B (both the `pg_trgm` and the `difflib` fallback paths).
- Test: `test_dedup_and_clusters_skip_merged`.

### AC-94-12 - the survivor always has an idea number [BE][T]
- **Given** an operator-captured survivor with no `idea_number` (BL-SS-280 shape), **when** it becomes a survivor, **then** merge mints its `idea_number` and `status_token` (`mint_idea_identity`, idempotent) so "merged into IDEA-xxxx" always has a number.
- Test: `test_merge_mints_survivor_identity`.

### AC-94-13 - the public page of a merged child keeps working [BE][T]
- **Given** B (captured over WhatsApp, has a `status_token`) is merged into A, **when** `GET /public/ideas/{B's token}` is called, **then** 200 with B's own `title`/`problem`/fields, `mergedInto = {ideaNumber, title}` of A, and `status`, `statusColor`, `timeline`, `nextStep`, `upvotes` taken from A. After unmerge the same token shows B's own status again with `mergedInto = null`.
- Test: `test_public_page_of_merged_child`.

### AC-94-14 - the public key set grows by exactly one key [BE][T]
- **Given** any servable idea, **then** the key set is AC-90-104's set plus `mergedInto` - nothing else; no PII rule changes; the survivor's submitter name never appears on the child's page.
- Test: `test_public_status_exact_key_set_and_no_pii` (updated deliberately).

### AC-94-15 - merge and unmerge are tenant scoped end to end [BE][T]
- **Given** tenant T1 and T2 each with ideas, **when** a T1 user merges using any T2 id (as survivor or member), **then** 404 and no T2 row is read or written; the survivor lookup on the public page is scoped by the child's own `tenant_id`.
- Test: `test_merge_tenant_isolation`.

### AC-94-16 - embed parity with product scope [BE][T]
- **Given** an embed token scoped to product P, **when** `POST /embed/ideas/merge`, `POST /embed/ideas/{id}/unmerge`, or `GET /embed/ideas/{id}/merged` targets an idea on another product, **then** 404 and nothing changes; within P they behave as AC-94-01..08.
- Test: `test_embed_merge_unmerge_scope` (`tests/test_ideation_embed_writes.py`).

### AC-94-17 - permission reuse, no new key [BE][T]
- **Given** a user WITHOUT `ideation.triage.manage`, **when** merge or unmerge is called, **then** 403; `ideation/permissions/permissions.csv` gains no row.
- Test: `test_merge_requires_triage_manage`.

### AC-94-18 - migration 0012 applies and backfills [BE][T]
- **Given** a Postgres database at `0011_ideation_br_is_test`, **when** `alembic upgrade head` runs for the ideation module, **then** revision `0012_ideation_merge_rank_events` (31 chars) adds `ideas.merged_into_id` (indexed, NO foreign key), `ideas.merged_at`, `idea_votes.origin_idea_id`, the `idea_status_events` table, and rewrites every existing idea's `priority` to a dense 1-based order per `(tenant_id, is_test)` that preserves today's visible order; downgrade removes them. Idempotent (`IF NOT EXISTS`).
- Test: `test_migration_0012_head_and_revision_length` + a live `bootstrap_db` run recorded in the evidence README.

### AC-94-19 - reorder ignores merged children [BE][T]
- **Given** B is a merged child, **when** `PUT /reorder` includes B, **then** B's priority is untouched and no error is raised.
- Test: `test_reorder_skips_merged_children`.

### AC-94-20 - unmerge restores list position [BE][T]
- **Given** B had priority rank 3 before merge, **when** B is unmerged, **then** B reappears at its stored priority (no forced append), ties broken by `created_at desc, id desc`.
- Test: `test_unmerge_restores_position`.

## B. Merge and unmerge - screens (AC-94-21..32)

### AC-94-21 - Merge in the bulk Actions menu [FE][T]
- **Given** 2 or more active ideas selected, **then** the bulk Actions menu shows "Merge"; with 1 selected it is hidden; with a mixed-product or mixed test/real selection it is disabled; in the Archived view it is hidden; on the operator surface it requires `ideation.triage.manage` via `useCan`.
- Test: `use-ideas-list-config.test.tsx` "merge visibility".

### AC-94-22 - the survivor picker is the system dropdown [FE][T]
- **Given** Merge is clicked, **then** a dialog opens with a `SearchSelect` (`components/platform/search-select/search-select.tsx`) whose options are EXACTLY the selected ideas (idea number and title), no default pick, and the Merge button disabled until a survivor is picked. No other select control is rendered.
- Test: `merge-ideas-dialog.test.tsx`.

### AC-94-23 - merged count badge [FE][T]
- **Given** a survivor with `mergedCount = 2`, **then** its Idea cell shows a badge reading "2 merged"; a plain idea shows none.
- Test: `use-ideas-list-config.test.tsx` "merged badge".

### AC-94-24 - list Unmerge on a survivor [FE][T]
- **Given** one or more survivors selected, **then** bulk and row Actions show "Unmerge", which calls `unmerge(id)` per survivor and reloads; hidden when any selected row has `mergedCount = 0`.
- Test: `use-ideas-list-config.test.tsx` "unmerge visibility".

### AC-94-25 - "Merged from" tab on the survivor form [FE][T]
- **Given** a survivor form, **then** a "Merged from" tab appears (hidden when `mergedCount = 0`) listing the children on the shared `ResourceList` (clone of `IdeaBrsTab`), each row opening that child's form, with a row and bulk "Unmerge" action.
- Test: `idea-merged-tab.test.tsx`.

### AC-94-26 - the child form [FE][T]
- **Given** a merged child's form, **then** Details shows a "Merged into" row linking to the survivor; the gear offers "Unmerge" and "Delete" only (no Advance, Archive, Restore, Promote, Merge); the vote control is disabled.
- Test: `use-idea-form.test.tsx` "merged child".

### AC-94-27 - E2E: merge two ideas [E2E]
- **Given** two timestamp-named ideas, **when** the tester clicks Ideation > Ideas in the sidebar, ticks both rows, opens Actions > Merge, picks the survivor in the dropdown and clicks Merge, **then** the list shows one row with "1 merged". Screenshots at 375 and 1280.

### AC-94-28 - E2E: open a merged child from the survivor [E2E]
- **When** the tester opens the survivor, clicks the "Merged from" tab and the child row, **then** the child form shows "Merged into IDEA-xxxx"; clicking that link returns to the survivor. 375 and 1280.

### AC-94-29 - E2E: unmerge from the child form [E2E]
- **When** the tester opens the child's gear and clicks Unmerge, **then** a success toast appears and, back on the list, both ideas are rows again with no badge. 375 and 1280.

### AC-94-30 - E2E: unmerge from the list [E2E]
- **When** the tester merges three ideas, then ticks the survivor and clicks Actions > Unmerge, **then** all three are rows again. 1280 (375 screenshot of the Actions menu).

### AC-94-31 - E2E: the requester's track link after merge [E2E]
- **Given** a WhatsApp-captured idea with a track link, merged into another, **when** the tester opens the track link (the public page is only ever reached by its link - the one sanctioned URL entry), **then** it reads "Merged into IDEA-xxxx" with the survivor's status and timeline. 375 and 1280.

### AC-94-32 - E2E: embed parity [E2E]
- **Given** an embed session minted through an embed connection (Ideation > Embed connections), **when** the tester merges and unmerges inside `/embed/ideas`, **then** the behaviour matches AC-94-27..29. 1280 and 375. DEFERRED with a written reason only if the host assertion cannot be minted locally.

## C. Form view fixes (AC-94-33..40)

### AC-94-33 - no Status dropdown [FE][T]
- **Given** an idea form in edit mode, **then** no status control is rendered; the form schema has no `status` field; `idea-form-fields.tsx` no longer imports `@/components/ui/select`. **In read mode there is no Status row either** (owner Q5, 28 Sep): the form renders no status in any mode.
- Test: `idea-form-fields.test.tsx` "no status select".

### AC-94-34 - save never moves status [FE][T]
- **Given** an edit and Save, **then** only `PATCH /ideation/ideas/{id}` is called (never `/status`).
- Test: `ideation-service.real.test.ts` "updateIdea is fields only".

### AC-94-35 - clickable votes in the form [FE][T]
- **Given** a live idea's form (read or edit mode), **then** the Votes row renders the same `VoteCell` the list uses (extracted to `components/vote-cell.tsx`), clicking up/down calls `vote(id, dir)` and updates counts and pressed state in place.
- Test: `vote-cell.test.tsx`, `use-idea-form.test.tsx` "vote".

### AC-94-36 - record pager "n / N" [FE][T]
- **Given** the form opened from the list (URL carries `ctx` and `i`), **then** the `RecordNav` pager shows "n / N" matching the list's filter, search and order; prev/next moves to the neighbour and wraps; the pager is hidden in edit mode and when there is no list context; `includeTest` rides along like `brFormHref`.
- Test: `use-idea-form.test.tsx` "recordNav fetchAt order equals list order".

### AC-94-37 - E2E: form votes [E2E]
- **When** the tester opens an idea from the list and clicks the up arrow, **then** the up count increments and the arrow shows pressed; clicking again cancels. 375 and 1280.

### AC-94-38 - E2E: pager [E2E]
- **When** the tester opens the 2nd row and clicks Next twice, **then** the pager reads "3 / N" then "4 / N" and the title changes to those rows' titles. 375 and 1280.

### AC-94-39 - E2E: edit mode has no status control [E2E]
- **When** the tester clicks Edit on an idea, **then** no Status control is visible; Save succeeds. 375 and 1280.

### AC-94-40 - the pager works in the embed [FE][T]
- **Given** embed mode, **then** `paths.formHref(id, {ctx, index})` builds `/embed/ideas/{id}?ctx=..&i=..` (token never in the query) and the pager navigates within the embed.
- Test: `embed-ideas.test.tsx` "pager".

## D. Priority rank (AC-94-41..48)

### AC-94-41 - rank is 1-based and server computed [BE][T]
- **Given** three active ideas ordered by priority, **then** `GET /ideation/ideas` returns them in that order with `rank` 1, 2, 3; archived ideas and merged children carry `rank = null`.
- Test: `test_rank_is_one_based` (`tests/test_ideation_priority_rank.py`).

### AC-94-42 - rank follows the caller's scope [BE][T]
- **Given** a product-scoped embed token or `?productId=`, **then** `rank` is the position within that product's active ideas; the operator list without a product filter ranks across the tenant; the test lane ranks separately from the real lane.
- Test: `test_rank_scope`.

### AC-94-43 - the detail carries the same rank [BE][T]
- **Given** idea X at list position 4, **then** `GET /ideation/ideas/{X}` returns `rank = 4` under the same scope.
- Test: `test_detail_rank_matches_list`.

### AC-94-44 - a new capture gets a real rank at the end [BE][T]
- **Given** 5 active ideas, **when** an idea is captured (operator create OR the WhatsApp sink's draft to captured), **then** its stored priority is the lane maximum plus 1 and its `rank` is 6.
- Test: `test_new_capture_appends` (both paths).

### AC-94-45 - a page-2 drag no longer collides with page 1 [BE][T]
- **Given** 15 ideas ranked 1..15, **when** `PUT /reorder` receives only ranks 11..15's ids in a new order (what a page-2 drag sends, `resource-list.tsx:256`), **then** those five ideas swap among slots 11..15 only; ranks 1..10 are unchanged and all 15 stay unique.
- Test: `test_reorder_is_slot_preserving`.

### AC-94-46 - the form shows the rank [FE][T]
- **Given** an idea with `rank = 1`, **then** the Priority row reads "#1"; with `rank = null` it reads "-". The raw stored `priority` is never rendered.
- Test: `idea-form-fields.test.tsx` "priority rank".

### AC-94-47 - list order is the server's order [FE][T]
- **Given** the list fetcher, **then** it keeps the server order (no client `.sort`); search and the Active/Archived view are applied by ONE shared helper also used by the pager.
- Test: `use-ideas-list-config.test.tsx` "server order".

### AC-94-48 - E2E: drag then open [E2E]
- **When** the tester drags the 3rd row to the top and opens it, **then** the form reads "Priority #1"; capturing a new idea and opening it shows the last rank. 1280 (drag) and 375 (form).

## E. Status labels, colours and transitions from the statuses engine (AC-94-49..60)

### AC-94-49 - the API returns the engine's display [BE][T]
- **Given** any idea, **then** `IdeaOut` carries `statusId`, `statusLabel`, `statusColor`, `statusIsArchived` from the tenant's resolved status tier, next to the existing `status` key.
- Test: `test_ideaout_status_display` (`tests/test_ideation_status_display.py`).

### AC-94-50 - a rename shows everywhere [BE][T]
- **Given** a tenant renames "Triaged" to "Discussed" (which forks the set, remapping records), **then** list, detail, board column title, the advance label source and the public page all return "Discussed".
- Test: `test_rename_flows_through`.

### AC-94-51 - per-record fireable transitions [BE][T]
- **Given** an idea, **then** `IdeaOut.transitions` lists the edges the caller may fire from the idea's current status (label, target id, target label), using `status_machine.fireable_edge_ids(..., always=True)`; an edge whose conditions fail or whose roles exclude the caller is absent; embed (actor none) never sees a role-restricted edge.
- Test: `test_transitions_are_fireable_only`.

### AC-94-52 - advance = the next stage by sort order [BE][T]
- **Given** an idea, **then** `advanceTransitionId` is the fireable edge whose target has the smallest `sort_order` strictly greater than the current status's; `null` when none. A tenant that swaps two stages' order changes the advance target with no code change.
- Test: `test_advance_follows_sort_order`.

### AC-94-53 - moves by target status id [BE][T]
- **Given** `POST /{id}/status {toStatusId}`, **then** the move runs through `status_machine.transition`; a target outside the idea entity or the tenant tier is 422; a missing edge is 409. The key form `{status}` keeps working for the deferred Archive handler.
- Test: `test_status_move_by_id`.

### AC-94-54 - board columns from trait flags [BE][T]
- **Given** the tier's status set, **then** `GET /ideation/ideas/board` columns are the statuses with `is_initial` false, `is_archived` false, `is_active` true, ordered by `sort_order`, each `{statusId, key, title (label), color}`. `BOARD_COLUMNS` and `_ARCHIVED_KEYS` are deleted from `services/ideas.py`; the list's active/archived filter reads `is_archived`.
- Test: `test_board_columns_from_flags`.

### AC-94-55 - frontend constants deleted [FE][T]
- **Given** the frontend, **then** `IDEA_STATUS_LABEL`, `IDEA_NEXT_STATUS`, `IDEA_BOARD_COLUMNS` and the `IdeaStatus` union no longer exist, and `grep -rn "IDEA_STATUS_LABEL\|IDEA_NEXT_STATUS\|IDEA_BOARD_COLUMNS" service_frontend` returns nothing.
- Test: `ideation-constants.inventory.test.ts`.

### AC-94-56 - labels and colours render from the API [FE][T]
- **Given** an idea with `statusLabel = "Discussed"` and `statusColor = "indigo"`, **then** the list Status column renders a `StatusBadge` reading "Discussed" (the form shows no status, AC-94-33) with the `colorToHex` dot; the CSV export writes the label.
- Test: `use-ideas-list-config.test.tsx` "status from API".

### AC-94-57 - Advance to next stage (row, form, bulk) [FE][T]
- **Given** rows whose `advanceTransitionId` targets the same label, **then** the action reads "Move to {label}"; a mixed selection reads "Advance to next stage"; disabled when any row has no advance; each row fires its OWN edge; the success toast names the label (never a key).
- Test: `use-ideas-list-config.test.tsx` "advance".

### AC-94-58 - board columns and drops from the API [FE][T]
- **Given** the board, **then** columns come from `GET /board` (operator) or `GET /embed/board` (embed); a card can only be dropped on a column its `transitions` reach; a drop fires that edge by id.
- Test: `board/page.test.tsx` "columns from API", "invalid drop refused".

### AC-94-59 - E2E: rename in the statuses engine [E2E]
- **When** the tester opens the statuses engine from the sidebar, renames the Idea status "Triaged" to a timestamped "Discussed-<ts>", then clicks Ideation > Ideas, **then** the Status column, the Advance label on a New idea, the board column and the public track page all read the new name; the idea form shows no status (AC-94-33). Run on a dedicated tenant (the rename forks the set). 375 and 1280.

### AC-94-60 - Archived view shows archived ideas [FE][BE][T]
- **Given** an archived idea, **when** the list switches to the Archived view, **then** the idea is listed with Restore available (today the view is always empty: the FE loads `filter=active` then filters `status === 'archived'`).
- Test: `use-ideas-list-config.test.tsx` "archived view" (red first).

## F. Requester status updates - event feed (AC-94-61..72)

### AC-94-61 - every stage change writes an event [BE][T]
- **Given** a WhatsApp-captured idea (has a submitter contact and a `status_token`), **when** it moves along any edge whose FROM status is not `is_initial` (triage, link, build, deliver, close, reject, mark duplicate, archive, restore), **then** one `idea_status_events` row is written after commit by the ideation event subscriber, with `kind = "status_changed"`.
- Test: `test_status_change_writes_event` (`tests/test_ideation_status_events.py`, parametrized over the platform edges).

### AC-94-62 - no event out of Draft or without a requester [BE][T]
- **Given** draft to captured, draft to rejected (cancel) or draft to duplicate (vote), **then** no event (the live chat already replied). **Given** an operator-authored idea (no submitter contact), **then** no event.
- Test: `test_no_event_from_initial_or_without_requester`.

### AC-94-63 - payload contract [BE][T]
- **Given** an event, **then** the feed item carries exactly `event_id, seq, kind, occurred_at, idea_id, idea_number, idea_title, product_id, status_label, from_status_label, track_url, requester_phone, merged_into, separated_from, is_test` (snake_case, the intake server-to-server convention); `status_label` is the engine label; `track_url` is the recipient idea's own public link.
- Test: `test_event_payload_exact_keys`.

### AC-94-64 - merge AND unmerge notify each child's requester [BE][T]
- **Given** B (has requester) merged into A, **then** one event `kind = "merged"` for B with `merged_into = {idea_number, title}` of A and `status_label` = A's current label. **When** B is unmerged (child unmerge, survivor unmerge or survivor delete), **then** one event `kind = "unmerged"` for B with `separated_from = {idea_number, title}` of A, `merged_into = null` and `status_label` = B's own restored label (owner Q3, 28 Sep); deduped by phone within one unmerge; no event for A.
- Test: `test_merge_event_per_child`, `test_unmerge_event_per_child`.

### AC-94-65 - a survivor's stage change reaches its children's requesters [BE][T]
- **Given** A survives B and C with requesters, **when** A moves stage, **then** one event per distinct requester phone across A, B, C, each with that recipient idea's own `track_url` and `merged_into` set for B and C.
- Test: `test_survivor_change_fans_out_deduped_by_phone`.

### AC-94-66 - the feed [BE][T]
- **Given** a workspace API key for tenant T, **when** `GET /ideation/intake/status-events?after=<seq>&limit=<n>` is called, **then** it returns T's events with `seq > after` ascending, at most `n` (default 100, max 200), plus `next_after`; another tenant's key never sees T's events; a missing or bad key is 401.
- Test: `test_feed_cursor_and_tenant_scope`.

### AC-94-67 - test ideas never reach a real requester [BE][T]
- **Given** an `is_test` idea changes stage, **then** its event is written with `is_test = true` and is excluded from the feed unless `includeTest=true` is passed.
- Test: `test_feed_excludes_test_events`.

### AC-94-68 - ordering and idempotency [BE][T]
- **Given** two stage changes on one idea, **then** their `seq` values ascend in commit order and each `event_id` is unique; the feed withholds rows younger than the settle window (5 s) so a late-committing lower `seq` is never skipped by a cursor.
- Test: `test_feed_order_and_settle_window`.

### AC-94-69 - a failing subscriber never breaks the move [BE][T]
- **Given** the event write raises, **then** the status move still commits and returns 200 (event-bus contract, `entity_events.py:61-70`).
- Test: `test_event_failure_isolated`.

### AC-94-70 - tenant-scoped requester lookup [BE][T]
- **Given** an idea whose `submitter_contact_id` points at another tenant's contact (defensive), **then** no event is written; the phone is never resolved unscoped.
- Test: `test_requester_lookup_tenant_scoped`.

### AC-94-71 - uninstall clears events [BE][T]
- **Given** a tenant uninstalls ideation, **then** its `idea_status_events` rows are deleted with the rest (generic `uninstall_tenant`, `bootstrap.py:192-202`).
- Test: `test_uninstall_clears_events`.

### AC-94-72 - the CRM contract doc exists [T]
- **Given** the PR, **then** `documentation/ideation/status-events-contract.md` documents the feed, payload, cursor, settle window, `is_test` rule and the merge and unmerge semantics (`merged`, `unmerged` kinds), and matches `test_event_payload_exact_keys` field for field.
- Test: reviewer checklist item.

## G. Cross-cutting (AC-94-73..78)

### AC-94-73 - every select is the system dropdown [FE][T]
- **Given** every surface touched by this PR, **then** each select is `SearchSelect`/`MultiSelect`; `npx eslint` passes the `no-restricted-imports` rule with no new disable comment.

### AC-94-74 - responsive [E2E]
- **Given** each surface (list with badge, merge dialog, form with pager and votes, Merged from tab, child form, board, public merged page), **then** nothing clips or overflows at 375 and 1280; truncated titles use `ClampedText`.

### AC-94-75 - white-label and foolproof copy [FE][T]
- **Given** any new tenant-facing string, **then** it never names the platform brand and carries no instructional hint text (state only: "2 merged", "Merged into IDEA-0042", "Merged from").

### AC-94-76 - no dashes [T]
- **Given** the diff, **then** no em dash or en dash is present (CI grep).

### AC-94-77 - layering [T]
- **Given** the diff, **then** no router contains a query, no component calls `apiFetch`, no `any` is introduced (reviewer hard-fail list).

### AC-94-78 - suites green [T]
- **Given** the PR head, **then** `python -m pytest -q` (absolute venv python) and `npm test`, `npm run lint`, `rm -rf .next && npm run build` all pass.
