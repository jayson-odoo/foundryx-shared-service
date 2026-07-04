"""Status-engine routes (sprint-2/01). Thin: validate, delegate to
StatusService, shape HTTP. ``statuses.read`` gates reads, ``statuses.manage``
gates configuration; WHO may FIRE a transition is the edge's role list,
enforced by the executor (status_machine), not here.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status as http
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.status import Status
from app.models.status_transition import StatusTransition
from app.models.user import User
from app.schemas.status_engine import (
    MigrateRecordsRequest,
    MigrateRecordsResponse,
    NotificationItem,
    RecipientItem,
    StatusCreateRequest,
    SimulateRequest,
    SimulateResponse,
    SimulateRow,
    StatusEntityItem,
    StatusEntityListResponse,
    StatusGraphResponse,
    StatusItem,
    StatusReorderRequest,
    StatusUpdateRequest,
    TransitionCreateRequest,
    TransitionItem,
    TransitionRoleItem,
    TransitionUpdateRequest,
)
from app.services.status_service import (
    EntityNotEditable,
    EntityNotFound,
    StatusEngineError,
    StatusNotFound,
    StatusReferenced,
    StatusService,
    StatusValidationError,
    SystemStatusProtected,
    TransitionNotFound,
    UNSET,
)

router = APIRouter()
entities_router = APIRouter()


def _status_item(row: Status, record_count: int) -> StatusItem:
    return StatusItem(
        id=row.id,
        entityType=row.entity_type,
        key=row.key,
        label=row.label,
        color=row.color,
        sortOrder=row.sort_order,
        isInitial=row.is_initial,
        isTerminal=row.is_terminal,
        isActive=row.is_active,
        blocksAccess=row.blocks_access,
        isArchived=row.is_archived,
        isDefault=row.is_default,
        positionX=row.position_x,
        positionY=row.position_y,
        isSystem=row.is_system,
        recordCount=record_count,
    )


def _transition_item(edge: StatusTransition) -> TransitionItem:
    return TransitionItem(
        id=edge.id,
        entityType=edge.entity_type,
        fromStatusId=edge.from_status_id,
        toStatusId=edge.to_status_id,
        label=edge.label,
        sortOrder=edge.sort_order,
        conditionsJson=edge.conditions_json,
        triggerMode=edge.trigger_mode,
        roles=[TransitionRoleItem(id=r.id, name=r.name) for r in edge.roles],
        notifications=[
            NotificationItem(
                channel=spec.channel,
                templateSubject=spec.template_subject,
                templateBody=spec.template_body,
                templateKey=spec.template_key,
                templateId=spec.template_id,
                doc=spec.doc_json,
                recipients=[
                    RecipientItem(
                        targetType=r.target_type,
                        targetId=r.target_id,
                        dynamicKey=r.dynamic_key,
                    )
                    for r in spec.recipients
                ],
            )
            for spec in edge.notification_specs
        ],
    )


def _raise(exc: StatusEngineError) -> None:
    if isinstance(exc, (EntityNotFound, StatusNotFound, TransitionNotFound)):
        raise HTTPException(http.HTTP_404_NOT_FOUND, exc.message)
    if isinstance(exc, EntityNotEditable):
        raise HTTPException(http.HTTP_403_FORBIDDEN, exc.message)
    if isinstance(exc, StatusReferenced):
        raise HTTPException(http.HTTP_409_CONFLICT, exc.message)
    if isinstance(exc, SystemStatusProtected):
        raise HTTPException(http.HTTP_409_CONFLICT, exc.message)
    if isinstance(exc, StatusValidationError):
        raise HTTPException(http.HTTP_422_UNPROCESSABLE_ENTITY, exc.message)
    raise HTTPException(http.HTTP_400_BAD_REQUEST, exc.message)


# ---- registry ----


@entities_router.get("", response_model=StatusEntityListResponse)
def list_status_entities(
    current_user: User = Depends(require_permission("statuses.read")),
    db: Session = Depends(get_db),
) -> StatusEntityListResponse:
    service = StatusService(db)
    entities = service.list_entities(current_user)
    items = []
    for e in entities:
        stats = service.entity_stats(e, current_user)
        items.append(
            StatusEntityItem(
                entityType=e.entity_type,
                label=e.label,
                module=e.module,
                platformOwned=e.platform_owned,
                requiredFlags=e.required_flags,
                statusCount=stats["status_count"],
                transitionCount=stats["transition_count"],
                customized=stats["customized"],
                hasTimeAutoEdges=e.has_time_auto_edges,
            )
        )
    return StatusEntityListResponse(data=items)


@entities_router.post("/{entity_type}/simulate", response_model=SimulateResponse)
def simulate_date(
    entity_type: str,
    payload: SimulateRequest,
    current_user: User = Depends(require_permission("statuses.manage")),
    db: Session = Depends(get_db),
) -> SimulateResponse:
    """Admin date-simulation (sprint-4/03 Slice 6) — run this entity's time sweep
    AS-OF a date, tenant-scoped. Dry-run (default) previews the would-advance
    records without persisting; ``apply`` commits them."""
    from app.workflow_engine.scheduler import simulate_entity_sweep

    rows = simulate_entity_sweep(
        db, entity_type, current_user.tenant_id, payload.asOf, apply=payload.apply
    )
    return SimulateResponse(data=[SimulateRow(**r) for r in rows], applied=payload.apply)


# ---- graph read ----


@router.get("", response_model=StatusGraphResponse)
def get_status_graph(
    entity_type: str = Query(alias="entityType"),
    scope_id: str | None = Query(default=None, alias="scopeId"),
    current_user: User = Depends(require_permission("statuses.read")),
    db: Session = Depends(get_db),
) -> StatusGraphResponse:
    service = StatusService(db)
    try:
        _entity, tier, statuses, transitions, counts = service.get_graph(
            entity_type, current_user, scope_id=scope_id
        )
    except StatusEngineError as exc:
        _raise(exc)
    return StatusGraphResponse(
        entityType=entity_type,
        source="platform" if tier is None else "tenant",
        statuses=[_status_item(s, counts.get(s.id, 0)) for s in statuses],
        transitions=[_transition_item(t) for t in transitions],
    )


# ---- status CRUD ----


@router.post("", response_model=StatusItem, status_code=http.HTTP_201_CREATED)
def create_status(
    payload: StatusCreateRequest,
    current_user: User = Depends(require_permission("statuses.manage")),
    db: Session = Depends(get_db),
) -> StatusItem:
    service = StatusService(db)
    try:
        row = service.create_status(
            payload.entityType,
            current_user,
            label=payload.label,
            color=payload.color,
            key=payload.key,
            flags=payload.flags.to_columns() if payload.flags else None,
            position_x=payload.positionX,
            position_y=payload.positionY,
            scope_id=payload.scopeId,
        )
    except StatusEngineError as exc:
        _raise(exc)
    return _status_item(row, 0)


@router.post("/reorder", response_model=StatusGraphResponse)
def reorder_statuses(
    payload: StatusReorderRequest,
    current_user: User = Depends(require_permission("statuses.manage")),
    db: Session = Depends(get_db),
) -> StatusGraphResponse:
    service = StatusService(db)
    try:
        service.reorder(
            payload.entityType, payload.orderedIds, current_user, scope_id=payload.scopeId
        )
    except StatusEngineError as exc:
        _raise(exc)
    return get_status_graph(payload.entityType, payload.scopeId, current_user, db)


@router.patch("/{status_id}", response_model=StatusItem)
def update_status(
    status_id: str,
    payload: StatusUpdateRequest,
    current_user: User = Depends(require_permission("statuses.manage")),
    db: Session = Depends(get_db),
) -> StatusItem:
    service = StatusService(db)
    try:
        row = service.update_status(
            status_id,
            current_user,
            label=payload.label,
            color=payload.color,
            flags=payload.flags.to_columns() if payload.flags else None,
            position_x=payload.positionX,
            position_y=payload.positionY,
            fields_set=payload.model_fields_set,
        )
    except StatusEngineError as exc:
        _raise(exc)
    return _status_item(row, 0)


@router.delete("/{status_id}", status_code=http.HTTP_204_NO_CONTENT)
def delete_status(
    status_id: str,
    current_user: User = Depends(require_permission("statuses.manage")),
    db: Session = Depends(get_db),
) -> None:
    try:
        StatusService(db).delete_status(status_id, current_user)
    except StatusEngineError as exc:
        _raise(exc)


@router.post("/{status_id}/deactivate", response_model=StatusItem)
def deactivate_status(
    status_id: str,
    current_user: User = Depends(require_permission("statuses.manage")),
    db: Session = Depends(get_db),
) -> StatusItem:
    try:
        row = StatusService(db).set_status_active(status_id, current_user, False)
    except StatusEngineError as exc:
        _raise(exc)
    return _status_item(row, 0)


@router.post("/{status_id}/activate", response_model=StatusItem)
def activate_status(
    status_id: str,
    current_user: User = Depends(require_permission("statuses.manage")),
    db: Session = Depends(get_db),
) -> StatusItem:
    try:
        row = StatusService(db).set_status_active(status_id, current_user, True)
    except StatusEngineError as exc:
        _raise(exc)
    return _status_item(row, 0)


@router.post("/{status_id}/migrate-records", response_model=MigrateRecordsResponse)
def migrate_records(
    status_id: str,
    payload: MigrateRecordsRequest,
    current_user: User = Depends(require_permission("statuses.manage")),
    db: Session = Depends(get_db),
) -> MigrateRecordsResponse:
    try:
        migrated = StatusService(db).migrate_records(
            status_id, payload.toStatusId, current_user
        )
    except StatusEngineError as exc:
        _raise(exc)
    return MigrateRecordsResponse(migrated=migrated)


# ---- transitions ----


@router.post("/transitions", response_model=TransitionItem, status_code=http.HTTP_201_CREATED)
def create_transition(
    payload: TransitionCreateRequest,
    current_user: User = Depends(require_permission("statuses.manage")),
    db: Session = Depends(get_db),
) -> TransitionItem:
    service = StatusService(db)
    try:
        edge = service.create_transition(
            payload.entityType,
            current_user,
            from_status_id=payload.fromStatusId,
            to_status_id=payload.toStatusId,
            label=payload.label,
            sort_order=payload.sortOrder,
            role_ids=payload.roleIds,
            notifications=[n.model_dump() for n in payload.notifications],
            conditions=payload.conditionsJson,
            trigger_mode=payload.triggerMode,
            scope_id=payload.scopeId,
        )
    except StatusEngineError as exc:
        _raise(exc)
    return _transition_item(edge)


@router.patch("/transitions/{transition_id}", response_model=TransitionItem)
def update_transition(
    transition_id: str,
    payload: TransitionUpdateRequest,
    current_user: User = Depends(require_permission("statuses.manage")),
    db: Session = Depends(get_db),
) -> TransitionItem:
    service = StatusService(db)
    try:
        edge = service.update_transition(
            transition_id,
            current_user,
            label=payload.label,
            sort_order=payload.sortOrder,
            role_ids=payload.roleIds,
            notifications=(
                [n.model_dump() for n in payload.notifications]
                if payload.notifications is not None
                else None
            ),
            # Absent = keep, null = clear (PATCH semantics via fields_set).
            conditions=(
                payload.conditionsJson
                if "conditionsJson" in payload.model_fields_set
                else UNSET
            ),
            trigger_mode=payload.triggerMode,
        )
    except StatusEngineError as exc:
        _raise(exc)
    return _transition_item(edge)


@router.delete("/transitions/{transition_id}", status_code=http.HTTP_204_NO_CONTENT)
def delete_transition(
    transition_id: str,
    current_user: User = Depends(require_permission("statuses.manage")),
    db: Session = Depends(get_db),
) -> None:
    try:
        StatusService(db).delete_transition(transition_id, current_user)
    except StatusEngineError as exc:
        _raise(exc)
