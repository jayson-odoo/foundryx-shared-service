"""Opt-in service (S0 plan §5) — the caller's own master toggle (spine M6).

Every method takes the tenant from the caller's JWT; there is no path here that
reads or writes another tenant's row.
"""
from typing import Optional

from sqlalchemy.orm import Session

from ..models import UserOptIn


class OptInService:
    def __init__(self, db: Session):
        self.db = db

    def _row(self, tenant_id: str, user_id: str) -> Optional[UserOptIn]:
        return (
            self.db.query(UserOptIn)
            .filter(UserOptIn.tenant_id == tenant_id, UserOptIn.user_id == user_id)
            .first()
        )

    def get(self, tenant_id: str, user_id: str) -> UserOptIn:
        """The user's toggle. Off by default is the whole point (AC-S0-6), so an
        absent row and a stored ``False`` are indistinguishable to the caller -
        which is exactly why a READ returns a TRANSIENT default rather than
        writing a row for everyone who merely opened the page."""
        row = self._row(tenant_id, user_id)
        if row is None:
            return UserOptIn(tenant_id=tenant_id, user_id=user_id, enabled=False)
        return row

    def set(self, tenant_id: str, user_id: str, enabled: bool) -> UserOptIn:
        """Flip the toggle - the only path that creates the row.

        Switching OFF keeps the mirrored events and the sync token: the rows stay
        (AC-S0-9) and a later re-opt-in resumes incrementally instead of
        refetching the fortnight."""
        row = self._row(tenant_id, user_id)
        if row is None:
            row = UserOptIn(tenant_id=tenant_id, user_id=user_id, enabled=enabled)
            self.db.add(row)
        row.enabled = enabled
        self.db.commit()
        self.db.refresh(row)
        return row
