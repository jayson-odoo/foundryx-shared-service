# Sprint 2 · Plan 09 - Workflow Engine (triggers & actions breadth)

**Branch:** `sprint-2/09-workflow-triggers-actions`
**Advances:** BL-025. **Second of 3 vertical slices** (08 foundation → **09 breadth** → 10 polish). Builds on slice 08's proven executor + canvas.
**Spawns/feeds:** BL-084 (audit log - subscribes the same `emit_entity_event` seam this plan introduces).
**Depends on:** slice 08 (executor, registry, canvas, runs), rule engine `evaluate`/fact registry (plan 02), `status_machine.transition` + `StatusTransitioned` event (plan 01), `storage_for_tenant` (plan 06), Celery beat (new here).

---

## Context

Slice 08 proved the whole stack on manual→email. Slice 09 fans out the **trigger and action catalog** on that proven executor, and lands the two pieces of new infrastructure the wider catalog needs: the **generic CRUD event bus** (explicit service-layer emit) and the **minute-tick scheduler**. The **IF node** (rule-engine branching) also lands here.

---

## Locked design decisions (from grilling)

1. **D1 - CRUD event bus = explicit service-layer emit (NOT ORM hooks).** A shared `app/services/entity_events.py` helper: `emit_entity_event(db, entity_type, action, record, *, actor, changes=None)` where `action ∈ created|updated|deleted`. Each mutating service calls it. Chosen over SQLAlchemy ORM/session hooks because: emit belongs in the service layer (the codebase's enforced boundary - `status_machine` already emits there); ORM hooks can't cleanly see the **actor** (incl. impersonation `get_actor_user_id`); ORM hooks fire on seeds/migrations/bulk writes (thousands of phantom runs every `init_db`); field-diff is free in the service (it has the validated patch). New-entity checklist item: "mutating service → emit_entity_event," same weight as "permission = CSV row."

2. **D2 - `changes` = `{field: {"from": old, "to": new}}` dict** (not a bare name list). Powers `field_changed` matching, run context (`trigger.changedFields` list + `trigger.changes.<field>.from/to`), and gives BL-084's audit log old/new for free.

3. **D3 - After-commit dispatch (never act on rolled-back data).** `emit_entity_event` **buffers events on the Session**; a SQLAlchemy `after_commit` hook drains the buffer → matches workflows → enqueues Celery runs. Rollback discards the buffer. The status engine's existing synchronous `StatusTransitioned` in-process emit stays (other listeners); the **workflow subscriber** hooks the after-commit drain. One unified "domain event → after-commit → match → enqueue" path for both `entity.*` and `StatusTransitioned`.

4. **D4 - Trigger→workflow matching is indexed, no JSON scan.** On **publish** (slice 08 D4), denormalize the published trigger node into `workflows.trigger_type / trigger_entity_type / trigger_action` columns (+ keep full `trigger_config_json` for field filters/cron). Matching = indexed `WHERE tenant_id=? AND is_active AND current_version_id IS NOT NULL AND trigger_type=? AND trigger_entity_type=? AND trigger_action=?`, then in-Python refine (field filters, the trigger's own conditions).

5. **D5 - Loop guard.** Each run carries `triggered_by_run_id` (walkable chain) + `depth`. A workflow action's write calls `emit_entity_event` tagged with the originating `run_id`/`workflow_id` (carried in the run/actor context). Matching **excludes any workflow already in the current chain** (a workflow's own write can NEVER re-trigger the same workflow - the explicit requirement) AND enforces a **global `max_depth` (default 5)** killing cross-workflow cascades. Over-depth = run not enqueued + a logged/visible "loop guard tripped" note.

6. **D6 - Triggerable-entity contract = rule-engine fact source + `triggerable` flag** (slice 08 D9). v1 instrumented set (services gain `emit_entity_event` + a `record:<entity>` fact source if missing): **`user`, `role`, `tenant`, `connection`, `template`, `workflow`**. Domain entities (Lead/Project/Task…) light up automatically as future sprints register their fact sources + emit calls.

7. **D7 - Trigger catalog (TriggerDefs registered here):**
   - `entity.created` / `entity.updated` / `entity.deleted` - config: pick entity (from triggerable fact sources). Output: `trigger.record.*` (+ `trigger.changes.*` for updated), `trigger.actor.*`, `trigger.action`.
   - `entity.field_changed` - `updated` refined by a chosen field present in `changes`.
   - `entity.status_changed` - subscribes `StatusTransitioned`; config: entity + optional from/to status. Output adds `trigger.fromStatus` / `trigger.toStatus`.
   - `schedule.cron` - see D9.

8. **D8 - Action catalog (ActionDefs registered here):**
   - `storage.put` (push file) → outputs `nodes.<id>.url`, `.key`, `.size`, `.mime`. `storage.delete`. `storage.get` = **resolve a stored key → URL/metadata ONLY** (`url`/`size`/`mime`), never load bytes into the run context (binary-in-JSON trap; attachment loading = backlog). All via `storage_for_tenant(db, tenant_id)`.
   - `entity.transition_status` → moves a record's status via `status_machine.transition` (acts as the synthetic Workflow actor - slice 08 D10).
   - `entity.update` → patches fields on a record (synthetic actor; its write emits `entity.updated` → loop-guarded by D5).
   - **IF node** (built-in, not an ActionDef) - config = a rule-engine `conditions_json` (mount `<RuleBuilder>`, facts = the run-context fact sources); `evaluate(tree, facts)` → true/false output ports. **Destructive actions (`storage.delete`, `entity.update/transition`) get a confirm dialog before any manual/test run** (slice 08 D13).

9. **D9 - Scheduler = single minute-tick draining `next_run_at`** (NOT a custom Celery-beat scheduler). One static beat entry (`run-due-workflows`, 60s) selects `WHERE trigger_type='schedule' AND is_active AND current_version_id IS NOT NULL AND next_run_at <= now()`, enqueues a run per row, advances `next_run_at` via `croniter`. Claim with a guarded `UPDATE … RETURNING` so two beats can't double-fire. **Structured cron builder UI**: frequency minute/hour/day/week/month, each with its sub-field (minute-of-hour, time-of-day, day-of-week, day-of-month) compiling to a standard 5-field cron string (+ raw-cron advanced field). Schedule carries an IANA **timezone** (default tenant/creator tz); `next_run_at` computed in that zone → stored UTC. **Fixed cron only** - relative-to-record-date reminders ("N days before {{record.date}}") = backlog (domain date entities don't exist yet).

---

## Build notes
- `entity_events.py` helper + retrofit emit into the 6 instrumented services (D6) + the after-commit drain + the unified matcher/enqueuer.
- Register the trigger/action defs (D7/D8) + the IF node kind in the executor (true/false port branching - the executor was built DAG-ready in 08).
- Celery beat process + the minute-tick task + `croniter` dep + the cron-builder component.
- Pydantic schemas camelCase / `ApiModel`; routers HTTP-only; every query tenant-scoped (layering + tenancy rules).

## Phases
- **A (frontend, mock):** entity/status/schedule trigger config UIs (entity picker from fact sources, cron builder, status pickers), storage/transition/update action drawers, IF node + RuleBuilder, branch edges on the canvas.
- **B (backend, TDD):** emit seam + after-commit drain + matcher + loop guard + scheduler tick + IF branching + each action; pytest (emit→match→enqueue, loop-chain exclusion + depth cap, field_changed matching, cron next_run_at + tz, status_changed subscription, storage/transition/update executors, IF true/false routing). Register a synthetic test entity (status-engine `ticket` precedent).
- **C (E2E):** create an `entity.status_changed → IF → email` workflow against a real entity, trigger it by actually changing a status in the UI, assert the run + branch taken in Logs; a scheduled workflow firing via an advanced `next_run_at`; loop-guard proven (a self-updating workflow doesn't storm). Dedicated tenant; timestamped names; dnd in Vitest.

## Out of scope (→ slice 10 or backlog)
- BL-081 notification template picker, BL-064 final undo/redo polish, run retention prune, audit-log seam handoff → **slice 10**.
- Parallel/merge/loop, retry/timeout, continue-on-error, dry-run, relative-date scheduling, in-app notification action, attachment bytes → **backlog**.
