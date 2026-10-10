"""Connector housekeeping, run from the existing Celery beat tick.

Idle grants (90 d unused) expire and their tokens die; ``call_log`` older than
``CONNECTOR_CALL_LOG_RETENTION_DAYS`` is deleted; spent/expired pending requests,
codes, tokens and assertion jti rows are cleaned up. Caller commits.
"""

from __future__ import annotations
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .. import registry
from ..repositories.connector_repository import MaintenanceRepository

GRANT_IDLE_DAYS = 90


def prune(db: Session, now: datetime) -> None:
    repo = MaintenanceRepository(db)
    repo.expire_idle_grants(now - timedelta(days=GRANT_IDLE_DAYS), now)
    repo.prune_call_log(now - timedelta(days=registry.call_log_retention_days()))
    repo.prune_ephemeral(now)
    db.flush()
