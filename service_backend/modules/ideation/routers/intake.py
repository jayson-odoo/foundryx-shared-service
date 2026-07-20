"""Intake router (public, workspace-key authed) — the single home of intake logic
(D7): ``POST /ideation/intake/create-idea`` (§5.1, AC-A-17..25).

**Public** because it is authenticated by a workspace/integration key, not a user
session — there is no authenticated user to resolve a tenant from (AC-A-45); the
tenant is derived from the key via ``get_api_workspace`` (reuses the omnichannel
workspace-key mechanism until the respond.io binding lands — AC-A-27). Errors use
the uniform ``{error:{code,message}}`` envelope (``ApiError``). Called
server-to-server by the sorento brain per turn — NOT an MCP tool (§8-R3)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from modules.omnichannel.api_auth import ApiWorkspace, get_api_workspace

from ..schemas import CreateIdeaIn
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
        audio_attachment_ref=body.audio_attachment_ref,
        draft_id=body.draft_id,
        fields=body.fields,
        remove=body.remove,
        confirm=body.confirm,
    )
