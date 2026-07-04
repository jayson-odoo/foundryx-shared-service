# Sprint 4 · Plan 03 — Status Engine: Derived / Computed Status (foundation enhancement)

**Status:** GRILLED (2026-06-18) — design locked, ready to slice + build.
**Branch (future):** `sprint-4/03-derived-status`
**Type:** Core engine enhancement (status engine v2). **Prerequisite for** Cluster D (participant `Checked-in`) + Cluster F (invoice `Paid`/`Partially Paid`).
**Source:** `01-...-grill-decisions.md` §6.7 + this grill.

---

## Headline

"A status that sets itself from related records" recurs: **invoice.Paid** ← SUM(payments), **participant.Checked-in** ← all admission tickets checked in, project status ← milestones. The engine **already** has ~90% of the machinery — so this is **wiring + a re-eval trigger + one new column**, not a new engine:

| Already exists | Reused for |
|---|---|
| `status_transitions.conditions_json` (rule tree) | the derivation rule on an auto-edge |
| `transition(db, …, actor=None, commit=False)` | firing the derived transition system-side |
| `FactDef` with a DB-querying resolver (`record.userCount` COUNT) | aggregate facts (SUM/COUNT over children) |
| `entity_events` bus + `register_event_subscriber` (isolated commits) | event-driven re-eval |
| `workflow_origin` chain + `MAX_RUN_DEPTH` loop-guard | cascade/loop safety |
| workflow scheduler beat | time-based re-eval sweep |

**One new column** (`status_transitions.trigger_mode`), **two new code-side registries/helpers**, **no new tables**.

---

## Locked decisions (this grill)

1. **Mechanism = auto-edges (G1).** `status_transitions.trigger_mode ∈ {manual, auto}` (default `manual`). An **auto-edge** is fired by the engine (not a user) when its `conditions_json` becomes true. A "derived status" = a state whose incoming edges are all `auto`. Reuses `conditions_json` + `transition()` wholesale.

2. **Dependency = code-side registry (G2).** `app/status_engine/derived.py`:
   ```python
   @dataclass(frozen=True)
   class DerivedTrigger:
       owner_entity: str                       # 'invoice'
       trigger_entity: str                     # 'payment'  (== owner_entity for self-triggers)
       resolve_owners: Callable[[Session, str, dict], list]   # (db, tenant_id, event) -> [owner records]
   def register_derived_trigger(t: DerivedTrigger) -> None      # idempotent, mirrors register_status_entity
   ```
   A bus subscriber maps each domain event → registered owners → re-eval. Core/modules declare at boot.

3. **Aggregate facts = helper + seeded system edges + tenant-authorable (G3).** `app/rule_engine/aggregates.py`:
   ```python
   def aggregate_fact(key, label, child_model, fk_attr, op='count'|'sum'|'min'|'max'|'avg',
                      column=None, where=None) -> FactDef   # tenant-scoped resolver
   ```
   Registered on the owner's rule fact source → the **RuleBuilder lists them**, so auto-edge conditions are authored like any conditional edge. Core/modules **SEED canonical derived edges as `is_system`** (locked — a tenant can't redefine "Paid"); tenants **may add their own** auto-edges where aggregate facts exist (two-tier discipline).

4. **Re-eval triggers = events + scheduler (G4).** Event-driven (child/self via the bus) for aggregate-fact derivations (instant); **scheduler sweep** (reuse the workflow beat) for **time-conditioned** auto-edges (`Overdue` when `due_date<now`) — only entities flagged as having time-based auto-edges, scoped query (no full scan).

5. **Cascade to fixpoint (G5).** From the current status, evaluate outgoing AUTO edges in `sort_order`; fire the FIRST passing via `transition()`; re-eval from the new status; repeat until none pass. **Hop-capped + no-revisit** (no oscillation). One big payment cascades Issued→Partially Paid→Paid in a single settle. Each hop = a real `transition()` (notifications + `status_changed` event emitted).

6. **Coexistence + override + UI (G6).** Auto edges: **excluded** from `available_transitions`/`fireable_edge_ids`/action buttons; **cannot carry `transition_roles`** (system-fired — 422 at save); **must carry `conditions_json`** (an unconditioned auto-edge would fire always — 422). Rendered **distinct on the canvas** (dashed + ⚡/rule badge). A derived state may ALSO have a **separate role-gated MANUAL edge for override** (Write-off→Paid, Force check-in). **Pull-back is the author's choice:** a state with NO outgoing auto-edges is stable (won't be re-derived).

7. **Run safety (G7).** Re-eval runs in the **after-commit drain via an isolated subscriber** — each derivation in its OWN commit, failure logged + rolled back, **NEVER 500s the triggering write** (same mandate as workflow dispatch). **Loop-safe** via the existing `workflow_origin` chain + depth cap (tag re-eval origin `derived`; an auto transition's emitted `status_changed` can't infinitely re-enter). **Fail-closed** on erroring/missing aggregate facts (no transition). Works on **scoped** (participant tier-2) + **unscoped** (invoice) graphs. Eventual (brief stale window, like workflow reactions).

---

## Core engine surface

**`reevaluate(db, entity_type, record, *, tenant_id, origin=None) -> int`** (new, `status_machine` or `app/status_engine/derived.py`):
- guard: entity has a status machine; resolve tier/scope (reuse `_tier_and_scope`).
- loop: gather outgoing edges where `trigger_mode='auto'` from `record`'s current status, sorted by `sort_order`; resolve owner facts once (incl. aggregates, only the keys the trees read via `collect_fact_keys`); fire the first whose `evaluate(conditions_json, facts)` is true via `transition(..., actor=None, commit=False)`; record the visited state; repeat until none pass / hop-cap / revisit. Returns hops fired.

**Bus subscriber** (registered at boot via `register_event_subscriber`):
- `_on_event(db, ev)`: skip if `ev.source` origin is `derived` (avoid self re-entry). For `DerivedTrigger`s whose `trigger_entity == ev['entity_type']` (and owner self-triggers on created/updated/status_changed), call `resolve_owners(db, ev['tenant_id'], ev)` → `reevaluate(...)` each, origin=`derived`. Isolated commit per the existing `_notify_subscribers` pattern.

**Scheduler** `reevaluate_time_based(db)` (new beat task, 60s): for each registered owner entity flagged `has_time_auto_edges`, query records currently in a status that has an outgoing time-conditioned auto-edge AND whose date fact would now pass (coarse pre-filter, e.g. `due_date < now`), `reevaluate` each. Failure-isolated + per-tenant scoped.

**Save validation** (`status_transitions` create/update): `trigger_mode='auto'` ⇒ `conditions_json` non-empty AND `transition_roles` empty, else 422. `available_transitions`/`fireable_edge_ids` add `trigger_mode != 'auto'` to their filters.

## Data model

- **`status_transitions.trigger_mode`** VARCHAR NOT NULL DEFAULT `'manual'` (core Alembic migration; add `import app.models.utc_datetime` rule N/A — no UTCDateTime). Optional index `(from_status_id, trigger_mode)` for the re-eval edge lookup.
- **No new tables** — `DerivedTrigger` registry + aggregate facts are code-side.

## Frontend

- **Edge editor (TransitionDrawer):** a **Trigger** toggle (Manual | Automatic). Automatic → conditions section required (RuleBuilder), roles section hidden, label optional. Mirror `trigger_mode` in `types/`.
- **FlowCanvas:** render `auto` edges distinctly (dashed + ⚡ + condition summary); exclude them from the canvas action/context menus. Status node shows an "auto" indicator when it has incoming auto-edges only.
- **StatusBadge / detail:** derived states render read-only (no manual transition button), consistent with the action-button exclusion.

## Slices (frontend-first where UI exists → backend → TDD → E2E)

1. **Core auto-edge engine** — `trigger_mode` column + migration; `reevaluate()` cascade (fixpoint/sort_order/hop-cap/no-revisit); save-validation; exclude auto from `available_transitions`/`fireable_edge_ids`. Tests on a **synthetic test entity** (mirror `tests/test_status_engine.py`'s `ticket`).
2. **Derived dependency wiring** — `DerivedTrigger` registry + bus subscriber (isolated, loop-guarded, fail-closed) + `aggregate_fact()` helper. Tests: child event re-evals owner; self-trigger; isolation (broken derivation can't 500 the child write); loop-guard depth; aggregate count/sum tenant-scoped; scoped-graph derivation.
3. **Time-based sweep + frontend** — scheduler `reevaluate_time_based` beat; edge Trigger toggle + canvas auto-edge rendering + read-only derived badge. E2E: author an auto-edge with an aggregate condition on the synthetic entity; drive a child change; assert the owner auto-advances.
4. **Configurable aggregate whitelist** (post-merge refinement, grilled — see "Slice 4" below) — generalize the hand-declared `aggregate_fact()` list into a declarative `AggregatableRelation` whitelist (per-column op whitelisting) that auto-generates both the rule facts AND the cross-entity `DerivedTrigger`. EMS project participant-count rides it. RuleBuilder unchanged (Option A).
5. **EMS Event Details edit** (enabler, grilled — see "Slice 5" below) — a Project had no edit surface at all, so the date facts now exposed for derived-status conditions (`start_date`/`end_date`/`event_validity_end`) were unsettable/invisible. Add a full edit surface (backend update + `PATCH` + a Details tab) so date-based derived status is usable end-to-end. The 3 date columns become date-only `Date` (calendar dates, not instants).
6. **Relative-to-now date conditions + admin date-simulation** (grilled — see "Slice 6" below) — a date-field-vs-FIXED-literal condition is static (event-driven only); genuinely time-dependent conditions need "now". Auto-generate `Days since`/`Days until <field>` **number** facts (computed against an injectable clock) so the user authors time windows with the existing `>/≥/</≤` operators (e.g. "close 2 days after end_date" = `Days since End Date ≥ 2`). Plus an **admin "Simulate date"** UI to fast-forward/backtrack "now" (dry-run/apply) and test without waiting. Retires the `eventEnded` boolean.

## Slice 4 — Configurable aggregate whitelist (grilled 2026-06-19)

**Problem.** Slice 2 shipped `aggregate_fact()` but each aggregate was **hand-declared** per owner (e.g. EMS listed `aggregate_fact("record.participantCount", …)` + a separate hand-written `DerivedTrigger`). Adding an aggregate meant editing three places (fact list, trigger, child emit). Goal: ONE declarative relation declaration drives facts + trigger, with per-field op whitelisting, so the platform is configurable without auto-exposing schema (D7 holds — the relation/op stay code-side; only the threshold is UI-authored).

**Decision = Option A (auto-generated facts), grilled.** Code declares relations; the platform auto-generates one rule `FactDef` per (relation × op × column). The RuleBuilder is **unchanged** — aggregates appear as ordinary pickable number/date facts (`"Participants · Count"`, `"Participants · Sum of Fee"`). No new condition kind, no schema/evaluator change, no frontend change. (Option B, an explicit method/field composer in the builder, was rejected — same whitelist, far more surface, marginal UX gain.)

**Design (all decisions locked):**
- **Declaration site (Q1):** new field `StatusEntity.aggregatable_relations: Sequence[AggregatableRelation]` (alongside `model`/`fact_attrs`/`aggregate_facts`). `AggregatableRelation` + `AggColumn` dataclasses live in `app/rule_engine/aggregates.py` next to `aggregate_fact`. `register_status_entity`'s existing auto-register seam expands relations → `FactDef`s and appends them to the `record:<type>` source. `aggregate_facts` survives as the **escape hatch** for one-off/`where=`-filtered aggregates.
- **Fact-key scheme (Q2):** `record.<relationKey>.<op>` (count) / `record.<relationKey>.<op>.<columnName>` (column ops) — every segment a **stable code-side identifier** (relationKey, op vocabulary, column attr), so a label rename/reorder never orphans a saved condition. Migrate the one existing key `record.participantCount` → `record.participants.count` (no stored condition references it).
- **`AggColumn` shape (Q3):** `AggColumn(name, label, type, ops⊆{sum,avg,min,max})` (count is the relation-level flag, not a column op). Generated `type`: count/sum/avg → `number`; min/max → the **column's** type (date-min stays a date → date operators). Generated label: `"<relation.label> · <Op> of <column.label>"`; count = `"<relation.label> · Count"`. Registration validates each op ∈ allowed set + column exists on `child_model` (loud `ValueError`, like `infer_facts`).
- **Filtered/scoped aggregates DEFERRED (Q4):** v1 = unfiltered count + column ops. "Count of *Confirmed* participants" = **BL-112** (`aggregate_fact(where=)` is the interim code-side escape hatch).
- **Auto-generated trigger (Q5):** the relation declares `child_entity_type` (the event-match string, e.g. `"project_participant"`); the expander registers the facts **and** a `DerivedTrigger(owner_entity, trigger_entity=child_entity_type, resolve_owners=load child-by-record_id → owner-by-fk_attr)`. EMS's hand-written `_register_derived`/`_project_owners` is removed. **Hard contract (documented, not auto-wirable):** the child's write path must `notify_entity_event(...)` or the cascade can't fire — it lives in the child service, not the relation. `register_derived_trigger` stays public for non-relation cross-entity cases.
- **Frontend (Q6):** ZERO change. Aggregates share the entity's one source group, disambiguated by label; `type` drives the existing per-type operator set. Verified: FE `FactDef = {key,label,type,source,sourceLabel,options}` — generated facts populate all of it. Relation sub-grouping in the picker = future polish (**BL-113**), not v1.
- **Validation (Q7):** none new at the API layer — generated facts are in `fact_map(sources)`, so `validate_tree` covers op-for-type/value exactly as for scalars. Registration-time expander checks only.
- **Coexistence/cleanup (Q8):** relations are the declarative norm; `aggregate_facts` is the rare escape hatch; the hand-written EMS trigger collapses into the relation; migrate the one key.

**Tests (Q9):** backend only (frontend unchanged). Expander unit on the synthetic ticket+line harness (count/column facts, key/label/type derivation, op whitelist honored, bad-op + missing-column `ValueError`); auto-generated trigger fires the cascade (AC-03-11 via a relation, not hand-registered); tenant-scope (sibling-tenant child excluded); `/rule-facts` exposes generated keys; EMS-level — project exposes `record.participants.count` + adding participants past the threshold auto-advances the event. One E2E (Event Flow): API-build the auto edge `Participant count >= N` (dodge flaky canvas drag), **real-click** adding participants → assert the event flips to the derived state.

## Slice 5 — EMS Event Details edit (grilled 2026-06-19)

**Problem.** A Project (Event) had **no edit surface**: `ProjectOut` exposed only `title/brief/statusId/createdAt`, there was no `ProjectUpdate` schema / `ProjectService.update` / `PATCH /ems/projects/{id}`, and the event detail had only Participants + Eligibility-flow tabs. Slice 1–4 exposed `start_date`/`end_date`/`event_validity_end` as rule facts for date-based derived status — but they were unsettable + invisible (a foolproof gap: authorable condition, unsettable field). This slice adds the edit surface so date conditions work end-to-end.

**Design (all decisions locked, grilled):**
- **Single Edit toggle reconciles both edits (Q1).** The event detail's existing global Edit toggle already drives the Eligibility-flow layout; the new Details tab's fields join it. `isDirty = form.formState.isDirty || layoutDirty`; `onSave` PATCHes the project **iff** the form is dirty AND calls `layoutController.save()` **iff** the layout is dirty (each branch guarded — no no-op PATCH); `onCancel` resets both. One Edit = edit the whole event. Mirrors the Profile detail for the field half (`profile-detail.tsx` is the reference).
- **Editable vs immutable (Q2).** Editable: `title`, `brief`, `notes`, `domain_name`, `start_date`, `end_date`, `event_validity_end`. **Immutable** (NOT in `ProjectUpdate`): `template_id`/`type_id` (the eligibility graph + roles/segments are copied FROM the template at create — re-pointing orphans them), `client_id` (Cluster B), `status_id` (only via the transition path). `ProjectOut` grows to expose the editable set + `typeId` (read-only).
- **Date-only `Date` columns (Q3).** The 3 date columns retype `UTCDateTime → Date` — an event's start/end is a **calendar date, not an instant**, so `Date` is the correct type and this does NOT violate the UTCDateTime-only mandate (which targets zone-bearing timestamps). Migration = a new per-module ems Alembic rev after `0001_ems_baseline`: `ALTER COLUMN … TYPE date USING (col::date)`, nullable (Postgres; SQLite tests `create_all` pick up `Date` directly). Wire = `"YYYY-MM-DD"` (no `Z`/time). **FE date-display gotcha:** render the calendar date DIRECTLY — never through the tz-aware `formatDate`/`parseUtc` (which treats `"2026-01-01"` as UTC-midnight and can shift the day in the session tz). `<input type="date">` (the house pattern — Form Engine + share-dialog), value = the date string as-is.
- **Date ordering validation (Q3).** When both present: `end_date >= start_date` and `event_validity_end >= end_date` → **422** server-side (the boundary) + inline client mirror. Each date independently optional/clearable (PATCH-merge; explicit `null` clears).
- **List columns (Q4).** Events list gains **Start** + **End** columns (sortable, in the default set, hideable via column prefs); `event_validity_end` + notes/domain stay detail-only. `exportColumns` gains `startDate`/`endDate` (round-trip parity). `_column_value`/exporter handle the new date columns.

**Backend:** `ProjectUpdate` schema (all-optional camelCase, date fields typed `date`); `ProjectService.update(tenant_id, pid, data)` — PATCH-merge, ordering 422, ignores immutable keys; `PATCH /ems/projects/{id}` gated `projects.manage`; `ProjectOut` + the list/export grow the fields. **Frontend:** a **Details tab** on `event-detail.tsx` (mirrors `profile-detail.tsx`) — read/edit FormRow fields incl. 3 `<input type="date">`; `emsService.updateProject(id, body)`; combined dirty/save with the flow layout per Q1. Events list config + page gain the Start/End columns.

**Tests (Q6):** backend (extend `test_ems_spine`) — update PATCH-merge (fields + dates), ordering 422, date-only round-trip (`"YYYY-MM-DD"`, no time), immutable `template_id` ignored, `ProjectOut` exposes fields, perm gate. **No FE unit** (no Profile-detail test to mirror; the Resource-form shell tests + E2E cover it). **One E2E** in `derived-status.spec.ts` — open an event → Edit → set Start/End + brief → Save → reload shows them + the list shows Start/End columns (real clicks).

## Slice 6 — Relative-to-now date conditions + admin date-simulation (grilled 2026-06-19)

**Problem.** A date-field-vs-FIXED-literal condition (`End Date after 2026-06-23`) is **static** — both operands fixed, truth never changes with the clock, so it only fires on save and the time sweep is useless for it. A genuinely time-dependent condition must compare to **now** (e.g. "close the project 2 days after end_date" = `today ≥ end_date + 2`, a settlement window). The rule engine is substitution-only (no eval, anti-SSTI) and has **no "now" literal**, so today the only time-dependent construct is a hand-wired computed boolean per field (`eventEnded`). And you can't author/observe any of this without an admin way to move "now" — waiting for real time is not testable.

**Decision (grilled):**
- **Mechanism = computed day-count NUMBER facts, not new operators (Q2).** Auto-generate, per date `fact_attr`, two facts: **`Days since <field>`** = `(today − field).days` and **`Days until <field>`** = `(field − today).days`. The user authors time windows with the **existing numeric operators** (`>/≥/</≤/=`) on a plain number input — full comparator coverage, **zero new operators, zero `types/rules.ts` parity work**. "close 2 days after end" = `Days since End Date ≥ 2`; "today > end" = `Days since End Date > 0`; "lock 3 days before start" = `Days until Start ≤ 3`. Time-dependent (truth flips as the clock moves) → the sweep re-checks.
- **"now" via a clock contextvar (Q1, revised).** `app/clock.py now()` returns a contextvar value or real `datetime.now(timezone.utc)`; `with clock_override(as_of): …` (reset in `finally`). **Only the day-count fact resolvers read the clock** — `evaluate()` stays pure (it compares already-resolved numbers), stored timestamps/transition times keep real `now`. **`eventEnded` is retired** (it becomes `Days since End Date ≥ 0`), removing the one non-injectable clock.
- **Auto-generation scope (Q3).** Every date fact an entity declares yields its base date fact (fixed-date `before/after/between`, unchanged) **plus** the two day-count facts. Stable keys `record.<attr>.daysSince` / `.daysUntil`; labels `"Days since <Label>"`. `fact_attrs` is the whitelist that bounds it. Being **swept** still needs the entity's `has_time_auto_edges` + `time_candidates` (Project's broadened to "any date field set").
- **Admin simulation = per-call `as_of`, NOT a global clock (Q4).** `POST /status-entities/{entityType}/simulate { asOf, apply }` → `with clock_override(as_of)` runs `simulate_entity_sweep(db, entity_type, tenant_id, as_of, apply)`: for each `time_candidates` filtered to the caller's tenant, snapshot before → `reevaluate` → capture after → collect changed `(record, from, to)`. **Dry-run (default)** rolls back — nothing persists, no events/notifications fire (they only drain on commit) → side-effect-free preview. **`apply=true`** commits (transitions + events fire normally). Tenant-scoped, gated **`statuses.manage`**. No persisted/global clock = no prod foot-gun; the production 60s beat is unchanged (default real clock).
- **Admin UI (Q5).** A **"Simulate date"** toolbar button on the generic `status-entity-detail.tsx` (every status entity — Project now, invoices later), shown when the entity is time-capable (`hasTimeAutoEdges` flag on the graph/entity wire) → a **dialog**: date picker (`as_of`) · **Preview** (dry-run → table of would-advance records `title · from → to`, capped + total count) · **Apply** (confirms, commits). Gated `statuses.manage`.

**Backend:** `app/clock.py` (contextvar + `now()` + `clock_override`); `infer_facts` (or the registration seam) emits the two day-count facts per date attr reading `clock.now()`; `simulate_entity_sweep` in `scheduler.py`; `POST /status-entities/{entity}/simulate`; `hasTimeAutoEdges` on the status-entity/graph wire; remove the EMS `eventEnded` FactDef + broaden Project `time_candidates`. **Frontend:** status-engine service `simulate(entityType, asOf, apply)`; the Simulate-date dialog on `status-entity-detail`; visibility off `hasTimeAutoEdges`.

**Tests (Q7):** backend — clock override+reset; day-count facts auto-gen + resolver math + override changes value + numeric ops evaluate; `simulate_entity_sweep` dry-run persists nothing / apply persists / tenant-scoped / fast-forward fires & backtrack doesn't; endpoint perm gate; `eventEnded` retired. **Light FE** component test for the dialog (+ service). **One E2E** (`derived-status.spec.ts`): author `Days since End Date ≥ 2` on Project → open Simulate date → pick a date ≥2 days past an event's end → Preview lists it → Apply → status advances (real clicks). **No operator parity work** (reusing numeric operators).

## First consumers (wired in their cluster plans, NOT here)
- **participant `Checked-in`** ← `checkedInTicketCount == admissionTicketCount` (Cluster D, `05`).
- **invoice `Partially Paid`/`Paid`** ← `amountPaid` vs total; `Overdue` ← time (Cluster F).
This plan ships the engine + synthetic-entity tests; consumers register their `DerivedTrigger` + aggregate facts + seed their system auto-edges in their own plans.

## Open risks / backlog
- **Burst coalescing:** many child events (rapid payments) → many re-evals; each is cheap + idempotent (fixpoint), but **coalesce/debounce per (owner, tick)** = optimization backlog.
- **Two-tier fork** of tenant-authored auto-edges (platform default vs tenant fork) follows the existing status two-tier; confirm fork copies `trigger_mode` + conditions (the `copy_scope`/fork paths must carry the new column).
- **`copy_scope`/branding fork parity:** add `trigger_mode` to every place that copies edge rows (`scoped.py copy_scope`, two-tier fork) — same lesson as the flag-copy list.
- Derived **min/avg** aggregates + `where`-filtered facts beyond count/sum = extend the helper as needed.
- UI: a "why did this auto-fire?" explainer (show the passing condition) = nice-to-have.
