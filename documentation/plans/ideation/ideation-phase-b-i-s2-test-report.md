# Ideation Phase B-i · Slice 2 (Business Requirement entity) - Test Execution Report

**Scope:** independent QA of the UNCOMMITTED S2 slice on branch
`feat/ideation-phase-b-idea-to-br`
(worktree `/.claude/worktrees/ideation-phase-b`).
**Contract:** `ideation-phase-b-idea-to-br-acceptance-criteria.md` - **AC-BI-15..19**.
**Date:** 2026-07-22 · **Tester:** automated QA agent.
**Verdict:** S2 is in good shape. All AC-BI-15..17 and the AC-BI-18 surfaces PASS;
AC-BI-19 is **PARTIAL** - the permission catalog + grant sweep land, but the
`.promote` gate is **not enforced in S2** (deferred to S4). One pre-existing,
out-of-scope suite failure. Live DoD gate PASSED against real data on :8002.

---

## 1. Test suite execution - ACTUAL output

### Backend - the S2 file (`tests/test_ideation_br.py`)
`.venv/bin/python -m pytest tests/test_ideation_br.py -q`
```
............                                                             [100%]
12 passed, 1 warning in 8.28s
```

### Backend - coverage additions authored by this QA pass (`tests/test_ideation_br_coverage.py`)
`.venv/bin/python -m pytest tests/test_ideation_br_coverage.py -q`
```
....                                                                     [100%]
4 passed, 1 warning in 5.44s
```

### Backend - full suite
`.venv/bin/python -m pytest` (unbuffered, `-o addopts=""`)
```
===== 1 failed, 1543 passed, 18 skipped, 186 warnings in 892.19s (0:14:52) =====
```
- The 1543 passed **includes** the 12 S2 tests + the 4 new coverage tests.
- **The single failure is PRE-EXISTING and OUT OF SCOPE** (see §2). No S2 regression.
- 18 skipped = the opt-in `pytest -m live` LLM suite (AC-BI-13) + other pre-existing skips.

### Frontend - vitest
`npm test` (in `service_frontend`)
```
Test Files  120 passed (120)
      Tests  931 passed (931)
   Duration  41.36s
```
BR-specific files (subset, for attribution):
```
✓ services/business-requirement-service.mock.test.ts (6 tests)
✓ app/(protected)/ideation/business-requirements/use-br-list-config.test.tsx (4 tests)
```

---

## 2. Pre-existing / out-of-scope failure (NOT an S2 regression)

`tests/test_cluster_d_slice3_migration.py::test_module_migration_revision_ids_fit_alembic_column`
```
E  AssertionError: Module migration revision ids exceed Alembic's VARCHAR(32) version
   column (un-runnable on Postgres):
   [('ideation','0003_ideation_idea_submitter_name.py','0003_ideation_idea_submitter_name',33),
    ('ideation','0004_ideation_idea_segregated_fields.py','0004_ideation_idea_segregated_fields',36)]
```
- Offenders are **Phase-A** ideation migration ids (`0003` = 33 chars, `0004` = 36 chars),
  which predate this slice.
- **The new S2 migration id `0008_ideation_business_reqs` is 27 chars (≤ 32) and is NOT
  in the offender list** - S2 introduced no new offender. Verified independently:
  `printf "0008_ideation_business_reqs" | wc -c → 27`.
- This is a genuine deploy-risk that **Phase A owns** (a >32-char id breaks `alembic upgrade`
  on real Postgres). Reported here for the record; correctly excluded from S2's verdict.

---

## 3. AC-by-AC verdict (AC-BI-15..19)

| AC | Title | Verdict | Evidence |
|----|-------|---------|----------|
| **AC-BI-15** | BR table + lifecycle | **PASS** | `business_requirements` model has `id, tenant_id, product_id, status_id, template_key, template_version, answers_json, created_by/updated_by`, `UTCDateTime` timestamps. Cross-schema refs to core are **plain indexed columns, no DB FK** (BL-030); intra-schema FKs kept (join→ideas/BRs, version→template). `register_status_entity("ideation_business_requirement")` at boot; unscoped, tenant-owned; seeded graph `draft→grilling→ready→in_fr→delivered→archived`. Tests: `test_create_br_stamps_active_template_and_starts_draft`, `test_status_engine_lifecycle_edges` (defined edge 200; undefined edge 409; unknown key 422). |
| **AC-BI-16** | versioned BR template | **PASS** | Template is a `form_engine` `FormDocument` with the 6 spec'd fields. BR stamps the active version at create. A template edit mints v2 + moves the active label; a v1 BR still renders + **validates against v1**. Tests: `test_create_br_validates_answers_against_stamped_version` (missing `success_metric` → 422 per-field), `test_historical_br_renders_against_its_stamped_version`, `test_versions_tab_flags_stamped`, **+ new** `test_update_historical_br_validates_against_stamped_version` (a v1 BR is editable WITHOUT the field v2 later made required - proves the WRITE path resolves the stamped, not active, doc). |
| **AC-BI-17** | Idea ↔ BR many-many | **PASS** | `idea_business_requirements` join; a BR absorbs many ideas, an idea feeds many BRs; `ideaCount` on the list. Cross-product refused (422); unknown idea refused (422); link validated on write + resolved tenant-scoped on read. Tests: `test_link_ideas_many_many_and_lineage`, `test_link_cross_product_idea_refused`, `test_link_unknown_idea_refused`, **+ new** `test_link_cross_tenant_idea_refused` (a planted foreign-tenant idea sharing the SAME product id is refused 422 and nothing links - the polymorphic-target rule). |
| **AC-BI-18** | BR Resource surfaces | **PASS** | `/ideation/business-requirements` is a config-driven `ResourceList` (search, Active\|Archived segments, Export/Columns, status badge, selection, server paginate). Detail is a `ResourceForm` with tabs **Details·Grill·Ideas·Trace·Versions**, global Edit toggle, dirty-guard, record-nav. **Details renders `answers_json` through the form-engine `FormRenderer`** against the STAMPED `templateDoc` - no bespoke BR form. Verified LIVE at 1280px + 375px (§4). Vitest: mock-service + list-config tests green. |
| **AC-BI-19** | BR permissions + promote gate | **PARTIAL** (bullets 1 & 4 PASS; bullets 2 & 3 **DEFERRED to S4**) | See §3a below. |

### 3a. AC-BI-19 detail - the honest state of the promote gate

- **Bullet 1 (CSV declares `.read`/`.manage`/`.promote` separately):** **PASS** - the module
  CSV declares all three as distinct actions.
- **Bullet 4 (grant sweep for existing tenants):** **PASS** - `scripts/grant_ideation_br_perms.py`
  re-syncs the catalog + appends the module perms to each active tenant's Admin role; install
  also grants them. `test_manage_grants_imply_read` confirms the seeded Admin holds all three;
  live `/auth/me` on :8002 returned `['…manage','…promote','…read']`.
- **Bullet 2 (`.manage`-not-`.promote` user: promote absent FE + refused 403 BE)** and
  **Bullet 3 (promote enforced via `transition_roles`):** **NOT ENFORCED in S2.**
  - There is **no promote endpoint** in S2. The `br-tr-promote` (`draft → ready`) edge is
    seeded with **empty `transition_roles`** (unrestricted at the engine), and the generic
    `POST /{id}/status` route is gated `.manage` only.
  - **Consequence:** a `.manage`-only actor **can currently fire `draft → ready`** through
    `/status`. Pinned by the new `test_manage_user_can_currently_fire_promote_edge_S2_gap`
    (asserts the current 200-to-`ready` behaviour so S4 provably flips it).
  - This matches the code's own comments (`statuses.py`: *"the router's `.promote` permission
    is the real boundary - S4 wires the promote UI onto this edge"*) and `grep` confirms
    **`.promote` is referenced only in docstrings, by no endpoint**. AC-BI-34 (the promote
    Gate-0) is a **Slice 4** item.
  - **Assessment:** acceptable as a documented deferral to S4, **but a latent hole today** -
    until S4 lands, `.promote` is decorative and any `.manage` user can promote. S4 must
    either (a) route promote through a `.promote`-gated action, or (b) assign `transition_roles`
    to `br-tr-promote` + block that edge from the generic `.manage` `/status` mover.

New coverage also added: `test_read_only_user_refused_on_status_and_link` (a `.read`-only user
is refused **403** on `/status`, `/ideas` link, and PATCH - the read↔manage boundary holds).

---

## 4. Live verification - the Definition-of-Done gate (real data, real clicks)

**Stack:** backend :8002 (`foundryx_ideation_verify`, ideation module installed ACTIVE for the
default tenant during this pass) · frontend :3001 restarted with
`NEXT_PUBLIC_BACKEND_API_URL=http://localhost:8002 BACKEND_API_URL=http://localhost:8002`.
**Seeded real data:** created a product + a BR via the :8002 API
(`Order export for CS 090654`, full 6-field `answers_json`, stamped `templateVersion=1`).
Driven headless via `playwright-core` (Chrome-for-Testing), navigating **by clicks**.

| Check | Result |
|-------|--------|
| Login through the real signin form (`input[name=email]`) → app | PASS (redirect `/signin` → `/`) |
| **Browser hits :8002, not :8001** | PASS - observed response `http://localhost:8002/ideation/business-requirements?filter=all` |
| Click sidebar **Ideation → Business requirements** → list route | PASS (`/ideation/business-requirements`) |
| **BR list renders on the Resource shell with the REAL row** (not empty-state) | PASS - row `Order export for CS 090654`, Product `Verify CRM 090654`, Status `Draft`, Ideas `0`, pagination `1-1 of 1`, Active\|Archived segments, Export/Columns/New buttons |
| Open BR detail by clicking the row → tabbed `ResourceForm` | PASS - tabs Details·Grill·Ideas·Trace·Versions all present; Edit toggle; `Draft · Verify CRM 090654` subtitle |
| **Details tab renders `answers_json` via FormRenderer against the STAMPED template** | PASS - all 6 stamped fields render with their real values (Problem statement / Business goal / Stakeholders / Success metric / Scope / Constraints) |
| **Grill** tab → placeholder | PASS - "Available after grilling." |
| **Trace** tab → placeholder | PASS - "Available after grilling." |
| No horizontal scroll @ **1280px** (list + detail) | PASS (`scrollWidth ≤ clientWidth`) |
| No horizontal scroll @ **375px** (list + detail) | PASS - tab strip scrolls, form stacks to one column |

**Screenshots captured** (scratchpad): `br-list-1280.png`, `br-detail-1280.png`,
`br-detail-375.png`, `br-list-375.png`, `br-grill-1280.png`. Visual review confirms the
Resource-shell list and the tabbed detail with the form-engine-rendered answers at both sizes.

---

## 5. Coverage gaps closed by this QA pass

Added `service_backend/tests/test_ideation_br_coverage.py` (4 tests, all green):
1. `test_update_historical_br_validates_against_stamped_version` - AC-BI-16 write-path proof
   (edit a v1 BR after the template moved to a v2 with a new required field; save succeeds
   against v1).
2. `test_link_cross_tenant_idea_refused` - AC-BI-17 cross-TENANT refusal (the existing suite
   only covered cross-product + unknown).
3. `test_read_only_user_refused_on_status_and_link` - AC-BI-19 read↔manage boundary on every
   mutating route.
4. `test_manage_user_can_currently_fire_promote_edge_S2_gap` - pins the AC-BI-19 promote-gate
   deferral so S4 provably closes it.

---

## 6. Notes, risks, and handoffs

- **AC-BI-19 promote gate (S4 must-do):** `.promote` is currently unenforced; a `.manage` user
  can reach `ready`. Close in S4 (see §3a). This is the one genuine correctness gap in S2.
- **Phase-A migration-id guard failure (Phase-A must-do):** ids `0003`/`0004` exceed
  VARCHAR(32) and would break a real Postgres `alembic upgrade`. Not S2's; flag to Phase A.
- **`grant_ideation_br_perms.py` is a script, not a migration** - an operator must run it once
  after deploy for tenants that already had ideation installed (DoD #4). Fresh installs get the
  grant automatically. Worth a note in the deploy runbook.
- **App-code untouched:** this QA pass added ONLY test files + this report - no application code
  was modified.
- **Verify-stack state left running:** :8002 backend + :3001 frontend (repointed at :8002) were
  left up; the ideation module is now ACTIVE on the verify DB's default tenant.
```

## Files (absolute)
- Added tests: /Users/tehjayson/Documents/foundryx/foundryx-shared-service/.claude/worktrees/ideation-phase-b/service_backend/tests/test_ideation_br_coverage.py
- This report: /Users/tehjayson/Documents/foundryx/foundryx-shared-service/.claude/worktrees/ideation-phase-b/documentation/plans/ideation/ideation-phase-b-i-s2-test-report.md
```
