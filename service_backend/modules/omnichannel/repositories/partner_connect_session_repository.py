"""Partner connect sessions (FSS-1): pure SQLAlchemy reads and the conditional
UPDATEs that make each step single-use. Every partner-facing read is scoped by
``tenant_id`` AND ``client_app_id``; only the public callback looks a session
up by its state hash, which is unique service-wide."""
from datetime import datetime
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import Channel, ClientApp, PartnerApiKey, PartnerConnectSession, Workspace

LIVE_STATUSES = ("OPEN", "AUTHORIZED")


def _claim_free_or_stale(stale_before: Optional[datetime]):
    """No completion runs: ``completed_at`` unset, or (a lease) set before
    ``stale_before`` by a completion that died without releasing it."""
    if stale_before is None:
        return PartnerConnectSession.completed_at.is_(None)
    return or_(
        PartnerConnectSession.completed_at.is_(None),
        PartnerConnectSession.completed_at < stale_before,
    )


class PartnerConnectSessionRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- reads ----
    def get_scoped(
        self, session_id: str, tenant_id: str, client_app_id: str
    ) -> Optional[PartnerConnectSession]:
        return (
            self.db.query(PartnerConnectSession)
            .filter(
                PartnerConnectSession.id == session_id,
                PartnerConnectSession.tenant_id == tenant_id,
                PartnerConnectSession.client_app_id == client_app_id,
            )
            .first()
        )

    def get_by_state_hash(self, state_hash: str) -> Optional[PartnerConnectSession]:
        return (
            self.db.query(PartnerConnectSession)
            .filter(PartnerConnectSession.state_hash == state_hash)
            .first()
        )

    def get_partner_key(self, key_id: str, tenant_id: str) -> Optional[PartnerApiKey]:
        return (
            self.db.query(PartnerApiKey)
            .filter(PartnerApiKey.id == key_id, PartnerApiKey.tenant_id == tenant_id)
            .first()
        )

    def get_client_app(self, client_app_id: str, tenant_id: str) -> Optional[ClientApp]:
        return (
            self.db.query(ClientApp)
            .filter(ClientApp.id == client_app_id, ClientApp.tenant_id == tenant_id)
            .first()
        )

    def get_live_workspace(
        self, workspace_id: str, tenant_id: str, client_app_id: str
    ) -> Optional[Workspace]:
        return (
            self.db.query(Workspace)
            .filter(
                Workspace.id == workspace_id,
                Workspace.tenant_id == tenant_id,
                Workspace.client_app_id == client_app_id,
                Workspace.is_trashed.is_(False),
            )
            .first()
        )

    def get_channels(self, ids, tenant_id: str, workspace_id: str):
        if not ids:
            return []
        rows = (
            self.db.query(Channel)
            .filter(
                Channel.id.in_(list(ids)),
                Channel.tenant_id == tenant_id,
                Channel.workspace_id == workspace_id,
            )
            .all()
        )
        order = {cid: i for i, cid in enumerate(ids)}
        return sorted(rows, key=lambda c: order.get(c.id, 0))

    # ---- writes ----
    def add(self, row: PartnerConnectSession) -> PartnerConnectSession:
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def claim_callback(self, session_id: str, now: datetime) -> bool:
        """OPEN and never claimed -> claimed. False when another request won."""
        n = (
            self.db.query(PartnerConnectSession)
            .filter(
                PartnerConnectSession.id == session_id,
                PartnerConnectSession.status == "OPEN",
                PartnerConnectSession.claimed_at.is_(None),
            )
            .update({"claimed_at": now}, synchronize_session=False)
        )
        self.db.commit()
        return n == 1

    def finish_callback(self, session_id: str, values: dict) -> bool:
        """Write the callback's outcome only while the session is still OPEN
        and claimed; False when it was cancelled or expired meanwhile."""
        n = (
            self.db.query(PartnerConnectSession)
            .filter(
                PartnerConnectSession.id == session_id,
                PartnerConnectSession.status == "OPEN",
                PartnerConnectSession.claimed_at.isnot(None),
            )
            .update(values, synchronize_session=False)
        )
        self.db.commit()
        return n == 1

    def claim_complete(
        self, session_id: str, now: datetime, stale_before: Optional[datetime] = None
    ) -> bool:
        """AUTHORIZED and not being completed (or its claim is stale) -> being completed."""
        n = (
            self.db.query(PartnerConnectSession)
            .filter(
                PartnerConnectSession.id == session_id,
                PartnerConnectSession.status == "AUTHORIZED",
                _claim_free_or_stale(stale_before),
            )
            .update({"completed_at": now}, synchronize_session=False)
        )
        self.db.commit()
        return n == 1

    def record_channel(self, session_id: str, channel_id: str) -> None:
        """Add one created channel to the session's result as soon as it exists."""
        row = (
            self.db.query(PartnerConnectSession)
            .filter(PartnerConnectSession.id == session_id)
            .first()
        )
        if row is None:
            return
        ids = list(row.result_channel_ids or [])
        if channel_id not in ids:
            ids.append(channel_id)
            row.result_channel_ids = ids
            self.db.commit()

    def release_complete(self, session_id: str) -> None:
        self.db.query(PartnerConnectSession).filter(
            PartnerConnectSession.id == session_id,
            PartnerConnectSession.status == "AUTHORIZED",
        ).update({"completed_at": None}, synchronize_session=False)
        self.db.commit()

    def cancel_live(
        self, session_id: str, now: datetime, stale_before: Optional[datetime] = None
    ) -> bool:
        n = (
            self.db.query(PartnerConnectSession)
            .filter(
                PartnerConnectSession.id == session_id,
                PartnerConnectSession.status.in_(LIVE_STATUSES),
                _claim_free_or_stale(stale_before),
            )
            .update(
                {"status": "CANCELLED", "credentials_json": None, "completed_at": now},
                synchronize_session=False,
            )
        )
        self.db.commit()
        return n == 1

    def expire_due(
        self,
        now: datetime,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
        stale_before: Optional[datetime] = None,
    ) -> int:
        """Live sessions past their expiry become EXPIRED, token dropped. A
        session being completed right now (``completed_at`` set, not stale) is
        left alone."""
        q = self.db.query(PartnerConnectSession).filter(
            PartnerConnectSession.status.in_(LIVE_STATUSES),
            _claim_free_or_stale(stale_before),
            PartnerConnectSession.expires_at < now,
        )
        if tenant_id is not None:
            q = q.filter(PartnerConnectSession.tenant_id == tenant_id)
        if session_id is not None:
            q = q.filter(PartnerConnectSession.id == session_id)
        n = q.update({"status": "EXPIRED", "credentials_json": None}, synchronize_session=False)
        self.db.commit()
        return n

    def save(self, row: PartnerConnectSession) -> None:
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
