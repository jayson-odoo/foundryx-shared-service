"""Integration log repository (sprint-4/07 Cluster F slice 3) — pure SQLAlchemy,
tenant-scoped. The idempotency ledger + masked webhook audit trail.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.integration_log import IntegrationLog


class IntegrationLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_event(
        self, tenant_id: str, provider: str, external_event_id: str
    ) -> Optional[IntegrationLog]:
        """Idempotency lookup (AC-07-30) — tenant-scoped."""
        return (
            self.db.query(IntegrationLog)
            .filter(
                IntegrationLog.tenant_id == tenant_id,
                IntegrationLog.provider == provider,
                IntegrationLog.external_event_id == external_event_id,
            )
            .first()
        )

    def create(self, log: IntegrationLog) -> IntegrationLog:
        self.db.add(log)
        self.db.flush()
        return log
