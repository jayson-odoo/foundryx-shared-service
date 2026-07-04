# Sprint 4 · Plan 09 — Configurable Status Semantics (Slice 1: core trait infra + Sales Order reference adopter)

**Status:** GRILLED + LOCKED 2026-06-24 — ready to slice + build.
**Acceptance criteria (the contract — fulfil these):** `09-configurable-status-semantics-acceptance-criteria.md` (AC-09-01..30; Slice-1 = AC-09-01..20 + AC-09-30).
**Branch (future):** `sprint-4/09-configurable-status-semantics`
**Depends on:** status engine (sprint-2/01, LIVE) · scoped machines (sprint-3/01) · derived status (sprint-4/03) · Cluster F SO/invoice/payment/settlement (sprint-4/07 — the key-branch sites). Slice 1 touches **only `sales_order`** (CRM); finance (Slice 2) + ems/quotation/lead (Slice 3) follow on the proven infra.

---

## Problem

~43 sites across `crm`/`finance`/`ems` branch on a status **KEY** (`confirmed`/`draft`/`issued`/`void`/`paid`/`succeeded`/`remitted`/`accepted`/`won`/`valid`/`transferred`/`checked_in`…). Key-matching hardwires a domain meaning to ONE label, so a tenant renaming a status — which the status engine is *supposed* to allow — silently breaks the feature. Real bug: a tenant renamed SO `confirmed`→`approved`; every invoice-from-SO `409`'d. The keys are currently locked `is_system` "code contracts" (AC-07-53) — that lock **defeats** the configurable status engine.

## Solution (locked design)

Replace key-matching with **configurable semantic traits** attached to statuses. Code branches on `has_trait(status,'x')` / `status_for_trait(entity,tenant,scope,'x')`, NEVER on key. Keys/labels become freely tenant-renamable. A trait is a named property a status carries:

- **Trait DEFINITIONS** = a code-side, per-entity, **module-owned** registry declared at module boot in `register_engine_entities` (mirrors `StatusEntity` / permissions-CSV / fact-source). Traits are STRICTLY per-entity — a module owns its traits and drops them on uninstall; common names (`editable`) are redeclared per entity, never globally shared.
- **Trait VALUES** = a `traits_json JSON(none_as_null=True)` column on the core `statuses` table (a `list[str]` of trait keys). Resolution loads the entity's status set (already cheap — ~4-8 rows) and filters in Python. NOT a side table.

The three semantic KINDS all collapse onto traits:
- **MILESTONE** ("on entering this state do X"): resolved via the *to_status's* trait in each module's existing `transition()` wrapper. The **action code STAYS in the wrapper** (the engine never learns about doc_numbers); only the GATE changes: `if has_trait(to_status,'assigns_doc_number') and not so.doc_number:` replaces `if target_key=='confirmed' and not so.doc_number:`. Existing idempotency guards kept.
- **PREDICATE** ("is the record in a state with property X"): `has_trait(record.current_status,'x')`. Modeled POSITIVELY (`invoiceable` on Confirmed, not "exclude void").
- **TARGET** ("move record TO this state"): `status_for_trait(...)` then the existing `status_machine.transition` (mechanics unchanged; still needs an edge — graph FK/path integrity already guards that).

**Cardinality × required** — two orthogonal guards: `single` = ≤1 holder (setting on B auto-moves off A, **explicit confirm first**); `required` = ≥1 holder (block clearing/deleting the last holder → 422). Matrix: single+required = exactly 1; single+optional = 0/1; multi+required = ≥1; multi+optional = ≥0 free.

## Out of scope (Slice 1 + deferrals)

- **Slice 2** (finance: invoice/payment/settlement) and **Slice 3** (ems ticket + crm quotation/lead) are contract-described in the UAC but built later on this infra.
- **Q8 DEFER** — do NOT expose traits as rule-engine facts or workflow triggers in v1. `has_trait`/`status_for_trait` stay pure functions a future fact resolver can wrap. Backlog: **BL-124**.
- The platform `tenant` lifecycle entity keeps `is_system`+`platform_owned` untouched (load-bearing). Scoped graphs (`form_submission`, `project_participant`) carry NO domain traits.

---

## Data model + migration

**Core migration** — `app/alembic/versions/` (autogenerate then hand-edit; add `import app.models.utc_datetime` if needed). Revision id **≤ 32 chars**: use **`a1b2c3d4e5f6_status_traits`** (id token `a1b2c3d4e5f6`).

- `statuses.traits_json` — `Column(JSON(none_as_null=True), nullable=True)` (model `app/models/status.py`, after `is_default`). Default NULL — NOT `[]` (the `none_as_null` house rule; an empty list under the default `JSON` would pass `IS NOT NULL`). Resolution treats NULL as "no traits".
- No new table, no new index (resolution is in-Python over the already-loaded entity status set).
- conftest uses `create_all` — the column lands in tests automatically; STILL run `alembic upgrade head` against live Postgres before live-verify (broken migration is invisible to pytest).

## Backend layering

### 1. Trait registry — `app/status_engine/traits.py` (NEW)

```python
@dataclass(frozen=True)
class StatusTrait:
    key: str          # bare, machine-stable, unique within entity, e.g. 'assigns_doc_number'
    entity_type: str  # 'sales_order'
    label: str        # toggle label / confirm copy
    description: str   # one-line: what code does when a status carries this
    cardinality: str  # 'single' (<=1 holder) | 'multi'
    required: bool     # >=1 holder required
    module: str
```

- `_REGISTRY: Dict[Tuple[str, str], StatusTrait]` keyed `(entity_type, key)`.
- `register_status_trait(trait)` — idempotent; if a re-register changes `cardinality`/`required` raise a loud `ValueError` (contract field, AC-09-02).
- `traits_for(entity_type) -> list[StatusTrait]` — per-entity slice, sorted by `key`.
- `lazy_once`-guarded; core registers nothing here (no core domain traits in Slice 1).

### 2. Resolution helpers — same module (or `app/status_engine/__init__` re-export)

- `has_trait(status, key) -> bool` — `bool(status and (status.traits_json or []) and key in status.traits_json)`. Never raises on `None`.
- `status_for_trait(db, entity_type, tenant_id, scope_id, key) -> Optional[Status]` — load the resolved status set (tenant fork else platform NULL tier; scope-filtered when scoped), filter in Python for the single holder, return it or `None`. Tenant-scoped (sibling tenants never leak). PURE — no rule-engine import.
- These are the ONLY semantic gate primitives modules call. Document: "branch on traits, never on `key`".

### 3. Trait-value mutation + invariant guards — `app/services/status_service.py`

The existing `update_status` / `delete_status` path gains trait handling (the PATCH already exists; `UpdateStatusInput` gains `traits`):
- **Set traits on a status** (within `update_status`): validate every incoming key ∈ `traits_for(entity_type)` (422 unknown trait). For each incoming `single` trait NOT already on this status: find the current holder in the set; if one exists and `confirmMove` is falsy → **409 `{requiresConfirm, trait, currentStatusId, currentStatusLabel}`** (no mutation, AC-09-04); if `confirmMove` truthy → remove from the old holder + add to this one **atomically in one commit**.
- **required guard** (AC-09-05): before committing a removal, if a `required` trait would end with **zero** holders in the set → **422** "At least one <entity> status must be marked '<label>'."
- **delete guard** (AC-09-06, in `delete_status`): block deleting a status that holds a **required** trait until reassigned (422 naming the trait); block deleting the **last `is_initial`** status (422). (These supersede the retired `is_system` lock for domain entities.)
- Helper `validate_trait_invariants(db, entity_type, tenant_id, scope_id)` — asserts exactly-one for each required-single, ≥1 for each required-multi, ≥1 `is_initial`; reused by the editor warning chip endpoint + the guards.

### 4. Fork-bug fix (AC-09-07)

- `app/services/status_service.py` `_fork` (~line 220): forked clone must set **`is_system=False`** (was `source.is_system` verbatim) AND copy `traits_json=source.traits_json` (verbatim — the tenant inherits the platform assignment).
- `app/status_engine/scoped.py` `copy_scope` (~line 156): same `is_system=False` fix + `traits_json` copy.
- `materialize_scope` already sets `is_system=False`; no domain traits on scoped — no trait copy needed there.

### 5. Catalog endpoint — `app/api/v1/status_traits.py` (NEW router) or fold into the statuses router

- `GET /status-traits?entityType=<type>` → `[{key,label,description,cardinality,required}]`. `get_current_user` only (no manage gate). Apply the `active_modules(db, tenant_id)` filter — a trait whose `module` is not active for the tenant is omitted (mirrors importer/terminology catalog gating). Register the router in `app/main.py`.

### 6. Sales Order adopter — `modules/crm/`

**Trait catalog** (declared in `modules/crm`'s `register_engine_entities`, AC-09-14):
| key | cardinality | required | replaces | description |
|---|---|---|---|---|
| `assigns_doc_number` | single | yes | `confirmed` milestone | "Entering this status assigns the gapless sales-order number." |
| `invoiceable` | multi | yes | `confirmed` predicate | "A sales order in this status can be invoiced." |
| `lines_editable` | multi | no | `draft` predicate | "Lines and amounts can be edited while in this status." |

**Gate-swaps in `modules/crm/services.py`** (`SalesOrderService`):
- `update` ~718: `is_draft = _status_key_by_id(...) == "draft"` → `editable = has_trait(self._status(so.status_id), 'lines_editable')` (load the Status row tenant-scoped). Guard message unchanged.
- `transition` ~747/751: drop `target_key = _status_key_by_id(...)`; load the `to_status` row → `if has_trait(to_status, 'assigns_doc_number') and not so.doc_number:` → keep the `next_number('sales_order')` + `confirmed_at` body (action code unchanged, AC-09-16).
- `create_invoice_from_so` ~779: `if _status_key_by_id(...) != "confirmed":` → `if not has_trait(self._status(so.status_id), 'invoiceable'):` → **but FIRST** degrade-check: if `status_for_trait`-style resolution shows NO `invoiceable` holder in the set, the friendly-409 is the same path; keep the `with_for_update` lock. Message preserved.
- Add a small `_status(self, status_id) -> Optional[Status]` helper (tenant-scoped load) — the four sites use it; the generic `_status_key_by_id`/`_status_id_by_key` may remain for non-semantic uses but are no longer the semantic gate (AC-09-18).
- **Graceful degradation** (AC-09-08): where a feature NEEDS a trait holder and none exists, raise `409 "No status is marked '<trait label>' for sales order — configure it in Settings"`, never let `status_for_trait` `None` reach a crash.

**Per-module backfill** — `modules/crm/bootstrap.py` (AC-09-19/20):
- Declare `SALES_ORDER_TRAIT_BACKFILL = {"draft": ["lines_editable"], "confirmed": ["assigns_doc_number", "invoiceable"]}`.
- `backfill_so_traits(db)` — for every `sales_order` status across **all tiers** (platform `tenant_id IS NULL` + every tenant fork) whose `key` ∈ the map and whose `traits_json` is unset/missing-those-keys → stamp `traits_json` (idempotent: re-run = no-op). DIVERGED-key rows (key ∉ map) → leave empty + append to a returned warning report `[(tenant_id, entity, status_key)]`; log it at WARNING. Called from `bootstrap_modules` AND `update_tenant` (existing tenants) AND folded into `install_tenant`/`_seed_system_graph` (new tenants seed traits from birth — `SALES_ORDER_STATUS_SEED` ~100-104 gains a `traits` field so the seeded rows carry traits without a separate backfill).
- **Retire `is_system` for sales_order** (AC-09-06/07): seed sales_order statuses `is_system=False` (was the locked code-contract). Protection is now the invariant guards.

---

## Frontend layering (UI → hook → service → api-client)

Build **frontend-first against the mock** status-engine service, then swap the boundary to `.real`.

### Types — `types/status-engine.ts` (AC-09-10)
- `StatusFlags` / `StatusNodeData` / `UpdateStatusInput` gain `traits?: string[]`.
- New `StatusTraitDef { key: string; label: string; description: string; cardinality: 'single' | 'multi'; required: boolean }`.

### Service — `services/status-engine-service.{ts,mock,real}`
- Add `listStatusTraits(entityType): Promise<StatusTraitDef[]>` → `.real` hits `GET /status-traits?entityType=`; `.mock` returns the SO catalog.
- `updateStatus(id, {... traits, confirmMove?})` — `.real` sends `traits`+`confirmMove` on the existing `PATCH /statuses/{id}`; surfaces the 409 `requiresConfirm` payload (don't swallow it — the hook drives the confirm dialog).

### Hook — `hooks/use-status-engine.ts` (or the entity-detail hook)
- Fetch + cache `listStatusTraits(entityType)` for the open entity.
- On save with a `single` trait that returns `409 requiresConfirm` → expose the payload so the drawer can show the confirm dialog → replay `updateStatus(... confirmMove:true)`.

### UI — `components/platform/status-engine/status-drawer.tsx` (AC-09-11)
- Below the FLAG_FIELDS Switch list (~lines 185-200), render a **Traits** section from the fetched catalog:
  - `multi` trait → a free `Switch` (label = trait `label`).
  - `single` trait → "make THIS the '<label>' status" affordance (a switch/checkbox that, when turned ON while another status holds it, triggers the confirm dialog).
- **Confirm-move dialog** (AlertDialog, reuse the dirty-guard pattern): "'<trait label>' is currently on '<Status A>'. Move it to '<Status B>'?" Confirm → atomic move; Cancel → revert the toggle. NO instructional/hint copy beyond the trait `label` + the confirm sentence (foolproof-UI).
- Save flows through `updateStatus(id, { ...flags, traits })`.

### Badges — `status-node.tsx` (~42-80) + `status-table.tsx` (~47-55) (AC-09-12)
- Render a compact trait pill per trait (resolve label from the catalog). Use `OverflowPills` for width-aware `+N`, never bare `truncate`.

### Warning chip — entity detail / Flow tab header (AC-09-13)
- A new lightweight `GET /status-entities/{type}/trait-warnings` (or reuse the graph response + the catalog) surfaces unsatisfied **required** traits; render a warning chip ("No status marked '<label>'"). Clears when the trait is assigned. Resolve via `validate_trait_invariants`.

### Responsive
- Traits section + confirm dialog + badges verified at **375px AND 1280px** (drawer is already a responsive sheet; pills wrap).

---

## TDD plan

### Backend — `dreamz_ems_backend/tests/test_status_traits.py` (NEW)
- `test_traits_json_column_nullable_none_as_null` (AC-09-01).
- `test_register_status_trait_idempotent` + `test_register_conflicting_cardinality_raises` (AC-09-02).
- `test_traits_for_is_per_entity` (AC-09-02).
- `test_has_trait_true_false_and_none_safe` (AC-09-03).
- `test_status_for_trait_resolves_tenant_fork_and_scope` + `test_status_for_trait_none_when_no_holder` (AC-09-03/08).
- `test_single_trait_requires_confirm_then_atomic_move` (AC-09-04).
- `test_single_trait_set_on_current_holder_is_noop` (AC-09-04).
- `test_required_trait_block_clear_last_holder_422` (AC-09-05).
- `test_delete_status_holding_required_trait_blocked` + `test_delete_last_initial_blocked` (AC-09-06).
- `test_fork_sets_is_system_false_and_copies_traits` + `test_copy_scope_is_system_false` (AC-09-07).
- `test_status_traits_endpoint_lists_catalog_active_module_filtered` (AC-09-09).

### Backend — `dreamz_ems_backend/tests/test_crm_so_traits.py` (NEW, or extend the CRM SO test)
- `test_so_lines_editable_gate_not_key` (AC-09-15) — rename `draft`→`Drafting`, lines still editable.
- `test_so_assigns_doc_number_milestone_by_trait` + idempotency (AC-09-16).
- `test_so_invoiceable_gate_not_key` (AC-09-17).
- `test_so_no_key_literal_branches_remain` — grep-style assert over the service module (AC-09-18).
- `test_so_trait_backfill_all_tiers_idempotent` + `test_diverged_key_warned_not_reset` (AC-09-19).
- `test_new_tenant_so_statuses_seeded_with_traits` (AC-09-20).
- `test_invoice_from_so_friendly_409_when_no_invoiceable_holder` (AC-09-08).

> Keep the pre-existing **status-engine + tenant-lifecycle** suites green (load-bearing — the `tenant` entity is untouched).

### Frontend — Vitest
- `types`/service: `services/status-engine-service.test.ts` — `listStatusTraits` shape; `updateStatus` sends `traits`+`confirmMove`; 409 `requiresConfirm` surfaced (AC-09-10).
- `components/platform/status-engine/status-drawer.test.tsx` — renders multi Switches + single affordance from the mock catalog; turning a held single trait ON opens the confirm dialog; Confirm calls `updateStatus(...confirmMove:true)` (AC-09-11).
- `status-node` / `status-table` render trait pills (AC-09-12).

### E2E — `e2e/configurable-status-semantics.spec.ts` (AC-09-30)
- Real clicks: sign in (`statuses.manage` user) → navigate to the sales_order status entity → open the **Confirmed** status drawer → **rename label to "Approved"** → save → canvas shows "Approved".
- Then via the SO UI (real clicks): create a Sales Order → transition to **Approved** (doc number assigned) → **Create invoice from SO** → assert the invoice is created with **NO 409**.
- `page.setViewportSize` at 375 AND 1280. Timestamp any created entity names (E2E residue discipline).

---

## Build order (frontend-first, reference-first)

1. **Frontend mock + UI** — extend types, add `listStatusTraits` to `.mock` (SO catalog), build the drawer Traits section + confirm dialog + badges + warning chip against the mock. Iterate UI at 375/1280. Vitest green.
2. **Backend TDD** — migration (`a1b2c3d4e5f6_status_traits`) → `traits.py` registry + helpers → `status_service` trait mutation + invariant guards → fork-bug fix → `GET /status-traits`. pytest red→green.
3. **SO adopter** — register the SO trait catalog, gate-swap the four `services.py` sites, per-module backfill + seed-with-traits + `is_system=False`, friendly-409 degradation. pytest green.
4. **Swap mock→real** — flip the service boundary to `.real`; verify the drawer shows real trait data.
5. **E2E + live verify** — run `configurable-status-semantics.spec.ts` against the live stack on a fresh build.

---

## Acceptance / QA — Definition-of-Done gate (binding) + code-review hard-fail rules

A slice is NOT done until this gate passes (reviewer checks it; embed it in every subagent brief):

1. **Mock swapped to real.** The trait-toggle UI ships against the mock first, then the boundary swaps to `.real` and is **verified showing real trait data**. No `PHASE 1 MOCK` reaches the user-perspective QA pass.
2. **Backfill existing rows/tenants.** `traits_json` is stamped on EVERY matching sales_order status across the platform tier AND every tenant fork (a per-module idempotent backfill in `bootstrap_modules` + `update_tenant`, seed-with-traits for new tenants) — NOT seed-if-absent only. Diverged-key rows are **warned, never auto-reset** (no tenant data loss).
3. **No hardcoded tenant-editable keys.** Zero `key == "<literal>"` semantic branches remain in the gate-swapped SO paths (grep-verified — `test_so_no_key_literal_branches_remain`). The whole point: a tenant rename must not break the feature.
4. **Perm-grant sweep — N/A (state it).** No new permission: trait edits ride existing `statuses.manage`; the `GET /status-traits` catalog rides `get_current_user`. No `tenant_admin_grant` sweep needed. (Recorded explicitly so the reviewer doesn't flag a missing sweep.)
5. **Real-data user-perspective verify.** AC-09-30 (rename Confirmed→Approved → invoice-from-SO succeeds — the exact bug) verified end-to-end with real data at **375px AND 1280px** on a freshly REBUILT frontend (`rm -rf .next && npm run build`, kill stale `next-server`) against correctly-owned ports (3001 FE / 8001 Dreamz BE — kill any sorento squatting 8001).

**Code-review hard-fail rules** (reviewer rejects): DB query/raw SQL in a router; a React component calling fetch/axios instead of a hook; `any` types; raw CSS/`<style>`; a module altering core `public` tables (this plan's `traits_json` migration is a **core** Alembic change to the core `statuses` table — correct, since the column is core infra; the per-module trait *catalog* and *backfill map* live in `modules/crm`, never in core). Also reject: a mock not swapped to real; a new column on an existing entity with no backfill for existing rows/tenants; code that hardcode-looks-up a tenant-editable key.

---

## Risks / notes

- **`none_as_null=True` is mandatory** on `traits_json` — the default `JSON` stores Python `None` as JSON `null` and would pass `IS NOT NULL` (the documented status-engine `conditions_json` bug class).
- **Fork copies traits verbatim** — a tenant editing post-fork edits their own copy; the platform tier is the default. The fork-bug fix (`is_system=False`) is load-bearing: without it a forked row stays "system" and the new invariant-guard deletes/edits would be wrongly blocked.
- **Resolution cost** — loading the entity's status set is the existing cheap query (~4-8 rows); filtering in Python is negligible. No new index.
- **Slice 2/3 reuse this infra unchanged** — they only add their module's trait catalog + backfill map + gate-swaps; no core change after Slice 1.
