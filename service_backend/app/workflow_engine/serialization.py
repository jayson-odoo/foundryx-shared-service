"""Durable keyed serialization for workflow runs.

Postgres run rows are the queue. Redis only admits one drainer for a
tenant/workflow/correlation scope and Celery only carries idempotent wakeups.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Protocol

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.workflow import RUN_FAILED, RUN_PENDING, RUN_RUNNING, WorkflowRun

logger = logging.getLogger("foundryx.workflows.serialization")


class SerializedCoordinationUnavailable(RuntimeError):
    """Redis could not safely coordinate a serialized scope."""


class LeaseClient(Protocol):
    def acquire(self, key: str, token: str, ttl_seconds: int) -> bool: ...

    def renew(self, key: str, token: str, ttl_seconds: int) -> bool: ...

    def release(self, key: str, token: str) -> bool: ...


class RedisLeaseClient:
    """Token-owned Redis lease. Renew/release never affect a newer owner."""

    _RENEW = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('expire', KEYS[1], ARGV[2])
    end
    return 0
    """
    _RELEASE = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('del', KEYS[1])
    end
    return 0
    """

    def __init__(self, client: Any = None):
        if client is None:
            from redis import Redis

            from app.config import settings

            client = Redis.from_url(settings.redis_url, decode_responses=True)
        self.client = client

    def acquire(self, key: str, token: str, ttl_seconds: int) -> bool:
        return bool(self.client.set(key, token, nx=True, ex=ttl_seconds))

    def renew(self, key: str, token: str, ttl_seconds: int) -> bool:
        return bool(self.client.eval(self._RENEW, 1, key, token, ttl_seconds))

    def release(self, key: str, token: str) -> bool:
        return bool(self.client.eval(self._RELEASE, 1, key, token))


class LocalLeaseClient:
    """Process-local eager-mode seam with the same token ownership contract."""

    def __init__(self):
        self._guard = threading.Lock()
        self._owners: dict[str, str] = {}

    def acquire(self, key: str, token: str, ttl_seconds: int) -> bool:
        del ttl_seconds
        with self._guard:
            if key in self._owners:
                return False
            self._owners[key] = token
            return True

    def renew(self, key: str, token: str, ttl_seconds: int) -> bool:
        del ttl_seconds
        with self._guard:
            return self._owners.get(key) == token

    def release(self, key: str, token: str) -> bool:
        with self._guard:
            if self._owners.get(key) != token:
                return False
            self._owners.pop(key, None)
            return True


_LOCAL_LEASES = LocalLeaseClient()


def correlation_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def assign_run_correlation(run: WorkflowRun) -> None:
    """Resolve once before the run is persisted; never recompute on retry."""
    from app.workflow_engine.executor import _ctx_from_payload, resolve_correlation_key
    from app.workflow_engine.schemas import parse_definition

    doc = parse_definition(run.definition_snapshot_json or {})
    key = resolve_correlation_key(doc, _ctx_from_payload(run.trigger_payload_json or {}))
    run.correlation_key = key
    run.correlation_key_digest = correlation_digest(key) if key is not None else None


def _lease_key(tenant_id: str, workflow_id: str, digest: str) -> str:
    return f"foundryx:workflow:serialized:{tenant_id}:{workflow_id}:{digest}"


def touch_run_heartbeat(bind: Any, run_id: str, now: Optional[datetime] = None) -> bool:
    """Stamp ``heartbeat_at`` on a RUNNING row in its OWN short transaction.

    Runs on the lease-renewal thread, so it must never wait on the executor's
    transaction: on Postgres the row is skipped (``SKIP LOCKED``) while the
    executor holds it - a blocked heartbeat would starve the lease renewal.
    Returns True when a row was stamped."""
    table = WorkflowRun.__table__
    target = select(table.c.id).where(table.c.id == run_id, table.c.status == RUN_RUNNING)
    if bind.dialect.name == "postgresql":
        target = target.with_for_update(skip_locked=True)
    stmt = (
        update(table)
        .where(table.c.id == target.scalar_subquery())
        .values(heartbeat_at=now or datetime.now(timezone.utc))
    )
    with bind.begin() as conn:
        return conn.execute(stmt).rowcount > 0


class _LeaseHeartbeat:
    """Renews the Redis lease AND, while a run executes, its DB heartbeat."""

    def __init__(
        self,
        client: LeaseClient,
        key: str,
        token: str,
        ttl_seconds: int,
        touch: Optional[Callable[[str], Any]] = None,
    ):
        self.client = client
        self.key = key
        self.token = token
        self.ttl_seconds = ttl_seconds
        self.touch = touch
        self.current_run_id: Optional[str] = None
        self.lost = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="workflow-lease-renewal",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1)

    def _run(self) -> None:
        interval = max(1.0, self.ttl_seconds / 3)
        while not self._stop.wait(interval):
            try:
                if not self.client.renew(
                    self.key,
                    self.token,
                    self.ttl_seconds,
                ):
                    self.lost.set()
                    return
            except Exception:  # noqa: BLE001
                self.lost.set()
                return
            run_id = self.current_run_id
            if run_id and self.touch is not None:
                try:
                    self.touch(run_id)
                except Exception:  # noqa: BLE001 - never lose the lease over a heartbeat write
                    logger.warning("workflow run %s heartbeat write failed", run_id, exc_info=True)


def _live_running_run_id(
    db: Session,
    tenant_id: str,
    workflow_id: str,
    digest: str,
    stale_after: timedelta,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """A RUNNING row in this scope whose heartbeat is still fresh - another
    worker is executing it (its lease may have expired while it works).
    Advancing past it would let a later same-key run overtake (AC-SAR-37)."""
    cutoff = (now or datetime.now(timezone.utc)) - stale_after
    row = (
        db.query(WorkflowRun.id)
        .filter(
            WorkflowRun.tenant_id == tenant_id,
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.correlation_key_digest == digest,
            WorkflowRun.status == RUN_RUNNING,
            func.coalesce(WorkflowRun.heartbeat_at, WorkflowRun.started_at, WorkflowRun.created_at) > cutoff,
        )
        .first()
    )
    return row[0] if row is not None else None


def _oldest_pending_run_id(
    db: Session,
    tenant_id: str,
    workflow_id: str,
    digest: str,
) -> Optional[str]:
    row = (
        db.query(WorkflowRun.id)
        .filter(
            WorkflowRun.tenant_id == tenant_id,
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.correlation_key_digest == digest,
            WorkflowRun.status == RUN_PENDING,
        )
        .order_by(WorkflowRun.created_at.asc(), WorkflowRun.id.asc())
        .first()
    )
    return row[0] if row is not None else None


def _mark_crashed(db: Session, run_id: str) -> None:
    # RUNNING included: an action that committed mid-run leaves the row
    # RUNNING after the rollback, and this process KNOWS the run is dead.
    run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if run is None or run.status not in (RUN_PENDING, RUN_RUNNING):
        return
    run.status = RUN_FAILED
    run.error = "Run crashed unexpectedly."
    run.finished_at = datetime.now(timezone.utc)
    db.commit()


def drain_serialized_runs(
    db: Session,
    tenant_id: str,
    workflow_id: str,
    digest: str,
    *,
    lease_client: Optional[LeaseClient] = None,
    execute: Optional[Callable[[Session, str], WorkflowRun]] = None,
    ttl_seconds: Optional[int] = None,
    touch: Optional[Callable[[str], Any]] = None,
    stale_after: Optional[timedelta] = None,
) -> dict[str, Any]:
    """Drain one durable FIFO scope. Duplicate wakeups lose the lease.

    ``touch`` stamps the executing run's DB heartbeat on every lease renewal
    (default: :func:`touch_run_heartbeat` on this session's engine);
    ``stale_after`` is how old a RUNNING heartbeat may be before the row no
    longer blocks the queue (default: the lease TTL - the reaper's threshold)."""
    from app.config import settings
    from app.workflow_engine.executor import run_workflow

    client = lease_client or RedisLeaseClient()
    execute_run = execute or run_workflow
    ttl = ttl_seconds or settings.workflow_serialized_lease_seconds
    stale = stale_after or timedelta(seconds=ttl)
    touch_run = touch or (lambda run_id: touch_run_heartbeat(db.get_bind(), run_id))
    key = _lease_key(tenant_id, workflow_id, digest)
    token = str(uuid.uuid4())
    try:
        admitted = client.acquire(key, token, ttl)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise SerializedCoordinationUnavailable(
            "Redis is unavailable; serialized workflow remains Pending."
        ) from exc
    if not admitted:
        return {"admitted": False, "drained": 0}

    heartbeat = _LeaseHeartbeat(client, key, token, ttl, touch=touch_run)
    heartbeat.start()
    drained = 0
    last_run_id: Optional[str] = None
    try:
        while not heartbeat.lost.is_set():
            blocker = _live_running_run_id(db, tenant_id, workflow_id, digest, stale)
            if blocker is not None:
                # Another worker still executes this key (its lease expired
                # but its heartbeat is fresh). Never overtake it; the reaper
                # wakes the scope once the heartbeat goes stale.
                logger.warning("serialized scope blocked by live run %s", blocker)
                return {"admitted": True, "drained": drained, "blocked": blocker}
            run_id = _oldest_pending_run_id(db, tenant_id, workflow_id, digest)
            if run_id is None:
                break
            if run_id == last_run_id:
                # The executor returned without moving the run off Pending.
                # Never spin on it: leave it for the beat backstop and log.
                logger.error("serialized workflow run %s did not leave Pending", run_id)
                return {"admitted": True, "drained": drained, "stalled": run_id}
            last_run_id = run_id
            heartbeat.current_run_id = run_id
            try:
                execute_run(db, run_id)
            except Exception:  # noqa: BLE001
                # Mirror the parallel task: an in-process crash marks THIS run
                # failed (Pending OR a mid-run-committed Running) so a poison
                # run cannot block its key forever. A hard process death never
                # reaches here: an uncommitted claim rolls back to Pending and
                # the beat backstop re-drives; a committed RUNNING row keeps
                # blocking until its heartbeat goes stale, then the reaper
                # fails it and wakes the scope.
                logger.exception("serialized workflow run %s crashed", run_id)
                db.rollback()
                _mark_crashed(db, run_id)
            finally:
                heartbeat.current_run_id = None
            drained += 1
        if heartbeat.lost.is_set():
            raise SerializedCoordinationUnavailable(
                "Redis lease was lost; remaining serialized workflows stay Pending."
            )
        return {"admitted": True, "drained": drained}
    finally:
        heartbeat.stop()
        try:
            client.release(key, token)
        except Exception:  # noqa: BLE001
            logger.exception("serialized workflow lease release failed")


def dispatch_persisted_run(
    db: Session,
    run: WorkflowRun,
    *,
    eager: Optional[bool] = None,
    direct_wake: Optional[Callable[[str], Any]] = None,
    serialized_wake: Optional[Callable[[str, str, str], Any]] = None,
) -> None:
    """Route a committed run without changing its durable Pending state."""
    from app.config import settings

    is_eager = settings.celery_task_always_eager if eager is None else eager
    if run.correlation_key_digest is None:
        if is_eager:
            from app.workflow_engine.executor import run_workflow

            run_workflow(db, run.id)
            return
        if direct_wake is None:
            from app.workflow_engine.worker import run_workflow_task

            direct_wake = run_workflow_task.delay
        direct_wake(run.id)
        return

    if is_eager:
        drain_serialized_runs(
            db,
            run.tenant_id,
            run.workflow_id,
            run.correlation_key_digest,
            lease_client=_LOCAL_LEASES,
        )
        return
    if serialized_wake is None:
        from app.workflow_engine.worker import wake_serialized_task

        serialized_wake = wake_serialized_task.delay
    serialized_wake(run.tenant_id, run.workflow_id, run.correlation_key_digest)


def reap_stale_running_serialized_runs(
    db: Session,
    *,
    now: Optional[datetime] = None,
    stale_after: Optional[timedelta] = None,
) -> list[tuple[str, str, str]]:
    """Fail RUNNING serialized rows whose worker stopped heart-beating (hard
    process death after a mid-run commit). Returns the scopes to wake."""
    from app.config import settings

    current = now or datetime.now(timezone.utc)
    stale = stale_after or timedelta(seconds=settings.workflow_serialized_lease_seconds)
    rows = (
        db.query(WorkflowRun)
        .filter(
            WorkflowRun.status == RUN_RUNNING,
            WorkflowRun.correlation_key_digest.isnot(None),
            func.coalesce(WorkflowRun.heartbeat_at, WorkflowRun.started_at, WorkflowRun.created_at)
            <= current - stale,
        )
        .all()
    )
    scopes: list[tuple[str, str, str]] = []
    for row in rows:
        row.status = RUN_FAILED
        row.error = "Run lost its worker (heartbeat stopped)."
        row.finished_at = current
        scope = (row.tenant_id, row.workflow_id, row.correlation_key_digest)
        if scope not in scopes:
            scopes.append(scope)
        logger.error("serialized workflow run %s reaped: heartbeat stale", row.id)
    if rows:
        db.commit()
    return scopes


def redrive_pending_serialized_runs(
    db: Session,
    *,
    now: Optional[datetime] = None,
    minimum_age: Optional[timedelta] = None,
    wake: Optional[Callable[[str, str, str], Any]] = None,
    stale_after: Optional[timedelta] = None,
) -> int:
    """Beat backstop: reap dead RUNNING rows, then emit one idempotent wakeup
    per stranded durable scope (a reaped scope is woken even when its pending
    rows are younger than ``minimum_age``)."""
    from app.config import settings

    current = now or datetime.now(timezone.utc)
    age = minimum_age or timedelta(
        seconds=settings.workflow_serialized_recovery_age_seconds
    )
    scopes = reap_stale_running_serialized_runs(db, now=current, stale_after=stale_after)
    for scope in (
        db.query(
            WorkflowRun.tenant_id,
            WorkflowRun.workflow_id,
            WorkflowRun.correlation_key_digest,
        )
        .filter(
            WorkflowRun.status == RUN_PENDING,
            WorkflowRun.correlation_key_digest.isnot(None),
            WorkflowRun.created_at <= current - age,
        )
        .distinct()
        .all()
    ):
        if tuple(scope) not in scopes:
            scopes.append(tuple(scope))
    if wake is None:
        from app.workflow_engine.worker import wake_serialized_task

        wake = wake_serialized_task.delay
    emitted = 0
    for tenant_id, workflow_id, digest in scopes:
        try:
            wake(tenant_id, workflow_id, digest)
            emitted += 1
        except Exception:  # noqa: BLE001
            logger.exception("serialized workflow recovery wakeup failed")
    return emitted
