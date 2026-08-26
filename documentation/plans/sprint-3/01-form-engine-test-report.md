# Sprint 3 · Plan 01 - Form Builder Engine - Test Execution Report (Slice 1)

**Branch:** `sprint-3/01-form-engine`
**Date:** 2026-06-10
**Scope:** Slice 1 - builder + publish + internal fill + submissions + scoped statuses. (Slice 2 - public surface + `form.submitted` trigger - is a separate branch.)

## Summary

| Layer | Suite | Result |
|---|---|---|
| Backend | `pytest -q` (full) | **570 passed** |
| - form engine | `test_form_engine.py` | 20 passed |
| - publish gate | `test_form_doc_validate.py` | 27 passed |
| - submit pipeline | `test_form_submit_validation.py` | 27 passed |
| - computed parser | `test_form_computed.py` | 64 passed |
| - scoped statuses | `test_scoped_status.py` | 12 passed |
| - doc/parity | `test_form_parity.py` | 1 passed |
| - status engine (regression) | `test_status_engine.py` | green (tenant lifecycle untouched) |
| Frontend | `vitest run` (full) | **472 passed** (55 files) |
| - builder | `components/platform/form-builder/*` | 29 passed |
| - renderer + validate | `form-renderer/*` + `lib/form-validate.test.ts` | 35 passed |
| E2E | `e2e/forms.spec.ts` (real clicks, live stack) | **4 passed** |
| E2E (regression) | `e2e/status-engine.spec.ts` | 4 passed |

Type-check (`tsc --noEmit`) and ESLint clean. Live-verified manually on the `default` tenant at desktop (~1280px) and mobile (~375px).

## E2E journeys (Playwright, real clicks, dedicated tenant `e2e-forms-<ts>`)

| # | User story | Steps | Expected | Actual |
|---|---|---|---|---|
| ① | Build + publish | New form → click-to-add text/yesno/number×2/computed fields → set keys/required → add a "visible when Workshop? is true" condition on Seats → add page 2 + required Abstract → name in Settings → Save → Publish | Form created (UUID route), validate gate passes, **Published · v1** badge | ✅ |
| ② | Internal fill | Open published fill page → Seats hidden until Workshop?=Yes → computed Revenue updates live (10×25=250) → Next blocked until required Full name filled → page 2 → Submit | Conditional show/hide live, computed live, per-page validation blocks, success state, row lands in Submissions tab as **Submitted** | ✅ |
| ③ | Scoped pipeline | Flow tab (form's OWN graph: seeded Draft + Submitted) → Edit → Add "Under Review" → drag Submitted→Under Review edge "Start review" → Submissions → open row → graph-driven **Start review** button | New status + edge persist on the scoped machine; transition fires; StatusBadge → Under Review | ✅ |
| ④ | Versioning (D9) | Edit draft (rename Full name → Speaker name) → Save → **Unpublished changes** → Republish → v2 → Versions tab lists v1+v2 → open the old submission | v2 created; version history paginated; the pinned submission **still renders v1** ("Full name", not "Speaker name") with its stored answer | ✅ |

## Verifications against the plan

- **Scoped status engine (D4)** - `statuses.scope_id` migration applied on Postgres; the full pre-existing status-engine suite stays green (tenant lifecycle untouched, the load-bearing requirement). `form_submission` registered as the first scoped entity; its graph is materialized at form creation (Draft→Submitted) and edits/transitions are scope-guarded (a cross-form transition is refused - `test_form_engine` + `test_scoped_status`). Scoped entities are hidden from the global Statuses list (their graph lives on the form's Flow tab).
- **Publish gate (D9)** - `validate_form_doc` 422 `{problems}` covers dup/missing keys, empty pages, choice options, computed forward/non-numeric refs, condition forward-refs, repeater sub-keys, bad patterns. Mirrored front (`lib/form-doc.ts`) + back, pinned by `test_form_parity`.
- **Submit pipeline (D14)** - hidden fields dropped, required-if-visible, options membership, computed recomputed server-side (client value ignored), repeater row min/max + per-row errors, address whitelist; 422 `{fieldErrors}` per-field map.
- **Versioning (D9)** - fill serves only the published version; preview renders the draft; submissions pin `version_id` and re-render faithfully forever.
- **Permissions (D19)** - `forms.read/manage`, `submissions.read/manage` seeded to tenant Admin; fill + submit gated by `get_current_user` only (any authed user).
- **Computed (D7)** - arithmetic-only own parser (no eval); live client recompute + authoritative server recompute.

## Bugs found + fixed during verification

1. **Mobile layout blow-out (responsive mandate)** - the 5-tab ResourceForm strip's min-content stretched the whole page past 375px because the demo1 `wrapper` flex item lacked `min-w-0`. Fixed at the layout root (`min-w-0` on the wrapper) + a scrollable `TabsList` - benefits every multi-tab surface, not just forms. Re-verified desktop unaffected.
2. **New scoped-graph node off-screen** - React Flow `fitView` only fires at mount, so a freshly-added status (grid-positioned, outside the initial fit) landed off-canvas and its drag handle was unreachable. Added a re-fit on node-count change in `EntityFlow` (position-only drags don't trigger it). Improves the status canvas for every entity.

## Known follow-ups (backlog)

BL-086 (payment field), BL-087 (entity-sourced options), BL-088 (`entity.create` action), BL-089 (repeater sub-field conditions), BL-090 (anonymous browser-local autosave). Slice 2 (public surface + `form.submitted` trigger) is the next branch.

## Code review (high-effort, 7 finder angles + verify)

Ran the multi-agent code-review gate over `main...HEAD`. Findings triaged → **6 fixed** (commit `4dd8107`), the rest deferred with rationale (BL-091).

**Fixed:**
1. **Hidden-field-drives-visibility (D14 violation)** - `validate_submission` derived the visible set from the RAW client answer map, so a curl client could force-feed a hidden field's value to flip a downstream field's visibility/computed. Now facts accumulate from the cleaned (visible) set in document order (refs are backward-only, so one pass is exact); frontend `resolveVisible()` mirrors it and the renderer + `validatePage`/`validateAll`/`visibleAnswers` all route through it (no client/server visible-set drift → no silently-dropped submit payload).
2. **Non-finite numbers** - `inf`/`nan` (from `1e400` or arithmetic overflow) serialize as invalid JSON and 500 the insert; `_to_number` + computed recompute now fail closed to None.
3. **Choice coercion** - `select`/`radio` answers stored as the string option value (a numeric `0` vs option `"0"` mismatched); `multiselect`/`checkboxes` coerced + client now rejects duplicate selections (backend parity).
4. **`submitted_at` on a stranded Draft** - stamped only when the Draft→Submitted transition actually fires (a tenant-restricted Submit edge no longer leaves a record falsely "submitted" at the editable initial status).
5. **`_version_number` unscoped** - now tenant-scoped via the join to forms (polymorphic-target_id rule).
6. (verifier-confirmed no regressions in the unscoped tenant-lifecycle status engine - the scoped branch is uniformly gated behind `entity.scoped`.)

**Deferred (BL-091, all low-risk / non-blocking):** unique-constraint NULL-distinctness loses the DB-level dup-key backstop for tenant-forked unscoped statuses (app-side `get_by_key` still guards; concurrency-only, single-admin UI); `form-service.mock.ts` is orphaned dead code; `rule-eval.ts`/`computed-expr.ts` mirror the backend with no parity test pinning them; `_fireable_map` could be generalized into `fireable_edge_ids` (force-return flag) instead of a per-row loop; the scoped read path routes through `resolve_tier` (coincidentally correct today); a single signature tap stores a blank-but-non-empty PNG (passes required); `SubmitRequest.answers` is uncapped and the file-descriptor shape is client-trusted - both folded into the slice-2 public-surface hardening (uploads + anonymous body caps live there).

## Residue note

E2E provisions `e2e-forms-<timestamp>` tenants that are never purged (BL-035) - clean `e2e-%` tenants from the local DB if the tenants list spec starts failing on page-1 crowding (methodology §7).
