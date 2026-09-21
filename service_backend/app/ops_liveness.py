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
from typing import Dict, Optional, Set, TypedDict

import redis

from app.config import settings

logger = logging.getLogger(__name__)

# Review round 2 (S6) - the control-plane broker round-trip must fail FAST
# against a dead/unreachable broker (never the multi-minute OS-level TCP
# hang a bare socket connect can suffer against a black-holed address).
# ``kombu.Connection``'s own ``connect_timeout`` bounds the connect attempt;
# ``max_retries: 0`` stops kombu retrying a failed connect before it gives up
# and lets the caller's own ``except Exception`` degrade gracefully.
_CONTROL_CONNECT_TIMEOUT_SECONDS = 1.0
_CONTROL_TRANSPORT_OPTIONS = {"max_retries": 0}

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


def consuming_workers_by_queue() -> Dict[str, Set[str]]:
    """`{queue_name: {worker_name, ...}}` for EVERY queue any reachable
    worker currently declares - ONE control-plane round-trip (one `ping()`,
    one `active_queues()`), not one per queue (review round 2, S6: the
    round-1 shape called this once per `KNOWN_QUEUES` entry from the route,
    doubling the broker round-trips for no reason - a caller inspecting N
    queues now costs the SAME one round-trip as inspecting one).

    Bounded so a dead/unreachable broker fails FAST rather than hanging on
    a black-holed TCP connect (`_CONTROL_CONNECT_TIMEOUT_SECONDS` via
    `connection_for_read`, plus the inspect's own request timeout) - see the
    module-level constants. Any error (broker down, no reply, ...) degrades
    to `{}` (every queue reads `alive: False`), never raises - see module
    docstring. Lazy import: `app.workflow_engine.worker` imports
    `KNOWN_QUEUES` from THIS module at module load time, so a top-level
    import here would be circular."""
    from app.workflow_engine.worker import celery_app

    try:
        with celery_app.connection_for_read(
            connect_timeout=_CONTROL_CONNECT_TIMEOUT_SECONDS,
            transport_options=_CONTROL_TRANSPORT_OPTIONS,
        ) as conn:
            inspector = celery_app.control.inspect(
                timeout=_CONTROL_CONNECT_TIMEOUT_SECONDS, connection=conn
            )
            pinged = inspector.ping() or {}
            active = inspector.active_queues() or {}
    except Exception as exc:  # noqa: BLE001 - degrade gracefully, never raise
        logger.warning("ops_liveness control-plane inspect failed: %s", exc)
        return {}
    by_queue: Dict[str, Set[str]] = {}
    for worker_name in pinged:
        for entry in active.get(worker_name) or []:
            qname = entry.get("name")
            if qname:
                by_queue.setdefault(qname, set()).add(worker_name)
    return by_queue


def queue_status(
    queue: str,
    *,
    now: Optional[datetime] = None,
    consuming: Optional[Dict[str, Set[str]]] = None,
) -> QueueStatus:
    """`{"queue", "lastSeen", "stale", "alive"}` for one queue.

    `stale` (the Redis-stamp path, unchanged) means "no free slot OR dead" -
    it is computed against `now` (not just Redis' own TTL) so a caller can
    assert staleness deterministically without waiting on real wall-clock
    time, and it can read fresh even when no worker is currently free to pick
    up NEW work (a busy-but-alive worker still answers `ops.ping`).

    `alive` (review round 1) is the CONTROL PLANE's own, synchronous answer -
    a live Celery `ping()` from a worker that declares this queue among its
    `active_queues()` - independent of whether that worker has happened to
    drain a recent `ops.ping` broker message. A dead Redis (or no stamp ever
    seen) reads `stale: True` with no `lastSeen`, and a dead/unreachable
    broker reads `alive: False`; neither ever raises - degrade gracefully,
    see module docstring.

    `consuming` (review round 2, S6): a caller inspecting MULTIPLE queues in
    one request computes `consuming_workers_by_queue()` ONCE and passes it
    here for every queue, so the control-plane round-trip happens once per
    REQUEST, not once per queue. Omitted (the default), this function
    computes it itself - the single-queue call site keeps working unchanged."""
    current = now or datetime.now(timezone.utc)
    by_queue = consuming if consuming is not None else consuming_workers_by_queue()
    alive = bool(by_queue.get(queue))
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
