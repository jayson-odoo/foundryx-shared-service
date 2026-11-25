"""Doc-feed repositories (sprint-5/14) - pure SQLAlchemy, no business logic.

    !!  EVERY query below filters ``tenant_id`` AND ``company_id`` (AC-13-41
        precedent - one tenant may run several AutoCount companies).  !!
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import case, func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.background_job import JOB_ABORTED, JOB_PENDING, JOB_RUNNING, BackgroundJob

from ..models import (
    DOC_FEED_BACKFILL_STOPPED,
    DOC_FEED_KEYS,
    AcDocFeed,
    AcDocFeedBackfill,
    AcDocFeedIssue,
    AcDocFeedLedger,
    AcDocFeedRun,
    BACKFILL_AUTO_RESUMING_CODE,
    BACKFILL_DISCARDED_CODE,
    BACKFILL_USER_STOPPED_CODE,
    DOC_FEED_BACKFILL_DONE,
    DOC_FEED_BACKFILL_OPEN_STATUSES,
    DOC_FEED_BACKFILL_RUNNING,
    DOC_FEED_BACKFILL_STOPPING,
)


def _dialect_insert(db: Session, table):
    """S2 (review round 1) - the ONE real ``INSERT .. ON CONFLICT DO UPDATE``
    builder the ledger/issue upserts below share: Postgres in production,
    SQLite (the same generic construct, just a different dialect module)
    under pytest's ``create_all``. Poll and backfill legitimately race on
    the SAME ``(tenant, company, feed, book, doc_key)`` row (a backfill's
    tail days overlap the hourly poll, plan 3.6 step 5) - a plain
    get-then-add loses that race with an ``IntegrityError`` that then wedges
    the session into ``PendingRollbackError`` for the rest of the run."""
    if db.get_bind().dialect.name == "postgresql":
        return pg_insert(table)
    return sqlite_insert(table)


class DocFeedRepository:
    def list_for_tenant_feed(self, tenant_id: str, feed: str) -> List[AcDocFeed]:
        """Plan 72 - every company's row of one feed in this tenant."""
        return (
            self.db.query(AcDocFeed)
            .filter(AcDocFeed.tenant_id == tenant_id, AcDocFeed.feed == feed)
            .all()
        )

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
            .filter(
                AcDocFeed.tenant_id == tenant_id, AcDocFeed.company_id == company_id,
                # A retired `branches` row (old dev 0023) is never a feed.
                AcDocFeed.feed.in_(DOC_FEED_KEYS),
            )
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

    _PK = ("tenant_id", "company_id", "feed", "book", "doc_key")

    def upsert_delivered(
        self,
        tenant_id: str, company_id: str, feed: str, book: str, doc_key: int,
        *, doc_no: Optional[str], doc_date: Optional[date],
        source_modified_at: Optional[datetime], outcome: str, now: datetime,
        content_digest: Optional[str] = None,
    ) -> None:
        """A ``created``/``updated`` verdict (D11) - always overwrites.
        S2 - a real ``INSERT .. ON CONFLICT DO UPDATE`` (never a get-then-
        add): poll and backfill may race on the SAME new DocKey."""
        table = AcDocFeedLedger.__table__
        stmt = _dialect_insert(self.db, table).values(
            tenant_id=tenant_id, company_id=company_id, feed=feed, book=book,
            doc_key=doc_key, doc_no=doc_no, doc_date=doc_date,
            source_modified_at=source_modified_at, last_outcome=outcome,
            pushed_at=now, vanished_at=None, content_digest=content_digest,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=self._PK,
            set_={
                "doc_no": stmt.excluded.doc_no,
                "doc_date": stmt.excluded.doc_date,
                "source_modified_at": stmt.excluded.source_modified_at,
                "last_outcome": stmt.excluded.last_outcome,
                "pushed_at": stmt.excluded.pushed_at,
                "vanished_at": stmt.excluded.vanished_at,
                "content_digest": stmt.excluded.content_digest,
            },
        )
        self.db.execute(stmt)

    def insert_if_absent(
        self,
        tenant_id: str, company_id: str, feed: str, book: str, doc_key: int,
        *, doc_no: Optional[str], doc_date: Optional[date],
        source_modified_at: Optional[datetime], outcome: str, now: datetime,
    ) -> None:
        """A ``stale_ignored`` verdict (AC-14-56) - inserts a missing row so
        the sweep still has something to compare against, but NEVER
        overwrites a row already there (the CRM's own stale-guard rejected
        this copy precisely because it is older). S2 - ``DO NOTHING`` on the
        PK is the race-safe form of "insert only if absent"."""
        table = AcDocFeedLedger.__table__
        stmt = _dialect_insert(self.db, table).values(
            tenant_id=tenant_id, company_id=company_id, feed=feed, book=book,
            doc_key=doc_key, doc_no=doc_no, doc_date=doc_date,
            source_modified_at=source_modified_at, last_outcome=outcome,
            pushed_at=now, vanished_at=None,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=self._PK)
        self.db.execute(stmt)

    def set_digest(
        self, tenant_id: str, company_id: str, feed: str, book: str, doc_key: int,
        *, content_digest: str,
    ) -> None:
        """DOC-FEED-WINDOW - record the digest of content the CRM has now
        SEEN without touching anything else on the row (a ``stale_ignored``
        verdict: the CRM kept its newer copy, but this content must not be
        re-pushed by every re-check)."""
        (
            self.db.query(AcDocFeedLedger)
            .filter(
                AcDocFeedLedger.tenant_id == tenant_id,
                AcDocFeedLedger.company_id == company_id,
                AcDocFeedLedger.feed == feed,
                AcDocFeedLedger.book == book,
                AcDocFeedLedger.doc_key == doc_key,
            )
            .update({AcDocFeedLedger.content_digest: content_digest}, synchronize_session=False)
        )

    def digests_for(
        self, tenant_id: str, company_id: str, feed: str, book: str, doc_keys: List[int],
    ) -> Dict[int, Optional[str]]:
        """DOC-FEED-WINDOW - ``{doc_key: content_digest}`` for the given keys
        of (feed, book); a key with no ledger row is absent. Batched in
        chunks so a 180-day re-check never builds one giant ``IN``."""
        out: Dict[int, Optional[str]] = {}
        keys = list(doc_keys)
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            rows = (
                self.db.query(AcDocFeedLedger.doc_key, AcDocFeedLedger.content_digest)
                .filter(
                    AcDocFeedLedger.tenant_id == tenant_id,
                    AcDocFeedLedger.company_id == company_id,
                    AcDocFeedLedger.feed == feed,
                    AcDocFeedLedger.book == book,
                    AcDocFeedLedger.doc_key.in_(chunk),
                )
                .all()
            )
            for key, digest in rows:
                out[int(key)] = digest
        return out

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

    _PK = ("tenant_id", "company_id", "feed", "book", "doc_key")

    def upsert(
        self,
        tenant_id: str, company_id: str, feed: str, book: str, doc_key: int,
        *, kind: str, doc_no: Optional[str], doc_date: Optional[date],
        source_modified_at: Optional[datetime], record_json: Dict[str, Any],
        errors_json: Optional[Dict[str, Any]], warnings_json: Optional[List[str]],
        last_run_id: Optional[str], now: datetime,
    ) -> None:
        """S2 - a real ``INSERT .. ON CONFLICT DO UPDATE`` (poll and
        backfill may race on the SAME new DocKey). ``attempts`` starts at 1
        on a fresh row and increments in the SAME statement on a conflict -
        never a get-then-add-1 that a concurrent insert could race."""
        table = AcDocFeedIssue.__table__
        stmt = _dialect_insert(self.db, table).values(
            tenant_id=tenant_id, company_id=company_id, feed=feed, book=book,
            doc_key=doc_key, kind=kind, doc_no=doc_no, doc_date=doc_date,
            source_modified_at=source_modified_at, record_json=record_json,
            errors_json=errors_json, warnings_json=warnings_json, attempts=1,
            first_at=now, last_at=now, last_run_id=last_run_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=self._PK,
            set_={
                "kind": stmt.excluded.kind,
                "doc_no": stmt.excluded.doc_no,
                "doc_date": stmt.excluded.doc_date,
                "source_modified_at": stmt.excluded.source_modified_at,
                "record_json": stmt.excluded.record_json,
                "errors_json": stmt.excluded.errors_json,
                "warnings_json": stmt.excluded.warnings_json,
                "attempts": table.c.attempts + 1,
                "last_at": stmt.excluded.last_at,
                "last_run_id": stmt.excluded.last_run_id,
            },
        )
        self.db.execute(stmt)

    def delete(
        self, tenant_id: str, company_id: str, feed: str, book: str, doc_key: int
    ) -> None:
        row = self.get(tenant_id, company_id, feed, book, doc_key)
        if row is not None:
            self.db.delete(row)
            self.db.flush()

    def records_for(
        self, tenant_id: str, company_id: str, feed: str, book: str, doc_keys: List[int],
    ) -> Dict[int, Any]:
        """DOC-FEED-WINDOW - ``{doc_key: stored record_json}`` of the open
        issue rows (either kind) among ``doc_keys``; chunked like
        ``DocFeedLedgerRepository.digests_for``."""
        out: Dict[int, Any] = {}
        keys = list(doc_keys)
        for i in range(0, len(keys), 500):
            rows = (
                self.db.query(AcDocFeedIssue.doc_key, AcDocFeedIssue.record_json)
                .filter(
                    AcDocFeedIssue.tenant_id == tenant_id,
                    AcDocFeedIssue.company_id == company_id,
                    AcDocFeedIssue.feed == feed,
                    AcDocFeedIssue.book == book,
                    AcDocFeedIssue.doc_key.in_(keys[i:i + 500]),
                )
                .all()
            )
            for key, record in rows:
                out[int(key)] = record
        return out

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

    def open_for_book(self, tenant_id: str, book: str) -> Optional[AcDocFeedBackfill]:
        """Plan 72 - a backfill (any feed, any company) still reading ``book``
        (running or stopping; a stopped one reads nothing): one backfill per
        book at a time keeps one AutoCount call in flight."""
        return (
            self.db.query(AcDocFeedBackfill)
            .filter(
                AcDocFeedBackfill.tenant_id == tenant_id,
                AcDocFeedBackfill.book == book,
                AcDocFeedBackfill.status.in_(
                    (DOC_FEED_BACKFILL_RUNNING, DOC_FEED_BACKFILL_STOPPING)
                ),
            )
            .first()
        )

    def running_for_feed(self, tenant_id: str, feed_id: str) -> Optional[AcDocFeedBackfill]:
        """Plan 72 - this feed's backfill that is still reading (running or stopping)."""
        return (
            self.db.query(AcDocFeedBackfill)
            .filter(
                AcDocFeedBackfill.tenant_id == tenant_id,
                AcDocFeedBackfill.feed_id == feed_id,
                AcDocFeedBackfill.status.in_(
                    (DOC_FEED_BACKFILL_RUNNING, DOC_FEED_BACKFILL_STOPPING)
                ),
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

    def earliest_completed_live_from_day(self, tenant_id: str, feed_id: str) -> Optional[date]:
        """SLOW-MOVING-BACKFILL S0.3 - the earliest from-day a LIVE backfill
        of this feed ran to completion from (dry runs and discarded rows never
        count). The run-once guard compares a new full-history request against
        this, not against the floor constant, so moving the floor earlier
        re-opens exactly one run from the new floor."""
        return (
            self.db.query(func.min(AcDocFeedBackfill.from_day))
            .filter(
                AcDocFeedBackfill.tenant_id == tenant_id,
                AcDocFeedBackfill.feed_id == feed_id,
                AcDocFeedBackfill.status == DOC_FEED_BACKFILL_DONE,
                AcDocFeedBackfill.dry_run.is_(False),
                or_(
                    AcDocFeedBackfill.error_code.is_(None),
                    AcDocFeedBackfill.error_code != BACKFILL_DISCARDED_CODE,
                ),
            )
            .scalar()
        )

    def in_flight(
        self, *, tenant_id: Optional[str] = None, feed_id: Optional[str] = None
    ) -> List[AcDocFeedBackfill]:
        """SS-BACKFILL-CHUNKED - every backfill still marked as reading
        (running or stopping), for the stale-row reaper. ``tenant_id=None``
        is the beat's cross-tenant pass; the service narrows to one feed."""
        query = self.db.query(AcDocFeedBackfill).filter(
            AcDocFeedBackfill.status.in_((DOC_FEED_BACKFILL_RUNNING, DOC_FEED_BACKFILL_STOPPING))
        )
        if tenant_id is not None:
            query = query.filter(AcDocFeedBackfill.tenant_id == tenant_id)
        if feed_id is not None:
            query = query.filter(AcDocFeedBackfill.feed_id == feed_id)
        return query.all()

    def job_for(self, tenant_id: str, job_id: Optional[str]) -> Optional[BackgroundJob]:
        if not job_id:
            return None
        return (
            self.db.query(BackgroundJob)
            .filter(BackgroundJob.tenant_id == tenant_id, BackgroundJob.id == job_id)
            .first()
        )

    def abort_pending_job(self, tenant_id: str, job_id: Optional[str], *, now: datetime) -> bool:
        """Guarded ``pending -> aborted`` (a queued segment no worker has
        claimed yet). False when a worker already claimed it - the caller
        then falls back to the cooperative ``stopping``."""
        if not job_id:
            return False
        count = (
            self.db.query(BackgroundJob)
            .filter(
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.id == job_id,
                BackgroundJob.status == JOB_PENDING,
            )
            .update(
                {
                    BackgroundJob.status: JOB_ABORTED,
                    BackgroundJob.error: "Stopped before it started.",
                    BackgroundJob.finished_at: now,
                },
                synchronize_session=False,
            )
        )
        return count > 0

    def stop_if_job_unchanged(
        self, tenant_id: str, backfill_id: str, seen_job_id: Optional[str],
        *, error: str, error_code: str,
    ) -> bool:
        """SS-BACKFILL-CHUNKED reaper - ``running|stopping -> stopped`` only
        while the row still points at ``seen_job_id``. No commit."""
        job_match = (
            AcDocFeedBackfill.job_id.is_(None) if seen_job_id is None
            else AcDocFeedBackfill.job_id == seen_job_id
        )
        count = (
            self.db.query(AcDocFeedBackfill)
            .filter(
                AcDocFeedBackfill.tenant_id == tenant_id,
                AcDocFeedBackfill.id == backfill_id,
                AcDocFeedBackfill.status.in_((DOC_FEED_BACKFILL_RUNNING, DOC_FEED_BACKFILL_STOPPING)),
                job_match,
            )
            .update(
                {
                    AcDocFeedBackfill.status: DOC_FEED_BACKFILL_STOPPED,
                    AcDocFeedBackfill.error: error,
                    # SS-BACKFILL-AUTO-RESUME - a row a person was stopping
                    # stays a user Stop (never auto-resumed), whatever ended
                    # its job.
                    AcDocFeedBackfill.error_code: case(
                        (AcDocFeedBackfill.status == DOC_FEED_BACKFILL_STOPPING,
                         BACKFILL_USER_STOPPED_CODE),
                        else_=error_code,
                    ),
                },
                synchronize_session=False,
            )
        )
        return count > 0

    def stopped_by_worker_loss(
        self, codes: Tuple[str, ...], *, stale_claim_before: datetime, scope=None,
    ) -> List[AcDocFeedBackfill]:
        """SS-BACKFILL-AUTO-RESUME - every stopped backfill, across tenants
        (the beat's pass), whose worker was lost (``codes``), plus a claim
        (``AUTO_RESUMING``) older than ``stale_claim_before`` - the beat that
        claimed it died before it resumed. ``scope`` narrows the query to
        active tenants / modules (the sweep's own join)."""
        query = self.db.query(AcDocFeedBackfill)
        if scope is not None:
            query = scope(query, AcDocFeedBackfill.tenant_id)
        return (
            query.filter(
                AcDocFeedBackfill.status == DOC_FEED_BACKFILL_STOPPED,
                or_(
                    AcDocFeedBackfill.error_code.in_(codes),
                    (AcDocFeedBackfill.error_code == BACKFILL_AUTO_RESUMING_CODE)
                    & (AcDocFeedBackfill.updated_at < stale_claim_before),
                ),
            )
            .all()
        )

    def claim_for_auto_resume(
        self, tenant_id: str, backfill_id: str, seen_code: str,
        *, now: Optional[datetime] = None, stale_claim_before: Optional[datetime] = None,
    ) -> bool:
        """Guarded ``seen_code -> AUTO_RESUMING`` on a stopped row: two beats
        that judged the same row never both claim it (a stale claim is taken
        over only while it is still stale). No commit."""
        query = self.db.query(AcDocFeedBackfill).filter(
            AcDocFeedBackfill.tenant_id == tenant_id,
            AcDocFeedBackfill.id == backfill_id,
            AcDocFeedBackfill.status == DOC_FEED_BACKFILL_STOPPED,
            AcDocFeedBackfill.error_code == seen_code,
        )
        if seen_code == BACKFILL_AUTO_RESUMING_CODE:
            if stale_claim_before is None:
                return False
            query = query.filter(AcDocFeedBackfill.updated_at < stale_claim_before)
        values: Dict[Any, Any] = {AcDocFeedBackfill.error_code: BACKFILL_AUTO_RESUMING_CODE}
        if now is not None:
            values[AcDocFeedBackfill.updated_at] = now
        return query.update(values, synchronize_session=False) > 0

    def start_resume(
        self, tenant_id: str, backfill_id: str, seen_job_id: Optional[str], new_job_id: str,
        *, summary: Optional[Dict[str, Any]], require_code: Optional[str] = None,
    ) -> bool:
        """Guarded ``stopped -> running`` under ``new_job_id`` while the row
        still points at the job the caller judged: a person's Resume and the
        beat's automatic one never both start a segment. No commit."""
        job_match = (
            AcDocFeedBackfill.job_id.is_(None) if seen_job_id is None
            else AcDocFeedBackfill.job_id == seen_job_id
        )
        query = self.db.query(AcDocFeedBackfill).filter(
            AcDocFeedBackfill.tenant_id == tenant_id,
            AcDocFeedBackfill.id == backfill_id,
            AcDocFeedBackfill.status == DOC_FEED_BACKFILL_STOPPED,
            job_match,
        )
        if require_code is not None:
            # The beat's own claim must still stand (a Stop pressed in the
            # meantime replaced it with USER_STOPPED).
            query = query.filter(AcDocFeedBackfill.error_code == require_code)
        count = (
            query
            .update(
                {
                    AcDocFeedBackfill.status: DOC_FEED_BACKFILL_RUNNING,
                    AcDocFeedBackfill.job_id: new_job_id,
                    AcDocFeedBackfill.error: None,
                    AcDocFeedBackfill.error_code: None,
                    AcDocFeedBackfill.summary_json: summary,
                },
                synchronize_session=False,
            )
        )
        return count > 0

    def release_auto_resume_claim(self, tenant_id: str, backfill_id: str, code: str) -> None:
        """Undo ``claim_for_auto_resume`` when the resume was refused (the
        next beat tries again). No commit."""
        (
            self.db.query(AcDocFeedBackfill)
            .filter(
                AcDocFeedBackfill.tenant_id == tenant_id,
                AcDocFeedBackfill.id == backfill_id,
                AcDocFeedBackfill.status == DOC_FEED_BACKFILL_STOPPED,
                AcDocFeedBackfill.error_code == BACKFILL_AUTO_RESUMING_CODE,
            )
            .update({AcDocFeedBackfill.error_code: code}, synchronize_session=False)
        )

    def done_dry_runs_overlapping(
        self, tenant_id: str, feed_id: str, from_day: date, to_day: date
    ) -> List[AcDocFeedBackfill]:
        """SS-BACKFILL-CHUNKED (AC-BFC-4) - every finished (never discarded)
        dry run of this feed that touches ``from_day..to_day``, oldest first;
        the service checks they cover the range together."""
        return (
            self.db.query(AcDocFeedBackfill)
            .filter(
                AcDocFeedBackfill.tenant_id == tenant_id,
                AcDocFeedBackfill.feed_id == feed_id,
                AcDocFeedBackfill.dry_run.is_(True),
                AcDocFeedBackfill.status == DOC_FEED_BACKFILL_DONE,
                or_(
                    AcDocFeedBackfill.error_code.is_(None),
                    AcDocFeedBackfill.error_code != BACKFILL_DISCARDED_CODE,
                ),
                AcDocFeedBackfill.from_day <= to_day,
                AcDocFeedBackfill.to_day >= from_day,
            )
            .order_by(AcDocFeedBackfill.from_day)
            .all()
        )

    def add(self, backfill: AcDocFeedBackfill) -> AcDocFeedBackfill:
        self.db.add(backfill)
        self.db.flush()
        return backfill

    def job_is_live(self, tenant_id: str, job_id: Optional[str]) -> bool:
        """B2 (review round 1) - whether ``job_id`` still names a pending or
        running ``background_jobs`` row. ``Resume`` refuses (409) while this
        is true: the OLD worker may still be physically alive between the
        moment it commits ``backfill.status = stopped`` and the moment it
        finishes its own job row, and a Resume landing in that window would
        enqueue a SECOND job racing the first on the same days (S2's ledger/
        issue PK race). A falsy ``job_id`` (never dispatched, or a legacy
        row) is never live."""
        if not job_id:
            return False
        return (
            self.db.query(BackgroundJob)
            .filter(
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.id == job_id,
                BackgroundJob.status.in_((JOB_PENDING, JOB_RUNNING)),
            )
            .first()
            is not None
        )
