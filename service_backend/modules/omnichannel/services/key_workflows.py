"""Workflows under the API key (plan 38 gap 7, S1: ownership and CRUD).

A key reaches only the workflows its own workspace owns (``workflow_owners``).
Tenant and workspace come from the key and nowhere else. Every miss, for any
reason, is the same ``404 not_found``. The workflow itself is created, edited
and archived by the core ``WorkflowService`` with ``actor=None`` and
``actor_id="apikey:<keyId>"``.
"""
import uuid
from typing import Any, Dict, Optional

from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.models.workflow import Workflow
from app.services.workflow_service import WorkflowService
from app.workflow_engine.schemas import parse_definition

from ..models import Workspace
from ..repositories.workflow_owner_repository import (
    InvalidCursor,
    WorkflowOwnerRepository,
    decode_cursor,
    encode_cursor,
)
from ..schemas import PublicWorkflowItem, PublicWorkflowListResponse

MAX_OWNED_WORKFLOWS = 200


def actor_id_for_key(key_id: str) -> str:
    return f"apikey:{key_id}"


def workflow_not_found() -> ApiError:
    """One body for every reason a workflow is not reachable by this key."""
    return ApiError(404, "not_found", "Workflow not found.")


def public_workflow_item(wf: Workflow) -> PublicWorkflowItem:
    return PublicWorkflowItem(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        isActive=bool(wf.is_active),
        publishedVersionId=wf.current_version_id,
        triggerType=wf.trigger_type,
        draftDefinition=wf.draft_definition_json or {},
        createdBy=wf.created_by or "",
        createdAt=wf.created_at,
        updatedAt=wf.updated_at,
    )


def _check_shape(definition: Dict[str, Any]) -> None:
    try:
        parse_definition(definition)
    except ValidationError:
        raise ApiError(422, "invalid_request", "draftDefinition is not a valid workflow definition.")


class KeyWorkflowService:
    def __init__(self, db: Session):
        self.db = db
        self.owners = WorkflowOwnerRepository(db)
        self.workflows = WorkflowService(db)

    def _owned_or_404(self, tenant_id: str, workspace_id: str, workflow_id: str) -> Workflow:
        wf = self.owners.get_owned(tenant_id, workspace_id, workflow_id)
        if wf is None:
            raise workflow_not_found()
        return wf

    def list(
        self,
        tenant_id: str,
        workspace_id: str,
        *,
        limit: int,
        cursor: Optional[str],
    ) -> PublicWorkflowListResponse:
        position = None
        if cursor:
            try:
                position = decode_cursor(cursor)
            except InvalidCursor:
                raise ApiError(422, "invalid_request", "cursor is not valid.")
        rows, nxt = self.owners.list_owned(tenant_id, workspace_id, limit=limit, cursor=position)
        return PublicWorkflowListResponse(
            data=[public_workflow_item(w) for w in rows],
            nextCursor=encode_cursor(*nxt) if nxt else None,
        )

    def get(self, tenant_id: str, workspace_id: str, workflow_id: str) -> PublicWorkflowItem:
        return public_workflow_item(self._owned_or_404(tenant_id, workspace_id, workflow_id))

    def create(
        self,
        tenant_id: str,
        workspace_id: str,
        key_id: str,
        *,
        name: str,
        description: str,
        definition: Dict[str, Any],
    ) -> PublicWorkflowItem:
        _check_shape(definition)
        actor_id = actor_id_for_key(key_id)
        # Serialise creates in this workspace so the count below stays true.
        # The lock is held until the commit inside the core create, and the
        # owner row is written in that same flush, so count and insert are one
        # unit. FOR NO KEY UPDATE: do not wait on child-row inserts.
        self.db.query(Workspace).filter(
            Workspace.id == workspace_id, Workspace.tenant_id == tenant_id
        ).with_for_update(key_share=True).first()
        if self.owners.count_owned(tenant_id, workspace_id) >= MAX_OWNED_WORKFLOWS:
            self.db.rollback()
            raise ApiError(
                422,
                "invalid_request",
                f"This workspace already has the maximum of {MAX_OWNED_WORKFLOWS} workflows. "
                "Delete one before adding another.",
            )

        owners = self.owners

        def _own_new_workflow(session: Session, _ctx: Any, _instances: Any) -> None:
            for obj in list(session.new):
                if isinstance(obj, Workflow) and obj.tenant_id == tenant_id:
                    if obj.id is None:
                        obj.id = str(uuid.uuid4())
                    owners.add(tenant_id, workspace_id, obj.id, actor_id)

        event.listen(self.db, "before_flush", _own_new_workflow, once=True)
        try:
            wf = self.workflows.create(
                tenant_id,
                name=name,
                description=description,
                draft=definition,
                actor_id=actor_id,
                actor=None,
            )
        except Exception:
            self.db.rollback()
            raise
        finally:
            if event.contains(self.db, "before_flush", _own_new_workflow):
                event.remove(self.db, "before_flush", _own_new_workflow)
        return public_workflow_item(wf)

    def update(
        self,
        tenant_id: str,
        workspace_id: str,
        workflow_id: str,
        *,
        name: Optional[str],
        description: Optional[str],
        definition: Optional[Dict[str, Any]],
    ) -> PublicWorkflowItem:
        wf = self._owned_or_404(tenant_id, workspace_id, workflow_id)
        if definition is not None:
            _check_shape(definition)
        updated = self.workflows.update(
            wf.id,
            tenant_id,
            name=wf.name if name is None else name,
            description=wf.description if description is None else description,
            draft=wf.draft_definition_json if definition is None else definition,
            actor=None,
        )
        return public_workflow_item(updated)

    def archive(self, tenant_id: str, workspace_id: str, workflow_id: str) -> None:
        wf = self._owned_or_404(tenant_id, workspace_id, workflow_id)
        self.workflows.archive(wf.id, tenant_id)
