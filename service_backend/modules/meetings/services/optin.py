"""Opt-in service (S0 plan §5) — the caller's own master toggle (spine M6).

Every method takes the tenant from the caller's JWT; there is no path here that
reads or writes another tenant's row.
"""
from sqlalchemy.orm import Session

from ..models import UserOptIn


class OptInService:
    def __init__(self, db: Session):
        self.db = db

    def get(self, tenant_id: str, user_id: str) -> UserOptIn:
        """The user's toggle, created OFF the first time it is read — off by
        default is the whole point (AC-S0-6), so an absent row and a stored
        ``False`` must be indistinguishable to every caller."""
        row = (
            self.db.query(UserOptIn)
            .filter(UserOptIn.tenant_id == tenant_id, UserOptIn.user_id == user_id)
            .first()
        )
        if row is None:
            row = UserOptIn(tenant_id=tenant_id, user_id=user_id, enabled=False)
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
        return row

    def set(self, tenant_id: str, user_id: str, enabled: bool) -> UserOptIn:
        """Flip the toggle. Switching OFF keeps the mirrored events and the sync
        token: the rows stay (AC-S0-9) and a later re-opt-in resumes
        incrementally instead of refetching the fortnight."""
        row = self.get(tenant_id, user_id)
        row.enabled = enabled
        self.db.commit()
        self.db.refresh(row)
        return row
