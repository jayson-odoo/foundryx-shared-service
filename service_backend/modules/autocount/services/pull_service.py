"""Sprint-5/10 §2.4 - the pull snapshot store: the ONE write gate for
``AcPullSnapshot``/``AcPullSnapshotRow`` (AC-10-19..26).

``SnapshotService`` is deliberately the only thing that ever writes a
snapshot: it refuses (raises) any write against a snapshot whose status is
not ``building`` - immutability once ``ready`` is a runtime guard here, not
just the repository's structural absence of an update-row method.
``PullService`` sits above it and owns the build LIFECYCLE (one ``building``
snapshot per triple, the re-attach/cooldown rule, the background job) - the
seam the operator routes (``routers/pull.py``) and, later, the public
gateway (S4) both call.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import (
    PULL_SNAPSHOT_STATUS_BUILDING,
    PULL_SNAPSHOT_STATUS_FAILED,
    PULL_SNAPSHOT_STATUS_READY,
    AcPullSnapshot,
    AcPullSnapshotRow,
)
from ..repositories import PullSnapshotRepository
from .company_service import AutocountServiceError

# The build-end TTL (AC-10-25). Kept as a module constant rather than an
# ``app/config.py`` setting for THIS slice (S3) - the throttle scope and its
# own settings land in S4, and a snapshot TTL is not part of that surface;
# promoting this to a setting is a fair S4/S5 follow-up, noted in the S3
# final report.
AUTOCOUNT_PULL_SNAPSHOT_TTL_HOURS = 24

# At most one ``building`` snapshot per (tenant, company, entity); a build
# request inside this window of the PREVIOUS build is refused (AC-10-26).
BUILD_COOLDOWN_SECONDS = 60

# Retention: keep only the newest N ready snapshots per triple (AC-10-25).
PULL_SNAPSHOT_RETENTION_KEEP = 3

# A page never serves more than this many rows (AC-10-33: "above max is
# clamped, not an error").
MAX_PULL_PAGE_SIZE = 1000


class SnapshotNotBuildingError(AutocountServiceError):
    """A write was attempted against a snapshot whose ``status`` is not
    ``building`` - AC-10-19's immutability guard. Never happens for a
    genuinely BUILDING snapshot (see the control test in
    ``test_s10_s3_snapshot_store.py``)."""


class PullBuildCooldownError(AutocountServiceError):
    """A build was requested within ``BUILD_COOLDOWN_SECONDS`` of the
    previous one for the same (tenant, company, entity) triple (AC-10-26).
    ``retry_after_seconds`` is the caller's own back-off hint."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            f"A snapshot for this entity was built less than "
            f"{BUILD_COOLDOWN_SECONDS} seconds ago. Try again shortly."
        )
        self.retry_after_seconds = max(1, int(retry_after_seconds))


class SnapshotService:
    """The ONE write gate (AC-10-19, verbatim). Every write checks the
    snapshot's OWN current status FIRST - never trusts an in-memory object
    that might be stale against a concurrent stamp."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = PullSnapshotRepository(db)

    def create_building(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        *,
        company_code: Optional[str],
        requested_via: str,
        requested_by: Optional[str] = None,
    ) -> AcPullSnapshot:
        snapshot = AcPullSnapshot(
            tenant_id=tenant_id,
            company_id=company_id,
            entity_type=entity_type,
            company_code=company_code,
            status=PULL_SNAPSHOT_STATUS_BUILDING,
            requested_via=requested_via,
            requested_by=requested_by,
        )
        self.repo.add(snapshot)
        self.db.commit()
        self.db.refresh(snapshot)
        return snapshot

    def _assert_building(self, tenant_id: str, snapshot: AcPullSnapshot) -> AcPullSnapshot:
        """Re-reads the snapshot's OWN current status from the DB (never the
        caller's possibly-stale in-memory object) before any write."""
        current = self.repo.get(tenant_id, snapshot.id)
        if current is None or current.status != PULL_SNAPSHOT_STATUS_BUILDING:
            raise SnapshotNotBuildingError(
                "This snapshot is no longer building and cannot be written to."
            )
        return current

    def insert_row(
        self,
        tenant_id: str,
        snapshot: AcPullSnapshot,
        row_index: int,
        *,
        company_id: str,
        source_ref: str,
        payload: Dict[str, Any],
    ) -> None:
        self._assert_building(tenant_id, snapshot)
        self.repo.insert_row(
            AcPullSnapshotRow(
                tenant_id=tenant_id,
                snapshot_id=snapshot.id,
                row_index=row_index,
                company_id=company_id,
                source_ref=source_ref,
                payload_json=payload,
            )
        )

    def stamp_ready(
        self,
        tenant_id: str,
        snapshot: AcPullSnapshot,
        *,
        record_count: int,
        complete: bool,
        content_hash: str,
        metadata: Dict[str, Any],
        extracted_at: datetime,
        expires_at: datetime,
    ) -> AcPullSnapshot:
        current = self._assert_building(tenant_id, snapshot)
        current.status = PULL_SNAPSHOT_STATUS_READY
        current.record_count = record_count
        current.complete = complete
        current.content_hash = content_hash
        current.metadata_json = dict(metadata)
        current.extracted_at = extracted_at
        current.expires_at = expires_at
        current.error = None
        current.error_code = None
        self.db.commit()
        self.db.refresh(current)
        return current

    def stamp_failed(
        self,
        tenant_id: str,
        snapshot: AcPullSnapshot,
        *,
        error: str,
        error_code: str,
    ) -> AcPullSnapshot:
        current = self._assert_building(tenant_id, snapshot)
        current.status = PULL_SNAPSHOT_STATUS_FAILED
        current.error = error
        current.error_code = error_code
        self.db.commit()
        self.db.refresh(current)
        return current


def compute_content_hash(rows: List[Dict[str, Any]]) -> str:
    """``sha256`` over the EXACT stored ``payload_json`` dicts, in
    ``row_index`` order (AC-10-23) - a pure function so it can be pinned
    independently of the build job that calls it."""
    digest = hashlib.sha256()
    for row in rows:
        digest.update(
            (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        )
    return digest.hexdigest()


def prune_pull_snapshots(db: Session, *, now: Optional[datetime] = None) -> Dict[str, int]:
    """The beat body (``autocount.prune_pull_snapshots``, AC-10-25): deletes
    every EXPIRED snapshot (and its rows), then - independently - drops
    every READY snapshot beyond the newest
    ``PULL_SNAPSHOT_RETENTION_KEEP`` per (tenant, company, entity) triple.
    Global (every tenant) - the module's own maintenance sweep, mirroring
    ``scheduler.sweep_etl_tasks``'s cross-tenant reach."""
    now = now or datetime.now(timezone.utc)
    repo = PullSnapshotRepository(db)
    expired_ids = repo.expired_ids(now)
    for snapshot_id in expired_ids:
        repo.delete(snapshot_id)
    retained_over_ids = [
        snapshot_id
        for snapshot_id in repo.ready_ids_beyond_newest(keep=PULL_SNAPSHOT_RETENTION_KEEP)
        if snapshot_id not in expired_ids
    ]
    for snapshot_id in retained_over_ids:
        repo.delete(snapshot_id)
    db.commit()
    return {"expired": len(expired_ids), "retentionPruned": len(retained_over_ids)}


def snapshot_header(snapshot: AcPullSnapshot) -> Dict[str, Any]:
    """The wire header (AC-10-32) - a thin, pure projection of the snapshot's
    own columns plus its ``metadata_json`` (which carries ``excludedRows``/
    ``excludedCount`` and every per-entity counter). The ONE place these
    fields assemble, so the operator routes and the S4 public gateway can
    never drift."""
    metadata = snapshot.metadata_json or {}
    header: Dict[str, Any] = {
        "id": snapshot.id,
        "entityType": snapshot.entity_type,
        "companyId": snapshot.company_id,
        "companyCode": snapshot.company_code,
        "status": snapshot.status,
        "requestedVia": snapshot.requested_via,
        "createdAt": snapshot.created_at,
        "extractedAt": snapshot.extracted_at,
        "expiresAt": snapshot.expires_at,
        "recordCount": snapshot.record_count,
        "complete": snapshot.complete,
        "contentHash": snapshot.content_hash,
        "sourcePageSize": metadata.get("sourcePageSize"),
        "excludedCount": metadata.get("excludedCount", 0),
        "excludedRows": metadata.get("excludedRows", []),
    }
    if snapshot.status == PULL_SNAPSHOT_STATUS_FAILED:
        header["error"] = {"code": snapshot.error_code, "message": snapshot.error}
    for key in (
        "zeroListPriceCount",
        "negativeListPriceCount",
        "enrichMissCount",
        "zeroPairs",
        "negativePairs",
        "fractionalPairs",
        "excludedNonzeroCount",
        "negativePairList",
    ):
        if key in metadata:
            header[key] = metadata[key]
    return header


class PullSnapshotNotFound(AutocountServiceError):
    """Unknown snapshot id, or one outside the caller's tenant/company scope
    - uniform (AC-10-30: possession of an id is not authorisation)."""


class PullService:
    """Owns the build LIFECYCLE: at most one ``building`` snapshot per
    triple, the re-attach/cooldown rule, and enqueuing the background job
    that does the actual extraction (``sync._run_pull_snapshot``)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = PullSnapshotRepository(db)

    def request_build(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        *,
        requested_via: str,
        requested_by: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> AcPullSnapshot:
        now = now or datetime.now(timezone.utc)
        existing = self.repo.latest_for_triple(tenant_id, company_id, entity_type)
        if existing is not None and existing.status == PULL_SNAPSHOT_STATUS_BUILDING:
            #     !!  RE-ATTACH HAS NO TIME LIMIT WHILE THE BUILD IS ALIVE.  !!
            # A consumer that stopped polling re-clicks and lands on the SAME
            # snapshot id, never a second extraction (AC-10-26/88). A build
            # that genuinely died is closed by the module's orphan hook, not
            # by age here.
            return existing
        if existing is not None and existing.extracted_at is not None:
            elapsed = (now - existing.extracted_at).total_seconds()
            if elapsed < BUILD_COOLDOWN_SECONDS:
                raise PullBuildCooldownError(
                    retry_after_seconds=BUILD_COOLDOWN_SECONDS - int(elapsed)
                )

        from .company_service import CompanyService

        company = CompanyService(self.db).get(tenant_id, company_id)
        snapshot = SnapshotService(self.db).create_building(
            tenant_id,
            company_id,
            entity_type,
            company_code=company.sorento_company_code,
            requested_via=requested_via,
            requested_by=requested_by,
        )

        #     !!  DEFERRED IMPORTS - MIRROR sync.py's OWN CYCLE AVOIDANCE.  !!
        # ``sync.py`` imports ``.services.*`` only inside functions (never at
        # module level) precisely so ``services/*.py`` can import FROM
        # ``sync`` at module level without a cycle - ``AUTOCOUNT_PULL_
        # SNAPSHOT`` is that constant.
        from app.jobs.service import JobService

        from ..sync import AUTOCOUNT_PULL_SNAPSHOT

        job = JobService(self.db).create_and_enqueue(
            type=AUTOCOUNT_PULL_SNAPSHOT,
            tenant_id=tenant_id,
            actor_user_id=requested_by,
            payload={
                "companyId": company_id,
                "entityType": entity_type,
                "snapshotId": snapshot.id,
            },
        )
        snapshot.job_id = job.id
        self.db.commit()
        self.db.refresh(snapshot)
        return snapshot

    # ── reads (operator routes now; the S4 public gateway reuses these) ─────

    def get_snapshot(
        self, tenant_id: str, snapshot_id: str, *, company_id: Optional[str] = None
    ) -> AcPullSnapshot:
        """Tenant-scoped (and, when given, additionally COMPANY-scoped - the
        gateway's own call) lookup. Unknown id and cross-scope id read
        IDENTICALLY (AC-10-30/37 - possession of an id is not authorisation)."""
        snapshot = (
            self.repo.get_scoped(tenant_id, company_id, snapshot_id)
            if company_id is not None
            else self.repo.get(tenant_id, snapshot_id)
        )
        if snapshot is None:
            raise PullSnapshotNotFound("That snapshot was not found.")
        return snapshot

    def list_snapshots(
        self,
        tenant_id: str,
        *,
        company_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        page: int = 0,
        page_size: int = 25,
    ) -> Tuple[List[AcPullSnapshot], int]:
        return self.repo.list(
            tenant_id,
            company_id=company_id,
            entity_type=entity_type,
            page=page,
            page_size=page_size,
        )

    def snapshot_rows_page(
        self,
        tenant_id: str,
        snapshot_id: str,
        *,
        company_id: Optional[str] = None,
        page: int,
        page_size: int,
    ) -> Tuple[AcPullSnapshot, List[AcPullSnapshotRow], int]:
        """``page`` is 1-based (AC-10-33); ``pageSize`` clamps to
        ``MAX_PULL_PAGE_SIZE`` rather than erroring."""
        snapshot = self.get_snapshot(tenant_id, snapshot_id, company_id=company_id)
        clamped_size = min(max(page_size, 1), MAX_PULL_PAGE_SIZE)
        rows, total = self.repo.rows_page(
            tenant_id, snapshot.id, page=max(page, 1), page_size=clamped_size
        )
        return snapshot, rows, total
