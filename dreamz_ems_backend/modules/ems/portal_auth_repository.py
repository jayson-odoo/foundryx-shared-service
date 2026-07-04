"""Profile-portal auth repository (sprint-4/06 slice 0a) — pure SQLAlchemy.

Every query is tenant-scoped (the tenant comes from the authenticated/resolved
context, never client input). Mirrors core's UserRepository + InviteToken repo
shape, but against the EMS ``Profile`` + ``ProfileAuthToken`` tables.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from modules.ems.models import Profile, ProfileAuthToken


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PortalAuthRepository:
    def __init__(self, db: Session):
        self.db = db

    # ── profiles ─────────────────────────────────────────────────────────────

    def get_by_email(self, email: str, tenant_id: str) -> Optional[Profile]:
        """Active (non-deleted) profile by tenant + lower(email)."""
        return (
            self.db.query(Profile)
            .filter(
                Profile.tenant_id == tenant_id,
                func.lower(Profile.email) == email.strip().lower(),
                Profile.is_deleted.is_(False),
            )
            .first()
        )

    def get_by_id(self, profile_id: str, tenant_id: str) -> Optional[Profile]:
        return (
            self.db.query(Profile)
            .filter(
                Profile.id == profile_id,
                Profile.tenant_id == tenant_id,
                Profile.is_deleted.is_(False),
            )
            .first()
        )

    def save(self, profile: Profile, *, commit: bool = True) -> Profile:
        self.db.add(profile)
        if commit:
            self.db.commit()
            self.db.refresh(profile)
        else:
            self.db.flush()
        return profile

    # ── auth tokens (single-use, expiring) ───────────────────────────────────

    def invalidate_outstanding(self, profile_id: str, tenant_id: str, kind: str) -> None:
        """Mark every unredeemed token of this kind used (issuing a new one
        invalidates prior outstanding ones — mirrors forgot-password)."""
        (
            self.db.query(ProfileAuthToken)
            .filter(
                ProfileAuthToken.tenant_id == tenant_id,
                ProfileAuthToken.profile_id == profile_id,
                ProfileAuthToken.kind == kind,
                ProfileAuthToken.used_at.is_(None),
            )
            .update({ProfileAuthToken.used_at: _now()}, synchronize_session=False)
        )

    def create_token(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        kind: str,
        token: str,
        expires_at: datetime,
        grant_persona_key: Optional[str] = None,
        grant_scope_type: Optional[str] = None,
        grant_scope_id: Optional[str] = None,
        commit: bool = True,
    ) -> ProfileAuthToken:
        row = ProfileAuthToken(
            tenant_id=tenant_id,
            profile_id=profile_id,
            kind=kind,
            token=token,
            expires_at=expires_at,
            grant_persona_key=grant_persona_key,
            grant_scope_type=grant_scope_type,
            grant_scope_id=grant_scope_id,
        )
        self.db.add(row)
        if commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get_active_by_token(self, token: str, tenant_id: str, kind: str) -> Optional[ProfileAuthToken]:
        """Unredeemed + unexpired token matching the secret (SET_PASSWORD path —
        the secret is the indexed plaintext capability)."""
        row = (
            self.db.query(ProfileAuthToken)
            .filter(
                ProfileAuthToken.tenant_id == tenant_id,
                ProfileAuthToken.kind == kind,
                ProfileAuthToken.token == token,
                ProfileAuthToken.used_at.is_(None),
            )
            .first()
        )
        if row is None or row.expires_at <= _now():
            return None
        return row

    def list_active_for_profile(
        self, profile_id: str, tenant_id: str, kind: str
    ) -> list[ProfileAuthToken]:
        """Unredeemed + unexpired tokens for a profile (OTP path — the stored
        value is hashed, so we fetch candidates and verify in the service)."""
        rows = (
            self.db.query(ProfileAuthToken)
            .filter(
                ProfileAuthToken.tenant_id == tenant_id,
                ProfileAuthToken.profile_id == profile_id,
                ProfileAuthToken.kind == kind,
                ProfileAuthToken.used_at.is_(None),
            )
            .all()
        )
        now = _now()
        return [r for r in rows if r.expires_at > now]

    def mark_used(self, row: ProfileAuthToken, *, commit: bool = True) -> None:
        row.used_at = _now()
        self.db.add(row)
        if commit:
            self.db.commit()
        else:
            self.db.flush()
