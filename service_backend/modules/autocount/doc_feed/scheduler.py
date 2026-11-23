"""The doc-feed beat sweep (D14, AC-14-33). Poll and sweep on
the feed's own schedule (sprint-5/19; default hourly / daily); a feed with an
unfinished job is skipped, not re-armed, so the NEXT beat minute picks it up (no lost tick).

**No extraction happens here** - this selects, claims (a guarded UPDATE, so
two beats never both enqueue the same feed) and enqueues the SAME
``autocount_doc_feed_run`` job ``Run now``/``Run sweep now`` use.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.jobs.service import JobService
from app.models.background_job import JOB_PENDING, JOB_RUNNING

from ..models import (
    DOC_FEED_BACKFILL_RUNNING,
    DOC_FEED_BACKFILL_STOPPED,
    DOC_FEED_BACKFILL_STOPPING,
    DOC_FEED_MODE_OFF,
    AcCompany,
    AcDocFeed,
    AcDocFeedBackfill,
)
from ..repositories.doc_feed_repository import DocFeedBackfillRepository, DocFeedRepository
from ..scheduler import active_tenant_service_join
from .constants import (
    ALL_FEEDS,
    DOC_FEED_RUN_JOB_TYPE,
    PROJNO_FEEDS,
    RUN_KIND_POLL,
    RUN_KIND_SWEEP,
)
from .schedule import next_poll_at, next_sweep_at, resolve_schedule

logger = logging.getLogger("foundryx.autocount")

# sprint-5/19 - the cadence is per feed now (`ac_doc_feed.schedule_config`,
# resolved by `doc_feed/schedule.py`); NULL = poll 60 min / sweep 24 h, the
# values that used to be hard-coded here.


def sweep_doc_feeds(db: Session, *, now: Optional[datetime] = None) -> Dict[str, int]:
    """The beat tick body. Returns ``{fired, skipped, failed}``."""
    now = now or datetime.now(timezone.utc)
    due = (
        active_tenant_service_join(db.query(AcDocFeed), AcDocFeed.tenant_id)
        .join(
            AcCompany,
            and_(
                AcCompany.id == AcDocFeed.company_id,
                AcCompany.tenant_id == AcDocFeed.tenant_id,
            ),
        )
        .filter(
            AcDocFeed.mode != DOC_FEED_MODE_OFF,
            # A dev DB that ran the OLD 0023 may hold a retired `branches` row.
            AcDocFeed.feed.in_(ALL_FEEDS),
            AcCompany.is_active.is_(True),
            or_(
                and_(AcDocFeed.next_poll_at.isnot(None), AcDocFeed.next_poll_at <= now),
                and_(AcDocFeed.next_sweep_at.isnot(None), AcDocFeed.next_sweep_at <= now),
            ),
        )
        .all()
    )
    fired = skipped = failed = 0
    for feed in due:
        try:
            outcome = _sweep_one_feed(db, feed, now=now)
        except Exception:  # noqa: BLE001 - one bad feed never stops the sweep
            logger.exception("doc-feed sweep failed for feed %s", feed.id)
            db.rollback()
            failed += 1
            continue
        if outcome == "fired":
            fired += 1
        elif outcome == "skipped":
            skipped += 1
    missing = _report_missing_feed_books(db)
    try:
        reaped = reap_stale_backfills(db, now=now)
    except Exception:  # noqa: BLE001 - the reaper never stops the sweep
        logger.exception("doc-feed backfill reaper failed")
        db.rollback()
        reaped = 0
    return {
        "fired": fired, "skipped": skipped, "failed": failed,
        "missingFeedBooks": missing, "reapedBackfills": reaped,
    }


BACKFILL_JOB_ENDED_CODE = "JOB_ENDED"
BACKFILL_JOB_ENDED_MESSAGE = (
    "Stopped: the job reading this backfill ended before it finished. "
    "Resume continues from the next day."
)


def reap_stale_backfills(
    db: Session, *, now: Optional[datetime] = None,
    tenant_id: Optional[str] = None, feed_id: Optional[str] = None,
) -> int:
    """SS-BACKFILL-CHUNKED (AC-BFC-3) - move every backfill still marked
    ``running``/``stopping`` whose job can no longer move it to ``stopped``
    (resumable; Resume / Discard work again). Returns how many.

    - no job, a job row that is gone, or a job that has ended (done / failed
      / aborted) -> ``stopped`` with ``JOB_ENDED``;
    - a RUNNING job with no heartbeat for ``background_job_orphan_after_minutes``
      (15) -> the job is failed through core's orphan sweep (its
      ``on_job_orphaned`` hook stops the row, so Resume's live-job check
      passes too);
    - a PENDING job (a queued segment waiting for a free slot) is left alone:
      core's undispatched sweep fails a lost one, then this pass stops it.

    Runs on the doc-feed beat for every tenant, and for one feed inside
    Stop / Resume / Discard. Each row commits on its own; one bad row never
    stops the others."""
    from ..repositories.doc_feed_repository import DocFeedBackfillRepository

    current = now or datetime.now(timezone.utc)
    threshold = timedelta(minutes=settings.background_job_orphan_after_minutes)
    repo = DocFeedBackfillRepository(db)
    reaped = 0
    for backfill in repo.in_flight(tenant_id=tenant_id, feed_id=feed_id):
        try:
            if _reap_one(db, repo, backfill, now=current, threshold=threshold):
                reaped += 1
        except Exception:  # noqa: BLE001 - one bad row never stops the pass
            logger.exception("doc-feed backfill reaper failed for %s", backfill.id)
            db.rollback()
    return reaped


def _reap_one(db: Session, repo, backfill: AcDocFeedBackfill, *, now: datetime, threshold: timedelta) -> bool:
    # Review round 1 - judge a FRESH row: the pass loaded every row up front,
    # and a healthy chain may have moved `job_id` to its next segment since.
    db.refresh(backfill)
    if backfill.status not in (DOC_FEED_BACKFILL_RUNNING, DOC_FEED_BACKFILL_STOPPING):
        return False
    seen_job_id = backfill.job_id
    job = repo.job_for(backfill.tenant_id, seen_job_id)
    if job is not None and job.status == JOB_PENDING:
        return False
    if job is not None and job.status == JOB_RUNNING:
        last_sign = job.heartbeat_at or job.started_at or job.created_at
        if last_sign is not None and last_sign >= now - threshold:
            return False
        # Core's own closer: fails the job AND runs autocount's
        # `on_job_orphaned`, which stops this row with the job's error.
        JobService(db).fail_orphaned_running_jobs(older_than=threshold, now=now, job_id=job.id)
        db.refresh(backfill)
        if backfill.status not in (DOC_FEED_BACKFILL_RUNNING, DOC_FEED_BACKFILL_STOPPING):
            logger.error("doc-feed backfill %s: job %s went quiet; stopped", backfill.id, job.id)
            return True
        logger.warning(
            "doc-feed backfill %s: the orphan sweep did not close job %s; stopping the row here",
            backfill.id, job.id,
        )
        db.refresh(job)
    detail = getattr(job, "error", None) if job is not None else None
    error = (BACKFILL_JOB_ENDED_MESSAGE + (f" Last error: {detail}" if detail else ""))[:4000]
    # A guarded write on the job id this pass judged: a chain that moved on
    # (or a Stop / Resume that landed meanwhile) is never stopped by mistake.
    if not repo.stop_if_job_unchanged(backfill.tenant_id, backfill.id, seen_job_id,
                                      error=error, error_code=BACKFILL_JOB_ENDED_CODE):
        db.rollback()
        return False
    db.commit()
    logger.error("doc-feed backfill %s: its job had ended; stopped", backfill.id)
    return True


def _report_missing_feed_books(db: Session) -> int:
    """Plan 72 (UAC S0-13) - every tenant that runs the registrations feed
    is checked for an allowed book with a connection but no feed row: that
    book fails loudly (an error log line each tick) while the configured
    books keep running. Never raises into the sweep."""
    from ..services.doc_feed_service import DocFeedService

    count = 0
    for feed in PROJNO_FEEDS:
        try:
            tenant_ids = [
                row[0] for row in active_tenant_service_join(
                    db.query(AcDocFeed.tenant_id), AcDocFeed.tenant_id
                ).filter(AcDocFeed.feed == feed).distinct().all()
            ]
            service = DocFeedService(db)
            for tenant_id in tenant_ids:
                for book in service.missing_feed_books(tenant_id, feed):
                    count += 1
                    logger.error(
                        "AutoCount project registrations: book %s has no feed set up "
                        "(tenant %s); its registrations are not read.", book, tenant_id,
                    )
        except Exception:  # noqa: BLE001 - the check never stops the sweep
            logger.exception("doc-feed missing-book check failed for %s", feed)
            db.rollback()
    return count


def _sweep_one_feed(db: Session, feed: AcDocFeed, *, now: datetime) -> str:
    due_poll = feed.next_poll_at is not None and feed.next_poll_at <= now
    due_sweep = feed.next_sweep_at is not None and feed.next_sweep_at <= now
    if not due_poll and not due_sweep:
        return "not_due"

    # A busy feed is simply left due for the NEXT beat minute - no lost
    # tick, no skip-row noise (D14).
    if DocFeedRepository(db).unfinished_job(
        feed.tenant_id, DOC_FEED_RUN_JOB_TYPE, feed.id
    ) is not None:
        return "skipped"
    if feed.feed in PROJNO_FEEDS and DocFeedBackfillRepository(db).running_for_feed(
        feed.tenant_id, feed.id
    ) is not None:
        # Plan 72 - one AutoCount call in flight per book: the poll waits for
        # the backfill; left due, it fires on the first beat after.
        return "skipped"

    schedule = resolve_schedule(feed.schedule_config)
    if due_poll:
        kind = RUN_KIND_POLL
        claimed = (
            db.query(AcDocFeed)
            .filter(
                AcDocFeed.id == feed.id,
                AcDocFeed.next_poll_at.isnot(None),
                AcDocFeed.next_poll_at <= now,
            )
            .update(
                {AcDocFeed.next_poll_at: next_poll_at(schedule, now)},
                synchronize_session=False,
            )
        )
    else:
        kind = RUN_KIND_SWEEP
        claimed = (
            db.query(AcDocFeed)
            .filter(
                AcDocFeed.id == feed.id,
                AcDocFeed.next_sweep_at.isnot(None),
                AcDocFeed.next_sweep_at <= now,
            )
            .update(
                {AcDocFeed.next_sweep_at: next_sweep_at(schedule, now)},
                synchronize_session=False,
            )
        )
    if not claimed:
        db.rollback()
        return "not_due"
    db.commit()

    JobService(db).create_and_enqueue(
        type=DOC_FEED_RUN_JOB_TYPE, tenant_id=feed.tenant_id,
        payload={"feedId": feed.id, "kind": kind},
    )
    return "fired"
