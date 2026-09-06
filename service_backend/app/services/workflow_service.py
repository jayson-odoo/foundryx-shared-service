"""Workflow business logic (plan sprint-2/08) - Router → THIS → Repository.

Owns: CRUD, publish/unpublish (snapshot → version → current + denormalized
trigger), active + archive/restore lifecycle, manual run (snapshot draft +
enqueue the Celery task), and the staleness-aware debug execute.
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.user import User
from app.models.workflow import (
    RUN_PENDING,
    RUN_RUNNING,
    RUN_CANCELLED,
    RUN_WAITING,
    TRIGGER_MANUAL,
    Workflow,
    WorkflowRun,
    WorkflowSettings,
    WorkflowVersion,
)
from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.filters import FilterGroup
from app.schemas.workflow import (
    WorkflowDetailOut,
    WorkflowListItemOut,
    WorkflowRunDetailOut,
    WorkflowRunItemOut,
    WorkflowRunNodeOut,
    WorkflowVersionSummaryOut,
)
from app.services.filter_translator import translate_filter
from app.workflow_engine import (
    get_trigger,
    parse_definition,
    TriggerTestDataError,
    validate_definition,
)
from app.workflow_engine.entity_events import emit_entity_event
from app.workflow_engine.executor import debug_execute as _debug_execute

_FILTER_COLUMNS = {
    "name": Workflow.name,
    "isActive": Workflow.is_active,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _form_answer_fields(definition: Dict[str, Any]) -> List[Dict[str, str]]:
    """Flatten a form definition to its answer fields ({key,label}) - input/
    choice/composite fields that carry a stable answer ``key`` (display blocks
    like heading/divider have none). Backs the form.submitted dynamic outputs."""
    fields: List[Dict[str, str]] = []
    for page in definition.get("pages", []) or []:
        for section in page.get("sections", []) or []:
            for field in section.get("fields", []) or []:
                key = field.get("key")
                if key:
                    fields.append({"key": key, "label": field.get("label") or key})
    return fields


class WorkflowError(Exception):
    pass


class WorkflowPermissionError(WorkflowError):
    """The caller lacks a permission the definition requires (403)."""


class CodeRunnerRequired(WorkflowError):
    """Publishing a Code-bearing graph needs a healthy external runner (422)."""


class WorkflowNotFound(WorkflowError):
    pass


class ShortcutNotFound(WorkflowError):
    """No matching PUBLISHED ``entity.shortcut`` workflow bound to this record's
    entity type in this tenant (plan sprint-4/27 AC-IVE-38) - the caller maps
    this to a uniform 404 whatever the underlying reason (unpublished /
    inactive / archived / another tenant / not an `entity.shortcut` workflow /
    not bound to the requested entity type)."""


class ShortcutCodeNotAuthorized(WorkflowError):
    """The workflow's published version carries a Code node without a
    `code_authorized_by` stamp (plan sprint-4/27 AC-IVE-38) - 409, no run
    created. The fail-closed check is inherited from `create_run_for_event`,
    never re-implemented here."""


class ShortcutSerializationConflict(WorkflowError):
    """The workflow's `execution.mode="serialized"` correlation key could not
    be resolved from the shortcut's trigger context (plan sprint-4/27 round-3
    codex triage B2) - a conflict, not a run, mirroring `run()`'s manual-run
    handling of the same `RuntimeError` from `assign_run_correlation`. No run
    is persisted (the error raises before `session.add(run)`)."""


class WorkflowService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = WorkflowRepository(db)

    # ---- tenant settings (plan 10 - run retention) ----
    def get_run_retention(self, tenant_id: str) -> Tuple[int, bool]:
        """Effective run-retention days for the tenant + whether it's the global
        default (no per-tenant override)."""
        from app.config import settings as cfg

        row = self.db.query(WorkflowSettings).filter_by(tenant_id=tenant_id).first()
        if row and row.run_retention_days is not None:
            return row.run_retention_days, False
        return cfg.workflow_run_retention_days, True

    def set_run_retention(self, tenant_id: str, days: int) -> Tuple[int, bool]:
        row = self.db.query(WorkflowSettings).filter_by(tenant_id=tenant_id).first()
        if row is None:
            row = WorkflowSettings(tenant_id=tenant_id, run_retention_days=days)
            self.db.add(row)
        else:
            row.run_retention_days = days
        self.db.commit()
        return days, False

    # ---- helpers ----

    def _user_name(self, user_id: Optional[str]) -> str:
        if not user_id:
            return ""
        user = self.db.query(User).filter(User.id == user_id).first()
        return (user.name or user.email) if user else ""

    @staticmethod
    def _trigger_label(definition: Dict[str, Any]) -> Tuple[str, str]:
        doc = parse_definition(definition)
        trigger = next((n for n in doc.nodes if n.kind == "trigger"), None)
        if trigger is None:
            return "", "-"
        defn = get_trigger(trigger.type)
        return trigger.type, (defn.label if defn else trigger.type)

    def _has_unpublished(self, wf: Workflow) -> bool:
        if not wf.current_version_id:
            doc = parse_definition(wf.draft_definition_json)
            return len(doc.nodes) > 0
        version = self.repo.get_version(wf.current_version_id)
        if version is None:
            return True
        return json.dumps(version.definition_json, sort_keys=True) != json.dumps(
            wf.draft_definition_json, sort_keys=True
        )

    def _current_version_number(self, wf: Workflow) -> Optional[int]:
        if not wf.current_version_id:
            return None
        version = self.repo.get_version(wf.current_version_id)
        return version.version_number if version else None

    # ---- list ----

    def list(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        status_view: Optional[str] = None,
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[List[WorkflowListItemOut], int]:
        clause = translate_filter(filter_group, _FILTER_COLUMNS)
        rows, total = self.repo.paginate(
            tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            status_view=status_view,
            filter_clause=clause,
        )
        latest = self.repo.latest_runs([w.id for w in rows], tenant_id)
        return [self._list_item(w, latest.get(w.id)) for w in rows], total

    def get_at(self, index: int, tenant_id: str, **kwargs) -> Tuple[Optional[WorkflowListItemOut], int]:
        rows, total = self.list(tenant_id, page=max(index, 0), page_size=1, **kwargs)
        return (rows[0] if rows else None), total

    def _list_item(self, wf: Workflow, last_run: Optional[WorkflowRun]) -> WorkflowListItemOut:
        trigger_type, trigger_label = self._trigger_label(wf.draft_definition_json)
        return WorkflowListItemOut(
            id=wf.id,
            name=wf.name,
            description=wf.description,
            is_active=wf.is_active,
            is_trashed=wf.is_trashed,
            trigger_type=trigger_type,
            trigger_label=trigger_label,
            current_version_number=self._current_version_number(wf),
            has_unpublished_changes=self._has_unpublished(wf),
            last_run_at=last_run.created_at if last_run else None,
            last_run_status=last_run.status if last_run else None,
            updated_at=wf.updated_at,
        )

    # ---- detail ----

    def get(self, workflow_id: str, tenant_id: str) -> Workflow:
        wf = self.repo.get(workflow_id, tenant_id)
        if wf is None:
            raise WorkflowNotFound()
        return wf

    def to_detail(self, wf: Workflow) -> WorkflowDetailOut:
        last_run = self.repo.latest_runs([wf.id], wf.tenant_id).get(wf.id)
        base = self._list_item(wf, last_run)
        current = self.repo.get_version(wf.current_version_id) if wf.current_version_id else None
        current_summary = (
            WorkflowVersionSummaryOut.from_row(current, self._user_name(current.published_by))
            if current
            else None
        )
        return WorkflowDetailOut(
            **base.model_dump(),
            draft_definition=wf.draft_definition_json,
            current_version_id=wf.current_version_id,
            current_version=current_summary,
            created_by_name=self._user_name(wf.created_by) or "-",
            created_at=wf.created_at,
        )

    # ---- writes ----

    @staticmethod
    def assert_code_permitted(actor: Optional[User], doc: Any) -> None:
        """Every ``ActionDef.permission`` a node in ``doc`` declares gates
        adding/editing/publishing/running that graph (AC-SAR-68, AC-WFP-61;
        plan sprint-4/31 S5 generalizes this beyond ``workflows.code`` -
        closes BL-SS-121, one seam for any current or future gated action -
        e.g. ``workflows.http`` on ``http.request``). ``actor=None`` = system
        path (an event/scheduled trigger has no live actor; ``code.run``
        keeps its own separate ``code_authorized_by`` publish-time stamp for
        that path - see ``entity_events.create_run_for_event``)."""
        from app.workflow_engine.schemas import required_node_permissions

        if actor is None:
            return
        required = required_node_permissions(doc)
        if not required:
            return
        from app.dependencies import effective_permission_keys

        have = effective_permission_keys(actor)
        missing = sorted(perm for perm in required if perm not in have)
        if missing:
            raise WorkflowPermissionError(f"Missing permission: {missing[0]}")

    def create(self, tenant_id: str, *, name: str, description: str, draft: Dict[str, Any], actor_id: str, actor: Optional[User] = None) -> Workflow:
        parse_definition(draft)  # shape gate (422 on malformed)
        self.assert_code_permitted(actor, draft)
        wf = Workflow(
            tenant_id=tenant_id,
            name=name.strip(),
            description=description.strip(),
            draft_definition_json=draft or {"schemaVersion": 1, "nodes": [], "edges": []},
            created_by=actor_id,
        )
        self.repo.add(wf)
        self.db.flush()
        emit_entity_event(self.db, "workflow", "created", wf, tenant_id=tenant_id, actor_id=actor_id)
        self.db.commit()
        self.db.refresh(wf)
        return wf

    def update(self, workflow_id: str, tenant_id: str, *, name: str, description: str, draft: Dict[str, Any], actor: Optional[User] = None) -> Workflow:
        wf = self.get(workflow_id, tenant_id)
        parse_definition(draft)
        self.assert_code_permitted(actor, draft)
        changes: Dict[str, Any] = {}
        if wf.name != name.strip():
            changes["name"] = {"from": wf.name, "to": name.strip()}
        if wf.description != description.strip():
            changes["description"] = {"from": wf.description, "to": description.strip()}
        wf.name = name.strip()
        wf.description = description.strip()
        wf.draft_definition_json = draft
        emit_entity_event(self.db, "workflow", "updated", wf, tenant_id=tenant_id, changes=changes or None)
        self.db.commit()
        self.db.refresh(wf)
        return wf

    def remove(self, workflow_id: str, tenant_id: str) -> None:
        wf = self.get(workflow_id, tenant_id)
        emit_entity_event(self.db, "workflow", "deleted", wf, tenant_id=tenant_id)
        self.repo.delete(wf)
        self.db.commit()

    def duplicate(self, workflow_id: str, tenant_id: str, actor_id: str) -> Workflow:
        wf = self.get(workflow_id, tenant_id)
        copy = Workflow(
            tenant_id=tenant_id,
            name=f"{wf.name} (copy)",
            description=wf.description,
            draft_definition_json=json.loads(json.dumps(wf.draft_definition_json)),
            created_by=actor_id,
        )
        self.repo.add(copy)
        self.db.commit()
        self.db.refresh(copy)
        return copy

    def set_active(self, workflow_id: str, tenant_id: str, is_active: bool) -> Workflow:
        wf = self.get(workflow_id, tenant_id)
        wf.is_active = is_active
        self.db.commit()
        self.db.refresh(wf)
        return wf

    def archive(self, workflow_id: str, tenant_id: str) -> Workflow:
        wf = self.get(workflow_id, tenant_id)
        wf.is_trashed = True
        wf.is_active = False  # archived workflows never fire
        self.db.commit()
        self.db.refresh(wf)
        return wf

    def restore(self, workflow_id: str, tenant_id: str) -> Workflow:
        wf = self.get(workflow_id, tenant_id)
        wf.is_trashed = False
        self.db.commit()
        self.db.refresh(wf)
        return wf

    def publish(self, workflow_id: str, tenant_id: str, actor_id: str, actor: Optional[User] = None) -> Workflow:
        wf = self.get(workflow_id, tenant_id)
        # raises on issues (422); `workflow_id` gates a `workflow.trigger`
        # node that targets ITSELF (AC-WFP-33).
        doc = validate_definition(wf.draft_definition_json, workflow_id=wf.id)
        from app.workflow_engine.schemas import has_code_nodes

        # Generalized permission gate (plan sprint-4/31 S5, closes BL-SS-121):
        # ANY node whose ActionDef declares a `permission` - not only
        # `code.run` - must be checked at publish, so `http.request`'s
        # `workflows.http` (AC-WFP-61) is enforced here too, not only at
        # create/update/manual-run.
        self.assert_code_permitted(actor, doc)
        code_bearing = has_code_nodes(doc)
        code_authorized_by = None
        if code_bearing:
            from app.workflow_engine.code_runner import code_runner_available

            if not code_runner_available():
                raise CodeRunnerRequired("The Code runner is unavailable - publishing a Code node is blocked.")
            code_authorized_by = actor.id if actor is not None else actor_id
        version = WorkflowVersion(
            workflow_id=wf.id,
            version_number=self.repo.next_version_number(wf.id),
            definition_json=json.loads(json.dumps(wf.draft_definition_json)),
            published_by=actor_id,
            code_authorized_by=code_authorized_by,
        )
        self.repo.add_version(version)
        wf.current_version_id = version.id
        # Denormalize the published trigger for fast matching (slice 09).
        trigger = next((n for n in doc.nodes if n.kind == "trigger"), None)
        wf.trigger_type = trigger.type if trigger else None
        wf.trigger_entity_type = (trigger.config.get("entityType") if trigger else None)
        wf.trigger_action = (trigger.config.get("action") if trigger else None)
        # Registry-driven override (plan sprint-4/31, AC-WFP-07/20, closes A4's
        # F3): a trigger with a FIXED entity type (form.submitted, omnichannel.*)
        # declares `TriggerDef.event_entity_type` so the indexed candidate query
        # matches - replaces the old per-type if-chain (form.submitted /
        # omnichannel.message_received). Author-picked `entity.*` triggers have
        # no `event_entity_type` and keep using `config.entityType` above.
        if trigger is not None:
            trig_def = get_trigger(trigger.type)
            if trig_def is not None and trig_def.event_entity_type:
                wf.trigger_entity_type = trig_def.event_entity_type
        # Scheduled trigger: arm the next fire (cron interpreted in its tz → UTC).
        wf.next_run_at = None
        if trigger and trigger.type == "schedule.cron":
            from app.workflow_engine.scheduler import compute_next_run_at

            cron_expr = str(trigger.config.get("cron") or "")
            if cron_expr:
                wf.next_run_at = compute_next_run_at(cron_expr, str(trigger.config.get("timezone") or ""))
        self.db.commit()
        self.db.refresh(wf)
        return wf

    def unpublish(self, workflow_id: str, tenant_id: str) -> Workflow:
        wf = self.get(workflow_id, tenant_id)
        wf.current_version_id = None
        wf.trigger_type = None
        wf.trigger_entity_type = None
        wf.trigger_action = None
        wf.next_run_at = None
        self.db.commit()
        self.db.refresh(wf)
        return wf

    # ---- runs ----

    def run(
        self,
        workflow_id: str,
        tenant_id: str,
        *,
        inputs: Dict[str, Any],
        is_test: bool,
        actor: User,
        test_trigger: Optional[Dict[str, Any]] = None,
    ) -> WorkflowRun:
        """Execute the draft manually or with registered synthetic trigger data."""
        wf = self.get(workflow_id, tenant_id)
        self.assert_code_permitted(actor, wf.draft_definition_json)
        version_id = wf.current_version_id
        current = self.repo.get_version(version_id) if version_id else None
        version_number = current.version_number if current else 0
        triggered_by = TRIGGER_MANUAL
        effective_is_test = is_test

        if test_trigger is not None:
            if not is_test:
                raise TriggerTestDataError("Test-trigger data requires test mode.")
            doc = parse_definition(wf.draft_definition_json)
            trigger = next((node for node in doc.nodes if node.kind == "trigger"), None)
            requested_type = str(test_trigger.get("type") or "")
            if trigger is None or requested_type != trigger.type:
                raise TriggerTestDataError("Test-trigger type does not match the draft.")
            trigger_def = get_trigger(trigger.type)
            if trigger_def is None or trigger_def.test_payload_builder is None:
                raise TriggerTestDataError("This trigger does not support test data.")
            payload = trigger_def.test_payload_builder(
                self.db, tenant_id, trigger.config, test_trigger
            )
            # Test-trigger runs always execute and identify the draft, regardless
            # of the workflow's current published version.
            version_id = None
            version_number = 0
            triggered_by = str(payload.get("triggeredBy") or "event")
            effective_is_test = True
        else:
            payload = {
                "triggeredBy": TRIGGER_MANUAL,
                "input": inputs or {},
                "actor": {"id": actor.id, "name": actor.name or actor.email, "email": actor.email},
            }
        run = WorkflowRun(
            tenant_id=tenant_id,
            workflow_id=wf.id,
            version_id=version_id,
            version_number=version_number,
            status=RUN_PENDING,
            triggered_by=triggered_by,
            is_test=effective_is_test,
            definition_snapshot_json=json.loads(json.dumps(wf.draft_definition_json)),
            trigger_payload_json=payload,
            actor_id=actor.id,
        )
        from app.workflow_engine.serialization import assign_run_correlation

        try:
            assign_run_correlation(run)
        except RuntimeError as exc:
            # A serialized manual run may not have the trigger data needed to
            # resolve its key. Surface that as a workflow-level conflict before
            # persisting a run, rather than returning an opaque 500.
            raise WorkflowError(str(exc)) from exc
        self.repo.add_run(run)
        self.db.commit()
        run_id = run.id

        from app.workflow_engine.serialization import dispatch_persisted_run

        dispatch_persisted_run(self.db, run)

        self.db.expire_all()
        return self.repo.get_run(run_id, tenant_id)

    # ---- shortcuts (plan sprint-4/27, D-A3-5/D-A3-10) ----
    # A "shortcut" is a workflow an agent fires against ONE record straight
    # from that record's own UI (the omnichannel conversation drawer is the
    # first consumer). Generic over any `WorkflowEntity.supports_shortcut`
    # entity - this file never branches on the entity type.

    def list_shortcuts(self, tenant_id: str, entity_type: str) -> List[Dict[str, str]]:
        """Published (`current_version_id` set), active, non-archived
        `entity.shortcut` workflows bound to `entity_type` (AC-IVE-36). Returns
        `{workflowId, name}` dicts - the caller shapes them into its own wire
        item (e.g. the omnichannel module's `ShortcutItem`)."""
        rows = (
            self.db.query(Workflow)
            .filter(
                Workflow.tenant_id == tenant_id,
                Workflow.is_active.is_(True),
                Workflow.is_trashed.is_(False),
                Workflow.current_version_id.isnot(None),
                Workflow.trigger_type == "entity.shortcut",
                Workflow.trigger_entity_type == entity_type,
            )
            .order_by(Workflow.name)
            .all()
        )
        return [{"workflowId": r.id, "name": r.name} for r in rows]

    def run_shortcut(
        self,
        tenant_id: str,
        workflow_id: str,
        entity_type: str,
        record: Any,
        actor: Optional[User],
    ) -> WorkflowRun:
        """Fire a shortcut against the workflow's PUBLISHED version - NEVER the
        draft (`run()` above executes the draft by design; a shortcut must not,
        D-A3-10). Every "not a valid shortcut for this record" case (foreign
        tenant / unpublished / inactive / archived / wrong trigger / wrong
        entity) raises the SAME `ShortcutNotFound` - a uniform 404, never
        leaking which reason applied (AC-IVE-38, AC-IVE-42).

        Goes through `create_run_for_event` - the SAME helper the CRUD event
        bus uses - so the fail-closed Code-node authorization gate,
        correlation-key assignment and serialized dispatch are inherited, not
        re-implemented (D-A3-10; reviewer: reject a duplicated `WorkflowRun(...)`
        construction here).

        (Round-3 codex triage B1) `entity_type` is generic caller input - this
        method is documented as usable by ANY `WorkflowEntity.supports_shortcut`
        entity, so it must not trust it blindly: resolve the entity from the
        registry and reject anything that never opted in (even if a workflow
        somehow got denormalized to that `trigger_entity_type` - `publish()`
        does not itself validate the trigger's entity against the registry).
        The record is then RELOADED tenant-scoped via the entity's own
        `load_record` rather than trusting the caller's object - defense in
        depth so a future caller can't hand this generic function a
        wrong-tenant record by mistake (the one current caller,
        `ConversationService.run_shortcut`, already loads tenant-scoped, but
        this function must hold the line on its own)."""
        from app.workflow_engine.entities import get_workflow_entity, load_record

        entity = get_workflow_entity(entity_type)
        if entity is None or not entity.supports_shortcut:
            raise ShortcutNotFound()
        record_id = getattr(record, "id", None)
        if not record_id:
            raise ShortcutNotFound()
        scoped_record = load_record(self.db, entity, tenant_id, record_id)
        if scoped_record is None:
            raise ShortcutNotFound()

        wf = (
            self.db.query(Workflow)
            .filter(
                Workflow.id == workflow_id,
                Workflow.tenant_id == tenant_id,
                Workflow.is_active.is_(True),
                Workflow.is_trashed.is_(False),
                Workflow.current_version_id.isnot(None),
                Workflow.trigger_type == "entity.shortcut",
                Workflow.trigger_entity_type == entity_type,
            )
            .first()
        )
        if wf is None:
            raise ShortcutNotFound()

        from app.workflow_engine.entity_events import (
            CodeNotAuthorized,
            build_shortcut_event,
            create_run_for_event,
        )
        from app.workflow_engine.serialization import CorrelationKeyUnresolved

        ev = build_shortcut_event(self.db, entity_type, scoped_record, tenant_id=tenant_id, actor=actor)
        try:
            run = create_run_for_event(self.db, wf, ev, depth=0)
        except CodeNotAuthorized as exc:
            raise ShortcutCodeNotAuthorized() from exc
        except CorrelationKeyUnresolved as exc:
            # B2 - an unresolved serialized `execution.correlationKey` raises
            # the typed `CorrelationKeyUnresolved` from `assign_run_correlation`
            # before any run is persisted; surface it as a conflict like the
            # manual `run()` path above does, never an opaque 500. Catching the
            # typed error (not bare `RuntimeError`) means an unrelated bug in
            # `create_run_for_event` still propagates as a 500 instead of
            # being mistaken for a serialization conflict.
            raise ShortcutSerializationConflict(str(exc)) from exc
        if run is None:
            # Defensive - the version raced a concurrent unpublish between the
            # lookup above and here; same uniform outcome as "not published".
            raise ShortcutNotFound()
        return run

    def list_runs(
        self, workflow_id: str, tenant_id: str, *, page: int = 0, page_size: int = 25, segment: Optional[str] = None
    ) -> Tuple[List[WorkflowRunItemOut], int]:
        self.get(workflow_id, tenant_id)  # tenant ownership check
        rows, total = self.repo.runs_paginate(
            workflow_id, tenant_id, page=page, page_size=page_size, segment=segment
        )
        return [WorkflowRunItemOut.from_row(r, self._user_name(r.actor_id)) for r in rows], total

    def get_run_detail(self, run_id: str, tenant_id: str) -> WorkflowRunDetailOut:
        run = self.repo.get_run(run_id, tenant_id)
        if run is None:
            raise WorkflowNotFound()
        base = WorkflowRunItemOut.from_row(run, self._user_name(run.actor_id))
        return WorkflowRunDetailOut(
            **base.model_dump(),
            definition=run.definition_snapshot_json,
            trigger_payload=run.trigger_payload_json,
            nodes=[WorkflowRunNodeOut.from_row(n) for n in run.nodes],
        )

    def cancel_run(self, run_id: str, tenant_id: str) -> WorkflowRunItemOut:
        run = self.repo.get_run(run_id, tenant_id)
        if run is None:
            raise WorkflowNotFound()
        if run.status not in (RUN_PENDING, RUN_RUNNING, RUN_WAITING):
            raise WorkflowError("Only pending, running or waiting runs can be cancelled.")
        if run.status == RUN_WAITING:
            # AC-WFP-52: cancelling a parked run also drops whatever module row
            # indexes it (omnichannel's `workflow_waits`) - core stays generic.
            from app.workflow_engine.parking import run_wait_cleanup

            run_wait_cleanup(self.db, run)
        run.status = RUN_CANCELLED
        run.paused_node_id = None
        run.resume_state_json = None
        run.finished_at = _now()
        self.db.commit()
        self.db.refresh(run)
        return WorkflowRunItemOut.from_row(run, self._user_name(run.actor_id))

    def list_versions(
        self, workflow_id: str, tenant_id: str, *, page: int = 0, page_size: int = 20
    ) -> Tuple[List[WorkflowVersionSummaryOut], int]:
        self.get(workflow_id, tenant_id)
        rows, total = self.repo.versions_paginate(workflow_id, page=page, page_size=page_size)
        return [WorkflowVersionSummaryOut.from_row(v, self._user_name(v.published_by)) for v in rows], total

    def debug_execute(
        self, workflow_id: str, tenant_id: str, *, run_id: str, target_node_id: str,
        scratch: Dict[str, Dict[str, Any]], stale_node_ids: List[str],
        actor: Optional[User] = None,
    ) -> List[WorkflowRunNodeOut]:
        self.get(workflow_id, tenant_id)
        run = self.repo.get_run(run_id, tenant_id)
        if run is None or run.workflow_id != workflow_id:
            raise WorkflowNotFound()
        # Debug re-executes the snapshot with scratch config (incl. edited Code
        # source) - the same ``workflows.code`` gate as a manual run (AC-SAR-68).
        # Scratch can only override config on existing nodes, never add a node
        # or change its type, so gating on the snapshot covers scratch too.
        self.assert_code_permitted(actor, run.definition_snapshot_json)
        touched = _debug_execute(
            self.db, run, target_node_id=target_node_id, scratch=scratch, stale_node_ids=stale_node_ids
        )
        self.db.commit()  # debug runs have real side effects (e.g. enqueued mail)
        return [
            WorkflowRunNodeOut(
                node_id=t["nodeId"],
                node_type=t["nodeType"],
                status=t["status"],
                input_json=t["inputJson"],
                output_json=t["outputJson"],
                error=t["error"],
                started_at=None,
                finished_at=None,
            )
            for t in touched
        ]

    def metadata(self, tenant_id: str, *, include_ai_agents: bool = False) -> Dict[str, Any]:
        """Triggerable entities + resolved statuses + record fields - the editor's
        entity/status/field pickers (swaps the frontend mock, slice 09).

        AI-agent options are included only when the caller holds the dedicated
        ``ai_agents.read`` permission. The workflow metadata endpoint itself
        remains available to every ``workflows.read`` caller."""
        from app.models.status import Status
        from app.rule_engine.registry import _camel, get_facts
        from app.workflow_engine.entities import list_workflow_entities

        entities = []
        for e in list_workflow_entities():
            facts = get_facts([f"record:{e.entity_type}"])
            fields = [
                {"key": fact.key.split("record.", 1)[-1], "label": fact.label, "type": fact.type}
                for _, _, fact in facts
            ]
            # entity.update may only write the whitelist (camelCase to match the
            # field keys above - see entity_actions guard).
            writable_fields = sorted(_camel(attr) for attr in e.writable)
            statuses: List[Dict[str, str]] = []
            if e.has_status:
                rows = (
                    self.db.query(Status)
                    .filter(Status.entity_type == e.entity_type, Status.tenant_id == tenant_id)
                    .order_by(Status.sort_order)
                    .all()
                )
                if not rows:  # no tenant fork → platform tier
                    rows = (
                        self.db.query(Status)
                        .filter(Status.entity_type == e.entity_type, Status.tenant_id.is_(None))
                        .order_by(Status.sort_order)
                        .all()
                    )
                statuses = [{"value": s.id, "label": s.label} for s in rows]
            entities.append({
                "type": e.entity_type,
                "label": e.label,
                "hasStatus": e.has_status,
                "statuses": statuses,
                "fields": fields,
                "writableFields": writable_fields,
                # AC-IVE-35 - the entity picker's `entityFilter: "shortcut"`
                # restricts to entities that opted in (plan sprint-4/27).
                "supportsShortcut": e.supports_shortcut,
            })

        # Whether a usable connection exists for each connection-requiring action
        # (tenant → platform fallback) - drives the editor's "no connection" warning.
        from app.repositories.connection_repository import ConnectionRepository

        conn_repo = ConnectionRepository(self.db)
        connections = {
            "email": conn_repo.resolve_for_type(tenant_id, "email") is not None,
            "storage": conn_repo.resolve_for_type(tenant_id, "storage") is not None,
        }
        from app.workflow_engine.code_runner import code_runner_available
        from code_runner.policy import CAPABILITIES as CODE_CAPABILITIES
        from app.workflow_engine.registry import list_actions, list_triggers

        # Plan 31 S3 review B-4: this branch's palette ships catalog entries
        # (ask_question/wait/business_hours/http.request) with no backend
        # ActionDef until S4/S5 register them - offering them would 422 at
        # Publish and RuntimeError at Run. `registeredNodeTypes` is the
        # generic, tenant-agnostic fix: the registry is process-global (every
        # module's TriggerDef/ActionDef lands here at boot regardless of
        # tenant), so the frontend catalog filters itself to exactly what the
        # backend can execute TODAY - a node type earns its palette slot the
        # moment its ActionDef/TriggerDef is registered, zero further FE edit.
        registered_node_types = sorted(
            {t.key for t in list_triggers()} | {a.key for a in list_actions()}
        )

        metadata = {
            "entities": entities,
            "connections": connections,
            "forms": self._form_options(tenant_id),
            "omnichannelChannels": self._omnichannel_channel_options(tenant_id),
            "omnichannelWorkspaces": self._omnichannel_workspace_options(tenant_id),
            "workflows": self._workflow_ref_options(tenant_id),
            "codeRunnerAvailable": code_runner_available(),
            "codeCapabilities": list(CODE_CAPABILITIES),
            "registeredNodeTypes": registered_node_types,
        }
        if include_ai_agents:
            metadata["aiAgents"] = self._ai_agent_options(tenant_id)
        return metadata

    def test_options(self, workflow_id: str, tenant_id: str) -> Dict[str, Any]:
        """Return tenant-safe options for the trigger in this workflow's draft.

        Trigger-specific discovery stays behind the registry callback so core
        never imports a Service module. The router separately gates access to
        the workflow run capability and the trigger data's domain permission.
        """
        workflow = self.get(workflow_id, tenant_id)
        document = parse_definition(workflow.draft_definition_json)
        trigger = next((node for node in document.nodes if node.kind == "trigger"), None)
        if trigger is None:
            return {}
        trigger_def = get_trigger(trigger.type)
        if trigger_def is None or trigger_def.test_metadata_provider is None:
            return {}
        return trigger_def.test_metadata_provider(self.db, tenant_id, trigger.config)

    def _omnichannel_channel_options(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Backs the omnichannel trigger's channel picker (sprint-4/17). A
        guarded import - core stays functional if the module isn't present in
        a given build (manifest-driven module set)."""
        try:
            from modules.omnichannel.models import Channel
        except ImportError:
            return []
        rows = (
            self.db.query(Channel.id, Channel.name)
            .filter(
                Channel.tenant_id == tenant_id,
                Channel.is_trashed.is_(False),
                Channel.is_active.is_(True),
            )
            .order_by(Channel.name)
            .all()
        )
        return [{"id": r.id, "name": r.name} for r in rows]

    def _workflow_ref_options(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Backs `workflow.trigger`'s `workflowId` picker (plan sprint-4/31 S2,
        AC-WFP-33) - published, active, non-trashed workflows only (the same
        bar `list_shortcuts`/`run_shortcut` hold a triggerable workflow to).
        Self-exclusion (a workflow must not offer itself) is a client concern
        (S3, drawer-scoped to the workflow being edited) - this generic,
        workflow-agnostic list is reused by every node drawer."""
        rows = (
            self.db.query(Workflow)
            .filter(
                Workflow.tenant_id == tenant_id,
                Workflow.is_active.is_(True),
                Workflow.is_trashed.is_(False),
                Workflow.current_version_id.isnot(None),
            )
            .order_by(Workflow.name)
            .all()
        )
        return [{"id": r.id, "name": r.name} for r in rows]

    def _omnichannel_workspace_options(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Backs every omnichannel workspace-scoped picker (tags, contact
        fields, lifecycle stages, close reasons, members, templates) in ONE
        call (plan sprint-4/31, AC-WFP-21; `templates` added S2 for the Send
        message/Ask a question template pickers). Guarded import - empty when
        the module isn't present in the build; tenant-scoped throughout.

        Plan 31 S3 review SF-3: early-returns `[]` when the module is not
        ACTIVE for the tenant (AC-WFP-21 - "all empty when the module is
        inactive"; the previous version only guarded the missing-in-BUILD
        case), and the six per-workspace queries are batched into six
        `IN (workspace_ids)` queries grouped in Python, instead of 6xN queries
        for N workspaces."""
        try:
            from modules.omnichannel.models import (
                Channel,
                CloseReason,
                ContactField,
                ContactTag,
                WhatsappTemplate,
                Workspace,
                WorkspaceMember,
            )
            from modules.omnichannel.services import lifecycle_service
        except ImportError:
            return []
        from app.models.status import Status as CoreStatus
        from app.models.user import User
        from app.repositories.module_repository import ModuleRepository

        if not ModuleRepository(self.db).is_active(tenant_id, "omnichannel"):
            return []

        workspaces = (
            self.db.query(Workspace)
            .filter(Workspace.tenant_id == tenant_id, Workspace.is_trashed.is_(False))
            .order_by(Workspace.name)
            .all()
        )
        if not workspaces:
            return []
        ws_ids = [ws.id for ws in workspaces]

        tags_by_ws: Dict[str, List[Any]] = {wid: [] for wid in ws_ids}
        for row in (
            self.db.query(ContactTag.id, ContactTag.name, ContactTag.workspace_id)
            .filter(ContactTag.tenant_id == tenant_id, ContactTag.workspace_id.in_(ws_ids))
            .order_by(ContactTag.name)
            .all()
        ):
            tags_by_ws[row.workspace_id].append(row)

        fields_by_ws: Dict[str, List[Any]] = {wid: [] for wid in ws_ids}
        for row in (
            self.db.query(
                ContactField.key, ContactField.label, ContactField.type, ContactField.workspace_id
            )
            .filter(ContactField.tenant_id == tenant_id, ContactField.workspace_id.in_(ws_ids))
            .order_by(ContactField.label)
            .all()
        ):
            fields_by_ws[row.workspace_id].append(row)

        stages_by_ws: Dict[str, List[Any]] = {wid: [] for wid in ws_ids}
        for row in (
            self.db.query(CoreStatus.id, CoreStatus.label, CoreStatus.scope_id)
            .filter(
                CoreStatus.tenant_id == tenant_id,
                CoreStatus.entity_type == lifecycle_service.ENTITY_TYPE,
                CoreStatus.scope_id.in_(ws_ids),
            )
            .order_by(CoreStatus.sort_order)
            .all()
        ):
            stages_by_ws[row.scope_id].append(row)

        reasons_by_ws: Dict[str, List[Any]] = {wid: [] for wid in ws_ids}
        for row in (
            self.db.query(CloseReason.id, CloseReason.name, CloseReason.workspace_id)
            .filter(
                CloseReason.tenant_id == tenant_id,
                CloseReason.workspace_id.in_(ws_ids),
                CloseReason.is_active.is_(True),
            )
            .order_by(CloseReason.name)
            .all()
        ):
            reasons_by_ws[row.workspace_id].append(row)

        # B-2: a stored `WorkspaceMember.user_id` is resolved tenant-scoped
        # AND excludes trashed users (the polymorphic-stored-id rule - the
        # exact leak class that shipped twice already, status-engine
        # notifications then the gateway `_user_names`) - a name AND email
        # render into an authenticated response below.
        members_by_ws: Dict[str, List[Any]] = {wid: [] for wid in ws_ids}
        for row in (
            self.db.query(User.id, User.name, User.email, WorkspaceMember.workspace_id)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .filter(
                WorkspaceMember.tenant_id == tenant_id,
                WorkspaceMember.workspace_id.in_(ws_ids),
                User.tenant_id == tenant_id,
                User.is_trashed.is_(False),
            )
            .order_by(User.name)
            .all()
        ):
            members_by_ws[row.workspace_id].append(row)

        # `whatsappTemplate` field type (Send message / Ask a question
        # template mode, plan sprint-4/31 S2) - every template regardless of
        # Meta review status; the drawer filters to APPROVED itself
        # (foolproof-UI - the picker only OFFERS a usable choice, but the
        # full set stays available for a future "show pending" affordance
        # without a second endpoint).
        templates_by_ws: Dict[str, List[Any]] = {wid: [] for wid in ws_ids}
        for row in (
            self.db.query(
                WhatsappTemplate.id,
                WhatsappTemplate.name,
                WhatsappTemplate.status,
                Channel.workspace_id,
            )
            .join(Channel, Channel.id == WhatsappTemplate.channel_id)
            .filter(
                WhatsappTemplate.tenant_id == tenant_id,
                Channel.tenant_id == tenant_id,
                Channel.workspace_id.in_(ws_ids),
            )
            .order_by(WhatsappTemplate.name)
            .all()
        ):
            templates_by_ws[row.workspace_id].append(row)

        out: List[Dict[str, Any]] = []
        for ws in workspaces:
            out.append(
                {
                    "id": ws.id,
                    "name": ws.name,
                    "contactTags": [
                        {"id": t.id, "name": t.name} for t in tags_by_ws[ws.id]
                    ],
                    "contactFields": [
                        {"key": f.key, "label": f.label, "type": f.type}
                        for f in fields_by_ws[ws.id]
                    ],
                    # `name` (not `label`) matches every sibling array on this
                    # workspace shape (contactTags/closeReasons/members all use
                    # `name`) and the pre-existing frontend contract
                    # (WorkflowOmnichannelWorkspace.lifecycleStages, S3 drift fix).
                    "lifecycleStages": [
                        {"id": s.id, "name": s.label} for s in stages_by_ws[ws.id]
                    ],
                    "closeReasons": [
                        {"id": r.id, "name": r.name} for r in reasons_by_ws[ws.id]
                    ],
                    "members": [
                        {"id": m.id, "name": m.name or m.email, "email": m.email}
                        for m in members_by_ws[ws.id]
                    ],
                    "templates": [
                        {"id": t.id, "name": t.name, "status": (t.status or "").upper()}
                        for t in templates_by_ws[ws.id]
                    ],
                }
            )
        return out

    def _ai_agent_options(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Backs the AI Agent node's agent picker (sprint-4/17)."""
        from app.models.ai import AiAgent

        rows = (
            self.db.query(AiAgent.id, AiAgent.name, AiAgent.model)
            .filter(AiAgent.tenant_id == tenant_id, AiAgent.is_enabled.is_(True))
            .order_by(AiAgent.name)
            .all()
        )
        return [{"id": r.id, "name": r.name, "model": r.model} for r in rows]

    def _form_options(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Published forms + their published-version answer keys - backs the
        `form.submitted` trigger picker + its dynamic `trigger.answers.<key>`
        outputs (sprint-3/02)."""
        from app.models.form import FORM_PUBLISHED, Form
        from app.repositories.form_repository import FormRepository

        repo = FormRepository(self.db)
        forms = (
            self.db.query(Form)
            .filter(
                Form.tenant_id == tenant_id,
                Form.status == FORM_PUBLISHED,
                Form.current_version_id.isnot(None),
            )
            .order_by(Form.name)
            .all()
        )
        out: List[Dict[str, Any]] = []
        for form in forms:
            version = repo.get_version(tenant_id, form.current_version_id)
            if version is None:
                continue
            out.append(
                {
                    "id": form.id,
                    "name": form.name,
                    "fields": _form_answer_fields(version.definition_json or {}),
                }
            )
        return out

    def template_options(self, tenant_id: str) -> List[Dict[str, str]]:
        from app.models.template import TEMPLATE_TYPE_EMAIL, Template
        from app.repositories.template_repository import TemplateRepository

        # Only EMAIL templates can back an email.send action - document/badge
        # (canvas) templates render to PDF, not mail (F2 slice 2).
        rows, _ = TemplateRepository(self.db).paginate(
            tenant_id, page=0, page_size=100,
            filter_clause=(Template.type == TEMPLATE_TYPE_EMAIL),
        )
        return [{"value": t.id, "label": t.name} for t in rows]
