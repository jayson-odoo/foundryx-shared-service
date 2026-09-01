"""Embed-reachable READ helpers - plan 11H follow-up.

The reused ``ConversationDrawer`` + composer fetch three workspace/channel
catalogs while rendering a thread: the send-picker template list, the workspace
quick-replies, and the workspace members (assignee picker). Those originally
lived on the gated ``channels`` / ``workspaces`` routers (native-only), so an
embed access token 401'd on them. This PUBLIC router hosts the SAME three reads
behind the unified ``get_conversation_principal`` resolver so BOTH schemes reach
them:

- **Native** - the pre-embed permission gate is preserved verbatim
  (``conversations.reply`` for templates, ``conversations.read`` for
  quick-replies, ``workspaces.read`` for members) via ``require_native_read``;
  the module-active check + tenant scoping come from the principal + service.
- **Embed** - no write cap needed (these are reads), but the token is confined
  to ITS OWN workspace: ``enforce_workspace`` / ``enforce_channel_workspace``
  refuse a token that names workspace A from reading workspace B's catalog
  (backend is the boundary, never the widget). A ``thread:<contactId>`` token
  may still read its workspace's catalog (it needs templates to send / members
  to see assignees).

Mounted PUBLIC (no ``require_module`` router gate) with FULL paths + an empty
prefix - the ONE handler per path lives here, removed from the gated routers to
avoid a duplicate registration. The module-active gate is re-applied inside
``get_conversation_principal`` for both schemes.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from ..embed_auth import (
    ConversationPrincipal,
    enforce_channel_workspace,
    enforce_workspace,
    get_conversation_principal,
)
from ..schemas import TemplateItem, WorkspaceMemberItem
from ..services.workspace_service import WorkspaceNotFound

router = APIRouter()


@router.get(
    "/omnichannel/channels/{channel_id}/templates",
    response_model=List[TemplateItem],
)
def list_channel_templates(
    channel_id: str,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
) -> List[TemplateItem]:
    """Approved templates for the channel (the composer's template picker)."""
    from ..services.conversation_service import ThreadNotFound
    from ..services.message_service import MessageService

    principal.require_native_read("conversations.reply")
    enforce_channel_workspace(db, principal, channel_id)
    try:
        return MessageService(db).list_templates(channel_id, principal.tenant_id)
    except ThreadNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found.")


@router.get("/omnichannel/workspaces/{ws_id}/quick-replies")
def list_quick_replies(
    ws_id: str,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
):
    """Canned responses for the composer's ★ picker."""
    from ..services.message_service import MessageService

    principal.require_native_read("conversations.read")
    enforce_workspace(principal, ws_id)
    return MessageService(db).list_quick_replies(ws_id, principal.tenant_id)


@router.get(
    "/omnichannel/workspaces/{ws_id}/members",
    response_model=List[WorkspaceMemberItem],
)
def list_members(
    ws_id: str,
    principal: ConversationPrincipal = Depends(get_conversation_principal),
    db: Session = Depends(get_db),
    search: str = "",
) -> List[WorkspaceMemberItem]:
    """Workspace members - the assignee picker."""
    from ..services.workspace_service import WorkspaceService

    principal.require_native_read("workspaces.read")
    enforce_workspace(principal, ws_id)
    try:
        return WorkspaceService(db).members(ws_id, principal.tenant_id, search or None)
    except WorkspaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
