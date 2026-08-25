"""Company routes - thin: HTTP + Pydantic only.

No DB query and no raw SQL lives here (code-review hard-fail). Every handler
takes the tenant from the authenticated user - NEVER from client input - and
hands off to a service.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import (
    CompanyCreate,
    CompanyDetailResponse,
    CompanyItem,
    CompanyListResponse,
    CompanySinkUpdate,
    EntityConfigItem,
    EntityConfigUpdate,
    FormulaTestRequest,
    FormulaTestResponse,
    MappingRowOut,
    MappingUpdateRequest,
    MappingViewResponse,
    SimulateRequest,
    SimulateResponse,
    SorentoFieldOut,
)
from ..services import (
    AutocountServiceError,
    CompanyAlreadyExists,
    CompanyNotFound,
    CompanyService,
    ConnectionNotFound,
    EntityConfigNotFound,
    MappingView,
    MappingWriteRow,
)

router = APIRouter()


def _raise(exc: AutocountServiceError) -> None:
    """ONE translator for every service error → HTTP. Messages are already
    operator-safe (no stack traces, no credentials)."""
    if isinstance(exc, (CompanyNotFound, ConnectionNotFound, EntityConfigNotFound)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    if isinstance(exc, CompanyAlreadyExists):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
    )


@router.get("", response_model=CompanyListResponse)
def list_companies(
    current_user: User = Depends(require_permission("autocount.companies.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
) -> CompanyListResponse:
    rows, total = CompanyService(db).list(
        current_user.tenant_id, page=page, page_size=page_size
    )
    return CompanyListResponse(
        data=[CompanyItem.model_validate(row) for row in rows], total=total, page=page
    )


@router.post("", response_model=CompanyItem, status_code=status.HTTP_201_CREATED)
def create_company(
    body: CompanyCreate,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> CompanyItem:
    """Register an AutoCount company by DISCOVERING it from its connection."""
    try:
        company = CompanyService(db).create_from_connection(
            current_user.tenant_id, body.connectionId, name=body.name
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return CompanyItem.model_validate(company)


@router.get("/{company_id}", response_model=CompanyDetailResponse)
def get_company(
    company_id: str,
    current_user: User = Depends(require_permission("autocount.companies.read")),
    db: Session = Depends(get_db),
) -> CompanyDetailResponse:
    service = CompanyService(db)
    try:
        company = service.get(current_user.tenant_id, company_id)
        # Config JOINED with the watermark: the Entities surface needs the delta
        # state (last synced, failures, last error) to explain a zero-record run.
        entities = service.entity_states(current_user.tenant_id, company_id)
    except AutocountServiceError as exc:
        _raise(exc)
    return CompanyDetailResponse(
        company=CompanyItem.model_validate(company),
        entities=[EntityConfigItem.model_validate(row) for row in entities],
    )


@router.patch("/{company_id}/sink-target", response_model=CompanyItem)
def set_sink_target(
    company_id: str,
    body: CompanySinkUpdate,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> CompanyItem:
    """Point a company at its consumer push target (hop 2).

    ``logging`` keeps the no-op default; ``sorento`` requires a Sorento
    ``consumer`` connection id, validated to belong to this tenant. Reuses
    ``autocount.companies.manage`` - the same "configure the company" authority -
    so no new permission needs a grant sweep for existing tenants."""
    try:
        company = CompanyService(db).set_sink_target(
            current_user.tenant_id,
            company_id,
            sink_impl=body.sinkImpl,
            sink_connection_id=body.sinkConnectionId,
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return CompanyItem.model_validate(company)


@router.patch(
    "/{company_id}/entities/{entity_type}", response_model=EntityConfigItem
)
def update_entity_config(
    company_id: str,
    entity_type: str,
    body: EntityConfigUpdate,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> EntityConfigItem:
    """Adjust one entity's sync configuration (the initial lookback window).

    Reuses ``autocount.companies.manage`` rather than minting a permission: a
    new key would not reach existing tenants' Admin roles without a grant sweep,
    and this is the same "configure the company" authority.
    """
    try:
        state = CompanyService(db).update_entity_config(
            current_user.tenant_id,
            company_id,
            entity_type,
            initial_lookback_days=body.initialLookbackDays,
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return EntityConfigItem.model_validate(state)


@router.post(
    "/{company_id}/entities/{entity_type}/refetch", response_model=EntityConfigItem
)
def refetch_entity(
    company_id: str,
    entity_type: str,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> EntityConfigItem:
    """Re-open the first-run window by resetting the entity's watermark, so the
    next sync re-fetches history from scratch (AC-15-30).

    Deliberately a POST (a state change, not idempotent config) and distinct from
    the entity PATCH: a lookback edit must never silently re-fetch, and this must
    never be mistaken for one. Reuses ``autocount.companies.manage``.
    """
    try:
        state = CompanyService(db).refetch_entity(
            current_user.tenant_id, company_id, entity_type
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return EntityConfigItem.model_validate(state)


def _mapping_response(view: MappingView) -> MappingViewResponse:
    return MappingViewResponse(
        entityType=view.entity_type,
        rows=[MappingRowOut.model_validate(row) for row in view.rows],
        sorentoFields=[SorentoFieldOut.model_validate(f) for f in view.sorento_fields],
        acFields=list(view.ac_fields),
    )


@router.get(
    "/{company_id}/entities/{entity_type}/mapping",
    response_model=MappingViewResponse,
)
def get_entity_mapping(
    company_id: str,
    entity_type: str,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> MappingViewResponse:
    """The entity's current field mappings projected AutoCount→Sorento, plus the
    source/target catalogs the editor's pickers need (AC-15-40).

    Reuses ``autocount.companies.manage`` - the same "configure the company"
    authority - so no new permission needs a grant sweep for existing tenants.
    """
    try:
        view = CompanyService(db).mapping_view(
            current_user.tenant_id, company_id, entity_type
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return _mapping_response(view)


@router.put(
    "/{company_id}/entities/{entity_type}/mapping",
    response_model=MappingViewResponse,
)
def replace_entity_mapping(
    company_id: str,
    entity_type: str,
    body: MappingUpdateRequest,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> MappingViewResponse:
    """Replace the entity's deliverable field mappings (AC-15-41/42/43).

    The server GUARDS every row: the Sorento target must be an accepted field
    (else 422 naming it - a target Sorento would reject can never be stored), the
    source path is non-blank and the transform is known. Provenance/watermark
    rows are preserved; the write is seed-if-absent-safe (``update_tenant`` never
    reverts an operator edit).
    """
    try:
        view = CompanyService(db).replace_mapping(
            current_user.tenant_id,
            company_id,
            entity_type,
            [
                MappingWriteRow(
                    source_path=row.sourcePath,
                    transform=row.transform,
                    sorento_field=row.sorentoField,
                    formula=row.formula,
                )
                for row in body.rows
            ],
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return _mapping_response(view)


@router.get(
    "/{company_id}/entities/{entity_type}/mapping/functions",
)
def get_formula_catalog(
    company_id: str,
    entity_type: str,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """The formula function/operator/preset/date-token catalog the builder needs
    (AC-16-13/15). Entity-agnostic; gated behind the company/entity guard so it
    shares the mapping editor's auth. Reuses ``autocount.companies.manage``.
    """
    try:
        catalog = CompanyService(db).function_catalog(
            current_user.tenant_id, company_id, entity_type
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return catalog


@router.post(
    "/{company_id}/entities/{entity_type}/mapping/test-formula",
    response_model=FormulaTestResponse,
)
def test_formula(
    company_id: str,
    entity_type: str,
    body: FormulaTestRequest,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> FormulaTestResponse:
    """Server-authoritative single-formula eval (AC-16-21) - the parity check for
    the builder's live client preview. Writes NOTHING. A bad formula/value comes
    back as ``{ok: false, error}``, never a 500. Reuses ``autocount.companies.manage``.
    """
    try:
        result = CompanyService(db).test_formula(
            current_user.tenant_id, company_id, entity_type, body.formula, body.value
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return FormulaTestResponse(**result)


@router.post(
    "/{company_id}/entities/{entity_type}/mapping/simulate",
    response_model=SimulateResponse,
)
def simulate_mapping(
    company_id: str,
    entity_type: str,
    body: SimulateRequest,
    current_user: User = Depends(require_permission("autocount.companies.manage")),
    db: Session = Depends(get_db),
) -> SimulateResponse:
    """Run the REAL MappingEngine over a MOCK AutoCount record → the projected
    Sorento record + per-field results (AC-16-30). Writes NOTHING - pure transform
    preview, distinct from the slice-14 Sorento dry-run. ``rows`` (optional) lets
    the operator simulate UNSAVED edits. Reuses ``autocount.companies.manage``.
    """
    try:
        draft = (
            [
                MappingWriteRow(
                    source_path=row.sourcePath,
                    transform=row.transform,
                    sorento_field=row.sorentoField,
                    formula=row.formula,
                )
                for row in body.rows
            ]
            if body.rows is not None
            else None
        )
        result = CompanyService(db).simulate_mapping(
            current_user.tenant_id, company_id, entity_type, body.record, draft
        )
    except AutocountServiceError as exc:
        _raise(exc)
    return SimulateResponse(**result)
