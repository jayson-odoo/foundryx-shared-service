"""Public gateway API (`/api/v1/omnichannel/*`, plan sprint-1/01 Slice 3).

Workspace-key-authenticated (NOT session/JWT): every route depends on
`get_api_workspace`, which derives (tenant, workspace) from the `fxw_live_…`
Bearer key. Errors use the structured `{error:{code,message}}` envelope
(`ApiError`). Marked `"public": true` in the manifest so the loader skips the
JWT `require_module` gate — service-active is re-checked inside the dependency.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.orm import Session

from app.database import get_db

from ..api_auth import ApiWorkspace, get_api_workspace
from ..schemas import (
    PublicSendRequest,
    PublicSendResponse,
    PublicTemplateListResponse,
)
from ..services.public_gateway_service import PublicGatewayService

router = APIRouter()


@router.post("/messages", response_model=PublicSendResponse, status_code=status.HTTP_202_ACCEPTED)
def send_message(
    payload: PublicSendRequest,
    response: Response,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicSendResponse:
    message_id, replay = PublicGatewayService(db).send(
        api_ws.tenant_id, api_ws.workspace_id, api_ws.key_id, payload, idempotency_key
    )
    # A replay is still 202 with the ORIGINAL message id (idempotent).
    return PublicSendResponse(id=message_id, status="queued", idempotencyReplay=replay)


@router.get("/templates", response_model=PublicTemplateListResponse)
def list_templates(
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicTemplateListResponse:
    items = PublicGatewayService(db).list_templates(api_ws.tenant_id, api_ws.workspace_id)
    return PublicTemplateListResponse(data=items)
