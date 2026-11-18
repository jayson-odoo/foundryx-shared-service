"""Public gateway API (`/api/v1/omnichannel/*`, plan sprint-1/01 Slice 3).

Workspace-key-authenticated (NOT session/JWT): every route depends on
`get_api_workspace`, which derives (tenant, workspace) from the `fxw_live_…`
Bearer key. Errors use the structured `{error:{code,message}}` envelope
(`ApiError`). Marked `"public": true` in the manifest so the loader skips the
JWT `require_module` gate - service-active is re-checked inside the dependency.
"""
import json
import re
from datetime import datetime
from typing import Optional, Union

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.gateway_body_cap import is_multipart
from app.database import get_db

from ..api_auth import ApiWorkspace, get_api_workspace
from ..schemas import (
    MessageItem,
    PublicContactListResponse,
    PublicMessageListResponse,
    ContactEraseResponse,
    ContactReadResponse,
    PublicCommentRequest,
    PublicContactUpdateRequest,
    PublicSendRequest,
    PublicSenderAttribution,
    PublicSendResponse,
    BusinessHoursUpdate,
    PublicBusinessHoursResponse,
    PublicCatalogResponse,
    PublicValidateRequest,
    PublicWorkflowActiveRequest,
    PublicWorkflowRunDetail,
    PublicWorkflowRunListResponse,
    PublicWorkflowRunRequest,
    PublicWorkflowVersionListResponse,
    PublicWorkflowRunItem,
    PublicValidateResponse,
    PublicWorkflowCreateRequest,
    PublicWorkflowItem,
    PublicWorkflowListResponse,
    PublicWorkflowUpdateRequest,
    PublicChannelListResponse,
    PublicTemplateListResponse,
    PublicWebhookDeliveryListResponse,
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
from ..services import payload_version
from ..services.business_hours import BusinessHoursService
from ..services.key_workflows import KeyWorkflowService, put_business_hours
from ..services.media_pipeline import META_CEILINGS
from ..services.public_gateway_service import (
    FORMAT_GUIDE,
    FORMAT_RIO,
    WIRE_FORMATS,
    PublicGatewayService,
)
from ..services.webchat_visitor_service import WebchatInvalidRequest, read_capped_json

API_VERSION_HEADER = "X-Fx-Api-Version"


def api_version(
    value: Optional[str] = Header(
        default=None,
        alias=API_VERSION_HEADER,
        description=(
            "Response payload version. Absent or `1` = the documented shapes as "
            "they are today. A higher version adds the keys introduced in it."
        ),
    ),
) -> int:
    """`X-Fx-Api-Version` request header -> the response payload version. Absent
    is version 1. An unknown value is a typed 422, never a silent fallback (same
    rule as `?format=`). Runs on every route of this router, so a bad value is
    refused everywhere; a route whose shapes have versioned keys also takes it
    as a parameter and answers with `versioned`."""
    if value is None:
        return payload_version.V1
    raw = value.strip()
    if re.fullmatch(r"[1-9][0-9]{0,2}", raw) and int(raw) in payload_version.VERSIONS:
        return int(raw)
    known = ", ".join(str(v) for v in payload_version.VERSIONS)
    raise ApiError(
        422, "invalid_request",
        f"Unknown {API_VERSION_HEADER} '{value}'. Use one of: {known}.",
    )


def versioned(item, version: int, status_code: int = status.HTTP_200_OK):
    """Version 1 returns the model untouched, so FastAPI serializes it exactly as
    before. A higher version answers the JSON dumped at that version."""
    if version == payload_version.V1:
        return item
    with payload_version.serializing(version):
        content = jsonable_encoder(item)
    return JSONResponse(content, status_code=status_code)


def versioned_shape(item, fmt: str, version: int, status_code: int = status.HTTP_200_OK):
    """`versioned` for a route with two shapes: `?format=rio` is a respond.io
    mirror and is never versioned."""
    if fmt == FORMAT_RIO:
        return item
    return versioned(item, version, status_code=status_code)


router = APIRouter(dependencies=[Depends(api_version)])

# Cap on a JSON body the gateway reads itself (the send route and the workflow routes).
_JSON_BODY_CAP = 256 * 1024


_MEDIA_HARD_CAP = max(META_CEILINGS.values()) + 1
_MULTIPART_MAX_FIELDS = 5  # `payload` + a little slack


async def _read_capped_body(request: Request) -> bytes:
    """Bytes of the request body, refused once over the cap (counted as read, so a
    chunked body with no Content-Length is capped too). No content-type rule."""
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > _JSON_BODY_CAP:
            raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_request", "Request body is too large.")
    return bytes(body)


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
    version: int = Depends(api_version),
) -> PublicSendResponse:
    """Send a message via the public gateway (plan 12 AC-12-10). Accepts EITHER
    JSON (text/template/media-by-url) OR multipart (``file`` part + a ``payload``
    JSON part carrying ``{to, type, media:{caption,filename}}``)."""
    svc = PublicGatewayService(db)
    content_type = request.headers.get("content-type", "")

    if is_multipart(content_type):
        try:
            # The send reads one file part and the `payload` part; the cap leaves slack.
            form = await request.form(max_files=1, max_fields=_MULTIPART_MAX_FIELDS)
        except StarletteHTTPException as exc:
            # Starlette words its part and field limits "Too many files/fields ..."
            too_many = str(exc.detail).startswith("Too many")
            raise ApiError(
                422,
                "invalid_request",
                "The multipart body has too many parts." if too_many else "The multipart body could not be read.",
            ) from None
        upload = form.get("file")
        raw = form.get("payload")
        if upload is None or raw is None:
            raise ApiError(422, "invalid_request", "A file part and a payload part are required.")
        try:
            payload_obj = json.loads(raw)
        except (ValueError, TypeError):
            raise ApiError(422, "invalid_request", "payload must be valid JSON.")
        if not isinstance(payload_obj, dict) or not isinstance(payload_obj.get("media") or {}, dict):
            raise ApiError(422, "invalid_request", "payload must be a JSON object.")
        media = payload_obj.get("media") or {}
        channel_id = payload_obj.get("channelId")
        if channel_id is not None and not isinstance(channel_id, str):
            raise ApiError(422, "invalid_channel", "channelId must be a string.")
        reply_to = payload_obj.get("replyToMessageId")
        if reply_to is not None and not isinstance(reply_to, str):
            raise ApiError(422, "invalid_request", "replyToMessageId must be a string.")
        sender = None
        if payload_obj.get("sender") is not None:
            try:
                sender = PublicSenderAttribution.model_validate(payload_obj["sender"])
            except ValidationError as exc:
                if version != payload_version.V1:
                    errors = exc.errors(include_url=False, include_context=False)
                    for e in errors:
                        e["loc"] = ("payload", "sender", *e.get("loc", ()))
                    raise RequestValidationError(errors) from None
                # Version 1: a malformed `sender` is ignored, as before it existed.
        # Cap the buffered read at this kind's Meta ceiling (memory safety).
        hard_cap = META_CEILINGS.get(str(payload_obj.get("type") or "").upper(), _MEDIA_HARD_CAP) + 1
        content = await upload.read(hard_cap)
        # The blocking work (database, media fetch, provider call) runs on a worker
        # thread; the body reads above stay on the loop, and nothing on the loop
        # touches `svc` or `db` while the thread holds them.
        message_id, replay = await run_in_threadpool(
            svc.send_multipart,
            api_ws.tenant_id,
            api_ws.workspace_id,
            api_ws.key_id,
            kind=str(payload_obj.get("type") or ""),
            content=content,
            filename=media.get("filename") or getattr(upload, "filename", None),
            caption=media.get("caption"),
            to=str(payload_obj.get("to") or ""),
            idempotency_key=idempotency_key,
            channel_id=channel_id,
            reply_to_message_id=reply_to,
            version=version,
            sender=sender,
        )
    else:
        try:
            body = json.loads(await _read_capped_body(request))
        except (ValueError, TypeError, RecursionError):  # nesting too deep to parse is not JSON we accept
            raise ApiError(422, "invalid_request", "Request body must be valid JSON.")
        if not isinstance(body, dict):
            raise RequestValidationError(
                [{"type": "dict_type", "loc": ("body",), "msg": "Input should be an object", "input": None}]
            )
        v1_sender = None
        if version == payload_version.V1 and "sender" in body:
            # Version 1 callers never get a new 422 from `sender`: a malformed
            # one is dropped (the send goes through as it did before the key
            # existed); a well-formed one is kept as attribution.
            try:
                v1_sender = PublicSenderAttribution.model_validate(body["sender"])
            except ValidationError:
                v1_sender = None
            body = {k: v for k, v in body.items() if k != "sender"}
        try:
            payload = PublicSendRequest(**body)
            if v1_sender is not None:
                payload.sender = v1_sender
        except ValidationError as exc:
            errors = exc.errors(include_url=False, include_context=False)
            if any(tuple(e.get("loc", ())[:2]) == ("media", "url") for e in errors):
                raise ApiError(422, "invalid_media_url", "The media url must be text.") from None
            # Same answer the route's own validation handler gives.
            raise RequestValidationError(errors) from None
        message_id, replay = await run_in_threadpool(
            svc.send,
            api_ws.tenant_id,
            api_ws.workspace_id,
            api_ws.key_id,
            payload,
            idempotency_key,
            version,
        )
    # A replay is still 202 with the ORIGINAL message id (idempotent).
    return PublicSendResponse(id=message_id, status="queued", idempotencyReplay=replay)


@router.get("/channels", response_model=PublicChannelListResponse)
def list_channels(
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
    version: int = Depends(api_version),
) -> PublicChannelListResponse:
    items = PublicGatewayService(db).list_channels(api_ws.tenant_id, api_ws.workspace_id)
    return versioned(PublicChannelListResponse(data=items), version)


@router.get("/templates", response_model=PublicTemplateListResponse)
def list_templates(
    channel_id: Optional[str] = Query(default=None, alias="channelId"),
    search: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None, description="UTILITY|MARKETING|AUTHENTICATION"),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
    version: int = Depends(api_version),
) -> PublicTemplateListResponse:
    items = PublicGatewayService(db).list_templates(
        api_ws.tenant_id, api_ws.workspace_id,
        channel_id=channel_id, search=search, category=category,
    )
    return versioned(PublicTemplateListResponse(data=items), version)


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
    updated_since: Optional[datetime] = Query(
        default=None, alias="updatedSince",
        description="ISO 8601 instant; only contacts changed or messaged after it (no offset = UTC).",
    ),
    channel_id: Optional[str] = Query(
        default=None, alias="channelId",
        description="Only contacts with an identity on this channel of your workspace.",
    ),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=200, alias="pageSize"),
    fmt: str = Depends(wire_format),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
    version: int = Depends(api_version),
):
    """List contacts (threads) in the workspace, filterable.

    Default (`?format=guide`) → `{data: ThreadItem[], total, page, pageSize}`.
    `?format=rio` → respond.io `{items, pagination}` with cursor URLs.
    `updatedSince` / `channelId` (2026-11-18) are optional; absent = no filter."""
    items, total = PublicGatewayService(db).list_contacts(
        api_ws.tenant_id, api_ws.workspace_id,
        status=status, assignee=assignee, priority=priority, search=search,
        updated_since=updated_since, channel_id=channel_id,
        page=page, page_size=page_size, fmt=fmt,
    )
    if fmt != FORMAT_RIO:
        return versioned(
            PublicContactListResponse(data=items, total=total, page=page, pageSize=page_size),
            version,
        )
    base = dict(status=status, assignee=assignee, priority=priority, search=search,
                updatedSince=request.query_params.get("updatedSince") if updated_since else None,
                channelId=channel_id, pageSize=page_size, format=FORMAT_RIO)
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
    version: int = Depends(api_version),
):
    """Get one contact by ``phone:+60…``, ``id:<uuid>`` or a bare id.
    `ThreadItem` by default; `RioContactItem` with `?format=rio`."""
    item = PublicGatewayService(db).get_contact(
        api_ws.tenant_id, api_ws.workspace_id, identifier, fmt=fmt
    )
    return versioned_shape(item, fmt, version)


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
    version: int = Depends(api_version),
):
    """Partial update - only sent fields change. Send ``assignedUserId`` as
    null to unassign. Send ``customFields`` as null (the whole value, not an
    object) to clear EVERY registered field's value at once; send an object
    with a key set to null to clear just that one key (partial merge, other
    keys untouched); omit ``customFields`` entirely to leave it unchanged.
    ``tags`` (names, auto-created if unknown) REPLACES the set; ``lifecycle``
    (a stage key or label) moves the contact along the workspace's lifecycle
    graph. ``assignedTeamId`` is a CORE team id, BY ID ONLY (never by name);
    an unknown/foreign/inactive id is a `422 invalid_request`."""
    sent = payload.model_fields_set
    _S = ...  # sentinel = "not provided"
    item = PublicGatewayService(db).update_contact(
        api_ws.tenant_id, api_ws.workspace_id, identifier,
        first_name=payload.firstName if "firstName" in sent else _S,
        last_name=payload.lastName if "lastName" in sent else _S,
        priority=payload.priority if "priority" in sent else None,
        assigned_user_id=payload.assignedUserId if "assignedUserId" in sent else _S,
        assigned_team_id=payload.assignedTeamId if "assignedTeamId" in sent else _S,
        custom_fields=payload.customFields if "customFields" in sent else _S,
        language=payload.language if "language" in sent else _S,
        country_code=payload.countryCode if "countryCode" in sent else _S,
        tags=payload.tags if "tags" in sent else _S,
        lifecycle=payload.lifecycle if "lifecycle" in sent else _S,
        fmt=fmt,
    )
    return versioned_shape(item, fmt, version)


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
    version: int = Depends(api_version),
):
    """A contact's message history - ALL types, always oldest→newest, read-only
    (never marks the thread read). Media: the default shape returns a RELATIVE,
    Bearer-authed `mediaUrl`; `?format=rio` returns an absolute pre-signed
    `message.url` that opens without a header (see §8).

    Default (`?format=guide`) → `{contactId, data: MessageItem[], nextBefore}`;
    page deeper by passing `nextBefore` back as `?before=`.
    `?format=rio` → respond.io `{items, pagination}` with a two-way cursor:
    `pagination.next` for OLDER history, `pagination.previous` for NEWER."""
    svc = PublicGatewayService(db)
    contact_id, items = svc.list_contact_messages(
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
        response = PublicMessageListResponse(
            contactId=contact_id, data=items, nextBefore=next_before
        )
        if payload_version.visible("PublicMessageListResponse", "window", version):
            response.window = svc.contact_window(api_ws.tenant_id, contact_id)
        return versioned(response, version)
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
    version: int = Depends(api_version),
):
    """Get one message on a contact's thread (full fidelity, any type).
    `MessageItem` by default; `RioMessageItem` with `?format=rio`."""
    item = PublicGatewayService(db).get_contact_message(
        api_ws.tenant_id, api_ws.workspace_id, identifier, message_id, fmt=fmt
    )
    return versioned_shape(item, fmt, version)


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
    version: int = Depends(api_version),
):
    """Reopen the conversation. Echoes the contact in the requested shape."""
    item = PublicGatewayService(db).set_conversation_state(
        api_ws.tenant_id, api_ws.workspace_id, identifier, open_=True, fmt=fmt
    )
    return versioned_shape(item, fmt, version)


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
    version: int = Depends(api_version),
):
    """Close the conversation. Echoes the contact in the requested shape."""
    item = PublicGatewayService(db).set_conversation_state(
        api_ws.tenant_id, api_ws.workspace_id, identifier, open_=False, fmt=fmt
    )
    return versioned_shape(item, fmt, version)


# ── Comments (internal notes - never sent to the customer) ────────────────────
@router.post("/contacts/{identifier}/comments", response_model=MessageItem, status_code=201)
def add_comment(
    identifier: str,
    payload: PublicCommentRequest,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
    version: int = Depends(api_version),
) -> MessageItem:
    item = PublicGatewayService(db).add_comment(
        api_ws.tenant_id, api_ws.workspace_id, identifier, payload.body
    )
    return versioned(item, version, status_code=status.HTTP_201_CREATED)


# ── Mark a contact read (resets unread; WhatsApp read receipts) ──────────────
@router.post("/contacts/{identifier}/read", response_model=ContactReadResponse)
def mark_contact_read(
    identifier: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> ContactReadResponse:
    return PublicGatewayService(db).mark_contact_read(
        api_ws.tenant_id, api_ws.workspace_id, identifier
    )


# ── Erase a contact (PDPA; every key has full power in its own workspace) ────
@router.delete("/contacts/{identifier}", response_model=ContactEraseResponse)
def erase_contact(
    identifier: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> ContactEraseResponse:
    return PublicGatewayService(db).erase_contact(
        api_ws.tenant_id, api_ws.workspace_id, identifier, api_key_id=api_ws.key_id
    )


# ── Webhook endpoints (self-serve; BL-SS-025) ────────────────────────────────
# A consumer holding only a workspace API key must be able to manage its OWN
# callbacks: webhooks are the intended inbound path, and until now registration
# was dashboard-only (session JWT + `webhooks.manage`), so a key-holder could
# neither create nor even LIST its endpoints. These mirror the operator routes
# but are scoped to the key's workspace - a consumer can
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
    version: int = Depends(api_version),
) -> WebhookEndpointListResponse:
    """Your workspace's registered callbacks (secrets are never echoed).

    Workspace-scoped, matching what the per-id routes can mutate - listing by
    active channel would hide an endpoint that `PATCH`/`DELETE` still reach."""
    rows = _webhook_service(db).list_for_workspace(api_ws.tenant_id, api_ws.workspace_id)
    return versioned(WebhookEndpointListResponse(data=[_wh_item(r) for r in rows]), version)


@router.post("/webhooks", response_model=WebhookEndpointMintResponse, status_code=201)
def create_webhook(
    payload: WebhookEndpointCreateRequest,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
    version: int = Depends(api_version),
) -> WebhookEndpointMintResponse:
    """Register a callback that covers every channel of your workspace. The
    signing secret is returned ONCE - store it; it is never shown again."""
    from ..services.webhook_service import (
        WebhookError,
        WebhookKeyRevoked,
        WebhookNoActiveChannel,
    )

    try:
        _webhook_service(db).require_active_channel(api_ws.tenant_id, api_ws.workspace_id)
        row, secret = _webhook_service(db).create_for_workspace(
            api_ws.tenant_id, api_ws.workspace_id, payload.name, payload.url, payload.events,
            # No user behind an API key - record WHICH key, matching the
            # `apikey:<id>` actor convention used elsewhere in this service.
            # The activity log is pruned per tenant; this row is permanent.
            created_by=f"apikey:{api_ws.key_id}",
            key_id=api_ws.key_id,
            payload_version=payload.payloadVersion,
        )
    except WebhookNoActiveChannel as exc:
        raise ApiError(409, "no_active_channel", str(exc)) from exc
    except WebhookKeyRevoked as exc:
        raise _key_revoked() from exc
    except WebhookError as exc:
        raise _wh_guard(exc) from exc
    return versioned(
        WebhookEndpointMintResponse(endpoint=_wh_item(row), signingSecret=secret),
        version,
        status_code=status.HTTP_201_CREATED,
    )


def _paused_by_staff() -> ApiError:
    """The gateway's answer for a key write on an endpoint staff paused."""
    return ApiError(409, "endpoint_paused_by_staff", "This endpoint was paused by staff.")


def _endpoint_not_found() -> ApiError:
    return ApiError(404, "not_found", "Webhook endpoint not found.")


def _key_revoked() -> ApiError:
    """The gateway's answer for a key revoked while its write was under way."""
    return ApiError(401, "invalid_api_key", "Invalid API key.")


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
    version: int = Depends(api_version),
) -> WebhookEndpointItem:
    from ..services.webhook_service import (
        WebhookError,
        WebhookKeyRevoked,
        WebhookNotFound,
        WebhookPausedByStaff,
    )

    _own_endpoint(db, api_ws, endpoint_id)
    try:
        row = _webhook_service(db).update(
            api_ws.tenant_id, endpoint_id,
            name=payload.name, url=payload.url, events=payload.events,
            key_id=api_ws.key_id, payload_version=payload.payloadVersion,
        )
    except WebhookKeyRevoked as exc:
        raise _key_revoked() from exc
    except WebhookPausedByStaff as exc:
        raise _paused_by_staff() from exc
    except WebhookNotFound as exc:
        raise _endpoint_not_found() from exc
    except WebhookError as exc:
        raise _wh_guard(exc) from exc
    return versioned(_wh_item(row), version)


@router.post("/webhooks/{endpoint_id}/rotate", response_model=WebhookSecretResponse)
def rotate_webhook_secret(
    endpoint_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> WebhookSecretResponse:
    """New signing secret, returned ONCE. The old one stops verifying at once -
    deploy the new secret before rotating."""
    _own_endpoint(db, api_ws, endpoint_id)
    from ..services.webhook_service import WebhookKeyRevoked, WebhookNotFound, WebhookPausedByStaff

    try:
        _row, secret = _webhook_service(db).rotate_secret(
            api_ws.tenant_id, endpoint_id, key_id=api_ws.key_id
        )
    except WebhookKeyRevoked as exc:
        raise _key_revoked() from exc
    except WebhookPausedByStaff as exc:
        raise _paused_by_staff() from exc
    except WebhookNotFound as exc:
        raise _endpoint_not_found() from exc
    return WebhookSecretResponse(signingSecret=secret)


@router.post("/webhooks/{endpoint_id}/enable", response_model=WebhookEndpointItem)
def enable_webhook(
    endpoint_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
    version: int = Depends(api_version),
) -> WebhookEndpointItem:
    """Re-enable a disabled endpoint (also clears an AUTO_DISABLED strike count)."""
    from ..services.webhook_service import WebhookKeyRevoked, WebhookNotFound, WebhookPausedByStaff

    _own_endpoint(db, api_ws, endpoint_id)
    try:
        row = _webhook_service(db).set_status(
            api_ws.tenant_id, endpoint_id, True, key_id=api_ws.key_id
        )
    except WebhookKeyRevoked as exc:
        raise _key_revoked() from exc
    except WebhookPausedByStaff as exc:
        raise _paused_by_staff() from exc
    except WebhookNotFound as exc:
        raise _endpoint_not_found() from exc
    return versioned(_wh_item(row), version)


@router.post("/webhooks/{endpoint_id}/disable", response_model=WebhookEndpointItem)
def disable_webhook(
    endpoint_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
    version: int = Depends(api_version),
) -> WebhookEndpointItem:
    from ..services.webhook_service import WebhookKeyRevoked, WebhookNotFound

    _own_endpoint(db, api_ws, endpoint_id)
    try:
        row = _webhook_service(db).set_status(
            api_ws.tenant_id, endpoint_id, False, key_id=api_ws.key_id
        )
    except WebhookKeyRevoked as exc:
        raise _key_revoked() from exc
    except WebhookNotFound as exc:
        raise _endpoint_not_found() from exc
    return versioned(_wh_item(row), version)


@router.delete("/webhooks/{endpoint_id}", status_code=204)
def delete_webhook(
    endpoint_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> None:
    from ..services.webhook_service import WebhookNotFound, WebhookPausedByStaff

    _own_endpoint(db, api_ws, endpoint_id)
    try:
        _webhook_service(db).delete(api_ws.tenant_id, endpoint_id, key_id=api_ws.key_id)
    except WebhookPausedByStaff as exc:
        raise _paused_by_staff() from exc
    except WebhookNotFound as exc:
        raise _endpoint_not_found() from exc


_DELIVERY_STATUSES = ("PENDING", "SUCCESS", "FAILED")


@router.get(
    "/webhooks/{endpoint_id}/deliveries", response_model=PublicWebhookDeliveryListResponse
)
def list_webhook_deliveries(
    endpoint_id: str,
    delivery_status: Optional[str] = Query(
        default=None, alias="status", description="PENDING|SUCCESS|FAILED"
    ),
    limit: int = Query(50, ge=1, le=200),
    before: Optional[str] = Query(
        default=None, description="A delivery id from the previous page (`nextBefore`)."
    ),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicWebhookDeliveryListResponse:
    """Delivery history of one of your OWN endpoints, newest first (2026-11-18).
    Another workspace's endpoint id is the same 404 as an unknown one. Never
    returns the event body or the signing secret."""
    from ..services.webhook_service import WebhookError, webhook_delivery_item

    wanted = delivery_status.strip().upper() if delivery_status else None
    if wanted is not None and wanted not in _DELIVERY_STATUSES:
        raise ApiError(
            422, "invalid_request",
            f"Unknown status '{delivery_status}'. Use one of: {', '.join(_DELIVERY_STATUSES)}.",
        )
    _own_endpoint(db, api_ws, endpoint_id)
    try:
        rows = _webhook_service(db).list_deliveries(
            api_ws.tenant_id, endpoint_id, limit, status=wanted, before_id=before
        )
    except WebhookError as exc:
        raise _wh_guard(exc) from exc
    # A full page may have older rows; a short page is the last one.
    next_before = rows[-1].id if len(rows) == limit else None
    return PublicWebhookDeliveryListResponse(
        data=[webhook_delivery_item(r) for r in rows], nextBefore=next_before
    )


# ── Workflows (plan 38 gap 7) ────────────────────────────────────────────────
# A key configures the workflows its own workspace owns. Tenant and workspace
# come from the key only. The fixed paths (catalog, validate, runs/{runId}) are
# registered BEFORE `/workflows/{workflow_id}` so they are never read as an id.


async def _read_workflow_body(request: Request) -> dict:
    """Capped JSON read, done on the loop with no transaction open."""
    try:
        return await read_capped_json(request, cap=_JSON_BODY_CAP)
    except WebchatInvalidRequest as exc:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_request", exc.message)


def _validated(model, body: dict):
    try:
        return model(**body)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_context=False)) from None


@router.get("/workflows", response_model=PublicWorkflowListResponse)
def list_workflows(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicWorkflowListResponse:
    return KeyWorkflowService(db).list(
        api_ws.tenant_id, api_ws.workspace_id, limit=limit, cursor=cursor
    )


@router.post("/workflows", response_model=PublicWorkflowItem, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    request: Request,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicWorkflowItem:
    payload = _validated(PublicWorkflowCreateRequest, await _read_workflow_body(request))
    return await run_in_threadpool(
        KeyWorkflowService(db).create,
        api_ws.tenant_id,
        api_ws.workspace_id,
        api_ws.key_id,
        name=payload.name,
        description=payload.description,
        definition=payload.draftDefinition,
    )


@router.get("/workflows/catalog", response_model=PublicCatalogResponse)
def workflow_catalog(
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicCatalogResponse:
    return KeyWorkflowService(db).catalog(api_ws.tenant_id, api_ws.workspace_id)


@router.post("/workflows/validate", response_model=PublicValidateResponse)
async def validate_workflow(
    request: Request,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicValidateResponse:
    payload = _validated(PublicValidateRequest, await _read_workflow_body(request))
    return await run_in_threadpool(
        KeyWorkflowService(db).validate,
        api_ws.tenant_id,
        api_ws.workspace_id,
        payload.draftDefinition,
    )


@router.get("/workflows/runs/{run_id}", response_model=PublicWorkflowRunDetail)
def get_workflow_run(
    run_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicWorkflowRunDetail:
    return KeyWorkflowService(db).run_detail(api_ws.tenant_id, api_ws.workspace_id, run_id)


@router.get("/workflows/{workflow_id}", response_model=PublicWorkflowItem)
def get_workflow(
    workflow_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicWorkflowItem:
    return KeyWorkflowService(db).get(api_ws.tenant_id, api_ws.workspace_id, workflow_id)


@router.patch("/workflows/{workflow_id}", response_model=PublicWorkflowItem)
async def update_workflow(
    workflow_id: str,
    request: Request,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicWorkflowItem:
    payload = _validated(PublicWorkflowUpdateRequest, await _read_workflow_body(request))
    return await run_in_threadpool(
        KeyWorkflowService(db).update,
        api_ws.tenant_id,
        api_ws.workspace_id,
        workflow_id,
        name=payload.name,
        description=payload.description,
        definition=payload.draftDefinition,
        expected_updated_at=payload.expectedUpdatedAt,
    )


@router.post("/workflows/{workflow_id}/publish", response_model=PublicWorkflowItem)
def publish_workflow(
    workflow_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicWorkflowItem:
    return KeyWorkflowService(db).publish(
        api_ws.tenant_id, api_ws.workspace_id, api_ws.key_id, workflow_id
    )


@router.post("/workflows/{workflow_id}/unpublish", response_model=PublicWorkflowItem)
def unpublish_workflow(
    workflow_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicWorkflowItem:
    return KeyWorkflowService(db).unpublish(api_ws.tenant_id, api_ws.workspace_id, workflow_id)


@router.put("/workflows/{workflow_id}/active", response_model=PublicWorkflowItem)
async def set_workflow_active(
    workflow_id: str,
    request: Request,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicWorkflowItem:
    payload = _validated(PublicWorkflowActiveRequest, await _read_workflow_body(request))
    return await run_in_threadpool(
        KeyWorkflowService(db).set_active,
        api_ws.tenant_id,
        api_ws.workspace_id,
        workflow_id,
        payload.isActive,
    )


@router.get("/workflows/{workflow_id}/versions", response_model=PublicWorkflowVersionListResponse)
def list_workflow_versions(
    workflow_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicWorkflowVersionListResponse:
    return KeyWorkflowService(db).list_versions(
        api_ws.tenant_id, api_ws.workspace_id, workflow_id, limit=limit, cursor=cursor
    )


@router.get("/workflows/{workflow_id}/runs", response_model=PublicWorkflowRunListResponse)
def list_workflow_runs(
    workflow_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicWorkflowRunListResponse:
    return KeyWorkflowService(db).list_runs(
        api_ws.tenant_id, api_ws.workspace_id, workflow_id, limit=limit, cursor=cursor
    )


@router.post(
    "/workflows/{workflow_id}/runs",
    response_model=PublicWorkflowRunItem,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_workflow_for_contact(
    workflow_id: str,
    request: Request,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicWorkflowRunItem:
    payload = _validated(PublicWorkflowRunRequest, await _read_workflow_body(request))
    return await run_in_threadpool(
        KeyWorkflowService(db).run_for_contact,
        api_ws.tenant_id,
        api_ws.workspace_id,
        api_ws.key_id,
        workflow_id,
        contact=payload.contact,
        inputs=payload.inputs,
    )


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_workflow(
    workflow_id: str,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> Response:
    KeyWorkflowService(db).archive(api_ws.tenant_id, api_ws.workspace_id, workflow_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Business hours (plan 38 gap 7): the key's own workspace only ─────────────
@router.get("/business-hours", response_model=PublicBusinessHoursResponse)
def get_business_hours(
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicBusinessHoursResponse:
    data = BusinessHoursService(db).get_with_source(api_ws.tenant_id, api_ws.workspace_id)
    return PublicBusinessHoursResponse(workspaceId=api_ws.workspace_id, **data)


@router.put("/business-hours", response_model=PublicBusinessHoursResponse)
async def put_business_hours_route(
    request: Request,
    api_ws: ApiWorkspace = Depends(get_api_workspace),
    db: Session = Depends(get_db),
) -> PublicBusinessHoursResponse:
    try:
        raw = await read_capped_json(request)
    except WebchatInvalidRequest as exc:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_request", exc.message)
    payload = _validated(BusinessHoursUpdate, raw)
    data = await run_in_threadpool(
        put_business_hours,
        db,
        api_ws.tenant_id,
        api_ws.workspace_id,
        payload.timezone,
        payload.windows,
    )
    return PublicBusinessHoursResponse(workspaceId=api_ws.workspace_id, **data)
