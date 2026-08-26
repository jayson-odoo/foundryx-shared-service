"""Platform Console tenant routes (plan 07 §9). Thin: validate, delegate to
TenantService, shape HTTP. ALL routes are operator-only -
``require_platform_permission`` = permission key AND platform-tenant membership.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_platform_permission
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.filters import FilterGroup
from app.schemas.status_engine import StatusGraphResponse
from app.schemas.tenant import (
    TenantDetail,
    TenantExportRequest,
    TenantItem,
    TenantListResponse,
    TenantNeighborResponse,
    TenantProvisionRequest,
    TenantPurgeRequest,
    TenantTransitionItem,
    TenantTransitionListResponse,
    TenantTransitionRequest,
    TenantUpdate,
)
from app.services.filter_translator import FilterError
from app.services.tenant_service import (
    DomainTaken,
    InvalidTransition,
    PlatformTenantProtected,
    PurgeConfirmMismatch,
    SlugInvalid,
    SlugTaken,
    TenantNotArchived,
    TenantNotFound,
    TenantService,
)

router = APIRouter()


def _parse_filter(raw: Optional[str]) -> Optional[FilterGroup]:
    if not raw:
        return None
    try:
        return FilterGroup.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid filter.") from exc


def _item(
    tenant: Tenant,
    user_count: int,
    available_transition_ids: Optional[list] = None,
) -> TenantItem:
    return TenantItem(
        availableTransitionIds=available_transition_ids,
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        # Legacy uppercase wire value (cosmetic category mirror); label/color
        # are the engine-driven display fields (sprint-2/01).
        status=tenant.status.category or tenant.status.key.upper(),
        statusId=tenant.status_id,
        statusLabel=tenant.status.label,
        statusColor=tenant.status.color,
        isPlatform=tenant.is_platform,
        contactName=tenant.contact_name,
        contactEmail=tenant.contact_email,
        customDomain=tenant.custom_domain,
        userCount=user_count,
        createdAt=tenant.created_at,
    )


def _fireable(service: TenantService, tenant: Tenant, user: User) -> Optional[list]:
    """Per-record fireable edge ids for ONE row (None while unconditioned)."""
    mapping = service.available_transition_ids([tenant], user)
    return mapping.get(tenant.id, []) if mapping else None


def _detail(
    tenant: Tenant,
    user_count: int,
    available_transition_ids: Optional[list] = None,
) -> TenantDetail:
    return TenantDetail(
        **_item(tenant, user_count, available_transition_ids).model_dump(),
        notes=tenant.notes,
        updatedAt=tenant.updated_at,
    )


# ---- list / neighbour / export ----


@router.get("", response_model=TenantListResponse)
def list_tenants(
    current_user: User = Depends(require_platform_permission("tenants.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    status_view: str = Query("active", pattern="^(active|trashed)$"),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> TenantListResponse:
    service = TenantService(db)
    try:
        rows, total = service.list(
            page=page,
            page_size=page_size,
            status_view=status_view,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    counts = service.user_counts([t.id for t in rows])
    # Rule-engine D6: per-record fireable edges, only while conditions exist.
    fireable = service.available_transition_ids(rows, current_user)
    return TenantListResponse(
        data=[
            _item(t, counts.get(t.id, 0), fireable.get(t.id, []) if fireable else None)
            for t in rows
        ],
        total=total,
        page=page,
    )


@router.get("/at", response_model=TenantNeighborResponse)
def tenant_at(
    current_user: User = Depends(require_platform_permission("tenants.read")),
    db: Session = Depends(get_db),
    index: int = Query(0, ge=0),
    status_view: str = Query("active", pattern="^(active|trashed)$"),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> TenantNeighborResponse:
    service = TenantService(db)
    try:
        tenant, total = service.get_at(
            index,
            status_view=status_view,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    if tenant is None:
        return TenantNeighborResponse(tenant=None, total=total)
    counts = service.user_counts([tenant.id])
    return TenantNeighborResponse(
        tenant=_detail(tenant, counts.get(tenant.id, 0), _fireable(service, tenant, current_user)),
        total=total,
    )


@router.post("/export", response_class=PlainTextResponse)
def export_tenants(
    payload: TenantExportRequest,
    current_user: User = Depends(require_platform_permission("tenants.read")),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    service = TenantService(db)
    try:
        csv_text = service.export_csv(
            payload.columns,
            ids=payload.ids,
            status_view=payload.statusView or "active",
            search=payload.search,
            sort_by=payload.sortBy,
            sort_dir=payload.sortDir or "asc",
            filter_group=payload.filter,
        )
    except FilterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tenants.csv"},
    )


# Registered BEFORE /{tenant_id} so the literal path wins the match.
@router.get("/status-graph", response_model=StatusGraphResponse)
def tenant_status_graph(
    current_user: User = Depends(require_platform_permission("tenants.read")),
    db: Session = Depends(get_db),
) -> StatusGraphResponse:
    """The tenant entity's status graph for the console's action registry -
    gated by ``tenants.read`` so lifecycle buttons never depend on the
    operator also holding ``statuses.read`` (code-review fix)."""
    from app.api.v1.statuses import get_status_graph

    # Keyword args - get_status_graph grew a ``scope_id`` parameter (scoped
    # status machines, sprint-3/01 D4) between entity_type and current_user, so
    # a positional call would land current_user in scope_id.
    return get_status_graph(entity_type="tenant", current_user=current_user, db=db)


# ---- provision / get / update ----


@router.post("", response_model=TenantDetail, status_code=status.HTTP_201_CREATED)
def provision_tenant(
    payload: TenantProvisionRequest,
    current_user: User = Depends(require_platform_permission("tenants.create")),
    db: Session = Depends(get_db),
) -> TenantDetail:
    service = TenantService(db)
    try:
        tenant = service.provision(
            name=payload.name,
            slug=payload.slug,
            contact_name=payload.contactName,
            contact_email=payload.contactEmail,
            notes=payload.notes,
            admin_name=payload.adminName,
            admin_email=payload.adminEmail,
            admin_password=payload.adminPassword,
        )
    except SlugInvalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.message)
    except SlugTaken:
        raise HTTPException(status.HTTP_409_CONFLICT, "This slug is already taken.")
    return _detail(tenant, 1)


@router.get("/{tenant_id}", response_model=TenantDetail)
def get_tenant(
    tenant_id: str,
    current_user: User = Depends(require_platform_permission("tenants.read")),
    db: Session = Depends(get_db),
) -> TenantDetail:
    service = TenantService(db)
    try:
        tenant = service.get(tenant_id)
    except TenantNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")
    counts = service.user_counts([tenant.id])
    return _detail(tenant, counts.get(tenant.id, 0), _fireable(service, tenant, current_user))


@router.patch("/{tenant_id}", response_model=TenantDetail)
def update_tenant(
    tenant_id: str,
    payload: TenantUpdate,
    current_user: User = Depends(require_platform_permission("tenants.update")),
    db: Session = Depends(get_db),
) -> TenantDetail:
    service = TenantService(db)
    try:
        tenant = service.update(
            tenant_id,
            name=payload.name,
            contact_name=payload.contactName,
            contact_email=payload.contactEmail,
            custom_domain=payload.customDomain,
            notes=payload.notes,
            fields_set=payload.model_fields_set,
        )
    except TenantNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")
    except DomainTaken:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This custom domain is already used by another tenant."
        )
    counts = service.user_counts([tenant.id])
    return _detail(tenant, counts.get(tenant.id, 0))


# ---- lifecycle (plan 07 §4 → status machine, sprint-2/01) ----


def _lifecycle(action: str, tenant_id: str, db: Session, actor: User) -> TenantDetail:
    service = TenantService(db)
    try:
        tenant = getattr(service, action)(tenant_id, actor)
    except TenantNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")
    except PlatformTenantProtected:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The platform tenant cannot be suspended or archived."
        )
    except InvalidTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message)
    counts = service.user_counts([tenant.id])
    return _detail(tenant, counts.get(tenant.id, 0), _fireable(service, tenant, actor))


@router.post("/{tenant_id}/suspend", response_model=TenantDetail)
def suspend_tenant(
    tenant_id: str,
    current_user: User = Depends(require_platform_permission("tenants.suspend")),
    db: Session = Depends(get_db),
) -> TenantDetail:
    return _lifecycle("suspend", tenant_id, db, current_user)


@router.post("/{tenant_id}/reactivate", response_model=TenantDetail)
def reactivate_tenant(
    tenant_id: str,
    current_user: User = Depends(require_platform_permission("tenants.suspend")),
    db: Session = Depends(get_db),
) -> TenantDetail:
    return _lifecycle("reactivate", tenant_id, db, current_user)


@router.post("/{tenant_id}/archive", response_model=TenantDetail)
def archive_tenant(
    tenant_id: str,
    current_user: User = Depends(require_platform_permission("tenants.archive")),
    db: Session = Depends(get_db),
) -> TenantDetail:
    return _lifecycle("archive", tenant_id, db, current_user)


# ---- generic graph transitions (sprint-2/01) ----


def _transition_permission(to_status) -> str:
    """The legacy privilege boundary, derived from the TARGET's trait flags
    (code-review fix): archiving-like moves need ``tenants.archive``;
    everything else (suspend / reactivate / custom blocks) stays under
    ``tenants.suspend`` - exactly the keys the dedicated endpoints used, so
    introducing the generic endpoint grants nobody new capability."""
    return "tenants.archive" if to_status is not None and to_status.is_archived else "tenants.suspend"


@router.get("/{tenant_id}/transitions", response_model=TenantTransitionListResponse)
def list_tenant_transitions(
    tenant_id: str,
    current_user: User = Depends(require_platform_permission("tenants.read")),
    db: Session = Depends(get_db),
) -> TenantTransitionListResponse:
    """Outgoing edges from the tenant's current status the actor may fire -
    edge label = action button text."""
    service = TenantService(db)
    try:
        edges = service.available_transitions(tenant_id, current_user)
    except TenantNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")
    return TenantTransitionListResponse(
        data=[
            TenantTransitionItem(
                id=e.id,
                label=e.label,
                toStatusId=e.to_status_id,
                toStatusLabel=e.to_status.label,
                toStatusColor=e.to_status.color,
            )
            for e in edges
        ]
    )


@router.post("/{tenant_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge_tenant(
    tenant_id: str,
    payload: TenantPurgeRequest,
    current_user: User = Depends(require_platform_permission("tenants.delete")),
    db: Session = Depends(get_db),
) -> None:
    """Hard-delete an ARCHIVED tenant + all its rows (BL-035). Irreversible -
    typed slug confirm, archive-first two-step."""
    try:
        TenantService(db).purge(tenant_id, payload.confirmSlug)
    except TenantNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")
    except PlatformTenantProtected:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The platform tenant cannot be deleted."
        )
    except PurgeConfirmMismatch:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Confirmation does not match the tenant slug.",
        )
    except TenantNotArchived as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message)


@router.post("/{tenant_id}/transition", response_model=TenantDetail)
def fire_tenant_transition(
    tenant_id: str,
    payload: TenantTransitionRequest,
    current_user: User = Depends(require_platform_permission("tenants.read")),
    db: Session = Depends(get_db),
) -> TenantDetail:
    from app.dependencies import effective_permission_keys
    from app.repositories.status_transition_repository import StatusTransitionRepository

    # Permission depends on the edge's TARGET (legacy boundary preserved):
    # archive-like → tenants.archive, everything else → tenants.suspend.
    edge = StatusTransitionRepository(db).get_by_id(payload.transitionId)
    needed = _transition_permission(edge.to_status if edge else None)
    if needed not in effective_permission_keys(current_user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Missing permission: {needed}"
        )

    service = TenantService(db)
    try:
        tenant = service.transition(tenant_id, payload.transitionId, current_user)
    except TenantNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")
    except PlatformTenantProtected:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The platform tenant cannot be suspended or archived."
        )
    except InvalidTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message)
    counts = service.user_counts([tenant.id])
    return _detail(tenant, counts.get(tenant.id, 0), _fireable(service, tenant, current_user))
