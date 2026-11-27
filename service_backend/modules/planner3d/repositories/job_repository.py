"""Planner 3D job persistence: pure SQLAlchemy, tenant-scoped on every staff
read. The worker-side functions take a job id the worker was handed and the
service scopes the follow-up work by that job's own ``tenant_id``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models import (
    DIRECTION_IN,
    DIRECTION_OUT,
    P3Job,
    P3JobFile,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
)

MAX_ATTEMPTS = 3
CLAIM_RETRIES = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── plain reads ─────────────────────────────────────────────────────────────

def get_for_tenant(db: Session, tenant_id: str, job_id: str) -> Optional[P3Job]:
    return (
        db.query(P3Job).filter(P3Job.tenant_id == tenant_id, P3Job.id == job_id).first()
    )


def get_by_id(db: Session, job_id: str) -> Optional[P3Job]:
    """Worker side only: the id was handed out by ``claim``."""
    return db.query(P3Job).filter(P3Job.id == job_id).first()


def list_for_tenant(
    db: Session, tenant_id: str, kind: Optional[str], status: Optional[str]
) -> Tuple[List[P3Job], int]:
    q = db.query(P3Job).filter(P3Job.tenant_id == tenant_id)
    if kind:
        q = q.filter(P3Job.kind == kind)
    if status:
        q = q.filter(P3Job.status == status)
    total = q.count()
    rows = q.order_by(P3Job.created_at.desc(), P3Job.id.desc()).all()
    return rows, total


def files_for_jobs(db: Session, tenant_id: str, job_ids: Sequence[str]) -> List[P3JobFile]:
    if not job_ids:
        return []
    return (
        db.query(P3JobFile)
        .filter(P3JobFile.tenant_id == tenant_id, P3JobFile.job_id.in_(list(job_ids)))
        .order_by(P3JobFile.created_at, P3JobFile.name)
        .all()
    )


def find_file(
    db: Session, tenant_id: str, job_id: str, name: str, direction: Optional[str] = None
) -> Optional[P3JobFile]:
    q = db.query(P3JobFile).filter(
        P3JobFile.tenant_id == tenant_id, P3JobFile.job_id == job_id, P3JobFile.name == name
    )
    if direction:
        return q.filter(P3JobFile.direction == direction).first()
    # a convert job has model.glb in AND out: the result wins
    return q.order_by(P3JobFile.direction.desc()).first()


# ── writes ──────────────────────────────────────────────────────────────────

def add(db: Session, row) -> None:
    db.add(row)
    db.flush()


def delete_file(db: Session, row: P3JobFile) -> None:
    db.delete(row)
    db.flush()


# ── claim + lease ───────────────────────────────────────────────────────────

def requeue_stale(db: Session, lease_minutes: int, failed_out: Optional[List[str]] = None) -> List[str]:
    """Running jobs silent for longer than the lease: attempts + 1, back to
    queued, or failed ``worker_lost`` once the attempts reach the limit.
    Returns the ids that were requeued (their old outputs are now void); the ids
    that failed ``worker_lost`` are appended to ``failed_out`` when given."""
    cutoff = _now() - timedelta(minutes=lease_minutes)
    stale = (
        db.query(P3Job)
        .filter(P3Job.status == STATUS_RUNNING)
        .filter((P3Job.heartbeat_at < cutoff) | ((P3Job.heartbeat_at.is_(None)) & (P3Job.claimed_at < cutoff)))
        .with_for_update(skip_locked=True)
        .all()
    )
    requeued: List[str] = []
    for job in stale:
        attempts = (job.attempts or 0) + 1
        if attempts >= MAX_ATTEMPTS:
            res = db.execute(
                update(P3Job)
                .where(P3Job.id == job.id, P3Job.status == STATUS_RUNNING)
                .values(
                    attempts=attempts,
                    status=STATUS_FAILED,
                    error_code="worker_lost",
                    error_message="The worker stopped responding too many times.",
                    finished_at=_now(),
                )
            )
            if res.rowcount == 1 and failed_out is not None:
                failed_out.append(job.id)
        else:
            res = db.execute(
                update(P3Job)
                .where(P3Job.id == job.id, P3Job.status == STATUS_RUNNING)
                .values(
                    attempts=attempts,
                    status=STATUS_QUEUED,
                    worker_name=None,
                    claimed_at=None,
                    heartbeat_at=None,
                    progress=0,
                )
            )
            if res.rowcount == 1:
                requeued.append(job.id)
    db.flush()
    return requeued


def claim_oldest(db: Session, kinds: Sequence[str], worker_name: str) -> Optional[P3Job]:
    """Oldest queued job of the wanted kinds: ``FOR UPDATE SKIP LOCKED`` to find
    it, then a guarded UPDATE (status must still be queued, rowcount 1) so two
    workers can never both win it."""
    for _ in range(CLAIM_RETRIES):
        cand = (
            db.query(P3Job.id)
            .filter(P3Job.status == STATUS_QUEUED, P3Job.kind.in_(list(kinds)))
            .order_by(P3Job.created_at, P3Job.id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if cand is None:
            return None
        now = _now()
        res = db.execute(
            update(P3Job)
            .where(P3Job.id == cand[0], P3Job.status == STATUS_QUEUED)
            .values(
                status=STATUS_RUNNING,
                worker_name=worker_name,
                claimed_at=now,
                heartbeat_at=now,
                started_at=now,
            )
        )
        if res.rowcount == 1:
            db.flush()
            db.expire_all()
            return get_by_id(db, cand[0])
    return None


# ── guarded transitions ─────────────────────────────────────────────────────

def heartbeat(db: Session, job_id: str, worker_name: str, progress: Optional[int]) -> bool:
    values = {"heartbeat_at": _now()}
    if progress is not None:
        values["progress"] = progress
    res = db.execute(
        update(P3Job)
        .where(P3Job.id == job_id, P3Job.status == STATUS_RUNNING, P3Job.worker_name == worker_name)
        .values(**values)
    )
    return res.rowcount == 1


def finish(db: Session, job_id: str, worker_name: str, **values) -> bool:
    res = db.execute(
        update(P3Job)
        .where(P3Job.id == job_id, P3Job.status == STATUS_RUNNING, P3Job.worker_name == worker_name)
        .values(finished_at=_now(), **values)
    )
    db.flush()
    return res.rowcount == 1


def cancel(db: Session, tenant_id: str, job_id: str) -> bool:
    res = db.execute(
        update(P3Job)
        .where(
            P3Job.id == job_id,
            P3Job.tenant_id == tenant_id,
            P3Job.status.in_([STATUS_QUEUED, STATUS_RUNNING]),
        )
        .values(status=STATUS_CANCELLED, finished_at=_now())
    )
    db.flush()
    return res.rowcount == 1


def mark_approved(db: Session, tenant_id: str, job_id: str, candidate: str) -> bool:
    res = db.execute(
        update(P3Job)
        .where(
            P3Job.id == job_id,
            P3Job.tenant_id == tenant_id,
            P3Job.approved_candidate.is_(None),
        )
        .values(approved_candidate=candidate)
    )
    db.flush()
    return res.rowcount == 1


def out_files(db: Session, tenant_id: str, job_id: str) -> List[P3JobFile]:
    return (
        db.query(P3JobFile)
        .filter(
            P3JobFile.tenant_id == tenant_id,
            P3JobFile.job_id == job_id,
            P3JobFile.direction == DIRECTION_OUT,
        )
        .all()
    )


def in_files(db: Session, tenant_id: str, job_id: str) -> List[P3JobFile]:
    return (
        db.query(P3JobFile)
        .filter(
            P3JobFile.tenant_id == tenant_id,
            P3JobFile.job_id == job_id,
            P3JobFile.direction == DIRECTION_IN,
        )
        .order_by(P3JobFile.created_at, P3JobFile.name)
        .all()
    )
