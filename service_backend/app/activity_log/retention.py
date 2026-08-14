"""Integration-activity retention pruner (sprint-4/12 Slice 3, AC-DLC-22).

Deletes ``integration_activity`` rows older than each tenant's retention window
(``integration_log_settings.retention_days`` override else the global default
``settings.integration_activity_retention_days``). Per-tenant + failure-isolated
- mirrors ``app.workflow_engine.scheduler.prune_runs``. Wired into the Celery
beat tick; eager dev has no beat, so it is directly callable from tests.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("foundryx.activity_log")


def prune_integration_activity(db: Session, *, now: Optional[datetime] = None) -> int:
    """Delete integration-activity rows older than each tenant's retention
    window. Returns the total number of rows deleted.

    Per-tenant so one tenant's long window never keeps another's rows. Isolated
    per tenant - a bad delete rolls back + logs, the loop continues. NEVER raises
    to the beat tick."""
    from app.config import settings
    from app.models.integration_activity import IntegrationActivity
    from app.models.integration_log_settings import IntegrationLogSettings

    now = now or datetime.now(timezone.utc)
    default_days = settings.integration_activity_retention_days
    overrides = {
        s.tenant_id: s.retention_days
        for s in db.query(IntegrationLogSettings).filter(
            IntegrationLogSettings.retention_days.isnot(None)
        )
    }
    tenant_ids = [row[0] for row in db.query(IntegrationActivity.tenant_id).distinct()]

    deleted = 0
    for tenant_id in tenant_ids:
        days = overrides.get(tenant_id, default_days)
        cutoff = now - timedelta(days=days)
        try:
            deleted += (
                db.query(IntegrationActivity)
                .filter(
                    IntegrationActivity.tenant_id == tenant_id,
                    IntegrationActivity.created_at < cutoff,
                )
                .delete(synchronize_session=False)
            )
            db.commit()
        except Exception:  # noqa: BLE001 - one tenant's failure never kills the tick.
            logger.exception("integration-activity prune failed (tenant=%s)", tenant_id)
            db.rollback()
    return deleted
