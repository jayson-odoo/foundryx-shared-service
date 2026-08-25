# Sprint 4 · Plan 09 - Configurable Status Semantics · Acceptance Criteria

**Source plan:** `09-configurable-status-semantics.md` (GRILLED + LOCKED 2026-06-24)
**Scope:** replace hardcoded status-KEY lookups across `crm`/`finance`/`ems` with tenant-configurable **semantic traits** attached to statuses. Code branches on `has_trait(status,'x')` / `status_for_trait(entity,tenant,scope,'x')`, NEVER on a status key. Keys/labels become freely tenant-renamable.

Format: each AC is independently verifiable (Given / When / Then). Grouped by slice. `[BE]` backend · `[FE]` frontend · `[E2E]` real-click · `[T]` unit/integration test. The Test Execution Report keys back PASS/FAIL/DEFERRED per AC id.

> **The bug this closes:** a tenant renamed Sales-Order `confirmed`→`approved`; every invoice-from-SO then `409`'d because the code branched on `key == "confirmed"`. With traits, the rename touches only the display label - the `assigns_doc_number` / `invoiceable` traits ride the status regardless of its key. **AC-09-30 is the exact reproduction-then-pass for that bug.**

> **Trait model (locked):** trait DEFINITIONS = a code-side, per-entity, module-owned registry declared at boot in `register_engine_entities` (mirrors StatusEntity / permissions-CSV / fact-source). Trait VALUES = a `traits_json JSON(none_as_null=True)` `list[str]` column on the core `statuses` table; resolution loads the entity's (cheap) status set and filters in Python. Two orthogonal guards: **cardinality** `single` (≤1 holder, auto-moves with explicit confirm) and **required** (≥1 holder; blocks clearing/deleting the last holder).

> **`is_system` retirement (locked):** the module domain entities (sales_order, invoice, payment, settlement, quotation, lead, ticket) are seeded `is_system=False` - keys/labels/flags become tenant-editable; protection moves to INVARIANT guards (exactly-one required-single, ≥1 required-multi, ≥1 `is_initial`, block-delete-last-holder). The platform `tenant` lifecycle entity keeps `is_system`+`platform_owned` UNTOUCHED (load-bearing, out of scope). Scoped graphs (`form_submission`, `project_participant`) carry **no** domain traits - untouched.

---

## Slice 1 - Core trait infra + Sales Order reference adopter (THIS PLAN)

### AC-09-01 - `traits_json` column on `statuses` [BE][T]
- **Given** the core Alembic migration ran, **when** inspecting the `statuses` table, **then** a `traits_json JSON(none_as_null=True)` column exists; every pre-existing row reads `NULL` (no implicit `[]` that would pass an `IS NOT NULL` filter - the `none_as_null=True` house rule).
- **Given** a status with `traits_json = ["assigns_doc_number"]`, **when** read back, **then** it deserializes to the Python `list[str]` `["assigns_doc_number"]`.
- The migration revision id is **≤ 32 chars** (`alembic_version.version_num` is VARCHAR(32)).

### AC-09-02 - `StatusTrait` registry + `register_status_trait` / `traits_for` [BE][T]
- **Given** `register_status_trait(StatusTrait(key, entity_type, label, description, cardinality, required, module))`, **when** registering, **then** it is **idempotent** (re-registering the same `(entity_type, key)` is a no-op, mirrors `register_status_entity`).
- **Given** the same `key` registered twice for the SAME entity with DIFFERENT cardinality/required, **then** a loud boot error is raised (no silent last-write-wins on a contract field).
- **Given** traits registered for `sales_order` and unrelated traits for another entity, **when** `traits_for('sales_order')` is called, **then** it returns ONLY the sales_order traits (strictly per-entity - common names like `editable` are redeclared per entity, never globally shared).

### AC-09-03 - `has_trait` / `status_for_trait` helpers [BE][T]
- **Given** a status carrying `traits_json=["invoiceable"]`, **when** `has_trait(status, 'invoiceable')`, **then** `True`; for a trait it lacks, **then** `False`; for a `None`/keyless status, **then** `False` (never raises).
- **Given** an entity+tenant+scope whose status set has exactly one status carrying `assigns_doc_number`, **when** `status_for_trait(db, entity_type, tenant_id, scope_id, 'assigns_doc_number')`, **then** it returns that status; resolution loads the tenant fork's set (falls back to the platform set), respects `scope_id`, and is tenant-scoped (a sibling tenant's status never returned).
- **Given** NO status in the set carries the trait, **then** `status_for_trait` returns `None` cleanly (never a 500 / never an exception) - the caller surfaces the friendly 409 (AC-09-08).
- `has_trait` / `status_for_trait` are **pure functions** with no rule-engine / workflow coupling (Q8 boundary - a future fact resolver wraps them).

### AC-09-04 - single-cardinality auto-move with explicit confirm [BE][FE][T]
- **Given** a `single` trait currently on Status A, **when** the same trait is set on Status B with `confirmMove=true`, **then** the trait is **atomically moved** - removed from A and added to B in one commit (A and B end with the correct `traits_json`).
- **Given** the same set WITHOUT `confirmMove` (and A already holds it), **then** the API returns a **409 `{requiresConfirm, trait, currentStatusId, currentStatusLabel}`** payload (no mutation) so the UI can show the confirm dialog; **confirm** replays with `confirmMove=true`.
- **Given** Status B already holds the trait (set it onto itself), **then** it is a no-op success (no spurious confirm).

### AC-09-05 - required guard blocks clearing the last holder [BE][T]
- **Given** a `required` trait whose ONLY holder is Status A, **when** a PATCH removes that trait from A (and assigns it to no one), **then** **422** with a friendly message ("At least one <entity> status must be marked '<trait label>'.").
- **Given** the same trait held by A and B (`multi+required`), **when** it is removed from A, **then** it succeeds (B still holds it).

### AC-09-06 - invariant guards replace `is_system` for domain entities [BE][T]
- **Given** the sales_order status set, **when** a status holding a **required** trait is deleted (without reassigning the trait), **then** the delete is **blocked (422)** with a message naming the trait.
- **Given** an attempt to delete the **last `is_initial`** status, **then** it is **blocked (422)** (a domain entity must always have a create-time initial).
- **Given** a `single+required` trait, the system enforces **exactly one** holder (≤1 via auto-move AC-09-04, ≥1 via AC-09-05).

### AC-09-07 - fork-bug fix: forked + copied rows are never `is_system` [BE][T]
- **Given** a tenant's FIRST edit forks the sales_order set via `status_service._fork`, **when** inspecting the forked rows, **then** every forked row has `is_system=False` (a tenant copy is never a system row) AND its `traits_json` is **copied verbatim** from the platform source (the tenant inherits the platform trait assignment).
- **Given** a scoped `copy_scope` (`scoped.py`), **when** materializing/copying a scope's graph, **then** the same `is_system=False` rule holds (the previously-verbatim copy is fixed).
- The pre-existing status-engine + tenant-lifecycle suites stay **green** (the `tenant` entity's `is_system`/`platform_owned` is untouched).

### AC-09-08 - runtime graceful degradation: friendly 409, never 500 [BE][T]
- **Given** an entity whose status set has NO holder for a required trait the code needs (`status_for_trait` returns `None`), **when** the dependent feature runs (e.g. invoice-from-SO needs `assigns_doc_number`), **then** the caller raises a **409** "No status is marked '<trait label>' for <entity> - configure it in Settings", **never a 500 / never a NoneType crash**.

### AC-09-09 - `GET /status-traits?entityType=` catalog endpoint [BE][T]
- **Given** an authenticated tenant user, **when** calling `GET /status-traits?entityType=sales_order`, **then** the response lists each registered trait as `{key, label, description, cardinality, required}` (the UI uses this to render toggles + decide single-vs-multi + label confirm copy).
- **Given** an entity that the caller's tenant does not have the owning module active for, **then** that module's traits are **absent** (`active_modules` filter, mirrors importer/terminology catalog gating).
- The endpoint requires only `get_current_user` (reading the catalog is not gated by a manage perm - editing values rides existing `statuses.manage`).

### AC-09-10 - frontend types extended + parity [FE][T]
- **Given** `types/status-engine.ts`, **when** inspected, **then** `StatusFlags` / `StatusNodeData` / `UpdateStatusInput` carry a `traits?: string[]` field; the status-engine service `updateStatus(id, {...traits})` sends them on the existing `PATCH /statuses/{id}`.
- A frontend type for the trait catalog (`StatusTraitDef {key,label,description,cardinality,required}`) exists and a `listStatusTraits(entityType)` service method fetches `GET /status-traits`.

### AC-09-11 - trait toggles in the status drawer (frontend-first mock) [FE][T]
- **Given** the status drawer open for a sales_order status, **when** rendered, **then** below the FLAG_FIELDS Switch list it shows a **Traits** section: each `multi` trait is a free `Switch`; each `single` trait renders as "make THIS the '<label>' status" (a single-select affordance), each labeled by the trait `label` (no instructional/hint copy - foolproof-UI).
- **Given** a `single` trait already held by another status, **when** the user toggles it ON here, **then** an **explicit confirm dialog** appears: "'<trait label>' is currently on '<Status A>'. Move it to '<Status B>'?" - Confirm performs the atomic move, Cancel leaves it unchanged.
- The drawer fetches `GET /status-traits?entityType=` to know which toggles + cardinality/required to render. **Built against the mock status-engine service first** (all states tunable with no backend).

### AC-09-12 - trait badges on canvas + table [FE][T]
- **Given** a status carrying traits, **when** rendered on `status-node.tsx` (canvas) and `status-table.tsx`, **then** a compact trait badge/pill per trait is shown (so the trait assignment is visible at a glance; truncation via `OverflowPills`/`ClampedText`, never bare `truncate`).

### AC-09-13 - warning chip on unsatisfied required trait [FE][T]
- **Given** a sales_order status entity whose set has a **required** trait with NO holder (e.g. a diverged-key tenant from backfill), **when** the entity detail / Flow tab header renders, **then** a **warning chip** is shown naming the missing required trait ("No status marked '<label>'"); fixing it (assigning the trait) clears the chip.

### AC-09-14 - sales_order trait catalog registered [BE][T]
- **Given** `modules/crm` boot, **when** `traits_for('sales_order')` is read, **then** it returns exactly: `assigns_doc_number` (single, required), `invoiceable` (multi, required), `lines_editable` (multi, optional) - each with a one-line description of what the code does.

### AC-09-15 - SO `lines_editable` predicate replaces `key=="draft"` [BE][T]
- **Given** `SalesOrderService.update` (was `crm/services.py:718` `_status_key_by_id(...) == "draft"`), **when** a line edit is attempted, **then** editing is allowed **iff** the SO's current status `has_trait('lines_editable')` - NOT iff its key is `"draft"`. A tenant that renamed `draft`→`Drafting` (keeping the trait) can still edit lines; a tenant that moved `lines_editable` onto a different state edits there.

### AC-09-16 - SO `assigns_doc_number` milestone replaces `key=="confirmed"` [BE][T]
- **Given** `SalesOrderService.transition` (was `crm/services.py:751` `target_key == "confirmed"`), **when** the SO transitions to a status that `has_trait('assigns_doc_number')` and `doc_number` is unset, **then** the gapless `next_number('sales_order')` is assigned + `confirmed_at` stamped **in the same commit** - the action code (numbering call) STAYS in the wrapper, only the GATE changed. The existing idempotency guard (`not so.doc_number`) is preserved (re-entering the state never re-numbers).

### AC-09-17 - SO `invoiceable` predicate replaces `key=="confirmed"` [BE][T]
- **Given** `SalesOrderService.create_invoice_from_so` (was `crm/services.py:779` `_status_key_by_id(...) != "confirmed"`), **when** invoicing is attempted, **then** it is allowed **iff** the SO's current status `has_trait('invoiceable')`, else **409** "Confirm the sales order before invoicing it." (message preserved; gate is the trait). The `with_for_update` SO row-lock (race guard) is preserved.

### AC-09-18 - SO `_status_key_by_id` / `_status_id_by_key` key-branches eliminated [BE][T]
- **Given** the SO service paths, **when** grepped, **then** NO sales_order code branches on a status `key` literal (`"draft"`/`"confirmed"`); all four sites (`services.py` ~718/747/751/779) route through `has_trait`/`status_for_trait`. (The generic `_status_key_by_id`/`_status_id_by_key` helpers may remain for non-semantic uses but are no longer the semantic gate.)

### AC-09-19 - per-module backfill stamps `traits_json` across ALL tiers [BE][T]
- **Given** existing sales_order statuses (platform `tenant_id NULL` + every tenant fork), **when** the crm-owned backfill runs in `bootstrap_modules` (and `install_tenant`/`update_tenant` for new/upgrading tenants), **then** each status matching the per-module `canonical_key→[trait_keys]` map (`draft→[lines_editable]`, `confirmed→[assigns_doc_number,invoiceable]`) gets its `traits_json` stamped; the backfill is **idempotent** (re-run = no change). Core never learns the crm semantics (map lives in `modules/crm`).
- **Given** a DIVERGED-key row (key NOT in the map - e.g. the manual `approved` hack), **then** its traits are left empty AND a **WARNING report** line is emitted (tenant / entity / status) - it is **NOT** auto-reset (no tenant data loss).

### AC-09-20 - bootstrap SEED gives new tenants traits from birth [BE][T]
- **Given** a freshly provisioned tenant with crm installed, **when** its sales_order statuses are seeded, **then** Draft carries `lines_editable` and Confirmed carries `assigns_doc_number`+`invoiceable` (the seed sets `traits_json`, not just labels) - no backfill step needed for new tenants.

### AC-09-30 - E2E: rename Confirmed→Approved, invoice-from-SO still succeeds [E2E]
- **Given** an authenticated `statuses.manage` user on the sales_order status entity, **when** they open the Confirmed status drawer in the editor and **rename its label to "Approved"** (key unchanged underneath; trait assignment unchanged) and save, **then** the canvas shows "Approved".
- **When** they then create a Sales Order, transition it to **Approved** (which still carries `assigns_doc_number` → doc number assigned), and **create an invoice from it**, **then** the invoice is created and **NO 409** is raised - the exact scenario broken today now PASSES. Verified at **375px AND 1280px** on a freshly rebuilt frontend.

---

## Slice 2 - Finance (LATER SLICE - in this UAC for contract completeness, NOT built in plan 09 slice 1)

### AC-09-21 - invoice trait catalog [BE][T] *(Slice 2)*
- **Given** `modules/finance` boot, **then** `traits_for('invoice')` returns `assigns_invoice_number` (single, required - assigns invoice_number+due_date at Issue), `financials_editable` (multi, optional - lines/amounts editable, was `draft`), `accepts_payment` (multi, required - a payment may be recorded, was Issued/Partially-Paid), plus finality traits `final_no_void`/`final_no_refund` (multi, optional - Void/Cancelled/Refunded). Predicates modeled POSITIVELY; `is_terminal` NEVER overloaded for finality.

### AC-09-22 - finance invoice key-branches gate-swapped [BE][T] *(Slice 2)*
- **Given** `finance/services.py` (~261/271/303/313/388) key-branches (`issued`/`void`/`paid`), **when** gate-swapped, **then** each routes through `has_trait`/`status_for_trait`; the milestone+predicate collapse onto ONE trait where it's the same status (Issued = `assigns_invoice_number`+`accepts_payment`). Existing idempotency guards preserved.

### AC-09-23 - payment success/failure TARGET traits [BE][T] *(Slice 2)*
- **Given** `payment_service.py` (~54/184/213/224/258), **then** the webhook flips route through `status_for_trait('payment', …, 'payment_success')` / `'payment_failure'` (single+required TARGETs) then the existing `status_machine.transition` (edge/path integrity unchanged); `final_no_recredit` (multi) replaces the `succeeded`-don't-re-credit predicate.

### AC-09-24 - settlement remittance traits [BE][T] *(Slice 2)*
- **Given** `settlement_service.py` (~145/181), **then** `captures_remittance`/`remitted` (single) replace the `remitted` milestone+predicate (collapsed onto one trait); the remittance-ref capture stays in the wrapper, gated by the trait.

### AC-09-25 - finance per-module backfill + seed + degradation [BE][T] *(Slice 2)*
- Mirrors AC-09-19/20/08 for finance entities (invoice/payment/settlement): finance-owned `canonical_key→traits` backfill across all tiers, seed-from-birth, diverged-key warning, friendly-409 degradation.

---

## Slice 3 - EMS ticket + CRM quotation/lead (LATER SLICE - contract-only here)

### AC-09-26 - ticket trait catalog + gate-swap [BE][T] *(Slice 3)*
- **Given** `modules/ems/services.py` (~613/1240/1248/1366/1867/1933/2006/2055) + `post_payment.py:70` ticket key-branches (`valid`/`void`/`transferred`/`checked_in`), **then** `traits_for('ticket')` = `counts_against_capacity` (multi+req, POSITIVE - on valid), `transferable` (multi), `scan_admissible` (multi), `checked_in` (single), `valid_after_payment` (single TARGET); all branches gate-swapped through `has_trait`/`status_for_trait`.

### AC-09-27 - quotation `convertible_to_so` trait [BE][T] *(Slice 3)*
- **Given** `crm/services.py:683` quotation `accepted` branch, **then** it routes through `has_trait('convertible_to_so')` (was the `accepted` predicate gating SO creation).

### AC-09-28 - lead `allows_event_creation` trait [BE][T] *(Slice 3)*
- **Given** `crm/services.py:296` lead `won` branch, **then** it routes through `has_trait('allows_event_creation')` (was the `won` predicate).

### AC-09-29 - ems per-module backfill + seed + degradation [BE][T] *(Slice 3)*
- Mirrors AC-09-19/20/08 for ticket/quotation/lead: ems/crm-owned backfill across all tiers, seed-from-birth, diverged-key warning, friendly-409 degradation. Scoped `project_participant` carries NO domain traits (untouched).

---

## Definition-of-Done gate (every slice)
1. **Mock swapped to real** - the trait-toggle UI is built frontend-first against the mock status-engine service, then the boundary swaps to `.real` and is verified showing real trait data. No `PHASE 1 MOCK` reaches the user-perspective QA pass.
2. **Backfill existing rows/tenants** - `traits_json` is stamped on EVERY matching status across the platform tier AND every tenant fork (not seed-if-absent only); diverged-key rows warned, never auto-reset.
3. **No hardcoded tenant-editable keys** - zero `key == "<literal>"` semantic branches remain in the gate-swapped paths (grep-verified).
4. **Perm-grant sweep** - **N/A** (no new permission; trait edits ride existing `statuses.manage`, catalog read rides `get_current_user`). State it explicitly in the report.
5. **Real-data user-perspective verify** - AC-09-30 verified end-to-end with real data at **375px AND 1280px** on a freshly REBUILT frontend (`rm -rf .next && npm run build`) against correctly-owned ports (3001 FE / 8001 Foundryx BE).
