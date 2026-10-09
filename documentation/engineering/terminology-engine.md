# Terminology engine

> Moved verbatim from `CLAUDE.md` on 2026-09-05 (slim-index restructure). The rules here still bind; `PRINCIPLES.md` governs on conflict. Update THIS file when the engine changes.

### Terminology engine (LIVE since sprint-3/08, F10 - per-tenant entity relabeling)
Salesforce-style "rename tabs/labels": the DB/code names are an immutable contract, only the **display label** is per-tenant config. Plan `documentation/plans/sprint-3/08-terminology.md`. **Core, horizontal** (`app/terminology/`, mirrors rule/status engine package shape).
- **Code-side `TermDef` registry** (`register_term`, `lazy_once` core seed `core_terms.py`): `{key, default_singular, default_plural, module, group}`. `key` aligns with existing entity keys (`form`/`workflow`/`project`…) so ONE vocabulary spans status/trigger/terminology. Modules register at install (EMS adds project/profile/… in its `register_engine_entities`). **`group` is code-side catalog metadata, NOT a tenant override** - set at registration; not editable per-tenant (only singular/plural are).
- **Both forms stored explicitly** (D3 - English irregulars; no auto-pluralize). `terminology_overrides` table PK (tenant_id, entity_key); a row exists only when overridden; Reset = delete.
- **Delivery = one cached config endpoint, NOT the JWT** (a rename must not force re-login). `GET /terminology` (authenticated) = merged map (defaults ⊕ overrides); `useTerminology()` fetch-once module store (`hooks/use-terminology.ts`), `label`/`labelPlural`/`t(key,count)` + humanized fallback (never blank), `refreshTerminology()` on edit (instant in-session). Catalog/PUT/DELETE gated `terminology.manage`.
- **`MenuItem.termKey`** resolved in sidebar + mega renderers + `ToolbarPageTitle`; relabelable list configs resolve `createLabel`/search via `useTerminology` (tag in ALL menu arrays, same discipline as `permission`).
- **`/settings/terminology` is on the FULL Resource shell** (config-driven `ResourceList`, search/filter/column-prefs/sort/export) - the catalog is small client data, so the fetcher pulls it whole + filters/sorts/paginates client-side (a valid adapter when there's no server-paginated endpoint). Edit/Reset in the action registry; no detail page (`rowHref` → current path); remount-on-save (`key` bump) reloads. **Don't hand-roll a plain table for a settings list - adapt the Resource shell** (user mandate, reinforced here).
- Tests: `tests/test_terminology.py` (9), `hooks/use-terminology.test.ts` (4), `e2e/terminology.spec.ts` (2). Report `08-terminology-test-report.md`.

