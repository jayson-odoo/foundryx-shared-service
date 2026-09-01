"""Import repository (sprint-3/09) - pure SQLAlchemy, tenant-scoped."""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.import_job import ImportJob, ImportSettings


class ImportRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, job: ImportJob) -> ImportJob:
        self.db.add(job)
        self.db.flush()
        return job

    def get(self, tenant_id: str, job_id: str) -> Optional[ImportJob]:
        return (
            self.db.query(ImportJob)
            .filter(ImportJob.tenant_id == tenant_id, ImportJob.id == job_id)
            .first()
        )

    def get_unscoped(self, job_id: str) -> Optional[ImportJob]:
        """For the Celery task - the worker re-scopes inside the job's tenant."""
        return self.db.query(ImportJob).filter(ImportJob.id == job_id).first()

    def list(
        self,
        tenant_id: str,
        *,
        actor_user_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 0,
        page_size: int = 25,
    ) -> tuple[List[ImportJob], int]:
        q = self.db.query(ImportJob).filter(ImportJob.tenant_id == tenant_id)
        if actor_user_id is not None:
            q = q.filter(ImportJob.actor_user_id == actor_user_id)
        if entity_type:
            q = q.filter(ImportJob.entity_type == entity_type)
        if status:
            q = q.filter(ImportJob.status == status)
        total = q.count()
        rows = (
            q.order_by(ImportJob.created_at.desc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total

    def claim_for_commit(self, job_id: str, from_status: str) -> bool:
        """Atomic double-commit guard (D7): UPDATE … WHERE status=validated →
        0 rows = already claimed."""
        from app.models.import_job import STATUS_IMPORTING

        updated = (
            self.db.query(ImportJob)
            .filter(ImportJob.id == job_id, ImportJob.status == from_status)
            .update({ImportJob.status: STATUS_IMPORTING}, synchronize_session=False)
        )
        self.db.flush()
        return updated == 1

    def get_settings(self, tenant_id: str) -> Optional[ImportSettings]:
        return (
            self.db.query(ImportSettings)
            .filter(ImportSettings.tenant_id == tenant_id)
            .first()
        )

    def upsert_settings(
        self, tenant_id: str, max_rows: Optional[int], max_file_mb: Optional[int]
    ) -> ImportSettings:
        row = self.get_settings(tenant_id)
        if row is None:
            row = ImportSettings(tenant_id=tenant_id)
            self.db.add(row)
        row.max_rows = max_rows
        row.max_file_mb = max_file_mb
        self.db.flush()
        return row
