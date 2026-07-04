"""Impersonation business logic (plan 03 §13).

Enforces the rules (must hold `users.impersonate`; not self; target active + not an
impersonator; same tenant) and keeps at most one active session per admin.
"""
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.dependencies import IMPERSONATE_PERMISSION, effective_permission_keys
from app.models.impersonation import ImpersonationSession
from app.models.user import User, UserStatus
from app.repositories.user_repository import UserRepository


class ImpersonationError(Exception):
    """Base class for impersonation domain errors."""


class NotAllowed(ImpersonationError):
    """Real user lacks the users.impersonate permission."""


class CannotImpersonateSelf(ImpersonationError):
    pass


class TargetNotFound(ImpersonationError):
    pass


class TargetNotImpersonatable(ImpersonationError):
    """Target is inactive, or is itself an impersonator (no peer/escalation games)."""


class TargetMorePrivileged(ImpersonationError):
    """Target holds permissions the impersonator lacks — would be an escalation."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ImpersonationService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)

    def _active(self, admin_id: str) -> Optional[ImpersonationSession]:
        return (
            self.db.query(ImpersonationSession)
            .filter(
                ImpersonationSession.admin_user_id == admin_id,
                ImpersonationSession.ended_at.is_(None),
            )
            .first()
        )

    def start(
        self,
        real_user: User,
        target_id: str,
        *,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[ImpersonationSession, User]:
        if IMPERSONATE_PERMISSION not in effective_permission_keys(real_user):
            raise NotAllowed()
        if not target_id or target_id == real_user.id:
            raise CannotImpersonateSelf()

        target = self.users.get_by_id(target_id, real_user.tenant_id)
        if target is None:
            raise TargetNotFound()
        if target.status != UserStatus.ACTIVE.value:
            raise TargetNotImpersonatable()
        # Can't impersonate another user who can also impersonate.
        if IMPERSONATE_PERMISSION in effective_permission_keys(target):
            raise TargetNotImpersonatable()
        # No escalation: you can only impersonate a user whose permissions you
        # already hold (so impersonation can't grant access you lack).
        if not effective_permission_keys(target) <= effective_permission_keys(real_user):
            raise TargetMorePrivileged()

        # Defensively end any prior active session (also satisfies the unique index).
        existing = self._active(real_user.id)
        if existing is not None:
            existing.ended_at = _now()
            self.db.flush()

        row = ImpersonationSession(
            admin_user_id=real_user.id,
            target_user_id=target.id,
            tenant_id=real_user.tenant_id,
            started_ip=ip,
            started_user_agent=(user_agent or "")[:500] or None,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row, target

    def stop(self, real_user: User) -> bool:
        row = self._active(real_user.id)
        if row is None:
            return False
        row.ended_at = _now()
        self.db.commit()
        return True

    def current(self, real_user: User) -> Optional[Tuple[ImpersonationSession, User]]:
        row = self._active(real_user.id)
        if row is None:
            return None
        target = self.users.get_by_id(row.target_user_id, real_user.tenant_id)
        if target is None:
            return None
        return row, target
