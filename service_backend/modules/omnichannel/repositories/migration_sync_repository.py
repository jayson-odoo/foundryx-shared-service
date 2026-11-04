"""``migration_syncs`` / ``migration_sync_hints`` repository (plan 52). Pure
SQLAlchemy; every read and write is tenant-scoped. The ONLY unscoped read is
``get_unscoped`` - used by the public webhook before the secret check, where
the tenant is not yet known (the sync row itself carries it)."""
from datetime import datetime
from typing import Any, Iterable, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.background_job import JOB_DONE, BackgroundJob
from app.models.user import User

from ..models import MigrationSync, MigrationSyncHint, Workspace


class MigrationSyncRepository:
    def __init__(self, db: Session):
        self.db = db

    # ── syncs ───────────────────────────────────────────────────────────────

    def get(self, tenant_id: str, sync_id: str) -> Optional[MigrationSync]:
        return (
            self.db.query(MigrationSync)
            .filter(MigrationSync.tenant_id == tenant_id, MigrationSync.id == sync_id)
            .first()
        )

    def get_by_workspace(self, tenant_id: str, workspace_id: str) -> Optional[MigrationSync]:
        return (
            self.db.query(MigrationSync)
            .filter(MigrationSync.tenant_id == tenant_id, MigrationSync.workspace_id == workspace_id)
            .first()
        )

    def get_unscoped(self, sync_id: str) -> Optional[MigrationSync]:
        """Public-hook lookup ONLY (the secret check follows immediately)."""
        return self.db.query(MigrationSync).filter(MigrationSync.id == sync_id).first()

    def add(self, sync: MigrationSync) -> MigrationSync:
        self.db.add(sync)
        self.db.flush()
        return sync

    def active_refs(self) -> List[Tuple[str, str]]:
        """``(tenant_id, sync_id)`` of every ACTIVE or STOPPING sync - the beat
        sweep walks all tenants; each row is then handled strictly with its
        own tenant."""
        rows = self.db.query(MigrationSync.tenant_id, MigrationSync.id).filter(
            MigrationSync.status.in_(("active", "stopping"))
        ).all()
        return [(t, i) for t, i in rows]

    def update(self, tenant_id: str, sync_id: str, **cols: Any) -> int:
        n = (
            self.db.query(MigrationSync)
            .filter(MigrationSync.tenant_id == tenant_id, MigrationSync.id == sync_id)
            .update(cols, synchronize_session=False)
        )
        return int(n or 0)

    def update_if(self, tenant_id: str, sync_id: str, where: Iterable[Any], **cols: Any) -> int:
        """Guarded UPDATE (claim): applies only while ``where`` still holds."""
        n = (
            self.db.query(MigrationSync)
            .filter(MigrationSync.tenant_id == tenant_id, MigrationSync.id == sync_id, *list(where))
            .update(cols, synchronize_session=False)
        )
        return int(n or 0)

    def fresh_status(self, tenant_id: str, sync_id: str) -> Optional[str]:
        return (
            self.db.query(MigrationSync.status)
            .filter(MigrationSync.tenant_id == tenant_id, MigrationSync.id == sync_id)
            .scalar()
        )

    # ── hints ───────────────────────────────────────────────────────────────

    def count_hints(self, tenant_id: str, sync_id: str) -> int:
        return (
            self.db.query(MigrationSyncHint)
            .filter(MigrationSyncHint.tenant_id == tenant_id, MigrationSyncHint.sync_id == sync_id)
            .count()
        )

    def hint_contact_ids(self, tenant_id: str, sync_id: str, limit: Optional[int] = None) -> List[str]:
        q = (
            self.db.query(MigrationSyncHint.external_contact_id)
            .filter(MigrationSyncHint.tenant_id == tenant_id, MigrationSyncHint.sync_id == sync_id)
            .order_by(MigrationSyncHint.created_at.asc(), MigrationSyncHint.id.asc())
        )
        if limit:
            q = q.limit(limit)
        return [r[0] for r in q.all()]

    def hint_rows(self, tenant_id: str, sync_id: str, limit: Optional[int] = None) -> List[Tuple[str, datetime]]:
        """``(contact id, created_at)`` as read - the tick deletes exactly
        these (id AND stamp), so a hint re-sent mid-tick survives."""
        q = (
            self.db.query(MigrationSyncHint.external_contact_id, MigrationSyncHint.created_at)
            .filter(MigrationSyncHint.tenant_id == tenant_id, MigrationSyncHint.sync_id == sync_id)
            .order_by(MigrationSyncHint.created_at.asc(), MigrationSyncHint.id.asc())
        )
        if limit:
            q = q.limit(limit)
        return [(r[0], r[1]) for r in q.all()]

    def add_hint(self, tenant_id: str, sync_id: str, external_contact_id: str, now: datetime) -> bool:
        """Insert-ignore. True when a new row was stored. A duplicate bumps the
        existing row's stamp to ``now`` (a tick that already read the old stamp
        then leaves the row for the next tick instead of deleting it)."""
        exists = (
            self.db.query(MigrationSyncHint.id)
            .filter(
                MigrationSyncHint.tenant_id == tenant_id,
                MigrationSyncHint.sync_id == sync_id,
                MigrationSyncHint.external_contact_id == external_contact_id,
            )
            .first()
        )
        if exists:
            (
                self.db.query(MigrationSyncHint)
                .filter(MigrationSyncHint.id == exists[0], MigrationSyncHint.tenant_id == tenant_id)
                .update({MigrationSyncHint.created_at: now}, synchronize_session=False)
            )
            return False
        try:
            with self.db.begin_nested():
                self.db.add(
                    MigrationSyncHint(
                        tenant_id=tenant_id, sync_id=sync_id,
                        external_contact_id=external_contact_id, created_at=now,
                    )
                )
                self.db.flush()
        except IntegrityError:
            return False
        return True

    def delete_hints(self, tenant_id: str, sync_id: str, read: Iterable[Tuple[str, datetime]]) -> None:
        """Delete only rows still carrying the (id, created_at) the tick read."""
        for contact_id, stamp in read:
            (
                self.db.query(MigrationSyncHint)
                .filter(
                    MigrationSyncHint.tenant_id == tenant_id,
                    MigrationSyncHint.sync_id == sync_id,
                    MigrationSyncHint.external_contact_id == contact_id,
                    MigrationSyncHint.created_at == stamp,
                )
                .delete(synchronize_session=False)
            )

    # ── source runs / jobs (payload filters stay in Python: no native column) ─

    def _done_runs(self, tenant_id: str, job_type: str):
        return (
            self.db.query(BackgroundJob)
            .filter(
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.type == job_type,
                BackgroundJob.status == JOB_DONE,
            )
            .order_by(BackgroundJob.finished_at.desc(), BackgroundJob.created_at.desc())
            .yield_per(50)
        )

    def newest_done_run(
        self, tenant_id: str, job_type: str, workspace_id: str, *, mode: str, source: Optional[str]
    ) -> Optional[BackgroundJob]:
        for job in self._done_runs(tenant_id, job_type):
            p = job.payload_json or {}
            if p.get("workspaceId") != workspace_id or p.get("mode") != mode:
                continue
            if source is not None and p.get("source", "api") != source:
                continue
            return job
        return None

    def get_job(self, tenant_id: str, job_id: str) -> Optional[BackgroundJob]:
        return (
            self.db.query(BackgroundJob)
            .filter(BackgroundJob.tenant_id == tenant_id, BackgroundJob.id == job_id)
            .first()
        )

    # ── neighbours (tenant-scoped reads) ────────────────────────────────────

    def workspace(self, tenant_id: str, workspace_id: str) -> Optional[Workspace]:
        return (
            self.db.query(Workspace)
            .filter(Workspace.tenant_id == tenant_id, Workspace.id == workspace_id)
            .first()
        )

    def user(self, tenant_id: str, user_id: str) -> Optional[User]:
        return self.db.query(User).filter(User.tenant_id == tenant_id, User.id == user_id).first()
