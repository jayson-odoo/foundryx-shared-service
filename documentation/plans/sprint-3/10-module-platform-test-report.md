# Sprint 3 · Plan 10 - Module Platform v2 · Test Execution Report

**Branch:** `sprint-3/10-module-platform` · **Date:** 2026-06-16

Validates `10-module-platform-acceptance-criteria.md` (AC-10-01 … AC-10-20).

---

## Summary

| Layer | Result |
|-------|--------|
| Backend (`tests/test_module_platform.py`) | **13 passed** |
| Backend full suite (regression) | **796 passed** (0 failures) |
| Per-module Alembic on LIVE Postgres | **verified** (omnichannel stamped, no DDL) |
| Frontend (`module-card.test.tsx`) | 7 passed; lint clean |

---

## Scope delivered (slices 1-3, the F9 contract + F4 enablers)

- **Slice 1 - per-module Alembic (D3, closes BL-029).** `app/module_platform/migrations.py`
  orchestrator: version-row → upgrade; legacy tables → **stamp** (no DDL); fresh → upgrade.
  `modules/omnichannel/alembic/` (env + `0001_omni_baseline`). Postgres-only (SQLite test
  suite keeps `create_all`). **Live-verified**: omnichannel had legacy tables → stamped to
  `0001_omni_baseline` in `app_omnichannel.alembic_version_omnichannel`, data untouched.
  ems (plan 11) starts clean (fresh → upgrade). **AC-10-03, AC-10-18.**
- **Slice 2 - dependency system (D4).** `dependencies.py`: `resolve_install_order` (topo +
  cycle → `DependencyError`), `version_satisfies`, `check_requires` (active/inactive/missing +
  cascade plan), `check_dependents` (reverse guard). App Store: requires-guard + cascade-with-
  consent on install; reverse-dep guard on **deactivate AND uninstall**. **AC-10-02, -04, -10, -16.**
- **Slice 3 - capability registry + soft refs + active_modules (D5/D6/D2).**
  `capabilities.py` (`register_capability`/`resolve_capability`, integer-major, tenant-active
  gated, duplicate-boot → `DuplicateCapability`); `soft_refs.py` (`SoftRef`, `resolve_soft_ref`,
  `validate_soft_ref` - via a provider `<entity>.resolve` capability, orphan → None);
  `active.py` (`active_modules` + `is_visible`). omnichannel registers `messaging.send@1` at
  boot; loader registers capabilities + isolates errored modules (D8). `active_modules` filter
  applied to terminology catalog/map + the import-engine entity guard. **AC-10-01, -05, -06, -07,
  -08, -09, -11.**

### Backend tests (`tests/test_module_platform.py`, 13)
topo order + cycle · version_satisfies · active_modules + is_visible · resolve_capability
(active→handler, inactive/wrong-version/absent→None, per tenant) · duplicate-boot error ·
soft-ref resolve + validate + orphan→None · check_requires (active/missing/cascade) ·
**reverse-dep guard blocks deactivate AND uninstall** · terminology active-module filter.

---

## Deferred (documented refinements - NOT F4-blocking)

The F9 *contract* (deps, capabilities, soft-refs, per-module Alembic, active_modules) is
complete and is what plan 11 (EMS) consumes. Two slice-4 items are deferred as pure-UX /
non-blocking refinement, with their user-facing value delivered in a lighter form:

- **AC-10-12/13 - App Store on the full Resource shell (tabbed detail form + generic
  card/grid display mode).** The existing card-grid storefront already delivers the storefront
  UX; the mechanical migration to the config-driven shell is deferred. **Value delivered now**:
  the `StoreModuleOut` API surfaces `requires`/`optional`/`provides`/`errored`/`availabilityOk`,
  and the `ModuleCard` renders dependency chips ("Requires X" / "Enhances Y"), an errored
  notice (install disabled), and a "needs required modules" warning (**AC-10-14**).
- **AC-10-17 - consumer-module E2E + the in-tree demo module.** The optional-dep / capability-
  resolve / self-disable / reverse-dep mechanics are proven by the 13 unit tests (deactivate
  omnichannel → `resolve_capability` returns None; synthetic dependent blocks removal). The
  Playwright journey + a permanent in-tree demo module are deferred (a demo module would also
  pollute the prod catalog) - to be added with the slice-4 shell migration.

## Verdict
Slices 1-3 (the F9 backend contract) **MET + green + live-verified**; BL-029 closed. Slice 4
reduced to API + card-level surfacing; full Resource-shell migration + consumer E2E logged as
follow-ups. **F4 (plan 11) is unblocked**: per-module Alembic, `optional`-deps, capability
`provides`/`resolve`, and `active_modules` are all live.
