"""Terminology routes (sprint-3/08, F10). Thin: validate, delegate, shape HTTP.

- GET /terminology          — authenticated. Merged map (client-cache source).
- GET /terminology/catalog  — terminology.manage. TermDefs + current overrides.
- PUT /terminology/{key}    — terminology.manage. Upsert override (422 unknown).
- DELETE /terminology/{key} — terminology.manage. Reset (delete row). 204.

Read is authenticated-only like /auth/me — labels are not secret but are
tenant-scoped. No DB logic here (house rule); TerminologyService owns it.
"""
from typing import Dict, List

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, get_current_user, require_permission
from app.models.user import User
from app.schemas.terminology import TermCatalogItem, TermLabels, TermSetRequest
from app.services.terminology_service import TerminologyService

router = APIRouter()


@router.get("", response_model=Dict[str, TermLabels])
def get_terminology(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Merged map {key: {singular, plural}} for the caller's tenant."""
    return TerminologyService(db).merged_map(current_user.tenant_id)


@router.get("/catalog", response_model=List[TermCatalogItem])
def get_catalog(
    current_user: User = Depends(require_permission("terminology.manage")),
    db: Session = Depends(get_db),
):
    return TerminologyService(db).catalog(current_user.tenant_id)


@router.put("/{entity_key}", response_model=TermLabels)
def set_term(
    entity_key: str,
    body: TermSetRequest,
    request_user_id: str = Depends(get_actor_user_id),
    current_user: User = Depends(require_permission("terminology.manage")),
    db: Session = Depends(get_db),
):
    return TerminologyService(db).set_term(
        current_user.tenant_id,
        entity_key,
        body.singular,
        body.plural,
        request_user_id,
    )


@router.delete("/{entity_key}", status_code=status.HTTP_204_NO_CONTENT)
def reset_term(
    entity_key: str,
    current_user: User = Depends(require_permission("terminology.manage")),
    db: Session = Depends(get_db),
):
    TerminologyService(db).reset_term(current_user.tenant_id, entity_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
