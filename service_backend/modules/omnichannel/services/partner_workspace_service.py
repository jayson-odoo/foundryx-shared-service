"""Partner workspaces (S7): one workspace per partner organisation, keyed by the
partner's own ``externalOrgId`` (``workspaces.external_ref``).

Every read and write is scoped to the partner key's tenant. A workspace id from
another tenant, an unknown id and a trashed workspace all raise the same
``PartnerWorkspaceNotFound`` so the router answers one uniform 404.

``upsert`` is idempotent: the first call creates the workspace through
``WorkspaceService`` (same seeding as the dashboard create), later calls return
the same row. Two concurrent first calls race on the partial unique index
``(tenant_id, external_ref) WHERE external_ref IS NOT NULL AND is_trashed =
false``; the loser catches the IntegrityError, rolls back and re-reads.
"""
from typing import List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Workspace
from ..repositories.workspace_repository import WorkspaceRepository
from ..schemas import PartnerWorkspaceItem, WorkspaceCreate, WorkspaceUpdate
from . import statuses
from .public_gateway_service import PublicGatewayService
from .workspace_service import WorkspaceService


class PartnerWorkspaceNotFound(Exception):
    pass


class PartnerWorkspaceService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = WorkspaceRepository(db)

    # ---- reads ----
    def require(self, tenant_id: str, workspace_id: str) -> Workspace:
        """The tenant's live workspace, or ``PartnerWorkspaceNotFound``."""
        ws = self.repo.get_by_id(workspace_id, tenant_id)
        if ws is None or ws.is_trashed:
            raise PartnerWorkspaceNotFound()
        return ws

    def list(
        self, tenant_id: str, external_ref: Optional[str], page: int, page_size: int
    ) -> Tuple[List[Workspace], int]:
        return self.repo.paginate_live_by_external_ref(
            tenant_id, external_ref, page=page, page_size=page_size
        )

    # ---- writes ----
    def upsert(self, tenant_id: str, external_ref: str, name: str) -> Workspace:
        name = name.strip()
        existing = self.repo.get_live_by_external_ref(tenant_id, external_ref)
        if existing is None:
            try:
                created = WorkspaceService(self.db).create_with_external_ref(
                    WorkspaceCreate(name=name), tenant_id, external_ref
                )
                return self.require(tenant_id, created.id)
            except IntegrityError:
                # A concurrent first call created it between our read and insert.
                self.db.rollback()
                existing = self.repo.get_live_by_external_ref(tenant_id, external_ref)
                if existing is None:
                    raise
        if existing.name != name:
            WorkspaceService(self.db).update(existing.id, WorkspaceUpdate(name=name), tenant_id)
            self.db.refresh(existing)
        return existing

    # ---- shapes ----
    def item(self, ws: Workspace) -> PartnerWorkspaceItem:
        smap = statuses.id_to_key_map(self.db, ws.tenant_id)
        return self._item(ws, smap)

    def items(self, rows: List[Workspace], tenant_id: str) -> List[PartnerWorkspaceItem]:
        smap = statuses.id_to_key_map(self.db, tenant_id)
        return [self._item(ws, smap) for ws in rows]

    def _item(self, ws: Workspace, smap) -> PartnerWorkspaceItem:
        return PartnerWorkspaceItem(
            id=ws.id,
            externalOrgId=ws.external_ref,
            name=ws.name,
            status=smap.get(ws.status_id, "ACTIVE"),
            createdAt=ws.created_at,
            channels=PublicGatewayService(self.db).list_channels(ws.tenant_id, ws.id),
        )
