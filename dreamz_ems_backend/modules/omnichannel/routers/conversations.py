"""Conversation (inbox) routes — thin; gated by `conversations.*` permissions.

PATCH is field-gated per plan 05 §7: assignment needs `conversations.assign`,
status/priority transitions need `conversations.reply`.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from pydantic import BaseModel

from app.database import get_db
from app.dependencies import (
    effective_permission_keys,
    get_actor_user_id,
    get_current_user,
    require_permission,
)
from app.models.user import User
from ..schemas import (
    MessageItem,
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
from ..services.message_service import MessageService, SendRejected

router = APIRouter()


@router.get("", response_model=ThreadListResponse)
def list_threads(
    current_user: User = Depends(require_permission("conversations.read")),
    db: Session = Depends(get_db),
    workspace_id: Optional[str] = Query(None, alias="workspaceId"),
    assignee: str = Query("all", pattern="^(all|me|unassigned)$"),
    thread_status: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=200, alias="pageSize"),
) -> ThreadListResponse:
    items, total = ConversationService(db).list_threads(
        current_user.tenant_id,
        workspace_id=workspace_id,
        assignee=assignee,
        me_user_id=current_user.id,
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
    current_user: User = Depends(require_permission("conversations.read")),
    db: Session = Depends(get_db),
) -> ThreadItem:
    try:
        return ConversationService(db).get_thread(contact_id, current_user.tenant_id)
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.get("/{contact_id}/messages", response_model=List[MessageItem])
def list_messages(
    contact_id: str,
    current_user: User = Depends(require_permission("conversations.read")),
    db: Session = Depends(get_db),
) -> List[MessageItem]:
    try:
        return ConversationService(db).list_messages(contact_id, current_user.tenant_id)
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.patch("/{contact_id}", response_model=ThreadItem)
def patch_thread(
    contact_id: str,
    payload: ThreadPatch,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ThreadItem:
    # Field-level gates (plan 05 §7). Distinguish omitted vs explicit-null for
    # assignedUserId via model_fields_set (null = unassign).
    keys = effective_permission_keys(current_user)
    wants_assign = "assignedUserId" in payload.model_fields_set
    wants_lifecycle = payload.status is not None or payload.priority is not None
    if not wants_assign and not wants_lifecycle:
        raise HTTPException(status_code=400, detail="Nothing to update")
    if wants_assign and "conversations.assign" not in keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing permission: conversations.assign",
        )
    if wants_lifecycle and "conversations.reply" not in keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing permission: conversations.reply",
        )

    try:
        return ConversationService(db).patch_thread(
            contact_id,
            current_user.tenant_id,
            assigned_user_id=payload.assignedUserId if wants_assign else ...,
            status=payload.status,
            priority=payload.priority,
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except InvalidPatch as exc:
        raise HTTPException(status_code=422, detail=exc.message)


@router.post("/{contact_id}/messages", response_model=MessageItem, status_code=201)
def send_message(
    contact_id: str,
    payload: SendMessageRequest,
    current_user: User = Depends(require_permission("conversations.reply")),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> MessageItem:
    try:
        return MessageService(db).send_message(
            contact_id, current_user.tenant_id, actor_user_id, payload
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except SendRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message)


class NoteRequest(BaseModel):
    body: str


@router.post("/{contact_id}/notes", response_model=MessageItem, status_code=201)
def add_internal_note(
    contact_id: str,
    payload: NoteRequest,
    current_user: User = Depends(require_permission("conversations.reply")),
    actor_user_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> MessageItem:
    try:
        return MessageService(db).add_internal_note(
            contact_id, current_user.tenant_id, actor_user_id, payload.body
        )
    except ThreadNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except SendRejected as exc:
        raise HTTPException(status_code=422, detail=exc.message)
