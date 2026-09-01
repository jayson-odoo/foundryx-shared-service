"""The tenant admin's view of what the bots have been doing (S2 plan §7).

Ops data, read straight off the core ``background_jobs`` rows the runs already
write - spine M19 again: no run table of its own, so there is nothing that can
disagree with the job.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.background_job import BackgroundJob

from ..models import Meeting

# A week is what an operator looks back over; anything older is a question for
# the job list, not for this page.
DEFAULT_DAYS = 7
MAX_DAYS = 90


@dataclass
class BotRun:
    """One run, flattened for the wire."""

    id: str
    meeting_id: str
    meeting_title: Optional[str]
    starts_at: datetime
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    exit_reason: Optional[str]
    duration_s: Optional[int]
    meeting_status: str


def list_bot_runs(
    db: Session,
    tenant_id: str,
    *,
    days: int = DEFAULT_DAYS,
    now: Optional[datetime] = None,
) -> List[BotRun]:
    """This tenant's bot runs over the window, newest first."""
    from ..jobs import BOT_RUN

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    jobs = (
        db.query(BackgroundJob)
        .filter(
            BackgroundJob.tenant_id == tenant_id,
            BackgroundJob.type == BOT_RUN,
            BackgroundJob.created_at >= cutoff,
        )
        # `id` breaks the tie: several meetings start in the same minute, and
        # `now()` inside one transaction gives them all the same stamp.
        .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
        .all()
    )
    if not jobs:
        return []

    # The payload carries the meeting id; resolving in Python beats a JSON
    # predicate that would have to be written twice for two dialects, and a week
    # of runs is a handful of rows.
    meeting_ids = {
        str((job.payload_json or {}).get("meeting_id") or "") for job in jobs
    }
    meetings = {
        row.id: row
        for row in db.query(Meeting)
        .filter(Meeting.tenant_id == tenant_id, Meeting.id.in_(list(meeting_ids)))
        .all()
    }

    runs: List[BotRun] = []
    for job in jobs:
        meeting = meetings.get(str((job.payload_json or {}).get("meeting_id") or ""))
        if meeting is None:
            # The meeting was deleted (module uninstall, tenant cleanup); the
            # orphan job is not something to render.
            continue
        result = job.result_json or {}
        runs.append(
            BotRun(
                id=job.id,
                meeting_id=meeting.id,
                meeting_title=meeting.title,
                starts_at=meeting.starts_at,
                started_at=job.started_at,
                ended_at=job.finished_at,
                # The container's own word when it gave one, else the job error
                # (a run that never started still has to say why).
                exit_reason=str(result.get("reason") or "") or job.error or None,
                duration_s=meeting.duration_s,
                meeting_status=meeting.status,
            )
        )
    return runs
