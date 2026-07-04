"""Channel business logic — tenant-scoped. Owns status transitions + the
Test Connection call via the channel adapter."""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.tenant import DEFAULT_TENANT_ID
from ..adapters.whatsapp_cloud import get_adapter
from ..models import (
    Channel,
    ContactChannelIdentity,
    ConversationMessage,
    WhatsappTemplate,
    Workspace,
)
from ..repositories.channel_repository import ChannelRepository
from ..schemas import ChannelItem, ChannelUpdate, TestConnectionResult
from ..security import decrypt_credentials
from . import statuses


class ChannelNotFound(Exception):
    pass


class ChannelService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ChannelRepository(db)

    # ---- helpers ----
    def _workspace_names(self, tenant_id: str, ws_ids: List[str]) -> dict:
        if not ws_ids:
            return {}
        rows = (
            self.db.query(Workspace.id, Workspace.name)
            .filter(Workspace.tenant_id == tenant_id, Workspace.id.in_(ws_ids))
            .all()
        )
        return {wid: name for wid, name in rows}

    def _items(self, rows: List[Channel], tenant_id: str) -> List[ChannelItem]:
        smap = statuses.id_to_key_map(self.db, tenant_id)
        wsmap = self._workspace_names(tenant_id, list({c.workspace_id for c in rows}))
        return [
            ChannelItem(
                id=c.id,
                tenantId=c.tenant_id,
                workspaceId=c.workspace_id,
                workspaceName=wsmap.get(c.workspace_id, "Workspace"),
                channelType=c.channel_type,
                name=c.name,
                status=smap.get(c.status_id, "ACTIVE"),
                isActive=c.is_active,
                wabaId=c.waba_id,
                phoneNumberId=c.phone_number_id,
                displayPhoneNumber=c.display_phone_number,
                businessAccountName=c.business_account_name,
                verifiedName=c.verified_name,
                lastVerifiedAt=c.last_verified_at,
                profileSyncedAt=c.profile_synced_at,
                isTrashed=c.is_trashed,
                createdAt=c.created_at,
                updatedAt=c.updated_at,
            )
            for c in rows
        ]

    # ---- reads ----
    def list(
        self,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        status_view: str = "active",
    ) -> Tuple[List[ChannelItem], int]:
        rows, total = self.repo.paginate(
            tenant_id, page=page, page_size=page_size, search=search,
            sort_by=sort_by, sort_dir=sort_dir, trashed=status_view == "trashed",
        )
        return self._items(rows, tenant_id), total

    def get(self, channel_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> ChannelItem:
        c = self.repo.get_by_id(channel_id, tenant_id)
        if c is None:
            raise ChannelNotFound()
        return self._items([c], tenant_id)[0]

    def get_at(
        self, index: int, tenant_id: str = DEFAULT_TENANT_ID, *, status_view: str = "active",
        search: Optional[str] = None, sort_by: Optional[str] = None, sort_dir: str = "asc",
    ) -> Tuple[Optional[ChannelItem], int]:
        rows, total = self.repo.paginate(
            tenant_id, page=0, page_size=10_000, search=search, sort_by=sort_by,
            sort_dir=sort_dir, trashed=status_view == "trashed",
        )
        if index < 0 or index >= len(rows):
            return None, total
        return self._items([rows[index]], tenant_id)[0], total

    def list_by_workspace(self, ws_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> List[ChannelItem]:
        return self._items(self.repo.list_by_workspace(ws_id, tenant_id), tenant_id)

    # ---- writes ----
    def update(
        self, channel_id: str, payload: ChannelUpdate, tenant_id: str = DEFAULT_TENANT_ID
    ) -> ChannelItem:
        c = self.repo.get_by_id(channel_id, tenant_id)
        if c is None:
            raise ChannelNotFound()
        if payload.name is not None:
            c.name = payload.name.strip()
        if payload.isActive is not None:
            c.is_active = payload.isActive
            key = "ACTIVE" if payload.isActive else "INACTIVE"
            c.status_id = statuses.status_id_for(self.db, tenant_id, "CHANNEL", key)
        self.db.commit()
        self.db.refresh(c)
        return self._items([c], tenant_id)[0]

    def test_connection(
        self, channel_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> TestConnectionResult:
        c = self.repo.get_by_id(channel_id, tenant_id)
        if c is None:
            raise ChannelNotFound()
        creds = decrypt_credentials(c.credentials_json) if c.credentials_json else {}
        status = get_adapter(c.channel_type).test_connection(creds, c.phone_number_id or "")
        now = datetime.now(timezone.utc)
        if status.ok:
            c.last_verified_at = now
            self.db.commit()
        return TestConnectionResult(ok=status.ok, message=status.message, checkedAt=now)

    def disconnect(self, ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> None:
        inactive = statuses.status_id_for(self.db, tenant_id, "CHANNEL", "INACTIVE")
        for c in self.repo.get_many(ids, tenant_id):
            c.is_trashed = True
            c.is_active = False
            c.status_id = inactive
        self.db.commit()

    def restore(self, ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> None:
        active = statuses.status_id_for(self.db, tenant_id, "CHANNEL", "ACTIVE")
        for c in self.repo.get_many(ids, tenant_id):
            c.is_trashed = False
            c.is_active = True
            c.status_id = active
        self.db.commit()

    def remove(self, ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> None:
        """Hard-delete channels. The FKs pointing at ``channels.id`` have no
        ON DELETE CASCADE, so a raw ``db.delete`` raises IntegrityError when the
        channel has identities/templates/messages (rolling back the whole batch
        — why 'Delete permanently' silently failed). Detach dependents first:
        messages keep their history (channel_id is nullable → set NULL),
        identities + templates are channel-owned → deleted."""
        channels = self.repo.get_many(ids, tenant_id)
        if not channels:
            return
        cids = [c.id for c in channels]
        self.db.query(ConversationMessage).filter(
            ConversationMessage.channel_id.in_(cids)
        ).update({ConversationMessage.channel_id: None}, synchronize_session=False)
        self.db.query(ContactChannelIdentity).filter(
            ContactChannelIdentity.channel_id.in_(cids)
        ).delete(synchronize_session=False)
        self.db.query(WhatsappTemplate).filter(
            WhatsappTemplate.channel_id.in_(cids)
        ).delete(synchronize_session=False)
        for c in channels:
            self.db.delete(c)
        self.db.commit()
