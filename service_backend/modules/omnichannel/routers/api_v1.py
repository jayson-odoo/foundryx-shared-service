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
    PublicContactUpdateRequest,
    PublicSendRequest,
    PublicSendResponse,
    PublicTemplateListResponse,
    RioContactItem,
    RioContactListResponse,
    RioCursorPagination,
    RioMessageItem,
    RioMessageListResponse,
)
from ..services.media_pipeline import META_CEILINGS
from ..services.public_gateway_service import PublicGatewayService

router = APIRouter()

_MEDIA_HARD_CAP = max(META_CEILINGS.values()) + 1


def _page_url(request: Request, **params) -> str:
    """Absolute URL for this endpoint with its query params fully replaced by
    ``params`` (drops any None). Backs the respond.io ``{next, previous}`` cursors."""
    clean = {k: v for k, v in params.items() if v is not None}
    return str(request.url.replace_query_params(**clean))


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
    channel_id: Optional[str] = Query(default=None, alias="channelId"),
    search: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None, description="UTILITY|MARKETING|AUTHENTICATION"),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicTemplateListResponse:
    items = PublicGatewayService(db).list_templates(
        api_ws.tenant_id, api_ws.workspace_id,
        channel_id=channel_id, search=search, category=category,
    )
    return PublicTemplateListResponse(data=items)


# ── Contacts (respond.io-style: {identifier} = phone:+60… | id:<uuid> | <uuid>) ──
@router.get("/contacts", response_model=RioContactListResponse)
def list_contacts(
    request: Request,
    status: Optional[str] = Query(default=None, description="OPEN|SNOOZED|CLOSED"),
    assignee: str = Query(default="all", description="all|unassigned"),
    priority: Optional[str] = Query(default=None, description="LOW|MEDIUM|HIGH|URGENT"),
    search: Optional[str] = Query(default=None),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=200, alias="pageSize"),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> RioContactListResponse:
    """List contacts (threads) in the workspace, filterable. respond.io-shaped
    ``{items, pagination}`` with ``{next, previous}`` page-cursor URLs."""
    items, total = PublicGatewayService(db).list_contacts(
        api_ws.tenant_id, api_ws.workspace_id,
        status=status, assignee=assignee, priority=priority, search=search,
        page=page, page_size=page_size,
    )
    base = dict(status=status, assignee=assignee, priority=priority, search=search, pageSize=page_size)
    has_next = (page + 1) * page_size < total
    pagination = RioCursorPagination(
        next=_page_url(request, **base, page=page + 1) if has_next else None,
        previous=_page_url(request, **base, page=page - 1) if page > 0 else None,
    )
    return RioContactListResponse(items=items, pagination=pagination)


@router.get("/contacts/{identifier}", response_model=RioContactItem)
def get_contact(
    identifier: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> RioContactItem:
    """Get one contact by ``phone:+60…``, ``id:<uuid>`` or a bare id."""
    return PublicGatewayService(db).get_contact(api_ws.tenant_id, api_ws.workspace_id, identifier)


@router.patch("/contacts/{identifier}", response_model=RioContactItem)
def update_contact(
    identifier: str,
    payload: PublicContactUpdateRequest,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> RioContactItem:
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


@router.get("/contacts/{identifier}/messages", response_model=RioMessageListResponse)
def list_contact_messages(
    request: Request,
    identifier: str,
    limit: int = Query(50, ge=1, le=200),
    before: Optional[str] = Query(default=None, description="Message id — page into OLDER history"),
    after: Optional[str] = Query(default=None, description="Message id — page toward NEWER messages"),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> RioMessageListResponse:
    """A contact's message history — ALL types, respond.io-shaped, always
    oldest→newest. Two-way cursor: follow ``pagination.next`` for OLDER history,
    ``pagination.previous`` for NEWER messages. Workspace-scoped + read-only
    (never marks the thread read). Media URLs are absolute, signed and clickable."""
    _contact_id, items = PublicGatewayService(db).list_contact_messages(
        api_ws.tenant_id, api_ws.workspace_id, identifier,
        limit=limit, before_id=before, after_id=after,
    )
    oldest = items[0].messageId if items else None
    newest = items[-1].messageId if items else None
    # next = further into history (older); only when the page was full (more likely).
    next_url = _page_url(request, limit=limit, before=oldest) if len(items) == limit else None
    # previous = toward the present (newer); offered whenever we have an anchor.
    prev_url = _page_url(request, limit=limit, after=newest) if items else None
    return RioMessageListResponse(
        items=items, pagination=RioCursorPagination(next=next_url, previous=prev_url)
    )


@router.get("/contacts/{identifier}/messages/{message_id}", response_model=RioMessageItem)
def get_contact_message(
    identifier: str,
    message_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> RioMessageItem:
    """Get one message on a contact's thread (full fidelity, any type)."""
    return PublicGatewayService(db).get_contact_message(
        api_ws.tenant_id, api_ws.workspace_id, identifier, message_id
    )


# ── Conversation lifecycle ───────────────────────────────────────────────────
@router.post("/contacts/{identifier}/conversation/open", response_model=RioContactItem)
def open_conversation(
    identifier: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> RioContactItem:
    return PublicGatewayService(db).set_conversation_state(
        api_ws.tenant_id, api_ws.workspace_id, identifier, open_=True
    )


@router.post("/contacts/{identifier}/conversation/close", response_model=RioContactItem)
def close_conversation(
    identifier: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> RioContactItem:
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
