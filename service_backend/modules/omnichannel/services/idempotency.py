"""Idempotency dedup for the public send API (plan sprint-1/01 AC-01-18).

Dedup is scoped to ``workspace + Idempotency-Key`` with a 24h TTL. Primary
store is Redis (survives across API replicas); if Redis is unreachable the store
degrades to a process-local dict so tests/dev need no Redis. A ``set_store``
seam lets tests inject a deterministic in-memory store.
"""
import logging
import threading
import time
import uuid
from typing import Dict, NamedTuple, Optional

from app.config import settings

_TTL_SECONDS = 24 * 60 * 60
# A PENDING reservation lives only this long. The route ends at enqueue in prod
# (the Meta send runs in the worker), so the hold must outlast the route's own
# steps (media fetch total limit plus storage save, DB and enqueue): it is
# MEDIA_FETCH_TOTAL_SECONDS (60 s) plus a margin, and public_gateway_service
# asserts that relation at import (importing the constant here would be a cycle).
# Trade-off: a request whose final step was lost can be sent again after the hold,
# where before it was refused for a day.
_PENDING_TTL_SECONDS = 300
# Bounded socket waits so an unreachable Redis falls back to memory quickly.
_SOCKET_CONNECT_TIMEOUT_SECONDS = 1.0
_SOCKET_READ_TIMEOUT_SECONDS = 1.0
# Sentinel stored while a send is in-flight - a second request seeing it knows a
# concurrent identical send is running (returns 409 rather than double-sending).
PENDING = "__pending__"
_PENDING_PREFIX = PENDING + ":"

logger = logging.getLogger(__name__)

# Compare-and-set / compare-and-delete: act only while the slot still holds this
# request's own pending mark.
_FINALIZE_LUA = (
    "if redis.call('GET', KEYS[1]) == ARGV[1] then "
    "redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[3])) return 1 end return 0"
)
_RELEASE_LUA = (
    "if redis.call('GET', KEYS[1]) == ARGV[1] then "
    "redis.call('DEL', KEYS[1]) return 1 end return 0"
)


class Reservation(NamedTuple):
    """``token`` is owned by the requester that claimed the slot (empty otherwise);
    ``existing`` is None when the slot was claimed, else a message id or PENDING."""

    token: str
    existing: Optional[str]


def is_pending(value: Optional[str]) -> bool:
    return value is not None and (value == PENDING or value.startswith(_PENDING_PREFIX))


def _pending_mark(token: str) -> str:
    return _PENDING_PREFIX + token


def _public(value: Optional[str]) -> Optional[str]:
    """A pending mark is shown to callers as plain PENDING (never the token)."""
    return PENDING if is_pending(value) else value


def _key(workspace_id: str, idem_key: str) -> str:
    return f"omnichannel:idem:{workspace_id}:{idem_key}"


class IdempotencyStore:
    """Redis-first with a per-process in-memory fallback.

    Reserve-before-send: ``reserve`` atomically claims the (workspace, key) slot
    (SET NX a PENDING sentinel) so two concurrent identical requests can't both
    send; the winner ``finalize``s with the real message id, or ``release``s the
    slot on failure so a legitimate retry can proceed.
    """

    def __init__(self) -> None:
        self._memory: Dict[str, str] = {}
        # monotonic expiry of PENDING entries held in memory
        self._pending_expiry: Dict[str, float] = {}
        self._memory_lock = threading.Lock()

    def _client(self):  # noqa: ANN202
        try:
            import redis

            return redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=_SOCKET_CONNECT_TIMEOUT_SECONDS,
                socket_timeout=_SOCKET_READ_TIMEOUT_SECONDS,
            )
        except Exception:  # noqa: BLE001 - any failure → memory fallback
            return None

    def lookup(self, workspace_id: str, idem_key: str) -> Optional[str]:
        k = _key(workspace_id, idem_key)
        client = self._client()
        if client is not None:
            try:
                return _public(client.get(k))
            except Exception:  # noqa: BLE001
                pass
        with self._memory_lock:
            return _public(self._memory_get(k))

    def _memory_get(self, k: str) -> Optional[str]:
        """Caller holds ``_memory_lock``. An expired PENDING reads as absent."""
        value = self._memory.get(k)
        if is_pending(value) and self._pending_expiry.get(k, 0.0) <= time.monotonic():
            self._memory.pop(k, None)
            self._pending_expiry.pop(k, None)
            return None
        return value

    def reserve(self, workspace_id: str, idem_key: str) -> Reservation:
        """Atomically claim the slot. ``existing`` is None if WE claimed it (caller
        proceeds to send, holding ``token``); otherwise the current stored value - a
        real message id (completed) or PENDING (a concurrent send is in-flight)."""
        k = _key(workspace_id, idem_key)
        token = uuid.uuid4().hex
        client = self._client()
        if client is not None:
            try:
                if client.set(k, _pending_mark(token), ex=_PENDING_TTL_SECONDS, nx=True):
                    return Reservation(token, None)
                # Expired between the SET and the GET: refuse this once, retry works.
                return Reservation("", _public(client.get(k)) or PENDING)
            except Exception:  # noqa: BLE001 - fall through to memory
                pass
        with self._memory_lock:
            current = self._memory_get(k)
            if current is not None:
                return Reservation("", _public(current))
            self._memory[k] = _pending_mark(token)
            self._pending_expiry[k] = time.monotonic() + _PENDING_TTL_SECONDS
            return Reservation(token, None)

    def finalize(self, workspace_id: str, idem_key: str, message_id: str, token: str) -> None:
        """Overwrite THIS request's pending mark with the real message id (24 h TTL);
        a no-op if the slot no longer holds the mark."""
        k = _key(workspace_id, idem_key)
        client = self._client()
        if client is not None:
            try:
                client.eval(_FINALIZE_LUA, 1, k, _pending_mark(token), message_id, _TTL_SECONDS)
                return
            except Exception:  # noqa: BLE001
                logger.warning("idempotency store unreachable during finalize; falling back to process memory")
        with self._memory_lock:
            if self._memory_get(k) == _pending_mark(token):
                self._memory[k] = message_id
                self._pending_expiry.pop(k, None)

    def release(self, workspace_id: str, idem_key: str, token: str) -> None:
        """Drop THIS request's reservation (send failed) so a retry can re-claim it;
        never touches a finalized id or a newer request's reservation."""
        k = _key(workspace_id, idem_key)
        client = self._client()
        if client is not None:
            try:
                client.eval(_RELEASE_LUA, 1, k, _pending_mark(token))
                return
            except Exception:  # noqa: BLE001
                logger.warning("idempotency store unreachable during release; falling back to process memory")
        with self._memory_lock:
            if self._memory.get(k) == _pending_mark(token):
                self._memory.pop(k, None)
                self._pending_expiry.pop(k, None)


class MemoryIdempotencyStore(IdempotencyStore):
    """Redis-free variant - always uses the in-memory dict (tests/CI)."""

    def _client(self):  # noqa: ANN202
        return None


_store: Optional[IdempotencyStore] = None


def get_store() -> IdempotencyStore:
    global _store
    if _store is None:
        _store = IdempotencyStore()
    return _store


def set_store(store: IdempotencyStore) -> None:
    """Test seam - inject a fresh/in-memory store."""
    global _store
    _store = store
