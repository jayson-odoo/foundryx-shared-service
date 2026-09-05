"""Embed access-token authorization - plan 11H Slice 3 (AC-11H-09/10/11).

The conversation API accepts EITHER the native session/permission auth OR an
embed access token (``Authorization: Bearer <accessToken>``, ``typ="embed"``,
minted by ``/embed/session``). ``get_conversation_principal`` is the ONE unified
resolver every conversation route depends on: it yields a ``ConversationPrincipal``
carrying the tenant, the actor identity (native user OR external agent), and the
authorization surface (native permission keys OR embed scope+caps).

Enforcement is SERVER-SIDE and the backend is the boundary:
- **scope** - a ``thread:<contactId>`` token may only read/act on that contact;
  it cannot list the workspace or touch any other contact (403). An ``inbox``
  token spans its workspace.
- **caps** - a write cap (reply/assign/close/note/send_template) must be present;
  a ``read_only`` (or cap-missing) token is refused on every write (403),
  regardless of what the widget UI shows.

The native path is UNCHANGED - same ``_resolve_user`` / impersonation / permission
resolution / module-active check, just invoked here instead of via the router
gate (the conversation router is mounted public so both auth schemes reach it).
"""
from dataclasses import dataclass, field
from typing import List, Optional, Set

from fastapi import Depends, Header, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    _maybe_apply_impersonation,
    _resolve_user,
    effective_permission_keys,
)
from app.models.user import User
from app.repositories.module_repository import ModuleRepository
from app.security import decode_access_token

from .models import Workspace

MODULE_NAME = "omnichannel"

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)
_MODULE_EXC = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN, detail="Module not installed"
)


@dataclass
class EmbedPrincipal:
    """Resolved from an embed access token - the WS handshake uses this directly."""

    tenant_id: str
    workspace_id: str
    external_agent_id: str
    scope: str
    caps: List[str]
    connection_id: str


@dataclass
class ConversationPrincipal:
    """Unified caller identity for the conversation API - native user OR embed."""

    tenant_id: str
    is_embed: bool
    # Native attribution (real admin under impersonation); None for embed.
    actor_user_id: Optional[str] = None
    # Native EFFECTIVE user (impersonation target when active, else same as
    # `actor_user_id`) - B5: the identity `status_machine.transition` must
    # authorize edge-role/condition checks AS, matching every other caller in
    # the codebase (form_service, tenant_service, ideation all pass the
    # effective `current_user`, never the real-admin attribution id). None
    # for embed.
    effective_user_id: Optional[str] = None
    # Federated attribution; None for native.
    external_agent_id: Optional[str] = None
    # Embed: the token's workspace (scope boundary). Native: None = all workspaces.
    workspace_id: Optional[str] = None
    scope: str = "inbox"  # "inbox" | "thread:<contactId>"
    caps: List[str] = field(default_factory=list)
    permission_keys: Set[str] = field(default_factory=set)
    connection_id: Optional[str] = None

    # ── scope ────────────────────────────────────────────────────────────────
    @property
    def scope_contact_id(self) -> Optional[str]:
        if self.scope and self.scope.startswith("thread:"):
            return self.scope.split(":", 1)[1] or None
        return None

    def enforce_list(self) -> None:
        """A thread-scoped embed token can never list the workspace inbox."""
        if self.is_embed and self.scope_contact_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This token is scoped to a single conversation.",
            )

    # ── caps / permissions ───────────────────────────────────────────────────
    def require_read(self) -> None:
        if not self.is_embed and "conversations.read" not in self.permission_keys:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing permission: conversations.read",
            )
        # Any embed token may READ within its scope (scope enforced separately).

    def require_native_read(self, native_perm: str) -> None:
        """Gate a READ helper that both auth schemes reach (workspace templates /
        quick-replies / members). Native → the permission must be held (preserves
        the pre-embed gate on those routes). Embed → any token may read its OWN
        workspace's catalog (workspace scope enforced by ``enforce_workspace`` /
        ``enforce_channel_workspace``); no write-cap needed for a read."""
        if not self.is_embed and native_perm not in self.permission_keys:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {native_perm}",
            )

    def require(self, *, native_perm: str, embed_cap: str) -> None:
        """Gate a mutation: embed → the cap must be present; native → the
        permission must be held. Backend is the boundary (AC-11H-11)."""
        if self.is_embed:
            if embed_cap not in self.caps:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"This token lacks the '{embed_cap}' capability.",
                )
        else:
            if native_perm not in self.permission_keys:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Missing permission: {native_perm}",
                )


def _parse_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def _resolve_embed(token: str, db: Session) -> Optional[EmbedPrincipal]:
    """Return an EmbedPrincipal iff ``token`` is a valid embed access token, else
    None (the caller falls through to the native path). A malformed/expired token
    returns None → the native path then 401s uniformly."""
    try:
        payload = decode_access_token(token)
    except JWTError:
        return None
    if payload.get("typ") != "embed":
        return None
    tenant_id = payload.get("tenant_id")
    workspace_id = payload.get("workspaceId")
    agent_id = payload.get("external_agent_id")
    connection_id = payload.get("connection_id")
    if not (tenant_id and workspace_id and agent_id and connection_id):
        raise _CREDENTIALS_EXC
    # Module must be active for the tenant (mounted public - re-apply the gate).
    if not ModuleRepository(db).is_active(tenant_id, MODULE_NAME):
        raise _MODULE_EXC
    # The workspace must still belong to the tenant (a moved/trashed workspace
    # invalidates the token).
    ws = (
        db.query(Workspace)
        .filter(
            Workspace.id == workspace_id,
            Workspace.tenant_id == tenant_id,
            Workspace.is_trashed.is_(False),
        )
        .first()
    )
    if ws is None:
        raise _CREDENTIALS_EXC
    caps = payload.get("caps") or []
    return EmbedPrincipal(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        external_agent_id=agent_id,
        scope=payload.get("scope") or "inbox",
        caps=[c for c in caps if isinstance(c, str)],
        connection_id=connection_id,
    )


def get_conversation_principal(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> ConversationPrincipal:
    token = _parse_bearer(authorization)
    if token is None:
        raise _CREDENTIALS_EXC

    embed = _resolve_embed(token, db)
    if embed is not None:
        return ConversationPrincipal(
            tenant_id=embed.tenant_id,
            is_embed=True,
            external_agent_id=embed.external_agent_id,
            workspace_id=embed.workspace_id,
            scope=embed.scope,
            caps=embed.caps,
            connection_id=embed.connection_id,
        )

    # Native path - identical to the pre-embed protected auth (get_current_user +
    # impersonation + module-active + effective permission keys).
    real_user = _resolve_user(token, db)
    effective = _maybe_apply_impersonation(request, db, real_user)
    if not ModuleRepository(db).is_active(effective.tenant_id, MODULE_NAME):
        raise _MODULE_EXC
    actor = getattr(request.state, "real_user", real_user)
    return ConversationPrincipal(
        tenant_id=effective.tenant_id,
        is_embed=False,
        actor_user_id=str(actor.id),
        effective_user_id=str(effective.id),
        permission_keys=effective_permission_keys(effective),
    )


def enforce_thread_access(
    db: Session, principal: ConversationPrincipal, contact_id: str
) -> None:
    """Per-contact scope gate (AC-11H-10). Native: no-op (a native user spans the
    tenant, existing behavior). Embed: a thread-scoped token may touch ONLY its
    contact; an inbox-scoped token may touch only contacts in its workspace."""
    if not principal.is_embed:
        return
    scoped = principal.scope_contact_id
    if scoped is not None:
        if contact_id != scoped:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This token is scoped to a different conversation.",
            )
        return
    # inbox-scoped: the contact must live in the token's workspace.
    from .repositories.contact_repository import ContactRepository

    contact = ContactRepository(db).get_by_id(contact_id, principal.tenant_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if contact.workspace_id != principal.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This conversation is outside the token's workspace.",
        )


def enforce_workspace(principal: ConversationPrincipal, workspace_id: str) -> None:
    """Workspace-scope gate for the reused workspace-catalog reads (quick-replies,
    members). Native: no-op (a native user spans the tenant). Embed: the requested
    workspace MUST be the token's own - a token for workspace A can never read
    workspace B's quick-replies/members (backend is the boundary, never the
    widget). This holds even for a ``thread:<contactId>`` token, which stays
    confined to its workspace for these catalog lists."""
    if not principal.is_embed:
        return
    if workspace_id != principal.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This resource is outside the token's workspace.",
        )


def resolve_native_actor(principal: ConversationPrincipal, db: Session) -> Optional[User]:
    """Native-only actor resolution for edge-role auth (embed has none -
    `actor=None` fails closed on any actor-conditioned edge, by design). Tenant-
    scoped (the polymorphic stored-id rule - `actor_user_id` is a stored id,
    never resolved unscoped). Lives here, not in a router, so a router never
    runs its own `db.query(User)` (review round 1, finding 3)."""
    if principal.is_embed or not principal.actor_user_id:
        return None
    return (
        db.query(User)
        .filter(User.id == principal.actor_user_id, User.tenant_id == principal.tenant_id)
        .first()
    )


def resolve_effective_actor(principal: ConversationPrincipal, db: Session) -> Optional[User]:
    """B5: the EFFECTIVE-user counterpart to `resolve_native_actor`, for the
    ONE use that is an AUTHORIZATION check, not attribution -
    `status_machine.transition`'s edge-role/rule-condition gate (`move_lifecycle`
    / `lifecycle_moves`, and the lifecycle sub-move inside `patch_thread`).
    Under impersonation this is the TARGET (matches `permission_keys`, which
    already reads the target's grants) - `resolve_native_actor` stays the real
    admin for attribution (entity-event actor facts, `actor_id`). Tenant-scoped
    (polymorphic stored-id rule); embed has no native actor at all."""
    if principal.is_embed or not principal.effective_user_id:
        return None
    return (
        db.query(User)
        .filter(User.id == principal.effective_user_id, User.tenant_id == principal.tenant_id)
        .first()
    )


def enforce_channel_workspace(
    db: Session, principal: ConversationPrincipal, channel_id: str
) -> None:
    """Workspace-scope gate for the send-picker template list (keyed by channel).
    Native: no-op. Embed: the channel must live in the token's workspace, else the
    template catalog of another workspace's channel would leak (403). A missing
    channel is 404 (uniform)."""
    if not principal.is_embed:
        return
    from .repositories.channel_repository import ChannelRepository

    channel = ChannelRepository(db).get_by_id(channel_id, principal.tenant_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found.")
    if channel.workspace_id != principal.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This channel is outside the token's workspace.",
        )
