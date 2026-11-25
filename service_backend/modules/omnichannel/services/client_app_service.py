"""Client apps: the consuming application that owns a tenant's workspaces and
partner keys (client app -> workspaces -> channels). One tenant may hold
several client apps (for example EcoHub, Sorento and MyFuji in one tenant).

The rule (migration 0032, its ``create_schema_and_tables`` mirror and
``backfill_tenant`` here all apply it):

1. A workspace without an external_ref joins the client app whose name
   matches its own, normalised (trimmed, case-insensitive), created when
   missing and named after the group's live workspace (oldest first). So a
   trashed "Ecohub" shares the live "Ecohub"'s client app.
2. Each tenant has exactly one ``is_default`` client app: the one of its
   default workspace, else its oldest. It is only the fallback parent of a
   partner key that has none (and of a pre-existing partner-made workspace).
3. A dashboard-created workspace joins (find-or-create) the client app named
   after it; a partner-created workspace joins the calling key's client app;
   module install's "General" gets its own "General" client app, the
   tenant's default.

The parent columns stay nullable for one release, so code never assumes they
are set: a NULL parent (a row an older running version wrote during a deploy)
is resolved by the same rule and persisted (``heal_tenant``).

Only the partner routes look at a client app's status; workspace keys,
webhooks, the dashboard and the public gateway never do.
"""
from typing import Callable, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.tenant import Tenant

from ..models import ClientApp, PartnerApiKey, Workspace
from ..repositories.client_app_repository import ClientAppRepository

STATUS_ACTIVE = "ACTIVE"
FALLBACK_NAME = "Default"


class ClientAppNotFound(Exception):
    pass


class ClientAppInvalidName(Exception):
    pass


class ClientAppNameConflict(Exception):
    pass


class ClientAppService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ClientAppRepository(db)

    # ---- find or create (race-safe, no commit: the caller owns the unit of work) ----
    def _insert(self, make: Callable[[], ClientApp], reread: Callable[[], Optional[ClientApp]]) -> ClientApp:
        try:
            with self.db.begin_nested():
                app = make()
                self.db.add(app)
                self.db.flush()
            return app
        except IntegrityError:
            # A concurrent call created it (unique name or one-default index).
            winner = reread()
            if winner is None:
                raise
            return winner

    def find_or_create_by_name(self, tenant_id: str, name: str, created_by: str) -> ClientApp:
        """The tenant's client app with this normalised name, created (not
        default) when missing."""
        name = (name or "").strip()
        existing = self.repo.get_by_name(tenant_id, name)
        if existing is not None:
            return existing
        return self._insert(
            lambda: ClientApp(
                tenant_id=tenant_id,
                name=name,
                is_default=False,
                status=STATUS_ACTIVE,
                created_by=created_by,
            ),
            lambda: self.repo.get_by_name(tenant_id, name),
        )

    def ensure_default(self, tenant_id: str) -> Optional[ClientApp]:
        """Rule 2: the tenant's default client app, marking the right one when
        none is marked yet. None when the tenant has no client app at all."""
        existing = self.repo.get_default(tenant_id)
        if existing is not None:
            return existing
        candidate = self.repo.default_candidate(tenant_id)
        if candidate is None:
            return None
        try:
            with self.db.begin_nested():
                candidate.is_default = True
                self.db.flush()
        except IntegrityError:
            pass  # a concurrent call marked one
        return self.repo.get_default(tenant_id)

    def default_for_tenant(self, tenant_id: str) -> ClientApp:
        """The tenant's default client app. A tenant with no client app at all
        (partner key but no workspace) gets one named after the tenant."""
        app = self.ensure_default(tenant_id)
        if app is not None:
            return app
        self.backfill_tenant(tenant_id)
        app = self.repo.get_default(tenant_id)
        if app is not None:
            return app
        tenant = self.db.get(Tenant, tenant_id)
        name = ((tenant.name if tenant is not None else "") or "").strip() or FALLBACK_NAME
        return self._insert(
            lambda: ClientApp(
                tenant_id=tenant_id,
                name=name,
                is_default=True,
                status=STATUS_ACTIVE,
                created_by="backfill",
            ),
            lambda: self.repo.get_default(tenant_id),
        )

    # ---- backfill (Python twin of migration 0032 step 3) ----
    def backfill_tenant(self, tenant_id: str) -> None:
        """Idempotent: attach every NULL-parent workspace and partner key of
        the tenant by the rule above. No commit."""
        for ws in self.repo.unassigned_named_workspaces(tenant_id):
            app = self.find_or_create_by_name(tenant_id, ws.name, created_by="backfill")
            self.repo.set_parent(ws.id, app.id)
        self.db.flush()
        default = self.ensure_default(tenant_id)
        if default is not None:
            self.repo.attach_partner_rows(tenant_id, default.id)
        self.db.flush()

    def heal_tenant(self, tenant_id: str) -> None:
        """The read fallback: resolve and persist NULL parents, if any."""
        if self.repo.has_unassigned(tenant_id):
            self.backfill_tenant(tenant_id)

    # ---- partner keys ----
    def for_partner_key(self, key: PartnerApiKey) -> ClientApp:
        """The client app a partner key acts for: its own, or (NULL parent) the
        tenant's default. Always within the key's tenant."""
        if key.client_app_id:
            app = self.repo.get(key.client_app_id, key.tenant_id)
            if app is not None:
                return app
        return self.default_for_tenant(key.tenant_id)

    def require(self, client_app_id: str, tenant_id: str) -> ClientApp:
        app = self.repo.get(client_app_id, tenant_id)
        if app is None:
            raise ClientAppNotFound()
        return app

    # ---- dashboard read ----
    def list_with_workspaces(self, tenant_id: str) -> List[Tuple[ClientApp, int, List[Workspace]]]:
        self.heal_tenant(tenant_id)
        self.db.commit()
        grouped = self.repo.live_workspaces_by_app(tenant_id)
        return [
            (app, len(grouped.get(app.id, [])), grouped.get(app.id, []))
            for app in self.repo.list_for_tenant(tenant_id)
        ]

    def item_state(self, client_app_id: str, tenant_id: str) -> Tuple[ClientApp, int, List[Workspace]]:
        app = self.require(client_app_id, tenant_id)
        workspaces = self.repo.live_workspaces_for_app(client_app_id, tenant_id)
        return app, len(workspaces), workspaces

    # ---- dashboard writes (create, rename, move a workspace) ----
    def create_named(self, tenant_id: str, name: str, created_by: str) -> ClientApp:
        """An explicit 'new client app' action: unlike
        ``find_or_create_by_name`` (the dashboard workspace-create path), a
        name already in use is a conflict, never a silent reuse."""
        name = (name or "").strip()
        if not name:
            raise ClientAppInvalidName()
        if self.repo.get_by_name(tenant_id, name) is not None:
            raise ClientAppNameConflict()
        try:
            app = self._insert(
                lambda: ClientApp(
                    tenant_id=tenant_id,
                    name=name,
                    is_default=False,
                    status=STATUS_ACTIVE,
                    created_by=created_by,
                ),
                lambda: None,
            )
        except IntegrityError as exc:
            raise ClientAppNameConflict() from exc
        self.db.commit()
        self.db.refresh(app)
        return app

    def rename(self, client_app_id: str, tenant_id: str, name: str) -> ClientApp:
        app = self.require(client_app_id, tenant_id)
        name = (name or "").strip()
        if not name:
            raise ClientAppInvalidName()
        existing = self.repo.get_by_name(tenant_id, name)
        if existing is not None and existing.id != app.id:
            raise ClientAppNameConflict()
        app.name = name
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ClientAppNameConflict() from exc
        self.db.refresh(app)
        return app

    def move_workspace(self, client_app_id: str, tenant_id: str, workspace_id: str) -> Workspace:
        """Re-point a workspace to another of the tenant's client apps. Its
        workspace keys and webhook endpoints key off ``workspace_id`` and keep
        working. Partner connect sessions carry the ``client_app_id`` stamped
        at creation, so an in-flight session of the old client app stops
        working (callback and complete answer ``connect_session_not_found``)."""
        from .workspace_service import WorkspaceExternalRefInUse, WorkspaceNotFound

        target = self.require(client_app_id, tenant_id)
        ws = self.repo.get_workspace(workspace_id, tenant_id)
        if ws is None:
            raise WorkspaceNotFound()
        if ws.client_app_id == target.id:
            return ws
        ws.client_app_id = target.id
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise WorkspaceExternalRefInUse(ws.id) from exc
        self.db.refresh(ws)
        return ws


