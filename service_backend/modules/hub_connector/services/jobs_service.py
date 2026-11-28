"""Hub Connector's scheduled tasks (owner standing rule: every background or
scheduled job is listed with last run, last error and Run now).

- ``crm-sync``: the CRM stock feed pull, per tenant (``hc_sync_state``).
- ``delivery-retries``: re-sends hub webhooks whose retry time has come.
  Platform-wide tick (``hc_job_runs``); Run now runs THIS tenant's due ones.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import HcJobRun
from . import delivery_service, sync_service
from .hub_service import HubError

JOB_SYNC = "crm-sync"
JOB_RETRIES = "delivery-retries"
JOBS = {
    JOB_SYNC: {"name": "Stock sync from the CRM", "schedule": "Every 10 minutes"},
    JOB_RETRIES: {"name": "Hub delivery retries", "schedule": "Every minute"},
}


def stamp(db: Session, job: str, error: Optional[str]) -> None:
    row = db.get(HcJobRun, job)
    if row is None:
        row = HcJobRun(job=job)
        db.add(row)
    row.last_run_at = datetime.now(timezone.utc)
    row.last_error = (error or None) and error[:500]
    db.commit()


def list_jobs(db: Session, tenant_id: str) -> List[Dict[str, Any]]:
    state = sync_service.get_state(db, tenant_id)
    retries = db.get(HcJobRun, JOB_RETRIES)
    return [
        {
            "key": JOB_SYNC,
            **JOBS[JOB_SYNC],
            "lastRunAt": state.last_run_at if state else None,
            "lastError": state.last_error if state else None,
        },
        {
            "key": JOB_RETRIES,
            **JOBS[JOB_RETRIES],
            "lastRunAt": retries.last_run_at if retries else None,
            "lastError": retries.last_error if retries else None,
        },
    ]


def run_now(db: Session, tenant_id: str, job: str) -> None:
    if job == JOB_SYNC:
        sync_service.sync_tenant(db, tenant_id)
        return
    if job == JOB_RETRIES:
        delivery_service.run_due(db, tenant_id=tenant_id)
        return
    raise HubError(404, "job_not_found", "This task does not exist.")
