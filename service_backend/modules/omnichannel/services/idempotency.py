"""Idempotency dedup for the public send API (plan sprint-1/01 AC-01-18).

Dedup is scoped to ``workspace + Idempotency-Key`` with a 24h TTL. Primary
store is Redis (survives across API replicas); if Redis is unreachable the store
degrades to a process-local dict so tests/dev need no Redis. A ``set_store``
seam lets tests inject a deterministic in-memory store.
"""
from typing import Dict, Optional

from app.config import settings

_TTL_SECONDS = 24 * 60 * 60
# Sentinel stored while a send is in-flight - a second request seeing it knows a
# concurrent identical send is running (returns 409 rather than double-sending).
PENDING = "__pending__"


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

    def _client(self):  # noqa: ANN202
        try:
            import redis

            return redis.Redis.from_url(settings.redis_url, decode_responses=True)
        except Exception:  # noqa: BLE001 - any failure → memory fallback
            return None

    def lookup(self, workspace_id: str, idem_key: str) -> Optional[str]:
        k = _key(workspace_id, idem_key)
        client = self._client()
        if client is not None:
            try:
                return client.get(k)
            except Exception:  # noqa: BLE001
                pass
        return self._memory.get(k)

    def reserve(self, workspace_id: str, idem_key: str) -> Optional[str]:
        """Atomically claim the slot. Returns None if WE claimed it (caller
        proceeds to send); otherwise the current stored value - a real message id
        (completed) or PENDING (a concurrent send is in-flight)."""
        k = _key(workspace_id, idem_key)
        client = self._client()
        if client is not None:
            try:
                if client.set(k, PENDING, ex=_TTL_SECONDS, nx=True):
                    return None
                return client.get(k)
            except Exception:  # noqa: BLE001 - fall through to memory
                pass
        if k in self._memory:
            return self._memory[k]
        self._memory[k] = PENDING
        return None

    def finalize(self, workspace_id: str, idem_key: str, message_id: str) -> None:
        """Overwrite the PENDING sentinel with the real message id (keeps TTL)."""
        k = _key(workspace_id, idem_key)
        client = self._client()
        if client is not None:
            try:
                client.set(k, message_id, ex=_TTL_SECONDS)
                return
            except Exception:  # noqa: BLE001
                pass
        self._memory[k] = message_id

    def release(self, workspace_id: str, idem_key: str) -> None:
        """Drop the reservation (send failed) so a later retry can re-claim it -
        but only if it's still PENDING (never clobber a finalized id)."""
        k = _key(workspace_id, idem_key)
        client = self._client()
        if client is not None:
            try:
                # Best-effort compare-and-delete; a plain DEL is acceptable since
                # only the in-flight owner calls release before finalize.
                if client.get(k) == PENDING:
                    client.delete(k)
                return
            except Exception:  # noqa: BLE001
                pass
        if self._memory.get(k) == PENDING:
            self._memory.pop(k, None)


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
