"""Public gateway API (`/api/v1/omnichannel/*`, plan sprint-1/01 Slice 3).

Workspace-key-authenticated (NOT session/JWT): every route depends on
`get_api_workspace`, which derives (tenant, workspace) from the `fxw_live_…`
Bearer key. Errors use the structured `{error:{code,message}}` envelope
(`ApiError`). Marked `"public": true` in the manifest so the loader skips the
JWT `require_module` gate - service-active is re-checked inside the dependency.
"""
import json
from typing import Optional, Union

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db

from ..api_auth import ApiWorkspace, get_api_workspace
from ..schemas import (
    MessageItem,
    PublicContactListResponse,
    PublicMessageListResponse,
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
    ThreadItem,
    WebhookEndpointCreateRequest,
    WebhookEndpointItem,
    WebhookEndpointListResponse,
    WebhookEndpointMintResponse,
    WebhookEndpointUpdateRequest,
    WebhookSecretResponse,
)
from ..services.media_pipeline import META_CEILINGS
from ..services.public_gateway_service import (
    FORMAT_GUIDE,
    FORMAT_RIO,
    WIRE_FORMATS,
    PublicGatewayService,
)

router = APIRouter()

_MEDIA_HARD_CAP = max(META_CEILINGS.values()) + 1


def wire_format(
    format: str = Query(
        default=FORMAT_GUIDE,
        description=(
            "Response shape. `guide` (default) = the documented MessageItem/"
            "ThreadItem contract. `rio` = respond.io-parity shape, for consumers "
            "migrating from respond.io."
        ),
    ),
) -> str:
    """`?format=` switch for the read endpoints. Unknown value is a typed 422
    rather than a silent fallback - a consumer that typos the format must not
    quietly receive the other shape and mis-parse it."""
    fmt = (format or FORMAT_GUIDE).strip().lower()
    if fmt not in WIRE_FORMATS:
        raise ApiError(
            422, "invalid_request",
            f"Unknown format '{format}'. Use one of: {', '.join(WIRE_FORMATS)}.",
        )
    return fmt


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
@router.get(
    "/contacts",
    response_model=None,  # two shapes; documented via `responses` so OpenAPI keeps both
    responses={200: {"model": Union[PublicContactListResponse, RioContactListResponse]}},
)
def list_contacts(
    request: Request,
    status: Optional[str] = Query(default=None, description="OPEN|SNOOZED|CLOSED"),
    assignee: str = Query(default="all", description="all|unassigned"),
    priority: Optional[str] = Query(default=None, description="LOW|MEDIUM|HIGH|URGENT"),
    search: Optional[str] = Query(default=None),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=200, alias="pageSize"),
    fmt: str = Depends(wire_format),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
):
    """List contacts (threads) in the workspace, filterable.

    Default (`?format=guide`) → `{data: ThreadItem[], total, page, pageSize}`.
    `?format=rio` → respond.io `{items, pagination}` with cursor URLs."""
    items, total = PublicGatewayService(db).list_contacts(
        api_ws.tenant_id, api_ws.workspace_id,
        status=status, assignee=assignee, priority=priority, search=search,
        page=page, page_size=page_size, fmt=fmt,
    )
    if fmt != FORMAT_RIO:
        return PublicContactListResponse(
            data=items, total=total, page=page, pageSize=page_size
        )
    base = dict(status=status, assignee=assignee, priority=priority, search=search,
                pageSize=page_size, format=FORMAT_RIO)
    has_next = (page + 1) * page_size < total
    pagination = RioCursorPagination(
        next=_page_url(request, **base, page=page + 1) if has_next else None,
        previous=_page_url(request, **base, page=page - 1) if page > 0 else None,
    )
    return RioContactListResponse(items=items, pagination=pagination)


@router.get(
    "/contacts/{identifier}",
    response_model=None,
    responses={200: {"model": Union[ThreadItem, RioContactItem]}},
)
def get_contact(
    identifier: str,
    fmt: str = Depends(wire_format),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
):
    """Get one contact by ``phone:+60…``, ``id:<uuid>`` or a bare id.
    `ThreadItem` by default; `RioContactItem` with `?format=rio`."""
    return PublicGatewayService(db).get_contact(
        api_ws.tenant_id, api_ws.workspace_id, identifier, fmt=fmt
    )


@router.patch(
    "/contacts/{identifier}",
    response_model=None,
    responses={200: {"model": Union[ThreadItem, RioContactItem]}},
)
def update_contact(
    identifier: str,
    payload: PublicContactUpdateRequest,
    fmt: str = Depends(wire_format),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
):
    """Partial update - only sent fields change. Send ``assignedUserId``/
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
        fmt=fmt,
    )


@router.get(
    "/contacts/{identifier}/messages",
    response_model=None,
    responses={200: {"model": Union[PublicMessageListResponse, RioMessageListResponse]}},
)
def list_contact_messages(
    request: Request,
    identifier: str,
    limit: int = Query(50, ge=1, le=200),
    before: Optional[str] = Query(default=None, description="Message id - page into OLDER history"),
    after: Optional[str] = Query(default=None, description="Message id - page toward NEWER messages"),
    fmt: str = Depends(wire_format),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
):
    """A contact's message history - ALL types, always oldest→newest, read-only
    (never marks the thread read). Media: the default shape returns a RELATIVE,
    Bearer-authed `mediaUrl`; `?format=rio` returns an absolute pre-signed
    `message.url` that opens without a header (see §8).

    Default (`?format=guide`) → `{contactId, data: MessageItem[], nextBefore}`;
    page deeper by passing `nextBefore` back as `?before=`.
    `?format=rio` → respond.io `{items, pagination}` with a two-way cursor:
    `pagination.next` for OLDER history, `pagination.previous` for NEWER."""
    contact_id, items = PublicGatewayService(db).list_contact_messages(
        api_ws.tenant_id, api_ws.workspace_id, identifier,
        limit=limit, before_id=before, after_id=after, fmt=fmt,
    )
    if fmt != FORMAT_RIO:
        # A full page implies more history behind it; the oldest row is the
        # cursor. Short page = we reached the beginning, so null.
        #
        # `after=` pages FORWARD, so items[0] is the row just past the caller's
        # own anchor - emitting it as `nextBefore` would send them backwards
        # over ground they already have. The guide documents `before` only for
        # this shape, so the honest answer is "no older-direction cursor".
        next_before = (
            items[0].id if (after is None and len(items) == limit) else None
        )
        return PublicMessageListResponse(
            contactId=contact_id, data=items, nextBefore=next_before
        )
    oldest = items[0].messageId if items else None
    newest = items[-1].messageId if items else None
    next_url = _page_url(request, limit=limit, before=oldest, format=FORMAT_RIO) if len(items) == limit else None
    prev_url = _page_url(request, limit=limit, after=newest, format=FORMAT_RIO) if items else None
    return RioMessageListResponse(
        items=items, pagination=RioCursorPagination(next=next_url, previous=prev_url)
    )


@router.get(
    "/contacts/{identifier}/messages/{message_id}",
    response_model=None,
    responses={200: {"model": Union[MessageItem, RioMessageItem]}},
)
def get_contact_message(
    identifier: str,
    message_id: str,
    fmt: str = Depends(wire_format),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
):
    """Get one message on a contact's thread (full fidelity, any type).
    `MessageItem` by default; `RioMessageItem` with `?format=rio`."""
    return PublicGatewayService(db).get_contact_message(
        api_ws.tenant_id, api_ws.workspace_id, identifier, message_id, fmt=fmt
    )


# ── Conversation lifecycle ───────────────────────────────────────────────────
@router.post(
    "/contacts/{identifier}/conversation/open",
    response_model=None,
    responses={200: {"model": Union[ThreadItem, RioContactItem]}},
)
def open_conversation(
    identifier: str,
    fmt: str = Depends(wire_format),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
):
    """Reopen the conversation. Echoes the contact in the requested shape."""
    return PublicGatewayService(db).set_conversation_state(
        api_ws.tenant_id, api_ws.workspace_id, identifier, open_=True, fmt=fmt
    )


@router.post(
    "/contacts/{identifier}/conversation/close",
    response_model=None,
    responses={200: {"model": Union[ThreadItem, RioContactItem]}},
)
def close_conversation(
    identifier: str,
    fmt: str = Depends(wire_format),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
):
    """Close the conversation. Echoes the contact in the requested shape."""
    return PublicGatewayService(db).set_conversation_state(
        api_ws.tenant_id, api_ws.workspace_id, identifier, open_=False, fmt=fmt
    )


# ── Comments (internal notes - never sent to the customer) ────────────────────
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


# ── Webhook endpoints (self-serve; BL-SS-025) ────────────────────────────────
# A consumer holding only a workspace API key must be able to manage its OWN
# callbacks: webhooks are the intended inbound path, and until now registration
# was dashboard-only (session JWT + `webhooks.manage`), so a key-holder could
# neither create nor even LIST its endpoints. These mirror the operator routes
# but are scoped to the key's workspace and its active channel - a consumer can
# never see or touch another workspace's endpoints.
def _webhook_service(db: Session):
    from ..services.webhook_service import WebhookService

    return WebhookService(db)


def _wh_item(row) -> WebhookEndpointItem:
    from ..services.webhook_service import webhook_endpoint_item

    return webhook_endpoint_item(row)


def _wh_guard(exc: Exception):
    """WebhookError → typed 422 in the gateway's error envelope (the operator
    router raises a bare 400; `/api/v1/*` speaks {error:{code,message}})."""
    return ApiError(422, "invalid_request", str(exc))


@router.get("/webhooks", response_model=WebhookEndpointListResponse)
def list_webhooks(
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> WebhookEndpointListResponse:
    """Your workspace's registered callbacks (secrets are never echoed).

    Workspace-scoped, matching what the per-id routes can mutate - listing by
    active channel would hide an endpoint that `PATCH`/`DELETE` still reach."""
    rows = _webhook_service(db).list_for_workspace(api_ws.tenant_id, api_ws.workspace_id)
    return WebhookEndpointListResponse(data=[_wh_item(r) for r in rows])


@router.post("/webhooks", response_model=WebhookEndpointMintResponse, status_code=201)
def create_webhook(
    payload: WebhookEndpointCreateRequest,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> WebhookEndpointMintResponse:
    """Register a callback on your workspace's active channel. The signing
    secret is returned ONCE - store it; it is never shown again."""
    from ..services.webhook_service import WebhookError

    svc = PublicGatewayService(db)
    channel = svc._workspace_channel(api_ws.tenant_id, api_ws.workspace_id)
    try:
        row, secret = _webhook_service(db).create(
            api_ws.tenant_id, channel.id, payload.name, payload.url, payload.events,
            # No user behind an API key - record WHICH key, matching the
            # `apikey:<id>` actor convention used elsewhere in this service.
            # The activity log is pruned per tenant; this row is permanent.
            created_by=f"apikey:{api_ws.key_id}",
        )
    except WebhookError as exc:
        raise _wh_guard(exc) from exc
    return WebhookEndpointMintResponse(endpoint=_wh_item(row), signingSecret=secret)


def _own_endpoint(db: Session, api_ws: ApiWorkspace, endpoint_id: str):
    """Workspace-scoped fetch, translated to the gateway's 404 envelope. The
    scoping RULE lives in `WebhookService.get_for_workspace` so it travels with
    the data access; this only maps the exception."""
    from ..services.webhook_service import WebhookNotFound

    try:
        return _webhook_service(db).get_for_workspace(
            api_ws.tenant_id, api_ws.workspace_id, endpoint_id
        )
    except WebhookNotFound as exc:
        raise ApiError(404, "not_found", "Webhook endpoint not found.") from exc


@router.patch("/webhooks/{endpoint_id}", response_model=WebhookEndpointItem)
def update_webhook(
    endpoint_id: str,
    payload: WebhookEndpointUpdateRequest,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> WebhookEndpointItem:
    from ..services.webhook_service import WebhookError

    _own_endpoint(db, api_ws, endpoint_id)
    try:
        row = _webhook_service(db).update(
            api_ws.tenant_id, endpoint_id,
            name=payload.name, url=payload.url, events=payload.events,
        )
    except WebhookError as exc:
        raise _wh_guard(exc) from exc
    return _wh_item(row)


@router.post("/webhooks/{endpoint_id}/rotate", response_model=WebhookSecretResponse)
def rotate_webhook_secret(
    endpoint_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> WebhookSecretResponse:
    """New signing secret, returned ONCE. The old one stops verifying at once -
    deploy the new secret before rotating."""
    _own_endpoint(db, api_ws, endpoint_id)
    _row, secret = _webhook_service(db).rotate_secret(api_ws.tenant_id, endpoint_id)
    return WebhookSecretResponse(signingSecret=secret)


@router.post("/webhooks/{endpoint_id}/enable", response_model=WebhookEndpointItem)
def enable_webhook(
    endpoint_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> WebhookEndpointItem:
    """Re-enable a disabled endpoint (also clears an AUTO_DISABLED strike count)."""
    _own_endpoint(db, api_ws, endpoint_id)
    return _wh_item(_webhook_service(db).set_status(api_ws.tenant_id, endpoint_id, True))


@router.post("/webhooks/{endpoint_id}/disable", response_model=WebhookEndpointItem)
def disable_webhook(
    endpoint_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> WebhookEndpointItem:
    _own_endpoint(db, api_ws, endpoint_id)
    return _wh_item(_webhook_service(db).set_status(api_ws.tenant_id, endpoint_id, False))


@router.delete("/webhooks/{endpoint_id}", status_code=204)
def delete_webhook(
    endpoint_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> None:
    _own_endpoint(db, api_ws, endpoint_id)
    _webhook_service(db).delete(api_ws.tenant_id, endpoint_id)
