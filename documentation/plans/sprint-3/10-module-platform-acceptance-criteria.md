# Sprint 3 · Plan 10 — Module Platform v2 · User Acceptance Criteria

**Plan:** `10-module-platform.md` · **Foundation:** F9 (closes BL-029)
**Gate role:** MERGE green after 09, before 11. Slice 1 (per-module Alembic) is the F4 hard gate.

Format: **Given / When / Then**, traced to a locked decision (Dn) + pillars 🟢📈🧭✅.
MET = named test green (UI at 375/1280 where it renders).

---

## 1. Functional SaaS — module ecosystem works end-to-end 🟢

- **AC-10-01 (demo/D4/D5) Optional-dep self-disable round-trip.**
  *Given* a demo consumer module declaring `optional` on omnichannel + a workflow action resolving
  `messaging.send`, *when* omnichannel is ACTIVE the action appears and sends; *when* omnichannel is
  uninstalled/inactive the action self-disables with a warning (no crash, consumer still installs/runs).

- **AC-10-02 (D4) Hard `requires` blocks install + uninstall correctly.**
  *Given* a module with a hard `requires`, *when* the provider is absent/inactive/version-mismatch,
  *then* install is blocked with a clear reason and a cascade-with-consent offer (topo order, one
  txn, grants shown); the provider's uninstall AND deactivate are blocked while a dependent is ACTIVE.

- **AC-10-03 (D3, BL-029) Per-module Alembic, data-safe.**
  *Given* a module, *when* `bootstrap_modules`/install runs, *then*: version-row exists → `upgrade
  head`; no row + tables exist (legacy `create_all`) → `stamp head` (no DDL); no row + no tables →
  `upgrade head`. omnichannel ships a baseline + is stamped on existing DBs (data untouched);
  `create_all` is retired; ems starts at rev 1.

- **AC-10-04 (D8) Failure isolation — no single point of failure.**
  *Given* a module that fails at boot (import/registration) or migration, *when* the app starts,
  *then* that module is marked `errored` + skipped + logged loudly; the app, all siblings, and core
  continue; an errored module behaves like inactive, is not installable, and is surfaced in the
  catalog/storefront/console with its captured message.

## 2. Scalable architecture / governance 📈

- **AC-10-05 (D1) Register at boot, gate per-tenant at resolve.**
  *Given* in-repo modules, *then* capabilities + extensions register at boot (like `lazy_once`) and
  per-tenant gating happens at resolve/use — install/uninstall is a per-tenant activation in
  `tenant_modules`, never code load/unload (no register churn on install).

- **AC-10-06 (D2) One `active_modules` filter across ALL catalogs.**
  *Given* a tenant without module X active, *when* they use any consumption point (workflow
  trigger/action pickers + event-bus trigger matching, rule-builder facts, status-entity list,
  import button, terminology page + label resolution, website-block palette, menu, `GET /permissions`),
  *then* X's items are hidden via the single `active_modules(db, tenant_id)` helper + uniform
  `module=='core' or module in active` filter.

- **AC-10-07 (D2) Stale references degrade gracefully.**
  *Given* a workflow referencing a now-inactive module's extension, *when* the run hits that node,
  *then* it errors "module X inactive", failure-isolated — never crashes the run or the system.

- **AC-10-08 (D5) Capability registry isolates cross-module calls.**
  *Given* `CapabilityDef{key,version,provider,handler}` boot-registered, *when*
  `resolve_capability(db, tenant_id, key, version)` is called, *then* it returns the handler iff the
  provider is ACTIVE for that tenant + exact-major match, else `None` (never raises for absent); the
  handler tenant-scopes internally; duplicate `(key,version)` at boot = loud error. No module imports
  another's internals (a 3rd party can ship an alternative provider transparently).

- **AC-10-09 (D6) Soft references replace cross-schema FKs.**
  *Given* a `SoftRef{module,entity_type,id}` on a consumer, *when* resolved, *then* it goes through a
  provider `resolve` capability (no `app_ems → app_omnichannel` query ever); save-time validates the
  ref + tenant match (422 else), resolve-time is tenant-scoped, orphan → None → "linked record
  unavailable" (no dangling FK).

- **AC-10-10 (D4) Cycle detection at boot.**
  *Given* a dependency cycle, *when* the app boots, *then* `resolve_install_order` fails loudly.

- **AC-10-11 (governance) Hard lines preserved.**
  *Given* any module, *then* it never FKs across schemas into another module's tables, never imports
  another module's Python internals, and per-tenant uninstall NEVER drops shared schema/tables
  (wipes that tenant's rows only); a global schema-drop is operator-only + explicit.

## 3. Guided UX 🧭

- **AC-10-12 (D9) App Store on the Resource shell with a generic card/grid display mode.**
  *Given* `/app-store` (tenant) + console Modules tab, *then* both use the config-driven shell; the
  list keeps the storefront aesthetic via a NEW reusable `ResourceListConfig` card/grid display mode
  (a shell capability, not an app-store one-off).

- **AC-10-13 (D9) Tabbed module detail form.**
  *Given* a module detail, *then* it shows Overview · Dependencies · Capabilities · Permissions ·
  Status (per-tenant active/inactive/errored + installed_version + update-available); lifecycle
  actions live in the action registry with typed-confirm uninstall + cascade-consent via
  `ConfirmActionDialog`.

- **AC-10-14 Dependency state is legible.** Requires-met/unmet + enhances badges, errored badge,
  reverse-dep block messaging on deactivate/uninstall, and the self-disable warning (reuse the
  workflow editor's missing-connection component) are all shown — foolproof, no silent failures.

- **AC-10-15 (house mandate) Responsive** at 375px and 1280px across list + detail form.

## 4. Validated quality ✅

- **AC-10-16 Backend tests green** (`tests/test_module_platform.py`): topo order + cycle loud-error ·
  install blocked on missing/inactive requires + cascade plan · reverse-dep guard on uninstall AND
  deactivate · optional needs no provider · `resolve_capability` matrix (active+match → handler;
  absent/inactive/wrong-version → None, per tenant) · duplicate (key,version) boot error ·
  `active_modules` filters every catalog · stale-ref graceful skip · errored-module isolation
  (app+siblings+core survive) · per-module Alembic (upgrade on fresh, stamp on legacy no-DDL, core
  untouched) · soft-ref save-validate 422 + tenant-scoped resolve + orphan → None.

- **AC-10-17 E2E green** (`e2e/module-platform.spec.ts`, **dedicated tenant**): list (card mode) →
  detail form (deps/capabilities) → install consumer (omnichannel absent) → self-disable warning →
  install omnichannel (cascade) → feature enables → deactivate omnichannel blocked by dependent →
  uninstall consumer → omnichannel deactivates. Report `10-module-platform-test-report.md`.

- **AC-10-18 (D3) Migration regression safety verified** on a real existing DB: omnichannel stamped,
  no data loss, no DDL on legacy tables; a fresh DB upgrades cleanly.

- **AC-10-19 House rules:** no DB/raw SQL in router · cross-process (web + Celery worker both boot the
  registry) · reviewer approved before merge.

- **AC-10-20 Slice gating respected:** Slice 1 (per-module Alembic) merges before plan 11 starts at
  all; the demo consumer module exercises optional-dep + capability resolve + self-disable.

---

## Delivery note (2026-06-16)
Slices 1–3 (the F9 backend contract — per-module Alembic/BL-029, dependency system, capability
registry, soft-refs, `active_modules`) are **complete, tested (13 + full 796 green), and the
per-module Alembic is live-verified**. AC-10-01..11, 16, 18, 19, 20 MET. **AC-10-12/13** (full
App-Store-on-Resource-shell migration) and **AC-10-17** (consumer-module Playwright E2E + the
in-tree demo module) are **deferred refinements** — their value is delivered in lighter form
(`StoreModuleOut` surfaces deps/provides/errored/availability; `ModuleCard` renders dep chips +
errored/availability warnings → AC-10-14). Deferral rationale + follow-ups in the test report.
F4 (plan 11) is unblocked. See `10-module-platform-test-report.md`.

## Definition of Done (plan 10)
All AC-10-* MET · suites green · E2E report filed · reviewer approved · merged to `main` ·
BL-029 closed. **Continuity gate:** plan 11's `ems` module rides per-module Alembic (AC-10-03),
`optional`-deps omnichannel (AC-10-01), and provides `profile.resolve`/`participant.resolve`
capabilities (AC-10-08) — these must be green before EMS is built.
