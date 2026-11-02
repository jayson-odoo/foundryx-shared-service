"""Plan 50: per-key request limits on the API key routes.

Two counters per workspace key in Redis: requests started in the current
minute (INCR, EXPIRE 120, keyed by the epoch minute) and requests in progress
(INCR, EXPIRE 60, so a crashed process cannot hold a slot for long). A request
over either bound gives back what it took and is refused with a typed error
carrying the seconds to wait. When Redis is unreachable requests are allowed,
with one warning a minute per process.

Not counted: nothing on the key routes streams or stays open (no SSE or
WebSocket route authenticates with a workspace key), so every key route is
counted.
"""
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

import redis

from app.config import settings

logger = logging.getLogger(__name__)

_WARN_EVERY_SECONDS = 60.0
_client: Optional[redis.Redis] = None
_last_warning: Optional[float] = None


class KeyLimitExceeded(Exception):
    """A key is over a bound. `limit` is `in_flight` or `per_minute`."""

    def __init__(self, limit: str, retry_after: int):
        super().__init__(limit)
        self.limit = limit
        self.retry_after = retry_after


@dataclass
class Slot:
    """What an acquire took, so release gives back exactly that."""

    key_id: str


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            settings.redis_url, socket_connect_timeout=1, socket_timeout=1
        )
    return _client


def _overrides() -> dict:
    raw = settings.omni_key_limit_overrides
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        _warn("key limit overrides are not valid JSON; none applied")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def limits_for(key_id: str) -> tuple[int, int]:
    """(max_in_flight, max_per_minute) for a key: setting defaults, then override."""
    in_flight = settings.omni_key_max_in_flight
    per_minute = settings.omni_key_max_per_minute
    entry = _overrides().get(key_id)
    if isinstance(entry, dict):
        value = entry.get("max_in_flight")
        if isinstance(value, int) and not isinstance(value, bool):
            in_flight = value
        value = entry.get("max_per_minute")
        if isinstance(value, int) and not isinstance(value, bool):
            per_minute = value
    return in_flight, per_minute


def _warn(message: str) -> None:
    """At most one warning a minute per process."""
    global _last_warning
    now = time.monotonic()
    if _last_warning is not None and now - _last_warning < _WARN_EVERY_SECONDS:
        return
    _last_warning = now
    logger.warning("%s", message)


def acquire(key_id: str) -> Optional[Slot]:
    """Take a slot for the key or raise KeyLimitExceeded. Returns None (nothing
    to release) when the counter store is unreachable."""
    max_in_flight, max_per_minute = limits_for(key_id)
    now = time.time()
    minute = int(now // 60)
    minute_key = f"omni:keylimit:{key_id}:min:{minute}"
    busy_key = f"omni:keylimit:{key_id}:busy"
    try:
        r = get_redis()
        started = r.incr(minute_key)
        r.expire(minute_key, 120)
        if started > max_per_minute:
            r.decr(minute_key)
            raise KeyLimitExceeded("per_minute", max(1, (minute + 1) * 60 - int(now)))
        busy = r.incr(busy_key)
        r.expire(busy_key, 60)
        if busy > max_in_flight:
            r.decr(busy_key)
            r.decr(minute_key)
            raise KeyLimitExceeded("in_flight", 1)
    except redis.exceptions.RedisError as exc:
        _warn(f"redis unavailable for key limits, requests allowed: {type(exc).__name__}")
        return None
    return Slot(key_id)


def release(slot: Optional[Slot]) -> None:
    """Give the in-progress slot back; never below zero."""
    if slot is None:
        return
    try:
        r = get_redis()
        key = f"omni:keylimit:{slot.key_id}:busy"
        if r.decr(key) < 0:
            r.incr(key)
    except redis.exceptions.RedisError as exc:
        _warn(f"redis unavailable for key limits, requests allowed: {type(exc).__name__}")
