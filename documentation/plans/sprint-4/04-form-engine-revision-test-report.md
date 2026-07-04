# Sprint 4 · Plan 04 — Form Submission Revisions — Test Execution Report

**Date:** 2026-06-18
**Branch:** `sprint-4/04-form-revisions`
**Stack under test:** FastAPI backend (dedicated `dreamz_ems_rev` Postgres DB, port 8012) + Next.js prod build (port 3002). Ports shifted to avoid two concurrent developers on the defaults.
**Method:** Phase 1 frontend-first UX verification (mock-bound) → Phase 2 backend + pytest → Phase 3 real-stack E2E (Playwright, real clicks) → Phase 4 code review.

---

## 1. Automated tests

| Suite | Result |
| --- | --- |
| Backend `pytest` (full) | **826 passed** |
| Backend `tests/test_form_revisions.py` (new, 12) | **12 passed** |
| Backend `tests/test_form_parity.py` (FE↔BE schema parity) | **passed** |
| Frontend `vitest` (forms scope) | **199 passed** |
| Frontend `tsc --noEmit` | **0 errors** |
| Frontend `eslint` (changed files) | **clean** |
| E2E `e2e/forms-revision.spec.ts` (3 journeys, real stack) | **3 passed** |

`test_form_revisions.py` covers: toggle persists · original identity (group_id == id, rev 1, current) · revise clones a frozen current submission into a new Draft (same group, rev+1, current, initial status, cloned answers) · prior revision frozen + demoted (status kept) · pins the CURRENT published version · guard matrix (revisions off / not current / not frozen / no published version) · list defaults to current-only · history chain · resubmit edits + fires the Submit edge · resubmit validates against the pinned version.

---

## 2. E2E execution (Playwright, real clicks against the live stack)

**Story:** As a form author, I revise a submitted entry into a new immutable version and resubmit corrected answers.
**Precondition:** A dedicated tenant (operator-API provision); a revisions-enabled published form with one required text field; one submitted entry (`{title: "Original proposal"}`).

| # | Scenario | Steps (real clicks) | Expected | Actual |
| --- | --- | --- | --- | --- |
| ① | Revise a frozen submission | Open submission → click **Revise** | New Draft rev 2 opens; "Current · rev 2" badge; **Edit & resubmit** shown; history lists rev 2 + rev 1 | ✅ Pass |
| ② | Edit & resubmit | From history open rev 2 → **Edit & resubmit** → fill page pre-filled with "Original proposal" → edit to "Revised proposal v2" → **Submit revision** | Redirect to detail; rev 2 now **Submitted**, "Current · rev 2"; edited answer rendered | ✅ Pass |
| ③ | Current-only list + immutability | List the form's submissions; read rev 1 via API | List shows ONE row (current rev 2, "rev 2" badge); rev 1 `isCurrent=false`, answers unchanged ("Original proposal") | ✅ Pass |

---

## 3. Manual UX verification (Playwright MCP, desktop 1280px + mobile 375px)

- **Settings — Allow revisions toggle:** renders in edit mode with helper text; toggles on/off; persists via PATCH. ✅
- **Submission detail (desktop):** "Current · rev N" badge beside the status; **Revise** (frozen) / **Edit & resubmit** (current Draft) actions; revision-history panel (each revision links to its own version-pinned detail). ✅
- **Submission detail (mobile 375px):** header + badges + actions wrap; the form / history / raw-answers columns stack; no horizontal scroll; history panel scrolls within bound. ✅
- **Full journey (mock):** submit → revise (rev 3 Draft) → edit ("Aisha Rahman (revised)") → resubmit → rev 3 Submitted; prior rev 2 byte-for-byte unchanged (immutability). ✅
- **Submissions list:** the revised group shows a single current row with a "rev N" badge; prior revisions hidden by default. ✅

---

## 4. Acceptance-criteria coverage (AC-04-RV-01 … 25)

| AC | Covered by |
| --- | --- |
| 01 toggle defaults off | `test_allow_revisions_toggle_persists` (create → false) |
| 02 toggle persists | `test_allow_revisions_toggle_persists` + UX |
| 03 toggle gates Revise | `test_revise_blocked_when_disabled` (409); UX hides action |
| 04 revise clones → Draft | `test_revise_clones_into_new_draft`; E2E ① |
| 05 prior frozen + demoted | `test_revise_clones_into_new_draft`; E2E ③; MCP immutability |
| 06 pins own version | `test_revise_pins_current_version` |
| 07 files clone by reference | by design (deep-copy of answer refs; no byte copy) — code review |
| 08 rides existing submit/transition | `test_resubmit_revision_edits_and_fires_submit`; E2E ② |
| 09–13 guard matrix (409/403) | `test_revise_blocked_when_disabled/_not_frozen/_on_stale_revision/_without_published_version`; service owner-or-manage guard |
| 14 list current-only | `test_list_defaults_to_current_only`; E2E ③ |
| 15 history chain | `test_revision_history_chain`; E2E ① |
| 16 version-faithful re-render | history links pin each revision's `versionId` (detail fetches `versionDefinition`) |
| 17 backfill correctness | Alembic `e6f7a8b9c0d1` backfill (`group_id=id`, rev 1, current); applied to dedicated DB |
| 18 latest-lookup index | partial index `ix_form_submissions_group_current` verified on the DB |
| 19–22 FE visibility/fill/badge/history | UX (desktop+mobile); E2E ①② |
| 23 type parity | `test_form_parity` green |
| 24 responsive both viewports | MCP 1280px + 375px |
| 25 E2E happy path | `e2e/forms-revision.spec.ts` (3 passed) |

---

## 5. Code review (Phase 4)

High-effort multi-angle review (correctness + reuse + altitude + conventions). Substantive findings addressed:

| Finding | Resolution |
| --- | --- |
| Concurrent `revise()` could create two `is_current` rows in a group | Partial **UNIQUE** index `(submission_group_id) WHERE is_current` (migration + model, so SQLite tests enforce it); the racing insert fails → caught → **409** |
| `revise()` derived the next number from the loaded row, not the group | Now `MAX(revision_number) + 1` via `max_revision_number()` (authoritative) |
| `resubmit_revision` silently left the row in Draft if the Submit edge was restricted | Now surfaces a **409** (an explicit submit action shouldn't no-op silently) |
| Hand-rolled `_status_is_active` re-implemented the scoped resolver + failed open on a foreign id | Replaced with the canonical `get_scope_status`; an unresolvable status now **refuses** the revise (no fail-open) |
| `submit()`/`resubmit_revision` duplicated the transition+emit tail | Extracted the shared `_fire_submit_and_emit` (one place for the load-bearing invariants) |

Re-verified after fixes: full backend suite **826 green**, `e2e/forms-revision.spec.ts` **3 green**. Remaining review notes (record-nav on a non-current revision; the owner/perm split; the revision fill-view assembly) were assessed low-severity / acceptable and left as-is.

## 6. Notes / deviations

- **Endpoint shape:** revise/resubmit live at `POST /submissions/{id}/revise` and `…/resubmit` (matching the existing `/submissions/{id}` + `/transition` routes), not under `/forms/{id}/…` as the plan sketched. The history chain is `GET /forms/{id}/submissions?group={groupId}` per plan.
- **Resubmit path:** `revise()` creates the Draft row; the author edits + resubmits via `POST /submissions/{id}/resubmit`, which validates against the revision's pinned version and fires the seeded Draft→Submitted edge through the ONE status executor (rides the existing transition pipeline, R3).
- **Caps count current revisions only** — revising never consumes a form's `max_submissions` / per-user quota.
- **Isolation:** ran on a dedicated DB + dedicated tenant so the migration's `alembic_version` bump never touched the shared DB the other developers use.
- Out of scope (deferred, unchanged): anonymous/public revision, blob GC on hard-delete, revision diff view.
