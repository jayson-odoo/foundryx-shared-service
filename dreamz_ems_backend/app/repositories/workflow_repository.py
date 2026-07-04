"""Workflow persistence (plan sprint-2/08) — pure SQLAlchemy, ALWAYS tenant-scoped.
Every query filters ``tenant_id``; the tenant comes from the authed context."""
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.workflow import Workflow, WorkflowRun, WorkflowRunNode, WorkflowVersion


class WorkflowRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- workflows ----

    def paginate(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        status_view: Optional[str] = None,
        filter_clause=None,
    ) -> Tuple[List[Workflow], int]:
        query = self.db.query(Workflow).filter(Workflow.tenant_id == tenant_id)
        # Active|Archived view (statusView 'trashed' = archived).
        query = query.filter(
            Workflow.is_trashed.is_(True) if status_view == "trashed" else Workflow.is_trashed.is_(False)
        )
        if search:
            like = f"%{search}%"
            query = query.filter(or_(Workflow.name.ilike(like), Workflow.description.ilike(like)))
        if filter_clause is not None:
            query = query.filter(filter_clause)
        total = query.count()
        sort_map = {
            "name": Workflow.name,
            "isActive": Workflow.is_active,
            "updatedAt": Workflow.updated_at,
            "createdAt": Workflow.created_at,
        }
        column = sort_map.get(sort_by or "name", Workflow.name)
        query = query.order_by(column.desc() if sort_dir == "desc" else column.asc())
        rows = query.offset(page * page_size).limit(page_size).all()
        return rows, total

    def get(self, workflow_id: str, tenant_id: str) -> Optional[Workflow]:
        return (
            self.db.query(Workflow)
            .filter(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id)
            .first()
        )

    def add(self, wf: Workflow) -> Workflow:
        self.db.add(wf)
        self.db.flush()
        return wf

    def delete(self, wf: Workflow) -> None:
        self.db.delete(wf)
        self.db.flush()

    # ---- versions ----

    def next_version_number(self, workflow_id: str) -> int:
        current = (
            self.db.query(func.max(WorkflowVersion.version_number))
            .filter(WorkflowVersion.workflow_id == workflow_id)
            .scalar()
        )
        return (current or 0) + 1

    def get_version(self, version_id: str) -> Optional[WorkflowVersion]:
        return self.db.query(WorkflowVersion).filter(WorkflowVersion.id == version_id).first()

    def add_version(self, version: WorkflowVersion) -> WorkflowVersion:
        self.db.add(version)
        self.db.flush()
        return version

    def versions_paginate(
        self, workflow_id: str, *, page: int = 0, page_size: int = 20
    ) -> Tuple[List[WorkflowVersion], int]:
        query = self.db.query(WorkflowVersion).filter(WorkflowVersion.workflow_id == workflow_id)
        total = query.count()
        rows = (
            query.order_by(WorkflowVersion.version_number.desc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total

    # ---- runs ----

    def add_run(self, run: WorkflowRun) -> WorkflowRun:
        self.db.add(run)
        self.db.flush()
        return run

    def get_run(self, run_id: str, tenant_id: str) -> Optional[WorkflowRun]:
        return (
            self.db.query(WorkflowRun)
            .filter(WorkflowRun.id == run_id, WorkflowRun.tenant_id == tenant_id)
            .first()
        )

    def runs_paginate(
        self,
        workflow_id: str,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        segment: Optional[str] = None,
    ) -> Tuple[List[WorkflowRun], int]:
        query = self.db.query(WorkflowRun).filter(
            WorkflowRun.workflow_id == workflow_id, WorkflowRun.tenant_id == tenant_id
        )
        if segment and segment != "all":
            query = query.filter(WorkflowRun.status == segment)
        total = query.count()
        rows = (
            query.order_by(WorkflowRun.created_at.desc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total

    def latest_runs(self, workflow_ids: List[str], tenant_id: str) -> Dict[str, WorkflowRun]:
        """Most-recent run per workflow (for the list's Last-run column)."""
        if not workflow_ids:
            return {}
        rows = (
            self.db.query(WorkflowRun)
            .filter(WorkflowRun.tenant_id == tenant_id, WorkflowRun.workflow_id.in_(workflow_ids))
            .order_by(WorkflowRun.created_at.desc())
            .all()
        )
        latest: Dict[str, WorkflowRun] = {}
        for r in rows:
            latest.setdefault(r.workflow_id, r)
        return latest

    def prune_runs(self, run_id: str) -> None:
        run = self.db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
        if run:
            self.db.delete(run)
            self.db.flush()
