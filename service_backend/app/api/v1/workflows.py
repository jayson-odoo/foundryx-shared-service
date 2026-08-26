"""Workflow engine endpoints (plan sprint-2/08) - gated workflows.read /
.manage / .run. Tenant-scoped: a tenant only ever sees/acts on its own
workflows (scope = the authed user's tenant)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.dependencies import effective_permission_keys, get_db, require_permission
from app.models.user import User
from app.schemas.filters import FilterGroup
from app.schemas.workflow import (
    TemplateOptionOut,
    WorkflowActiveRequest,
    WorkflowCreateRequest,
    WorkflowDebugRequest,
    WorkflowDebugResultOut,
    WorkflowDetailOut,
    WorkflowNeighborResponse,
    WorkflowRunDetailOut,
    WorkflowRunItemOut,
    WorkflowRunListResponse,
    WorkflowRunRequest,
    WorkflowListResponse,
    WorkflowSettingsOut,
    WorkflowSettingsUpdate,
    WorkflowUpdateRequest,
    WorkflowVersionListResponse,
)
from app.services.filter_translator import FilterError
from app.services.workflow_service import WorkflowError, WorkflowNotFound, WorkflowService
from app.workflow_engine import WorkflowValidationError
from app.workflow_engine.registry import TriggerTestDataError

router = APIRouter()


def _parse_filter(raw: Optional[str]) -> Optional[FilterGroup]:
    if not raw:
        return None
    try:
        return FilterGroup.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid filter.") from exc


# ---- list ----


@router.get("", response_model=WorkflowListResponse)
def list_workflows(
    current_user: User = Depends(require_permission("workflows.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    status_view: Optional[str] = None,
    filter: Optional[str] = None,
) -> WorkflowListResponse:
    service = WorkflowService(db)
    try:
        items, total = service.list(
            current_user.tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            status_view=status_view,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return WorkflowListResponse(data=items, total=total, page=page)


@router.get("/at", response_model=WorkflowNeighborResponse)
def workflow_at(
    index: int = Query(0, ge=0),
    current_user: User = Depends(require_permission("workflows.read")),
    db: Session = Depends(get_db),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    status_view: Optional[str] = None,
    filter: Optional[str] = None,
) -> WorkflowNeighborResponse:
    service = WorkflowService(db)
    item, total = service.get_at(
        index,
        current_user.tenant_id,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        status_view=status_view,
        filter_group=_parse_filter(filter),
    )
    return WorkflowNeighborResponse(workflow=item, total=total)


@router.get("/template-options", response_model=List[TemplateOptionOut])
def template_options(
    current_user: User = Depends(require_permission("workflows.read")),
    db: Session = Depends(get_db),
) -> List[TemplateOptionOut]:
    rows = WorkflowService(db).template_options(current_user.tenant_id)
    return [TemplateOptionOut(value=r["value"], label=r["label"]) for r in rows]


@router.get("/metadata")
def workflow_metadata(
    current_user: User = Depends(require_permission("workflows.read")),
    db: Session = Depends(get_db),
) -> dict:
    """Triggerable entities + statuses + record fields for the editor pickers."""
    can_read_ai_agents = "ai_agents.read" in effective_permission_keys(current_user)
    return WorkflowService(db).metadata(
        current_user.tenant_id,
        include_ai_agents=can_read_ai_agents,
    )


@router.get("/settings", response_model=WorkflowSettingsOut)
def get_workflow_settings(
    current_user: User = Depends(require_permission("workflows.manage")),
    db: Session = Depends(get_db),
) -> WorkflowSettingsOut:
    """Tenant workflow settings - run retention (plan 10)."""
    days, is_default = WorkflowService(db).get_run_retention(current_user.tenant_id)
    return WorkflowSettingsOut(run_retention_days=days, is_default=is_default)


@router.put("/settings", response_model=WorkflowSettingsOut)
def update_workflow_settings(
    body: WorkflowSettingsUpdate,
    current_user: User = Depends(require_permission("workflows.manage")),
    db: Session = Depends(get_db),
) -> WorkflowSettingsOut:
    days, is_default = WorkflowService(db).set_run_retention(
        current_user.tenant_id, body.runRetentionDays
    )
    return WorkflowSettingsOut(run_retention_days=days, is_default=is_default)


# ---- run reads (specific path before /{id}) ----


@router.get("/runs/{run_id}", response_model=WorkflowRunDetailOut)
def get_run(
    run_id: str,
    current_user: User = Depends(require_permission("workflows.read")),
    db: Session = Depends(get_db),
) -> WorkflowRunDetailOut:
    try:
        return WorkflowService(db).get_run_detail(run_id, current_user.tenant_id)
    except WorkflowNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found.")


@router.post("/runs/{run_id}/cancel", response_model=WorkflowRunItemOut)
def cancel_run(
    run_id: str,
    current_user: User = Depends(require_permission("workflows.run")),
    db: Session = Depends(get_db),
) -> WorkflowRunItemOut:
    try:
        return WorkflowService(db).cancel_run(run_id, current_user.tenant_id)
    except WorkflowNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found.")
    except WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))


# ---- detail + writes ----


@router.get("/{workflow_id}", response_model=WorkflowDetailOut)
def get_workflow(
    workflow_id: str,
    current_user: User = Depends(require_permission("workflows.read")),
    db: Session = Depends(get_db),
) -> WorkflowDetailOut:
    service = WorkflowService(db)
    try:
        return service.to_detail(service.get(workflow_id, current_user.tenant_id))
    except WorkflowNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")


@router.post("", response_model=WorkflowDetailOut, status_code=status.HTTP_201_CREATED)
def create_workflow(
    body: WorkflowCreateRequest,
    current_user: User = Depends(require_permission("workflows.manage")),
    db: Session = Depends(get_db),
) -> WorkflowDetailOut:
    service = WorkflowService(db)
    wf = service.create(
        current_user.tenant_id,
        name=body.name,
        description=body.description,
        draft=body.draftDefinition,
        actor_id=current_user.id,
    )
    return service.to_detail(wf)


@router.patch("/{workflow_id}", response_model=WorkflowDetailOut)
def update_workflow(
    workflow_id: str,
    body: WorkflowUpdateRequest,
    current_user: User = Depends(require_permission("workflows.manage")),
    db: Session = Depends(get_db),
) -> WorkflowDetailOut:
    service = WorkflowService(db)
    try:
        wf = service.update(
            workflow_id,
            current_user.tenant_id,
            name=body.name,
            description=body.description,
            draft=body.draftDefinition,
        )
    except WorkflowNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    return service.to_detail(wf)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(
    workflow_id: str,
    current_user: User = Depends(require_permission("workflows.manage")),
    db: Session = Depends(get_db),
) -> None:
    try:
        WorkflowService(db).remove(workflow_id, current_user.tenant_id)
    except WorkflowNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")


def _action(workflow_id: str, current_user: User, db: Session, fn) -> WorkflowDetailOut:
    service = WorkflowService(db)
    try:
        wf = fn(service)
    except WorkflowNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    except WorkflowValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "; ".join(exc.issues))
    except WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return service.to_detail(wf)


@router.post("/{workflow_id}/duplicate", response_model=WorkflowDetailOut)
def duplicate_workflow(workflow_id: str, current_user: User = Depends(require_permission("workflows.manage")), db: Session = Depends(get_db)) -> WorkflowDetailOut:
    return _action(workflow_id, current_user, db, lambda s: s.duplicate(workflow_id, current_user.tenant_id, current_user.id))


@router.post("/{workflow_id}/active", response_model=WorkflowDetailOut)
def set_active(workflow_id: str, body: WorkflowActiveRequest, current_user: User = Depends(require_permission("workflows.manage")), db: Session = Depends(get_db)) -> WorkflowDetailOut:
    return _action(workflow_id, current_user, db, lambda s: s.set_active(workflow_id, current_user.tenant_id, body.isActive))


@router.post("/{workflow_id}/publish", response_model=WorkflowDetailOut)
def publish_workflow(workflow_id: str, current_user: User = Depends(require_permission("workflows.manage")), db: Session = Depends(get_db)) -> WorkflowDetailOut:
    return _action(workflow_id, current_user, db, lambda s: s.publish(workflow_id, current_user.tenant_id, current_user.id))


@router.post("/{workflow_id}/unpublish", response_model=WorkflowDetailOut)
def unpublish_workflow(workflow_id: str, current_user: User = Depends(require_permission("workflows.manage")), db: Session = Depends(get_db)) -> WorkflowDetailOut:
    return _action(workflow_id, current_user, db, lambda s: s.unpublish(workflow_id, current_user.tenant_id))


@router.post("/{workflow_id}/archive", response_model=WorkflowDetailOut)
def archive_workflow(workflow_id: str, current_user: User = Depends(require_permission("workflows.manage")), db: Session = Depends(get_db)) -> WorkflowDetailOut:
    return _action(workflow_id, current_user, db, lambda s: s.archive(workflow_id, current_user.tenant_id))


@router.post("/{workflow_id}/restore", response_model=WorkflowDetailOut)
def restore_workflow(workflow_id: str, current_user: User = Depends(require_permission("workflows.manage")), db: Session = Depends(get_db)) -> WorkflowDetailOut:
    return _action(workflow_id, current_user, db, lambda s: s.restore(workflow_id, current_user.tenant_id))


# ---- run + debug ----


@router.post("/{workflow_id}/run", response_model=WorkflowRunItemOut)
def run_workflow(
    workflow_id: str,
    body: WorkflowRunRequest,
    current_user: User = Depends(require_permission("workflows.run")),
    db: Session = Depends(get_db),
) -> WorkflowRunItemOut:
    service = WorkflowService(db)
    try:
        run = service.run(
            workflow_id,
            current_user.tenant_id,
            inputs=body.inputs,
            is_test=body.isTest,
            actor=current_user,
            test_trigger=(body.testTrigger.model_dump() if body.testTrigger else None),
        )
    except WorkflowNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    except TriggerTestDataError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return WorkflowRunItemOut.from_row(run, current_user.name or current_user.email)


@router.get("/{workflow_id}/test-options")
def workflow_test_options(
    workflow_id: str,
    current_user: User = Depends(require_permission("workflows.run")),
    _conversation_reader: User = Depends(require_permission("conversations.read")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return WorkflowService(db).test_options(workflow_id, current_user.tenant_id)
    except WorkflowNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")


@router.get("/{workflow_id}/runs", response_model=WorkflowRunListResponse)
def list_runs(
    workflow_id: str,
    current_user: User = Depends(require_permission("workflows.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    segment: Optional[str] = None,
) -> WorkflowRunListResponse:
    service = WorkflowService(db)
    try:
        items, total = service.list_runs(
            workflow_id, current_user.tenant_id, page=page, page_size=page_size, segment=segment
        )
    except WorkflowNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    return WorkflowRunListResponse(data=items, total=total, page=page)


@router.get("/{workflow_id}/versions", response_model=WorkflowVersionListResponse)
def list_versions(
    workflow_id: str,
    current_user: User = Depends(require_permission("workflows.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100),
) -> WorkflowVersionListResponse:
    service = WorkflowService(db)
    try:
        items, total = service.list_versions(workflow_id, current_user.tenant_id, page=page, page_size=page_size)
    except WorkflowNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found.")
    return WorkflowVersionListResponse(data=items, total=total, page=page)


@router.post("/{workflow_id}/debug", response_model=WorkflowDebugResultOut)
def debug_execute(
    workflow_id: str,
    body: WorkflowDebugRequest,
    current_user: User = Depends(require_permission("workflows.run")),
    db: Session = Depends(get_db),
) -> WorkflowDebugResultOut:
    service = WorkflowService(db)
    try:
        nodes = service.debug_execute(
            workflow_id,
            current_user.tenant_id,
            run_id=body.runId,
            target_node_id=body.targetNodeId,
            scratch=body.scratch,
            stale_node_ids=body.staleNodeIds,
        )
    except WorkflowNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow or run not found.")
    return WorkflowDebugResultOut(nodes=nodes)
