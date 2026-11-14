# Plan - issue #94: Ideation round 2 - merge and unmerge, form fixes, priority rank, engine statuses, requester status updates

**UAC (the contract):** `ideation-round-2-merge-unmerge-acceptance-criteria.md` (AC-94-01..78)
**Issue:** [#94](https://github.com/jayson-odoo/foundryx-shared-service/issues/94) - owner hand test 28 Sep 2026 through the sorento CRM embed; owner rulings in the issue comment of 28 Sep bind.
**Delivery:** ONE PR against `main` (owner rule), built on top of this plan branch (`plan/ideation-round-2-merge-unmerge`) so plan + UAC + code merge together.
**Cross-repo dependency:** this repo ships the requester status-update EVENT FEED; the CRM (sorento) PR ships the WhatsApp SEND (section 7, Appendix A). Neither side is blocked by the other at build time; the owner sees messages only when both are deployed.

This document is structured to be rendered as a self-contained alignment page: section 1 (summary + decisions), section 2 (what the owner will see), section 15 (open questions) are written to stand alone.

---

## 0. Owner rulings (28 Sep 2026, verbatim in the issue comment)

1. Merge and unmerge: CONFIRMED.
2. Status labels, colours and transitions read from the statuses engine: CONFIRMED.
3. Priority fix (1-based rank, real rank on capture): CONFIRMED.
4. Stage-change notification to the requester: YES, on EVERY stage change, as a new WhatsApp template use case "ideation status update".
5. Open questions answered on the alignment page (28 Sep): Q1 CRM pulls the feed and sends; Q2 yes, merged ideas' requesters get the kept idea's updates; **Q3 every stage change except out of Draft, plus a message on merge AND on unmerge**; Q4 new captures land at the bottom; **Q5 no status on the form at all (neither edit nor read mode)**; Q6 flatten.

Standing owner rules: every select is the system dropdown (`SearchSelect`, `components/platform/search-select/search-select.tsx`, design-language primitives roster `docs/reference/design-language.md:134`); one PR; alignment page; no em or en dashes.

## 0.1 Issue facts checked against the code (corrections in bold)

| Issue claim | Verdict |
|---|---|
| `duplicate` is only a status (`services/statuses.py:80`) | **Partly off: the `duplicate` status row is `statuses.py:48` (terminal + archived); line 80 is the `draft -> duplicate` "Vote with existing" EDGE. The other edge into it is `captured -> duplicate` (`:61`).** No grouping column exists (`models.py:121-201`) - confirmed. |
| Clusters are suggestions only | Confirmed (`routers/ideas.py:122-135`, `services/clustering.py:15-19`, nothing stored). |
| Labels hard-coded in the FE; API sends only the key (`ideas.py:69`) | Confirmed, **and the backend hard-codes too: `BOARD_COLUMNS` (`services/ideas.py:28-34`) and `_ARCHIVED_KEYS` (`:23`, used by the list filter `:192-204`, whose status query is not even tier scoped).** The FE board does not call `/board`; it groups client side with `IDEA_BOARD_COLUMNS` (`board/triage-board.tsx:21,31-41`) and drops by KEY (`:116`). Toasts print the raw key (`ideas-view.tsx:70`, `use-idea-form.tsx:143`). |
| Priority #0: `actions.py:205` 0-based, `models.py:189` default 0, form renders raw (`idea-form-fields.tsx:230`), server orders by `created_at` (`ideas.py:206`), client sorts | Confirmed, **plus two more causes: (a) no capture path ever sets priority (`actions.py:89-103`, `intake.py:541-552`, `sinks.py:73-80`), so every new idea is 0; (b) the list drag sends only the CURRENT PAGE's ids (`components/platform/resource-list/resource-list.tsx:256`), so a page-2 drag rewrites those rows to 0..9 and collides with page 1; the embed reorder (`routers/embed.py:223-242`) and the board (`triage-board.tsx:118`) send subsets too.** |
| Nothing notifies on a stage change; seed has no notification specs | Confirmed (`statuses.py:57-81`, `status_machine.py:199-206` dispatches only specs). |
| `RecordNav` exists (`record-nav.tsx:17`), enabled by `config.recordNav` (`resource-form.tsx:393`), BR uses it (`use-br-form.tsx:304`) | Confirmed. The pager label format is "n / N" (`hooks/use-record-nav.ts:24`), not "n of N" - reused as is. |
| Form votes read-only (`idea-form-fields.tsx:212-224`); list `VoteCell` (`use-ideas-list-config.tsx:31`) | Confirmed. `VoteCell` is a file-local function today. |
| (not in issue) | **The Archived list view is always empty: `listIdeas` never passes `filter` (`services/ideation-service.real.ts:73-76`) so the server returns active only (`routers/ideas.py:39`), then the FE keeps `status === 'archived'` (`use-ideas-list-config.tsx:252-255`).** Fixed in this round (AC-94-60, red test first). |
| (not in issue) | **The Status dropdown is a bare `@/components/ui/select` (`idea-form-fields.tsx:21-27,178-191`), itself a violation of the system-dropdown rule.** Removed. |
| (not in issue) | **"Comments" do not exist in the ideation model** (`models.py`), so nothing to carry on merge. |
| (not in issue) | **Every operator write route has an embed twin (`routers/embed.py:223-355`); the owner tests through the embed, so merge/unmerge must ship on both.** |

Reference docs: `docs/reference/status-engine.md` and `docs/reference/frontend-design-language.md` are NOT present in this worktree (they are untracked in the main checkout only); this plan read them there. `docs/reference/design-language.md` is present.

---

## 1. Summary and decisions (alignment page: "What we are building")

Five things, one PR:

1. **Merge / unmerge** similar ideas into one surviving idea; the merged ones stay openable and can be split back out.
2. **Form fixes**: no Status dropdown, clickable votes, prev/next pager.
3. **Priority** shows a real 1-based rank; new captures land at the end; page-2 drags stop corrupting ranks.
4. **Statuses come from the statuses engine**: rename "Triaged" to "Discussed" and every screen follows.
5. **Requester status updates**: every stage change produces an event the CRM turns into a WhatsApp template message (CRM sends; this repo publishes the feed).

| Id | Decision | Why (one line) |
|---|---|---|
| D1 | `ideas.merged_into_id` = plain indexed VARCHAR (NO foreign key) + `merged_at` | A FK on the hot `ideas` table takes a lock that hung blue/green before (`models.py:449-460`, BL-030 rule). Integrity lives in the service. |
| D2 | Single level. Merging a survivor re-points its children to the new survivor (flatten) | No chains to walk; every read is one hop. Cost: unmerging the old survivor later does not bring its old children with it (Q6). |
| D3 | "Merged" is a separate flag, NOT the `duplicate` status; a merged child's status is frozen | `duplicate` is terminal (`statuses.py:48`) so unmerge could never move back through the engine; only `captured` has an edge into it (`:61`); and `draft -> duplicate` is already the WhatsApp "vote with existing" path (`intake.py:627-655`). |
| D4 | Votes MOVE to the survivor, stamped `idea_votes.origin_idea_id`; a voter who already voted on the survivor keeps the child row in place (shadowed); unmerge moves stamped rows back | Tallies, `myVote` and the vote toggle stay the existing per-idea code (`actions.py:158-190`), unchanged; unmerge is lossless. |
| D5 | Attachments and BR links stay on the child; the survivor shows children in a "Merged from" tab | Nothing is copied, so unmerge is a pointer clear. |
| D6 | Merge refuses mixed product, mixed test/real, archived, already-merged, fewer than 2 | Same lane rules as BR promote (`use-ideas-list-config.tsx:117-120`, `business_requirements.py:510-560`). |
| D7 | Permission: reuse `ideation.triage.manage`; no new CSV row | Every other triage write uses it (`routers/ideas.py:113,172,209,226`); no grant sweep needed. |
| D8 | Survivor picked in a dialog with `SearchSelect`, no default pick | Owner rule (system dropdown); foolproof: never auto-derive the survivor. |
| D9 | Public track page of a merged child: its own content + "Merged into IDEA-xxxx" + the SURVIVOR's status, timeline, votes | The WhatsApp "Track it here" link keeps working and keeps tracking progress. |
| D10 | The survivor always has an idea number (merge calls `mint_idea_identity`, `numbering.py:52`) | Operator-made ideas have none today (BL-SS-280). |
| D11 | Rank is computed server side (1-based, per the caller's scope); `priority` stays the stored sort key; reorder is slot preserving; captures append at the end; migration backfills dense values | Fixes all three #0 causes with no API shape change to `/reorder`. |
| D12 | `IdeaOut` carries `statusId/statusLabel/statusColor/statusIsArchived`, per-record `transitions` and `advanceTransitionId`; board columns derive from trait flags | Tenant console pattern (`status-engine.md`: server label/colour + per-record fireable edges); never branch on `category`. |
| D13 | Requester updates: an ideation event-bus subscriber writes `idea_status_events`; the CRM PULLS a workspace-key feed and sends the template | Catches every transition from all 7 call sites; no WhatsApp credentials, SSRF surface, retries or second log on this side. |

---

## 2. What the owner will see (alignment page: step-by-step flows)

**Flow 1 - Merge two ideas (list).** Ideation > Ideas. Tick idea 1 and idea 2. Actions > **Merge**. A small dialog shows one dropdown listing just those two ideas ("IDEA-0012 · Faster quotation", ...). Pick the one to keep, click **Merge**. The list now shows one row; its Idea cell carries a "1 merged" badge. Votes of both now count on the kept idea.

**Flow 2 - See what was merged (form).** Open the kept idea. A **Merged from** tab appears next to Details / Attachments / Business Requirements. It lists the merged idea(s); click one to open it. That form shows a **Merged into IDEA-0012** row (a link back), read-only votes, and its gear offers only **Unmerge** and **Delete**.

**Flow 3 - Regret it (unmerge).** Either: in the merged idea's form, gear > **Unmerge**; or in the kept idea's Merged from tab, tick rows > **Unmerge**; or in the list, tick the kept idea > Actions > **Unmerge** (splits the whole group). The idea returns to the list at its old position with its old status and its own votes.

**Flow 4 - The form.** The form has no Status row at all, in edit or read mode (owner Q5); status is visible on the list and board, and changes only through actions. The Votes row has the same up/down buttons as the list. Top right shows **‹ 3 / 12 ›** when opened from the list; prev/next walks the list in the same order and filter.

**Flow 5 - Priority.** Drag an idea to the top of the list, open it: **Priority #1**. Capture a new idea: it shows the last rank (for example **#13**). Dragging on page 2 no longer disturbs page 1.

**Flow 6 - Rename a stage.** In the statuses engine rename the Idea stage "Triaged" to "Discussed". The Ideas list Status column, the "Move to Discussed" action, the board column and the public track page all say "Discussed". Nothing is hard-coded any more.

**Flow 7 - The requester (after the CRM side ships).** Each time an idea moves stage, the requester gets a WhatsApp template message: "Update on your idea IDEA-0012: it is now Discussed. Track it here: <link>". If their idea was merged, they get "... has been combined with IDEA-0012 ..." once, then the kept idea's stage updates from then on; if it is later unmerged, they get "... is being handled separately again, it is now <stage> ..." once, then their own idea's updates. Their original track link shows "Merged into IDEA-0012" and follows the kept idea's progress. Test ideas never message anyone.

---

## 3. Merge and unmerge

### 3.1 Data model (module `app_ideation`, migration 0012 in section 9)

- `ideas.merged_into_id VARCHAR NULL`, indexed, NO FK (D1). `ideas.merged_at UTCDateTime NULL`.
- `idea_votes.origin_idea_id VARCHAR NULL` (NULL = the vote was cast on this idea).
- Invariant (service enforced, tested AC-94-05): a row with `merged_into_id` set is never itself a `merged_into_id` target.
- Tenant scoping: every read/write filters `Idea.tenant_id == <JWT or embed-token tenant>`; the survivor pointer is resolved tenant scoped everywhere, including the public page (by the child's own `tenant_id`, the polymorphic stored-id rule).

### 3.2 Service - new `modules/ideation/services/merge.py` (`IdeaMergeService`)

`merge(tenant_id, survivor_id, idea_ids, actor)`:
1. Load all ids tenant scoped (404 if any missing). Validate D6 (422, no writes).
2. `mint_idea_identity(survivor)` (D10).
3. Flatten: for each non-survivor member that is itself a survivor, re-point its children to `survivor_id` and move their stamped vote rows (keep `origin_idea_id`).
4. For each member: set `merged_into_id`, `merged_at`; move its vote rows to the survivor with `origin_idea_id = member` unless the survivor already has that voter (then leave it, shadowed).
5. Recount the survivor and every member (reuse `IdeaActionService._recount`, `actions.py:158-163`).
6. Write a `merged` event per member with a requester (section 7). Commit once.

`unmerge(tenant_id, idea_id)`: child -> restore that child; survivor -> restore all its children; else 422. Restore = clear pointer + `merged_at`, move rows `idea_id = survivor AND origin_idea_id = child` back (clear origin), recount both. Write one `kind = "unmerged"` event per restored child with a requester (owner Q3), in the same transaction; deleting a survivor (which unmerges first) writes them too.

Guards added elsewhere (all read `merged_into_id`):
- `IdeaActionService.set_status` and `vote` -> 409 on a child ("merged into IDEA-xxxx").
- `IdeaActionService.delete` -> on a survivor, `unmerge(survivor)` first (AC-94-10).
- `IdeaActionService.reorder` -> skips children (AC-94-19).
- `BusinessRequirementService._link_ideas` (`business_requirements.py:510`) -> 422 for a child.
- `DedupService` (`dedup.py:80-85` and the candidate query) -> exclude children; intake `_register_submitter_upvote` (`intake.py:418-460`) resolves a child candidate to its survivor first and then uses the shared recount.
- `ClusteringService._candidate_pairs_pg` / `_fallback` (`clustering.py:138-193`) -> `merged_into_id IS NULL` on both sides.
- `IdeaReadService.list` / `board` (`ideas.py:162-252`) -> survivors only; `mergedCount` via ONE grouped count over the page's ids; `mergedInto` via one batched lookup.

### 3.3 API (router = HTTP only)

| Route | Gate | Body / result |
|---|---|---|
| `POST /ideation/ideas/merge` | `ideation.triage.manage` | `{survivorId, ideaIds}` -> survivor `IdeaOut` |
| `POST /ideation/ideas/{id}/unmerge` | `ideation.triage.manage` | -> `IdeaOut[]` restored |
| `GET /ideation/ideas/{id}/merged` | `ideation.ideas.view` | -> children `IdeaOut[]` |
| `POST /embed/ideas/merge`, `POST /embed/ideas/{id}/unmerge`, `GET /embed/ideas/{id}/merged` | embed token; every id through `_assert_in_scope` (`embed.py:168-179`) | same |

Static paths (`/merge`) are declared before `/{idea_id}` (the existing ordering rule, `routers/ideas.py:85`).

`IdeaOut` additions: `mergedIntoId: str|None`, `mergedInto: {id, ideaNumber, title}|None`, `mergedCount: int`.

### 3.4 Public track page (`services/public_status.py`)

`resolve()` (`:87-136`): when the idea has `merged_into_id`, load the survivor scoped by `idea.tenant_id`; `status`, `statusColor`, `nextStep`, `timeline`, `upvotes` come from the survivor; content fields stay the child's; add `mergedInto: {ideaNumber, title} | None` (never the survivor's submitter). `PUBLIC_NEXT_STEP` (`:55-65`) is unchanged (its `duplicate` line already says "merged into it"). The pinned key-set test grows by exactly `mergedInto` (AC-94-14). If the survivor vanished (cannot happen: delete unmerges first) fall back to the child's own status.

### 3.5 Frontend

- `MergeIdeasDialog` (new, `app/(protected)/ideation/ideas/merge-ideas-dialog.tsx`): `Dialog` + `SearchSelect` over the selected rows only; Merge disabled until picked. Opened by the Merge action's `run` through a new `onMerge(rows)` handler in `ideas-view.tsx` (same pattern as the capture dialog, `ideas-view.tsx:144-150`). Not a confirm dialog (non-destructive, reversible), so the confirm carve-out rule does not apply.
- List actions (`use-ideas-list-config.tsx`): **Merge** (bulk only; visible 2+ rows, none archived; disabled on mixed product or mixed test; `permission: 'ideation.triage.manage'` only when `mode === 'operator'`, because the embed has no session and `useCan` would hide it - the embed token is the boundary there, same as today's Advance/Archive); **Unmerge** (row + bulk; visible when every row has `mergedCount > 0`).
- Badge: in the Idea cell next to TEST (`:210-214`), `Badge` "{n} merged".
- Form (`use-idea-form.tsx`): a "Merged from" tab (hidden at 0) rendering `IdeaMergedTab`, a clone of `IdeaBrsTab` (`components/idea-brs-tab.tsx`) on `ResourceList`, rows open the child, row/bulk action Unmerge. On a child: Details gets a "Merged into" `FormRow` with a `Link` to the survivor; the gear shows only Unmerge + Delete; `VoteCell` disabled.
- Service trio: `IdeaService` gains `merge`, `unmerge`, `listMerged` in `ideation-service.ts`, `.real.ts`, `ideation-embed-service.ts`, and a NEW `ideation-service.mock.ts` (the comment at `ideation-service.ts:56` names a mock that does not exist).

---

## 4. Form view fixes

1. **Status dropdown removed** (`idea-form-fields.tsx:171-198`, `EDITABLE_STATUSES :41-49`, bare Select import `:21-27`); `status` leaves `idea-schema.ts` and `toFormValues`/`onSave` (`use-idea-form.tsx:24,33,204`); `updateIdea` drops its status branch (`ideation-service.real.ts:102-123`). Owner Q5: no status row on the form in ANY mode (read mode loses its status row too); status is shown on the list and board only.
2. **Clickable votes**: move `VoteCell` from `use-ideas-list-config.tsx:31-68` to `app/(protected)/ideation/ideas/components/vote-cell.tsx`, add ONE prop `disabled?: boolean`; the list and the form import it (no parallel component). The form's vote handler calls `ideationService.vote` and `setIdea(updated)`.
3. **Pager**: `recordNav: { fetchAt, buildHref }` wired exactly like `use-br-form.tsx:182-201,304`. `fetchAt` calls `listIdeas({ includeTest, filter: 'all' })` and runs the SAME pure helper the list fetcher uses (`selectIdeaRows(ideas, query)`, extracted from `use-ideas-list-config.tsx:251-268`), so order and filter can never drift. `IdeaPaths.formHref` (`hooks/use-ideation-runtime.tsx:21-28`) gains `{ctx, index, includeTest}` for both runtimes (operator: extend `ideaFormHref` in `components/paths.ts` like `brFormHref`; embed: plain query on `/embed/ideas/{id}`, token stays out of the URL per `embed-app.tsx` comment).

---

## 5. Priority rank

**Root cause (cited in 0.1):** 0-based write (`actions.py:205`), default 0 with no capture path assigning one (`models.py:189`, `actions.py:89-103`, `sinks.py:73-80`), page-subset reorders (`resource-list.tsx:256`, `embed.py:223-242`, `triage-board.tsx:118`), raw render (`idea-form-fields.tsx:230`). The list only looked right because the client sort ties fall back to the server's `created_at desc` order.

**Source of truth: the server.**
- Stored `priority` = sort key, lower first. Lane = `(tenant_id, is_test)`, survivors only.
- `rank` (new `IdeaOut` field, 1-based) = position among the caller-scope's ACTIVE survivors (tenant, plus product when the caller is product scoped: embed token or `?productId=`, plus the test lane) ordered `priority asc, created_at desc, id desc`. Computed on the full scope BEFORE search so it is the true position; `null` for archived and merged. Detail computes it with one COUNT under the same scope (AC-94-43).
- New capture: `priority = max(lane) + 1` at the FIRST move into captured - in `create_operator` (`actions.py:106-109`) and in the sink's transition branch (`sinks.py:74-78`). Drafts never consume a rank. (Q4: top instead of bottom?)
- `reorder` (`actions.py:192-213`) becomes slot preserving: renumber the lane densely first (heals legacy ties), take the given ids' current slots sorted ascending, reassign in the given order. `/reorder` request shape unchanged, so list page drags, the board and the embed all become correct without FE changes to the call.
- The list API orders by the rank order (replacing `ideas.py:206`); the FE fetcher drops its `.sort` (`use-ideas-list-config.tsx:255`); the form renders `#{rank}` or `-`.

---

## 6. Status labels, colours and transitions from the statuses engine

**Backend (`services/ideas.py` serializer):**
- `IdeaOut` adds `statusId`, `statusLabel`, `statusColor`, `statusIsArchived` from the status row already batch-loaded in `_resolve_maps` (`ideas.py:143-160`).
- `transitions: [{id, label, toStatusId, toStatusLabel}]` per record: load the tier's edges ONCE (`StatusTransitionRepository.list_for_entity(IDEA_ENTITY, tier)`), then keep the ids returned by `status_machine.fireable_edge_ids(db, IDEA_ENTITY, ideas, actor, tenant_id=..., always=True)`.
- **Core extension (a prop, not a fork):** add keyword `always: bool = False` to `fireable_edge_ids` (`app/services/status_machine.py:324`); when True it skips the "no conditioned edge -> None" short-circuit (`:363-371`) and returns the per-record dict through `_filter_fireable` (`:291-321`: auto edges, roles, inactive targets, conditions). Existing callers (`tenant_service.py:350`, `form_service.py:968`) are untouched. One core test added to `tests/test_status_engine.py`.
- `advanceTransitionId`: among the record's `transitions`, the edge whose target has the smallest `sort_order` strictly greater than the current status's (ties by edge `sort_order`). Pure trait-free rule driven by the tenant-editable order; never `category`, never a key.
- `StatusIn` (`schemas.py:111-115`) accepts exactly one of `status` (key; kept for the deferred Archive handler `deferred_actions.py:33-36`) or `toStatusId` (validated to the idea entity and the tenant tier, 422 otherwise); both call `status_machine.transition`.
- Board (`ideas.py:209-252`): columns = tier statuses with `is_initial` false, `is_archived` false, `is_active` true, by `sort_order` (the same "main path" rule as the public timeline, `public_status.py:227`); `BoardColumnOut` gains `statusId`, `color`, `title` = label. Delete `BOARD_COLUMNS` and `_ARCHIVED_KEYS`; the list filter uses the tier's `is_archived` ids.

**Frontend:**
- Delete `IdeaStatus`, `IDEA_NEXT_STATUS`, `IDEA_BOARD_COLUMNS`, `IDEA_STATUS_LABEL` (`types/ideation.ts:24-48,127-153`); `Idea.status` becomes `string`, plus the new fields. An inventory test pins their absence (AC-94-55).
- List Status column renders `StatusBadge` from `statusLabel`/`statusColor` (the form shows no status, owner Q5); CSV exports the label.
- **Advance to next stage** (row, form, bulk): label "Move to {toStatusLabel}" when every row's advance target label matches, else "Advance to next stage"; disabled if any row lacks `advanceTransitionId`; each row fires its own edge via `setStatus(id, toStatusId)` (signature changes from key to target id); toast names the label.
- Archive stays the deferred action (server key path). Visibility uses `statusIsArchived`. **Restore** is visible when `statusIsArchived` and the row has a transition; it fires that edge (label from the engine).
- Board: switch `triage-board.tsx` to `GET /board` (operator) / `GET /embed/board` (both already exist, `routers/ideas.py:88`, `embed.py:203`); a drop target is valid only if the card's `transitions` reach that column's `statusId`; fire by id; then `/reorder`.
- `useIdeas` loads `filter=all` so the Archived view is fed; the shared `selectIdeaRows` splits by `statusIsArchived`.

---

## 7. Requester status updates (owner: every stage change; Q1 = who sends)

### 7.1 Recommendation (default for Q1): this repo publishes, the CRM sends

**Capture - the CRUD event bus.** Every idea move already emits `entity.status_changed` through `emit_entity_event` inside `status_machine.transition` (`status_machine.py:219-239`), drained after commit on a fresh session, each subscriber isolated in its own commit and never able to break the request (`workflow_engine/entity_events.py:36-70, 202-229`). Ideation registers ONE subscriber (`register_event_subscriber`, `entity_events.py:50`) from `bootstrap.register_engine_entities` (`bootstrap.py:36`), new file `services/status_events.py`. This catches all 7 transition call sites (`actions.py:107,230`, `sinks.py:75`, `intake.py:366,606,640`, `business_requirements.py:680`) and any future one, with no per-call-site code.

**Delivery - the CRM pulls.** `GET /ideation/intake/status-events?after=<seq>&limit=<n>&includeTest=<bool>` on the existing workspace-key router (`routers/intake_reads.py`, auth `get_api_workspace`, `modules/omnichannel/api_auth.py:42` - the same key the CRM already uses for `create-idea`). Tenant comes from the key.

Why pull over push: no callback URL or signing secret to store, no SSRF surface, no retry/backoff/dead-letter machinery, no second integration log on this side; the CRM owns cadence, templates, opt-outs and its integration log in one place (the ideation_draft_reminder precedent, sorento #1201). Why not "poll each idea's status through the embed session API": embed tokens are short-lived per host user (`routers/embed.py:83-131`), polling per idea misses intermediate stages and scales with idea count.

**Subscriber rules (`on_domain_event(session, ev)`):**
- Only `ev.entity_type == "idea"` and `ev.action == "status_changed"`.
- Skip when the FROM status `is_initial` (draft to captured / rejected / duplicate: the live chat already replied, `sinks.py`, `intake.py:598-655`).
- Recipients = the moved idea plus, if it is a survivor, each merged child; each must have `submitter_contact_id` resolved TENANT SCOPED to a Contact with a phone, and a `status_token`; dedupe by phone (the survivor's own row wins).
- One row per recipient: `kind = "status_changed"`, `status_label` = the moved idea's new label (`ev.extra.to_status_label`), `from_status_label`, `track_url = mint_idea_link(recipient)` (`sinks.py:44-59`), `merged_into` set for children, `is_test` copied from the recipient.
- Merge writes `kind = "merged"` rows for members with a requester inside the merge transaction (section 3.2); unmerge writes `kind = "unmerged"` rows for each restored child with a requester (owner Q3), `status_label` = the child's own restored label, `separated_from` = the former kept idea, `merged_into = null`, deduped by phone within the one unmerge.

**Table `idea_status_events`:** `seq` INTEGER autoincrement PK (Postgres SERIAL), `id` uuid unique (the `event_id`), `tenant_id`, `idea_id` (recipient), `kind`, `is_test`, `payload_json`, `created_at`. Generic `uninstall_tenant` clears it (`bootstrap.py:192-202`).

**Payload (snake_case, the server-to-server convention of `schemas.py:1-8`):**
```
{ "event_id": "uuid", "seq": 812, "kind": "status_changed" | "merged" | "unmerged",
  "occurred_at": "2026-09-28T09:10:00Z",
  "idea_id": "...", "idea_number": "IDEA-0031", "idea_title": "Faster quotation",
  "product_id": "...", "status_label": "Discussed", "from_status_label": "New",
  "track_url": "https://<frontend>/public/ideas/<token>",
  "requester_phone": "+60123456789",
  "merged_into": null | { "idea_number": "IDEA-0012", "title": "..." },
  "separated_from": null | { "idea_number": "IDEA-0012", "title": "..." },
  "is_test": false }
```
Feed response: `{ "events": [...], "next_after": <last seq or the given after> }`.

**Ordering and idempotency:** at-least-once. `seq` ascends in insert order; the feed withholds rows younger than a 5 s settle window so a lower `seq` that commits late is not skipped past by the cursor. The CRM keeps its cursor, dedupes on `event_id`, and processes ascending. Per idea, events follow commit order.

**Test ideas:** written with `is_test = true`, excluded from the feed unless `includeTest=true`; the CRM contract says never send to a requester when `is_test` (double guard, so the console test lane can still verify the event).

**Deliverable doc:** `documentation/ideation/status-events-contract.md` (AC-94-72) - the Appendix A brief in contract form.

### 7.2 Alternative (not recommended): this repo calls the CRM's notify route

Reusing the omnichannel consumer-webhook outbox (`modules/omnichannel/services/webhook_delivery.py`: HMAC `sign_body :61`, SSRF `assert_deliverable` per attempt `:180`, backoff `:30`, auto-disable, activity log) would push the same payload. Costs: (a) credentials/route coupling - a CRM URL + signing secret stored here, and the CRM route's auth contract; (b) retries - the outbox is CHANNEL bound (`_active_endpoints :72-83`, `EVENT_TYPES` `webhook_service.py:39`) and ideas have no channel, so it needs an ideation-owned endpoint registry + beat re-driver; (c) a second integration log split across two systems; (d) opt-out source of truth - this side cannot see the CRM's opt-outs, so it either sends blind or needs a sync. A third option, sending WhatsApp from here through omnichannel, is out: this service holds no WhatsApp credentials for the CRM's Respond.io number.

### 7.3 24h window, templates, opt-out (CRM side, summarised; detail in Appendix A)

A stage change is business-initiated and usually outside the 24h customer-service window, so it must be an approved template (Utility category). Opt-outs are checked by the CRM before each send.

---

## 8. Frontend layering and reuse map

UI -> hook -> service -> `lib/api-client`, no component calls `apiFetch`.

| Need | Reuse | Change |
|---|---|---|
| List, bulk menu | `ResourceList` + `ActionMenu` (`use-ideas-list-config.tsx`) | Merge / Unmerge actions, badge, server order, shared `selectIdeaRows` |
| Survivor picker | `Dialog` + `SearchSelect` | new `merge-ideas-dialog.tsx` |
| Merged from tab | clone `IdeaBrsTab` on `ResourceList` | new `idea-merged-tab.tsx` + hook `use-idea-merged.ts` |
| Votes | `VoteCell` | extracted to `components/vote-cell.tsx`, prop `disabled` |
| Pager | `RecordNav` via `config.recordNav` | wiring only |
| Status pill (list only) | `StatusBadge` + `colorToHex` | no change to the primitive |
| Board | `/board` + `/embed/board` | FE switches source; columns from API |
| Truncation | `ClampedText` | titles in dialog options and tab rows |
| Toasts | `lib/toast` | label-based copy |

Hooks: `useIdeas` gains `merge`, `unmerge`; new `useIdeaMerged(id)`. No new permission keys on the FE; operator gating via `useCan('ideation.triage.manage')`.

---

## 9. Migration `0012_ideation_merge_rank_events` (31 chars; head today is `0011_ideation_br_is_test`)

Postgres only, idempotent, `down_revision = "0011_ideation_br_is_test"`, same style as `0011` (`ALTER ... ADD COLUMN IF NOT EXISTS`):
1. `ideas.merged_into_id VARCHAR NULL`, `ideas.merged_at TIMESTAMPTZ NULL`, `CREATE INDEX IF NOT EXISTS ix_ideas_merged_into_id`.
2. `idea_votes.origin_idea_id VARCHAR NULL`.
3. `CREATE TABLE IF NOT EXISTS idea_status_events (...)` + index `(tenant_id, seq)`.
4. Backfill (DoD 2): `UPDATE ideas SET priority = rn FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY tenant_id, is_test ORDER BY priority ASC, created_at DESC, id DESC) rn ...)` - preserves today's visible order (priority ties, newest first).
Models get the same columns/table so `create_all` (tests, fresh boot `bootstrap.py:118`) matches. After merge to main: `alembic upgrade head` on the live DB via `bootstrap_db` before live testing (DoD 5).

## 10. RBAC

No new permission (D7). `merge`/`unmerge` = `ideation.triage.manage`; `GET /{id}/merged` = `ideation.ideas.view`; the feed = workspace key (no RBAC, tenant from key). Embed routes = embed token scope. No grant sweep needed (DoD 4).

---

## 11. Slices (all in the ONE PR)

Order follows `PRINCIPLES.md` (frontend mock before backend impl, tests before impl). Every brief embeds the PRINCIPLES design mandates, DoD gate and hard-fail list.

| # | Owner | Scope | Exit |
|---|---|---|---|
| S0 | tester | Write ALL red tests: backend files in 12.1, Vitest files in 12.2, the core `fireable_edge_ids(always=True)` test | Every listed test exists and fails for the right reason |
| S1 | coder (FE) | Types, `ideation-service.mock.ts`, service/embed interface, hooks, `vote-cell.tsx`, form fixes (4), list (merge dialog, unmerge, badge, server order, archived view), Merged from tab, child form, board from API, constants deleted. Bound to the mock (one line `ideation-service.ts:57`) | Vitest green; all states tuned on the mock at 375/1280 |
| S2 | coder (BE) | Migration 0012 + models; status display fields, transitions, advance, `always=` core prop, board/list from flags, `toStatusId`; rank + capture append + slot-preserving reorder | S0 backend tests for sections D, E green |
| S3 | coder (BE) | Merge service + routes (operator + embed) + all guards (3.2) + public page | Section A tests green |
| S4 | coder (BE) | `idea_status_events`, subscriber, feed, merge events, contract doc | Section F tests green |
| S5 | coder (FE) | Swap mock -> real (one line), embed service real calls, live smoke | Real data on screen |
| S6 | tester | agent-browser evidence (12.3) at 375 + 1280, fresh `rm -rf .next && npm run build`, dedicated tenant for the rename journey, Test Execution Report keyed to AC-94 ids | Report + `94-evidence/` README |
| S7 | reviewer (Opus) | Diff vs UAC + hard-fail list; security focus: tenant scope on merge ids, public page survivor lookup, feed tenant scope, requester phone lookup | Approve or findings loop to the owning coder |

Sequential coders on the shared branch (S2/S3/S4 touch the same services). S1 may run in parallel with S2 (no file overlap).

## 12. Tests

### 12.1 Backend (pytest; absolute venv python)
- `tests/test_ideation_merge.py` - AC-94-01..15, 17, 19, 20.
- `tests/test_ideation_embed_writes.py` (extend) - AC-94-16.
- `tests/test_ideation_public_status.py` (extend) - AC-94-13, 14.
- `tests/test_ideation_priority_rank.py` - AC-94-41..45.
- `tests/test_ideation_status_display.py` - AC-94-49..54, 60 (BE half).
- `tests/test_ideation_status_events.py` - AC-94-61..71.
- `tests/test_status_engine.py` (extend) - `fireable_edge_ids(always=True)`.
- Migration: revision id length + head chain (AC-94-18).
- Regression: existing `test_ideation_triage.py`, `test_ideation_ideas_actions.py`, `test_ideation_embed*.py`, `test_ideation_dedup.py`, `test_ideation_clustering.py`, `test_ideation_create_idea.py` stay green (they assert keys like `status == "captured"`; `status` is kept).

### 12.2 Frontend (Vitest)
`use-ideas-list-config.test.tsx` (merge/unmerge visibility, badge, server order, archived view, advance, status from API), `merge-ideas-dialog.test.tsx`, `idea-merged-tab.test.tsx`, `vote-cell.test.tsx`, `idea-form-fields.test.tsx`, `use-idea-form.test.tsx` (merged child, vote, recordNav), `board/page.test.tsx`, `embed-ideas.test.tsx` (pager, merge), `ideation-service.real.test.ts`, `ideation-constants.inventory.test.ts`.

### 12.3 agent-browser journeys (real clicks from the sidebar, `--session` per lane, 375 AND 1280)
AC-94-27 merge · 28 open child · 29 unmerge from child · 30 unmerge from list · 31 track link of a merged child · 32 embed parity · 37 form votes · 38 pager · 39 no status control · 48 drag then open · 59 rename in the statuses engine (dedicated tenant) · 74 responsive sweep. Timestamp every created name. Evidence `documentation/plans/ideation/94-evidence/<slice>/` + README run log.

## 13. Risks

| Risk | Mitigation |
|---|---|
| The rename journey forks the tenant's status set (D7 two-tier) and remaps ids | Code resolves by key within tier (`statuses.py:139-152`) and the FE now uses `statusId` from the API; run on a dedicated tenant. |
| After-commit subscriber: a process crash between commit and drain loses that one event | Accepted event-bus contract; the requester still has the live track page. Revisit only if observed. |
| `rank` differs between the operator list (tenant wide) and a product-scoped embed | By design ("position in the list you see"); Q-free because each surface is self-consistent. |
| Flatten loses the old grouping when an absorbed survivor is later unmerged | Documented; Q6. |
| Deleting an idea with attachments may already fail on Postgres (real FK `idea_attachments.idea_id`, `models.py:256`, and `delete` does not remove attachments, `actions.py:240-247`); BR link rows are left orphaned | Out of scope; verify and file (BL-SS-285). Survivor delete path in this PR unmerges first, which does not touch attachments. |
| Adding keys to the public page | Deliberate update of the pinned key-set test (AC-94-14); PII test kept. |
| `IdeaOut` grows (transitions per row) | One edge query per request + in-memory filtering; facts only for conditioned edges. |
| The CRM side not ready | Events accumulate harmlessly; feed starts at the table's first row (no historical replay). |

## 14. Backlog rows (added to `documentation/backlogs/backlog.md`)

- BL-SS-281 Merge action on a cluster suggestion card (merge the suggested group in one click).
- BL-SS-282 Prune `idea_status_events` older than 30 days (retention job).
- BL-SS-283 Full graph-driven lifecycle actions on the idea form (Reject, Mark duplicate as their own actions, like `use-br-actions.tsx`).
- BL-SS-284 Merge audit (who merged, when) shown on the Merged from tab and an activity trail.
- BL-SS-285 Verify and fix idea hard-delete with attachments / BR links (FK and orphan rows).

## 15. Owner answers (alignment page, 28 Sep 2026; all questions closed)

1. **Q1 - Who sends the "ideation status update" WhatsApp?** ANSWERED: **the CRM sends**, through a new template use case, pulling this service's status-event feed (section 7.1); this service holds no WhatsApp credentials, and templates, opt-outs and the integration log stay in the CRM. Alternative: this service calls a CRM notify route (costs in 7.2).
2. **Q2 - When a kept idea moves stage, do the requesters of the ideas merged into it get the update too?** ANSWERED: **yes**, one message per distinct phone, each with their own track link.
3. **Q3 - Which moves message the requester?** ANSWERED (changed from the default): **every stage change except those out of Draft** (capture, cancel and "vote with existing" are already answered in the chat), **plus one "combined with IDEA-xxxx" message on merge AND one "handled separately again" message on unmerge**.
4. **Q4 - Where does a new capture land in the priority order?** ANSWERED: **at the bottom** (last rank); a triager drags it up.
5. **Q5 - Keep a read-only status pill on the form?** ANSWERED (changed from the default): **no status on the form at all**, in edit or read mode; status lives on the list and board.
6. **Q6 - Merging an idea that already has merged ideas into another one:** ANSWERED: **flatten** (all of them move under the new kept idea); the alternative is to refuse and ask for an unmerge first.

---

## Appendix A - CRM (sorento) brief: "ideation status update" (for the Sorento session)

**Dependency:** needs this repo's PR deployed (feed live) and the CRM workspace key already used for `POST /ideation/intake/create-idea`.

1. **Template use case** `ideation_status_update` on the CRM template screen (same mechanism as `ideation_draft_reminder`, sorento #1201), category Utility, submitted for WhatsApp approval. Suggested body: "Update on your idea {{1}}: it is now {{2}}. Track it here: {{3}}" with {{1}} = `idea_number` (fall back to `idea_title`), {{2}} = `status_label`, or for `kind = "merged"` the text "combined with {merged_into.idea_number}", or for `kind = "unmerged"` the text "handled separately again from {separated_from.idea_number}, now {status_label}", {{3}} = `track_url` (or a URL button with the token as suffix if the template uses a button). Owner approves the wording.
2. **Poller** in the ideation service layer (next to `ideation_turn_service`): every 60 s call `GET /ideation/intake/status-events?after=<cursor>&limit=100`; process ascending; persist the cursor only after each event is handled.
3. **Idempotency:** unique `event_id` in the CRM integration log; skip seen ids (at-least-once feed).
4. **Guards before send:** `is_test` true -> never send (log only); requester opted out -> skip + log; resolve the Respond.io contact by `requester_phone`.
5. **24h window:** always send the approved template (business initiated); do not attempt free text.
6. **Logging:** every send/skip in the CRM integration log with `event_id`, idea number, template, result.
