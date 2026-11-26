"""Hub-facing read API ``/api/v1/hub-connector`` (a hub's own key).

``GET /products?customer=<code>&codes=&limit=&offset=`` returns exactly what
that customer may see: ``{code, name, brand_name, in_stock, incoming}`` (+
``list_price`` / ``currency`` only while the hub shows price). Errors use
core's ``{"error": {"code", "message"}}`` envelope. Contract of record:
``documentation/hub-connector/integration-guide.md``.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db

from .. import schemas
from ..gateway_auth import HubKey, get_hub_key
from ..services import hub_service
from ..services.hub_service import HubError

router = APIRouter()


@router.get("/products", response_model=schemas.HubProductPage)
def products(
    customer: str = Query(min_length=1, max_length=64),
    codes: Optional[str] = Query(default=None, max_length=20000),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    key: HubKey = Depends(get_hub_key),
    db: Session = Depends(get_db),
) -> schemas.HubProductPage:
    try:
        rows, total = hub_service.hub_api_rows(
            db, key.tenant_id, key.hub_id, customer, codes=codes, limit=limit, offset=offset
        )
    except HubError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message)
    return schemas.HubProductPage(data=rows, total=total, limit=limit, offset=offset)
