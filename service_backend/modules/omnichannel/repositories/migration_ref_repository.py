"""``migration_refs`` repository (plan 33 S2, D-A6-3) - THE idempotency index
for the respond.io migration tool. Every query is tenant AND workspace scoped
(never a bare tenant-only lookup - two respond.io spaces migrated into two
different workspaces of the SAME tenant must never see each other's refs).
"""
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from ..models import MigrationRef


class MigrationRefRepository:
    def __init__(self, db: Session):
        self.db = db

    def local_for_one(
        self, tenant_id: str, workspace_id: str, source: str, entity_type: str, external_id: str
    ) -> Optional[str]:
        row = (
            self.db.query(MigrationRef.local_id)
            .filter(
                MigrationRef.tenant_id == tenant_id,
                MigrationRef.workspace_id == workspace_id,
                MigrationRef.source == source,
                MigrationRef.entity_type == entity_type,
                MigrationRef.external_id == str(external_id),
            )
            .first()
        )
        return row[0] if row else None

    def local_for(
        self,
        tenant_id: str,
        workspace_id: str,
        source: str,
        entity_type: str,
        external_ids: Iterable[str],
    ) -> Dict[str, str]:
        """Batched ``external_id -> local_id`` for every id in
        ``external_ids`` that already has a ref - ONE query, never one per id
        (mirrors every other batched lookup in this module)."""
        ids = [str(i) for i in external_ids]
        if not ids:
            return {}
        rows = (
            self.db.query(MigrationRef.external_id, MigrationRef.local_id)
            .filter(
                MigrationRef.tenant_id == tenant_id,
                MigrationRef.workspace_id == workspace_id,
                MigrationRef.source == source,
                MigrationRef.entity_type == entity_type,
                MigrationRef.external_id.in_(ids),
            )
            .all()
        )
        return {external_id: local_id for external_id, local_id in rows}

    def already_migrated(
        self,
        tenant_id: str,
        workspace_id: str,
        source: str,
        entity_type: str,
        external_ids: Iterable[str],
    ) -> set:
        """The SUBSET of ``external_ids`` that already have a ref (AC-MIG-28's
        "a later re-run resumes from migration_refs and creates no
        duplicates")."""
        return set(self.local_for(tenant_id, workspace_id, source, entity_type, external_ids))

    def record(
        self,
        tenant_id: str,
        workspace_id: str,
        source: str,
        entity_type: str,
        external_id: str,
        local_id: str,
    ) -> MigrationRef:
        """Adds + flushes (never commits) - rides the caller's own unit of
        work, same convention as `event_service.record`. The caller (the job
        handler's per-contact SAVEPOINT) decides whether this survives."""
        row = MigrationRef(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            source=source,
            entity_type=entity_type,
            external_id=str(external_id),
            local_id=local_id,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def count_for_entity(self, tenant_id: str, workspace_id: str, source: str, entity_type: str) -> int:
        """Total refs recorded for one entity type - used for report totals
        that must reflect a RESUMED run's full history, not just this
        session's page (e.g. "contacts migrated so far" across crashes)."""
        return (
            self.db.query(MigrationRef.id)
            .filter(
                MigrationRef.tenant_id == tenant_id,
                MigrationRef.workspace_id == workspace_id,
                MigrationRef.source == source,
                MigrationRef.entity_type == entity_type,
            )
            .count()
        )

    def list_local_ids(
        self, tenant_id: str, workspace_id: str, source: str, entity_type: str
    ) -> List[str]:
        rows = (
            self.db.query(MigrationRef.local_id)
            .filter(
                MigrationRef.tenant_id == tenant_id,
                MigrationRef.workspace_id == workspace_id,
                MigrationRef.source == source,
                MigrationRef.entity_type == entity_type,
            )
            .all()
        )
        return [r[0] for r in rows]

    def paged(
        self,
        tenant_id: str,
        workspace_id: str,
        source: str,
        entity_type: str,
        *,
        after_id: Optional[str],
        limit: int,
    ) -> List[MigrationRef]:
        """Keyset pagination over ``MigrationRef.id`` (plan 33 S3) - the
        identities/messages phases walk every "contact" ref this workspace has
        EVER migrated (across job runs, not just this one), and a per-contact
        checkpoint (``after_id`` = the last-processed ref's own id) is what
        makes each phase resumable across a crash without re-processing an
        already-completed contact. ``MigrationRef.id`` is a plain indexed
        primary key - any STABLE total order works for keyset paging (the
        rows are never updated in place, so lexical UUID order never skips or
        duplicates a row), it does not need to reflect insertion time."""
        q = self.db.query(MigrationRef).filter(
            MigrationRef.tenant_id == tenant_id,
            MigrationRef.workspace_id == workspace_id,
            MigrationRef.source == source,
            MigrationRef.entity_type == entity_type,
        )
        if after_id:
            q = q.filter(MigrationRef.id > after_id)
        return q.order_by(MigrationRef.id.asc()).limit(limit).all()
