# Sprint 2 · Plan 02 — Rule Engine

**Branch:** `sprint-2/02-rule-engine`
**Closes/advances:** BL-026 (rule engine). Second of the four-engine foundation (after sprint-2/01 status engine; BL-025 Workflow + BL-024 Template downstream).
**First integration:** `conditions_json` on `status_transitions` edges (the status engine's "Transition Hooks evaluate conditions via the Rule Engine" — project plan §1.2.3).
**Defers (new backlog items):** hybrid named-rules catalog, disabled-transition-button-with-reason polish.

---

## Context

The status engine (sprint-2/01) ships a strict transition graph with role-gated edges but no *conditional* edges. The project plan's rule engine (§1.2.2) is the missing evaluator: facts + operators + JSON condition trees → boolean. It is consumed everywhere downstream — edge conditions now; workflow-node triggers (BL-025), reviewer auto-assignment (sprint 4), payment→eligibility rules (sprint 5), checkpoint eligibility (sprint 7) later.

The repo already holds the two halves of the pattern: backend `services/filter_translator.py` (recursive whitelisted group→SQL translator) and frontend `components/platform/resource-list/filter-builder.tsx` (condition-row + AND/OR group builder). The rule engine is their sibling pair evaluating **in-memory fact dicts**, not SQL.

### Locked design decisions (from grilling)

1. **D1 — Rule = property, not entity (Option A).** No `rules` table, no central CRUD. Engine = library: pure evaluator + fact registry + reusable builder UI. Each consumer stores its own condition tree in its own JSON column (`status_transitions.conditions_json` now; workflow nodes / review rules / checkpoints later). Hybrid named-rules catalog ("save as named rule", reference + sync across consumers) = backlogged, non-breaking add later.
2. **D2 — Multi-source facts.** Fact keys namespaced by source: `actor.name`, `record.slug`. A consumer declares which sources it provides (`actor` + `record:<entity_type>` for edges); the builder shows only those facts, grouped by source; the evaluator receives a matching fact dict per source.
3. **D3 — Operators per fact type** (nothing more; no regex):
   | Type | Operators |
   |---|---|
   | string | `eq, neq, contains, in, not_in` |
   | number | `eq, neq, gt, gte, lt, lte, between` |
   | boolean | `is_true, is_false` |
   | date | `before, after, between` |
   | enum | `eq, neq, in, not_in` (value widget = select from options) |
   | list | `contains_any, contains_all, not_contains` (e.g. `actor.roles`) |
   Combinators `and`/`or`, groups nest to depth 5 (same `_MAX_DEPTH` guard as filter_translator).
4. **D4 — Cross-fact compare.** Condition carries `valueKind: "literal" | "fact"`; when `fact`, value = another fact key. Type-gated both ends (builder RHS picker shows only same-type facts; `validate()` rejects mismatches). Scalar compare operators only (`eq, neq, gt, gte, lt, lte, before, after`) — `between`/`contains`/list ops stay literal-only.
5. **D5 — Fail closed, uniformly.** Missing or null fact ⇒ that condition evaluates `false` — no exceptions, including negative operators (`neq`, `not_in`, `not_contains`). No runtime errors from stale rules; the whole rule may still pass via an OR branch.
6. **D6 — Edge UX mirrors RBAC gating.** Failing edges are **hidden** from `available_transitions()` (like role-blocked edges today); the executor **re-checks at fire** (server boundary + race safety). Distinct, specific errors: role block = existing `TransitionForbidden` 403; rule block = new `TransitionConditionsNotMet` 409 whose message lists the FAILED conditions via the prose renderer ("'Approve' is not available: conditions not met — Amount must be greater than 1000.").
7. **D7 — Fact registry = whitelist + schema inference (never auto-expose the schema).** Full auto-derive is rejected (would expose `password_hash`/credentials columns, can't label, can't do enum options, relationships, or computed facts like `unreviewed_count`). Declaration is opt-in but cheap: `facts(Model, ["name", "slug", "is_platform", "created_at"])` infers type/label/resolver from the SQLAlchemy column (`String→string`, `Boolean→boolean`, `DateTime→date`, `Integer/Numeric→number`; label = title-cased key, overridable); computed/relationship/enum facts use an explicit `FactDef` with a resolver callable (and `options` for enums). Modules register facts in code at install (callables can't live in a manifest), deregistered with the module — permissions.csv lifecycle, code-side.
8. **D8 — Thin v1 fact set.** `actor` source (User: email, name, status, roles as list) + `record:tenant` (name, slug, isPlatform, createdAt). Real meat arrives as entities register; no scope creep (User.status migration stays deferred per plan 01).
9. **D9 — Frontend builder = sibling component**, `components/platform/rule-builder/`, cloned from filter-builder's interaction pattern (draft tree with stable keys, per-type operator menus) but its own types/schema. `filter-builder.tsx` untouched — production-stable across every Resource list, and lists can never need cross-fact compare. Possible later unification = backlog note only.
10. **D10 — Backend package `app/rule_engine/`** mirroring `app/status_engine/`: `registry.py` (FactDef, sources, `facts()` helper), `evaluator.py` (pure `evaluate(tree, facts) -> bool`), `schemas.py` (Pydantic camelCase `RuleGroup`/`RuleCondition`), `prose.py` (tree → human sentences), `sites.py` (rule-site registry for the observability list).
11. **D11 — Save-time validation.** Consumers PATCHing a condition tree call `rule_engine.validate(tree, sources)` → 422 listing problems: unknown fact key, operator invalid for type, cross-fact RHS type mismatch / RHS on non-scalar op, depth > 5, empty rows, value type mismatch. Stale facts (removed after save): runtime = fail closed (D5); builder renders amber "unknown field" chips + warning banner; re-save is blocked by validation until fixed.
12. **D12 — Read-only "Rules" observability page.** Rules are born where they're used; this page answers "what rules exist + where". Code-side **rule-site registry**: each consumer registers a lister returning `{site, context, summary (prose), editUrl}` rows. `GET /rules` aggregates, tenant-scoped. Resource list, no create/edit — row deep-links to the owning UI (edge drawer). Gated by new core permission **`rules.read`**; two menu surfaces (operator under Platform, tenant under Settings) like the status engine.
13. **D13 — `GET /rule-facts?sources=...` = authenticated-only** (like `/roles/options`) — exposes only whitelisted fact labels/types, needed by any consumer's builder. Config writes ride each consumer's own permission (`statuses.manage` for edges); no new manage permission.

---

## Wire schema (camelCase, stored as-is in consumer JSON columns)

```jsonc
{
  "kind": "group",
  "combinator": "and",            // "and" | "or"
  "rules": [
    { "kind": "condition", "fact": "record.isPlatform", "operator": "is_false",
      "valueKind": "literal", "value": null },
    { "kind": "condition", "fact": "record.createdAt", "operator": "before",
      "valueKind": "fact", "value": "actor.lastLoginAt" },   // cross-fact (D4)
    { "kind": "group", "combinator": "or", "rules": [ /* nested, ≤ depth 5 */ ] }
  ]
}
```

Dates compare as UTC ISO strings parsed to datetimes (DB stores UTC — CLAUDE.md datetime rule).

---

## Data model

One migration (Alembic autogen):
- `status_transitions.conditions_json` — nullable JSON. NULL/empty = unconditional edge (today's behavior, regression-protected).

No other tables. (No `rules` table — D1.)

---

## Backend (`dreamz_ems_backend/`)

- **`app/rule_engine/registry.py`** — `FactDef(key, label, type, options?, resolver)`, fact sources (`register_fact_source`, `facts(Model, keys, overrides?)` inference helper), `get_facts(sources) -> list[FactDef]`, `resolve_facts(sources, objects, db) -> dict`. Core registers `actor` (User) + `record:tenant` next to `STATUS_ENTITIES`.
- **`app/rule_engine/evaluator.py`** — `evaluate(tree, facts) -> bool`, pure, no I/O. Fail-closed on missing/null (D5), depth guard, cross-fact resolution (D4). Also `failed_conditions(tree, facts)` for the error message.
- **`app/rule_engine/schemas.py`** — `RuleGroup`/`RuleCondition` Pydantic (camelCase via alias, like filter schemas); `validate_tree(tree, sources)` (D11).
- **`app/rule_engine/prose.py`** — condition/tree → sentences using registry labels + operator phrases. Consumers: `TransitionConditionsNotMet` message (failed only) + Rules list `summary` column.
- **`app/rule_engine/sites.py`** — `register_rule_site(key, label, lister)`; status engine registers a lister over non-null-condition edges (`context = "<Entity> · <From> → <To>"`, `editUrl` = canvas deep-link).
- **Status-engine integration** (`services/status_machine.py`):
  - `transition()`: after the role check — build facts (`actor` + record), `evaluate`; fail → `TransitionConditionsNotMet` (409) listing failed conditions.
  - `available_transitions()`: filter edges whose conditions fail (alongside the role filter).
  - `status_service` transition CRUD: run `validate_tree` on save → 422.
- **Routers** — `api/v1/rules.py`: `GET /rule-facts?sources=` (authenticated), `GET /rules` (gated `rules.read`, paginated). Transition CRUD already lives in `api/v1/statuses.py` — schema gains `conditionsJson`.
- **Permissions** — add `rules.read` row to `app/permissions/permissions.csv`; re-grant Admin at seed.

## Frontend (`dreamz_ems_frontend/`)

- **`components/platform/rule-builder/`** — `<RuleBuilder sources facts value onChange>`: fact dropdown grouped by source, operator menu per fact type (D3), value widget per type (text/number/date/bool/enum-select/multi), literal⇄field toggle on scalar compares (RHS = type-compatible facts only, D4), AND/OR group nesting, stale-fact amber chip + warning banner (D11). Interaction pattern cloned from `filter-builder.tsx` (draft tree, stable keys); own types in `types/rules.ts`.
- **Edge drawer** (status-engine canvas) — "Conditions" section beneath roles: `<RuleBuilder sources={['actor', 'record:<entity>']}>`. Empty = unconditional.
- **Rules page** — `app/(protected)/platform/rules/` + Settings surface: read-only Resource list (Site / Context / Summary via `ClampedText` / Updated), row click = `editUrl` deep-link, `<RequirePermission permission="rules.read">`. No create button.
- **Services** — `services/rule-engine-service.ts` (+ mock first, `.real.ts` swap at the boundary): `getFacts(sources)`, `listRules(params)`.
- **Menu** — Platform + Settings entries gated `rules.read`.

Frontend-first: build `RuleBuilder` + Rules page against the mock service (mock fact registry + canned rules); wire real endpoints in the backend phase.

---

## TDD

- **Backend (pytest):** evaluator matrix (every operator × type; AND/OR nesting; depth-5 reject; missing/null → false incl. negative ops; cross-fact match + type-mismatch rejected at validate; list ops on `actor.roles`); `validate_tree` 422 shapes (unknown fact, bad operator-for-type, RHS mismatch, empty rows); registry inference (String/Boolean/DateTime/Integer → type) + computed FactDef resolver + module register/deregister; edge integration (conditioned edge passes/blocks at fire; `available_transitions` hides failing edges; 409 lists failed conditions via prose; role-block vs rule-block distinct; unconditional edge regression); `GET /rule-facts` source filtering; `GET /rules` aggregation tenant-scoped + permission-gated.
- **Frontend (Vitest + RTL):** RuleBuilder renders source-grouped fact dropdown; operator list follows fact type; cross-fact toggle limits RHS to compatible facts; serializes/round-trips the tree; stale-fact chip + save block; Rules list renders prose summary; permission gating.
- **E2E (Playwright, real clicks, timestamped names):** operator → Status Engine canvas → edge drawer → add condition (`record.isPlatform is false`) → save → fire transition on a qualifying record (allowed) → non-qualifying (button hidden) → Rules page shows the row → deep-link back to the drawer. Test Execution Report per orchestration guide §6.

---

## Verification (end-to-end)

1. `python -m scripts.bootstrap_db`; `uvicorn app.main:app --reload --port 8001`.
2. `python -m pytest -q` green.
3. Frontend: `npm run build && npm start` (no new deps).
4. Manual: Admin → Status Engine → edge drawer → build a condition → confirm hidden button on non-qualifying record, 409 with specific failed-condition prose when fired via API, Rules page lists + deep-links.
5. Regression: condition-less edges behave exactly as plan 01 shipped.

---

## Follow-up backlog (log in `backlog.md`)

- **Hybrid named-rules catalog** — optional `rules` table + "save as named rule" / "insert named rule" beside inline; reference + edit-once-sync semantics, delete protection. Non-breaking add over D1.
- **Disabled-transition-button-with-reason** — show rule-blocked edges greyed with prose tooltip instead of hidden (reuses `prose.py`).
- Workflow engine (BL-025) consumes `evaluate()` for node trigger conditions; reviewer assignment (sprint 4), payment eligibility (sprint 5), checkpoint eligibility (sprint 7) follow the same inline pattern + register their rule sites.
