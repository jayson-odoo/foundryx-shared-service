"""Opt-in service (S0 plan §5) - the caller's own master toggle (spine M6).

Every method takes the tenant from the caller's JWT; there is no path here that
reads or writes another tenant's row.

It also owns the answer to "WHICH calendar is this user's?", because the opt-in
row is where the override lives: ``calendar_address_for`` is the one definition
the sync and the connection test both read, so the two can never disagree about
what the service account is supposed to be able to see.
"""
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import UserOptIn

def calendar_address_for(opt_in: Any, user: Any) -> Optional[str]:
    """The calendar address to read for this user.

    ``calendar_email`` when they set one - a Workspace that blocks external
    sharing cannot share its own users' calendars with our service account, so
    the calendar they CAN share is often a personal address - else their login
    email, which is what domain-wide delegation always impersonates."""
    explicit = (getattr(opt_in, "calendar_email", None) or "").strip()
    if explicit:
        return explicit
    return (getattr(user, "email", None) or "").strip() or None


def enabled_calendar_email_index(opt_ins: List[UserOptIn]) -> Dict[str, str]:
    """``calendar_email`` (lowercased) -> ``user_id``, ENABLED opt-ins only.

    The additional match participant resolution needs on top of login email: a
    shared calendar's attendee list carries whatever address the calendar
    itself uses, which is often not the user's login (shared-calendar mode).
    Filtering on ``enabled`` here rather than only at the caller means a
    caller that mixes enabled and disabled rows can never accidentally
    resurrect a toggled-off user."""
    return {
        (row.calendar_email or "").strip().lower(): row.user_id
        for row in opt_ins
        if row.enabled and row.calendar_email
    }


def opted_in_calendars(db: Optional[Session], tenant_id: Optional[str]) -> List[str]:
    """Every opted-in user's calendar address for this tenant, deduped, sorted.

    Sorted by ADDRESS, not by ``user_id``: the ids are uuids, so ordering by
    them is effectively random and the connection test would list the same
    calendars in a different order on every run."""
    if db is None or not tenant_id:
        return []
    from app.models.user import User

    rows = (
        db.query(UserOptIn)
        .filter(UserOptIn.tenant_id == tenant_id, UserOptIn.enabled.is_(True))
        .order_by(UserOptIn.user_id.asc())
        .all()
    )
    if not rows:
        return []
    users = {
        user.id: user
        for user in db.query(User)
        .filter(User.tenant_id == tenant_id, User.id.in_([r.user_id for r in rows]))
        .all()
    }
    out = {
        address
        for row in rows
        if (address := calendar_address_for(row, users.get(row.user_id)))
    }
    return sorted(out)


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

    def set(
        self,
        tenant_id: str,
        user_id: str,
        enabled: bool,
        *,
        calendar_email: Optional[str] = None,
        set_calendar_email: bool = False,
    ) -> UserOptIn:
        """Flip the toggle - the only path that creates the row.

        Switching OFF keeps the mirrored events and the sync token: the rows stay
        (AC-S0-9) and a later re-opt-in resumes incrementally instead of
        refetching the fortnight.

        ``set_calendar_email`` tells "not sent" from "sent as null": only a
        client that actually sent the key changes the stored address, so flipping
        the toggle from anywhere else never silently clears it. Changing the
        address DROPS the sync token - it belongs to the calendar that minted it,
        and reusing it against a different calendar is a 400 from Google."""
        row = self._row(tenant_id, user_id)
        if row is None:
            row = UserOptIn(tenant_id=tenant_id, user_id=user_id, enabled=enabled)
            self.db.add(row)
        row.enabled = enabled
        if set_calendar_email:
            cleaned = (calendar_email or "").strip() or None
            if cleaned != row.calendar_email:
                row.calendar_email = cleaned
                row.sync_token = None
                row.last_synced_at = None
        self.db.commit()
        self.db.refresh(row)
        return row
