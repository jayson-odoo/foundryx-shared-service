"""Profile-portal authentication business logic (sprint-4/06 slice 0a).

A SEPARATE auth system for EMS ``Profile`` actors, reusing core primitives
(``security.py`` hashing + 72-byte truncation, single-use token machinery,
forgot/set-password convention) — never the staff ``/auth/*`` path or session.

Security posture mirrors core auth:
  - No enumeration: login = uniform InvalidCredentials (unknown email, bad
    password, OTP-only profile all the same); request-otp / forgot-password
    ALWAYS succeed silently (dummy work on the miss path).
  - No timing oracle: the miss path runs a bcrypt comparison against a dummy
    hash so it costs ~the same as the real path.
  - Single-use + expiring tokens; issuing a new token of a kind invalidates the
    profile's prior outstanding ones of that kind.

Raises domain exceptions (never HTTPException) — the router translates to HTTP.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.tenant import DEFAULT_TENANT_SLUG, Tenant
from app.schemas.password import validate_password_strength
from app.security import create_access_token, hash_password, verify_password
from app.services.email_service import email_service
from modules.ems.models import (
    PROFILE_TOKEN_OTP,
    PROFILE_TOKEN_SET_PASSWORD,
    Profile,
)
from modules.ems.portal_auth_repository import PortalAuthRepository

# Precomputed once; compared against on the not-found path to equalize timing.
_DUMMY_PASSWORD_HASH = hash_password("dreamz-portal-timing-equalizer")

# JWT discriminator — a portal token MUST carry kind="profile"; a staff token
# never does. current_profile rejects anything else (AC-06-11).
PROFILE_TOKEN_KIND = "profile"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PortalAuthError(Exception):
    """Base class for portal-auth domain errors."""


class InvalidCredentials(PortalAuthError):
    """Email unknown OR password wrong OR OTP-only — deliberately indistinguishable."""


class TenantInactive(PortalAuthError):
    """Tenant suspended/archived — sign-in blocked (mirrors staff auth)."""


class InvalidToken(PortalAuthError):
    """Set-password / OTP token unknown, expired, or already used."""


class ProfileNotFound(PortalAuthError):
    """Staff-invite path: the profile id does not resolve in the tenant."""


class PortalAuthService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = PortalAuthRepository(db)

    # ── tenant resolution ────────────────────────────────────────────────────

    def resolve_tenant(self, tenant_slug: Optional[str]) -> Tenant:
        """Resolve the portal tenant from its subdomain slug (mirrors core).

        Missing slug = default tenant. Unknown slug raises InvalidCredentials
        (uniform 401 — probing slugs leaks nothing beyond DNS).
        """
        slug = (tenant_slug or DEFAULT_TENANT_SLUG).strip().lower()
        tenant = self.db.query(Tenant).filter(Tenant.slug == slug).first()
        if tenant is None:
            raise InvalidCredentials()
        if not tenant.signin_allowed:
            raise TenantInactive()
        return tenant

    def _resolve_tenant_quiet(self, tenant_slug: Optional[str]) -> Optional[Tenant]:
        """Enumeration-safe resolution for the always-200 paths — returns None
        on unknown/blocked tenant (caller does dummy work + returns silently)."""
        slug = (tenant_slug or DEFAULT_TENANT_SLUG).strip().lower()
        tenant = self.db.query(Tenant).filter(Tenant.slug == slug).first()
        if tenant is None or not tenant.signin_allowed:
            return None
        return tenant

    # ── token claims ─────────────────────────────────────────────────────────

    def issue_token(self, profile: Profile, remember_me: bool = False) -> str:
        """Portal JWT (AC-06-13). ``kind="profile"`` is the discriminator a staff
        token never carries. ``portal_perms`` + ``personas`` are a convenience/UX
        MIRROR of the profile's effective portal keys + scoped persona memberships
        at issue time — but ``require_portal_permission`` resolves FRESH from the
        DB (RBAC edits apply immediately, no re-login), so the claim is never the
        gate of record (slice 0b)."""
        from modules.ems.portal_deps import (
            effective_portal_keys,
            profile_persona_memberships,
        )

        portal_perms = sorted(effective_portal_keys(self.db, profile))
        personas = [
            {"persona": key, "scopeType": st, "scopeId": sid}
            for key, st, sid in profile_persona_memberships(self.db, profile)
        ]
        return create_access_token(
            {
                "sub": str(profile.id),
                "tenant_id": profile.tenant_id,
                "kind": PROFILE_TOKEN_KIND,
                "email": profile.email,
                "portal_perms": portal_perms,
                "personas": personas,
            },
            expires_minutes=settings.remember_me_expire_minutes if remember_me else None,
        )

    # ── login (password primary) ─────────────────────────────────────────────

    def login(
        self,
        email: str,
        password: str,
        tenant_slug: Optional[str] = None,
        remember_me: bool = False,
    ) -> tuple[Profile, str]:
        tenant = self.resolve_tenant(tenant_slug)
        profile = self.repo.get_by_email(email, tenant.id)
        if profile is None:
            verify_password(password, _DUMMY_PASSWORD_HASH)  # timing parity
            raise InvalidCredentials()
        # A profile with no password set must use OTP (uniform 401, no leak).
        if not profile.password_hash or not verify_password(password, profile.password_hash):
            raise InvalidCredentials()
        profile.last_login_at = _now()
        self.repo.save(profile)
        return profile, self.issue_token(profile, remember_me)

    # ── OTP (zero-activation email login) ────────────────────────────────────

    def request_otp(self, email: str, tenant_slug: Optional[str] = None) -> None:
        """Always succeeds silently (no enumeration). On a real match: issue a
        6-digit code (stored hashed), email it. Works even with NULL password."""
        tenant = self._resolve_tenant_quiet(tenant_slug)
        profile = self.repo.get_by_email(email, tenant.id) if tenant else None
        if profile is None:
            secrets.token_urlsafe(16)  # timing-shape parity with the found path
            return
        code = f"{secrets.randbelow(1_000_000):06d}"
        self.repo.invalidate_outstanding(profile.id, profile.tenant_id, PROFILE_TOKEN_OTP)
        self.repo.create_token(
            tenant_id=profile.tenant_id,
            profile_id=profile.id,
            kind=PROFILE_TOKEN_OTP,
            token=hash_password(code),
            expires_at=_now() + timedelta(minutes=settings.profile_otp_ttl_minutes),
        )
        email_service.send_profile_otp(self.db, profile.email, code, profile.tenant_id)

    def login_otp(
        self,
        email: str,
        code: str,
        tenant_slug: Optional[str] = None,
        remember_me: bool = False,
    ) -> tuple[Profile, str]:
        tenant = self.resolve_tenant(tenant_slug)
        profile = self.repo.get_by_email(email, tenant.id)
        if profile is None:
            verify_password(code, _DUMMY_PASSWORD_HASH)  # timing parity
            raise InvalidToken()
        candidates = self.repo.list_active_for_profile(
            profile.id, profile.tenant_id, PROFILE_TOKEN_OTP
        )
        matched = next((r for r in candidates if verify_password(code, r.token)), None)
        if matched is None:
            raise InvalidToken()
        self.repo.mark_used(matched, commit=False)
        if profile.email_verified_at is None:
            profile.email_verified_at = _now()
        profile.last_login_at = _now()
        self.repo.save(profile)  # commits (the used-mark flushed first)
        return profile, self.issue_token(profile, remember_me)

    # ── forgot / set password ────────────────────────────────────────────────

    def forgot_password(self, email: str, tenant_slug: Optional[str] = None) -> None:
        """Always succeeds silently (no enumeration). On a real match: issue a
        SET_PASSWORD token + email the /portal/change-password link."""
        tenant = self._resolve_tenant_quiet(tenant_slug)
        profile = self.repo.get_by_email(email, tenant.id) if tenant else None
        if profile is None:
            secrets.token_urlsafe(32)  # timing-shape parity
            return
        self._issue_set_password(profile)

    def issue_profile_invite(
        self,
        tenant_id: str,
        profile_id: str,
        *,
        grant_persona_key: Optional[str] = None,
        grant_scope_type: Optional[str] = None,
        grant_scope_id: Optional[str] = None,
    ) -> str:
        """Staff-driven set-password invite (AC-06-15 path c). May carry a
        persona+context to grant on acceptance (AC-06-15a / AC-06-22 INVITE
        path). Returns the link. Tenant-scoped resolution."""
        profile = self.repo.get_by_id(profile_id, tenant_id)
        if profile is None:
            raise ProfileNotFound()
        return self._issue_set_password(
            profile,
            grant_persona_key=grant_persona_key,
            grant_scope_type=grant_scope_type,
            grant_scope_id=grant_scope_id,
        )

    def _issue_set_password(
        self,
        profile: Profile,
        *,
        grant_persona_key: Optional[str] = None,
        grant_scope_type: Optional[str] = None,
        grant_scope_id: Optional[str] = None,
    ) -> str:
        self.repo.invalidate_outstanding(
            profile.id, profile.tenant_id, PROFILE_TOKEN_SET_PASSWORD
        )
        token = secrets.token_urlsafe(32)
        self.repo.create_token(
            tenant_id=profile.tenant_id,
            profile_id=profile.id,
            kind=PROFILE_TOKEN_SET_PASSWORD,
            token=token,
            expires_at=_now() + timedelta(minutes=settings.invite_token_ttl_minutes),
            grant_persona_key=grant_persona_key,
            grant_scope_type=grant_scope_type,
            grant_scope_id=grant_scope_id,
        )
        link = f"{settings.frontend_url}/portal/change-password?token={token}"
        email_service.send_profile_set_password(self.db, profile.email, link, profile.tenant_id)
        return link

    def set_password(self, token: str, password: str, tenant_slug: Optional[str] = None) -> Profile:
        """Redeem a SET_PASSWORD token (single-use + expiry + policy). Sets
        password_hash, stamps email_verified_at, marks the token used. If the
        invite carried a persona+context, applies it (granted_via=INVITE,
        AC-06-22) — failure-isolated so a bad grant never strands the redeem."""
        validate_password_strength(password)
        tenant = self.resolve_tenant(tenant_slug)
        row = self.repo.get_active_by_token(token, tenant.id, PROFILE_TOKEN_SET_PASSWORD)
        if row is None:
            raise InvalidToken()
        profile = self.repo.get_by_id(row.profile_id, tenant.id)
        if profile is None:
            raise InvalidToken()
        profile.password_hash = hash_password(password)
        if profile.email_verified_at is None:
            profile.email_verified_at = _now()
        self.repo.mark_used(row, commit=False)
        self.repo.save(profile)  # commits password + used-mark in one txn
        # Apply the invite's persona grant AFTER the redeem commit (its own txn).
        if row.grant_persona_key:
            try:
                from modules.ems.models import (
                    PERSONA_GRANT_INVITE,
                    PERSONA_SCOPE_TENANT,
                )
                from modules.ems.persona_service import grant_persona

                grant_persona(
                    self.db,
                    profile.tenant_id,
                    profile.id,
                    row.grant_persona_key,
                    row.grant_scope_type or PERSONA_SCOPE_TENANT,
                    row.grant_scope_id,
                    PERSONA_GRANT_INVITE,
                )
            except Exception:  # noqa: BLE001 — grant must never strand the redeem
                self.db.rollback()
        return profile
