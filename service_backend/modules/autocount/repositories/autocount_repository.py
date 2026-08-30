"""AutoCount repositories - pure SQLAlchemy. No business logic, no HTTP.

    !!  EVERY query below filters ``tenant_id`` AND ``company_id`` (AC-13-41).  !!

Company scope is not decoration. One tenant legitimately runs several AutoCount
companies (D16 - ``AppId`` IS the company selector), so a tenant-only filter
would let company A's staged supplier documents surface under company B inside
the same customer. That is a data-leak class defect, not a UX bug.

The ONE exception is ``CompanyRepository``, where the company id IS the row's
primary key - scoping by ``(tenant_id, id)`` is the same guarantee.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import Text, cast, or_, select
from sqlalchemy.orm import Session

from app.models.background_job import (
    JOB_NEEDS_REVIEW,
    JOB_PENDING,
    JOB_RUNNING,
    BackgroundJob,
)
from app.models.connection import Connection

from ..models import (
    STAGED,
    STAGED_DISCARDED,
    STAGED_FAILED,
    STAGED_OP_DELETE,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
    AcRowHash,
    AcStagedRecord,
    AcSyncRun,
    AcWatermark,
)

# A job that is ACTUALLY EXECUTING. ``needs_review`` is deliberately absent -
# it is non-terminal but parked on a human, not running (see
# ``SyncJobRepository.first_unfinished``).
RUNNING_JOB_STATUSES = (JOB_PENDING, JOB_RUNNING)

# Chunk size for an ``IN (...)`` list - a 50k-row extract must never build one
# enormous parameter list (several drivers cap it outright).
_IN_CHUNK = 500


class ConnectionRepository:
    """READ-ONLY access to core ``public.connections`` for AutoCount rows.

    A module never ALTERS a core table; it may read one it owns rows in, and
    ``connections`` is where the provider's own config/credentials live. Kept in
    the repository layer rather than inline in the service so the enforced
    Router → Service → Repository split holds for core tables too, not just the
    module's own.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_for_provider(
        self, tenant_id: str, connection_id: str, provider: str
    ) -> Optional[Connection]:
        """Tenant- AND provider-scoped. NEVER a bare ``get(id)``: a connection id
        is a STORED reference, and resolving one unscoped is the polymorphic-
        target_id leak class (a planted id would read another tenant's
        credentials)."""
        return (
            self.db.query(Connection)
            .filter(
                Connection.tenant_id == tenant_id,
                Connection.id == connection_id,
                Connection.provider == provider,
            )
            .first()
        )

    def list_for_provider(self, tenant_id: str, provider: str) -> List[Connection]:
        """Every ACTIVE connection of one provider for THIS tenant (the task
        editor's connection picker, AC-22-29) - never a bare provider fetch."""
        return (
            self.db.query(Connection)
            .filter(
                Connection.tenant_id == tenant_id,
                Connection.provider == provider,
                Connection.is_active.is_(True),
            )
            .order_by(Connection.name.asc(), Connection.id.asc())
            .all()
        )


class CompanyRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, company: AcCompany) -> AcCompany:
        self.db.add(company)
        self.db.flush()
        return company

    def get(self, tenant_id: str, company_id: str) -> Optional[AcCompany]:
        return (
            self.db.query(AcCompany)
            .filter(AcCompany.tenant_id == tenant_id, AcCompany.id == company_id)
            .first()
        )

    def search_ids(self, tenant_id: str, term: str) -> List[str]:
        """Company ids whose label or database name contains ``term`` (case-
        insensitive), for the Review-list search. Tenant-scoped. The jobs table
        holds only a ``companyId``, so a company-name search resolves to an id
        set here first, then the jobs query filters ``payload.companyId IN`` it -
        the only way to keep the paginated total correct in one SQL pass."""
        like = f"%{term.strip()}%"
        rows = (
            self.db.query(AcCompany.id)
            .filter(
                AcCompany.tenant_id == tenant_id,
                or_(
                    AcCompany.name.ilike(like),
                    AcCompany.database_name.ilike(like),
                    AcCompany.company_name.ilike(like),
                ),
            )
            .all()
        )
        return [r[0] for r in rows]

    def get_by_database_name(
        self, tenant_id: str, database_name: str
    ) -> Optional[AcCompany]:
        """Company identity is ``DatabaseName`` - the uniqueness guard core
        deliberately delegated to this module (the ``erp`` carve-out)."""
        return (
            self.db.query(AcCompany)
            .filter(
                AcCompany.tenant_id == tenant_id,
                AcCompany.database_name == database_name,
            )
            .first()
        )

    def get_by_connection(
        self, tenant_id: str, connection_id: str
    ) -> Optional[AcCompany]:
        return (
            self.db.query(AcCompany)
            .filter(
                AcCompany.tenant_id == tenant_id,
                AcCompany.connection_id == connection_id,
            )
            .first()
        )

    def get_map(
        self, tenant_id: str, company_ids: Sequence[str]
    ) -> dict[str, AcCompany]:
        """Batch, TENANT-scoped id→company lookup (for a jobs page's labels) -
        ONE query, never one per row. A company id resolved here is filtered by
        tenant, so a job payload's id can never reach another tenant's row."""
        ids = list({cid for cid in company_ids if cid})
        if not ids:
            return {}
        rows = (
            self.db.query(AcCompany)
            .filter(AcCompany.tenant_id == tenant_id, AcCompany.id.in_(ids))
            .all()
        )
        return {row.id: row for row in rows}

    def list(
        self, tenant_id: str, *, page: int = 0, page_size: int = 25
    ) -> Tuple[List[AcCompany], int]:
        q = self.db.query(AcCompany).filter(AcCompany.tenant_id == tenant_id)
        total = q.count()
        rows = (
            q.order_by(AcCompany.created_at.asc(), AcCompany.id.asc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total


class EntityConfigRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, config: AcEntityConfig) -> AcEntityConfig:
        self.db.add(config)
        self.db.flush()
        return config

    def get(
        self, tenant_id: str, company_id: str, entity_type: str
    ) -> Optional[AcEntityConfig]:
        return (
            self.db.query(AcEntityConfig)
            .filter(
                AcEntityConfig.tenant_id == tenant_id,
                AcEntityConfig.company_id == company_id,
                AcEntityConfig.entity_type == entity_type,
            )
            .first()
        )

    def list_for_company(self, tenant_id: str, company_id: str) -> List[AcEntityConfig]:
        return (
            self.db.query(AcEntityConfig)
            .filter(
                AcEntityConfig.tenant_id == tenant_id,
                AcEntityConfig.company_id == company_id,
            )
            .order_by(AcEntityConfig.entity_type.asc())
            .all()
        )


class WatermarkRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(
        self, tenant_id: str, company_id: str, entity_type: str
    ) -> Optional[AcWatermark]:
        return (
            self.db.query(AcWatermark)
            .filter(
                AcWatermark.tenant_id == tenant_id,
                AcWatermark.company_id == company_id,
                AcWatermark.entity_type == entity_type,
            )
            .first()
        )

    def list_for_company(self, tenant_id: str, company_id: str) -> List[AcWatermark]:
        """Every entity's delta state for one company - ONE query, so the
        Entities surface never fans out per row."""
        return (
            self.db.query(AcWatermark)
            .filter(
                AcWatermark.tenant_id == tenant_id,
                AcWatermark.company_id == company_id,
            )
            .all()
        )

    def get_or_create(
        self, tenant_id: str, company_id: str, entity_type: str
    ) -> AcWatermark:
        row = self.get(tenant_id, company_id, entity_type)
        if row is None:
            row = AcWatermark(
                tenant_id=tenant_id, company_id=company_id, entity_type=entity_type
            )
            self.db.add(row)
            self.db.flush()
        return row


class FieldMappingRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, row: AcFieldMapping) -> AcFieldMapping:
        self.db.add(row)
        self.db.flush()
        return row

    def list(
        self, tenant_id: str, company_id: str, entity_type: str
    ) -> List[AcFieldMapping]:
        """Mapping ROWS for one (company, entity) - the data that IS the
        behaviour (D5). Includes disabled rows; the engine filters them, so the
        management surface can show an operator what exists but is off."""
        return (
            self.db.query(AcFieldMapping)
            .filter(
                AcFieldMapping.tenant_id == tenant_id,
                AcFieldMapping.company_id == company_id,
                AcFieldMapping.entity_type == entity_type,
            )
            .order_by(
                AcFieldMapping.scope.asc(),
                AcFieldMapping.sort_order.asc(),
                AcFieldMapping.canonical_field.asc(),
            )
            .all()
        )

    def count(self, tenant_id: str, company_id: str, entity_type: str) -> int:
        return (
            self.db.query(AcFieldMapping)
            .filter(
                AcFieldMapping.tenant_id == tenant_id,
                AcFieldMapping.company_id == company_id,
                AcFieldMapping.entity_type == entity_type,
            )
            .count()
        )

    def delete_by_canonical(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        canonical_fields: Sequence[str],
    ) -> int:
        """Delete the mapping rows whose ``canonical_field`` is in the given set -
        the DELIVERABLE rows the operator is replacing (plan 15 §2). Rows whose
        canonical field is NOT listed (identity/watermark provenance like
        ``last_modified``) are left untouched, so a full re-map can never wipe the
        watermark mapping and silently break delta sync."""
        fields = list(canonical_fields)
        if not fields:
            return 0
        deleted = (
            self.db.query(AcFieldMapping)
            .filter(
                AcFieldMapping.tenant_id == tenant_id,
                AcFieldMapping.company_id == company_id,
                AcFieldMapping.entity_type == entity_type,
                AcFieldMapping.canonical_field.in_(fields),
            )
            .delete(synchronize_session=False)
        )
        self.db.flush()
        return deleted


class StagedRecordRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, row: AcStagedRecord) -> AcStagedRecord:
        self.db.add(row)
        self.db.flush()
        return row

    def list_for_job(
        self, tenant_id: str, company_id: str, job_id: str
    ) -> List[AcStagedRecord]:
        return (
            self.db.query(AcStagedRecord)
            .filter(
                AcStagedRecord.tenant_id == tenant_id,
                AcStagedRecord.company_id == company_id,
                AcStagedRecord.job_id == job_id,
            )
            .order_by(AcStagedRecord.created_at.asc(), AcStagedRecord.id.asc())
            .all()
        )

    def page_for_job(
        self,
        tenant_id: str,
        company_id: str,
        job_id: str,
        *,
        changed: Optional[bool] = None,
        page: int = 0,
        page_size: int = 25,
    ) -> Tuple[List[AcStagedRecord], int, int, int]:
        """A PAGE of a job's staged records + counts (plan 15 §2, AC-15-10/11).

        Returns ``(rows, batch_total, filtered_total, no_change_count)``:
          * ``batch_total``    - every staged row for the job (unfiltered).
          * ``filtered_total`` - rows matching the ``changed`` filter (== total
            when unfiltered), for the caller's page math.
          * ``no_change_count`` - rows whose per-record diff is an EMPTY object
            (a legitimate no-op re-fetch - LastModified advanced but no mapped
            field differs), so the FE can render the collapsed summary WITHOUT
            fetching them all.

        The "no field changes" predicate is ``diff_json`` serialising to the
        empty-object literal ``'{}'``. It is expressed as a TEXT cast compared to
        that one literal - NEVER a JSON ``=`` (the Postgres ``json`` type has no
        equality operator; a JSON ``==`` would pass the SQLite suite and 500 in
        production). Only ever compared to ``'{}'``, so key ordering / whitespace
        of non-empty diffs is irrelevant.
        """
        base = self.db.query(AcStagedRecord).filter(
            AcStagedRecord.tenant_id == tenant_id,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.job_id == job_id,
        )
        empty_diff = cast(AcStagedRecord.diff_json, Text) == "{}"
        batch_total = base.count()
        no_change_count = base.filter(empty_diff).count()

        q = base
        if changed is True:
            q = q.filter(AcStagedRecord.diff_json.isnot(None), ~empty_diff)
        elif changed is False:
            q = q.filter(empty_diff)
        filtered_total = q.count()
        rows = (
            q.order_by(AcStagedRecord.created_at.asc(), AcStagedRecord.id.asc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return rows, batch_total, filtered_total, no_change_count

    def list_pending_for_job(
        self, tenant_id: str, company_id: str, job_id: str
    ) -> List[AcStagedRecord]:
        """STAGED rows only - FAILED rows are never pushable (D13) and already
        PUSHED rows are skipped, which is the belt to the approval claim's
        braces for exactly-once (AC-13-13)."""
        return (
            self.db.query(AcStagedRecord)
            .filter(
                AcStagedRecord.tenant_id == tenant_id,
                AcStagedRecord.company_id == company_id,
                AcStagedRecord.job_id == job_id,
                AcStagedRecord.status == STAGED,
            )
            .order_by(AcStagedRecord.created_at.asc(), AcStagedRecord.id.asc())
            .all()
        )

    def list_pending_for_entity(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        *,
        job_type: str,
        limit: int = 5000,
    ) -> List[AcStagedRecord]:
        """Every AUTO-PUSHABLE staged row for one (company, entity), oldest
        first - across jobs (plan 22 §2.6, AC-22-20).

        Two rules, and the second one is a safety gate:

        * **Across jobs**, because an auto-pushing task has no per-job review
          gate and "what is still undelivered" is an ENTITY-level question: a
          record the consumer called ``retryable`` stays STAGED and must be
          re-offered by the NEXT run, which is a different job.
        * **NEVER a row belonging to a batch that is still awaiting review.**
          An entity switched from the API path to a DB task can carry old
          ``needs_review`` batches (the API path parks them there by design).
          Auto-pushing those would deliver records a human explicitly still
          owns - the review gate bypassed by a source switch. Those rows stay
          exactly where they are until somebody approves or discards them.

        The per-JOB ``list_pending_for_job`` is untouched: the review gate is a
        per-batch decision and must not widen.
        """
        parked = (
            self.db.query(BackgroundJob.id)
            .filter(
                BackgroundJob.tenant_id == tenant_id,
                # ``background_jobs`` is a SHARED core table - pin the TYPE
                # too (NIT, S2 review) so this can never widen onto another
                # feature's needs_review jobs as the table grows, even though
                # ``AcStagedRecord.job_id`` only ever references OUR job type
                # today (defense-in-depth, not a behaviour change).
                BackgroundJob.type == job_type,
                BackgroundJob.status == JOB_NEEDS_REVIEW,
            )
            .subquery()
        )
        return (
            self.db.query(AcStagedRecord)
            .filter(
                AcStagedRecord.tenant_id == tenant_id,
                AcStagedRecord.company_id == company_id,
                AcStagedRecord.entity_type == entity_type,
                AcStagedRecord.status == STAGED,
                AcStagedRecord.job_id.notin_(select(parked.c.id)),
            )
            .order_by(AcStagedRecord.created_at.asc(), AcStagedRecord.id.asc())
            .limit(limit)
            .all()
        )

    def last_pushed(
        self, tenant_id: str, company_id: str, entity_type: str, source_ref: str
    ) -> Optional[AcStagedRecord]:
        """The most recently PUSHED version of this document - the "before" side
        of the per-record diff (AC-13-12)."""
        from ..models import STAGED_PUSHED

        return (
            self.db.query(AcStagedRecord)
            .filter(
                AcStagedRecord.tenant_id == tenant_id,
                AcStagedRecord.company_id == company_id,
                AcStagedRecord.entity_type == entity_type,
                AcStagedRecord.source_ref == source_ref,
                AcStagedRecord.status == STAGED_PUSHED,
            )
            .order_by(AcStagedRecord.pushed_at.desc(), AcStagedRecord.created_at.desc())
            .first()
        )

    def mark(
        self,
        rows: Sequence[AcStagedRecord],
        *,
        status: str,
        pushed_at: Optional[datetime] = None,
    ) -> None:
        for row in rows:
            row.status = status
            if pushed_at is not None:
                row.pushed_at = pushed_at
        self.db.flush()

    def discard_stale_deletes(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        current_refs: Sequence[str],
    ) -> int:
        """Cancel any pending delete intent whose ref REAPPEARED at source
        (plan 22 S3 review BLOCKER 1). A delete intent must not outlive the
        evidence that produced it: marks every STAGED ``op='delete'`` row for
        a ref now present in ``current_refs`` as ``STAGED_DISCARDED`` - so a
        ref that reappears with an UNCHANGED hash (nothing new staged for it)
        still cancels its own stale intent, and one parked on a draft/paused
        task never survives to fire once the task is later activated (this
        runs on every extract, not just ones whose push is live). Does not
        commit; the caller owns the transaction."""
        refs = [r for r in dict.fromkeys(current_refs) if r]
        if not refs:
            return 0
        discarded = 0
        for start in range(0, len(refs), _IN_CHUNK):
            chunk = refs[start : start + _IN_CHUNK]
            discarded += (
                self.db.query(AcStagedRecord)
                .filter(
                    AcStagedRecord.tenant_id == tenant_id,
                    AcStagedRecord.company_id == company_id,
                    AcStagedRecord.entity_type == entity_type,
                    AcStagedRecord.source_ref.in_(chunk),
                    AcStagedRecord.op == STAGED_OP_DELETE,
                    AcStagedRecord.status == STAGED,
                )
                .update({"status": STAGED_DISCARDED}, synchronize_session=False)
            )
        self.db.flush()
        return discarded

    def pending_delete_refs(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        source_refs: Sequence[str],
    ) -> set[str]:
        """Refs among ``source_refs`` that already carry a NON-TERMINAL delete
        intent (``STAGED`` or ``STAGED_FAILED``, ``op='delete'``) - S6/S3
        review: a reconcile that runs again before the first intent is
        resolved must never pile up a second row for the same ref."""
        refs = [r for r in dict.fromkeys(source_refs) if r]
        if not refs:
            return set()
        out: set[str] = set()
        for start in range(0, len(refs), _IN_CHUNK):
            chunk = refs[start : start + _IN_CHUNK]
            rows = (
                self.db.query(AcStagedRecord.source_ref)
                .filter(
                    AcStagedRecord.tenant_id == tenant_id,
                    AcStagedRecord.company_id == company_id,
                    AcStagedRecord.entity_type == entity_type,
                    AcStagedRecord.source_ref.in_(chunk),
                    AcStagedRecord.op == STAGED_OP_DELETE,
                    AcStagedRecord.status.in_((STAGED, STAGED_FAILED)),
                )
                .all()
            )
            out.update(ref for (ref,) in rows)
        return out


class RowHashRepository:
    """``ac_row_hash`` - reconcile state (plan 22 §2.4, AC-22-16).

    ONE row per source record ever seen by a DB task, holding only the hash of
    its compared columns. Every query is scoped by (tenant, company, entity) -
    the PK's first three columns - so one company's refs can never classify
    another's.
    """

    def __init__(self, db: Session):
        self.db = db

    def hashes_for(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        source_refs: Sequence[str],
    ) -> dict[str, str]:
        """``{source_ref: row_hash}`` for the refs given - batched in chunks so
        a 50k-row extract never builds one enormous ``IN`` list."""
        refs = [r for r in dict.fromkeys(source_refs) if r]
        out: dict[str, str] = {}
        for start in range(0, len(refs), _IN_CHUNK):
            chunk = refs[start : start + _IN_CHUNK]
            rows = (
                self.db.query(AcRowHash.source_ref, AcRowHash.row_hash)
                .filter(
                    AcRowHash.tenant_id == tenant_id,
                    AcRowHash.company_id == company_id,
                    AcRowHash.entity_type == entity_type,
                    AcRowHash.source_ref.in_(chunk),
                )
                .all()
            )
            out.update({ref: value for ref, value in rows})
        return out

    def upsert_many(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        hashes: dict[str, str],
        *,
        seen_at: datetime,
    ) -> int:
        """Write/refresh the hash of every ref given. Returns rows touched.

        Set-based: ONE read of the existing refs, then an UPDATE per changed
        ref and a bulk INSERT for the new ones - never a SELECT per row. Does
        not commit; the caller owns the transaction.
        """
        if not hashes:
            return 0
        existing = self.hashes_for(tenant_id, company_id, entity_type, list(hashes))
        scope = {
            "tenant_id": tenant_id,
            "company_id": company_id,
            "entity_type": entity_type,
        }
        updates = [
            {**scope, "source_ref": ref, "row_hash": value, "last_seen_at": seen_at}
            for ref, value in hashes.items()
            if ref in existing
        ]
        inserts = [
            {**scope, "source_ref": ref, "row_hash": value, "last_seen_at": seen_at}
            for ref, value in hashes.items()
            if ref not in existing
        ]
        # Both take the FULL composite PK, so SQLAlchemy batches each set into
        # one executemany - never a statement per row.
        if updates:
            self.db.bulk_update_mappings(AcRowHash, updates)
        if inserts:
            self.db.bulk_insert_mappings(AcRowHash, inserts)
        self.db.flush()
        return len(hashes)

    def count(self, tenant_id: str, company_id: str, entity_type: str) -> int:
        return (
            self.db.query(AcRowHash)
            .filter(
                AcRowHash.tenant_id == tenant_id,
                AcRowHash.company_id == company_id,
                AcRowHash.entity_type == entity_type,
            )
            .count()
        )

    def all_hashes(
        self, tenant_id: str, company_id: str, entity_type: str
    ) -> dict[str, str]:
        """Every stored ``{source_ref: row_hash}`` for one (tenant, company,
        entity) - plan 22 S3's reconcile diff needs the WHOLE known population,
        not just the refs a partial fetch happened to touch (that is the only
        way a ref absent from an extract becomes visible at all, AC-22-16).

        Bounded the same way a full extract is - a reconcile task's hash
        population is the same order of magnitude as the table it mirrors.
        """
        rows = (
            self.db.query(AcRowHash.source_ref, AcRowHash.row_hash)
            .filter(
                AcRowHash.tenant_id == tenant_id,
                AcRowHash.company_id == company_id,
                AcRowHash.entity_type == entity_type,
            )
            .all()
        )
        return {ref: value for ref, value in rows}

    def delete_many(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        source_refs: Sequence[str],
    ) -> int:
        """Remove the hash rows for CONFIRMED-DELETED refs (AC-22-21) - so a
        later re-appearance at source has no prior hash to compare against and
        stages as a fresh add, not a phantom update. Chunked like every other
        ``IN`` list here. Does not commit; the caller owns the transaction."""
        refs = [r for r in dict.fromkeys(source_refs) if r]
        deleted = 0
        for start in range(0, len(refs), _IN_CHUNK):
            chunk = refs[start : start + _IN_CHUNK]
            deleted += (
                self.db.query(AcRowHash)
                .filter(
                    AcRowHash.tenant_id == tenant_id,
                    AcRowHash.company_id == company_id,
                    AcRowHash.entity_type == entity_type,
                    AcRowHash.source_ref.in_(chunk),
                )
                .delete(synchronize_session=False)
            )
        self.db.flush()
        return deleted


class SyncRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, run: AcSyncRun) -> AcSyncRun:
        self.db.add(run)
        self.db.flush()
        return run

    def get_for_job(
        self, tenant_id: str, company_id: str, job_id: str
    ) -> Optional[AcSyncRun]:
        return (
            self.db.query(AcSyncRun)
            .filter(
                AcSyncRun.tenant_id == tenant_id,
                AcSyncRun.company_id == company_id,
                AcSyncRun.job_id == job_id,
            )
            .first()
        )

    def list(
        self,
        tenant_id: str,
        company_id: str,
        *,
        entity_type: Optional[str] = None,
        page: int = 0,
        page_size: int = 25,
    ) -> Tuple[List[AcSyncRun], int]:
        q = self.db.query(AcSyncRun).filter(
            AcSyncRun.tenant_id == tenant_id, AcSyncRun.company_id == company_id
        )
        if entity_type:
            q = q.filter(AcSyncRun.entity_type == entity_type)
        total = q.count()
        rows = (
            q.order_by(AcSyncRun.started_at.desc(), AcSyncRun.id.desc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total


class SyncJobRepository:
    """READ-ONLY, TENANT-scoped access to core ``public.background_jobs``, pinned
    to this module's job ``type`` (``autocount_sync``).

    A module never ALTERS a core table; it may read one it owns rows in.
    ``background_jobs`` is generic machinery, but AutoCount's sync-job knowledge
    (the ``type`` tag and the ``entityType`` payload key) is module-specific, so
    the JSON-payload filter belongs here rather than in the generic core
    ``JobService``. Every query filters ``tenant_id`` - a job from another tenant
    can never surface (the polymorphic-scope rule).
    """

    def __init__(self, db: Session):
        self.db = db

    def first_unfinished(
        self, tenant_id: str, job_type: str, company_id: str, entity_type: str
    ) -> Optional[BackgroundJob]:
        """The oldest job for one (company, entity) that is ACTUALLY EXECUTING.

        The overlap guard (AC-22-14) and the manual-run 409 both ask the same
        question: "is a run for this task already in flight?" - so the answer
        is ``pending``/``running`` only.

            !!  ``needs_review`` IS NOT IN FLIGHT.  !!

        It is a deliberately non-terminal status the pruner never reaps, and a
        batch parked there is not executing - it is waiting on a human, maybe
        forever. Counting it as in-flight would let an old API-path batch
        permanently refuse every run of the DB task that replaced it (found in
        live verify: four July batches blocked Run now outright).
        """
        return (
            self.db.query(BackgroundJob)
            .filter(
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.type == job_type,
                BackgroundJob.status.in_(RUNNING_JOB_STATUSES),
                BackgroundJob.payload_json["companyId"].as_string() == company_id,
                BackgroundJob.payload_json["entityType"].as_string() == entity_type,
            )
            .order_by(BackgroundJob.created_at.asc(), BackgroundJob.id.asc())
            .first()
        )

    def list(
        self,
        tenant_id: str,
        job_type: str,
        *,
        status: Optional[str] = None,
        entity_type: Optional[str] = None,
        company_ids: Optional[Sequence[str]] = None,
        page: int = 0,
        page_size: int = 25,
    ) -> Tuple[List[BackgroundJob], int]:
        q = self.db.query(BackgroundJob).filter(
            BackgroundJob.tenant_id == tenant_id,
            BackgroundJob.type == job_type,
        )
        if status:
            q = q.filter(BackgroundJob.status == status)
        if company_ids is not None:
            # The Review-list search resolved to this id set (company label match);
            # an empty set means "no company matched" → no rows, in SQL, so the
            # paginated total is honest.
            q = q.filter(
                BackgroundJob.payload_json["companyId"].as_string().in_(company_ids)
            )
        if entity_type:
            # ``payload_json ->> 'entityType'`` - the generic-JSON string
            # comparator compiles per dialect (``json_extract`` on SQLite, ``->>``
            # on Postgres, both valid for the ``json`` type) so the filter runs
            # in SQL and pagination totals stay correct.
            q = q.filter(
                BackgroundJob.payload_json["entityType"].as_string() == entity_type
            )
        total = q.count()
        rows = (
            q.order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total
