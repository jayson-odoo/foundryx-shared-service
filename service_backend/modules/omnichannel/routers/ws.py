"""Realtime WebSocket (plan 05 decision 9): browser ⇄ FastAPI, one room per
workspace, Redis pub/sub fan-out so the Celery worker + multiple uvicorn
workers all reach the right sockets.

Auth on connect: JWT via `?token=` (browsers can't set headers on WS), user
must be ACTIVE in a sign-in-allowed tenant, hold `conversations.read`, and
either be a member of the workspace or hold `workspaces.manage` (admins see
every workspace without a membership row).
"""
import asyncio
import json
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError

from app.config import settings
from app.database import SessionLocal
from app.dependencies import effective_permission_keys
from app.models.user import User, UserStatus
from app.security import decode_access_token
from ..models import Workspace, WorkspaceMember
from ..services.realtime import channel_for

logger = logging.getLogger(__name__)

router = APIRouter()

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
    """Test seam — inject a fakeredis.aioredis client sharing the publisher's server."""
    global _async_client
    _async_client = client


def _authorize(token: str, workspace_id: str):
    """Resolve + authorize the WS user synchronously. Returns ``(principal_id,
    scope_contact_id)`` — ``principal_id`` is the user id OR external-agent id,
    ``scope_contact_id`` is the single contact a thread-scoped embed token is
    confined to (``None`` = whole-workspace visibility). Returns ``None`` when
    the caller is not authorized (callers close the socket with 4403).

    Accepts BOTH the native staff JWT and an omnichannel embed access token
    (``typ="embed"``, plan 11H Slice 3)."""
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
            return agent_id, scope_contact_id
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
        # The router is mounted public (no require_module gate) — re-apply the
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
        return user.id, None
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
    _principal_id, scope_contact_id = principal

    await websocket.accept()
    pubsub = get_async_redis().pubsub()
    await pubsub.subscribe(channel_for(workspace_id))

    async def forward_events():
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message["data"]
            # Thread-scoped embed token: only relay frames for its one contact
            # (server-side scope enforcement — never trust the widget to filter).
            if scope_contact_id is not None and _event_contact_id(data) != scope_contact_id:
                continue
            await websocket.send_text(data)

    async def watch_disconnect():
        # Drain client frames (pings etc.) — raises on close.
        while True:
            await websocket.receive_text()

    forward = asyncio.create_task(forward_events())
    watcher = asyncio.create_task(watch_disconnect())
    try:
        done, pending = await asyncio.wait(
            {forward, watcher}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        forward.cancel()
        watcher.cancel()
        try:
            await pubsub.unsubscribe(channel_for(workspace_id))
            await pubsub.aclose()
        except Exception:  # noqa: BLE001 — teardown best-effort
            pass
