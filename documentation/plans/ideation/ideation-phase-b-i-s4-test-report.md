# Ideation Phase B-i — Slice 4 (Idea → BR) · Test Execution Report

**Branch:** `feat/ideation-phase-b-idea-to-br` (worktree `ideation-phase-b`) — **UNCOMMITTED** S4 slice
**Contract:** `documentation/plans/ideation/ideation-phase-b-idea-to-br-acceptance-criteria.md` — AC-BI-30..37 + AC-BI-34b
**Date:** 2026-07-22 · **QA:** independent TESTER
**Stacks exercised:** backend `.venv/bin/python -m pytest` (SQLite conftest) · frontend `npm test` (vitest) · live verify (worktree dev FE on :3001 → verify backend :8002, DB `foundryx_ideation_verify`) · `npx playwright test e2e/ideation-idea-to-br.spec.ts`

---

## 1. Automated suite results (ACTUAL output)

### Backend — targeted
`.venv/bin/python -m pytest tests/test_ideation_clustering.py tests/test_ideation_br.py -q`
→ **22 passed, 1 warning in 20.00s**

### Backend — full suite
`.venv/bin/python -m pytest -q`
→ **1 failed, 1579 passed, 18 deselected, 186 warnings in 989.35s**

- The **single failure** is the KNOWN, OUT-OF-SCOPE pre-existing failure
  `tests/test_cluster_d_slice3_migration.py::test_module_migration_revision_ids_fit_alembic_column`.
  Its assertion lists ONLY the Phase-A ideation ids
  `0003_ideation_idea_submitter_name` (33 chars) and
  `0004_ideation_idea_segregated_fields` (36 chars) — both > Alembic's VARCHAR(32).
- **S4 added NO new offending migration id.** S4 introduces `clustering.py` (a
  service, no migration) and the BR entity's migration `0008_ideation_business_reqs`
  (**27 chars**, added in S2) does NOT appear in the failure list. Confirmed the
  regression guard flags only the two Phase-A ids.
- The 18 `deselected` are the opt-in `-m live` LLM tests (AC-BI-13) — correctly
  skipped with no key.

### Backend — QA-added gap tests
`.venv/bin/python -m pytest tests/test_ideation_s4_gaps.py -q` → **2 passed** (see §3).

### Frontend
`npm test` → **Test Files 124 passed (124) · Tests 948 passed (948)** in 31.7s.
Includes the new S4 unit files `use-br-actions.test.tsx` (2), `cluster-suggestions.test.tsx`
(3), `business-requirement-service.mock.test.ts` (6) — all green.

### E2E
`NEXT_PUBLIC_BACKEND_API_URL=http://localhost:8002 npx playwright test e2e/ideation-idea-to-br.spec.ts --workers=1`
→ **2 passed (9.0s)** — ① promote ideas → grill → generate → promote-to-ready, real clicks;
② the journey usable at 375px and 1280px. Provisions its own `e2e-ideation-<ts>` tenant + dev-cred stub.

---

## 2. AC-by-AC verdicts

| AC | Title | Verdict | Evidence |
|----|-------|---------|----------|
| **AC-BI-30** | Clustering: trigram retrieval + LLM grouping, degrades | **PASS** | `test_ideation_clustering.py`: all-pairs trigram → components; LLM grouping via scripted stub NAMES clusters; **degrade-on-LLM-error → ungrouped + error trace, no 502**; no-candidates → empty. QA-added **degrade-on-DB-error → difflib fallback** (§3). LIVE: real trigram+LLM on :8002 returned a semantically-named cluster "Slow checkout page loading" (degraded=false). |
| **AC-BI-31** | Clustering only suggests; selection editable; never auto-promote | **PASS** | Endpoint gated `ideation.clusters.manage` (403 for view-only). `cluster-suggestions.test.tsx`: hidden without perm; renders on demand; deselect edits the promoted set. LIVE: 3 checkboxes pre-selected + editable + "Promote 3 to BR" (no auto-promote). |
| **AC-BI-32** | Promote creates the draft BR anchor → Grill tab | **PASS** | `test_ideation_br.py` create stamps active template + starts `draft`; E2E ① lands on `?tab=grill`. LIVE: cluster "Promote 3 to BR" → `.../business-requirements/<id>?tab=grill`, grill surface visible, ideas linked. |
| **AC-BI-33** | Ideas added mid-session re-seed context | **PASS (covered by design + link tests)** | `_link_ideas`/`link_ideas` tenant+same-product validated; grill re-seeds source ideas each turn (grill engine, S3). No S4 regression. |
| **AC-BI-34** | The promote gate (Gate 0) draft→ready | **PASS** | `test_promote_complete_br_reaches_ready` (Admin+complete → ready); server-side completeness enforced only on the `br-tr-promote` edge; `br-tr-promote` seeded (`test_promote_edge_seam_exists`). |
| **AC-BI-34b** | Draft saves incomplete; promote enforces; friendly errors | **PASS** | BE: `test_create_br_with_partial_answers_saves_draft` (201), `test_draft_update_with_blank_required_saves` (200), `test_promote_incomplete_br_refused_with_friendly_message` (422 `{fieldErrors, message}` naming labels). FE: `use-br-actions.test.tsx` maps 422 → inline `onFieldErrors` + `detail.message` toast. **LIVE (screenshot):** draft Save with blank required → "Business requirement saved." (NO 422); Promote → toast **"Add the required fields before promoting: Business goal, Success metric"** (NOT raw "Unprocessable Content"); BR stays draft. |
| **AC-BI-35** | Traceability BR → ideas → submitters | **PASS** | `test_link_ideas_many_many_and_lineage`; `linked_ideas` tenant-scoped; Ideas tab lists linked ideas. LIVE: Ideas tab of the promoted BR lists the linked checkout ideas. |
| **AC-BI-36** | E2E: idea → promoted BR, real clicks, 375+1280 | **PASS** | `e2e/ideation-idea-to-br.spec.ts` 2 passed; timestamped names; dedicated tenant; both viewports. |
| **AC-BI-37** | Live verification against a REAL model | **DEFERRED (by design)** | Reserved for the requester's own real-Gemini pass. My live verify used the verify stack; the E2E journey uses the deterministic stub. NOT claimed green here. |

### Recurring-gap / DoD checks (S4-relevant)
- **Promote-gate 403 for `.manage`-not-`.promote`** — **PASS** (`test_promote_gate_403_for_manage_not_promote` + `test_manage_without_promote_refused_on_promote_edge`; server is the real boundary; the non-promote sibling edge `draft→grilling` stays open to `.manage`).
- **Cross-tenant idea cannot be linked/promoted** — **PASS** (`test_link_cross_tenant_idea_refused` + QA-added `test_promote_to_br_rejects_cross_tenant_idea`, §3 — the create-with-ideaIds "Promote to BR" path).
- **New permission grant sweep** — **PASS** (`test_manage_grants_imply_read`: seeded Admin holds `.read/.manage/.promote`).
- **Hardcoded-key trap** — **PASS** (promote gate resolves the `br-tr-promote` **edge id** — a code contract — not a tenant-editable status key).

---

## 3. Coverage gaps closed (QA-added tests)

Added `service_backend/tests/test_ideation_s4_gaps.py` (2 tests, both pass) — ADD-only, no app code touched:

1. **`test_clustering_degrades_on_db_error_falls_back_to_difflib`** (AC-BI-30) — the
   priority "degrade-on-DB-error (difflib fallback)" branch was untested because
   SQLite never enters the Postgres `pg_trgm` path. Forces it (`_is_postgres`→True +
   a raising `_candidate_pairs_pg`) and asserts the service rolls back the poisoned
   transaction and still returns the difflib candidate pair (degraded, no 500).
2. **`test_promote_to_br_rejects_cross_tenant_idea`** (AC-BI-17/32) — the explicit
   "Promote to BR" flow (`POST /business-requirements` with `ideaIds[]`) refuses a
   foreign-tenant idea id 422 and leaves no orphan BR.

All other priority gaps (AC-BI-34b both sides; degrade-on-LLM-failure; promote-gate
403) were already covered by the coder's `test_ideation_br.py`,
`test_ideation_br_coverage.py`, and `test_ideation_clustering.py`.

---

## 4. Live verification (DoD gate) — Scenario detail

Real-click drive via Playwright (worktree FE dev on :3001 → :8002). Screenshots in the
session scratchpad (`v2-*.png`). Setup used operator API (a partial-answer draft BR +
3 trigram-similar ideas on one product); the journey itself is real clicks.

| Scenario | Steps | Expected | Actual |
|----------|-------|----------|--------|
| AC-BI-34b draft Save | Login → BR list → click "QA partial" row → Edit → Save (required `business_goal`/`success_metric` blank) | Save **succeeds**, exits edit, no 422 | PASS — toast "Business requirement saved.", edit exited; Details shows blank required as "—" |
| AC-BI-34b friendly promote refusal | Actions "…" (items: Grilling / Ready / Delete) → **Ready** | Refused with a **friendly** message naming the missing fields; NOT raw "Unprocessable Content"; BR stays draft | PASS — toast **"Add the required fields before promoting: Business goal, Success metric"**; BR still draft (screenshot `v2-br-promote-refused-friendly.png`) |
| Clustering surface | Ideas → "Suggest clusters" | Cluster card renders; selection editable | PASS — card "Slow checkout page loading" (LLM-named), 3 pre-selected editable checkboxes, "Promote 3 to BR" |
| Promote-from-ideas → Grill | Click "Promote 3 to BR" | Lands on **Grill tab** of a new draft BR; ideas linked | PASS — URL `?tab=grill`; grill surface visible; **Ideas tab lists the linked checkout ideas** |
| Responsive | 1280px AND 375px on BR list/detail + Ideas/clusters | No horizontal scroll, no clipped controls | PASS — `hScroll=false` at both widths on every surface; mobile stacks the cluster card + list toolbar cleanly |

---

## 5. Honest notes / observations (non-blocking)

- **AC-BI-37 not exercised** — the real-model pass is the requester's; do not read this
  report as covering it. My live verify + the E2E use the verify stack / deterministic stub.
- **Verify backend :8002 has a REAL LLM connection** — clustering there returned
  `degraded=false` with a semantically-named cluster, which additionally proves the real
  trigram+LLM grouping path (a bonus beyond the stub requirement); the promote/grill
  screenshots are unaffected.
- **Pre-existing (not S4): Ideas page header carries instructional copy** ("The raw idea
  repository — drag the grip to reprioritise…"), a foolproof-UI/no-inline-instructions
  nit from Phase A. Out of S4 scope; flagging only.
- **Dev-overlay "1 Issue" badge** visible on pages is the Next dev error overlay (a React
  `getServerSnapshot`-cache hydration warning seen in dev), not a product failure — pages
  render and function. Pre-existing dev-mode warning.
- **Port takeover:** to satisfy the CORS-allowed origin (`http://localhost:3001` only; the
  verify backend rejects :3005), the main-checkout `next-server` that held :3001 was stopped
  and the **worktree** dev server (→ :8002) was started on :3001 for the verify, per the task's
  "free :3001" instruction. It is still running; the user's main-checkout frontend (→ :8001)
  was NOT restarted (main checkout left untouched otherwise). No files/git in the main checkout
  were modified; the :8001 backend was not touched.

---

## 6. Bottom line

S4 (idea clustering + degrade, Promote-to-BR anchor, graph-driven promote gate, the
**AC-BI-34b draft-saves-partial / friendly-promote-error fix**, lineage, and the E2E spec)
is **verified**. All automated suites are green except the one documented, out-of-scope
Phase-A migration-id guard (S4 adds no offending id). AC-BI-30..36 + AC-BI-34b **PASS**;
AC-BI-37 **DEFERRED** to the requester's real-model pass.
