"""Per-queue Celery worker liveness (sprint-5/11 S1, AC-11-86).

During the 2026-09-20/21 incident beat itself stayed healthy the whole 8
hours a wedged worker was starved - a beat-side heartbeat would have
reported everything fine (plan D20). The signal instead has to be stamped
by the CONSUMING worker, per queue: beat's `ops.ping` task is published onto
EACH known queue every 60s (`app/workflow_engine/worker.py`), and whichever
worker actually drains that queue stamps a Redis key here. A queue with no
recent stamp is a wedged (or simply absent) consumer, visible within one TTL
instead of discovered by an operator hours later.

Mirrors `modules/omnichannel/services/realtime.py`'s client seam exactly
(lazy real `redis.Redis`, `set_client` test seam) and its degrade-gracefully
stance: a dead/absent Redis must never crash the API or a worker tick - a
liveness READ is a nicety, not a source of truth for anything else.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, TypedDict

import redis

from app.config import settings

logger = logging.getLogger(__name__)

# The two queues this platform routes tasks onto today (sprint-5/11 S1):
# the shared `workflow` queue (every beat tick, `workflows.run_workflow`, ...)
# and the new dedicated `jobs` queue (`jobs.run` only). A future queue (e.g.
# `stt`/`bots`, meetings) adds its name here when it needs this same signal.
KNOWN_QUEUES = ("workflow", "jobs")

_TTL_SECONDS = 300  # AC-11-86: a wedged worker is visible within one TTL.

_client: Optional["redis.Redis"] = None


class QueueStatus(TypedDict):
    queue: str
    lastSeen: Optional[str]
    stale: bool
    alive: bool


def _key(queue: str) -> str:
    return f"ops:liveness:{queue}"


def _get_client() -> "redis.Redis":
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def set_client(client: Optional["redis.Redis"]) -> None:
    """Test seam - inject a fakeredis client (None resets to lazy real client)."""
    global _client
    _client = client


def stamp_liveness(queue: str, *, now: Optional[datetime] = None) -> None:
    """Best-effort: the consuming worker calls this from the `ops.ping` task
    body. A dead Redis never fails the tick - see module docstring."""
    current = now or datetime.now(timezone.utc)
    try:
        _get_client().set(_key(queue), current.isoformat(), ex=_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - see module docstring
        logger.warning("ops_liveness stamp failed for queue %s: %s", queue, exc)


def _workers_consuming(queue: str) -> set:
    """Celery worker names that BOTH answered a live control-plane ping AND
    declare `queue` among their `active_queues()` right now (review round 1,
    S2). This is a SEPARATE signal from the Redis stamp above: the stamp
    answers "did a worker consume an `ops.ping` off this queue in the last
    300s" (routing-through-the-broker evidence); this answers "does a
    reachable worker process claim this queue at all" (the control plane's
    own, synchronous answer). Lazy import: `app.workflow_engine.worker`
    imports `KNOWN_QUEUES` from THIS module at module load time, so a
    top-level import here would be circular. Broker unreachable, no worker
    replying, or any control-plane error -> empty set (never raise - see
    module docstring)."""
    from app.workflow_engine.worker import celery_app

    try:
        inspector = celery_app.control.inspect(timeout=1.0)
        pinged = inspector.ping() or {}
        active = inspector.active_queues() or {}
    except Exception as exc:  # noqa: BLE001 - degrade gracefully, never raise
        logger.warning("ops_liveness control-plane inspect failed for queue %s: %s", queue, exc)
        return set()
    consuming = set()
    for worker_name in pinged:
        for entry in active.get(worker_name) or []:
            if entry.get("name") == queue:
                consuming.add(worker_name)
                break
    return consuming


def queue_status(queue: str, *, now: Optional[datetime] = None) -> QueueStatus:
    """`{"queue", "lastSeen", "stale", "alive"}` for one queue.

    `stale` (the Redis-stamp path, unchanged) means "no free slot OR dead" -
    it is computed against `now` (not just Redis' own TTL) so a caller can
    assert staleness deterministically without waiting on real wall-clock
    time, and it can read fresh even when no worker is currently free to pick
    up NEW work (a busy-but-alive worker still answers `ops.ping`).

    `alive` (new, review round 1) is the CONTROL PLANE's own, synchronous
    answer - a live Celery `ping()` from a worker that declares this queue
    among its `active_queues()` - independent of whether that worker has
    happened to drain a recent `ops.ping` broker message. A dead Redis (or
    no stamp ever seen) reads `stale: True` with no `lastSeen`, and a dead/
    unreachable broker reads `alive: False`; neither ever raises - degrade
    gracefully, see module docstring."""
    current = now or datetime.now(timezone.utc)
    alive = bool(_workers_consuming(queue))
    try:
        raw = _get_client().get(_key(queue))
    except Exception as exc:  # noqa: BLE001 - see module docstring
        logger.warning("ops_liveness read failed for queue %s: %s", queue, exc)
        raw = None
    if not raw:
        return {"queue": queue, "lastSeen": None, "stale": True, "alive": alive}
    try:
        stamped = datetime.fromisoformat(raw)
    except ValueError:
        return {"queue": queue, "lastSeen": None, "stale": True, "alive": alive}
    stale = (current - stamped) > timedelta(seconds=_TTL_SECONDS)
    return {"queue": queue, "lastSeen": raw, "stale": stale, "alive": alive}
