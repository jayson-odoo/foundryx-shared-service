"""Company routes — thin: HTTP + Pydantic only.

No DB query and no raw SQL lives here (code-review hard-fail). Every handler
takes the tenant from the authenticated user — NEVER from client input — and
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
    EntityConfigItem,
)
from ..services import (
    AutocountServiceError,
    CompanyAlreadyExists,
    CompanyNotFound,
    CompanyService,
    ConnectionNotFound,
)

router = APIRouter()


def _raise(exc: AutocountServiceError) -> None:
    """ONE translator for every service error → HTTP. Messages are already
    operator-safe (no stack traces, no credentials)."""
    if isinstance(exc, (CompanyNotFound, ConnectionNotFound)):
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
        entities = service.entity_configs(current_user.tenant_id, company_id)
    except AutocountServiceError as exc:
        _raise(exc)
    return CompanyDetailResponse(
        company=CompanyItem.model_validate(company),
        entities=[EntityConfigItem.model_validate(row) for row in entities],
    )
