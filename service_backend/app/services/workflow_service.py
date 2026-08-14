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


class WorkflowNotFound(WorkflowError):
    pass


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

    def create(self, tenant_id: str, *, name: str, description: str, draft: Dict[str, Any], actor_id: str) -> Workflow:
        parse_definition(draft)  # shape gate (422 on malformed)
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

    def update(self, workflow_id: str, tenant_id: str, *, name: str, description: str, draft: Dict[str, Any]) -> Workflow:
        wf = self.get(workflow_id, tenant_id)
        parse_definition(draft)
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

    def publish(self, workflow_id: str, tenant_id: str, actor_id: str) -> Workflow:
        wf = self.get(workflow_id, tenant_id)
        doc = validate_definition(wf.draft_definition_json)  # raises on issues (422)
        version = WorkflowVersion(
            workflow_id=wf.id,
            version_number=self.repo.next_version_number(wf.id),
            definition_json=json.loads(json.dumps(wf.draft_definition_json)),
            published_by=actor_id,
        )
        self.repo.add_version(version)
        wf.current_version_id = version.id
        # Denormalize the published trigger for fast matching (slice 09).
        trigger = next((n for n in doc.nodes if n.kind == "trigger"), None)
        wf.trigger_type = trigger.type if trigger else None
        wf.trigger_entity_type = (trigger.config.get("entityType") if trigger else None)
        wf.trigger_action = (trigger.config.get("action") if trigger else None)
        # form.submitted denormalizes to the constant entity type so the indexed
        # match finds it; per-form selectivity is refined by config.formId at
        # dispatch (sprint-3/02). The formId itself stays in the version config.
        if trigger and trigger.type == "form.submitted":
            wf.trigger_entity_type = "form_submission"
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

    def run(self, workflow_id: str, tenant_id: str, *, inputs: Dict[str, Any], is_test: bool, actor: User) -> WorkflowRun:
        """Manual run - executes the DRAFT (no publish required, D13)."""
        wf = self.get(workflow_id, tenant_id)
        current = self.repo.get_version(wf.current_version_id) if wf.current_version_id else None
        payload = {
            "triggeredBy": TRIGGER_MANUAL,
            "input": inputs or {},
            "actor": {"id": actor.id, "name": actor.name or actor.email, "email": actor.email},
        }
        run = WorkflowRun(
            tenant_id=tenant_id,
            workflow_id=wf.id,
            version_id=wf.current_version_id,
            version_number=current.version_number if current else 0,
            status=RUN_PENDING,
            triggered_by=TRIGGER_MANUAL,
            is_test=is_test,
            definition_snapshot_json=json.loads(json.dumps(wf.draft_definition_json)),
            trigger_payload_json=payload,
            actor_id=actor.id,
        )
        self.repo.add_run(run)
        self.db.commit()
        run_id = run.id

        from app.config import settings

        if settings.celery_task_always_eager:
            # Dev/E2E + tests: execute inline on THIS session (a worker process
            # would open a different DB session and not see an in-test run).
            from app.workflow_engine.executor import run_workflow

            run_workflow(self.db, run_id)
        else:
            # Prod: hand off to a worker (its own session, separate process).
            from app.workflow_engine.worker import run_workflow_task

            run_workflow_task.delay(run_id)

        self.db.expire_all()
        return self.repo.get_run(run_id, tenant_id)

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
        if run.status not in (RUN_PENDING, RUN_RUNNING):
            raise WorkflowError("Only pending or running runs can be cancelled.")
        run.status = RUN_CANCELLED
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
        scratch: Dict[str, Dict[str, Any]], stale_node_ids: List[str]
    ) -> List[WorkflowRunNodeOut]:
        self.get(workflow_id, tenant_id)
        run = self.repo.get_run(run_id, tenant_id)
        if run is None or run.workflow_id != workflow_id:
            raise WorkflowNotFound()
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

    def metadata(self, tenant_id: str) -> Dict[str, Any]:
        """Triggerable entities + resolved statuses + record fields - the editor's
        entity/status/field pickers (swaps the frontend mock, slice 09)."""
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
            })

        # Whether a usable connection exists for each connection-requiring action
        # (tenant → platform fallback) - drives the editor's "no connection" warning.
        from app.repositories.connection_repository import ConnectionRepository

        conn_repo = ConnectionRepository(self.db)
        connections = {
            "email": conn_repo.resolve_for_type(tenant_id, "email") is not None,
            "storage": conn_repo.resolve_for_type(tenant_id, "storage") is not None,
        }
        return {
            "entities": entities,
            "connections": connections,
            "forms": self._form_options(tenant_id),
        }

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
