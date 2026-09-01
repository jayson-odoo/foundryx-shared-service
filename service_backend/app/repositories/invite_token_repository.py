"""Invite-token repository."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.invite_token import InviteToken
from app.models.tenant import DEFAULT_TENANT_ID


class InviteTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        token: str,
        user_id: str,
        expires_at: datetime,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> InviteToken:
        row = InviteToken(
            token=token,
            user_id=user_id,
            tenant_id=tenant_id,
            expires_at=expires_at,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_active(self, token: str) -> Optional[InviteToken]:
        # Looked up by token alone: the 256-bit secret is the capability, and
        # set_password re-scopes the user lookup with row.tenant_id afterwards.
        row = (
            self.db.query(InviteToken)
            .filter(InviteToken.token == token, InviteToken.used_at.is_(None))
            .first()
        )
        if row is None:
            return None
        if row.expires_at < datetime.now(timezone.utc):
            return None
        return row

    def mark_used(self, row: InviteToken) -> None:
        row.used_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()

    def invalidate_for_user(self, user_id: str, tenant_id: str) -> int:
        """Kill a user's outstanding (unused) tokens - a new reset supersedes
        every prior link (plan 10 §3)."""
        now = datetime.now(timezone.utc)
        updated = (
            self.db.query(InviteToken)
            .filter(
                InviteToken.user_id == user_id,
                InviteToken.tenant_id == tenant_id,
                InviteToken.used_at.is_(None),
            )
            .update({InviteToken.used_at: now}, synchronize_session=False)
        )
        self.db.commit()
        return updated
