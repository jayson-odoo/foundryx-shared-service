"""Idempotency dedup for the public send API (plan sprint-1/01 AC-01-18).

Dedup is scoped to ``workspace + Idempotency-Key`` with a 24h TTL. Primary
store is Redis (survives across API replicas); if Redis is unreachable the store
degrades to a process-local dict so tests/dev need no Redis. A ``set_store``
seam lets tests inject a deterministic in-memory store.
"""
from typing import Dict, Optional

from app.config import settings

_TTL_SECONDS = 24 * 60 * 60


def _key(workspace_id: str, idem_key: str) -> str:
    return f"omnichannel:idem:{workspace_id}:{idem_key}"


class IdempotencyStore:
    """Redis-first with a per-process in-memory fallback."""

    def __init__(self) -> None:
        self._memory: Dict[str, str] = {}

    def _client(self):  # noqa: ANN202
        try:
            import redis

            return redis.Redis.from_url(settings.redis_url, decode_responses=True)
        except Exception:  # noqa: BLE001 — any failure → memory fallback
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

    def remember(self, workspace_id: str, idem_key: str, message_id: str) -> None:
        k = _key(workspace_id, idem_key)
        client = self._client()
        if client is not None:
            try:
                client.set(k, message_id, ex=_TTL_SECONDS, nx=True)
                return
            except Exception:  # noqa: BLE001
                pass
        self._memory.setdefault(k, message_id)


class MemoryIdempotencyStore(IdempotencyStore):
    """Redis-free variant — always uses the in-memory dict (tests/CI)."""

    def _client(self):  # noqa: ANN202
        return None


_store: Optional[IdempotencyStore] = None


def get_store() -> IdempotencyStore:
    global _store
    if _store is None:
        _store = IdempotencyStore()
    return _store


def set_store(store: IdempotencyStore) -> None:
    """Test seam — inject a fresh/in-memory store."""
    global _store
    _store = store
