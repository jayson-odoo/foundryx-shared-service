"""Public gateway API (`/api/v1/omnichannel/*`, plan sprint-1/01 Slice 3).

Workspace-key-authenticated (NOT session/JWT): every route depends on
`get_api_workspace`, which derives (tenant, workspace) from the `fxw_live_…`
Bearer key. Errors use the structured `{error:{code,message}}` envelope
(`ApiError`). Marked `"public": true` in the manifest so the loader skips the
JWT `require_module` gate — service-active is re-checked inside the dependency.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db

from ..api_auth import ApiWorkspace, get_api_workspace
from ..schemas import (
    PublicSendRequest,
    PublicSendResponse,
    PublicTemplateListResponse,
)
from ..services.media_pipeline import META_CEILINGS
from ..services.public_gateway_service import PublicGatewayService

router = APIRouter()

_MEDIA_HARD_CAP = max(META_CEILINGS.values()) + 1


@router.post("/messages", response_model=PublicSendResponse, status_code=status.HTTP_202_ACCEPTED)
async def send_message(
    request: Request,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicSendResponse:
    """Send a message via the public gateway (plan 12 AC-12-10). Accepts EITHER
    JSON (text/template/media-by-url) OR multipart (``file`` part + a ``payload``
    JSON part carrying ``{to, type, media:{caption,filename}}``)."""
    svc = PublicGatewayService(db)
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("multipart/"):
        form = await request.form()
        upload = form.get("file")
        raw = form.get("payload")
        if upload is None or raw is None:
            raise ApiError(422, "invalid_request", "A file part and a payload part are required.")
        try:
            payload_obj = json.loads(raw)
        except (ValueError, TypeError):
            raise ApiError(422, "invalid_request", "payload must be valid JSON.")
        media = payload_obj.get("media") or {}
        content = await upload.read(_MEDIA_HARD_CAP)
        message_id, replay = svc.send_multipart(
            api_ws.tenant_id,
            api_ws.workspace_id,
            api_ws.key_id,
            kind=str(payload_obj.get("type") or ""),
            content=content,
            filename=media.get("filename") or getattr(upload, "filename", None),
            caption=media.get("caption"),
            to=str(payload_obj.get("to") or ""),
            idempotency_key=idempotency_key,
        )
    else:
        try:
            body = await request.json()
        except (ValueError, TypeError):
            raise ApiError(422, "invalid_request", "Request body must be valid JSON.")
        payload = PublicSendRequest(**body)
        message_id, replay = svc.send(
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
