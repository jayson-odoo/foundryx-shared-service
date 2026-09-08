"""Realtime WebSocket (plan 05 decision 9): browser ⇄ FastAPI, one room per
workspace, Redis pub/sub fan-out so the Celery worker + multiple uvicorn
workers all reach the right sockets.

Auth on connect: JWT via `?token=` (browsers can't set headers on WS), user
must be ACTIVE in a sign-in-allowed tenant, hold `conversations.read`, and
either be a member of the workspace or hold `workspaces.manage` (admins see
every workspace without a membership row).

Plan 34 (A7b) S3 adds a THIRD principal type: a visitor token
(`typ="webchat"`, D-A7B-15). It is ALWAYS thread-scoped to its own contact
(never the native/embed "None = whole workspace" carve-out) and every
relayed frame passes through `webchat_projection.visitor_frame` - the same
fail-closed chokepoint the REST reads use (AC-WEB-38/39, R1/R2).
"""
import asyncio
import json
import logging
import random
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Optional

import redis.asyncio as aioredis
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError

from app.config import settings
from app.database import SessionLocal
from app.dependencies import effective_permission_keys
from app.models.user import User, UserStatus
from app.security import decode_access_token
from ..models import Channel, Workspace, WorkspaceMember
from ..services.realtime import channel_for
from ..services.webchat_projection import visitor_frame

logger = logging.getLogger(__name__)


@dataclass
class WsPrincipal:
    """What `_authorize` resolves a connecting socket to.

    `scope_contact_id` is `None` only for the native staff branch (whole-
    workspace visibility, admins/full members); the plan-11H embed branch
    and the plan-34 visitor branch both confine it to one contact.
    `visitor_channel` is set ONLY for a visitor principal - a plain proxy
    (never a live ORM row, which would be detached once `_authorize`'s own
    db session closes below) carrying just the one attribute
    `webchat_projection.visitor_frame` reads (`widget_config_json`), snapshot
    at connect time. `visitor_channel_id` is that channel's id, carried
    separately (review round 1, B2) because every relayed frame must be
    CHANNEL-scoped as well as contact-scoped - a contact can hold identities
    on several channels at once and this room is per workspace."""

    principal_id: str
    scope_contact_id: Optional[str]
    visitor_channel: Optional[Any] = None
    visitor_channel_id: Optional[str] = None


router = APIRouter()

# Plan 34 review round 1 (S4) - how often a LIVE visitor socket re-runs the
# full `_authorize` check. The visitor principal used to be resolved once at
# the handshake and never again, so an admin's "sign out all visitors" (an
# epoch bump), a channel deactivation, a channel trash or a tenant block left
# every already-open panel receiving agent replies until the visitor happened
# to close the tab. Only the VISITOR branch is re-verified: the staff and
# embed principals keep their existing (short-lived-token) behaviour, which
# this slice is not the place to change.
VISITOR_REVERIFY_SECONDS = 60.0


def set_visitor_reverify_seconds(seconds: float) -> None:
    """Test seam - shrink the interval so a test can prove an epoch bump
    closes an ALREADY-OPEN socket without sleeping a minute."""
    global VISITOR_REVERIFY_SECONDS
    VISITOR_REVERIFY_SECONDS = seconds


# Review round 2 (N-new-2) - a socket that connects in the same burst as a
# thousand others must not all re-verify (5+ queries plus an UPDATE/COMMIT)
# in lockstep every `VISITOR_REVERIFY_SECONDS`. A pure function (rather than
# inlining `random.uniform` in the loop) so it is unit-testable and so
# "computed once per socket" is enforced by call-site discipline: it is
# called exactly once, before `revalidate_visitor`'s `while True` starts.
def _jittered_interval(seconds: float) -> float:
    return seconds * random.uniform(0.8, 1.2)


_async_client = None
# Session factory seam: the WS handshake runs outside FastAPI's dependency
# system, so tests inject their sqlite session factory here.
_session_factory = SessionLocal


def set_session_factory(factory) -> None:
    global _session_factory
    _session_factory = factory


def get_async_redis():
    global _async_client
    if _async_client is None:
        _async_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _async_client


def set_async_redis(client) -> None:
    """Test seam - inject a fakeredis.aioredis client sharing the publisher's server."""
    global _async_client
    _async_client = client


def _authorize(
    token: str, workspace_id: str, *, stamp_presence: bool = True
) -> Optional[WsPrincipal]:
    """Resolve + authorize the WS caller synchronously. Returns `None` when
    the caller is not authorized (callers close the socket with 4403).

    Accepts the native staff JWT, an omnichannel embed access token
    (``typ="embed"``, plan 11H Slice 3), and a web chat visitor token
    (``typ="webchat"``, plan 34 / A7b S3).

    `stamp_presence` (review round 2, N-new-1) gates ONLY the visitor
    branch's `stamp_last_seen` side effect. The initial handshake and every
    real client-originated event (connect, message post) still stamp; the
    periodic background re-verification (`revalidate_visitor`) passes
    `stamp_presence=False` so a visitor who opens the panel and walks away
    stops reading as "Online now" forever - the marker is meant to decay to
    "Last seen ..." once nobody is actually there, and a timer that is not a
    real presence signal must not keep refreshing it."""
    db = _session_factory()
    try:
        try:
            payload = decode_access_token(token)
        except JWTError:
            return None
        # ── Embed access token branch (plan 11H) ──────────────────────────────
        # An `inbox` token → whole-workspace fan-out. A `thread:<contactId>`
        # token → the SAME workspace room, but every forwarded frame is filtered
        # server-side to that contact (``scope_contact_id`` below): scope is
        # enforced on the socket, NOT left to the widget (contract §8.2).
        if payload.get("typ") == "embed":
            agent_id = payload.get("external_agent_id")
            tenant_id = payload.get("tenant_id")
            token_ws = payload.get("workspaceId")
            if not (agent_id and tenant_id and token_ws) or token_ws != workspace_id:
                return None
            from app.repositories.module_repository import ModuleRepository

            if not ModuleRepository(db).is_active(tenant_id, "omnichannel"):
                return None
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
                return None
            scope = payload.get("scope") or ""
            scope_contact_id = (
                scope.split(":", 1)[1] if scope.startswith("thread:") else None
            )
            return WsPrincipal(agent_id, scope_contact_id)
        # ── Web chat visitor token branch (plan 34 / A7b S3) ───────────────────
        # ALWAYS thread-scoped (never the "None = whole workspace" carve-out
        # above) - a visitor is precisely a single-contact principal, and the
        # SAME `verify_visitor_token` the REST endpoints use is the ONE place
        # that decides a token is valid for this channel right now (typ,
        # tenant, channel, epoch - AC-WEB-27/R4).
        if payload.get("typ") == "webchat":
            from ..repositories.contact_repository import ContactRepository
            from ..services.webchat_visitor_service import stamp_last_seen
            from ..webchat_auth import InvalidVisitorToken, verify_visitor_token

            channel_id = payload.get("channelId")
            tenant_id = payload.get("tenantId")
            if not (channel_id and tenant_id):
                return None
            channel = (
                db.query(Channel)
                .filter(
                    Channel.id == channel_id,
                    Channel.tenant_id == tenant_id,
                    Channel.channel_type == "WEBCHAT",
                    Channel.is_trashed.is_(False),
                )
                .first()
            )
            if channel is None or not channel.is_active:
                return None
            from app.repositories.module_repository import ModuleRepository

            if not ModuleRepository(db).is_active(tenant_id, "omnichannel"):
                return None
            ws = (
                db.query(Workspace)
                .filter(
                    Workspace.id == workspace_id,
                    Workspace.tenant_id == tenant_id,
                    Workspace.is_trashed.is_(False),
                )
                .first()
            )
            if ws is None or ws.id != channel.workspace_id:
                return None
            try:
                claims = verify_visitor_token(token, channel)
            except InvalidVisitorToken:
                return None
            # The token's OWN `contactId` claim is advisory only (webchat_auth
            # docstring) - re-derive from the channel-scoped identity via the
            # token's own `identity_key` (plan 34 S5: `visitor:<visitorId>`
            # for an anonymous session, `host:<userRef>` once a host identity
            # assertion verified, D-A7B-9), exactly like `webchat_visitor_
            # service.history` does, never from the possibly-stale claim.
            identity = ContactRepository(db).find_identity(
                channel.id, claims.identity_key
            )
            if identity is None:
                # No thread yet (D-A7B-7's lazy creation) - nothing to scope a
                # socket to. Refuse rather than fall back to whole-workspace
                # visibility (R1); the poll fallback (GET .../messages,
                # D-A7B-16) covers a visitor who opens the panel before their
                # first message, and the panel reconnects once one exists.
                return None
            if stamp_presence:
                stamp_last_seen(db, channel.id, claims.identity_key)  # AC-WEB-42
            return WsPrincipal(
                principal_id=claims.identity_key,
                scope_contact_id=identity.contact_id,
                visitor_channel=SimpleNamespace(widget_config_json=channel.widget_config_json),
                visitor_channel_id=channel.id,
            )
        user = db.query(User).filter(User.id == payload.get("sub")).first()
        if (
            user is None
            or user.status != UserStatus.ACTIVE.value
            or user.tenant is None
            or not user.tenant.signin_allowed
        ):
            return None
        keys = effective_permission_keys(user)
        if "conversations.read" not in keys:
            return None
        # The router is mounted public (no require_module gate) - re-apply the
        # module-active check here, where we have the resolved tenant.
        from app.repositories.module_repository import ModuleRepository

        if not ModuleRepository(db).is_active(user.tenant_id, "omnichannel"):
            return None
        ws = (
            db.query(Workspace)
            .filter(Workspace.id == workspace_id, Workspace.tenant_id == user.tenant_id)
            .first()
        )
        if ws is None:
            return None
        member = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user.id,
            )
            .first()
        )
        if member is None and "workspaces.manage" not in keys:
            return None
        return WsPrincipal(user.id, None)
    finally:
        db.close()


def _event_contact_id(data: str):
    """Extract the contact id an event pertains to, for thread-scope filtering.
    Events carry it as a top-level ``contactId`` (status/reaction), a nested
    ``message.contactId`` (message.created), or the ``thread.id`` (the contact
    IS the thread, on message.created / contact.updated). Returns None when the
    frame carries no contact (fail closed: a thread-scoped socket drops it)."""
    try:
        event = json.loads(data)
    except (ValueError, TypeError):
        return None
    if event.get("contactId"):
        return event["contactId"]
    msg = event.get("message")
    if isinstance(msg, dict) and msg.get("contactId"):
        return msg["contactId"]
    thread = event.get("thread")
    if isinstance(thread, dict) and thread.get("id"):
        return thread["id"]
    return None


@router.websocket("/ws")
async def conversation_socket(
    websocket: WebSocket,
    workspace_id: str = Query(..., alias="workspaceId"),
    token: str = Query(...),
):
    principal = await asyncio.to_thread(_authorize, token, workspace_id)
    if principal is None:
        await websocket.close(code=4403)
        return
    scope_contact_id = principal.scope_contact_id

    await websocket.accept()
    pubsub = get_async_redis().pubsub()
    await pubsub.subscribe(channel_for(workspace_id))

    async def forward_events():
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message["data"]
            # Thread-scoped embed/visitor token: only relay frames for its one
            # contact (server-side scope enforcement - never trust the widget
            # to filter). A visitor principal's `scope_contact_id` is NEVER
            # `None` (`_authorize`'s webchat branch refuses the connection
            # rather than falling back to whole-workspace visibility - R1).
            if scope_contact_id is not None and _event_contact_id(data) != scope_contact_id:
                continue
            if principal.visitor_channel is not None:
                # AC-WEB-38/39 - a visitor NEVER gets a raw internal frame:
                # every relayed frame passes through the SAME fail-closed
                # projection the REST reads use (D-A7B-17). An unrecognized
                # frame type, or one belonging to another contact somehow
                # (defense in depth past the pre-filter above), is dropped.
                try:
                    frame = json.loads(data)
                except (ValueError, TypeError):
                    continue
                projected = visitor_frame(
                    frame,
                    principal.visitor_channel,
                    scope_contact_id,
                    principal.visitor_channel_id,
                )
                if projected is None:
                    continue
                await websocket.send_text(
                    json.dumps({"type": frame.get("type"), "message": projected}, default=str)
                )
                continue
            await websocket.send_text(data)

    async def watch_disconnect():
        # Drain client frames (pings etc.) - raises on close.
        while True:
            await websocket.receive_text()

    async def revalidate_visitor():
        """S4 (review round 1) - re-run the FULL visitor authorization on a
        timer for the life of the socket: token signature/expiry/`typ`,
        tenant + channel binding, the channel's `widget_token_epoch`, the
        channel being active and untrashed, the module being active for the
        tenant, and the tenant's own `signin_allowed`. `_authorize` IS all of
        those checks (never a second, drifting copy), so this returns exactly
        when the connection has stopped being authorized and the caller
        closes 4403.

        Review round 2 (N-new-1): this call passes `stamp_presence=False` -
        a timer firing is not a person being present, so it must not refresh
        `last_seen_at` (the real client actions - connect, message post -
        still do that, via `_authorize`'s default).

        Review round 2 (N-new-2): the interval carries +/-20% jitter,
        computed ONCE per socket (not per tick), so a burst of sockets that
        all connected in the same second do not all re-verify - and all hit
        the executor and the database - in lockstep every minute."""
        interval = _jittered_interval(VISITOR_REVERIFY_SECONDS)
        while True:
            await asyncio.sleep(interval)
            authorized = await asyncio.to_thread(
                _authorize, token, workspace_id, stamp_presence=False
            )
            if authorized is None:
                return

    forward = asyncio.create_task(forward_events())
    watcher = asyncio.create_task(watch_disconnect())
    tasks = {forward, watcher}
    revalidator = None
    if principal.visitor_channel is not None:
        revalidator = asyncio.create_task(revalidate_visitor())
        tasks.add(revalidator)
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if revalidator is not None and revalidator in done and not revalidator.cancelled():
            # Same close code the handshake refusal uses - the panel treats
            # 4403 as permanent (no reconnect storm) and falls back to the
            # poll, which re-checks the token on its own next call.
            await websocket.close(code=4403)
    except WebSocketDisconnect:
        pass
    finally:
        forward.cancel()
        watcher.cancel()
        if revalidator is not None:
            revalidator.cancel()
        try:
            await pubsub.unsubscribe(channel_for(workspace_id))
            await pubsub.aclose()
        except Exception:  # noqa: BLE001 - teardown best-effort
            pass
