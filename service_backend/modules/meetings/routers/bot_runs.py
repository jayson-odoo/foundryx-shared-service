"""Bot-run routes (S2 plan §7, AC-S2-12).

HTTP + Pydantic only, gated on ``meetings.settings.manage``: a run is tenant-wide
ops data, not the caller's own meeting.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import BotRunListResponse, BotRunOut
from ..services.bot_runs import DEFAULT_DAYS, MAX_DAYS, BotRun, list_bot_runs

router = APIRouter()


def _out(run: BotRun) -> BotRunOut:
    return BotRunOut(
        id=run.id,
        meetingId=run.meeting_id,
        meetingTitle=run.meeting_title,
        startsAt=run.starts_at,
        startedAt=run.started_at,
        endedAt=run.ended_at,
        exitReason=run.exit_reason,
        durationS=run.duration_s,
        meetingStatus=run.meeting_status,
    )


@router.get("", response_model=BotRunListResponse)
def list_runs(
    days: int = Query(default=DEFAULT_DAYS, ge=1, le=MAX_DAYS),
    current_user: User = Depends(require_permission("meetings.settings.manage")),
    db: Session = Depends(get_db),
) -> BotRunListResponse:
    runs = list_bot_runs(db, current_user.tenant_id, days=days)
    return BotRunListResponse(data=[_out(run) for run in runs])
