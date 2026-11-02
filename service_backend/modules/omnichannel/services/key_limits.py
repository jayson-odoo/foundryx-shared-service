"""Plan 50: per-key request limits on the API key routes.

Two bounds per workspace key, both held in Redis and checked by one Lua script
so the check and the take are atomic:

- requests started in the current minute: a counter keyed by the epoch minute
  (EXPIRE 120 set when the counter is created);
- requests in progress: a sorted set per key, one member per request (a uuid)
  scored by its expiry (now + 60 s). Entries past their expiry are dropped
  before counting, so a slot left by a dead worker frees itself. A refusal adds
  nothing and refreshes nothing; release removes that request's member.

A request over either bound gives back what it took and is refused with a
typed error carrying the seconds to wait. When Redis is unreachable requests
are allowed, with one warning a minute per kind per process.

Counted: the gateway routes (`get_api_workspace`), the ideation intake routes
that share it, and `GET /omnichannel/media/{id}` when a workspace key
authenticates it. Not counted: nothing on these routes streams or stays open
(no SSE or WebSocket route authenticates with a workspace key), so there is no
exemption to make.
"""
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import redis

from app.config import settings

logger = logging.getLogger(__name__)

SLOT_TTL_SECONDS = 60
_WARN_EVERY_SECONDS = 60.0
_SOCKET_TIMEOUT_SECONDS = 0.25

# KEYS: minute counter, in-flight set. ARGV: now, slot expiry, member,
# max per minute, max in flight. Returns 0 admitted, 1 per-minute, 2 in-flight.
_ACQUIRE_LUA = """
local started = redis.call('INCR', KEYS[1])
if started == 1 then redis.call('EXPIRE', KEYS[1], 120) end
if started > tonumber(ARGV[4]) then
  redis.call('DECR', KEYS[1])
  return 1
end
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ARGV[1])
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[5]) then
  redis.call('DECR', KEYS[1])
  return 2
end
redis.call('ZADD', KEYS[2], ARGV[2], ARGV[3])
redis.call('EXPIRE', KEYS[2], 61)
return 0
"""

_client: Optional[redis.Redis] = None
_timers: dict[str, float] = {}
_overrides_cache: Optional[tuple[str, dict]] = None


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
    member: str


def reset_state() -> None:
    """Forget the cached client, the warning timers and the parsed overrides."""
    global _client, _overrides_cache
    _client = None
    _overrides_cache = None
    _timers.clear()


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
            socket_timeout=_SOCKET_TIMEOUT_SECONDS,
        )
    return _client


def _warn(kind: str, message: str) -> None:
    """At most one warning a minute per kind per process."""
    now = time.monotonic()
    last = _timers.get(kind)
    if last is not None and now - last < _WARN_EVERY_SECONDS:
        return
    _timers[kind] = now
    logger.warning("%s", message)


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _setting(name: str, default: int) -> int:
    value = getattr(settings, name, default)
    if _whole(value):
        return value
    _warn(f"setting:{name}", f"key limit setting {name} is not a whole number of at least 1; default used")
    return default


def _overrides() -> dict:
    """The override map, parsed once per raw string; bad entries are skipped."""
    global _overrides_cache
    raw = settings.omni_key_limit_overrides or "{}"
    if _overrides_cache is not None and _overrides_cache[0] == raw:
        return _overrides_cache[1]
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        _warn("overrides_json", "key limit overrides are not valid JSON; none applied")
        parsed = {}
    if not isinstance(parsed, dict):
        _warn("overrides_json", "key limit overrides are not a JSON object; none applied")
        parsed = {}
    clean: dict[str, dict[str, int]] = {}
    for key_id, entry in parsed.items():
        if not isinstance(entry, dict):
            _warn("overrides_value", "a key limit override entry is not an object; skipped")
            continue
        kept: dict[str, int] = {}
        for name in ("max_in_flight", "max_per_minute"):
            if name not in entry:
                continue
            if _whole(entry[name]):
                kept[name] = entry[name]
            else:
                _warn("overrides_value", "a key limit override value is not a whole number of at least 1; skipped")
        clean[str(key_id)] = kept
    _overrides_cache = (raw, clean)
    return clean


def limits_for(key_id: str) -> tuple[int, int]:
    """(max_in_flight, max_per_minute) for a key: setting defaults, then override."""
    in_flight = _setting("omni_key_max_in_flight", 10)
    per_minute = _setting("omni_key_max_per_minute", 600)
    entry = _overrides().get(key_id, {})
    return entry.get("max_in_flight", in_flight), entry.get("max_per_minute", per_minute)


def acquire(key_id: str) -> Optional[Slot]:
    """Take a slot for the key or raise KeyLimitExceeded. Returns None (nothing
    to release) when the counter store is unreachable."""
    max_in_flight, max_per_minute = limits_for(key_id)
    now = time.time()
    minute = int(now // 60)
    member = uuid.uuid4().hex
    try:
        verdict = get_redis().execute_command(
            "EVAL",
            _ACQUIRE_LUA,
            2,
            f"omni:keylimit:{key_id}:min:{minute}",
            f"omni:keylimit:{key_id}:busy",
            now,
            now + SLOT_TTL_SECONDS,
            member,
            max_per_minute,
            max_in_flight,
        )
    except redis.exceptions.RedisError as exc:
        _warn("redis", f"redis unavailable for key limits, requests allowed: {type(exc).__name__}")
        return None
    verdict = int(verdict)
    if verdict == 1:
        raise KeyLimitExceeded("per_minute", max(1, math.ceil((minute + 1) * 60 - now)))
    if verdict == 2:
        raise KeyLimitExceeded("in_flight", 1)
    return Slot(key_id, member)


def release(slot: Optional[Slot]) -> None:
    """Give this request's slot back."""
    if slot is None:
        return
    try:
        get_redis().execute_command("ZREM", f"omni:keylimit:{slot.key_id}:busy", slot.member)
    except redis.exceptions.RedisError as exc:
        _warn("redis", f"redis unavailable for key limits, requests allowed: {type(exc).__name__}")


def log_refusal(key_id: str, exc: KeyLimitExceeded, route_name: str) -> None:
    """One record per refusal: key id, limit hit, route name. Never the key or body."""
    logger.warning(
        "key request refused: key_id=%s limit=%s route=%s", key_id, exc.limit, route_name
    )
