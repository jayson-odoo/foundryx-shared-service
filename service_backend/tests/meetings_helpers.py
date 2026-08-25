"""Shared builders for the meetings suite — a second tenant, users, opt-ins and
a fake calendar source. Kept out of ``conftest.py`` so it is importable as a
plain module and obvious at the call site.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.models import DEFAULT_TENANT_ID, Role, Tenant, User, UserStatus
from app.security import hash_password
from app.seed import tenant_admin_grant
from modules.meetings.calendar.base import (
    CalendarSourceError,
    RawEvent,
    SyncPage,
    SyncTokenInvalid,
)


def utc(*args) -> datetime:
    """Aware-UTC datetime — the only kind this codebase stores or compares."""
    return datetime(*args, tzinfo=timezone.utc)


def make_tenant(db: Session, tenant_id: str, name: str) -> Tenant:
    """A second tenant reusing the default tenant's lifecycle status."""
    default = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).one()
    tenant = Tenant(
        id=tenant_id,
        name=name,
        slug=name.lower().replace(" ", "-"),
        status_id=default.status_id,
    )
    db.add(tenant)
    db.flush()
    return tenant


def make_admin_user(
    db: Session, tenant_id: str, email: str, password: str = "demo1234", name: str = "User"
) -> User:
    """An ACTIVE user holding that tenant's full Admin grant."""
    role = (
        db.query(Role).filter(Role.tenant_id == tenant_id, Role.name == "Admin").first()
    )
    if role is None:
        role = Role(
            tenant_id=tenant_id, name="Admin", description="Full access", is_system=True
        )
        role.permissions = tenant_admin_grant(db, tenant_id)
        db.add(role)
        db.flush()
    user = User(
        tenant_id=tenant_id,
        email=email,
        password=hash_password(password),
        name=name,
        status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    user.roles = [role]
    db.add(user)
    db.flush()
    return user


def opt_in(db: Session, tenant_id: str, user_id: str, *, enabled: bool = True):
    """Flip a user's master toggle directly (the sync's only precondition)."""
    from modules.meetings.models import UserOptIn

    row = (
        db.query(UserOptIn)
        .filter(UserOptIn.tenant_id == tenant_id, UserOptIn.user_id == user_id)
        .first()
    )
    if row is None:
        row = UserOptIn(tenant_id=tenant_id, user_id=user_id, enabled=enabled)
        db.add(row)
    else:
        row.enabled = enabled
    db.flush()
    return row


class FakeCalendarSource:
    """A scripted ``CalendarSource`` — the stand-in for Google in every test.

    ``pages`` maps a user's email to the list of ``SyncPage``s successive reads
    return; the last page repeats once the script runs out. Set
    ``invalid_token_for`` to make the FIRST read that carries a sync token raise
    ``SyncTokenInvalid`` (Google's HTTP 410), which is what the fallback path
    must recover from. ``calls`` records every read for assertions.

    Google also drops ``nextSyncToken`` from any response carrying an
    ``orderBy``, which is why the adapter never sends one - guarded where that
    parameter is actually built, in ``test_meetings_shared_calendar.py``.

    **A tokenless read never yields a cancelled event.** ``events.list`` defaults
    to ``showDeleted=false``, so a full-window read simply OMITS an event the
    calendar has dropped; only an incremental (tokened) read reports it with
    ``status="cancelled"``. Getting this wrong is what let the first cut of the
    sync believe a full read could see cancellations at all.
    """

    kind = "fake"

    def __init__(
        self,
        pages: Dict[str, List[SyncPage]],
        *,
        invalid_token_for: Optional[str] = None,
        error_for: Optional[str] = None,
    ):
        self._pages = {email: list(pages_) for email, pages_ in pages.items()}
        self._invalid_token_for = invalid_token_for
        self._error_for = error_for
        self.calls: List[dict] = []

    def list_events(
        self,
        *,
        user_email: str,
        sync_token: Optional[str] = None,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
    ) -> SyncPage:
        self.calls.append(
            {
                "user_email": user_email,
                "sync_token": sync_token,
                "time_min": time_min,
                "time_max": time_max,
            }
        )
        if self._error_for == user_email:
            raise CalendarSourceError("calendar usage limits exceeded")
        if sync_token and self._invalid_token_for == user_email:
            self._invalid_token_for = None  # only the first tokened read 410s
            raise SyncTokenInvalid("Sync token is no longer valid")
        queue = self._pages.get(user_email) or [SyncPage()]
        page = queue.pop(0) if len(queue) > 1 else queue[0]
        if sync_token:
            return page
        # showDeleted defaults false: a full read omits cancellations entirely.
        return SyncPage(
            events=[e for e in page.events if not e.cancelled],
            next_sync_token=page.next_sync_token,
        )


def raw_event(
    external_id: str,
    *,
    starts_at: datetime,
    ends_at: Optional[datetime] = None,
    title: Optional[str] = "Meeting",
    organiser_email: Optional[str] = "organiser@example.com",
    attendees: Optional[List[dict]] = None,
    conference_url: Optional[str] = "https://meet.google.com/abc-defg-hij",
    cancelled: bool = False,
) -> RawEvent:
    return RawEvent(
        external_id=external_id,
        starts_at=starts_at,
        ends_at=ends_at,
        title=title,
        organiser_email=organiser_email,
        attendees=attendees if attendees is not None else [],
        conference_url=conference_url,
        cancelled=cancelled,
    )
