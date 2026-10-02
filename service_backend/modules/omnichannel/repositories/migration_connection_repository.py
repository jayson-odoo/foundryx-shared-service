"""READ-ONLY access to core ``public.connections`` for the respond.io
migration tool (plan 33 S1, AC-MIG-14/51/52).

Mirrors ``modules/autocount/repositories/autocount_repository.py``'s
``ConnectionRepository`` verbatim: a module never ALTERS a core table, but may
read the rows it owns (the ``respondio`` provider's config/credentials). Every
lookup is tenant- AND provider-scoped - NEVER a bare ``get(id)``. A connection
id is a client-supplied, stored reference; resolving one unscoped is the
polymorphic-target_id leak class that has bitten this codebase twice
(notifications, then the omnichannel gateway) - a foreign tenant's
``connectionId`` must read back as "not found", identically to a missing one.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.connection import Connection


class MigrationConnectionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_for_provider(
        self, tenant_id: str, connection_id: str, provider: str
    ) -> Optional[Connection]:
        return (
            self.db.query(Connection)
            .filter(
                Connection.tenant_id == tenant_id,
                Connection.id == connection_id,
                Connection.provider == provider,
            )
            .first()
        )
