"""The doc-feed beat sweep (D14, AC-14-33). Poll hourly (documents), sweep
daily; a feed with an unfinished job is skipped, not
re-armed, so the NEXT beat minute picks it up (no lost tick).

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

from app.jobs.service import JobService

from ..models import DOC_FEED_MODE_OFF, AcCompany, AcDocFeed
from ..repositories.doc_feed_repository import DocFeedRepository
from ..scheduler import active_tenant_service_join
from .constants import (
    ALL_FEEDS,
    DOC_FEED_RUN_JOB_TYPE,
    RUN_KIND_POLL,
    RUN_KIND_SWEEP,
)

logger = logging.getLogger("foundryx.autocount")

POLL_INTERVAL = timedelta(minutes=60)
SWEEP_INTERVAL = timedelta(hours=24)


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
    return {"fired": fired, "skipped": skipped, "failed": failed}


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

    if due_poll:
        kind = RUN_KIND_POLL
        claimed = (
            db.query(AcDocFeed)
            .filter(
                AcDocFeed.id == feed.id,
                AcDocFeed.next_poll_at.isnot(None),
                AcDocFeed.next_poll_at <= now,
            )
            .update({AcDocFeed.next_poll_at: now + POLL_INTERVAL}, synchronize_session=False)
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
            .update({AcDocFeed.next_sweep_at: now + SWEEP_INTERVAL}, synchronize_session=False)
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
