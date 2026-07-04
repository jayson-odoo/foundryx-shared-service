# Sprint 4 · Plan 03 — Derived / Computed Status · Acceptance Criteria

**Source plan:** `03-status-engine-derived-status.md` (GRILLED 2026-06-18)
**Scope:** the status-engine v2 enhancement only — `trigger_mode` auto-edges, the `DerivedTrigger` registry, aggregate facts, event + scheduler re-eval, frontend authoring. **First domain consumers (participant Checked-in, invoice Paid) are validated in their own cluster plans (05/07), NOT here** — this plan ships the engine + synthetic-entity proof.

Format: each AC is independently verifiable (Given / When / Then). Grouped by slice. `[BE]` backend, `[FE]` frontend, `[E2E]` real-click, `[T]` unit/integration test.

---

## Slice 1 — Core auto-edge engine

### AC-03-01 — `trigger_mode` column [BE][T]
- **Given** the core Alembic migration ran, **when** inspecting `status_transitions`, **then** a `trigger_mode VARCHAR NOT NULL DEFAULT 'manual'` column exists; every pre-existing edge reads `'manual'`.
- An index on `(from_status_id, trigger_mode)` exists for the re-eval edge lookup.

### AC-03-02 — auto-edge save validation: conditions required [BE][T]
- **Given** an edge create/update with `trigger_mode='auto'` and **empty** `conditions_json`, **when** saved, **then** **422** ("an automatic edge must carry conditions") — an unconditioned auto-edge that would fire always is rejected.

### AC-03-03 — auto-edge save validation: roles forbidden [BE][T]
- **Given** an edge with `trigger_mode='auto'` and a non-empty `transition_roles`, **when** saved, **then** **422** (system-fired edges cannot carry role gating).
- **Given** a `trigger_mode='manual'` edge with roles, **then** it saves normally (no regression).

### AC-03-04 — auto edges excluded from user transition surfaces [BE][T]
- **Given** a record whose current status has an outgoing `auto` edge, **when** calling `available_transitions` / `fireable_edge_ids`, **then** the auto edge is **absent** from both results.
- **Manual** edges from the same status still appear.

### AC-03-05 — `reevaluate()` fires the first passing auto edge [BE][T]
- **Given** a synthetic test entity at status A with auto edges A→B (conditions false) and A→C (conditions true), sorted by `sort_order`, **when** `reevaluate()` runs, **then** it fires **A→C** via a real `transition(actor=None, commit=False)`; A→B is skipped.
- **Given** no outgoing auto edge passes, **then** `reevaluate()` returns 0 and the status is unchanged.

### AC-03-06 — cascade to fixpoint, sort_order, no oscillation [BE][T]
- **Given** auto edges Issued→PartiallyPaid (passes) and PartiallyPaid→Paid (passes), **when** `reevaluate()` runs once, **then** the record advances Issued→PartiallyPaid→**Paid** in a single call (cascade to fixpoint).
- Each hop fires a real `transition()` (a `status_changed` event is emitted per hop; notifications fire per hop).
- **Given** a cyclic/oscillating auto-edge config, **then** the cascade is **hop-capped + no-revisit** — it terminates, never loops a visited state.

### AC-03-07 — first-passing wins on a passing-pair [BE][T]
- **Given** two auto edges from the same status both pass, **when** `reevaluate()` runs, **then** only the one with the **lower `sort_order`** fires; the other is ignored that hop (re-evaluated from the new state).

### AC-03-08 — manual override edge to a derived state coexists [BE][T]
- **Given** a derived state Paid with an incoming `auto` edge AND a separate role-gated **manual** edge (e.g. Writeoff→Paid), **when** an authorized user lists transitions from Writeoff, **then** the manual Paid edge appears and is fireable; the auto edge remains hidden.

### AC-03-09 — a state with no outgoing auto edge is stable [BE][T]
- **Given** a record reaches a status with **no** outgoing auto edges, **when** a later re-eval runs, **then** the record is **not** pulled back / re-derived (author-chosen stability).

---

## Slice 2 — Derived dependency wiring (registry + bus + aggregates)

### AC-03-10 — `DerivedTrigger` registry [BE][T]
- **Given** `register_derived_trigger(DerivedTrigger(owner_entity, trigger_entity, resolve_owners))`, **then** registration is **idempotent** (re-registering the same trigger is a no-op, mirrors `register_status_entity`).

### AC-03-11 — child event re-evaluates the owner [BE][T]
- **Given** a registered trigger (owner `invoice`, trigger_entity `payment`) and a derived Paid auto-edge, **when** a `payment` is created such that the aggregate condition now passes, **then** the bus subscriber resolves the owning invoice via `resolve_owners` and `reevaluate()` advances it to Paid.

### AC-03-12 — self-trigger on owner created/updated/status_changed [BE][T]
- **Given** a trigger where `trigger_entity == owner_entity`, **when** the owner record is created/updated, **then** its own auto edges are re-evaluated.

### AC-03-13 — aggregate facts available to RuleBuilder [BE][T]
- **Given** `aggregate_fact(key, label, child_model, fk_attr, op, column, where)` registered on the owner's rule fact source, **when** the rule fact list is fetched, **then** the aggregate fact (count/sum/min/max/avg) appears and is usable as an auto-edge condition; its resolver is **tenant-scoped**.
- count and sum aggregates compute correctly over only the owner's children, scoped to the owner's tenant (a sibling tenant's children never contribute).

### AC-03-14 — re-eval is failure-isolated, never 500s the triggering write [BE][T]
- **Given** a derivation that raises (broken aggregate / bad rule), **when** the child write commits, **then** the child write **succeeds**; the derivation error is **logged + rolled back in its own commit**; the triggering request returns 2xx (same mandate as workflow dispatch).

### AC-03-15 — fail-closed on missing/erroring aggregate facts [BE][T]
- **Given** an auto edge whose condition references a missing or erroring aggregate fact, **when** `reevaluate()` runs, **then** **no transition fires** (fail-closed; never a wrong-direction move).

### AC-03-16 — loop guard via origin chain + depth cap [BE][T]
- **Given** re-eval tagged origin `derived`, **when** an auto transition emits its own `status_changed`, **then** the subscriber **skips** events whose origin is `derived` (no self re-entry); a cascade chain is bounded by `MAX_RUN_DEPTH`.

### AC-03-17 — works on scoped graphs [BE][T]
- **Given** a **scoped** entity (e.g. participant tier-2, scope = project), **when** a child event triggers re-eval, **then** the correct scoped owner graph is resolved (`_tier_and_scope`) and the derivation fires on the right per-scope graph — a record can never be moved onto another scope's graph.

### AC-03-18 — fork / copy carries `trigger_mode` [BE][T]
- **Given** a two-tier fork (platform default → tenant fork) or a `copy_scope` materialization, **when** edges are copied, **then** each copied edge retains its `trigger_mode` **and** `conditions_json` (regression guard — the flag-copy-list lesson).

---

## Slice 3 — Time-based sweep + frontend

### AC-03-19 — scheduler re-eval beat for time-conditioned auto edges [BE][T]
- **Given** an owner entity flagged `has_time_auto_edges` and a record in a status with a time-conditioned auto edge (e.g. Overdue when `due_date < now`), **when** `reevaluate_time_based(db)` runs (60s beat), **then** records whose date fact now passes advance; the query is **scoped (coarse pre-filter)**, not a full-table scan, and per-tenant.
- The sweep is failure-isolated (one bad record never aborts the batch).

### AC-03-20 — edge editor Trigger toggle [FE]
- **Given** the TransitionDrawer, **when** authoring an edge, **then** a **Trigger** toggle (Manual | Automatic) is present; selecting **Automatic** makes the conditions (RuleBuilder) section **required** and **hides** the roles section; the label becomes optional.
- `trigger_mode` is mirrored in `types/` (parity-pinned).

### AC-03-21 — canvas renders auto edges distinctly [FE]
- **Given** an `auto` edge on the FlowCanvas, **then** it renders **dashed + ⚡/rule badge** with a condition summary, and is **excluded** from the canvas action/context menus.
- A status whose incoming edges are all `auto` shows an "auto/derived" indicator on its node.

### AC-03-22 — derived state read-only in detail / badge [FE]
- **Given** a record in a derived state (no outgoing manual edges to advance), **when** viewing the detail / StatusBadge, **then** **no manual transition button** is offered for the auto path (consistent with the backend exclusion); any manual override edge still renders its own button.

### AC-03-23 — end-to-end auto-advance [E2E]
- **Given** the synthetic test entity with an authored auto-edge carrying an aggregate condition, **when** a user drives a child change through the UI that makes the condition pass, **then** the owner record **auto-advances** to the derived status without a manual transition, and the new status is visible on refresh.

---

## Cross-cutting / non-functional

### AC-03-24 — no new tables [BE]
- **Given** the merged migration set, **then** the ONLY schema change is `status_transitions.trigger_mode` (+ its index); `DerivedTrigger` registry and aggregate facts are **code-side** (no new tables).

### AC-03-25 — existing status suite stays green [T]
- **Given** the full pre-existing `tests/test_status_engine.py` + tenant-lifecycle suite, **when** run after this plan, **then** all pass (the load-bearing tenant lifecycle is untouched).

### AC-03-26 — eventual consistency window acknowledged [BE]
- **Given** a child write, **then** the derived owner status updates in the **after-commit drain** (brief stale window, like workflow reactions) — not synchronously inside the child transaction.

### AC-03-27 — responsive authoring surfaces [FE]
- **Given** the TransitionDrawer + FlowCanvas auto-edge rendering, **then** both are usable + non-clipped at **375px** and **1280px** (mandate).

---

## Slice 4 — Configurable aggregate whitelist (grilled 2026-06-19)

### AC-03-28 — `AggregatableRelation` declares aggregates + per-column ops [BE][T]
- **Given** `StatusEntity(aggregatable_relations=[AggregatableRelation(key, label, child_entity_type, child_model, fk_attr, count=True, columns=[AggColumn(name, label, type, ops=[...])])])`, **when** the entity is registered, **then** for each relation the platform generates a `record:<type>` fact for `count` (when `count=True`) and one per `(column × op)` for `op ∈ column.ops` (`ops ⊆ {sum,avg,min,max}`), appended to the owner's existing `record:<type>` source — alongside scalar `fact_attrs` and any raw `aggregate_facts` (escape hatch).

### AC-03-29 — stable generated keys [BE][T]
- **Given** a generated aggregate fact, **then** its key is `record.<relationKey>.<op>` (count) or `record.<relationKey>.<op>.<columnName>` (column op) — composed only of code-side identifiers, so a label/order change never orphans a saved condition. The legacy `record.participantCount` is migrated to `record.participants.count`.

### AC-03-30 — type + label derivation [BE][T]
- **Given** a generated fact, **then** its `type` is `number` for count/sum/avg and the **column's declared type** for min/max (a date column's min/max gets date operators); its label is `"<relation.label> · Count"` or `"<relation.label> · <Op> of <column.label>"`.

### AC-03-31 — registration-time whitelist validation [BE][T]
- **Given** a relation with an op ∉ `{sum,avg,min,max}` on a column, or a column name absent from `child_model.__table__`, **when** registered, **then** a loud `ValueError` is raised at boot (mirrors `aggregate_fact`/`infer_facts`). No API-layer validation change — generated facts pass through the existing `validate_tree`/`fact_map` gate like any scalar fact.

### AC-03-32 — relation auto-generates the cross-entity `DerivedTrigger` [BE][T]
- **Given** a registered `AggregatableRelation(child_entity_type, child_model, fk_attr)`, **when** a child record's entity event fires, **then** a platform-generated `DerivedTrigger` resolves the owner (child-by-`record_id` → owner-by-`fk_attr`, tenant-scoped) and `reevaluate()` runs — no hand-written trigger. Contract: the child write path must emit the entity event (`notify_entity_event`) or nothing fires (documented per-relation manual step).

### AC-03-33 — tenant-scoped aggregate via the relation [BE][T]
- **Given** owners in two tenants each with children, **then** a generated `count`/`sum` fact counts only the owner's own children scoped to the owner's tenant (a sibling tenant's children never contribute) — same guarantee as the slice-2 `aggregate_fact`.

### AC-03-34 — catalog exposes generated facts [BE][T]
- **Given** `GET /rule-facts?sources=record:<type>`, **then** the generated aggregate keys appear with their derived label/type and are authorable as an auto-edge condition (201).

### AC-03-35 — EMS project participant-count rides the relation [BE][T]
- **Given** the EMS project entity declares an `AggregatableRelation("participants", child_entity_type="project_participant", child_model=ProjectParticipant, fk_attr="project_id", count=True)`, **when** participants are added past an auto-edge threshold (`record.participants.count >= N`), **then** the event auto-advances to the derived status; the hand-written `_register_derived`/`_project_owners` is gone.

### AC-03-36 — frontend unchanged [FE]
- **Given** the RuleBuilder, **then** aggregate facts render as ordinary number/date facts under the entity's source group (label-disambiguated) with the correct per-type operators — **no** `types/rules.ts` / RuleBuilder / parity change.

### AC-03-37 — E2E: configure participant-count derivation [E2E]
- **Given** an event with a Draft→Confirmed auto edge conditioned `Participant count >= N` (edge built via API to dodge flaky canvas drag), **when** an operator **real-clicks** adding the Nth participant in the UI, **then** the event's status flips to Confirmed without a manual transition.

---

## Slice 5 — EMS Event Details edit (grilled 2026-06-19)

### AC-03-38 — project update endpoint + service [BE][T]
- **Given** `PATCH /ems/projects/{id}` (gated `projects.manage`) with a partial body, **then** `ProjectService.update` PATCH-merges `title/brief/notes/domain_name/start_date/end_date/event_validity_end`; absent keys are unchanged; an explicit `null` clears that field; **immutable** keys (`template_id`, `type_id`, `client_id`, `status_id`, `id`, `created_at`) are ignored/rejected (never mutated).

### AC-03-39 — ProjectOut exposes the editable fields [BE][T]
- **Given** `GET /ems/projects/{id}` (and the list), **then** the response includes `notes`, `domainName`, `startDate`, `endDate`, `eventValidityEnd`, `typeId` (read-only) in addition to the existing fields.

### AC-03-40 — dates are date-only [BE][T]
- **Given** the 3 date columns retyped to `Date`, **when** a date is set via update, **then** it stores + round-trips as a calendar date `"YYYY-MM-DD"` (no time component, no tz shift); the rule-fact type stays `date`.

### AC-03-41 — date ordering validation [BE][T]
- **Given** an update with both bounds present, **when** `end_date < start_date` or `event_validity_end < end_date`, **then** the API returns **422**; a valid (or single-sided) order persists.

### AC-03-42 — Details tab edit under the shared Edit toggle [FE]
- **Given** the event detail, **then** a **Details** tab shows `title/brief/notes/domain_name` + 3 date inputs (`<input type="date">`); the global Edit toggle flips them read↔editable together with the Eligibility-flow canvas; **Save** PATCHes the project (when the form is dirty) AND persists the layout (when the layout is dirty), each guarded; **Cancel** resets both. Read-only date display renders the calendar date directly (never via the tz formatter).

### AC-03-43 — Events list shows scheduling [FE]
- **Given** the Events list, **then** **Start** and **End** columns render (sortable, hideable via column prefs); export includes `startDate`/`endDate`.

### AC-03-44 — E2E: edit event dates round-trip [E2E]
- **Given** an event, **when** a user opens it, clicks Edit, sets Start/End + brief, and Saves, **then** on reload the values persist on the Details tab and the Events list shows the Start/End columns — all via real clicks.

### AC-03-45 — date-based derived status usable end-to-end [BE][T]
- **Given** an event date is now settable, **then** a date-conditioned auto edge (authored on `record.endDate` / `record.startDate`, or a computed "passed-now" boolean for the time sweep) has real data to evaluate — closing the foolproof gap that motivated this slice.

---

## Slice 6 — Relative-to-now date conditions + admin date-simulation (grilled 2026-06-19)

### AC-03-46 — clock provider [BE][T]
- **Given** `app/clock.py`, **then** `now()` returns the contextvar value inside `with clock_override(as_of): …` and real `datetime.now(timezone.utc)` outside it (reset in `finally`, even on exception). Only day-count fact resolvers read it — stored timestamps/transition times keep real `now`.

### AC-03-47 — day-count facts auto-generated per date field [BE][T]
- **Given** an entity declares a `date` column in `fact_attrs`, **then** the `record:<type>` source also exposes `record.<attr>.daysSince` (= `(today − field).days`) and `record.<attr>.daysUntil` (= `(field − today).days`) as **number** facts (labels `"Days since <Label>"` / `"Days until <Label>"`), in addition to the base date fact. Null field → fact resolves None (fails closed).

### AC-03-48 — day-counts are time-dependent + use existing operators [BE][T]
- **Given** an auto edge conditioned `Days since End Date ≥ 2` (existing numeric operator, number value), **then** it is **false** while `today < end + 2` and **true** once `today ≥ end + 2`; the value tracks `clock.now()` (a `clock_override` changes it). No new operator / no `types/rules.ts` change.

### AC-03-49 — `eventEnded` retired [BE]
- **Given** the EMS project entity, **then** the hand-wired `eventEnded` boolean is removed; the "event ended" window is expressed as `Days since End Date ≥ 0` (or N), and the project still registers `has_time_auto_edges` + a `time_candidates` query covering any date field set.

### AC-03-50 — simulate dry-run is side-effect-free [BE][T]
- **Given** `simulate_entity_sweep(db, entity_type, tenant_id, as_of, apply=False)`, **then** it returns the `(record, from, to)` rows that WOULD advance at `as_of` but **persists nothing** (record statuses unchanged after; no events/notifications fire), scoped to the caller's tenant (sibling-tenant records excluded).

### AC-03-51 — simulate apply commits [BE][T]
- **Given** `apply=True`, **then** the would-advance transitions are committed (statuses persist, events/notifications fire normally); a fast-forward `as_of` advances eligible records, a backtrack `as_of` advances none.

### AC-03-52 — simulate endpoint gated [BE][T]
- **Given** `POST /status-entities/{entityType}/simulate { asOf, apply }`, **then** it requires `statuses.manage`, is tenant-scoped, and returns the would-advance preview (dry-run) or the applied result.

### AC-03-53 — Simulate-date admin UI [FE]
- **Given** the status entity detail of a time-capable entity (`hasTimeAutoEdges`), **then** a **"Simulate date"** action opens a dialog (date picker → **Preview** dry-run table of `title · from → to`, capped + count → **Apply** with confirm); a non-time-capable entity does not show it. Gated `statuses.manage`.

### AC-03-54 — E2E: simulate a date window [E2E]
- **Given** a Project auto edge `Days since End Date ≥ 2` and an event whose end_date is set, **when** an admin opens **Simulate date**, picks a date ≥2 days after that end_date, **Previews** (the event is listed) and **Applies**, **then** the event's status advances — all via real clicks; the production beat is untouched.

---

## Out of scope (do NOT test here — deferred per plan)
- Filtered/scoped aggregates ("count of *Confirmed* participants") → **BL-112** (`aggregate_fact(where=)` interim).
- Persisted/global clock time-travel (staging-wide) → per-call `as_of` only; log later if needed.
- Relation sub-grouping in the RuleBuilder fact picker → **BL-113** (label-only disambiguation ships).
- Explicit method/field composer UI in the builder (Option B) → rejected in favor of Option A.
- participant `Checked-in` derivation → Cluster D (`05`).
- invoice `Partially Paid`/`Paid`/`Overdue`/`Refunded`, SO `Fulfilled` → Cluster F (`07`).
- Burst coalescing / debounce per (owner, tick) → optimization backlog.
- "why did this auto-fire?" explainer → nice-to-have backlog.
- min/avg + `where`-filtered aggregates beyond what slice 2 needs → extend on demand.

---

## Definition of done
- All AC-03-01..27 pass.
- Slices 1–3 merged behind review.
- Synthetic-entity tests added (mirror `tests/test_status_engine.py`'s `ticket`).
- Backlog candidates logged (burst coalescing, auto-fire explainer, two-tier fork parity confirmation).
- Per-plan test-report doc produced (`03-...-test-report.md`).
