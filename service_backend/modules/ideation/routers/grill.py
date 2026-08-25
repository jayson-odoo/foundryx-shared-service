"""Grill router (Phase B-i slice 3, AC-BI-20..29) - the AI grill on the BR
detail's Grill tab. Mounted at ``/ideation/business-requirements`` alongside the
BR router; gated by ``require_module("ideation")`` + ``ideation.business_
requirements.manage`` (grilling + editing answers ride ``.manage``; ``.promote``
is the separate Gate-0 permission, not needed here).

HTTP-only (no DB/SQL - the hard-fail rule). Turns are SYNCHRONOUS (Bi-D10): a
chat turn is a request/response, never a ``background_jobs`` row.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import GrillGenerateOut, GrillStateOut, GrillTurnIn, GrillTurnOut
from ..services.grill import IdeationGrillService

router = APIRouter()

_MANAGE = "ideation.business_requirements.manage"


@router.get("/{br_id}/grill", response_model=GrillStateOut)
def get_grill_state(
    br_id: str,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> GrillStateOut:
    """The Grill tab snapshot: readiness + target fields + transcript + coverage."""
    return IdeationGrillService(db).state(current_user.tenant_id, br_id)


@router.post("/{br_id}/grill/open", response_model=GrillTurnOut)
def post_grill_open(
    br_id: str,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> GrillTurnOut:
    """Fire the opening grill turn on a fresh promoted BR (AC-BI-29b) - the agent
    greets + summarizes the absorbed idea(s) + asks its first question, with NO
    user message. Idempotent (a BR that already has messages returns its latest
    reply, no new LLM call)."""
    return IdeationGrillService(db).open_grill(
        current_user.tenant_id, br_id, actor=current_user
    )


@router.post("/{br_id}/grill/turn", response_model=GrillTurnOut)
def post_grill_turn(
    br_id: str,
    body: GrillTurnIn,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> GrillTurnOut:
    """One synchronous grill turn → ``{replyText, coveredFields}`` (AC-BI-24b)."""
    return IdeationGrillService(db).turn(
        current_user.tenant_id, br_id, body.message, actor=current_user
    )


@router.post("/{br_id}/grill/generate", response_model=GrillGenerateOut)
def post_grill_generate(
    br_id: str,
    current_user: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> GrillGenerateOut:
    """Extract answers from the whole transcript → validate → one retry → persist.
    The BR STAYS draft (AC-BI-27); the human promotes separately."""
    return IdeationGrillService(db).generate(current_user.tenant_id, br_id, actor=current_user)
