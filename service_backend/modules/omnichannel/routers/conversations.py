"""Conversation (inbox) routes — thin; authorized by the unified conversation
principal (native session/permission OR embed access token, plan 11H Slice 3).

Every route depends on ``get_conversation_principal`` and enforces:
- **scope** — embed thread/inbox tokens can't widen (``enforce_list`` /
  ``enforce_thread_access``);
- **caps/permissions** — native PATCH is field-gated (assign vs reply); embed
  writes require the matching cap. Backend is the boundary.

Sends are attributed to the native actor (real admin under impersonation) OR the
federated external agent — never to client input.
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
from ..embed_auth import (
    ConversationPrincipal,
    enforce_thread_access,
    get_conversation_principal,
)
from ..schemas import (
    MessageItem,
    SendContactsRequest,
    SendLocationRequest,
    SendMessageRequest,
    ThreadItem,
    ThreadListResponse,
    ThreadPatch,
)
from ..services.conversation_service import (
    ConversationService,
    InvalidPatch,
    ThreadNotFound,
)
from ..services.media_pipeline import META_CEILINGS, MediaRejected
from ..services.message_service import MessageService, SendRejected

router = APIRouter()

# Capped read: never buffer more than the largest Meta ceiling + 1 (oversize is
# then rejected by the pipeline), so a hostile body can't exhaust memory.
_MEDIA_HARD_CAP = max(META_CEILINGS.values()) + 1


@router.get("", response_model=ThreadListResponse)
def list_threads(
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
    workspace_id: Optional[str] = Query(None, alias="workspaceId"),
    assignee: str = Query("all", pattern="^(all|me|unassigned)$"),
    thread_status: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=200, alias="pageSize"),
) -> ThreadListResponse:
    principal.require_read()
    # A thread-scoped embed token cannot list the workspace.
    principal.enforce_list()
    # Embed tokens are pinned to their own workspace + agent identity (client
    # query is ignored for tenancy — never trust it).
    if principal.is_embed:
        workspace_id = principal.workspace_id
    items, total = ConversationService(db).list_threads(
        principal.tenant_id,
        workspace_id=workspace_id,
        assignee=assignee,
        me_user_id=principal.actor_user_id,
        me_external_agent_id=principal.external_agent_id,
        status_key=None if thread_status in (None, "ALL") else thread_status,
        priority=None if priority in (None, "ALL") else priority,
        search=search,
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


@router.patch("/{contact_id}", response_model=ThreadItem)
def patch_thread(
    contact_id: str,
    payload: ThreadPatch,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> ThreadItem:
    enforce_thread_access(db, principal, contact_id)
    # Field-level gates (plan 05 §7): assignment vs lifecycle. Distinguish omitted
    # vs explicit-null for assignedUserId via model_fields_set (null = unassign).
    wants_assign = "assignedUserId" in payload.model_fields_set
    wants_lifecycle = payload.status is not None or payload.priority is not None
    if not wants_assign and not wants_lifecycle:
        raise HTTPException(status_code=400, detail="Nothing to update")
    if wants_assign:
        principal.require(native_perm="conversations.assign", embed_cap="assign")
    if wants_lifecycle:
        # Close/priority ride the reply-class gate natively; embed maps to "close".
        principal.require(native_perm="conversations.reply", embed_cap="close")

    try:
        return ConversationService(db).patch_thread(
            contact_id,
            principal.tenant_id,
            assigned_user_id=payload.assignedUserId if wants_assign else ...,
            status=payload.status,
            priority=payload.priority,
            external_connection_id=principal.connection_id if principal.is_embed else None,
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except InvalidPatch as exc:
        raise HTTPException(status_code=422, detail=exc.message)


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
    """Send an approved template — accepts JSON (the SendMessageRequest fields) OR
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
    """Send outbound media (image/video/audio/voice/document/sticker) — multipart.
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
    """React (emoji) to a message by our durable id — empty emoji removes."""
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
