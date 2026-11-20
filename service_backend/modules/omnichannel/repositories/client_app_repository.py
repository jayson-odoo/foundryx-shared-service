"""Client app repository - tenant-scoped queries. Pure SQLAlchemy."""
from typing import Dict, List, Optional, Set

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import ClientApp, PartnerApiKey, Workspace


def normalise(name: Optional[str]) -> str:
    """The grouping key: trimmed, case-insensitive (SQL: lower(trim(name)))."""
    return (name or "").strip().lower()


class ClientAppRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, client_app_id: str, tenant_id: str) -> Optional[ClientApp]:
        return (
            self.db.query(ClientApp)
            .filter(ClientApp.id == client_app_id, ClientApp.tenant_id == tenant_id)
            .first()
        )

    def get_default(self, tenant_id: str) -> Optional[ClientApp]:
        return (
            self.db.query(ClientApp)
            .filter(ClientApp.tenant_id == tenant_id, ClientApp.is_default.is_(True))
            .first()
        )

    def get_by_name(self, tenant_id: str, name: str) -> Optional[ClientApp]:
        return (
            self.db.query(ClientApp)
            .filter(
                ClientApp.tenant_id == tenant_id,
                func.lower(func.trim(ClientApp.name)) == normalise(name),
            )
            .order_by(ClientApp.created_at.asc(), ClientApp.id.asc())
            .first()
        )

    def list_for_tenant(self, tenant_id: str) -> List[ClientApp]:
        return (
            self.db.query(ClientApp)
            .filter(ClientApp.tenant_id == tenant_id)
            .order_by(ClientApp.name.asc(), ClientApp.id.asc())
            .all()
        )

    def workspace_counts(self, tenant_id: str) -> Dict[str, int]:
        """Live workspaces per client app."""
        rows = (
            self.db.query(Workspace.client_app_id, func.count(Workspace.id))
            .filter(
                Workspace.tenant_id == tenant_id,
                Workspace.client_app_id.isnot(None),
                Workspace.is_trashed.is_(False),
            )
            .group_by(Workspace.client_app_id)
            .all()
        )
        return {cid: n for cid, n in rows}

    def has_unassigned(self, tenant_id: str) -> bool:
        """Any NULL-parent workspace or partner key in the tenant."""
        if (
            self.db.query(Workspace.id)
            .filter(Workspace.tenant_id == tenant_id, Workspace.client_app_id.is_(None))
            .first()
        ):
            return True
        return (
            self.db.query(PartnerApiKey.id)
            .filter(PartnerApiKey.tenant_id == tenant_id, PartnerApiKey.client_app_id.is_(None))
            .first()
            is not None
        )

    def unassigned_named_workspaces(self, tenant_id: str) -> List[Workspace]:
        """NULL-parent workspaces without an external_ref, live first, oldest
        first (so the first of each name group names its client app)."""
        return (
            self.db.query(Workspace)
            .filter(
                Workspace.tenant_id == tenant_id,
                Workspace.client_app_id.is_(None),
                Workspace.external_ref.is_(None),
            )
            .order_by(Workspace.is_trashed.asc(), Workspace.created_at.asc(), Workspace.id.asc())
            .all()
        )

    def default_candidate(self, tenant_id: str) -> Optional[ClientApp]:
        """The client app of the tenant's default workspace (live first,
        oldest first), else the tenant's oldest client app."""
        ws = (
            self.db.query(Workspace)
            .filter(
                Workspace.tenant_id == tenant_id,
                Workspace.is_default.is_(True),
                Workspace.client_app_id.isnot(None),
            )
            .order_by(Workspace.is_trashed.asc(), Workspace.created_at.asc(), Workspace.id.asc())
            .first()
        )
        if ws is not None:
            app = self.get(ws.client_app_id, tenant_id)
            if app is not None:
                return app
        oldest_ws = (
            self.db.query(Workspace.client_app_id, func.min(Workspace.created_at).label("first"))
            .filter(Workspace.tenant_id == tenant_id, Workspace.client_app_id.isnot(None))
            .group_by(Workspace.client_app_id)
            .subquery()
        )
        return (
            self.db.query(ClientApp)
            .outerjoin(oldest_ws, oldest_ws.c.client_app_id == ClientApp.id)
            .filter(ClientApp.tenant_id == tenant_id)
            .order_by(
                ClientApp.created_at.asc(),
                oldest_ws.c.first.is_(None).asc(),
                oldest_ws.c.first.asc(),
                ClientApp.id.asc(),
            )
            .first()
        )

    def set_parent(self, workspace_id: str, client_app_id: str) -> None:
        """Attach a workspace; keeps updated_at (attaching is not an edit)."""
        self.db.query(Workspace).filter(Workspace.id == workspace_id).update(
            {Workspace.client_app_id: client_app_id, Workspace.updated_at: Workspace.updated_at},
            synchronize_session="fetch",
        )

    def attach_partner_rows(self, tenant_id: str, client_app_id: str) -> None:
        """Same rule as migration 0032 steps 3d/3e: NULL-parent partner-made
        workspaces (external_ref set) and partner keys join this (the default)
        client app; a live workspace whose external_ref another live workspace
        of the tenant also carries is left NULL."""
        q = self.db.query(Workspace).filter(
            Workspace.tenant_id == tenant_id,
            Workspace.client_app_id.is_(None),
            Workspace.external_ref.isnot(None),
        )
        shared = self._shared_live_refs(tenant_id)
        for ws in q.all():
            if not ws.is_trashed and ws.external_ref in shared:
                continue
            self.set_parent(ws.id, client_app_id)
        self.db.query(PartnerApiKey).filter(
            PartnerApiKey.tenant_id == tenant_id, PartnerApiKey.client_app_id.is_(None)
        ).update({PartnerApiKey.client_app_id: client_app_id}, synchronize_session="fetch")

    def _shared_live_refs(self, tenant_id: str) -> Set[str]:
        rows = (
            self.db.query(Workspace.external_ref)
            .filter(
                Workspace.tenant_id == tenant_id,
                Workspace.external_ref.isnot(None),
                Workspace.is_trashed.is_(False),
            )
            .group_by(Workspace.external_ref)
            .having(func.count(Workspace.id) > 1)
            .all()
        )
        return {ref for (ref,) in rows}
