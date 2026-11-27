"""AUTOCOUNT-LOAD-STRATEGY - one AutoCount request at a time per server, and a
safety stop when the server is failing
(``documentation/plans/sprint-5/autocount-load-strategy.md``).

Owner 27 Nov: "one request at a time per server, across all entities" - an SO
query and a stock balance page never hit the same AutoCount server together.
The turn is taken PAGE BY PAGE (one request), never for a whole run, so a
4-minute stock walk interleaves with a 1-page SO poll instead of blocking it.
A call a person is waiting on (a write such as Link PO, a lookup from a
screen) is ``PRIORITY_USER``: while one waits, no scheduled page takes the
next turn, so a person waits at most for the one page already in flight.

The "server" is the base URL's host (``scheme://host:port``): the books of
one wrapper share one machine, which is what slows down.

State lives in Redis so the web process and every worker share it. Redis is
best-effort: when it cannot be reached the request goes ahead (today's
behaviour) and a warning is logged, never a failed sync.

Safety stop: ``stop_after_failures`` failed requests in a row (timeout,
connection error, 5xx/524) on a server stop every SCHEDULED request to that
server for ``stop_minutes``. After that one test call is let through; a good
answer resumes everything, a bad one stops it again. A person's own call is
never refused by the stop (it is still counted).
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator, Optional
from urllib.parse import urlsplit

logger = logging.getLogger("foundryx.autocount")

PRIORITY_SYNC = "sync"
PRIORITY_USER = "user"

KEY_PREFIX = "ac:server"
# How often a waiter asks for the turn again. A person's call asks more often.
POLL_SECONDS_SYNC = 0.2
POLL_SECONDS_USER = 0.05
# A scheduled page that cannot get a turn for this long fails like a busy
# server (the page's own retry ladder then applies). A person's call never
# fails for want of a turn: past this it goes ahead (better one overlap than a
# write reported as failed although nothing was sent).
MAX_WAIT_SECONDS_SYNC = 600.0
MAX_WAIT_SECONDS_USER = 120.0
# The "a person is waiting" marker outlives a crashed waiter by this much.
URGENT_TTL_SECONDS = 30
# Margin on top of the request timeout for the held turn's expiry, so a
# crashed holder frees the server by itself.
HOLD_MARGIN_SECONDS = 10.0

_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)

# ``None`` = lazy real client from settings; ``False`` = switched off (tests).
_client: Any = None
_last_warning = 0.0


class ServerBusy(Exception):
    """No turn within ``MAX_WAIT_SECONDS_SYNC``."""


class ServerStopped(Exception):
    """The safety stop is on for this server; ``until`` is when it lifts."""

    def __init__(self, until: datetime) -> None:
        self.until = until
        super().__init__(f"stopped until {until.isoformat()}")


@dataclass(frozen=True)
class ServerPolicy:
    one_at_a_time: bool = True
    stop_after_failures: int = 3
    stop_minutes: int = 10


DEFAULT_POLICY = ServerPolicy()
OFF_POLICY = ServerPolicy(one_at_a_time=False, stop_after_failures=0)


def set_client(client: Any) -> None:
    """Test seam: a fakeredis client, ``False`` to switch the gate off, or
    ``None`` to go back to the lazy real client."""
    global _client
    _client = client


def _redis() -> Any:
    global _client
    if _client is False:
        return None
    if _client is None:
        import redis

        from app.config import settings

        _client = redis.Redis.from_url(
            settings.redis_url, decode_responses=True,
            socket_connect_timeout=1.0, socket_timeout=1.0,
        )
    return _client


def _warn(message: str, exc: Exception) -> None:
    global _last_warning
    now = time.monotonic()
    if now - _last_warning > 60:
        _last_warning = now
        logger.warning("AutoCount server gate: %s (%s) - going ahead without it", message, exc)


def server_key(base_url: str) -> str:
    parts = urlsplit(base_url or "")
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port else ""
    return f"{(parts.scheme or 'https').lower()}://{host}{port}"


def _keys(base_url: str) -> dict:
    root = f"{KEY_PREFIX}:{server_key(base_url)}"
    return {
        "lock": f"{root}:lock", "urgent": f"{root}:urgent", "fails": f"{root}:fails",
        "until": f"{root}:stopped_until", "probe": f"{root}:probe",
    }


def _now() -> float:
    return time.time()


_sleep = time.sleep


# ── the turn ───────────────────────────────────────────────────────────────


@contextmanager
def turn(
    base_url: str, *, priority: str = PRIORITY_SYNC, hold_seconds: float,
    policy: ServerPolicy = DEFAULT_POLICY,
) -> Iterator[float]:
    """Hold the server's one turn for one request. Yields the seconds waited.

    Raises ``ServerStopped`` (scheduled calls only) while the safety stop is
    on, ``ServerBusy`` when a scheduled call got no turn in time."""
    client = _redis()
    if client is None:
        yield 0.0
        return
    keys = _keys(base_url)
    try:
        _check_stop(client, keys, priority=priority, policy=policy, hold_seconds=hold_seconds)
    except ServerStopped:
        raise
    except Exception as exc:  # noqa: BLE001 - Redis is best-effort
        _warn("stop check failed", exc)
    if not policy.one_at_a_time:
        yield 0.0
        return
    token = uuid.uuid4().hex
    ttl_ms = int((hold_seconds + HOLD_MARGIN_SECONDS) * 1000)
    started = time.monotonic()
    held = False
    try:
        held = _acquire(client, keys, token, ttl_ms, priority=priority)
    except ServerBusy:
        raise
    except Exception as exc:  # noqa: BLE001
        _warn("could not take a turn", exc)
    waited = time.monotonic() - started
    try:
        yield waited
    finally:
        if held:
            try:
                client.eval(_RELEASE_LUA, 1, keys["lock"], token)
            except Exception as exc:  # noqa: BLE001
                _warn("could not hand the turn back", exc)


def _acquire(client: Any, keys: dict, token: str, ttl_ms: int, *, priority: str) -> bool:
    user = priority == PRIORITY_USER
    poll = POLL_SECONDS_USER if user else POLL_SECONDS_SYNC
    max_wait = MAX_WAIT_SECONDS_USER if user else MAX_WAIT_SECONDS_SYNC
    deadline = time.monotonic() + max_wait
    if user:
        client.incr(keys["urgent"])
        client.expire(keys["urgent"], URGENT_TTL_SECONDS)
    try:
        while True:
            if user or int(client.get(keys["urgent"]) or 0) <= 0:
                if client.set(keys["lock"], token, nx=True, px=ttl_ms):
                    return True
            if time.monotonic() >= deadline:
                if user:
                    logger.warning(
                        "AutoCount server gate: a person's call waited %.0f s for %s; going ahead",
                        max_wait, keys["lock"],
                    )
                    return False
                raise ServerBusy()
            if user:
                client.expire(keys["urgent"], URGENT_TTL_SECONDS)
            _sleep(poll)
    finally:
        if user:
            try:
                left = client.decr(keys["urgent"])
                if left is not None and int(left) <= 0:
                    client.delete(keys["urgent"])
            except Exception as exc:  # noqa: BLE001
                _warn("could not clear the waiting marker", exc)


# ── safety stop ────────────────────────────────────────────────────────────


def _check_stop(client: Any, keys: dict, *, priority: str, policy: ServerPolicy, hold_seconds: float) -> None:
    if policy.stop_after_failures <= 0 or priority == PRIORITY_USER:
        return
    until_raw = client.get(keys["until"])
    if not until_raw:
        return
    until = float(until_raw)
    if _now() < until:
        raise ServerStopped(datetime.fromtimestamp(until, tz=timezone.utc))
    # The stop has run out: exactly one caller makes the test call; the rest
    # wait for its answer (still stopped for them).
    probe_ttl = int(hold_seconds + HOLD_MARGIN_SECONDS)
    if not client.set(keys["probe"], "1", nx=True, ex=probe_ttl):
        raise ServerStopped(datetime.fromtimestamp(_now() + probe_ttl, tz=timezone.utc))


def record_result(base_url: str, *, ok: bool, policy: ServerPolicy = DEFAULT_POLICY) -> Optional[datetime]:
    """Count a request's outcome. Returns the stop's end when this failure
    switched the stop on (or a failed test call switched it on again)."""
    if policy.stop_after_failures <= 0:
        return None
    client = _redis()
    if client is None:
        return None
    keys = _keys(base_url)
    try:
        if ok:
            client.delete(keys["fails"], keys["until"], keys["probe"])
            return None
        was_probe = bool(client.get(keys["probe"]))
        fails = int(client.incr(keys["fails"]))
        client.expire(keys["fails"], max(policy.stop_minutes * 60 * 2, 600))
        if was_probe or fails >= policy.stop_after_failures:
            until = _now() + policy.stop_minutes * 60
            client.set(keys["until"], str(until), ex=policy.stop_minutes * 60 * 6)
            client.delete(keys["probe"])
            logger.warning(
                "AutoCount server %s stopped for %d min after %d failed requests in a row",
                server_key(base_url), policy.stop_minutes, fails,
            )
            return datetime.fromtimestamp(until, tz=timezone.utc)
    except Exception as exc:  # noqa: BLE001
        _warn("could not count the result", exc)
    return None


def stopped_until(base_url: str) -> Optional[datetime]:
    """When the safety stop on this server lifts, ``None`` when it is off."""
    client = _redis()
    if client is None:
        return None
    try:
        raw = client.get(_keys(base_url)["until"])
    except Exception as exc:  # noqa: BLE001
        _warn("could not read the stop", exc)
        return None
    if not raw or _now() >= float(raw):
        return None
    return datetime.fromtimestamp(float(raw), tz=timezone.utc)
