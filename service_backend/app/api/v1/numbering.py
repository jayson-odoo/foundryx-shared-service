"""Numbering routes (sprint-4/07, Cluster F). Thin: validate, delegate, shape HTTP.

- GET    /numbering              — numbering.read. Catalog (defaults ⊕ overrides
                                     ⊕ live next-val) — drives the settings page.
- PUT    /numbering/{docType}    — numbering.manage. Upsert format override.
- PUT    /numbering/{docType}/next-val — numbering.manage. Set next running value.
- DELETE /numbering/{docType}    — numbering.manage. Reset (delete override). 204.

No DB logic here (house rule); NumberingService owns it.
"""
from typing import List

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User
from app.schemas.numbering import (
    NumberCatalogItem,
    NumberFormatSetRequest,
    NumberNextValRequest,
)
from app.services.numbering_service import NumberingService

router = APIRouter()


@router.get("", response_model=List[NumberCatalogItem])
def get_catalog(
    current_user: User = Depends(require_permission("numbering.read")),
    db: Session = Depends(get_db),
):
    return NumberingService(db).catalog(current_user.tenant_id)


@router.put("/{doc_type}", status_code=status.HTTP_204_NO_CONTENT)
def set_format(
    doc_type: str,
    body: NumberFormatSetRequest,
    request_user_id: str = Depends(get_actor_user_id),
    current_user: User = Depends(require_permission("numbering.manage")),
    db: Session = Depends(get_db),
):
    NumberingService(db).set_format(
        current_user.tenant_id,
        doc_type,
        body.prefix,
        body.formatPattern,
        body.reset,
        request_user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{doc_type}/next-val", status_code=status.HTTP_204_NO_CONTENT)
def set_next_val(
    doc_type: str,
    body: NumberNextValRequest,
    current_user: User = Depends(require_permission("numbering.manage")),
    db: Session = Depends(get_db),
):
    NumberingService(db).set_next_val(current_user.tenant_id, doc_type, body.nextVal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{doc_type}", status_code=status.HTTP_204_NO_CONTENT)
def reset_format(
    doc_type: str,
    current_user: User = Depends(require_permission("numbering.manage")),
    db: Session = Depends(get_db),
):
    NumberingService(db).reset(current_user.tenant_id, doc_type)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
