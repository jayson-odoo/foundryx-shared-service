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
    """Deterministic conversational-intake turn (§5.1, S1). Returns the full
    ten-key envelope - ``status, draft_id, reply_text, missing, next_field,
    title, captured, duplicate_candidate, idea_number, link`` (no LLM).
    ``product_id`` is validated for the key's tenant; ``confirm`` is the only
    path to ``complete`` (D-CONFIRM)."""
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
        is_test=body.is_test,
        title=body.title,
        skip=body.skip,
        cancel=body.cancel,
        duplicate_choice=body.duplicate_choice,
        submitter_tier=body.submitter_tier,
    )


@router.post("/ideas", status_code=status.HTTP_201_CREATED)
def create_idea_one_shot(
    body: OneShotIdeaIn,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> dict:
    """One-shot chatbot create (SS-IDEATION-OWN). The host has already collected
    and confirmed the idea - this creates it straight into ``captured`` and
    returns ``{idea_id, idea_number, status, title, link}``. Errors (uniform
    envelope): 422 ``submitter_required`` (no ``submitter_crm_user_id``), 422
    ``problem_required``, 422 ``title_too_long``, 422 ``invalid_phone``, 404
    ``unknown_product``, 422 ``no_workspace``, 409 ``intake_ref_conflict``.
    A retry with the same ``intake_ref`` returns the same idea (idempotent).
    ``/create-idea`` (the turn flow) is unchanged."""
    return IntakeService(db).create_one_shot(
        api_ws.tenant_id,
        product_id=body.product_id,
        problem=body.problem,
        title=body.title,
        proposed_solution=body.proposed_solution,
        impact=body.impact,
        department=body.department,
        submitter_crm_user_id=body.submitter_crm_user_id,
        submitter_phone=body.submitter_phone,
        submitter_name=body.submitter_name,
        submitter_tier=body.submitter_tier,
        raw_transcript=body.raw_transcript,
        attachments=[a.model_dump() for a in body.attachments] if body.attachments else None,
        is_test=body.is_test,
        intake_ref=body.intake_ref,
    )


@router.post("/ideas/similar-own")
def similar_own_ideas(
    body: SimilarOwnIn,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> dict:
    """The sender's OWN live ideas similar to ``text`` (SS-IDEATION-OWN): same
    submitter only (CRM user id or phone - never name), live only (no draft /
    rejected / duplicate / archived / merged-away), same product + test lane,
    top 3, the existing pg_trgm threshold. Returns ``{matches:[{idea_id,
    idea_number, title, problem, status, status_label, similarity, created_at,
    link}]}``. 422 ``submitter_required`` when no usable identity is given."""
    return IntakeService(db).similar_own(
        api_ws.tenant_id,
        product_id=body.product_id,
        text_=body.text,
        submitter_crm_user_id=body.submitter_crm_user_id,
        submitter_phone=body.submitter_phone,
        is_test=body.is_test,
    )
