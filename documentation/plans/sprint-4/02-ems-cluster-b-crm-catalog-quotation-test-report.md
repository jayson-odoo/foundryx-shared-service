# Sprint 3 · Plan 12 — EMS Cluster B · Test Execution Report

**Plan:** `02-ems-cluster-b-crm-catalog-quotation.md` · **AC:** `02-...-acceptance-criteria.md`
**Branch:** `sprint-3/12-ems-cluster-b` (worktree `.claude/worktrees/cluster-b`, served :3003/:8003)
**Built in 3 slices**, each: frontend-first UI/UX verify → backend → TDD → E2E → code review.

Format per the orchestration guide: User Story / Scenario / Precondition / Steps / Expected / Actual / Remarks.

---

## Suites (final)

| Suite | Result |
|-------|--------|
| `tests/test_ems_cluster_b.py` (slice 1 CRM) | **12 passed** |
| `tests/test_ems_catalog.py` (slice 2 catalog) | **10 passed** |
| `tests/test_ems_quotations.py` (slice 3 quotations + FileLink seam) | **9 passed** |
| `tests/test_ems_spine.py` (plan-11 spine, regression) | **14 passed** |
| `tests/test_status_engine.py`, `test_import_engine.py` (regression) | green |
| Frontend eslint (all `app/(protected)/ems`) | clean |
| E2E `e2e/ems-cluster-b.spec.ts` (6 specs, desktop + mobile) | **6 passed** |

---

## Slice 1 — CRM (Clients + Leads)

- **US:** As an admin I manage B2B clients and sales leads, and win a lead into an event.
- **Scenario (E2E ①):** create Client → create Lead inline-quick-creating a Client → move New→Qualified → "Create event" (Won convert) → lands on the new event.
  - **Precondition:** tenant with `ems` installed; an event template exists.
  - **Steps:** real clicks through Clients → Leads → row "…" → convert dialog.
  - **Expected:** lead reaches Won (terminal), a Project spawns with `client_id`/`lead_id` back-linked + its own copied eligibility graph; double-convert → 409.
  - **Actual:** ✅ verified (E2E + `test_lead_convert_spawns_and_links_project`, API live-check: lead.status=won, project.client_id==lead.client_id, project.lead_id==lead.id, 5 scoped statuses copied, re-convert 409).
- **Scenario (E2E ②, mobile 375px):** Clients + Leads lists render with no horizontal overflow. **Actual:** ✅.
- **AC covered:** AC-12-02/03/04, 09 (client/lead triggerable), 11 (tenant isolation), 12 (import round-trip + foreign-client reject), 14 (quick-create), 15 (graph-driven Won), 18/19/20.

## Slice 2 — Product catalog (categories tree + master)

- **US:** As an admin I organize a product catalog by a category tree and maintain products with behavioral kinds.
- **Scenario (E2E ③):** create a root category + sub-category → create a product in it (kind Admission) → toggle active off.
  - **Expected:** tree shows root → child (parent auto-expands on add); product created with kind + category; row toggle flips Active↔Inactive.
  - **Actual:** ✅ (E2E + `test_category_tree_crud_and_guards`, `test_product_crud_kind_and_category_validation`).
- **Guards verified:** reparent cycle/self-parent → 422; delete with children/products → 409; move-to-top-level (sentinel→null); non-numeric import price flagged at Test; foreign category import rejected.
- **Scenario (E2E ④, mobile):** Products + Categories render with no horizontal overflow. **Actual:** ✅.
- **Name-collision lesson:** core already owns `products.*` → product perms namespaced **`ems_products.*`** (category perms `product_categories.*` are free). Consistent end-to-end (router/CSV/menu/RequirePermission/importer/createPermission).
- **AC covered:** AC-12-05, 09, 11, 12, 17, 19, 20, 24.

## Slice 3 — Quotations + document attach

- **US:** As an admin I raise a B2B quote against a lead, build line items with a derived total, attach a document, and revise it.
- **Scenario (E2E ⑤):** New quotation (raised against a lead, autofills client) → Edit → Add line referencing a product (autofills unit price) → qty 2 → Save → total = 100 → Revise.
  - **Expected:** lines saved with server-recomputed amount; header total derived; revise clones lines into a new Draft v2 with `parent_quotation_id` lineage, original untouched.
  - **Actual:** ✅ (E2E + `test_quotation_create_with_lines_derives_total`, `test_quotation_revise_clones_with_lineage`, `test_quotation_update_replaces_lines`, `test_quotation_status_transitions`).
- **FileLink attach seam (AC-12-08):** the core `/documents/file-links` API already existed (ShareService, tenant-scoped) — **consumed, not rebuilt**. Verified for `entity_type='quotation'`: link → list → detach, foreign/bogus file rejected (`test_quotation_filelink_attach_list_detach`). Frontend AttachPanel + Drive folder picker on the Documents tab.
- **Validation:** ≥1 of lead/project (422), client required, line product tenant-scoped (incl. soft-deleted excluded), quotation `get()` excludes trashed.
- **Scenario (E2E ⑥, mobile):** Quotations list renders with no horizontal overflow. **Actual:** ✅.
- **AC covered:** AC-12-06, 07, 08, 09 (quotation triggerable), 11, 13, 16 (RepeaterField-style line editor), 19, 20.

---

## Code review
Each slice reviewed by an independent reviewer before commit; verdicts APPROVE / APPROVE-WITH-NITS with all blockers + majors + actionable minors fixed:
- Slice 1: migration auto-index-name blocker fixed; lead-importer clientId tenant-validation (major) added; convert-from-terminal clean 409.
- Slice 2: category move-to-top-level sentinel (major) added; importer numeric validator.
- Slice 3: `get()` is_deleted filter + line product soft-delete exclusion.

## Environment notes
- Worktree served on **:3003 / :8003** (two other developers active on 3001/8001 + 3002/8002). Backend CORS extended to `:3003` + `*.localhost:3003` via env (not committed config) — prod ports already covered.
- DB = shared local Postgres; new `app_ems` tables + namespaced perms applied surgically (no full reseed, to avoid clobbering siblings' module rows).

## Definition of Done
All AC-12-* MET across the 3 slices · backend + E2E suites green · per-slice reviewer approval with fixes applied · merged-ready on `sprint-3/12-ems-cluster-b`.
