"""Realtime fan-out (plan 05 decision 9): Redis pub/sub per workspace room.

Publishers (API send path, Celery worker) call ``publish(workspace_id, event)``;
the FastAPI WS endpoint subscribes to ``omnichannel:ws:{workspace_id}`` and
relays to connected sockets. Publish is BEST-EFFORT: a dead Redis must never
fail a send or a webhook task — events are a delivery nicety, the DB is truth.
"""
import json
import logging
from typing import Any, Dict, Optional

import redis

from app.config import settings

logger = logging.getLogger(__name__)

_client: Optional[redis.Redis] = None


def channel_for(workspace_id: str) -> str:
    return f"omnichannel:ws:{workspace_id}"


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def set_client(client: Optional[redis.Redis]) -> None:
    """Test seam — inject a fakeredis client (None resets to lazy real client)."""
    global _client
    _client = client


def publish(workspace_id: str, event: Dict[str, Any]) -> None:
    """Fire-and-forget publish of one event dict (camelCase payloads)."""
    try:
        _get_client().publish(channel_for(workspace_id), json.dumps(event, default=str))
    except Exception as exc:  # noqa: BLE001 — see module docstring
        logger.warning("omnichannel realtime publish failed: %s", exc)
