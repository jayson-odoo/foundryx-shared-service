"""Partner workspaces (S7): one workspace per partner organisation, keyed by the
partner's own ``externalOrgId`` (``workspaces.external_ref``).

Every read and write is scoped to the partner key's tenant AND client app
(migration 0032). A workspace id from another tenant or another client app, an
unknown id and a trashed workspace all raise the same
``PartnerWorkspaceNotFound`` so the router answers one uniform 404. NULL
parents (written by an older running version) are resolved and persisted by
``get_partner_tenant`` before any route runs (``ClientAppService.heal_tenant``).

``upsert`` is idempotent: the first call creates the workspace through
``WorkspaceService`` (same seeding as the dashboard create, parent set to the
key's client app), later calls return the same row. Two concurrent first calls
race on the partial unique index ``(client_app_id, external_ref) WHERE
external_ref IS NOT NULL AND is_trashed = false``; the loser catches the
IntegrityError, rolls back and re-reads.
"""
from typing import List, NamedTuple, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Workspace
from ..repositories.channel_repository import ChannelRepository
from ..repositories.workspace_repository import WorkspaceRepository
from ..schemas import PartnerWorkspaceItem, WorkspaceCreate, WorkspaceUpdate
from . import statuses
from .channel_service import ChannelService
from .public_gateway_service import PublicGatewayService
from .workspace_service import WorkspaceService


class PartnerScope(NamedTuple):
    """What a partner key may reach: one client app of one tenant."""

    tenant_id: str
    client_app_id: str


class PartnerWorkspaceNotFound(Exception):
    pass


class PartnerChannelNotFound(Exception):
    pass


class PartnerWorkspaceService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = WorkspaceRepository(db)

    # ---- reads ----
    def require(self, scope: PartnerScope, workspace_id: str) -> Workspace:
        """The client app's live workspace, or ``PartnerWorkspaceNotFound``."""
        ws = self.repo.get_in_client_app(workspace_id, scope.tenant_id, scope.client_app_id)
        if ws is None or ws.is_trashed:
            raise PartnerWorkspaceNotFound()
        return ws

    def list(
        self, scope: PartnerScope, external_ref: Optional[str], page: int, page_size: int
    ) -> Tuple[List[Workspace], int]:
        return self.repo.paginate_live_by_external_ref(
            scope.tenant_id,
            external_ref,
            scope.client_app_id,
            page=page,
            page_size=page_size,
        )

    def _live(self, scope: PartnerScope, external_ref: str) -> Optional[Workspace]:
        return self.repo.get_live_by_external_ref(scope.tenant_id, external_ref, scope.client_app_id)

    # ---- writes ----
    def upsert(self, scope: PartnerScope, external_ref: str, name: str) -> Workspace:
        name = name.strip()
        existing = self._live(scope, external_ref)
        if existing is None:
            try:
                created = WorkspaceService(self.db).create_with_external_ref(
                    WorkspaceCreate(name=name), scope.tenant_id, external_ref, scope.client_app_id
                )
                return self.require(scope, created.id)
            except IntegrityError:
                # A concurrent first call created it between our read and insert.
                self.db.rollback()
                existing = self._live(scope, external_ref)
                if existing is None:
                    raise
        if existing.name != name:
            WorkspaceService(self.db).update(
                existing.id, WorkspaceUpdate(name=name), scope.tenant_id
            )
            self.db.refresh(existing)
        return existing

    def disconnect_channel(self, scope: PartnerScope, workspace_id: str, channel_id: str) -> None:
        """FSS-3: disconnect one live channel of one of the client app's
        workspaces through the existing ``ChannelService.disconnect`` (the
        dashboard's own path). Another workspace's, an unknown or an already
        disconnected channel raises ``PartnerChannelNotFound``."""
        ws = self.require(scope, workspace_id)
        channel = ChannelRepository(self.db).get_by_id(channel_id, scope.tenant_id)
        if channel is None or channel.workspace_id != ws.id or channel.is_trashed:
            raise PartnerChannelNotFound()
        ChannelService(self.db).disconnect([channel.id], scope.tenant_id)

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
