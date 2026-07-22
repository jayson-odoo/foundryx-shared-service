"""Trace retention sweep (AC-BI-10) — the `prune_runs` pattern.

`ok` traces prune on a SHORT window (they are noise once the feature works);
`error` and `flagged` traces keep a LONGER one (they are the reason traces exist
— a bad BR must stay attributable to its prompt version long enough to diagnose).

Child `ai_spans` are deleted first via a subquery so the cascade is correct on
Postgres AND on the SQLite test engine (whose FK pragma is off).

The caller (`app/workflow_engine/worker.py`) wraps this in its own isolated
`try/except` so a prune failure never breaks the beat.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.ai import TRACE_STATUS_OK, AiSpan, AiTrace


def prune_traces(db: Session, *, now: Optional[datetime] = None) -> int:
    """Delete traces past their status-dependent TTL. Returns rows deleted."""
    from app.config import settings

    now = now or datetime.now(timezone.utc)
    ok_cutoff = now - timedelta(days=settings.ai_trace_retention_days)
    kept_cutoff = now - timedelta(days=settings.ai_trace_error_retention_days)

    # `ok` AND not flagged → short window. Anything else (error, or flagged for
    # review) → long window. Flagging an `ok` trace therefore preserves it,
    # which is the entire point of the flag.
    doomed = or_(
        (AiTrace.status == TRACE_STATUS_OK)
        & (AiTrace.flagged.is_(False))
        & (AiTrace.created_at < ok_cutoff),
        (
            (AiTrace.status != TRACE_STATUS_OK) | (AiTrace.flagged.is_(True))
        )
        & (AiTrace.created_at < kept_cutoff),
    )

    doomed_ids = db.query(AiTrace.id).filter(doomed)
    db.query(AiSpan).filter(AiSpan.trace_id.in_(doomed_ids.scalar_subquery())).delete(
        synchronize_session=False
    )
    deleted = db.query(AiTrace).filter(doomed).delete(synchronize_session=False)
    db.commit()
    return deleted
