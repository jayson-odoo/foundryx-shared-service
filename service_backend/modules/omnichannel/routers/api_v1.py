"""Public gateway API (`/api/v1/omnichannel/*`, plan sprint-1/01 Slice 3).

Workspace-key-authenticated (NOT session/JWT): every route depends on
`get_api_workspace`, which derives (tenant, workspace) from the `fxw_live_…`
Bearer key. Errors use the structured `{error:{code,message}}` envelope
(`ApiError`). Marked `"public": true` in the manifest so the loader skips the
JWT `require_module` gate — service-active is re-checked inside the dependency.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db

from ..api_auth import ApiWorkspace, get_api_workspace
from ..schemas import (
    MessageItem,
    PublicCommentRequest,
    PublicContactListResponse,
    PublicContactUpdateRequest,
    PublicMessageListResponse,
    PublicSendRequest,
    PublicSendResponse,
    PublicTemplateListResponse,
    ThreadItem,
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
        # Cap the buffered read at this kind's Meta ceiling (memory safety).
        hard_cap = META_CEILINGS.get(str(payload_obj.get("type") or "").upper(), _MEDIA_HARD_CAP) + 1
        content = await upload.read(hard_cap)
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


# ── Contacts (respond.io-style: {identifier} = phone:+60… | id:<uuid> | <uuid>) ──
@router.get("/contacts", response_model=PublicContactListResponse)
def list_contacts(
    status: Optional[str] = Query(default=None, description="OPEN|SNOOZED|CLOSED"),
    assignee: str = Query(default="all", description="all|unassigned"),
    priority: Optional[str] = Query(default=None, description="LOW|MEDIUM|HIGH|URGENT"),
    search: Optional[str] = Query(default=None),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=200, alias="pageSize"),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicContactListResponse:
    """List contacts (threads) in the workspace, filterable + paginated."""
    items, total = PublicGatewayService(db).list_contacts(
        api_ws.tenant_id, api_ws.workspace_id,
        status=status, assignee=assignee, priority=priority, search=search,
        page=page, page_size=page_size,
    )
    return PublicContactListResponse(data=items, total=total, page=page, pageSize=page_size)


@router.get("/contacts/{identifier}", response_model=ThreadItem)
def get_contact(
    identifier: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> ThreadItem:
    """Get one contact by ``phone:+60…``, ``id:<uuid>`` or a bare id."""
    return PublicGatewayService(db).get_contact(api_ws.tenant_id, api_ws.workspace_id, identifier)


@router.patch("/contacts/{identifier}", response_model=ThreadItem)
def update_contact(
    identifier: str,
    payload: PublicContactUpdateRequest,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> ThreadItem:
    """Partial update — only sent fields change. Send ``assignedUserId``/
    ``customFields`` as null to clear; omit to leave unchanged."""
    sent = payload.model_fields_set
    _S = ...  # sentinel = "not provided"
    return PublicGatewayService(db).update_contact(
        api_ws.tenant_id, api_ws.workspace_id, identifier,
        first_name=payload.firstName if "firstName" in sent else _S,
        last_name=payload.lastName if "lastName" in sent else _S,
        priority=payload.priority if "priority" in sent else None,
        assigned_user_id=payload.assignedUserId if "assignedUserId" in sent else _S,
        custom_fields=payload.customFields if "customFields" in sent else _S,
    )


@router.get("/contacts/{identifier}/messages", response_model=PublicMessageListResponse)
def list_contact_messages(
    identifier: str,
    limit: int = Query(50, ge=1, le=200),
    before: Optional[str] = Query(default=None),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicMessageListResponse:
    """A contact's message history — ALL message types, workspace-scoped, read-
    only (never marks the thread read). Newest ``limit`` oldest→newest; pass the
    returned ``nextBefore`` back as ``before`` to page further into history.
    Media rides the same authed ``/omnichannel/media/{id}`` route (the API key
    is accepted there too)."""
    svc = PublicGatewayService(db)
    contact = svc._resolve_contact(api_ws.tenant_id, api_ws.workspace_id, identifier)
    items = svc.list_contact_messages(
        api_ws.tenant_id, api_ws.workspace_id, identifier, limit=limit, before_id=before
    )
    next_before = items[0].id if len(items) == limit else None
    return PublicMessageListResponse(contactId=contact.id, data=items, nextBefore=next_before)


@router.get("/contacts/{identifier}/messages/{message_id}", response_model=MessageItem)
def get_contact_message(
    identifier: str,
    message_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> MessageItem:
    """Get one message on a contact's thread (full fidelity, any type)."""
    return PublicGatewayService(db).get_contact_message(
        api_ws.tenant_id, api_ws.workspace_id, identifier, message_id
    )


# ── Conversation lifecycle ───────────────────────────────────────────────────
@router.post("/contacts/{identifier}/conversation/open", response_model=ThreadItem)
def open_conversation(
    identifier: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> ThreadItem:
    return PublicGatewayService(db).set_conversation_state(
        api_ws.tenant_id, api_ws.workspace_id, identifier, open_=True
    )


@router.post("/contacts/{identifier}/conversation/close", response_model=ThreadItem)
def close_conversation(
    identifier: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> ThreadItem:
    return PublicGatewayService(db).set_conversation_state(
        api_ws.tenant_id, api_ws.workspace_id, identifier, open_=False
    )


# ── Comments (internal notes — never sent to the customer) ────────────────────
@router.post("/contacts/{identifier}/comments", response_model=MessageItem, status_code=201)
def add_comment(
    identifier: str,
    payload: PublicCommentRequest,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> MessageItem:
    return PublicGatewayService(db).add_comment(
        api_ws.tenant_id, api_ws.workspace_id, identifier, payload.body
    )
