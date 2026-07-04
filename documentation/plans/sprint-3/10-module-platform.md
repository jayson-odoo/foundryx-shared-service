# Sprint 3 · Plan 10 — Module Platform v2 (inter-module deps + 3rd-party extensibility)

**Branch:** `sprint-3/10-module-platform`
**Advances:** F9 (roadmap `sprint-3/00`; grill record `F4-foundations-grill-decisions.md` §2). Third F4 prerequisite. Extends the App Store (sprint-1/08) from "install/uninstall isolated leaf modules" to "a real module ecosystem with declared dependencies, a capability registry, and module-authored extension points." **Closes BL-029** (per-module Alembic). **Consumed by** F4 (EMS as the first big module) and every future vertical / 3rd-party module.
**Spawns:** BL-1xx module **suite** support (a module declaring `requires` another *non-core* module — 3rd parties building *on* EMS) once one-big-module strains · BL-1xx capability-version deprecation tooling · BL-1xx module package export/import + certifier (was BL-049 — revisit here) · BL-1xx admin UI for the dependency graph + capability catalog.
**Depends on:** App Store (`modules`/`tenant_modules`, `AppStoreService`, `module_loader.py`, `require_module`, `requires_version`, sprint-1/08), the manifest contract (`manifest.json`), the code-side registry pattern used everywhere (StatusEntity/TriggerDef/FactSource/ImporterDef/TermDef), the omnichannel module (the first `optional`-dep target — `messaging.send`), Alembic core setup + the module-isolated-migration governance rule.

---

## Context

The App Store today installs **leaf** modules (omnichannel) in isolation: a module FKs only into core `public`, hooks via events, and depends on nothing but core. That was enough for one comms leaf. F4 breaks it: **EMS is a big module that wants to *use* another module (send WhatsApp via omnichannel) and be *built upon* by future modules**, and the platform's whole value proposition is a 3rd-party ecosystem. That needs three things the App Store lacks:

1. **Declared dependencies** — hard (`requires`) and soft (`optional`/`enhances`) — with install/uninstall ordering + guards.
2. **A sanctioned way for one module to call another** without importing its internals (so implementations are swappable and uninstall stays safe).
3. **Extension points opened to modules** — today only *core* registers into the TriggerDef/StatusEntity/website-block/menu/ImporterDef/TermDef catalogs; modules must be able to register too (and publish their own catalogs).

Plus an infra debt this forces us to pay: a domain the size of EMS **cannot ride `create_all`** (omnichannel's BL-029 shortcut). **Per-module Alembic** is the F4 gate and the first slice here.

**Hard governance line preserved:** modules still **never** FK across schemas into another module's tables and **never** import another module's Python internals. Cross-module coupling goes through a **capability registry** (runtime resolution) and **soft references** (string ids resolved via the provider's service). This keeps every module independently installable + uninstallable.

**Net demo at end of plan 10:** install a tiny demo "consumer" module that declares `optional` dependency on omnichannel and registers a workflow action resolving the `messaging.send` capability — with omnichannel installed the action appears and sends; uninstall omnichannel and the action **self-disables with a warning** (no crash, consumer still installs/runs); a `requires`-style dep blocks install until its provider is present and blocks the provider's uninstall while depended-upon; and a module ships + applies its **own Alembic migration** into its own schema with its own version table.

---

## Locked design decisions (from grill record §2)

1. **D1 — Register at BOOT, gate per-tenant at RESOLVE (the spine).** Module code is in-repo and **loaded at boot** (`load_modules` imports every manifest's routers regardless of install state; `require_module` gates per-tenant at request). So **capabilities + extensions register at boot** (like core's `lazy_once`), and **per-tenant gating happens at resolve/use** (is the providing module ACTIVE for *this* tenant?). "Install" stays a per-tenant **activation** (`tenant_modules`), never code load. True per-tenant **dynamic code deployment** (zip/certify/upload) = an explicit **seam, deferred** — F9 assumes in-repo modules. **No register/unregister churn on install** — registration is static at boot; only visibility/resolution is per-tenant dynamic.

2. **D2 — One `active_modules` filter across ALL catalogs.** Every registry item carries a **`module` tag** (`'core'` always visible; else the module name) — `WorkflowEntity.module` already exists; add it to `FactSource`/`TermDef`/`ImporterDef`/website-block/`CapabilityDef`/Trigger/Action where missing. One helper **`active_modules(db, tenant_id) -> set[str]`** + a uniform filter (`module=='core' or module in active`) applied at **every consumption point**: workflow trigger/action pickers + **trigger matching** (event bus), rule-builder facts, status-entity list, import button, terminology page + label resolution, website-block palette (menu + `GET /permissions` already filter — fold into the same helper). **Stale references degrade gracefully** (a workflow referencing a now-inactive module's extension → run node errors "module X inactive", failure-isolated, never crashes). **New-catalog checklist rule:** any future catalog MUST tag `module` + apply `active_modules`.

3. **D3 — Per-module Alembic (closes BL-029), data-safe.** Each module gets `/modules/<name>/alembic/` — own `env.py` (reads its `Base.metadata` + schema + `alembic_version_table`, both already in the manifest) + `versions/`, isolated from core's history (dodges the cross-branch-pin gotcha). Orchestrator (in `bootstrap_modules` + on install), per module: **version-row exists → `upgrade head`; no row + tables exist (legacy `create_all`) → `stamp head` (no DDL); no row + no tables → `upgrade head`**. **omnichannel** gets an autogenerated **baseline migration** capturing its current schema → existing DBs **stamped** (data untouched), fresh DBs **upgraded**; `create_all` retired. **ems starts clean** (rev 1, never `create_all`). **Per-tenant uninstall NEVER drops schema/tables** (shared across tenants — wipes that tenant's rows only); global schema-drop = **operator-only, explicit** (never automatic on delist — data safety).

4. **D4 — Dependencies: `requires` (hard) vs `optional` (soft).**
   - **`requires`:** `[{name, version}]`. **Install blocked unless the dep is installed + ACTIVE + version-satisfies** (`requires_version`); missing → **block + offer cascade-with-consent** (install the whole chain in **topological order, one transaction**, user sees what else + its grants — no silent auto-install); a dep that's **installed-but-INACTIVE** → block "activate X first" (no silent reactivation). **Reverse-dependency guard on BOTH uninstall AND deactivate** (a required provider can't go away or go inactive while a dependent is ACTIVE). Cycle detection at boot → loud failure.
   - **`optional`/`enhances`:** **zero guards, ever** — the consumer discovers the capability at runtime; absent provider → the enhanced feature **self-disables/hides** (foolproof warn, never a silent runtime error). *EMS `optional`-deps omnichannel.*

5. **D5 — Capability registry (cross-module calls).** `CapabilityDef{key, version, provider_module, handler}` **boot-registered** (e.g. omnichannel `messaging.send@1`). **`resolve_capability(db, tenant_id, key, version) -> handler | None`** — returns the handler iff the provider module is **ACTIVE for that tenant** and version matches, else **None** (the self-disable signal; never raises for "absent"). **Handler `(db, tenant_id, payload) -> result`** — provider **tenant-scopes internally** (isolation never relaxed; the critical house invariant). **Versioning = integer major**, **exact-major match** (breaking = new major; provider may keep old majors registered). **Unique `(key, version)` → one provider; a duplicate at boot = loud error** (per-tenant multi-provider selection = backlog). Works cross-process (web + Celery worker both boot the registry; resolve takes a `db`). A module **never imports another's internals** — so a 3rd party can ship an alternative provider transparently.

6. **D6 — Soft references (cross-module data), not FKs.** A `SoftRef{module, entity_type, id}` stored on the consumer (JSON column v1; link table when many). **Resolved through a provider `resolve` capability** (e.g. omnichannel `contact.resolve@1`) — `resolve_soft_ref(db, tenant_id, ref)` → `resolve_capability(...)` → call. **No `app_ems → app_omnichannel` query, ever.** Orphan (provider inactive/uninstalled) → None → UI "linked record unavailable" (no dangling FK; there's no FK). **Security generalizes the polymorphic-`target_id` rule** (sprint-2/01 leak): **save-time validate** (ref resolves + target tenant matches author's → 422 else) + **resolve-time tenant-scope**. Generalizes BL-030 to the cross-module case.

7. **D7 — State is code + manifest, not heavy tables.** Capabilities/extensions live in-process (boot registries). Dependency info for the guards + admin view is **computed from manifests at catalog sync** (a denormalized `module_dependencies` table only if a guard query needs it). `manifest.json` gains `requires[]`, `optional[]`, `provides[]` (`required_core_version` exists).

8. **D8 — Failure isolation: no single point of failure crashes the system.** Per-module boot (router import + registration) **and** per-module migration are each wrapped in try/except → failure marks the module **`errored`**, **skips** it (routers + registrations + migration), logs loudly, **app + all siblings + core continue**. An **errored module behaves like inactive** (routes unavailable, capabilities/extensions absent → consumers self-disable) + is **not installable** + is **surfaced** (errored state + captured message in the catalog API, storefront, console). Capability resolution returning None is a normal state, never an exception at the call site.

9. **D9 — App Store onto the Resource shell (reverses plan-08's card-grid decision).** Both `/app-store` (tenant) + the console Modules tab move to the config-driven shell. **The detail lives in a tabbed full-page form** (Overview · Dependencies · Capabilities · Permissions · Status[per-tenant active/inactive/errored + installed_version + update-available]); lifecycle actions (install/activate/deactivate/update/uninstall) in the **action registry** with typed-confirm uninstall + cascade-consent via `ConfirmActionDialog`. **List keeps the storefront aesthetic via a NEW generic card/grid display mode added to the Resource shell** (`ResourceListConfig` gains a display-mode + card renderer — a reusable shell capability, not an app-store one-off).

---

## Manifest additions

```jsonc
{
  "module_name": "ems",
  "version": "1.0.0",
  "required_core_version": ">=2.0.0",
  "requires":  [],                                   // hard deps (topo + guard)
  "optional":  [{ "name": "omnichannel", "version": ">=1.2.0" }],  // soft, self-disabling
  "provides":  [{ "capability": "ems.participant_lookup", "version": 1 }],
  "routers":   [ /* existing */ ]
}
```

## Code-side contracts (`app/module_platform/`)

```python
@dataclass(frozen=True)
class CapabilityDef:
    key: str            # 'messaging.send'
    version: int
    provider_module: str
    handler: Callable   # (db, tenant_id, payload) -> result

register_capability(CapabilityDef)                      # at BOOT (provider code present)
resolve_capability(db, tenant_id, key, version) -> Optional[Callable]   # tenant-active + exact-major gated; None => self-disable
SoftRef(module, entity_type, id) / resolve_soft_ref(db, tenant_id, ref)  # cross-module data via a provider `resolve` capability, no FK
active_modules(db, tenant_id) -> set[str]               # the one filter for every catalog
```

Dependency resolution: `resolve_install_order(manifests)` (topo + cycle error), `check_requires(db, tenant_id, manifest)` (active + version + cascade plan), `check_dependents(db, tenant_id, module)` (reverse-guard for uninstall **and** deactivate).

## API / loader

- `module_loader.py` — boot: topo-ordered load, **per-module try/except** (errored → skip + isolate), capability/extension registration (at boot, not install).
- `bootstrap_modules` — per-module Alembic orchestration (stamp-if-legacy-else-upgrade), each wrapped (errored → skip, core/siblings unaffected).
- `AppStoreService.install/deactivate/uninstall` — requires-guard + cascade-consent + reverse-dep guard (uninstall **and** deactivate); per-tenant uninstall keeps schema.
- `GET /app-store/modules` (+ console mirror) — each entry gains `requires`/`optional`/`provides`, met/unmet **availability**, and `errored`+message; feeds the Resource shell.
- New: `GET /platform/modules/graph` (operator, `tenants.manage_modules`) — dependency + capability catalog (visual graph UI = BL).

## Phase A — Frontend-first (mock)
**App Store on the Resource shell** (D9): add the generic **card/grid display mode** to the shell, then the storefront list (card mode) + the **tabbed detail form** (Overview/Dependencies/Capabilities/Permissions/Status). Dependency **badges** (requires met/unmet, enhances), **cascade-consent dialog**, reverse-dep **block messaging** on deactivate/uninstall, **errored** badge, and the consumer **self-disable warning** (reuse the workflow editor's missing-connection component). Mock the availability/errored flags.

## Slices (4)
1. **Slice 1 — per-module Alembic (BL-029)** *(the F4 gate)*: per-module alembic dir/env/version-table; orchestrator stamp-if-legacy-else-upgrade; omnichannel baseline + stamp, retire `create_all`; per-module migration isolation (errored → skip). ems gets its skeleton in plan 11.
2. **Slice 2 — dependency system:** manifest `requires`/`optional`, topo order + cycle detection, install guard + cascade-consent, reverse-dep guard on uninstall **and** deactivate, `requires_version` reuse.
3. **Slice 3 — capability registry + soft refs + extension-open + the `active_modules` filter sweep:** boot `register_capability` / `resolve_capability` (integer-major, tenant-active-gated), `SoftRef`/`resolve_soft_ref` (provider `resolve` capability + save-validate), the `module` tag on all registry items + `active_modules` applied at every consumption point + stale-ref graceful skip, errored-module isolation at boot.
4. **Slice 4 — App Store on the Resource shell (D9):** generic card/grid display mode on the shell; storefront + console Modules tab refactored to list (card mode) + tabbed detail form; dependency/capability/errored UX + cascade-consent + self-disable warnings.

A tiny **demo consumer module** (in-tree, test-only) exercises optional-dep + capability resolve + self-disable. *(Slices 2–3 land before the EMS-comms slice; slice 1 before F4 at all.)*

## Phase C — TDD + E2E
**Backend (`tests/test_module_platform.py`):** topo order + cycle = loud error · install blocked on missing/inactive `requires` + cascade plan · reverse-dep guard blocks uninstall **and** deactivate while depended-upon · `optional` needs no provider · `resolve_capability` → handler when provider ACTIVE+version-match, None when absent/inactive/wrong-version (per tenant) · duplicate (key,version) = boot error · **`active_modules` filters every catalog** (a module's trigger/fact/term/importer hidden for a tenant without it active) · stale-ref run-node skips gracefully · errored module isolated (app + siblings + core survive) · per-module Alembic: upgrade creates schema+version-table on fresh, **stamp on legacy tables (no DDL)**, core untouched · soft-ref save-validate (tenant-match 422) + resolve tenant-scoped + orphan → None.
**E2E (`e2e/module-platform.spec.ts`):** App Store list (card mode) → open a module's detail form (deps/capabilities tabs) → install consumer (omnichannel absent) → feature shows self-disable warning → install omnichannel (cascade if needed) → feature enables → try deactivate omnichannel → blocked by dependent → uninstall consumer → omnichannel deactivates. **Spec isolation:** dedicated tenant. Report `10-module-platform-test-report.md`.

---

## Out of scope / backlog
Module **suite** with inter-*module* `requires` (non-core) — the 3rd-party-builds-on-EMS case · capability deprecation tooling · package export/import + certifier (BL-049) · visual dependency-graph admin UI · cross-module distributed transactions (each module commits independently; sagas not in scope).
