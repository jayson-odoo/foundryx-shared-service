"""Realtime WebSocket (plan 05 decision 9): browser ⇄ FastAPI, one room per
workspace, Redis pub/sub fan-out so the Celery worker + multiple uvicorn
workers all reach the right sockets.

Auth on connect: JWT via `?token=` (browsers can't set headers on WS), user
must be ACTIVE in a sign-in-allowed tenant, hold `conversations.read`, and
either be a member of the workspace or hold `workspaces.manage` (admins see
every workspace without a membership row).
"""
import asyncio
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
    """Resolve + authorize the WS user synchronously. Returns the user id or
    None (callers close the socket with 4403)."""
    db = _session_factory()
    try:
        try:
            payload = decode_access_token(token)
        except JWTError:
            return None
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
        return user.id
    finally:
        db.close()


@router.websocket("/ws")
async def conversation_socket(
    websocket: WebSocket,
    workspace_id: str = Query(..., alias="workspaceId"),
    token: str = Query(...),
):
    user_id = await asyncio.to_thread(_authorize, token, workspace_id)
    if user_id is None:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    pubsub = get_async_redis().pubsub()
    await pubsub.subscribe(channel_for(workspace_id))

    async def forward_events():
        async for message in pubsub.listen():
            if message.get("type") == "message":
                await websocket.send_text(message["data"])

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
