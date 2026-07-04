# Sprint 3 · Plan 08 — Terminology (per-tenant entity relabeling)

**Branch:** `sprint-3/08-terminology`
**Advances:** F10 (roadmap `sprint-3/00-foundation-gaps-roadmap.md`; full grill record `sprint-3/F4-foundations-grill-decisions.md` §3). First of the four F4-prerequisite foundations (F10 → F8 → F9 → F4). **Consumed by** every list title / menu / breadcrumb / create-button in the system, and most visibly by F4 (`project` → "Event" for FoundryX, "Project" for a Sorento-style tenant).
**Spawns:** BL-1xx language i18n layer (multi-language labels, not just rename) · BL-1xx auto-pluralization helper (v1 stores both forms explicitly) · BL-1xx field-level relabeling (rename a column/field, not just the entity) · BL-1xx purge override rows on module uninstall.
**Depends on:** Resource shell (sprint-1/02), the cached-config delivery pattern (permissions / branding SSR), the code-side registry pattern (StatusEntity / TriggerDef / FactSource — terminology mirrors it), `useCan` + core `permissions.csv`, the menu config arrays + `filterMenu` (sprint-2/05).

---

## Context

FoundryX EMS is multi-tenant: one deployment serves a tenant who calls the core entity an **"Event"** and another who calls it a **"Project"** (and a CRM tenant who calls a `profile` a "Contact"). The display word can't be a build-time constant — it must be **per-tenant config**. This is Salesforce-style "rename tabs and labels."

The mechanism is **general and core** (horizontal — any module's entities register a default label; any tenant overrides), seeded with the entities that already exist and reused by every future vertical. It is deliberately small: it ships *before* the Import Engine (F8) so the import-history list title and every other list/menu already resolve their words through one place.

**Hard line (locked):** the **DB table + code names stay fixed** (`projects`, `profiles`) — they are an immutable contract. Only the **display label** is configurable. Clean split: table = contract, label = presentation. Terminology is also **orthogonal to language i18n** (a future layer) — v1 is single-language relabeling.

**Net demo at end of plan 08:** open Settings → Terminology, rename **"Form" → "Survey"** (singular + plural), Save; the sidebar menu item, the `/forms` list page title, its breadcrumb, and the "Create Form" button all immediately read "Survey"/"Surveys" — no reload, no re-login; click **Reset** and it reverts to the code default. A second tenant in another browser is unaffected.

---

## Locked design decisions (from grilling — see F4 grill record §3)

1. **D1 — Core, general mechanism.** `app/terminology/` (mirrors `status_engine/`, `rule_engine/` package shape), table in `public`, perms in core `permissions.csv`. Any module registers its entities' labels; the mechanism is not EMS-specific.

2. **D2 — Code-side registry of `TermDef`.** `register_term(TermDef)` where `TermDef = {key, default_singular, default_plural, module, group?, description?}`. Core registers its relabelable entities at startup (`lazy_once`); a module registers its own at install (same contract as `permissions.csv` sync). **`key` aligns with existing registry entity keys** where one exists (`form`, `workflow`, `document`, `template`, `connection`, later `project`/`profile`/`project_participant`) so one vocabulary spans status/trigger/terminology.

3. **D3 — Store both forms explicitly, no auto-pluralize.** English irregulars (`Person`/`People`) make naive pluralization wrong. An override supplies **both** `singular` and `plural` (both required). Auto-pluralization helper for the UI default = backlog.

4. **D4 — Per-tenant only, no two-tier fork.** Defaults live in code (`TermDef`); a tenant override is a row. No platform-tier fork (unlike templates/status) — the "default" is the code value, not a platform-tenant row. The platform tenant uses code defaults like anyone.

5. **D5 — Data model (core `public`):**
   - **`terminology_overrides`** — PK `(tenant_id, entity_key)`; `singular`, `plural`, `updated_at`, `updated_by`. Tenant-scoped (house invariant). A row exists only when a tenant has overridden that key; absence = use the code default. Reset = delete the row.

6. **D6 — Delivery = one cached config endpoint, not the JWT.** `GET /terminology` (authenticated) returns the **merged map** `{entity_key: {singular, plural}}` = code defaults overlaid with the tenant's override rows. Client fetches once via a `TerminologyProvider` (same shape as the branding/permissions client cache) and **refetches on an override edit** (instant in-session update — no re-login, mirrors the App-Store `update()` freshness pattern). Not added to the JWT (labels change independently of auth; bloating the token forces re-login on every rename).

7. **D7 — `useTerminology()` is the single resolver.** `const { label, labelPlural, t } = useTerminology()` → `label('form')` → "Survey", `labelPlural('form')` → "Surveys", `t('form', count)` → count-aware. Components resolve titles/menus/breadcrumbs/buttons through it; **never hard-code an entity word** on a relabelable surface again. Missing key → falls back to a humanized form of the key (never blank).

8. **D8 — Menus resolve via a tagged key.** Add optional **`MenuItem.termKey`** to the menu config. When set, the rendered label = `labelPlural(termKey)` (fallback to the static `title`). All three menu arrays (`MENU_SIDEBAR`, `MENU_MEGA`, `MENU_MEGA_MOBILE`) + the mobile/desktop renderers resolve it; `filterMenu` is untouched (it gates visibility, terminology only renames). Tag a relabelable entry in **every** array (same discipline as `MenuItem.permission`).

9. **D9 — Management UI = Resource-shell-adjacent Settings page.** `/settings/terminology` lists every registered `TermDef` (entity, module/group, code default, current override) with inline **Edit** (singular + plural) and **Reset to default**. Read for all authenticated users (everyone needs labels); **edit gated `terminology.manage`** (new core key). A `terminology.read` is unnecessary — `GET /terminology` is authenticated-only like `/auth/me` (labels are not secret, but are tenant-scoped).

10. **D10 — Registry is the extension seam (F9-ready).** The same `register_term` that core calls is what a module calls at install — so when F9 opens registries to modules, terminology already conforms. Module uninstall leaving orphan override rows = harmless (resolve falls back to default if the key is no longer registered); cleanup = backlog.

---

## Data model

```
terminology_overrides
  tenant_id    FK tenants   ┐ PK
  entity_key   str          ┘
  singular     str   not null
  plural       str   not null
  updated_at   UTCDateTime
  updated_by   FK users (nullable)
```

`TermDef` (code, not a table):
```python
@dataclass(frozen=True)
class TermDef:
    key: str                 # 'form', 'workflow', 'project', ...
    default_singular: str    # 'Form'
    default_plural: str      # 'Forms'
    module: str = 'core'     # 'core' | '<module_name>'
    group: str | None = None # optional UI grouping on the settings page
    description: str | None = None
```

## API (router `app/api/v1/terminology.py`)

- `GET /terminology` — **authenticated.** Merged map `{key: {singular, plural}}` (defaults ⊕ tenant overrides). The client cache source.
- `GET /terminology/catalog` — **`terminology.manage`.** All registered `TermDef`s + each key's current override (drives the settings page).
- `PUT /terminology/{entity_key}` — **`terminology.manage`.** Body `{singular, plural}` (both required, non-blank, length-capped). Upsert the override row. 422 on unknown key (must be registered). Returns the updated merged entry.
- `DELETE /terminology/{entity_key}` — **`terminology.manage`.** Reset (delete the override row). 204.

Service `TerminologyService` (resolve/list/set/reset) + `TerminologyRepository` (tenant-scoped). No raw SQL in the router (house rule). Schemas inherit `ApiModel` (camelCase wire). New core perms: **`terminology.read`** *(not used — see D9; omit)* and **`terminology.manage`** → `permissions.csv`, granted to tenant Admin.

## Seed (`register_term` at `lazy_once`)

Register the existing relabelable core entities so the mechanism is demoable day one: `form`, `workflow`, `template`, `document`, `connection` (label "Integration"), `role`, `import` (label "Import"). **Not** `user`/`permission`/`tenant` (relabeling those confuses RBAC/admin). EMS adds `project`/`profile`/`project_participant`/`project_type` at the `ems` module's install (plan 11).

---

## Phase A — Frontend-first (mock service)

UI → hook → service → **mock**. All states tunable with no backend.

1. **`services/terminology-service.{ts,mock,real}`** — `getTerminology()`, `getCatalog()`, `setTerm(key, {singular,plural})`, `resetTerm(key)`. Mock returns a static map + simulated latency/error.
2. **`providers/terminology-provider.tsx`** + **`hooks/use-terminology.ts`** — fetch-once context, `label`/`labelPlural`/`t(key,count)`, `refetch()`. Fallback = humanized key. Mounted in the protected layout (after auth, like the session/branding providers).
3. **Wire consumers:** the `/forms`, `/workflows`, `/templates`, `/documents`, `/settings/integrations` list page titles + breadcrumbs + create-button labels resolve through `useTerminology` (the first batch — proves the pattern; the rest follow as touched). Add `termKey` to the matching entries in all three menu arrays + resolve in the renderers.
4. **`/settings/terminology` page** — Resource-shell list (columns: Entity, Group, Default, Current label, …actions Edit/Reset). Inline edit dialog (singular + plural, both required). `RequirePermission permission="terminology.manage"`. Loading/empty/error states via the shell.
5. **Responsive** — settings table reflows / horizontally scrolls at 375px; verify both viewports (house mandate).

## Phase B — Backend (swap mock → real)

1. Migration: `terminology_overrides` (UTCDateTime import added to autogen — house gotcha).
2. `app/terminology/registry.py` (`TermDef`, `register_term`, `list_terms`, `lazy_once` seed) + `core_terms.py` (the seed set).
3. `TerminologyRepository` (tenant-scoped) + `TerminologyService` (resolve-merged / catalog / set / reset; 422 unknown-key guard).
4. Router + schemas (`ApiModel`). Perms CSV row `terminology.manage` + `tenant_admin_grant`.
5. Swap the service boundary (`terminology-service.real`), one-line per method.

## Phase C — TDD + E2E

**Backend (`tests/test_terminology.py`):** registry seed present · merged map = defaults ⊕ overrides · `PUT` upsert + 422 unknown key + blank-reject · `DELETE` reset falls back to default · tenant isolation (tenant A's rename invisible to tenant B) · perm gate (`terminology.manage` required for PUT/DELETE, GET authenticated-only).

**Frontend (vitest):** `use-terminology` resolves override > default > humanized-fallback · `t(key, count)` singular/plural selection · provider refetch after `setTerm`.

**E2E (`e2e/terminology.spec.ts`, real clicks, both viewports):** ① Settings → Terminology → rename Form→Survey → Save → assert sidebar + `/forms` title + breadcrumb + create button read "Survey(s)" with no reload → Reset → reverts. ② second provisioned tenant unaffected (isolation). Report `08-terminology-test-report.md`.

---

## Out of scope / backlog
Language i18n (multi-language, not rename) · auto-pluralization default · field/column-level relabeling · per-module override-row cleanup on uninstall · relabeling `user`/`tenant`/`permission` (deliberately excluded).
