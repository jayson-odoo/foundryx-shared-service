"""Change-email ceremony (plan sprint-2/04) — Service layer.

Dual confirmation: the OLD mailbox approves the change, the NEW mailbox
proves deliverability; ``users.email`` flips only on the new-side verify
(an old-email approval alone cannot prove the new address is deliverable —
a typo would bind the account to a mailbox nobody owns).

Self-service only — the admin instant path lives in UserService.update.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.email_change_request import (
    CHANGE_COMPLETED,
    CHANGE_PENDING_NEW,
    CHANGE_PENDING_OLD,
    EmailChangeRequest,
)
from app.models.user import User
from app.repositories.email_change_repository import EmailChangeRepository
from app.repositories.user_repository import UserRepository
from app.security import verify_password
from app.services.email_service import email_service


class EmailChangeError(Exception):
    """Base class for change-email domain errors."""


class InvalidPassword(EmailChangeError):
    """Password re-entry rejected — fresh proof of possession failed."""


class SameEmail(EmailChangeError):
    """The requested address is the account's current address."""


class InvalidChangeToken(EmailChangeError):
    """Approve/verify token missing, expired, superseded or already used."""


class EmailTaken(EmailChangeError):
    """The new address lost the uniqueness race at flip time (409)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ttl() -> timedelta:
    """Read at call time so ops can tune Settings without restarts (plan 10 D2)."""
    return timedelta(minutes=settings.email_change_token_ttl_minutes)


def mask_email(email: str) -> str:
    """``name@example.com`` → ``n***@example.com`` — enough for the old-side
    approve mail to identify the request without disclosing the full target."""
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    visible = local[:1]
    return f"{visible}***@{domain}"


class EmailChangeService:
    def __init__(self, db: Session):
        self.db = db
        self.requests = EmailChangeRepository(db)
        self.users = UserRepository(db)

    # ---- Self-service ceremony ----

    def get_pending(self, user: User) -> Optional[EmailChangeRequest]:
        return self.requests.get_pending_for_user(user.id, user.tenant_id)

    def request(self, user: User, new_email: str, password: str) -> EmailChangeRequest:
        """Start the ceremony. Password re-entry = fresh proof of possession
        (a hijacked live session must not be enough to redirect the account's
        mailbox). Uniqueness is deliberately NOT checked here — the response
        stays uniform whether or not the address is taken (no enumeration);
        the flip re-checks transactionally in verify()."""
        if not verify_password(password, user.password or ""):
            raise InvalidPassword()

        normalized = new_email.strip().lower()
        if normalized == (user.email or "").lower():
            raise SameEmail()

        # A new request supersedes every prior outstanding one (plan 04 data
        # model). ONE transaction for cancel + create + enqueue (the enqueue
        # commits) — separate commits could lose the prior request or leave a
        # pending row whose approve mail never sends (review fix).
        self.requests.cancel_outstanding(user.id, user.tenant_id, commit=False)

        row = EmailChangeRequest(
            tenant_id=user.tenant_id,
            user_id=user.id,
            new_email=normalized,
            old_token=secrets.token_urlsafe(32),
            status=CHANGE_PENDING_OLD,
            expires_at=_now() + _ttl(),
        )
        self.requests.create(row, commit=False)

        email_service.send_email_change_approve(
            self.db,
            user.email,
            f"{settings.frontend_url}/approve-email-change?token={row.old_token}",
            user.tenant_id,
            new_email_masked=mask_email(normalized),
        )
        return row

    def cancel(self, user: User) -> None:
        self.requests.cancel_outstanding(user.id, user.tenant_id)

    # ---- Public token redeems ----

    def approve(self, token: str) -> None:
        """OLD-side approve: PENDING_OLD → PENDING_NEW; the new-side token is
        generated only now and mailed to the NEW address."""
        row = self.requests.get_by_old_token(token)
        if row is None:
            raise InvalidChangeToken()
        row.new_token = secrets.token_urlsafe(32)
        row.status = CHANGE_PENDING_NEW
        # commit=False: the enqueue commits flip + mail atomically — a crash
        # between separate commits would consume the old token while the
        # verify mail never sends (review fix).
        self.requests.save(row, commit=False)

        email_service.send_email_change_verify(
            self.db,
            row.new_email,
            f"{settings.frontend_url}/verify-email-change?token={row.new_token}",
            row.tenant_id,
        )

    def verify(self, token: str) -> User:
        """NEW-side verify — THE step that flips the email. Uniqueness is
        re-checked transactionally (the request never checked it); the final
        notice goes to the PREVIOUS address."""
        row = self.requests.get_by_new_token(token)
        if row is None:
            raise InvalidChangeToken()

        # Tenant-scoped resolution of the stored user id (polymorphic
        # target_id rule — never resolve with an unscoped get).
        user = self.users.get_by_id(row.user_id, row.tenant_id)
        if user is None:
            raise InvalidChangeToken()

        # include_trashed: uq_users_tenant_email covers trashed rows too — a
        # trashed holder of the address would pass the active-only check and
        # then 500 at flush instead of this clean 409 (review fix).
        if self.users.exists_by_email(row.new_email, row.tenant_id, include_trashed=True):
            # Row stays PENDING_NEW — the link may be retried within the TTL
            # once the conflict clears; the user can also cancel + re-request.
            raise EmailTaken()

        old_email = user.email
        try:
            user.email = row.new_email
            # They just proved control of the mailbox — that IS verification.
            user.email_verified_at = _now()
            row.status = CHANGE_COMPLETED
            row.completed_at = _now()
            self.db.add(user)
            self.requests.save(row, commit=False)
            # Enqueue commits the whole unit: flip + request row + notice
            # (uq_users_tenant_email backstops the exists check above — the
            # try covers the flush AND the commit, so a constraint race
            # surfaces as 409, never 500).
            email_service.send_email_change_notice(
                self.db,
                old_email,
                row.tenant_id,
                old_email=old_email,
                new_email=row.new_email,
            )
        except IntegrityError:
            self.db.rollback()
            raise EmailTaken()
        return user
