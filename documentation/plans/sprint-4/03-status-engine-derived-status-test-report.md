# Sprint 4 · Plan 03 — Derived / Computed Status · Test Execution Report

**Branch:** `sprint-4/03-derived-status` · **Date:** 2026-06-18
**Built in 3 slices** (frontend-first where UI exists → backend → TDD → E2E → code review), all on this branch.

## Result summary

| Gate | Result |
|------|--------|
| Backend unit/integration (`pytest -q`) | **835 passed**, 0 failed (full suite, slices 1–3) |
| `tests/test_status_engine.py` (derived focus) | **39 passed** (incl. 22 new derived-status tests) |
| Frontend unit (`vitest run`) | **595 passed**, 2 pre-existing failures (see below) |
| `status-engine.test.tsx` | **13 passed** (incl. 2 new auto-edge tests) |
| TypeScript (`tsc --noEmit`) | clean |
| ESLint (changed files) | clean |
| Alembic migration `a7b8c9d0e1f2` | applied to live Postgres; additive `trigger_mode` column + index |
| E2E (`e2e/derived-status.spec.ts`, live stack) | **1 passed** (8.6s) |
| Live UX verification (Playwright MCP, real clicks) | desktop 1280px + mobile 375px — satisfactory |
| Code review (high-effort, 8 finder angles + verify) | 3 findings actioned, rest verified non-issues |

**Pre-existing failures (NOT introduced here, confirmed by stashing the branch diff):**
`app/(auth)/signin/page.test.tsx › renders the FoundryX heading` and
`services/import-service.test.ts › commit() POSTs to the commit endpoint` — both in files this plan never touches; fail identically on the branch base.

## AC coverage (see `03-...-acceptance-criteria.md`)

| AC | Verified by |
|----|-------------|
| AC-03-01 trigger_mode column/index/default | migration offline-SQL + `test_trigger_mode_defaults_manual` |
| AC-03-02 auto requires conditions | `test_auto_edge_requires_conditions`, `test_update_to_auto_validates_resulting_state` |
| AC-03-03 auto forbids roles | `test_auto_edge_forbids_roles` |
| AC-03-04 auto excluded from user surfaces | `test_auto_edges_excluded_from_user_surfaces` |
| AC-03-05 first passing fires / none = no move | `test_reevaluate_fires_first_passing_auto_edge` |
| AC-03-06 cascade to fixpoint / no oscillation | `test_reevaluate_cascades_to_fixpoint`, `test_reevaluate_terminates_on_cycle` |
| AC-03-07 sort_order first-wins | `test_reevaluate_first_wins_by_sort_order` |
| AC-03-08 manual override coexists | `test_manual_override_edge_to_derived_state_coexists` |
| AC-03-09 stable state not pulled back | `test_reevaluate_stable_state_not_pulled_back` |
| AC-03-10 registry idempotent | covered via `_wire_line_derivation` re-register no-op |
| AC-03-11 child event re-evaluates owner | `test_child_event_reevaluates_owner` |
| AC-03-12 self-trigger | `test_self_trigger_reevaluates_on_update` |
| AC-03-13 aggregate facts authorable + tenant-scoped | `test_aggregate_fact_registered_and_authorable`, `test_aggregate_facts_are_tenant_scoped` |
| AC-03-14 failure-isolated, never 500s child write | `test_broken_derivation_never_breaks_the_child_write` |
| AC-03-15 fail-closed on missing fact | `test_fail_closed_on_missing_aggregate_fact` |
| AC-03-16 loop guard / no self re-entry | `test_derived_reeval_does_not_self_reenter` |
| AC-03-17 scoped graph derivation | `test_scoped_graph_derivation` |
| AC-03-18 fork/copy carries trigger_mode | `test_fork_carries_trigger_mode` + `copy_scope`/`materialize_scope` updates |
| AC-03-19 time-based sweep | `test_time_based_sweep_advances_overdue` |
| AC-03-20 edge Trigger toggle | `status-engine.test.tsx` auto tests + E2E + MCP |
| AC-03-21 canvas auto-edge distinct (⚡/dashed) | E2E `⚡ Submit` assertion + MCP screenshot |
| AC-03-22 derived read-only (no manual button) | backend exclusion (AC-04) drives UI; verified MCP |
| AC-03-23 end-to-end auto-advance | backend `test_child_event_reevaluates_owner` (UI auto-advance needs a domain consumer — D/F) |
| AC-03-24 no new tables | only `trigger_mode` column added |
| AC-03-25 existing status suite green | full suite 835 passed |
| AC-03-26 eventual (after-commit drain) | by design; `_on_event` rides `_notify_subscribers` |
| AC-03-27 responsive 375/1280 | MCP screenshots both viewports |

## Code review (high effort) — disposition

- **Fixed:** `reevaluate` now skips an auto edge with empty `conditions_json` (fail-safe against a DB-planted unconditioned auto edge).
- **Fixed:** drawer no longer clears `roleIds` on manual→auto toggle — roles are preserved across a round-trip; save sends `[]` for auto via `effectiveRoles`.
- **Fixed (convention):** foolproof-UI mandate — concise `Manual`/`Automatic` toggle labels; dropped the procedural helper sentence for auto edges.
- **Verified non-issues:** scheduler "stale records after rollback" (SQLAlchemy expires session objects on commit/rollback → re-loaded fresh); FE/BE condition checks are equivalent; single-edge E2E `⚡`-prefix selector is unambiguous.

## Notes / follow-ups
- A true UI auto-advance demo (child change → owner advances on screen) needs a domain consumer with aggregate facts — lands with Cluster D (participant Checked-in) / Cluster F (invoice Paid). Engine + synthetic-entity proof ship here.
- Celery beat `status.reevaluate_time_based` (60s) wired; eager dev has no beat — call `reevaluate_time_based(db)` directly (as the test does).
- Backlog (from plan): burst coalescing per (owner, tick); two-tier fork parity for tenant-authored auto edges; "why did this auto-fire?" explainer.

---

# Slices 4–6 addendum (grilled + built 2026-06-19)

Three follow-on slices layered on the merged engine, all on `sprint-4/03-derived-status`.

## Slice 4 — Configurable aggregate whitelist
- `AggregatableRelation` + `AggColumn` (`app/rule_engine/aggregates.py`) auto-generate count + column×op rule facts AND the child→owner `DerivedTrigger` from ONE declaration; per-column op whitelist; `StatusEntity.aggregatable_relations`.
- EMS project rides it: `record.participants.count` + the participant→project re-derive trigger (hand-wired trigger removed).
- Tests: `test_status_engine` expander units (keys/labels/types, op-whitelist + missing-column `ValueError`, registration wires facts+trigger); `test_ems_spine::test_event_auto_confirms_on_participant_count` (add 2 participants → event auto-advances). **AC-03-28..37.**

## Slice 5 — EMS Event Details edit
- Backend: 3 date columns `UTCDateTime → Date` (calendar dates) + ems migration `0002`; `ProjectOut` grown; `ProjectUpdate` + `ProjectService.update` (PATCH-merge, ordering 422, immutables ignored); `PATCH /ems/projects/{id}`; export start/end.
- Frontend: Details tab on the event detail (fields + date inputs) under the one Edit toggle (combined save w/ flow layout); Events list Start/End columns + export.
- `ProjectService.update` emits `entity.updated` → a field-vs-fixed auto edge fires ON SAVE (event-driven). Same for `ProfileService.update`.
- Tests: `test_ems_spine` update merge/date-only/ordering-422/immutable + `test_event_auto_advances_on_date_field_save`. **AC-03-38..45.**

## Slice 6 — Relative-to-now date conditions + admin date-simulation
- `app/clock.py` injectable clock (contextvar); `infer_facts` auto-generates `Days since`/`Days until <field>` NUMBER facts per date field (read the clock) → time windows authored with the existing `>/≥/</≤` operators (no new operators, no parity). `eventEnded` retired.
- `simulate_entity_sweep` + `POST /status-entities/{entity}/simulate` (dry-run = rollback/no side-effects, apply = commit; tenant-scoped, `statuses.manage`); `hasTimeAutoEdges` on the wire.
- Frontend: `SimulateDateDialog` ("Simulate date" on the status entity detail, gated by `hasTimeAutoEdges`) — date picker → Preview (dry-run table) → Apply.
- Tests: `test_ems_spine` clock-reset, day-count sweep, simulate dry-run/apply/perm; `simulate-date-dialog.test.tsx` (3). **AC-03-46..54.**

## Results
- **Backend: 850 passed** (full suite, `python -m pytest -q`).
- **Frontend unit:** `simulate-date-dialog.test.tsx` (3) green; builder/renderer suites unaffected; `npm run build` clean.
- **E2E `e2e/derived-status.spec.ts`: 3 passed** (real clicks, dedicated tenant w/ EMS installed):
  1. auto-edge authoring (Slice 1–3, unchanged);
  2. **Event Details edit** — Edit → set Brief + (setup) date → Save → reload persists → Events list shows the End-date cell (AC-03-44);
  3. **Simulate date** — Actions → Simulate date → as-of 2027-01-15 → Preview lists the event (Draft → Active) → Apply → the event status advances (AC-03-54).
- **Live (Playwright MCP) during build:** bulk per-target transitions; Events Status column; participant-count auto-cascade; date-field-save auto-advance on the user's real project; simulate dialog Preview.

## AC coverage (Slices 4–6)
| AC | Evidence |
|----|----------|
| AC-03-28..32,34 aggregate relation → facts + trigger, validation | `test_status_engine` expander + registration tests |
| AC-03-33 aggregate tenant-scoped | slice-2 `test_aggregate_facts_are_tenant_scoped` (same `aggregate_fact`) |
| AC-03-35 EMS participant-count cascade | `test_event_auto_confirms_on_participant_count` + MCP |
| AC-03-36 aggregates = plain number facts (no parity) | `types/rules.ts` unchanged |
| AC-03-37 / AC-03-44 event-edit E2E | `derived-status.spec.ts` test ② |
| AC-03-38..41 project update + date-only + ordering 422 | `test_ems_spine` update tests |
| AC-03-42/43 Details tab + list columns | E2E ② + MCP |
| AC-03-45 date-based derived usable | `test_event_auto_advances_on_date_field_save` |
| AC-03-46 clock provider | `test_clock_override_resets` |
| AC-03-47/48 day-count facts + numeric ops | `/rule-facts` (MCP) + sweep test |
| AC-03-49 eventEnded retired | day-count edge in tests; grep-clean |
| AC-03-50/51/52 simulate dry-run/apply/perm | `test_simulate_dry_run_then_apply`, `test_simulate_requires_manage_perm` |
| AC-03-53 Simulate-date UI | `simulate-date-dialog.test.tsx` + MCP |
| AC-03-54 simulate E2E | `derived-status.spec.ts` test ③ |

## Backlog logged
- **BL-112** filtered/scoped aggregates (`aggregate_fact(where=)` interim).
- **BL-113** relation sub-grouping in the RuleBuilder fact picker.
- Persisted/global clock time-travel — rejected; per-call `as_of` only.
