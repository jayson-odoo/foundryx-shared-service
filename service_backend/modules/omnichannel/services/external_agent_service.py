"""External-agent identity service — plan 11H Slice 1 (AC-11H-01/02/03).

The federated identity for an embed agent. ``upsert`` provisions-or-loads by
``(connection_id, sub)`` (cross-consumer isolation: two consumers' "u-1" agents
stay distinct) and refreshes name/email/avatar from later assertions. Also the
tenant-scoped display-name/avatar resolver the conversation mapper uses.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import ExternalAgent


class ExternalAgentService:
    def __init__(self, db: Session):
        self.db = db

    def upsert(
        self,
        *,
        connection_id: str,
        tenant_id: str,
        sub: str,
        name: str,
        email: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> ExternalAgent:
        """Provision-or-load the agent keyed by ``(connection_id, sub)``. Updates
        display fields on later calls. Caller owns the transaction boundary — this
        commits so the row (and its id) are durable before a token is minted."""
        row = (
            self.db.query(ExternalAgent)
            .filter(
                ExternalAgent.connection_id == connection_id,
                ExternalAgent.sub == sub,
            )
            .first()
        )
        if row is None:
            row = ExternalAgent(
                tenant_id=tenant_id,
                connection_id=connection_id,
                sub=sub,
                name=name or sub,
                email=email,
                avatar_url=avatar_url,
            )
            self.db.add(row)
        else:
            # Refresh display fields (name/email/avatar may change per assertion).
            row.tenant_id = tenant_id
            if name:
                row.name = name
            row.email = email
            row.avatar_url = avatar_url
        self.db.commit()
        self.db.refresh(row)
        return row

    def get(self, agent_id: str, tenant_id: str) -> Optional[ExternalAgent]:
        """Tenant-scoped load (defense-in-depth — never resolve a stored id
        unscoped, the polymorphic-target_id rule)."""
        return (
            self.db.query(ExternalAgent)
            .filter(ExternalAgent.id == agent_id, ExternalAgent.tenant_id == tenant_id)
            .first()
        )

    def get_for_connection(
        self, agent_id: str, connection_id: str, tenant_id: str
    ) -> Optional[ExternalAgent]:
        """Load an agent that belongs to a SPECIFIC connection — used to validate
        an embed assign target (a token can only assign to its consumer's agents)."""
        return (
            self.db.query(ExternalAgent)
            .filter(
                ExternalAgent.id == agent_id,
                ExternalAgent.connection_id == connection_id,
                ExternalAgent.tenant_id == tenant_id,
            )
            .first()
        )

    def names(self, agent_ids: List[str], tenant_id: str) -> Dict[str, ExternalAgent]:
        """Batched id → ExternalAgent for the conversation mapper (name + avatar)."""
        ids = [a for a in set(agent_ids) if a]
        if not ids:
            return {}
        rows = (
            self.db.query(ExternalAgent)
            .filter(
                ExternalAgent.tenant_id == tenant_id,
                ExternalAgent.id.in_(ids),
            )
            .all()
        )
        return {a.id: a for a in rows}
