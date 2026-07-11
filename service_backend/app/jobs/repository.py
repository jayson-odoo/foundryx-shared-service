"""Background-job repository (sprint-4/10) — pure SQLAlchemy, tenant-scoped."""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.background_job import (
    JOB_RUNNING,
    JOB_TERMINAL_STATUSES,
    BackgroundJob,
)


class BackgroundJobRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, job: BackgroundJob) -> BackgroundJob:
        self.db.add(job)
        self.db.flush()
        return job

    def get(self, tenant_id: str, job_id: str) -> Optional[BackgroundJob]:
        return (
            self.db.query(BackgroundJob)
            .filter(BackgroundJob.tenant_id == tenant_id, BackgroundJob.id == job_id)
            .first()
        )

    def get_unscoped(self, job_id: str) -> Optional[BackgroundJob]:
        """For the worker — it re-scopes inside the job's tenant."""
        return self.db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()

    def list(
        self,
        tenant_id: str,
        *,
        job_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 0,
        page_size: int = 25,
    ) -> Tuple[List[BackgroundJob], int]:
        q = self.db.query(BackgroundJob).filter(BackgroundJob.tenant_id == tenant_id)
        if job_type:
            q = q.filter(BackgroundJob.type == job_type)
        if status:
            q = q.filter(BackgroundJob.status == status)
        total = q.count()
        rows = (
            q.order_by(BackgroundJob.created_at.desc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total

    def claim(self, job_id: str, from_status: str) -> bool:
        """Atomic status-claim (the import-engine double-commit guard):
        ``UPDATE … SET status='running', started_at=now WHERE id=? AND status=?``.
        0 rows updated = another worker already claimed it → exactly-once."""
        updated = (
            self.db.query(BackgroundJob)
            .filter(BackgroundJob.id == job_id, BackgroundJob.status == from_status)
            .update(
                {
                    BackgroundJob.status: JOB_RUNNING,
                    BackgroundJob.started_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
        )
        self.db.flush()
        return updated == 1

    def prune_terminal(self, *, older_than: datetime) -> int:
        """Delete TERMINAL jobs finished before ``older_than``. Running / pending
        / needs_review jobs are never touched."""
        return (
            self.db.query(BackgroundJob)
            .filter(
                BackgroundJob.status.in_(JOB_TERMINAL_STATUSES),
                BackgroundJob.finished_at.isnot(None),
                BackgroundJob.finished_at < older_than,
            )
            .delete(synchronize_session=False)
        )
