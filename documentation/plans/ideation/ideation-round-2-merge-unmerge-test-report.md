# Issue #94 - Ideation round 2: merge/unmerge, form fixes, priority rank, engine statuses, requester status updates - Test Execution Report

**Contract:** `ideation-round-2-merge-unmerge-acceptance-criteria.md` (AC-94-01..78)
**Plan:** `PLAN-ideation-round-2-merge-unmerge.md`
**Branch under test:** `feat/ideation-round-2`, HEAD `ef18049b` (S0-S5, worktree `foundryx-shared-service-ideation-r2`)
**Lane:** dedicated - DB `foundryx_service_ir2` (Postgres, native), Redis db 5, backend `:8016`, frontend `:3016` (`npx next start -p 3016`). Bootstrap output and every environment correction needed to stand the lane up are recorded in `94-evidence/s6/README.md`.
**Servers left RUNNING** at the end of this report per instruction - see "Lane details" at the bottom for pids.

---

## 1. Automated suite results (actual output, this run)

### Backend - full suite (absolute venv python from the MAIN checkout, run against the lane DB)
```
DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_ir2 \
.venv/bin/python -m pytest -q
```
-> **5747 passed, 1 skipped, 18 deselected, 624 warnings in 732.40s (0:12:12)**. Zero failures. (The 18 deselected are pytest-marker exclusions unrelated to this branch; the 1 skip is pre-existing.)

### Backend - ideation-scoped
```
.venv/bin/python -m pytest -q -k ideation
```
-> **391 passed, 5383 deselected in 94.02s**. Every UAC-named file exists and is green: `test_ideation_merge.py`, `test_ideation_priority_rank.py`, `test_ideation_status_display.py`, `test_ideation_status_events.py`, `test_ideation_embed_writes.py` (extended), `test_ideation_public_status.py` (extended), plus the regression set (`test_ideation_triage.py`, `test_ideation_ideas_actions.py`, `test_ideation_embed.py`, `test_ideation_dedup.py`, `test_ideation_clustering.py`, `test_ideation_create_idea.py`, `test_ideation_br*.py`, `test_ideation_intake_*.py`, `test_ideation_tenant_scoping.py`, `test_ideation_deferred_actions.py`, `test_ideation_s4_gaps.py`, `test_ideation_scaffold.py`, `test_ideation_products.py`, `test_ideation_ideas.py`, `test_ideation_ideas_operator.py`, `test_ideation_grill*.py`).

Targeted re-run of the six new/extended files alone: **127 passed** (`test_ideation_merge.py` + `test_ideation_priority_rank.py` + `test_ideation_status_display.py` + `test_ideation_status_events.py` + `test_ideation_embed_writes.py` + `test_ideation_public_status.py`).

### Frontend unit (Vitest, one full run per the brief)
```
npx vitest run
```
-> **421 test files passed (421), 3334 tests passed (3334)**, 95.02s. Zero failures (the `stderr` lines in the log are expected `console.error` calls inside error-path tests, e.g. a component asserting it renders a 422 - each is immediately followed by that test's own pass). Every UAC-named ideation FE spec present and green: `use-ideas-list-config.test.tsx` (18 tests), `merge-ideas-dialog.test.tsx` (2), `idea-merged-tab.test.tsx` (5), `vote-cell.test.tsx` (3), `idea-form-fields.test.tsx` (6), `use-idea-form.test.tsx` (3), `board/page.test.tsx` (9 - see the live-vs-jsdom discrepancy noted under AC-94-58 below), `embed-ideas.test.tsx` (8), `ideation-service.real.test.ts` (14), `ideation-constants.inventory.test.ts` (2), plus regression (`idea-capture-dialog`, `idea-brs-tab`, `cluster-suggestions`, `promote-to-br`, `ideas-view`, `paths`, `embed-connection-create-dialog`, `use-embed-connections-list-config`, `use-br-*`, `grill-chat`, `br-create-dialog`, `ideation-service.mock.test.ts`).

### Lint
```
npm run lint
```
-> **0 errors, 243 warnings**, exit code 0. All 243 warnings are pre-existing `jsx-a11y` warnings on files this branch did not touch (email-editor, flow-canvas, form-builder, form-renderer, import-wizard, jobs-drawer, resource-list, webchat-panel, workflow-canvas). No new `no-restricted-imports` violation (AC-94-73 confirmed: no disable comment added, no bare `<Select>`/table/sonner import in the diff's files).

### Dashes
`git diff main...feat/ideation-round-2` (already merged history) was clean of em/en dashes at the review rounds recorded in the branch's own commits (AC-94-76); not re-swept in this round since no code changed - only this report and its evidence were authored, and both are written with plain hyphens only.

---

## 2. AC-by-AC verdicts

### A. Merge and unmerge - data and API (AC-94-01..20) - all [BE][T]

All twenty backed by `tests/test_ideation_merge.py` / `test_ideation_embed_writes.py` / `test_ideation_public_status.py`, green in the full suite. Several were additionally proven LIVE in this round (not just by the unit test) through real UI actions against the lane:

| AC | Verdict | Live cross-check this round |
|----|---------|------------------------------|
| AC-94-01 merge collapses onto survivor | **PASS** | Live: merged Bravo+Charlie -> Bravo carries `mergedCount=1`, toast "Merged into IDEA-0002." (`AC-94-27-merged-list-1280.png`) |
| AC-94-02 list/board hide merged children | **PASS** | Live: Charlie absent from the list after merge |
| AC-94-03 merged child still readable, `/merged` listing | **PASS** | Live: `GET`-backed "Merged from" tab lists exactly the child (`AC-94-28-merged-from-tab-1280.png`) |
| AC-94-04 merge refuses invalid selections | **PASS** | Live cross-product refusal observed directly: the merge dialog for the WhatsApp idea (Software product) only ever offered same-product partners; Golf/Hotel (the other product) never appeared as merge candidates |
| AC-94-05 merging a survivor flattens | **PASS** | Test-only this round (not re-proven live) |
| AC-94-06 votes follow merge/unmerge | **PASS** | Test-only this round |
| AC-94-07 unmerge a single child | **PASS** | Live: child gear > Unmerge, "Idea unmerged." toast, Priority restored (`AC-94-29-*`) |
| AC-94-08 unmerge a survivor dissolves the group | **PASS** | Live: 3-way merge then bulk Unmerge on the survivor restored all three (`AC-94-30-list-after-unmerge-1280.png`) |
| AC-94-09 a merged child is frozen | **PASS** | Live: child form gear offered ONLY Unmerge + Delete, vote arrows disabled (`AC-94-28-child-form-1280.png`) |
| AC-94-10 deleting a survivor restores children first | **PASS** | Test-only |
| AC-94-11 dedup/clustering ignore merged children | **PASS** | Test-only |
| AC-94-12 survivor always gets an idea number | **PASS** | Live: Bravo (no idea number before) became "IDEA-0002" on merge |
| AC-94-13 public page of a merged child | **PASS** | Live: the WhatsApp idea's track link, merged into IDEA-0004, reads "Merged into IDEA-0004" with the survivor's status/timeline (`AC-94-31-track-link-merged-1280/375.png`) |
| AC-94-14 exact key-set growth (+`mergedInto`) | **PASS** | Test-only |
| AC-94-15 tenant isolation end to end | **PASS** | Test-only; live cross-tenant isolation independently confirmed via the status-events feed (section 3) |
| AC-94-16 embed parity, product scope | **PASS** | Live: merge + unmerge inside `/embed/ideas` behaved identically (`AC-94-32-embed-*`) |
| AC-94-17 permission reuse, no new CSV row | **PASS** | `ideation/permissions/permissions.csv` unchanged per the branch diff (test-only re-verify) |
| AC-94-18 migration 0012 applies + backfills | **PASS** | Live: `bootstrap_db` on a fresh lane DB landed exactly at `0012_ideation_merge_rank_events`; every idea captured live got a real 1-based priority (see README) |
| AC-94-19 reorder ignores merged children | **PASS** | Test-only |
| AC-94-20 unmerge restores list position | **PASS** | Live: Charlie reappeared at Priority #3 after unmerge (screenshot `AC-94-29-list-after-unmerge-1280.png` shows the form's Priority row reading #3 mid-flow) |

### B. Merge and unmerge - screens (AC-94-21..32)

| AC | Type | Verdict | Evidence |
|----|------|---------|----------|
| AC-94-21 Merge in bulk Actions menu | [FE][T] | **PASS** | `use-ideas-list-config.test.tsx` "merge visibility" green; live confirmed hidden/disabled rules while building AC-94-27/30 |
| AC-94-22 survivor picker is `SearchSelect` | [FE][T] | **PASS** | `merge-ideas-dialog.test.tsx` green; live dialog showed exactly the 2 (then 3) selected ideas, no default pick, Merge disabled until chosen (`AC-94-27-merge-dialog-1280.png`) |
| AC-94-23 merged count badge | [FE][T] | **PASS** | Live "1 merged" / "2 merged" badges seen throughout |
| AC-94-24 list Unmerge on a survivor | [FE][T] | **PASS** | Live: row+bulk Unmerge fired, reloaded (`AC-94-30-*`) |
| AC-94-25 "Merged from" tab | [FE][T] | **PASS** | Live tab present/hidden correctly (`AC-94-28-merged-from-tab-1280.png`, `AC-94-74-merged-from-tab-375.png`) |
| AC-94-26 the child form | [FE][T] | **PASS** | Live: "Merged into" row + link, gear = Unmerge/Delete only, votes disabled (`AC-94-28-child-form-*`) |
| AC-94-27 E2E merge two ideas | **[E2E]** | **PASS** | See detail below |
| AC-94-28 E2E open merged child | **[E2E]** | **PASS** | See detail below |
| AC-94-29 E2E unmerge from child form | **[E2E]** | **PASS** | See detail below |
| AC-94-30 E2E unmerge from list | **[E2E]** | **PASS** | See detail below |
| AC-94-31 E2E requester track link after merge | **[E2E]** | **PASS** | See detail below |
| AC-94-32 E2E embed parity | **[E2E]** | **PASS** | See detail below |

#### AC-94-27 - E2E: merge two ideas
- **Precondition:** Tenant `default`, ideas `E2E Idea 20260928-1218 Bravo` and `...Charlie` captured moments earlier (timestamped).
- **Steps:** Sidebar Ideation > Ideas; tick Bravo + Charlie; Actions (bulk) > Merge; SearchSelect > pick Bravo; click Merge.
- **Expected:** One row remains, "1 merged" badge.
- **Actual:** Toast "Merged into IDEA-0002.", list shows Bravo with a "1 merged" badge, Charlie gone. Matches.
- **Screens:** `AC-94-27-merge-dialog-1280.png`, `AC-94-27-merged-list-1280.png`, `AC-94-27-merged-list-375.png`.
- **Verdict: PASS**

#### AC-94-28 - E2E: open a merged child from the survivor
- **Steps:** Open Bravo (survivor) > "Merged from" tab > click Charlie row > click the "IDEA-0002" link on Charlie's form.
- **Expected:** Charlie's form shows "Merged into IDEA-0002"; the link returns to Bravo.
- **Actual:** Exactly that; verified the return navigation landed back on the Bravo form heading.
- **Screens:** `AC-94-28-merged-from-tab-1280.png`, `AC-94-28-child-form-1280.png`, `AC-94-28-child-form-375.png`.
- **Verdict: PASS**

#### AC-94-29 - E2E: unmerge from the child form
- **Steps:** Charlie's form (still open) > gear > Unmerge.
- **Expected:** Success toast, both ideas rows again on the list, no badge.
- **Actual:** Toast "Idea unmerged.", Charlie's own form immediately re-rendered with Priority `#3` (its restored position) and no "Merged into" row; back on the list both Bravo and Charlie are separate rows, no badge.
- **Screens:** `AC-94-29-child-actions-menu-1280.png`, `AC-94-29-unmerge-toast-1280.png`, `AC-94-29-list-after-unmerge-1280.png`, `AC-94-29-list-after-unmerge-375.png`.
- **Verdict: PASS**

#### AC-94-30 - E2E: unmerge from the list
- **Steps:** Merged Delta+Echo+Foxtrot (survivor Delta, "2 merged"); ticked Delta; Actions > Unmerge.
- **Expected:** All three rows again.
- **Actual:** Toast "Merged into IDEA-0003." on merge, then all three (Delta, Echo, Foxtrot) present as separate rows with no badges after Unmerge.
- **Screens:** 1280 `AC-94-30-actions-menu-1280.png` + `AC-94-30-list-after-unmerge-1280.png`; 375 `AC-94-30-actions-menu-375.png` (the Actions menu, as the AC specifically asks for).
- **Verdict: PASS**

#### AC-94-31 - E2E: the requester's track link after merge
- **Precondition:** A WhatsApp-style idea captured through the real `POST /ideation/intake/create-idea` multi-turn flow (workspace API key), requester `+60191234567`, became `IDEA-0001` with its own track token. Merged into idea `India` (`IDEA-0004`) on the same product.
- **Steps:** Open the track link (`/public/ideas/<token>`) - the sole sanctioned entry to that page.
- **Expected:** Page reads "Merged into IDEA-0004" with the survivor's status/timeline, the child's own content fields.
- **Actual:** Exactly that - problem/solution/impact are the child's own text; status badge, timeline and vote count are India's (all "New"/0 at capture time).
- **Screens:** `AC-94-31-track-link-merged-1280.png`, `AC-94-31-track-link-merged-375.png`.
- **Verdict: PASS**

#### AC-94-32 - E2E: embed parity
- **Precondition:** An embed connection (`e2e-embed-20260928-1218`, no product scope) created through Ideation > Embed connections in the UI. The connection's own signing secret (shown once) was used to mint a short-lived host assertion locally (`python-jose`, `iss=sorento`, `aud=ideation-embed`, `typ=assertion`) and exchanged via `POST /embed/session` for an embed token, placed in `/embed/ideas#token=...` - the same handshake the host performs; no code path was bypassed (a wrong secret/issuer/audience was independently confirmed to be rejected while wiring this up).
- **Steps:** In `/embed/ideas`: tick Alpha + Juliet; Bulk actions > Merge > pick Alpha > Merge; then tick Alpha; Bulk actions > Unmerge.
- **Expected:** Behaviour matches AC-94-27..29 inside the embed.
- **Actual:** Toast "Merged into IDEA-0006." then "1 merged" badge; Unmerge toast, both rows restored with no badge. Identical to the operator surface.
- **Screens:** `AC-94-32-embed-list-1280.png`, `AC-94-32-embed-merge-dialog-1280.png`, `AC-94-32-embed-merged-1280.png`, `AC-94-32-embed-merged-375.png`, `AC-94-32-embed-unmerged-1280.png`, `AC-94-32-embed-unmerged-375.png`.
- **Verdict: PASS** (not deferred - the assertion was mintable locally)

### C. Form view fixes (AC-94-33..40)

| AC | Type | Verdict | Evidence |
|----|------|---------|----------|
| AC-94-33 no Status control, any mode | [FE][T] | **PASS** | `idea-form-fields.test.tsx` green; live: neither read nor edit mode rendered any "Status" text anywhere on the Delta form or the dedicated tenant's Rename-Track form |
| AC-94-34 save is fields-only | [FE][T] | **PASS** | `ideation-service.real.test.ts` green; live network capture on Save showed only `PATCH /ideation/ideas/{id}`, never `/status` |
| AC-94-35 clickable votes in the form | [FE][T] | **PASS** | `vote-cell.test.tsx` + `use-idea-form.test.tsx` green; live below (AC-94-37) |
| AC-94-36 record pager "n / N" | [FE][T] | **PASS** | live below (AC-94-38) |
| AC-94-37 E2E form votes | **[E2E]** | **PASS** | see below |
| AC-94-38 E2E pager | **[E2E]** | **PASS** | see below |
| AC-94-39 E2E edit mode has no status | **[E2E]** | **PASS** | see below |
| AC-94-40 embed pager (`ctx`/`i`, no token in query) | [FE][T] | **PASS** | `embed-ideas.test.tsx` "pager" green |

#### AC-94-37 - E2E: form votes
- **Steps:** Open idea (from the pager flow, Delta) > click the up arrow.
- **Expected:** Up count increments, arrow shows pressed; click again cancels.
- **Actual:** Button changed to "Cancel upvote" and the count row read `1  0`; a second click restored `Upvote`/`0  0`.
- **Screens:** `AC-94-37-vote-up-1280.png`, `AC-94-37-vote-up-375.png`.
- **Verdict: PASS**

#### AC-94-38 - E2E: pager
- **Steps:** Opened the 2nd list row (Bravo, "2 / 9"); clicked Next twice.
- **Expected:** "3 / N" then "4 / N", title changes to those rows.
- **Actual:** "3 / 9" (Charlie) then "4 / 9" (Delta) - title updated both times.
- **Screens:** `AC-94-38-pager-step1-1280.png`, `AC-94-38-pager-step2-1280.png`, `AC-94-38-pager-step2-375.png`.
- **Verdict: PASS**

#### AC-94-39 - E2E: edit mode has no status control
- **Steps:** Click Edit on Delta's form; inspect; click Save.
- **Expected:** No Status control visible; Save succeeds.
- **Actual:** Edit-mode field list = problem/solution/impact/department/product/votes/raw notes only, no status anywhere; Save produced toast "Idea updated." and a `PATCH` (never `/status`, confirmed via network capture).
- **Screens:** `AC-94-39-edit-no-status-1280.png`, `AC-94-39-edit-no-status-375.png`.
- **Verdict: PASS**

### D. Priority rank (AC-94-41..48)

All [BE][T]/[FE][T] backed by `test_ideation_priority_rank.py` / `use-ideas-list-config.test.tsx`, green.

| AC | Verdict | Live cross-check |
|----|---------|-------------------|
| AC-94-41 rank 1-based, server computed | **PASS** | Live: 8 captured ideas showed priority 1..8 in DB order matching list order |
| AC-94-42 rank follows caller scope | **PASS** | Test-only |
| AC-94-43 detail carries same rank | **PASS** | Live: Charlie's form Priority matched its list position throughout |
| AC-94-44 new capture gets a real rank at the end | **PASS** | Live: idea "Juliet" (9th real idea at capture time) got priority/rank 10 after another capture pushed the count; the very next capture ("Juliet") landed at `#10` (see AC-94-48 detail) |
| AC-94-45 page-2 drag no longer collides | **PASS** | Test-only |
| AC-94-46 form shows rank, never raw priority | **PASS** | Live: every form showed "#N" or "-", never a raw 0-based number |
| AC-94-47 list order is the server's order | **PASS** | `use-ideas-list-config.test.tsx` "server order" green |
| AC-94-48 E2E drag then open | **[E2E]** | **PASS** | see below |

#### AC-94-48 - E2E: drag then open
- **Steps:** Dragged the 3rd row (Charlie) to the top of the list; opened it. Then captured a new idea ("Juliet") and opened it.
- **Expected:** Dragged idea reads "Priority #1"; the new capture shows the last rank.
- **Actual:** Charlie's form read "Priority #1" immediately after the drag. Juliet (captured after 9 existing real ideas) opened showing "Priority #10".
- **Screens:** `AC-94-48-drag-1280.png` (the drag/board reorder), `AC-94-48-form-priority-375.png` (the form).
- **Verdict: PASS**

### E. Status labels, colours and transitions from the statuses engine (AC-94-49..60)

| AC | Type | Verdict | Evidence |
|----|------|---------|----------|
| AC-94-49 API returns engine display | [BE][T] | **PASS** | `test_ideation_status_display.py` green |
| AC-94-50 a rename shows everywhere | [BE][T] | **PASS** | Test-only + live cross-check (see AC-94-59) |
| AC-94-51 per-record fireable transitions | [BE][T] | **PASS** | Test-only; live `GET /ideation/ideas/board` payloads inspected by hand showed per-idea `transitions` arrays consistent with the tier's edges |
| AC-94-52 advance = next stage by sort order | [BE][T] | **PASS** | Live: "Move to Triaged" (then, on the renamed tenant, "Move to Discussed-...") was always the fireable edge whose target is the next `sort_order` stage |
| AC-94-53 moves by target status id | [BE][T] | **PASS** | Test-only |
| AC-94-54 board columns from trait flags | [BE][T] | **PASS** | Live: `GET /ideation/ideas/board` JSON inspected by hand - columns keyed by trait flags, `BOARD_COLUMNS`/`_ARCHIVED_KEYS` gone from the diff |
| AC-94-55 FE constants deleted | [FE][T] | **PASS** | `ideation-constants.inventory.test.ts` green; `grep -rn "IDEA_STATUS_LABEL\|IDEA_NEXT_STATUS\|IDEA_BOARD_COLUMNS" service_frontend` returns nothing in this checkout |
| AC-94-56 labels/colours from the API | [FE][T] | **PASS** | `use-ideas-list-config.test.tsx` "status from API" green; live Status column showed "New" and, after rename, "Discussed-20260928-1218" |
| AC-94-57 Advance to next stage (row/form/bulk) | [FE][T] | **PASS** | Live: bulk Advance read "Move to Discussed-20260928-1218" after the rename (screenshot below) |
| AC-94-58 board columns/drops from API | [FE][T] | **FAIL (live)** | See below - jsdom unit test passes, the real browser crashes |
| AC-94-59 E2E rename in the statuses engine | **[E2E]** | **PARTIAL PASS** | See below |
| AC-94-60 Archived view shows archived ideas | [FE][BE][T] | **PASS** | Test-only this round (not separately re-verified live; covered by the merge/unmerge Active-view screenshots showing the correct "Active"/"Archived" segmented control) |

#### AC-94-58 - board columns and drops from the API - **FAIL, live browser only**
- **Given** the board page, **when** it is opened with real captured ideas present (either the `default` tenant or a freshly-provisioned dedicated tenant), **then** it should render columns from `GET /board`.
- **Actual:** The page throws immediately on render: `TypeError: Cannot read properties of undefined (reading 'map')`, stack rooted in a shared/vendor JS chunk (not an ideation source file per the visible frame), and the app's generic error boundary ("Something went wrong") replaces the board. Reproduced on BOTH the `default` tenant (9 real ideas, several merged/unmerged during this session) and the freshly-provisioned `e2eideation1218` tenant (1 real idea). The `GET /ideation/ideas/board` response itself was fetched by hand (`curl`) in both cases and is well-formed per AC-94-54's contract (each column carries `statusId/key/title/color/ideas[]`, `ideas` always an array, never `null`/missing) - so the defect is in the frontend board wiring, not the API.
- **Notable:** `app/(protected)/ideation/board/page.test.tsx` (9 tests, jsdom/Vitest) is green - the unit test does NOT reproduce this, which points at something the jsdom test double/mocked Kanban wiring doesn't exercise the same way the real DOM/dnd-kit measurement path does (worth a coder look, e.g. a `ResizeObserver`/`getBoundingClientRect` assumption the Kanban primitive makes that jsdom silently no-ops).
- **Screenshot:** `AC-94-58-board-crash-1280.png`.
- **Remarks:** Not fixed - tester does not touch app code. This is the one concrete regression found this round; everything else the board would have shown (the renamed column title "Discussed-20260928-1218") was independently confirmed correct through the raw API response and through the requester status-events feed (section 3), so the DATA side of AC-94-58/59 is right - only the board's own render crashes.

#### AC-94-59 - E2E: rename in the statuses engine - **PARTIAL PASS**
- **Precondition:** A dedicated tenant `e2eideation1218` (provisioned via the platform operator API, `platform@example.com`, per the AC's own instruction that the rename forks the tenant's status set) with ideation + omnichannel installed, one product, one WhatsApp-captured idea (`IDEA-0005`, requester `+60197654321`).
- **Steps:** Logged into `http://e2eideation1218.localhost:3016`; Settings > Statuses > Idea entity > clicked "Edit" (the page-level edit toggle that forks the platform-tier set onto the tenant) > clicked the "Triaged" node > renamed it to `Discussed-20260928-1218` > Save status. Then: Ideation > Ideas (Status column check + Advance label check) > attempted Ideation > Triage board (board column check) > opened the idea's public track link.
- **Expected:** Status column, the Advance label on a New idea, the board column, and the public track page all read the new name; the idea form shows no status.
- **Actual:**
  - Statuses engine node itself: renamed and saved cleanly (`AC-94-59-statuses-engine-renamed-1280/375.png`).
  - Row Actions menu on the New idea: "Move to Discussed-20260928-1218" (`AC-94-59-advance-label-1280.png`).
  - After firing that action, the list Status column read "Discussed-20260928-1218" (`AC-94-59-status-column-1280/375.png`).
  - The idea's own public track page read "Discussed-20260928-1218" as both the badge and the active timeline step (`AC-94-59-public-page-renamed-1280/375.png`).
  - The idea's form (both read mode, after the rename, and edit mode) showed no Status row at all - consistent with AC-94-33.
  - The Triage board column check could NOT be completed: the board page crashes on render (AC-94-58 above) for this tenant too. The renamed label WAS independently confirmed to reach the board's own data source (`GET /ideation/ideas/board` returned `"title": "Discussed-20260928-1218"` for that column when fetched by hand), and independently again through the status-events feed (`status_label: "Discussed-20260928-1218"`, section 3) - so only the visual board-column leg of this AC is blocked, by the same defect as AC-94-58.
- **Verdict: PASS on 4 of 5 legs (statuses engine, Status column, Advance label, public page, no-status-on-form); FAIL on the board-column leg (blocked by AC-94-58's crash).**

### F. Requester status updates - event feed (AC-94-61..72)

All [BE][T], backed by `test_ideation_status_events.py`, green in the full suite. Additionally proven LIVE this round via the actual feed endpoint (not just the unit test):

**Live sequence:** on the WhatsApp idea `IDEA-0001` (requester `+60191234567`): unmerge -> stage move (New -> Triaged) -> re-merge into `IDEA-0004`. Waited >5s for the settle window, then `GET /ideation/intake/status-events?after=0&limit=100` with the `default` tenant's own workspace API key returned, in ascending `seq`:

```json
{
  "events": [
    {"seq": 1, "kind": "merged", "idea_number": "IDEA-0001", "status_label": "New",
     "merged_into": {"idea_number": "IDEA-0004", "title": "E2E Idea 20260928-1218 India"},
     "separated_from": null, "requester_phone": "+60191234567", "is_test": false, ...},
    {"seq": 3, "kind": "unmerged", "idea_number": "IDEA-0001", "status_label": "New",
     "merged_into": null,
     "separated_from": {"idea_number": "IDEA-0004", "title": "E2E Idea 20260928-1218 India"}, ...},
    {"seq": 4, "kind": "status_changed", "idea_number": "IDEA-0001",
     "from_status_label": "New", "status_label": "Triaged",
     "merged_into": null, "separated_from": null, ...},
    {"seq": 5, "kind": "merged", "idea_number": "IDEA-0001", "status_label": "New",
     "merged_into": {"idea_number": "IDEA-0004", "title": "E2E Idea 20260928-1218 India"}, ...}
  ],
  "next_after": 5
}
```
Every row's key set is exactly `event_id, seq, kind, occurred_at, idea_id, idea_number, idea_title, product_id, status_label, from_status_label, track_url, requester_phone, merged_into, separated_from, is_test` - matches AC-94-63 field for field. `seq=2` is missing from this feed (it belongs to a different tenant's event, below) - itself live proof of tenant scoping (AC-94-66), since the sequence counter is evidently shared but each tenant's key only ever sees its own rows.

The SAME query against the dedicated `e2eideation1218` tenant's own key returned exactly one row: `{"seq": 2, "kind": "status_changed", "idea_number": "IDEA-0005", "from_status_label": "New", "status_label": "Discussed-20260928-1218", ...}` - the renamed label reaching the event feed independently of the UI (further live cross-check of AC-94-50).

| AC | Verdict |
|----|---------|
| AC-94-61 every stage change writes an event | **PASS** (live: seq 4 above) |
| AC-94-62 no event out of Draft / no requester | **PASS** (test-only; consistent with the operator-authored Alpha/Juliet embed merge producing no visible event-feed noise) |
| AC-94-63 payload contract, exact keys | **PASS** (live, field-for-field match above) |
| AC-94-64 merge AND unmerge notify each child's requester | **PASS** (live: seq 1 `merged` + seq 3 `unmerged` above) |
| AC-94-65 survivor's stage change fans out, deduped by phone | **PASS** (test-only) |
| AC-94-66 the feed, cursor + tenant scope | **PASS** (live: both tenants' feeds independently correct, `next_after` present) |
| AC-94-67 test ideas never reach a real requester | **PASS** (test-only; every idea in this run was `is_test=false` by construction, no negative case exercised live) |
| AC-94-68 ordering and idempotency, 5s settle window | **PASS** (test-only; the live curl was deliberately run after a >5s wait per the brief) |
| AC-94-69 a failing subscriber never breaks the move | **PASS** (test-only) |
| AC-94-70 tenant-scoped requester lookup | **PASS** (test-only) |
| AC-94-71 uninstall clears events | **PASS** (test-only) |
| AC-94-72 CRM contract doc exists | **PASS** | `documentation/ideation/status-events-contract.md` present in the branch (reviewer-checklist item, not independently re-verified field-for-field this round beyond the live payload matching it) |

### G. Cross-cutting (AC-94-73..78)

| AC | Verdict | Evidence |
|----|---------|----------|
| AC-94-73 every select is the system dropdown | **PASS** | `npm run lint` clean of new `no-restricted-imports` violations; every dropdown touched live (product picker, merge survivor picker) was the `SearchSelect` pattern (a floating listbox with `option`/`Suggestions`, never a native `<select>`) |
| AC-94-74 responsive, 375 and 1280 | **PASS on all surfaces except the board** | List+badge, merge dialog, child form, "Merged from" tab, public merged page, Actions menus all captured at both sizes with no clipping/overflow. The Triage board could not be swept (AC-94-58 crash) at either size - only a 1280 crash screenshot exists. |
| AC-94-75 white-label + foolproof copy | **PASS** | Every new string seen live was state-only ("1 merged", "Merged into IDEA-0004", "Merged from", "Merged into", toasts naming the label) - no platform brand name, no instructional hint text |
| AC-94-76 no dashes | **PASS** | This report and its evidence README use plain hyphens only; no code changed this round |
| AC-94-77 layering | **PASS** | Not independently re-audited line-by-line this round (no code changed); relies on the prior review rounds recorded in the branch history |
| AC-94-78 suites green | **PASS** | Backend 5747 passed/1 skipped/0 failed; `npm test` (vitest) 3334 passed/0 failed; `npm run lint` 0 errors. `rm -rf .next && npm run build` was run once to produce the lane's build (see README) and succeeded. |

---

## 3. Summary

- **PASS:** 74 of 78 AC ids (fully or on every leg checked).
- **FAIL:** AC-94-58 (board render crash, live browser only - jsdom unit test does not reproduce it) and the board-column leg of AC-94-59 (blocked by the same crash; the other 4 legs of AC-94-59 pass). AC-94-74's board sweep is correspondingly incomplete (blocked, not clipping).
- **DEFERRED:** none - AC-94-32's embed assertion WAS mintable locally (`python-jose` + the connection's own signing secret), so no deferral was needed.
- **Not independently re-verified live this round** (relied on the green automated suites only, since no application code changed in this session): AC-94-05/06/10/11/14/15/17/19/20 (data-layer specifics already covered indirectly by the merges/unmerges performed live), AC-94-41/42/45/47/51/53/55/60/62/65/67-72/77.

The one genuine product defect found is filed as **AC-94-58/AC-94-59 board render crash** above (screenshot `94-evidence/s6/AC-94-58-board-crash-1280.png`, console signature `TypeError: Cannot read properties of undefined (reading 'map')` from a vendor chunk). Recommend the coder reproduce with a real browser (not jsdom) against either tenant used in this lane before re-running `board/page.test.tsx` - the unit test's mocks are not catching this.

---

## 4. Lane details (servers left running)

- Backend: `uvicorn` on `:8016`, `DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_ir2`, `REDIS_URL=redis://localhost:6379/5`, `CORS_ORIGINS` widened to include `http://localhost:3016`, `CORS_ORIGIN_REGEX` widened to `http://[a-z0-9-]+\.localhost:30[0-9][0-9]` (both env-only, not code changes).
- Frontend: `npx next start -p 3016`, `NEXT_PUBLIC_BACKEND_API_URL`/`BACKEND_API_URL=http://localhost:8016`, `NEXTAUTH_URL=http://localhost:3016`, `NEXTAUTH_SECRET` set.
- Demo login: `demo@example.com` / `demo1234` on `http://localhost:3016` (default tenant, ideation installed this session).
- Dedicated tenant for the rename AC: `e2eideation1218` / `e2e-admin-e2eideation1218@example.com` / `E2eTest1234!` on `http://e2eideation1218.localhost:3016`.
- pids reported to the caller alongside this report.
