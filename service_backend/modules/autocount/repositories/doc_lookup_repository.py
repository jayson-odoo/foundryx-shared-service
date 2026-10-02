"""Doc finder repositories (sprint-5/17) - pure SQLAlchemy, ALWAYS tenant- AND
company-scoped. Reads over snapshot rows / the feed ledger are SELECTs only;
the only rows written are the finder's own hint + settings rows."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.background_job import JOB_PENDING, JOB_RUNNING, BackgroundJob

from ..models import (
    PULL_SNAPSHOT_STATUS_READY,
    AcCompany,
    AcDocFeedLedger,
    AcDocLookupHint,
    AcDocLookupSettings,
    AcPullSnapshot,
    AcPullSnapshotRow,
)

MAX_SNAPSHOT_SIGHTINGS = 50


def _norm_expr(column):
    """``lower(trim(x))`` - the SAME expression the 0024 expression indexes
    are built on, so Postgres can use them."""
    return func.lower(func.trim(column))


class DocLookupRepository:
    def __init__(self, db: Session):
        self.db = db

    # ── stored history ───────────────────────────────────────────────────────

    def snapshot_sightings(
        self, tenant_id: str, company_id: str, entity_type: str, doc_no_norm: str,
    ) -> List[Tuple[AcPullSnapshot, AcPullSnapshotRow]]:
        """Every READY snapshot row of this company whose payload DocNo matches,
        newest snapshot first."""
        doc_no_expr = _norm_expr(AcPullSnapshotRow.payload_json["DocNo"].as_string())
        return (
            self.db.query(AcPullSnapshot, AcPullSnapshotRow)
            .join(
                AcPullSnapshotRow,
                (AcPullSnapshotRow.snapshot_id == AcPullSnapshot.id)
                & (AcPullSnapshotRow.tenant_id == AcPullSnapshot.tenant_id),
            )
            .filter(
                AcPullSnapshot.tenant_id == tenant_id,
                AcPullSnapshot.company_id == company_id,
                AcPullSnapshot.entity_type == entity_type,
                AcPullSnapshot.status == PULL_SNAPSHOT_STATUS_READY,
                AcPullSnapshotRow.tenant_id == tenant_id,
                AcPullSnapshotRow.company_id == company_id,
                doc_no_expr == doc_no_norm,
            )
            .order_by(AcPullSnapshot.created_at.desc(), AcPullSnapshotRow.row_index)
            .limit(MAX_SNAPSHOT_SIGHTINGS)
            .all()
        )

    def ledger_row(
        self, tenant_id: str, company_id: str, feed: str, doc_no_norm: str,
    ) -> Optional[AcDocFeedLedger]:
        return (
            self.db.query(AcDocFeedLedger)
            .filter(
                AcDocFeedLedger.tenant_id == tenant_id,
                AcDocFeedLedger.company_id == company_id,
                AcDocFeedLedger.feed == feed,
                _norm_expr(AcDocFeedLedger.doc_no) == doc_no_norm,
            )
            .order_by(AcDocFeedLedger.pushed_at.desc().nullslast())
            .first()
        )

    # ── hint (D5) ────────────────────────────────────────────────────────────

    def get_hint(
        self, tenant_id: str, company_id: str, doc_type: str, doc_no_norm: str,
    ) -> Optional[AcDocLookupHint]:
        return self.db.get(AcDocLookupHint, (tenant_id, company_id, doc_type, doc_no_norm))

    def save_hint(
        self, tenant_id: str, company_id: str, doc_type: str, doc_no_norm: str, *,
        doc_key: Optional[int], doc_date: Optional[date], last_modified: Optional[str],
    ) -> None:
        row = self.get_hint(tenant_id, company_id, doc_type, doc_no_norm)
        if row is None:
            row = AcDocLookupHint(
                tenant_id=tenant_id, company_id=company_id, doc_type=doc_type,
                doc_no_norm=doc_no_norm,
            )
            self.db.add(row)
        row.doc_key = doc_key
        row.doc_date = doc_date
        row.last_modified = last_modified
        row.found_at = datetime.now(timezone.utc)

    # ── settings (D7) ────────────────────────────────────────────────────────

    def get_settings(self, tenant_id: str, company_id: str) -> Optional[AcDocLookupSettings]:
        return self.db.get(AcDocLookupSettings, (tenant_id, company_id))

    def save_settings(
        self, tenant_id: str, company_id: str, *, back_days: int, forward_days: int,
    ) -> AcDocLookupSettings:
        row = self.get_settings(tenant_id, company_id)
        if row is None:
            row = AcDocLookupSettings(tenant_id=tenant_id, company_id=company_id)
            self.db.add(row)
        row.back_days = back_days
        row.forward_days = forward_days
        return row

    # ── jobs ─────────────────────────────────────────────────────────────────

    def lock_company(self, tenant_id: str, company_id: str) -> None:
        """``SELECT ... FOR UPDATE`` on the company row - serialises lookup
        starts per company. SQLAlchemy drops FOR UPDATE on SQLite (tests)."""
        (
            self.db.query(AcCompany.id)
            .filter(AcCompany.tenant_id == tenant_id, AcCompany.id == company_id)
            .with_for_update()
            .first()
        )

    def open_jobs(self, tenant_id: str, job_type: str) -> List[BackgroundJob]:
        return (
            self.db.query(BackgroundJob)
            .filter(
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.type == job_type,
                BackgroundJob.status.in_((JOB_PENDING, JOB_RUNNING)),
            )
            .order_by(BackgroundJob.created_at.desc())
            .all()
        )

    def get_job(self, tenant_id: str, job_type: str, job_id: str) -> Optional[BackgroundJob]:
        return (
            self.db.query(BackgroundJob)
            .filter(
                BackgroundJob.id == job_id,
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.type == job_type,
            )
            .first()
        )

    def job_status(self, job_id: str) -> Optional[str]:
        """Re-read FRESH (cooperative abort - a stop committed on another session)."""
        return self.db.query(BackgroundJob.status).filter(BackgroundJob.id == job_id).scalar()
