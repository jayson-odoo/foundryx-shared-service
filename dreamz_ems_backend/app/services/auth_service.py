"""Authentication business logic.

Owns the rules; the router only translates these outcomes to HTTP. Raises domain
exceptions (never HTTPException) so the layer stays transport-agnostic.

Security properties (see plan §security):
  - No user enumeration: unknown email and wrong password raise the SAME error.
  - No timing oracle: the unknown-email path still runs a bcrypt comparison
    (against a dummy hash) so it costs ~the same as the wrong-password path.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.tenant import DEFAULT_TENANT_ID, DEFAULT_TENANT_SLUG, Tenant
from app.models.user import User, UserStatus
from app.repositories.user_repository import UserRepository
from app.security import create_access_token, hash_password, verify_password

# Precomputed once; compared against on the user-not-found path to equalize
# response timing with the wrong-password path.
_DUMMY_PASSWORD_HASH = hash_password("dreamz-timing-equalizer")


class AuthError(Exception):
    """Base class for auth domain errors."""


class InvalidCredentials(AuthError):
    """Email unknown OR password wrong — deliberately indistinguishable."""


class AccountInactive(AuthError):
    """User exists and password matched, but the account is not ACTIVE."""


class TenantInactive(AuthError):
    """The tenant is suspended or archived — sign-in blocked (plan 07 §4)."""


class EmailAlreadyExists(AuthError):
    """Signup with an email already taken in the tenant."""


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepository(db)

    def resolve_tenant(self, tenant_slug: Optional[str]) -> Tenant:
        """Resolve the login tenant from its subdomain slug (plan 07 §6).

        Missing slug = the default tenant (local dev / bare domains). Unknown
        slug raises InvalidCredentials — same uniform 401 as a bad password, so
        probing slugs leaks nothing beyond what DNS already exposes.
        """
        slug = (tenant_slug or DEFAULT_TENANT_SLUG).strip().lower()
        tenant = self.db.query(Tenant).filter(Tenant.slug == slug).first()
        if tenant is None:
            raise InvalidCredentials()
        if not tenant.signin_allowed:
            raise TenantInactive()
        return tenant

    def authenticate(
        self, email: str, password: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> User:
        """Return the user on success, else raise an AuthError."""
        user = self.repo.get_by_email(email, tenant_id)

        if user is None:
            # Equalize timing with the real-user path; result is discarded.
            verify_password(password, _DUMMY_PASSWORD_HASH)
            raise InvalidCredentials()

        if not verify_password(password, user.password):
            raise InvalidCredentials()

        if user.status != UserStatus.ACTIVE.value:
            raise AccountInactive()

        self.repo.touch_last_sign_in(user)
        return user

    def issue_token(self, user: User, remember_me: bool = False) -> str:
        # rememberMe = long session (30d) vs the 24h default — the JWT exp is
        # the real session boundary (plan 10 D4).
        return create_access_token(
            {
                "sub": str(user.id),
                "tenant_id": user.tenant_id,
                "email": user.email,
                "name": user.name,
                "avatar": user.avatar,
                "roles": [{"id": r.id, "name": r.name} for r in user.roles],
                "status": user.status,
            },
            expires_minutes=settings.remember_me_expire_minutes if remember_me else None,
        )

    def login(
        self,
        email: str,
        password: str,
        tenant_slug: Optional[str] = None,
        remember_me: bool = False,
    ) -> tuple[User, str]:
        tenant = self.resolve_tenant(tenant_slug)
        user = self.authenticate(email, password, tenant.id)
        return user, self.issue_token(user, remember_me)

    def register(
        self,
        email: str,
        password: str,
        name: Optional[str] = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> User:
        if self.repo.exists_by_email(email, tenant_id):
            raise EmailAlreadyExists()
        user = User(
            tenant_id=tenant_id,
            email=email,
            password=hash_password(password),
            name=name,
            status=UserStatus.ACTIVE.value,  # auto-activate for now
            email_verified_at=datetime.now(timezone.utc),
        )
        try:
            return self.repo.add(user)
        except IntegrityError:
            # Race, or a soft-deleted row with the same (tenant_id, email):
            # exists_by_email() filters is_trashed but the unique index does not.
            self.repo.rollback()
            raise EmailAlreadyExists()
