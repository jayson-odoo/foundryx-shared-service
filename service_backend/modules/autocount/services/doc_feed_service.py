"""``DocFeedService`` (sprint-5/14, D2) - configuration, run dispatch and
history for the DO/GRN HTTP source.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.jobs.service import JobService
from app.models.background_job import JOB_FAILED, JOB_TERMINAL_STATUSES

from ..doc_feed.clock import myt_date
from ..doc_feed.constants import (
    ALL_FEEDS,
    BACKFILL_FROM_DEFAULT,
    DOC_FEED_BACKFILL_JOB_TYPE,
    DOC_FEED_RUN_JOB_TYPE,
    DOCUMENT_FEEDS,
)
from ..doc_feed.jobs import run_doc_feed_backfill_job, run_doc_feed_job
from ..doc_feed.schedule import (
    next_poll_at,
    next_sweep_at,
    poll_changed,
    resolve_schedule,
    sweep_changed,
    validate_doc_feed_schedule,
)
from ..doc_feed.window import resolve_window, validate_doc_feed_window
from ..http_source.book import derive_book
from ..models import (
    DOC_FEED_BACKFILL_RUNNING,
    DOC_FEED_BACKFILL_STOPPED,
    DOC_FEED_MODE_DRY_RUN,
    DOC_FEED_MODE_OFF,
    DOC_FEED_MODE_PUSH,
    DOC_FEED_MODES,
    AcCompany,
    AcDocFeed,
    AcDocFeedBackfill,
)
from ..provider import AUTH_NONE, PROVIDER_KEY, auth_mode
from ..repositories import CompanyRepository, ConnectionRepository
from ..repositories.doc_feed_repository import (
    DocFeedBackfillRepository,
    DocFeedIssueRepository,
    DocFeedLedgerRepository,
    DocFeedRepository,
    DocFeedRunRepository,
)
from ..schemas import (
    DocFeedBackfillOut,
    DocFeedContractGateOut,
    DocFeedIssueListOut,
    DocFeedIssueOut,
    DocFeedItemOut,
    DocFeedRunListOut,
    DocFeedRunOut,
    DocFeedScheduleOut,
    DocFeedsViewOut,
    DocFeedWindowOut,
    EligibleConnectionOut,
)
from .company_service import CompanyNotFound, CompanyService

logger = logging.getLogger("foundryx.autocount")


class DocFeedError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DocFeedValidationError(DocFeedError):
    """A save-time or action-time field 422 - the router renders
    ``{fieldErrors: {field: message}}`` (plan section 3.2)."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class DocFeedConflictError(DocFeedError):
    """A 409 - ``code`` is one of ``RUN_IN_FLIGHT`` / ``BACKFILL_OPEN`` /
    ``BACKFILL_ALREADY_DONE``. ``str()`` carries the code first (mirrors
    ``SinkAnchorError``) so a caller that only inspects the exception's
    text (the service-level tests, never the HTTP layer) can still assert
    on it."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        # Bypasses `DocFeedError.__init__` (which would overwrite
        # `self.message` with the combined string) - `Exception.__init__`
        # only sets the args `str()` reads.
        Exception.__init__(self, f"{code}: {message}")


class DocFeedService:
    def __init__(self, db: Session):
        self.db = db
        self.companies = CompanyRepository(db)
        self.connections = ConnectionRepository(db)
        self.company_service = CompanyService(db)
        self.feeds = DocFeedRepository(db)
        self.ledger = DocFeedLedgerRepository(db)
        self.issues = DocFeedIssueRepository(db)
        self.runs = DocFeedRunRepository(db)
        self.backfills = DocFeedBackfillRepository(db)

    # ── shared ────────────────────────────────────────────────────────────────

    def _company(self, tenant_id: str, company_id: str) -> AcCompany:
        company = self.companies.get(tenant_id, company_id)
        if company is None:
            raise CompanyNotFound("That AutoCount company was not found.")
        return company

    def eligible_connections(self, tenant_id: str) -> List[Tuple[Any, str]]:
        """AC-14-02 - open (no-auth) ``autocount`` connections whose base URL
        ends in a book-shaped segment (13.2)."""
        out: List[Tuple[Any, str]] = []
        for conn in self.connections.list_for_provider(tenant_id, PROVIDER_KEY):
            if auth_mode(conn.config_json or {}) != AUTH_NONE:
                continue
            book = derive_book(str((conn.config_json or {}).get("baseUrl") or ""))
            if not book:
                continue
            out.append((conn, book))
        return out

    # ── view ─────────────────────────────────────────────────────────────────

    def view(self, tenant_id: str, company_id: str) -> DocFeedsViewOut:
        company = self._company(tenant_id, company_id)
        eligible = self.eligible_connections(tenant_id)
        items = [self._item_out(tenant_id, company, feed) for feed in ALL_FEEDS]
        return DocFeedsViewOut(
            feeds=items,
            eligibleConnections=[
                EligibleConnectionOut(id=conn.id, name=conn.name, book=book)
                for conn, book in eligible
            ],
        )

    def _item_out(self, tenant_id: str, company: AcCompany, feed: str) -> DocFeedItemOut:
        row = self.feeds.get(tenant_id, company.id, feed)
        gate = self.company_service.doc_feed_gate_error(tenant_id, company, feed)
        counts = self.issues.counts(tenant_id, company.id, feed)
        last_run = self.runs.latest_for_feed(tenant_id, company.id, row.id) if row else None
        backfill = (
            self.backfills.latest_for_feed(tenant_id, row.id)
            if row and feed in DOCUMENT_FEEDS else None
        )
        return DocFeedItemOut(
            feed=feed,
            mode=row.mode if row else DOC_FEED_MODE_OFF,
            schedule=DocFeedScheduleOut(**resolve_schedule(row.schedule_config if row else None)),
            window=DocFeedWindowOut(**resolve_window(row.window_config if row else None)),
            connectionId=row.connection_id if row else None,
            book=row.book if row else None,
            cursorDay=row.cursor_day if row else None,
            nextPollAt=row.next_poll_at if row else None,
            nextSweepAt=row.next_sweep_at if row else None,
            lastPollAt=row.last_poll_at if row else None,
            lastPollOkAt=row.last_poll_ok_at if row else None,
            lastSweepOkAt=row.last_sweep_ok_at if row else None,
            fullBackfillDoneAt=row.full_backfill_done_at if row else None,
            contractGate=DocFeedContractGateOut(**gate) if gate else None,
            retryableCount=counts.get("retryable", 0),
            failedCount=counts.get("failed", 0),
            lastRun=DocFeedRunOut.model_validate(last_run) if last_run else None,
            backfill=DocFeedBackfillOut.model_validate(backfill) if backfill else None,
        )

    # ── configure (AC-14-03..06) ─────────────────────────────────────────────

    def update(
        self, tenant_id: str, company_id: str, feed: str,
        *, connection_id: Optional[str], mode: str, clear_connection: bool = False,
        schedule: Optional[Dict[str, Any]] = None,
        window: Optional[Dict[str, Any]] = None,
    ) -> DocFeedItemOut:
        company = self._company(tenant_id, company_id)
        if feed not in ALL_FEEDS:
            raise DocFeedValidationError("feed", "Unknown feed.")
        if mode not in DOC_FEED_MODES:
            raise DocFeedValidationError("mode", "Unknown mode.")
        # sprint-5/19 - validated BEFORE any write, with the Entities rule set
        # (a rejected schedule leaves mode/connection untouched too).
        clean_schedule: Optional[Dict[str, Any]] = None
        if schedule is not None:
            clean_schedule, schedule_errors = validate_doc_feed_schedule(schedule)
            if schedule_errors:
                field, message = next(iter(schedule_errors.items()))
                raise DocFeedValidationError(field, message)
        # DOC-FEED-WINDOW - same before-any-write rule. The window changes
        # what a run reads, never when it runs, so nothing re-arms on it.
        clean_window: Optional[Dict[str, Any]] = None
        if window is not None:
            clean_window, window_errors = validate_doc_feed_window(window)
            if window_errors:
                field, message = next(iter(window_errors.items()))
                raise DocFeedValidationError(field, message)

        row = self.feeds.get_or_create(tenant_id, company_id, feed)

        resolved_conn = None
        if connection_id is not None:
            eligible_ids = {conn.id for conn, _book in self.eligible_connections(tenant_id)}
            candidate = self.connections.get_for_provider(tenant_id, connection_id, PROVIDER_KEY)
            if candidate is None or candidate.id not in eligible_ids:
                raise DocFeedValidationError(
                    "connectionId",
                    "That connection is not an eligible open (no-auth) AutoCount "
                    "connection with a usable book.",
                )
            resolved_conn = candidate
        elif clear_connection:
            # N4 - an EXPLICIT `connectionId: null` clears the stored
            # connection; a feed with no connection can only be Off.
            if mode != DOC_FEED_MODE_OFF:
                raise DocFeedValidationError("connectionId", "Choose a connection first.")
        elif mode != DOC_FEED_MODE_OFF and not row.connection_id:
            raise DocFeedValidationError("connectionId", "Choose a connection first.")

        if mode in (DOC_FEED_MODE_DRY_RUN, DOC_FEED_MODE_PUSH):
            gate = self.company_service.doc_feed_gate_error(tenant_id, company, feed)
            if gate is not None:
                raise DocFeedValidationError("mode", self._gate_message(gate, feed))

        if resolved_conn is not None:
            row.connection_id = resolved_conn.id
            row.book = derive_book(str((resolved_conn.config_json or {}).get("baseUrl") or ""))
        elif clear_connection:
            row.connection_id = None
            row.book = None

        was_armed = row.mode not in (DOC_FEED_MODE_OFF, None)
        previous_schedule = resolve_schedule(row.schedule_config)
        if clean_schedule is not None:
            row.schedule_config = clean_schedule
        if clean_window is not None:
            row.window_config = clean_window
        effective = resolve_schedule(row.schedule_config)
        row.mode = mode
        now = datetime.now(timezone.utc)
        if mode == DOC_FEED_MODE_OFF:
            row.next_poll_at = None
            row.next_sweep_at = None
        elif not was_armed:
            row.next_poll_at = now
            if feed in DOCUMENT_FEEDS:
                row.next_sweep_at = next_sweep_at(effective, now)
        else:
            # sprint-5/19 (R4) - only the CHANGED half re-arms, from now; the
            # other keeps its due time (editing the poll never delays a sweep).
            if poll_changed(previous_schedule, effective):
                row.next_poll_at = next_poll_at(effective, now)
            if feed in DOCUMENT_FEEDS and sweep_changed(previous_schedule, effective):
                row.next_sweep_at = next_sweep_at(effective, now)

        self.db.commit()
        self.db.refresh(row)
        return self._item_out(tenant_id, company, feed)

    @staticmethod
    def _gate_message(gate: Dict[str, Any], feed: str) -> str:
        if gate.get("reason") == "config_error":
            return (
                "This company's Sorento push target is not fully configured "
                "yet (a connection and a company code are both required)."
            )
        version = gate.get("version")
        if version is None:
            return (
                f"The Sorento consumer's contract could not be confirmed to "
                f"support '{feed}' (needs {gate.get('requiredVersion')}+)."
            )
        return (
            f"The Sorento consumer's contract ({version}) does not yet support "
            f"'{feed}' (needs {gate.get('requiredVersion')}+)."
        )

    # ── run now / sweep now (AC-14-05) ───────────────────────────────────────

    def run_feed(
        self, tenant_id: str, company_id: str, feed: str, kind: str,
        *, actor_user_id: Optional[str] = None, transport: Any = None,
    ) -> str:
        self._company(tenant_id, company_id)
        if feed not in ALL_FEEDS:
            raise DocFeedValidationError("feed", "Unknown feed.")
        if kind not in ("poll", "sweep"):
            raise DocFeedValidationError("kind", "kind must be 'poll' or 'sweep'.")

        row = self.feeds.get(tenant_id, company_id, feed)
        if row is None or row.mode == DOC_FEED_MODE_OFF:
            raise DocFeedValidationError("mode", "This feed is off.")

        if self.feeds.unfinished_job(tenant_id, DOC_FEED_RUN_JOB_TYPE, row.id) is not None:
            raise DocFeedConflictError(
                "RUN_IN_FLIGHT", "A run for this feed is already in progress."
            )

        job = JobService(self.db).create(
            type=DOC_FEED_RUN_JOB_TYPE, tenant_id=tenant_id, actor_user_id=actor_user_id,
            payload={"feedId": row.id, "kind": kind},
        )
        self._dispatch(job, run_doc_feed_job, transport=transport)
        return job.id

    def _dispatch(self, job, handler, *, transport: Any) -> None:
        """Mirrors ``PreviewJobService._run`` - EXACTLY ONE dispatch path,
        never both. S10/regression fix (review round 1): the earlier shape
        called ``create_and_enqueue`` (which itself calls ``enqueue`` -
        under ``CELERY_TASK_ALWAYS_EAGER`` that runs the job SYNCHRONOUSLY
        with ``transport=None``, the plain ``handler_def.handler(db, job)``
        two-arg dispatch ``run_job`` uses) and THEN a redundant transport-
        carrying attempt that could never win the claim (the job was
        already terminal). A test's ``sink_transport``/``vendor_transport``
        override was silently discarded; production's real dev/eager mode
        is unaffected (there ``transport`` is always ``None``, so this
        still takes the plain ``enqueue`` branch)."""
        if settings.celery_task_always_eager and transport is not None:
            self._run_eager_with_transport(handler, job, transport=transport)
        else:
            JobService(self.db).enqueue(job.id)

    def _run_eager_with_transport(self, handler, job, *, transport: Any) -> None:
        """Mirrors ``PreviewJobService._run_eager_with_transport`` - a
        TEST-ONLY seam (production never overrides ``get_http_transport``,
        so ``transport`` is always ``None`` there and ``_dispatch`` takes
        the plain ``enqueue()`` branch instead)."""
        jobs = JobService(self.db)
        if not jobs.claim(job.id):
            return
        self.db.refresh(job)
        try:
            handler(self.db, job, transport=transport)
        except Exception as exc:  # noqa: BLE001 - isolated, mirrors run_job
            logger.exception("doc-feed job %s crashed", job.id)
            self.db.rollback()
            fresh = jobs.repo.get_unscoped(job.id)
            if fresh is not None and fresh.status not in JOB_TERMINAL_STATUSES:
                jobs.finish(fresh, status=JOB_FAILED, error=f"Job crashed: {exc}")
                self.db.commit()

    # ── runs / issues (AC-14-70/71) ──────────────────────────────────────────

    def list_runs(
        self, tenant_id: str, company_id: str,
        *, feed: Optional[str] = None, page: int = 0, page_size: int = 25,
    ) -> DocFeedRunListOut:
        self._company(tenant_id, company_id)
        rows, total = self.runs.list(tenant_id, company_id, feed=feed, page=page, page_size=page_size)
        return DocFeedRunListOut(
            data=[DocFeedRunOut.model_validate(r) for r in rows], total=total, page=page,
        )

    def list_issues(
        self, tenant_id: str, company_id: str,
        *, feed: Optional[str] = None, kind: Optional[str] = None,
        search: Optional[str] = None, page: int = 0, page_size: int = 25,
    ) -> DocFeedIssueListOut:
        self._company(tenant_id, company_id)
        rows, total = self.issues.list(
            tenant_id, company_id, feed=feed, kind=kind, search=search,
            page=page, page_size=page_size,
        )
        # `AcDocFeedIssue`'s primary key is the composite (tenant, company,
        # feed, book, doc_key) - there is no single `id` column to
        # `model_validate` off, so the wire id is synthesised here.
        items = [
            DocFeedIssueOut(
                # N4 (review round 1) - the feed is part of the id: a DO
                # and a GRN can legitimately share a DocKey, and the
                # UNFILTERED issues list renders every feed's rows together.
                id=f"{row.feed}:{row.book}:{row.doc_key}", feed=row.feed, book=row.book,
                doc_key=row.doc_key, doc_no=row.doc_no, doc_date=row.doc_date,
                source_modified_at=row.source_modified_at, kind=row.kind,
                errors=row.errors_json or {},
                warnings=list(row.warnings_json) if isinstance(row.warnings_json, list) else None,
                attempts=row.attempts or 0, first_at=row.first_at, last_at=row.last_at,
            )
            for row in rows
        ]
        return DocFeedIssueListOut(data=items, total=total, page=page)

    # ── backfill (AC-14-60..65) ───────────────────────────────────────────────

    def start_backfill(
        self, tenant_id: str, company_id: str, feed: str,
        *, dry_run: bool, from_day: Optional[date] = None, to_day: Optional[date] = None,
        actor_user_id: Optional[str] = None, transport: Any = None,
    ) -> AcDocFeedBackfill:
        self._company(tenant_id, company_id)
        if feed not in ALL_FEEDS:
            raise DocFeedValidationError("feed", "Unknown feed.")
        row = self.feeds.get(tenant_id, company_id, feed)
        if row is None:
            raise DocFeedValidationError("feed", "Configure this feed first.")
        if row.mode == DOC_FEED_MODE_OFF:
            raise DocFeedValidationError("mode", "This feed is off.")
        if not dry_run and row.mode != DOC_FEED_MODE_PUSH:
            raise DocFeedValidationError(
                "mode", "A live backfill needs this feed in Push mode first."
            )

        if self.backfills.open_for_feed(tenant_id, row.id) is not None:
            raise DocFeedConflictError(
                "BACKFILL_OPEN", "A backfill is already open for this feed."
            )

        now = datetime.now(timezone.utc)
        today = myt_date(now)
        default_from = date.fromisoformat(BACKFILL_FROM_DEFAULT)
        from_day_value = from_day or default_from
        if from_day_value < default_from:
            # SS2 - an unbounded fromDay (0001-01-01) would queue ~740k
            # sequential vendor GETs.
            raise DocFeedValidationError(
                "fromDay", f"fromDay must be on or after {default_from.isoformat()}."
            )
        to_day_value = to_day or today
        if from_day_value > to_day_value or to_day_value > today:
            raise DocFeedValidationError(
                "toDay", "toDay must be on or before today, and not before fromDay."
            )

        if not dry_run and from_day_value <= default_from and row.full_backfill_done_at is not None:
            raise DocFeedConflictError(
                "BACKFILL_ALREADY_DONE", "The full-history backfill has already completed."
            )

        backfill = AcDocFeedBackfill(
            tenant_id=tenant_id, company_id=company_id, feed_id=row.id, feed=feed,
            book=row.book, dry_run=dry_run, from_day=from_day_value, to_day=to_day_value,
            next_day=from_day_value, status=DOC_FEED_BACKFILL_RUNNING,
            days_total=(to_day_value - from_day_value).days + 1, days_done=0,
            started_by=actor_user_id, started_at=now,
        )
        self.backfills.add(backfill)
        try:
            self.db.commit()
        except IntegrityError:
            # N5 - two concurrent Starts both passed `open_for_feed`; the
            # partial unique index (one open backfill per feed) refuses the
            # loser.
            self.db.rollback()
            raise DocFeedConflictError(
                "BACKFILL_OPEN", "A backfill is already open for this feed."
            )

        job = JobService(self.db).create(
            type=DOC_FEED_BACKFILL_JOB_TYPE, tenant_id=tenant_id, actor_user_id=actor_user_id,
            payload={"backfillId": backfill.id},
        )
        backfill.job_id = job.id
        self.db.commit()
        self._dispatch(job, run_doc_feed_backfill_job, transport=transport)
        self.db.refresh(backfill)
        return backfill

    def _open_backfill_or_404(self, tenant_id: str, company_id: str, feed: str) -> AcDocFeedBackfill:
        self._company(tenant_id, company_id)
        row = self.feeds.get(tenant_id, company_id, feed)
        if row is None:
            raise DocFeedValidationError("feed", "This feed is not configured.")
        backfill = self.backfills.open_for_feed(tenant_id, row.id)
        if backfill is None:
            raise DocFeedValidationError("feed", "There is no open backfill for this feed.")
        return backfill

    def stop_backfill(self, tenant_id: str, company_id: str, feed: str) -> AcDocFeedBackfill:
        backfill = self._open_backfill_or_404(tenant_id, company_id, feed)
        if backfill.status == DOC_FEED_BACKFILL_RUNNING:
            from ..models import DOC_FEED_BACKFILL_STOPPING

            backfill.status = DOC_FEED_BACKFILL_STOPPING
            self.db.commit()
        return backfill

    def resume_backfill(
        self, tenant_id: str, company_id: str, feed: str,
        *, actor_user_id: Optional[str] = None, transport: Any = None,
    ) -> AcDocFeedBackfill:
        self._company(tenant_id, company_id)
        row = self.feeds.get(tenant_id, company_id, feed)
        if row is None:
            raise DocFeedValidationError("feed", "This feed is not configured.")
        backfill = self.backfills.latest_for_feed(tenant_id, row.id)
        if backfill is None or backfill.status != DOC_FEED_BACKFILL_STOPPED:
            raise DocFeedValidationError("feed", "There is no stopped backfill to resume.")
        if self.backfills.job_is_live(tenant_id, backfill.job_id):
            raise DocFeedConflictError(
                "BACKFILL_JOB_LIVE",
                "The previous run for this backfill is still finishing up.",
            )
        if row.mode == DOC_FEED_MODE_OFF:
            raise DocFeedValidationError("mode", "This feed is off.")
        # N2 (review round 1) - re-check the SAME start-time rule Start
        # applies (a live backfill needs the feed in Push): the feed may
        # have left Push in the time this backfill sat stopped.
        if not backfill.dry_run and row.mode != DOC_FEED_MODE_PUSH:
            raise DocFeedValidationError(
                "mode", "A live backfill needs this feed in Push mode first."
            )
        backfill.status = DOC_FEED_BACKFILL_RUNNING
        self.db.commit()
        job = JobService(self.db).create(
            type=DOC_FEED_BACKFILL_JOB_TYPE, tenant_id=tenant_id, actor_user_id=actor_user_id,
            payload={"backfillId": backfill.id},
        )
        backfill.job_id = job.id
        self.db.commit()
        self._dispatch(job, run_doc_feed_backfill_job, transport=transport)
        self.db.refresh(backfill)
        return backfill

    def discard_backfill(self, tenant_id: str, company_id: str, feed: str) -> AcDocFeedBackfill:
        self._company(tenant_id, company_id)
        row = self.feeds.get(tenant_id, company_id, feed)
        if row is None:
            raise DocFeedValidationError("feed", "This feed is not configured.")
        backfill = self.backfills.latest_for_feed(tenant_id, row.id)
        if backfill is None or backfill.status != DOC_FEED_BACKFILL_STOPPED:
            raise DocFeedValidationError("feed", "There is no stopped backfill to discard.")
        from ..models import DOC_FEED_BACKFILL_DONE

        backfill.status = DOC_FEED_BACKFILL_DONE
        backfill.error_code = "DISCARDED"
        backfill.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        return backfill
