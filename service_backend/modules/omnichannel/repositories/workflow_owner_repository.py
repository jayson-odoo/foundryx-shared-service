"""Workflow ownership repository (plan 38 gap 7). Pure SQLAlchemy.

A workflow built through an API key is reachable only through its
``workflow_owners`` row. Every read filters the owner's tenant AND workspace,
joins the core ``Workflow`` on the same tenant, and leaves archived workflows
out.
"""
import base64
import binascii
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.workflow import Workflow

from ..models import WorkflowOwner


class InvalidCursor(ValueError):
    """The opaque list cursor could not be decoded."""


def encode_cursor(created_at: datetime, workflow_id: str) -> str:
    aware = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    raw = f"{aware.astimezone(timezone.utc).isoformat()}|{workflow_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> Tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        stamp, workflow_id = raw.split("|", 1)
        created_at = datetime.fromisoformat(stamp)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCursor() from exc
    if not workflow_id:
        raise InvalidCursor()
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at, workflow_id


class WorkflowOwnerRepository:
    def __init__(self, db: Session):
        self.db = db

    def _owned(self, tenant_id: str, workspace_id: str):
        return (
            self.db.query(Workflow)
            .join(
                WorkflowOwner,
                and_(
                    WorkflowOwner.workflow_id == Workflow.id,
                    WorkflowOwner.tenant_id == Workflow.tenant_id,
                ),
            )
            .filter(
                WorkflowOwner.tenant_id == tenant_id,
                WorkflowOwner.workspace_id == workspace_id,
                Workflow.tenant_id == tenant_id,
                Workflow.is_trashed.is_(False),
            )
        )

    def get_owned(self, tenant_id: str, workspace_id: str, workflow_id: str) -> Optional[Workflow]:
        return self._owned(tenant_id, workspace_id).filter(Workflow.id == workflow_id).first()

    def list_owned(
        self,
        tenant_id: str,
        workspace_id: str,
        *,
        limit: int,
        cursor: Optional[Tuple[datetime, str]] = None,
    ) -> Tuple[List[Workflow], Optional[Tuple[datetime, str]]]:
        """Newest ``created_at`` first, ties by ``id`` descending. Returns the
        page and the position of the next one (None on the last page)."""
        q = self._owned(tenant_id, workspace_id)
        if cursor is not None:
            at, wid = cursor
            q = q.filter(
                or_(
                    Workflow.created_at < at,
                    and_(Workflow.created_at == at, Workflow.id < wid),
                )
            )
        rows = q.order_by(Workflow.created_at.desc(), Workflow.id.desc()).limit(limit + 1).all()
        if len(rows) <= limit:
            return rows, None
        page = rows[:limit]
        last = page[-1]
        return page, (last.created_at, last.id)

    def count_owned(self, tenant_id: str, workspace_id: str) -> int:
        return (
            self.db.query(func.count(Workflow.id))
            .join(
                WorkflowOwner,
                and_(
                    WorkflowOwner.workflow_id == Workflow.id,
                    WorkflowOwner.tenant_id == Workflow.tenant_id,
                ),
            )
            .filter(
                WorkflowOwner.tenant_id == tenant_id,
                WorkflowOwner.workspace_id == workspace_id,
                Workflow.tenant_id == tenant_id,
                Workflow.is_trashed.is_(False),
            )
            .scalar()
            or 0
        )

    def add(
        self, tenant_id: str, workspace_id: str, workflow_id: str, created_by: str
    ) -> WorkflowOwner:
        row = WorkflowOwner(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            created_by=created_by,
        )
        self.db.add(row)
        return row
