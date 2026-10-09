"""Connector admin API (session JWT, module-gated, perm-gated). HTTP only."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import GrantPage
from ..services.grant_admin_service import GrantAdminService

router = APIRouter()


@router.get("/grants", response_model=GrantPage, response_model_by_alias=True)
def list_grants(
    status: Optional[str] = None,
    product: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    page_size_camel: Optional[int] = Query(None, alias="pageSize", ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("connector.read")),
) -> GrantPage:
    return GrantAdminService(db, user.tenant_id).list(
        status=status, product=product, search=search, page=page,
        page_size=page_size_camel or page_size)
