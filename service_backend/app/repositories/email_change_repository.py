"""Email-change request repository (plan sprint-2/04)."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.email_change_request import (
    CHANGE_CANCELLED,
    CHANGE_PENDING_NEW,
    CHANGE_PENDING_OLD,
    EmailChangeRequest,
)

_NON_TERMINAL = (CHANGE_PENDING_OLD, CHANGE_PENDING_NEW)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EmailChangeRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, row: EmailChangeRequest, *, commit: bool = True) -> EmailChangeRequest:
        self.db.add(row)
        if commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            # Caller owns the transaction — the service commits each ceremony
            # step atomically via the outbox enqueue (review fix: a crash
            # between separate commits stranded the ceremony).
            self.db.flush()
        return row

    def save(self, row: EmailChangeRequest, *, commit: bool = True) -> EmailChangeRequest:
        self.db.add(row)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
        return row

    def get_pending_for_user(
        self, user_id: str, tenant_id: str
    ) -> Optional[EmailChangeRequest]:
        """The user's outstanding (non-terminal, unexpired) request, if any."""
        return (
            self.db.query(EmailChangeRequest)
            .filter(
                EmailChangeRequest.user_id == user_id,
                EmailChangeRequest.tenant_id == tenant_id,
                EmailChangeRequest.status.in_(_NON_TERMINAL),
                EmailChangeRequest.expires_at > _now(),
            )
            .order_by(EmailChangeRequest.created_at.desc())
            .first()
        )

    def get_by_old_token(self, token: str) -> Optional[EmailChangeRequest]:
        """Redeemable old-side row. Looked up by token alone — the 256-bit
        secret is the capability (invite-token convention); the service
        re-scopes the user lookup with row.tenant_id afterwards."""
        return self._redeemable(EmailChangeRequest.old_token, token, CHANGE_PENDING_OLD)

    def get_by_new_token(self, token: str) -> Optional[EmailChangeRequest]:
        return self._redeemable(EmailChangeRequest.new_token, token, CHANGE_PENDING_NEW)

    def _redeemable(self, column, token: str, expected_status: str):
        if not token:
            return None
        # Expiry in the WHERE clause — same idiom as get_pending_for_user
        # (expired vs missing is indistinguishable to callers anyway).
        return (
            self.db.query(EmailChangeRequest)
            .filter(
                column == token,
                EmailChangeRequest.status == expected_status,
                EmailChangeRequest.expires_at > _now(),
            )
            .first()
        )

    def cancel_outstanding(
        self, user_id: str, tenant_id: str, *, commit: bool = True
    ) -> int:
        """A new request (or an explicit cancel) supersedes every prior
        outstanding one — mirrors invite_token.invalidate_for_user."""
        updated = (
            self.db.query(EmailChangeRequest)
            .filter(
                EmailChangeRequest.user_id == user_id,
                EmailChangeRequest.tenant_id == tenant_id,
                EmailChangeRequest.status.in_(_NON_TERMINAL),
            )
            .update(
                {EmailChangeRequest.status: CHANGE_CANCELLED},
                synchronize_session=False,
            )
        )
        if commit:
            self.db.commit()
        return updated
