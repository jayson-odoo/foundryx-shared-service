"""User management business logic (Service layer).

Owns workflow + rules (invite on create, INVITED is system-managed, soft-trash,
CSV export). Routers translate these to HTTP; repositories do the SQL.
"""
import csv
import io
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from sqlalchemy import not_

from app.models.role import Role
from app.models.tenant import DEFAULT_TENANT_ID, DEFAULT_TENANT_SLUG, Tenant
from app.models.user import User, UserStatus
from app.repositories.invite_token_repository import InviteTokenRepository
from app.repositories.role_repository import RoleRepository
from app.repositories.user_repository import UserRepository
from app.workflow_engine.entity_events import notify_entity_event
from app.schemas.filters import FilterCondition
from app.schemas.user import FilterGroup
from app.security import hash_password
from app.services.email_service import email_service
from app.services.filter_translator import FilterError, translate_filter

def _invite_ttl() -> timedelta:
    """Read at call time so ops can tune Settings without restarts (plan 10 D2)."""
    return timedelta(minutes=settings.invite_token_ttl_minutes)


def _reset_ttl() -> timedelta:
    return timedelta(minutes=settings.reset_token_ttl_minutes)

# Whitelisted filter columns for the users list (field -> column).
_USER_FILTER_COLUMNS = {
    "name": User.name,
    "user": User.name,
    "email": User.email,
    "status": User.status,
    "joined": User.created_at,
    "lastSignIn": User.last_sign_in_at,
}


def _user_special(cond: FilterCondition):
    """Roles are many-to-many — filter via membership (not a plain column)."""
    if cond.field != "role":
        return None
    op, val = cond.operator, cond.value
    if op == "in":
        values = val if isinstance(val, list) else [val]
        return User.roles.any(Role.name.in_(values))
    if op == "eq":
        return User.roles.any(Role.name == val)
    if op == "neq":
        return not_(User.roles.any(Role.name == val))
    raise FilterError(f"unsupported operator for role: {op}")


class UserServiceError(Exception):
    """Base class for user-management domain errors."""


class UserNotFound(UserServiceError):
    pass


class EmailExists(UserServiceError):
    pass


class InvalidToken(UserServiceError):
    pass


class SelfEmailChange(UserServiceError):
    """Admins change their OWN email via the ceremony, never the user form."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UserService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.roles = RoleRepository(db)
        self.invites = InviteTokenRepository(db)

    # ---- Read ----

    def list(
        self,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
        status_view: str = "active",
    ) -> Tuple[List[User], int]:
        clause = translate_filter(filter_group, _USER_FILTER_COLUMNS, _user_special)
        return self.users.list(
            tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_clause=clause,
            status_view=status_view,
        )

    def get(self, user_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> User:
        # include_trashed so a trashed user's form (Restore) can still be opened.
        user = self.users.get_by_id(user_id, tenant_id, include_trashed=True)
        if user is None:
            raise UserNotFound()
        return user

    def get_at(
        self,
        index: int,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
        status_view: str = "active",
    ) -> Tuple[Optional[User], int]:
        rows, total = self.list(
            tenant_id,
            page=max(index, 0),
            page_size=1,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=filter_group,
            status_view=status_view,
        )
        return (rows[0] if rows else None), total

    # ---- Write ----

    def create(
        self,
        name: str,
        email: str,
        role_ids: List[str],
        status: str = UserStatus.ACTIVE.value,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> User:
        if self.users.exists_by_email(email, tenant_id):
            raise EmailExists()
        user = User(
            tenant_id=tenant_id,
            name=name,
            email=email,
            status=UserStatus.INVITED.value,  # invite flow → INVITED until set-password
            password=None,
        )
        user.roles = self.roles.get_many(role_ids, tenant_id)
        try:
            self.users.add(user)
        except IntegrityError:
            self.users.rollback()
            raise EmailExists()
        self._send_invite(user)
        notify_entity_event(self.db, "user", "created", user, tenant_id=tenant_id)
        return user

    def update(
        self,
        user_id: str,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        name: Optional[str] = None,
        email: Optional[str] = None,
        role_ids: Optional[List[str]] = None,
        status: Optional[str] = None,
        actor_id: Optional[str] = None,
    ) -> User:
        user = self.get(user_id, tenant_id)
        changes: dict = {}
        if name is not None and user.name != name:
            changes["name"] = {"from": user.name, "to": name}
            user.name = name
        old_email: Optional[str] = None
        if email is not None and email.strip().lower() != (user.email or "").lower():
            # Admin instant path (plan sprint-2/04): actor ≠ target only — own
            # email goes through the dual-confirmation ceremony. FAIL CLOSED:
            # a caller that can't name the actor doesn't get the instant path
            # (review fix — an omitted Optional kwarg must not bypass the guard).
            if actor_id is None or actor_id == user.id:
                raise SelfEmailChange()
            normalized = email.strip().lower()
            # include_trashed: mirror uq_users_tenant_email's full scope.
            if self.users.exists_by_email(normalized, tenant_id, include_trashed=True):
                raise EmailExists()
            old_email = user.email
            changes["email"] = {"from": old_email, "to": normalized}
            user.email = normalized
            # The new mailbox never proved deliverability — the Verified badge
            # must not carry over from the previous address (review fix).
            user.email_verified_at = None
        if role_ids is not None:
            user.roles = self.roles.get_many(role_ids, tenant_id)
        # INVITED is system-managed — a profile save must not change it.
        if status is not None and user.status != UserStatus.INVITED.value and user.status != status:
            changes["status"] = {"from": user.status, "to": status}
            user.status = status
        try:
            saved = self.users.save(user)
        except IntegrityError:
            self.users.rollback()
            raise EmailExists()
        notify_entity_event(self.db, "user", "updated", saved, tenant_id=tenant_id, actor_id=actor_id, changes=changes or None)
        if old_email is not None:
            # Instant change → notify BOTH addresses (plan 04 decision 2).
            for recipient in (old_email, saved.email):
                email_service.send_email_change_notice(
                    self.db,
                    recipient,
                    tenant_id,
                    old_email=old_email,
                    new_email=saved.email,
                )
        return saved

    def trash(self, ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> None:
        self.users.set_trashed(ids, tenant_id, True)

    def restore(self, ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> None:
        self.users.set_trashed(ids, tenant_id, False)

    def invite(self, ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> int:
        """(Re)send invitations to the INVITED users among `ids`."""
        sent = 0
        for user_id in ids:
            user = self.users.get_by_id(user_id, tenant_id, include_trashed=True)
            if user and user.status == UserStatus.INVITED.value:
                self._send_invite(user)
                sent += 1
        return sent

    def reset_password(self, user_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> None:
        user = self.get(user_id, tenant_id)
        self._issue_reset(user)

    def forgot_password(self, email: str, tenant_slug: Optional[str] = None) -> None:
        """Public forgot-password (plan 10 §3). Enumeration-safe by design:
        EVERY outcome returns silently — unknown tenant/email, inactive or
        trashed user all do the same dummy token-generation work and send
        nothing. The router replies with the uniform message regardless.
        """
        slug = (tenant_slug or DEFAULT_TENANT_SLUG).strip().lower()
        tenant = self.db.query(Tenant).filter(Tenant.slug == slug).first()
        user = None
        if tenant is not None and tenant.signin_allowed:
            user = self.users.get_by_email(email, tenant.id)
        if user is None or user.status != UserStatus.ACTIVE.value:
            secrets.token_urlsafe(32)  # timing-shape parity with the found path
            return
        self._issue_reset(user)

    def resend_verification(self, user_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> None:
        user = self.get(user_id, tenant_id)
        email_service.send_verification(
            self.db, user.email, f"{settings.frontend_url}/verify-email", tenant_id
        )

    def set_password(self, token: str, password: str) -> User:
        row = self.invites.get_active(token)
        if row is None:
            raise InvalidToken()
        user = self.users.get_by_id(row.user_id, row.tenant_id, include_trashed=True)
        if user is None:
            raise InvalidToken()
        user.password = hash_password(password)
        if user.status == UserStatus.INVITED.value:
            user.status = UserStatus.ACTIVE.value
        if user.email_verified_at is None:
            user.email_verified_at = _now()
        self.users.save(user)
        self.invites.mark_used(row)
        return user

    # ---- Export ----

    def export_csv(
        self,
        columns: List[str],
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        ids: Optional[List[str]] = None,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
        status_view: str = "active",
    ) -> str:
        rows, _ = self.list(
            tenant_id,
            page=0,
            page_size=100_000,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=filter_group,
            status_view=status_view,
        )
        if ids:
            id_set = set(ids)
            rows = [u for u in rows if u.id in id_set]

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(columns)
        for user in rows:
            writer.writerow([_column_value(user, c) for c in columns])
        return buffer.getvalue()

    # ---- internal ----

    def _send_invite(self, user: User) -> None:
        token = secrets.token_urlsafe(32)
        self.invites.create(token, user.id, _now() + _invite_ttl(), user.tenant_id)
        email_service.send_invite(
            self.db, user.email, f"{settings.frontend_url}/change-password?token={token}", user.tenant_id
        )

    def _issue_reset(self, user: User) -> None:
        """Single-use reset link: prior outstanding tokens die first (plan 10
        §3), then a fresh token (reset TTL) is issued and the email enqueued
        via the plan-09 outbox."""
        self.invites.invalidate_for_user(user.id, user.tenant_id)
        token = secrets.token_urlsafe(32)
        self.invites.create(token, user.id, _now() + _reset_ttl(), user.tenant_id)
        email_service.send_password_reset(
            self.db, user.email, f"{settings.frontend_url}/change-password?token={token}", user.tenant_id
        )


def _column_value(user: User, column: str) -> str:
    if column == "id":
        return user.id  # the import match key — enables export → edit → update
    if column in ("user", "name"):
        return user.name or ""
    if column == "email":
        return user.email
    if column == "role":
        return "; ".join(r.name for r in user.roles)
    if column == "status":
        return user.status
    if column == "joined":
        return user.created_at.isoformat() if user.created_at else ""
    if column == "lastSignIn":
        return user.last_sign_in_at.isoformat() if user.last_sign_in_at else ""
    return ""
