"""Finance settlement routes (sprint-4/07 Cluster F slice 4) — agency give-back
settlements. Generate a PRIMARY from an AGENCY project's paid invoices, list,
get, and drive the Draft→Approved→Remitted lifecycle. Gated settlements.read /
settlements.manage; the loader wraps in require_module('finance'). Router =
HTTP/Pydantic only."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from modules.finance.schemas import (
    GenerateSettlementIn,
    SettlementListResponse,
    SettlementOut,
    SettlementTransitionIn,
)
from modules.finance.settlement_service import SettlementService

router = APIRouter()


@router.get("", response_model=SettlementListResponse)
def list_settlements(
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    project_id: Optional[str] = Query(None),
    current_user: User = Depends(require_permission("settlements.read")),
    db: Session = Depends(get_db),
):
    rows, total = SettlementService(db).list(
        current_user.tenant_id, page=page, page_size=page_size, project_id=project_id
    )
    return SettlementListResponse(
        items=[SettlementOut.model_validate(r) for r in rows], total=total, page=page, pageSize=page_size
    )


@router.post("", response_model=SettlementOut)
def generate_settlement(
    body: GenerateSettlementIn,
    current_user: User = Depends(require_permission("settlements.manage")),
    db: Session = Depends(get_db),
):
    res = SettlementService(db).generate(current_user.tenant_id, body.projectId, current_user)
    return SettlementOut.model_validate(res)


@router.get("/{settlement_id}", response_model=SettlementOut)
def get_settlement(
    settlement_id: str,
    current_user: User = Depends(require_permission("settlements.read")),
    db: Session = Depends(get_db),
):
    return SettlementOut.model_validate(
        SettlementService(db).get(current_user.tenant_id, settlement_id)
    )


@router.post("/{settlement_id}/transition", response_model=SettlementOut)
def transition_settlement(
    settlement_id: str,
    body: SettlementTransitionIn,
    current_user: User = Depends(require_permission("settlements.manage")),
    db: Session = Depends(get_db),
):
    res = SettlementService(db).transition(
        current_user.tenant_id, settlement_id, body.toStatusId,
        {"remittanceRef": body.remittanceRef}, current_user,
    )
    return SettlementOut.model_validate(res)
