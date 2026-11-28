"""Read-only lookup of the LLM connection the builder uses (core ``connections``)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.connection import CONNECTION_STATUS_ERROR, Connection
from app.models.tenant import PLATFORM_TENANT_ID

LLM_TYPE = "llm"


class ConnectionRepository:
    def __init__(self, db: Session):
        self.db = db

    def _first(self, owner_id: str, provider: str) -> Optional[Connection]:
        return (
            self.db.query(Connection)
            .filter(
                Connection.tenant_id == owner_id,
                Connection.type == LLM_TYPE,
                Connection.provider == provider,
                Connection.is_active.is_(True),
                Connection.status != CONNECTION_STATUS_ERROR,
            )
            .order_by(Connection.created_at.asc(), Connection.id.asc())
            .first()
        )

    def llm_for_provider(self, tenant_id: str, provider: str) -> Optional[Connection]:
        """The tenant's own connection first, then the platform's; oldest active first, ERROR skipped."""
        own = self._first(tenant_id, provider)
        if own is not None or tenant_id == PLATFORM_TENANT_ID:
            return own
        return self._first(PLATFORM_TENANT_ID, provider)
