"""Intake router (public, workspace-key authed) - the single home of intake logic
(D7): ``POST /ideation/intake/create-idea`` (§5.1, AC-A-17..25).

**Public** because it is authenticated by a workspace/integration key, not a user
session - there is no authenticated user to resolve a tenant from (AC-A-45); the
tenant is derived from the key via ``get_api_workspace`` (reuses the omnichannel
workspace-key mechanism until the respond.io binding lands - AC-A-27). Errors use
the uniform ``{error:{code,message}}`` envelope (``ApiError``). Called
server-to-server by the sorento brain per turn - NOT an MCP tool (§8-R3)."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from modules.omnichannel.api_auth import ApiWorkspace, get_api_workspace

from ..schemas import CreateIdeaIn, OneShotIdeaIn, SimilarOwnIn
from ..services.intake import IntakeService

router = APIRouter()


@router.post("/create-idea")
def create_idea(
    body: CreateIdeaIn,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> dict:
    """Deterministic conversational-intake turn (§5.1). Returns exactly
    ``{draft_id, status, captured, missing, reply_text, link?, duplicate_of?}``
    (no LLM). ``product_id`` is validated for the key's tenant; ``confirm`` is the
    only path to ``complete`` (D-CONFIRM)."""
    return IntakeService(db).create_idea(
        api_ws.tenant_id,
        product_id=body.product_id,
        submitter_contact_id=body.submitter_contact_id,
        submitter_name=body.submitter_name,
        message_text=body.message_text,
        raw_transcript=body.raw_transcript,
        attachments=[a.model_dump() for a in body.attachments] if body.attachments else None,
        draft_id=body.draft_id,
        discard_draft_id=body.discard_draft_id,
        fields=body.fields,
        remove=body.remove,
        confirm=body.confirm,
    )


@router.post("/ideas", status_code=status.HTTP_201_CREATED)
def create_idea_one_shot(
    body: OneShotIdeaIn,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> dict:
    """One-shot chatbot create (SS-IDEATION-OWN). The host has already collected
    and confirmed the idea - this creates it straight into ``captured`` and
    returns ``{idea_id, number, status, link}``. ``submitter_crm_user_id`` is
    required (422 ``submitter_required``); blank ``problem`` = 422
    ``problem_required``; unknown product = 404 ``unknown_product``. The
    draft/collect/confirm flow (``/create-idea``) is unchanged."""
    return IntakeService(db).create_one_shot(
        api_ws.tenant_id,
        product_id=body.product_id,
        problem=body.problem,
        proposed_solution=body.proposed_solution,
        impact=body.impact,
        department=body.department,
        submitter_crm_user_id=body.submitter_crm_user_id,
        submitter_phone=body.submitter_phone,
        submitter_name=body.submitter_name,
        raw_transcript=body.raw_transcript,
        attachments=[a.model_dump() for a in body.attachments] if body.attachments else None,
        source=body.source,
    )


@router.post("/ideas/similar-own")
def similar_own_ideas(
    body: SimilarOwnIn,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> dict:
    """The sender's OWN live ideas similar to ``text`` (SS-IDEATION-OWN): same
    submitter only (CRM user id or phone - never name), live only (no drafts, no
    archived/terminal), same product, top 3, existing pg_trgm threshold. Returns
    ``{matches:[{idea_id, number, problem, status, similarity, created_at, link}]}``."""
    return IntakeService(db).similar_own(
        api_ws.tenant_id,
        product_id=body.product_id,
        text_=body.text,
        submitter_crm_user_id=body.submitter_crm_user_id,
        submitter_phone=body.submitter_phone,
    )
