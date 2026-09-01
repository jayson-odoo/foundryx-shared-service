"""Connection repository (plan 09 §3) - pure SQLAlchemy, tenant-scoped.

The PLATFORM tenant's row doubles as the deployment default - `get_default`
resolves tenant → platform for the dispatcher/EmailService fallback chain.
"""
from typing import List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.connection import CONNECTION_STATUS_ERROR, Connection
from app.models.tenant import PLATFORM_TENANT_ID

_SORT_COLUMNS = {
    "name": Connection.name,
    "provider": Connection.provider,
    "type": Connection.type,
    "status": Connection.status,
    "lastTestedAt": Connection.last_tested_at,
    "created": Connection.created_at,
}


class ConnectionRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_for_tenant(self, tenant_id: str) -> List[Connection]:
        return (
            self.db.query(Connection)
            .filter(Connection.tenant_id == tenant_id)
            .order_by(Connection.created_at)
            .all()
        )

    def list(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_clause=None,
        providers: Optional[List[str]] = None,
    ) -> Tuple[List[Connection], int]:
        """Server-side Resource list (plan 06 D6): search + filter + sort +
        paginate. Returns (rows, total).

        ``providers`` (when given) restricts to those provider keys - the
        Integrations UI passes the registered-provider set so infrastructure
        rows in the same table (e.g. the embed ``omnichannel_shared`` connection)
        never surface where a Disconnect would silently destroy them.
        """
        q = self.db.query(Connection).filter(Connection.tenant_id == tenant_id)

        if providers is not None:
            q = q.filter(Connection.provider.in_(providers))

        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(
                or_(
                    Connection.name.ilike(term),
                    Connection.provider.ilike(term),
                    Connection.last_error.ilike(term),
                )
            )

        if filter_clause is not None:
            q = q.filter(filter_clause)

        total = q.count()

        column = _SORT_COLUMNS.get(sort_by or "", Connection.created_at)
        q = q.order_by(column.desc() if sort_dir == "desc" else column.asc())
        # Stable tiebreak so pagination + record-nav are deterministic.
        q = q.order_by(Connection.id.asc())

        rows = q.offset(page * page_size).limit(page_size).all()
        return rows, total

    def get(self, connection_id: str, tenant_id: str) -> Optional[Connection]:
        return (
            self.db.query(Connection)
            .filter(Connection.id == connection_id, Connection.tenant_id == tenant_id)
            .first()
        )

    def get_by_provider(self, tenant_id: str, provider: str) -> Optional[Connection]:
        return (
            self.db.query(Connection)
            .filter(Connection.tenant_id == tenant_id, Connection.provider == provider)
            .first()
        )

    def get_by_type(self, tenant_id: str, type_: str) -> Optional[Connection]:
        """The tenant's ACTIVE connection of this type (sprint-4/10 D10).

        Only an ``is_active`` row is the write-target: during a storage
        migration a retired ``A`` (is_active=false) and its successor ``B``
        coexist, so the type-level resolver must pick the single active one.
        Resolve-BY-KEY (``get_by_id``) deliberately ignores ``is_active`` so a
        retired connection still serves its historical blobs.
        """
        return (
            self.db.query(Connection)
            .filter(
                Connection.tenant_id == tenant_id,
                Connection.type == type_,
                Connection.is_active.is_(True),
            )
            .first()
        )

    def get_by_id(self, connection_id: str) -> Optional[Connection]:
        """Unscoped lookup - ONLY for resolving server-written `conn:` storage
        keys, and the caller MUST verify tenant ownership (storage.py does)."""
        return self.db.query(Connection).filter(Connection.id == connection_id).first()

    def resolve_for_type(self, tenant_id: str, type_: str) -> Optional[Connection]:
        """Type-level fallback chain (plan 06 D1): tenant's connection of this
        TYPE → platform's. ERROR rows skipped, like `resolve_for_send`."""
        conn = self.get_by_type(tenant_id, type_)
        if conn is not None and conn.status != CONNECTION_STATUS_ERROR:
            return conn
        if tenant_id != PLATFORM_TENANT_ID:
            platform = self.get_by_type(PLATFORM_TENANT_ID, type_)
            if platform is not None and platform.status != CONNECTION_STATUS_ERROR:
                return platform
        return None

    def resolve_for_send(self, tenant_id: str, provider: str) -> Optional[Connection]:
        """Fallback chain (plan 09 D6): tenant's connection → platform default.

        ERROR connections are skipped - a known-bad tenant connection must not
        absorb 3 retries (~31 min) before the working platform default gets a
        turn. UNVERIFIED stays usable (saved-but-untested is usually fine).
        """
        conn = self.get_by_provider(tenant_id, provider)
        if conn is not None and conn.status != CONNECTION_STATUS_ERROR:
            return conn
        if tenant_id != PLATFORM_TENANT_ID:
            platform = self.get_by_provider(PLATFORM_TENANT_ID, provider)
            if platform is not None and platform.status != CONNECTION_STATUS_ERROR:
                return platform
        return None

    def mark_active(self, connection_id: str, active: bool) -> None:
        """Flip a connection's write-target flag (sprint-4/10 D10). Used by the
        storage-migration engine to retire ``A`` / promote ``B`` (and reverse
        on abort). Unscoped by id - the caller owns the tenant check."""
        conn = self.db.query(Connection).filter(Connection.id == connection_id).first()
        if conn is not None:
            conn.is_active = active
            self.db.flush()

    def create(self, connection: Connection) -> Connection:
        self.db.add(connection)
        self.db.flush()
        return connection

    def delete(self, connection: Connection) -> None:
        self.db.delete(connection)
        self.db.flush()
