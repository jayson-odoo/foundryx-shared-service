"""Conversation (inbox) routes - thin; authorized by the unified conversation
principal (native session/permission OR embed access token, plan 11H Slice 3).

Every route depends on ``get_conversation_principal`` and enforces:
- **scope** - embed thread/inbox tokens can't widen (``enforce_list`` /
  ``enforce_thread_access``);
- **caps/permissions** - native PATCH is field-gated (assign vs reply); embed
  writes require the matching cap. Backend is the boundary.

Sends are attributed to the native actor (real admin under impersonation) OR the
federated external agent - never to client input.
"""
import json
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from sqlalchemy.orm import Session

from pydantic import BaseModel

from app.database import get_db
from app.services.status_machine import (
    TransitionConditionsNotMet,
    TransitionForbidden,
    TransitionNotAllowed,
)
from ..embed_auth import (
    ConversationPrincipal,
    enforce_thread_access,
    get_conversation_principal,
    resolve_effective_actor,
    resolve_native_actor,
)
from ..schemas import (
    CloseThreadRequest,
    ConversationEventListResponse,
    LifecycleMoveOption,
    LifecycleMoveRequest,
    MessageItem,
    SendContactsRequest,
    SendLocationRequest,
    SendMessageRequest,
    ShortcutItem,
    ShortcutRunResponse,
    ThreadItem,
    ThreadListResponse,
    ThreadPatch,
)
from ..services import event_service
from ..services.close_reason_service import CloseReasonInactive, CloseReasonNotFound
from ..services.contact_profile_service import ProfilePatchError
from ..services.conversation_service import (
    ConversationService,
    InvalidPatch,
    ThreadNotFound,
)
from ..services.inbox_view_service import InboxViewNotFound, InboxViewService
from ..services.lifecycle_service import LifecycleStageNotFound
from ..services.media_pipeline import META_CEILINGS, MediaRejected
from ..services.message_service import MessageService, SendRejected

router = APIRouter()

# Capped read: never buffer more than the largest Meta ceiling + 1 (oversize is
# then rejected by the pipeline), so a hostile body can't exhaust memory.
_MEDIA_HARD_CAP = max(META_CEILINGS.values()) + 1


def _csv(v: Optional[str]) -> Optional[List[str]]:
    if v is None:
        return None
    return [x.strip() for x in v.split(",") if x.strip()]


@router.get("", response_model=ThreadListResponse)
def list_threads(
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
    workspace_id: Optional[str] = Query(None, alias="workspaceId"),
    assignee: Optional[str] = Query(None, pattern="^(all|me|unassigned|user)$"),
    assignee_user_ids: Optional[str] = Query(None, alias="assigneeUserIds"),
    thread_status: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = None,
    search: Optional[str] = None,
    lifecycle_stage_ids: Optional[str] = Query(None, alias="lifecycleStageIds"),
    tag_ids: Optional[str] = Query(None, alias="tagIds"),
    channel_ids: Optional[str] = Query(None, alias="channelIds"),
    unreplied: Optional[bool] = Query(None),
    sort: Optional[str] = Query(
        None, pattern="^(newest|oldest|unreplied_first|longest_waiting)$"
    ),
    view_id: Optional[str] = Query(None, alias="viewId"),
    segment_id: Optional[str] = Query(None, alias="segmentId"),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=200, alias="pageSize"),
) -> ThreadListResponse:
    """Thread list (plan 05; plan 27 A3 S2 widens it - AC-IVE-15/16/17). All
    filtering/sorting happens in the repository, never Python. `viewId`
    expands a saved view's stored filter server-side; any EXPLICIT param sent
    alongside overrides that value (AC-IVE-17) - the sentinel for "not sent"
    is `None` on every new param, so a view's value survives unless the
    caller actually set that param. `segmentId` is reserved for A2 (plan 26,
    not on this branch yet) - accepted on the wire, refused with a named 422
    until then (D-A3-17)."""
    principal.require_read()
    # A thread-scoped embed token cannot list the workspace.
    principal.enforce_list()
    # Embed tokens are pinned to their own workspace + agent identity (client
    # query is ignored for tenancy - never trust it).
    if principal.is_embed:
        workspace_id = principal.workspace_id
    if segment_id:
        raise HTTPException(
            status_code=422, detail="Contact segments are not available yet."
        )

    view_kwargs: dict = {}
    if view_id:
        try:
            view = InboxViewService(db).get_visible(
                view_id, principal.tenant_id, principal.actor_user_id
            )
        except InboxViewNotFound:
            raise HTTPException(status_code=404, detail="View not found")
        if workspace_id and workspace_id != view.workspace_id:
            raise HTTPException(status_code=404, detail="View not found")
        workspace_id = view.workspace_id
        view_kwargs = InboxViewService(db).expand(view)

    final_status_key = None
    final_status_keys = view_kwargs.get("status_keys")
    if thread_status is not None:
        final_status_key = None if thread_status == "ALL" else thread_status
        final_status_keys = None

    items, total = ConversationService(db).list_threads(
        principal.tenant_id,
        workspace_id=workspace_id,
        assignee=assignee if assignee is not None else view_kwargs.get("assignee", "all"),
        assignee_user_ids=(
            _csv(assignee_user_ids)
            if assignee_user_ids is not None
            else view_kwargs.get("assignee_user_ids")
        ),
        me_user_id=principal.actor_user_id,
        me_external_agent_id=principal.external_agent_id,
        status_key=final_status_key,
        status_keys=final_status_keys,
        priority=(
            (None if priority in (None, "ALL") else priority)
            if priority is not None
            else view_kwargs.get("priority")
        ),
        search=search,
        lifecycle_stage_ids=(
            _csv(lifecycle_stage_ids)
            if lifecycle_stage_ids is not None
            else view_kwargs.get("lifecycle_stage_ids")
        ),
        tag_ids=_csv(tag_ids) if tag_ids is not None else view_kwargs.get("tag_ids"),
        channel_ids=(
            _csv(channel_ids) if channel_ids is not None else view_kwargs.get("channel_ids")
        ),
        unreplied=unreplied if unreplied is not None else view_kwargs.get("unreplied"),
        sort=sort if sort is not None else view_kwargs.get("sort"),
        page=page,
        page_size=page_size,
    )
    return ThreadListResponse(data=items, total=total)


@router.get("/{contact_id}", response_model=ThreadItem)
def get_thread(
    contact_id: str,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> ThreadItem:
    principal.require_read()
    enforce_thread_access(db, principal, contact_id)
    try:
        return ConversationService(db).get_thread(contact_id, principal.tenant_id)
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.get("/{contact_id}/messages", response_model=List[MessageItem])
def list_messages(
    contact_id: str,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> List[MessageItem]:
    principal.require_read()
    enforce_thread_access(db, principal, contact_id)
    try:
        return ConversationService(db).list_messages(contact_id, principal.tenant_id)
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")


_PROFILE_KEYS = {
    "firstName",
    "lastName",
    "email",
    "language",
    "countryCode",
    "customFields",
    "tagIds",
}


@router.patch("/{contact_id}", response_model=ThreadItem)
def patch_thread(
    contact_id: str,
    payload: ThreadPatch,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> ThreadItem:
    enforce_thread_access(db, principal, contact_id)
    # Field-level gates (plan 05 §7 + plan 25 AC-CDM-28): assignment vs
    # lifecycle vs profile (system fields / custom fields / tags). Distinguish
    # omitted vs explicit-null for assignedUserId via model_fields_set (null =
    # unassign).
    sent = payload.model_fields_set
    # `phone` is the inbound stitch key (no uniqueness guard, outside the
    # AC-22 whitelist) - never writable through this PATCH (finding 12).
    if "phone" in sent:
        raise HTTPException(
            status_code=422,
            detail={"fieldErrors": {"phone": "Phone is not editable."}},
        )
    wants_assign = "assignedUserId" in sent
    wants_lifecycle = payload.status is not None or payload.priority is not None
    wants_profile = bool(sent & _PROFILE_KEYS)
    if not (wants_assign or wants_lifecycle or wants_profile):
        raise HTTPException(status_code=400, detail="Nothing to update")
    if wants_assign:
        principal.require(native_perm="conversations.assign", embed_cap="assign")
    if wants_lifecycle:
        # Close/priority ride the reply-class gate natively; embed maps to "close".
        principal.require(native_perm="conversations.reply", embed_cap="close")
    if wants_profile:
        # Profile edits (fields/tags) are a native-only surface in this slice -
        # embed access tokens have no matching capability.
        if principal.is_embed:
            raise HTTPException(
                status_code=403,
                detail="This token cannot edit contact profile fields.",
            )
        if "contacts.manage" not in principal.permission_keys:
            raise HTTPException(
                status_code=403, detail="Missing permission: contacts.manage"
            )

    try:
        return ConversationService(db).patch_thread(
            contact_id,
            principal.tenant_id,
            assigned_user_id=payload.assignedUserId if wants_assign else ...,
            status=payload.status,
            priority=payload.priority,
            first_name=payload.firstName if "firstName" in sent else ...,
            last_name=payload.lastName if "lastName" in sent else ...,
            email=payload.email if "email" in sent else ...,
            language=payload.language if "language" in sent else ...,
            country_code=payload.countryCode if "countryCode" in sent else ...,
            custom_fields=payload.customFields if "customFields" in sent else ...,
            tag_ids=payload.tagIds if "tagIds" in sent else ...,
            actor=resolve_native_actor(principal, db),
            actor_id=principal.actor_user_id,
            actor_external_agent_id=principal.external_agent_id if principal.is_embed else None,
            external_connection_id=principal.connection_id if principal.is_embed else None,
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except InvalidPatch as exc:
        raise HTTPException(status_code=422, detail=exc.message)
    except ProfilePatchError as exc:
        raise HTTPException(status_code=422, detail={"fieldErrors": exc.errors})


@router.post("/{contact_id}/close", response_model=ThreadItem)
def close_thread(
    contact_id: str,
    payload: CloseThreadRequest,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> ThreadItem:
    """Close with a required reason + optional note (plan 27 A3, S2 -
    AC-IVE-28/29). Reuses `patch_thread`'s existing `closed` write (no
    duplicate event insert) and its `_publish_contact_updated` fan-out - the
    realtime WS event and the consumer `contact.updated` webhook both still
    fire exactly once."""
    principal.require(native_perm="conversations.reply", embed_cap="close")
    enforce_thread_access(db, principal, contact_id)
    try:
        return ConversationService(db).close_thread(
            contact_id,
            principal.tenant_id,
            close_reason_id=payload.closeReasonId,
            note=payload.note,
            actor=resolve_native_actor(principal, db),
            actor_id=principal.actor_user_id,
            actor_external_agent_id=principal.external_agent_id if principal.is_embed else None,
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except CloseReasonNotFound:
        raise HTTPException(status_code=404, detail="Close reason not found")
    except CloseReasonInactive:
        raise HTTPException(
            status_code=422, detail={"fieldErrors": {"closeReasonId": "This close reason is inactive."}}
        )


@router.get("/{contact_id}/events", response_model=ConversationEventListResponse)
def list_events(
    contact_id: str,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=200, alias="pageSize"),
) -> ConversationEventListResponse:
    """Conversation events (plan 27 A3, S1) - newest-first, paginated
    (AC-IVE-13). Same read gate + scope enforcement as `list_messages` (an
    embed token sees its own thread's events, exactly like notes) - a foreign-
    tenant contact_id is a uniform 404, never a 403."""
    principal.require_read()
    enforce_thread_access(db, principal, contact_id)
    contact = ConversationService(db).repo.get_by_id(contact_id, principal.tenant_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    rows, total = event_service.list_for_contact(
        db, contact_id, principal.tenant_id, page=page, page_size=page_size
    )
    items = event_service.to_items(db, rows, principal.tenant_id)
    return ConversationEventListResponse(data=items, total=total)


@router.get("/{contact_id}/shortcuts", response_model=List[ShortcutItem])
def list_shortcuts(
    contact_id: str,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> List[ShortcutItem]:
    """Published `entity.shortcut` workflows the drawer's Shortcuts control may
    offer for this contact (plan 27 A3, S3 - AC-IVE-36). Gated
    `conversations.shortcut` only (main-session decision 2026-09-06 supersedes
    the plan's `conversations.read` + `workflows.read` pair - a typical agent
    should not need core workflow-engine permissions to see the button); no
    embed cap grants it (AC-IVE-40)."""
    principal.require_native("conversations.shortcut")
    enforce_thread_access(db, principal, contact_id)
    try:
        rows = ConversationService(db).list_shortcuts(contact_id, principal.tenant_id)
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return [ShortcutItem(workflowId=r["workflowId"], name=r["name"]) for r in rows]


@router.post("/{contact_id}/shortcuts/{workflow_id}", response_model=ShortcutRunResponse)
def run_shortcut(
    contact_id: str,
    workflow_id: str,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> ShortcutRunResponse:
    """Fire a shortcut workflow against this contact's PUBLISHED version
    (never the draft) through the SAME helper the CRUD event bus uses (plan 27
    A3, S3 - AC-IVE-37, D-A3-10). Gated `conversations.shortcut` only (see
    `list_shortcuts` above); no embed cap grants it (AC-IVE-40). Every
    "not a valid shortcut for this record" case (unpublished / inactive /
    archived / foreign tenant / not an `entity.shortcut` workflow / not bound
    to `omnichannel_contact`) is a uniform 404 (AC-IVE-38, AC-IVE-42); a
    Code-node the publisher never authorized is a 409, not a run."""
    principal.require_native("conversations.shortcut")
    enforce_thread_access(db, principal, contact_id)
    from app.services.workflow_service import ShortcutCodeNotAuthorized, ShortcutNotFound

    try:
        run = ConversationService(db).run_shortcut(
            contact_id, principal.tenant_id, workflow_id, actor=resolve_native_actor(principal, db)
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except ShortcutNotFound:
        raise HTTPException(status_code=404, detail="Shortcut not found")
    except ShortcutCodeNotAuthorized:
        raise HTTPException(
            status_code=409,
            detail="This workflow's published version has an unauthorized Code node.",
        )
    return ShortcutRunResponse(runId=run.id, status=run.status)


@router.post("/{contact_id}/lifecycle", response_model=ThreadItem)
def move_lifecycle(
    contact_id: str,
    payload: LifecycleMoveRequest,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> ThreadItem:
    """Move a contact's lifecycle stage (plan 25 S2, AC-CDM-17) - delegates
    entirely to `status_machine.transition` via `lifecycle_service.move`."""
    enforce_thread_access(db, principal, contact_id)
    if principal.is_embed:
        raise HTTPException(
            status_code=403, detail="This token cannot move a contact's lifecycle."
        )
    if "contacts.manage" not in principal.permission_keys:
        raise HTTPException(status_code=403, detail="Missing permission: contacts.manage")

    # B5: edge-role/condition authorization runs AS the effective (impersonated
    # target) user - `resolve_native_actor` (real admin) is for ATTRIBUTION
    # only, never for a `status_machine.transition` auth check.
    actor = resolve_effective_actor(principal, db)
    try:
        return ConversationService(db).move_lifecycle(
            contact_id, principal.tenant_id, payload.toStatusId, actor=actor
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except LifecycleStageNotFound:
        raise HTTPException(status_code=404, detail="Lifecycle stage not found.")
    except TransitionForbidden as exc:
        raise HTTPException(status_code=403, detail=exc.message)
    except (TransitionNotAllowed, TransitionConditionsNotMet) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "lifecycle_move_not_allowed", "message": exc.message},
        )


@router.get("/{contact_id}/lifecycle-moves", response_model=List[LifecycleMoveOption])
def get_lifecycle_moves(
    contact_id: str,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> List[LifecycleMoveOption]:
    """Fireable outgoing edges for this contact right now (AC-CDM-18) - empty
    on a won (`is_terminal`) stage. Lifecycle is a native-only surface (like the
    two lifecycle WRITE routes) - an embed principal is refused, consistent
    with `move_lifecycle` / the `wants_profile` gate on `patch_thread` (D14)."""
    if principal.is_embed:
        raise HTTPException(
            status_code=403,
            detail="This token cannot read a contact's lifecycle moves.",
        )
    if not ({"conversations.read", "contacts.read"} & principal.permission_keys):
        raise HTTPException(
            status_code=403,
            detail="Missing permission: one of conversations.read, contacts.read",
        )
    enforce_thread_access(db, principal, contact_id)
    # B5: same authorization-vs-attribution split as `move_lifecycle` above -
    # the fireable-edges computation must reflect what the EFFECTIVE user can
    # fire, not the real admin under impersonation.
    actor = resolve_effective_actor(principal, db)
    try:
        edges = ConversationService(db).lifecycle_moves(
            contact_id, principal.tenant_id, actor=actor
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return [
        LifecycleMoveOption(edgeId=e.id, toStatusId=e.to_status_id, label=e.label)
        for e in edges
    ]


@router.post("/{contact_id}/messages", response_model=MessageItem, status_code=201)
def send_message(
    contact_id: str,
    payload: SendMessageRequest,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> MessageItem:
    principal.require(native_perm="conversations.reply", embed_cap="reply")
    enforce_thread_access(db, principal, contact_id)
    try:
        return MessageService(db).send_message(
            contact_id,
            principal.tenant_id,
            principal.actor_user_id,
            payload,
            external_agent_id=principal.external_agent_id,
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except SendRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message)


@router.post("/{contact_id}/template", response_model=MessageItem, status_code=201)
async def send_template(
    contact_id: str,
    request: Request,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> MessageItem:
    """Send an approved template - accepts JSON (the SendMessageRequest fields) OR
    multipart (a ``payload`` JSON part + an optional ``file`` header-media part).
    Handles TEXT-header / body / URL-button variables + image/video/document
    header media (AC-12-22). The header-less/text path also works via
    ``POST /{contact_id}/messages``."""
    principal.require(native_perm="conversations.reply", embed_cap="send_template")
    enforce_thread_access(db, principal, contact_id)
    header_content: Optional[bytes] = None
    header_filename: Optional[str] = None
    if request.headers.get("content-type", "").startswith("multipart/"):
        form = await request.form()
        raw = form.get("payload")
        upload = form.get("file")
        if raw is None:
            raise HTTPException(status_code=422, detail="A payload part is required.")
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="payload must be valid JSON.")
        if upload is not None:
            header_content = await upload.read(_MEDIA_HARD_CAP)
            header_filename = getattr(upload, "filename", None)
    else:
        try:
            data = await request.json()
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Request body must be valid JSON.")
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="Invalid template request.")
    data.setdefault("messageType", "TEMPLATE")
    try:
        payload = SendMessageRequest(**data)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Invalid template request.")
    try:
        return MessageService(db).send_message(
            contact_id,
            principal.tenant_id,
            principal.actor_user_id,
            payload,
            header_content=header_content,
            header_filename=header_filename,
            external_agent_id=principal.external_agent_id,
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except MediaRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message)
    except SendRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message)


@router.post("/{contact_id}/media", response_model=MessageItem, status_code=201)
async def send_message_media(
    contact_id: str,
    kind: str = Form(...),
    caption: Optional[str] = Form(None),
    reply_to_message_id: Optional[str] = Form(None),
    file: UploadFile = File(...),
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> MessageItem:
    """Send outbound media (image/video/audio/voice/document/sticker) - multipart.
    Sniff-gated + cap-checked, then queued for async upload-by-id send."""
    principal.require(native_perm="conversations.reply", embed_cap="reply")
    enforce_thread_access(db, principal, contact_id)
    # Cap the buffered read at THIS kind's Meta ceiling (memory safety); the real
    # per-workspace cap is enforced in send_media.
    hard_cap = META_CEILINGS.get((kind or "").upper(), _MEDIA_HARD_CAP) + 1
    content = await file.read(hard_cap)
    try:
        return MessageService(db).send_media(
            contact_id,
            principal.tenant_id,
            principal.actor_user_id,
            kind=kind,
            content=content,
            filename=file.filename,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
            external_agent_id=principal.external_agent_id,
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except MediaRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message)
    except SendRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message)


@router.post("/{contact_id}/interactive", response_model=MessageItem, status_code=201)
async def send_interactive(
    contact_id: str,
    request: Request,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> MessageItem:
    """Send an interactive message (reply-buttons/list/CTA-URL/location-request).
    Accepts JSON (the interactive definition) OR multipart (``file`` media header
    + a ``payload`` JSON part)."""
    principal.require(native_perm="conversations.reply", embed_cap="reply")
    enforce_thread_access(db, principal, contact_id)
    header_content: Optional[bytes] = None
    header_filename: Optional[str] = None
    reply_to: Optional[str] = None
    if request.headers.get("content-type", "").startswith("multipart/"):
        form = await request.form()
        raw = form.get("payload")
        upload = form.get("file")
        if raw is None:
            raise HTTPException(status_code=422, detail="A payload part is required.")
        try:
            defn = json.loads(raw)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="payload must be valid JSON.")
        if upload is not None:
            header_content = await upload.read(max(META_CEILINGS.values()) + 1)
            header_filename = getattr(upload, "filename", None)
    else:
        try:
            defn = await request.json()
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="Request body must be valid JSON.")
    if not isinstance(defn, dict):
        raise HTTPException(status_code=422, detail="Invalid interactive definition.")
    reply_to = defn.pop("replyToMessageId", None)
    try:
        return MessageService(db).send_interactive(
            contact_id,
            principal.tenant_id,
            principal.actor_user_id,
            defn=defn,
            header_content=header_content,
            header_filename=header_filename,
            reply_to_message_id=reply_to,
            external_agent_id=principal.external_agent_id,
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except MediaRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message)
    except SendRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message)


@router.post("/{contact_id}/location", response_model=MessageItem, status_code=201)
def send_location(
    contact_id: str,
    payload: SendLocationRequest,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> MessageItem:
    principal.require(native_perm="conversations.reply", embed_cap="reply")
    enforce_thread_access(db, principal, contact_id)
    try:
        return MessageService(db).send_location(
            contact_id,
            principal.tenant_id,
            principal.actor_user_id,
            defn=payload.model_dump(exclude={"replyToMessageId"}),
            reply_to_message_id=payload.replyToMessageId,
            external_agent_id=principal.external_agent_id,
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except SendRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message)


@router.post("/{contact_id}/contacts", response_model=MessageItem, status_code=201)
def send_contacts(
    contact_id: str,
    payload: SendContactsRequest,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> MessageItem:
    principal.require(native_perm="conversations.reply", embed_cap="reply")
    enforce_thread_access(db, principal, contact_id)
    try:
        return MessageService(db).send_contacts(
            contact_id,
            principal.tenant_id,
            principal.actor_user_id,
            defn={"contacts": payload.contacts},
            reply_to_message_id=payload.replyToMessageId,
            external_agent_id=principal.external_agent_id,
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except SendRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message)


class ReactRequest(BaseModel):
    emoji: str = ""  # empty removes the agent's reaction


class ReactionResult(BaseModel):
    targetMessageId: str
    emoji: str
    removed: bool


@router.post("/{contact_id}/messages/{message_id}/react", response_model=ReactionResult)
def react_to_message(
    contact_id: str,
    message_id: str,
    payload: ReactRequest,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> ReactionResult:
    """React (emoji) to a message by our durable id - empty emoji removes."""
    principal.require(native_perm="conversations.reply", embed_cap="reply")
    enforce_thread_access(db, principal, contact_id)
    try:
        result = MessageService(db).react(
            message_id,
            principal.tenant_id,
            principal.actor_user_id,
            emoji=payload.emoji,
            expected_contact_id=contact_id,
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Message not found")
    except SendRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message)
    return ReactionResult(**result)


class NoteRequest(BaseModel):
    body: str


@router.post("/{contact_id}/notes", response_model=MessageItem, status_code=201)
def add_internal_note(
    contact_id: str,
    payload: NoteRequest,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> MessageItem:
    principal.require(native_perm="conversations.reply", embed_cap="note")
    enforce_thread_access(db, principal, contact_id)
    try:
        return MessageService(db).add_internal_note(
            contact_id,
            principal.tenant_id,
            principal.actor_user_id,
            payload.body,
            external_agent_id=principal.external_agent_id,
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except SendRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message)
