"""Doc-feed repositories (sprint-5/14) - pure SQLAlchemy, no business logic.

    !!  EVERY query below filters ``tenant_id`` AND ``company_id`` (AC-13-41
        precedent - one tenant may run several AutoCount companies).  !!
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.background_job import JOB_PENDING, JOB_RUNNING, BackgroundJob

from ..models import (
    AcDocFeed,
    AcDocFeedBackfill,
    AcDocFeedIssue,
    AcDocFeedLedger,
    AcDocFeedRun,
    DOC_FEED_BACKFILL_OPEN_STATUSES,
)


class DocFeedRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, tenant_id: str, feed_id: str) -> Optional[AcDocFeed]:
        return (
            self.db.query(AcDocFeed)
            .filter(AcDocFeed.tenant_id == tenant_id, AcDocFeed.id == feed_id)
            .first()
        )

    def get(self, tenant_id: str, company_id: str, feed: str) -> Optional[AcDocFeed]:
        return (
            self.db.query(AcDocFeed)
            .filter(
                AcDocFeed.tenant_id == tenant_id,
                AcDocFeed.company_id == company_id,
                AcDocFeed.feed == feed,
            )
            .first()
        )

    def list_for_company(self, tenant_id: str, company_id: str) -> List[AcDocFeed]:
        return (
            self.db.query(AcDocFeed)
            .filter(AcDocFeed.tenant_id == tenant_id, AcDocFeed.company_id == company_id)
            .all()
        )

    def unfinished_job(
        self, tenant_id: str, job_type: str, feed_id: str
    ) -> Optional[BackgroundJob]:
        """A pending/running ``job_type`` job for THIS feed (the RUN_IN_FLIGHT
        409 / the scheduler's own busy-feed skip). Core ``background_jobs`` -
        module-owned knowledge (the ``feedId`` payload key) belongs here, not
        the generic ``JobService``."""
        return (
            self.db.query(BackgroundJob)
            .filter(
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.type == job_type,
                BackgroundJob.status.in_((JOB_PENDING, JOB_RUNNING)),
                BackgroundJob.payload_json["feedId"].as_string() == feed_id,
            )
            .first()
        )

    def get_or_create(self, tenant_id: str, company_id: str, feed: str) -> AcDocFeed:
        row = self.get(tenant_id, company_id, feed)
        if row is not None:
            return row
        row = AcDocFeed(tenant_id=tenant_id, company_id=company_id, feed=feed)
        self.db.add(row)
        self.db.flush()
        return row


class DocFeedLedgerRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(
        self, tenant_id: str, company_id: str, feed: str, book: str, doc_key: int
    ) -> Optional[AcDocFeedLedger]:
        return (
            self.db.query(AcDocFeedLedger)
            .filter(
                AcDocFeedLedger.tenant_id == tenant_id,
                AcDocFeedLedger.company_id == company_id,
                AcDocFeedLedger.feed == feed,
                AcDocFeedLedger.book == book,
                AcDocFeedLedger.doc_key == doc_key,
            )
            .first()
        )

    def upsert_delivered(
        self,
        tenant_id: str, company_id: str, feed: str, book: str, doc_key: int,
        *, doc_no: Optional[str], doc_date: Optional[date],
        source_modified_at: Optional[datetime], outcome: str, now: datetime,
    ) -> None:
        """A ``created``/``updated`` verdict (D11) - always overwrites."""
        row = self.get(tenant_id, company_id, feed, book, doc_key)
        if row is None:
            row = AcDocFeedLedger(
                tenant_id=tenant_id, company_id=company_id, feed=feed, book=book,
                doc_key=doc_key,
            )
            self.db.add(row)
        row.doc_no = doc_no
        row.doc_date = doc_date
        row.source_modified_at = source_modified_at
        row.last_outcome = outcome
        row.pushed_at = now
        row.vanished_at = None
        self.db.flush()

    def insert_if_absent(
        self,
        tenant_id: str, company_id: str, feed: str, book: str, doc_key: int,
        *, doc_no: Optional[str], doc_date: Optional[date],
        source_modified_at: Optional[datetime], outcome: str, now: datetime,
    ) -> None:
        """A ``stale_ignored`` verdict (AC-14-56) - inserts a missing row so
        the sweep still has something to compare against, but NEVER
        overwrites a row already there (the CRM's own stale-guard rejected
        this copy precisely because it is older)."""
        row = self.get(tenant_id, company_id, feed, book, doc_key)
        if row is not None:
            return
        row = AcDocFeedLedger(
            tenant_id=tenant_id, company_id=company_id, feed=feed, book=book,
            doc_key=doc_key, doc_no=doc_no, doc_date=doc_date,
            source_modified_at=source_modified_at, last_outcome=outcome,
            pushed_at=now, vanished_at=None,
        )
        self.db.add(row)
        self.db.flush()

    def window_rows(
        self, tenant_id: str, company_id: str, feed: str, book: str,
        *, day_from: date, day_to: date,
    ) -> List[AcDocFeedLedger]:
        """Not-yet-vanished rows of (feed, book) whose ``doc_date`` falls in
        the sweep window (D12)."""
        return (
            self.db.query(AcDocFeedLedger)
            .filter(
                AcDocFeedLedger.tenant_id == tenant_id,
                AcDocFeedLedger.company_id == company_id,
                AcDocFeedLedger.feed == feed,
                AcDocFeedLedger.book == book,
                AcDocFeedLedger.doc_date.isnot(None),
                AcDocFeedLedger.doc_date >= day_from,
                AcDocFeedLedger.doc_date <= day_to,
                AcDocFeedLedger.vanished_at.is_(None),
            )
            .all()
        )

    def mark_vanished(
        self, tenant_id: str, company_id: str, feed: str, book: str, doc_key: int,
        *, now: datetime,
    ) -> None:
        row = self.get(tenant_id, company_id, feed, book, doc_key)
        if row is not None:
            row.vanished_at = now
            self.db.flush()

    def clear_vanished(
        self, tenant_id: str, company_id: str, feed: str, book: str, doc_key: int,
    ) -> None:
        row = self.get(tenant_id, company_id, feed, book, doc_key)
        if row is not None and row.vanished_at is not None:
            row.vanished_at = None
            self.db.flush()


class DocFeedIssueRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(
        self, tenant_id: str, company_id: str, feed: str, book: str, doc_key: int
    ) -> Optional[AcDocFeedIssue]:
        return (
            self.db.query(AcDocFeedIssue)
            .filter(
                AcDocFeedIssue.tenant_id == tenant_id,
                AcDocFeedIssue.company_id == company_id,
                AcDocFeedIssue.feed == feed,
                AcDocFeedIssue.book == book,
                AcDocFeedIssue.doc_key == doc_key,
            )
            .first()
        )

    def upsert(
        self,
        tenant_id: str, company_id: str, feed: str, book: str, doc_key: int,
        *, kind: str, doc_no: Optional[str], doc_date: Optional[date],
        source_modified_at: Optional[datetime], record_json: Dict[str, Any],
        errors_json: Optional[Dict[str, Any]], warnings_json: Optional[List[str]],
        last_run_id: Optional[str], now: datetime,
    ) -> None:
        row = self.get(tenant_id, company_id, feed, book, doc_key)
        if row is None:
            row = AcDocFeedIssue(
                tenant_id=tenant_id, company_id=company_id, feed=feed, book=book,
                doc_key=doc_key, attempts=0, first_at=now,
            )
            self.db.add(row)
        row.kind = kind
        row.doc_no = doc_no
        row.doc_date = doc_date
        row.source_modified_at = source_modified_at
        row.record_json = record_json
        row.errors_json = errors_json
        row.warnings_json = warnings_json
        row.attempts = (row.attempts or 0) + 1
        row.last_at = now
        row.last_run_id = last_run_id
        self.db.flush()

    def delete(
        self, tenant_id: str, company_id: str, feed: str, book: str, doc_key: int
    ) -> None:
        row = self.get(tenant_id, company_id, feed, book, doc_key)
        if row is not None:
            self.db.delete(row)
            self.db.flush()

    def list_retryable(self, tenant_id: str, company_id: str, feed: str, book: str) -> List[AcDocFeedIssue]:
        return (
            self.db.query(AcDocFeedIssue)
            .filter(
                AcDocFeedIssue.tenant_id == tenant_id,
                AcDocFeedIssue.company_id == company_id,
                AcDocFeedIssue.feed == feed,
                AcDocFeedIssue.book == book,
                AcDocFeedIssue.kind == "retryable",
            )
            .all()
        )

    def counts(self, tenant_id: str, company_id: str, feed: str) -> Dict[str, int]:
        rows = (
            self.db.query(AcDocFeedIssue.kind)
            .filter(
                AcDocFeedIssue.tenant_id == tenant_id,
                AcDocFeedIssue.company_id == company_id,
                AcDocFeedIssue.feed == feed,
            )
            .all()
        )
        counts = {"retryable": 0, "failed": 0}
        for (kind,) in rows:
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    def list(
        self, tenant_id: str, company_id: str,
        *, feed: Optional[str] = None, kind: Optional[str] = None,
        search: Optional[str] = None, page: int = 0, page_size: int = 25,
    ) -> Tuple[List[AcDocFeedIssue], int]:
        query = self.db.query(AcDocFeedIssue).filter(
            AcDocFeedIssue.tenant_id == tenant_id,
            AcDocFeedIssue.company_id == company_id,
        )
        if feed:
            query = query.filter(AcDocFeedIssue.feed == feed)
        if kind:
            query = query.filter(AcDocFeedIssue.kind == kind)
        if search:
            like = f"%{search.strip()}%"
            query = query.filter(AcDocFeedIssue.doc_no.ilike(like))
        total = query.count()
        rows = (
            query.order_by(AcDocFeedIssue.last_at.desc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total


class DocFeedRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, run: AcDocFeedRun) -> AcDocFeedRun:
        self.db.add(run)
        self.db.flush()
        return run

    def latest_for_feed(self, tenant_id: str, company_id: str, feed_id: str) -> Optional[AcDocFeedRun]:
        return (
            self.db.query(AcDocFeedRun)
            .filter(
                AcDocFeedRun.tenant_id == tenant_id,
                AcDocFeedRun.company_id == company_id,
                AcDocFeedRun.feed_id == feed_id,
            )
            .order_by(AcDocFeedRun.started_at.desc())
            .first()
        )

    def list(
        self, tenant_id: str, company_id: str,
        *, feed: Optional[str] = None, page: int = 0, page_size: int = 25,
    ) -> Tuple[List[AcDocFeedRun], int]:
        query = self.db.query(AcDocFeedRun).filter(
            AcDocFeedRun.tenant_id == tenant_id, AcDocFeedRun.company_id == company_id,
        )
        if feed:
            query = query.filter(AcDocFeedRun.feed == feed)
        total = query.count()
        rows = (
            query.order_by(AcDocFeedRun.started_at.desc())
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total


class DocFeedBackfillRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, tenant_id: str, backfill_id: str) -> Optional[AcDocFeedBackfill]:
        return (
            self.db.query(AcDocFeedBackfill)
            .filter(AcDocFeedBackfill.tenant_id == tenant_id, AcDocFeedBackfill.id == backfill_id)
            .first()
        )

    def open_for_feed(self, tenant_id: str, feed_id: str) -> Optional[AcDocFeedBackfill]:
        return (
            self.db.query(AcDocFeedBackfill)
            .filter(
                AcDocFeedBackfill.tenant_id == tenant_id,
                AcDocFeedBackfill.feed_id == feed_id,
                AcDocFeedBackfill.status.in_(DOC_FEED_BACKFILL_OPEN_STATUSES),
            )
            .first()
        )

    def latest_for_feed(self, tenant_id: str, feed_id: str) -> Optional[AcDocFeedBackfill]:
        return (
            self.db.query(AcDocFeedBackfill)
            .filter(AcDocFeedBackfill.tenant_id == tenant_id, AcDocFeedBackfill.feed_id == feed_id)
            .order_by(AcDocFeedBackfill.started_at.desc())
            .first()
        )

    def add(self, backfill: AcDocFeedBackfill) -> AcDocFeedBackfill:
        self.db.add(backfill)
        self.db.flush()
        return backfill
