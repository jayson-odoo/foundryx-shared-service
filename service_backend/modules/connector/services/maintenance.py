"""Connector housekeeping, run from the existing Celery beat tick.

Idle grants (90 d unused) expire and their tokens die; ``call_log`` older than
the tenant's retention setting (else ``CONNECTOR_CALL_LOG_RETENTION_DAYS``) is deleted; spent/expired pending requests,
codes, tokens and assertion jti rows are cleaned up. Caller commits.
"""

from __future__ import annotations
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .. import registry
from ..repositories.connector_repository import MaintenanceRepository
from ..repositories.settings_repository import SettingsRepository

GRANT_IDLE_DAYS = 90


def prune(db: Session, now: datetime) -> None:
    repo = MaintenanceRepository(db)
    repo.expire_idle_grants(now - timedelta(days=GRANT_IDLE_DAYS), now)
    # Per-tenant retention: a tenant's own setting, else the environment/default.
    overrides = SettingsRepository(db).retention_overrides()
    repo.prune_call_log(now - timedelta(days=registry.call_log_retention_days()),
                        exclude_tenants=list(overrides))
    for tenant_id, days in overrides.items():
        repo.prune_call_log(now - timedelta(days=days), tenant_id=tenant_id)
    repo.prune_ephemeral(now)
    db.flush()
