"""Profile-portal request dependencies (sprint-4/06 slice 0a).

``current_profile`` mirrors core ``get_current_user``: decode the JWT, REJECT
anything that is not a portal token (``kind != "profile"`` — a staff JWT must
never authenticate the portal and vice versa, AC-06-11), resolve the Profile
tenant-scoped, and re-check the tenant lifecycle per request (AC-06-13).

``require_portal_permission(key)`` gates protected portal endpoints (AC-06-14).
In 0a the effective key set is empty (personas land in 0b); the resolution is
isolated in ``effective_portal_keys`` so 0b just fills it.
"""
from typing import Callable, List, Optional, Set, Tuple

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import DEFAULT_TENANT_ID, Tenant
from app.security import decode_access_token
from modules.ems.models import Profile
from modules.ems.portal_auth_repository import PortalAuthRepository
from modules.ems.portal_auth_service import PROFILE_TOKEN_KIND

# Separate scheme from the staff one — its tokenUrl points at the portal login.
portal_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/portal/auth/login", auto_error=True)

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

_TENANT_INACTIVE_EXC = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="This tenant is suspended. Contact support.",
)


def effective_portal_keys(db: Session, profile: Profile) -> Set[str]:
    """The Profile's effective portal-permission keys (AC-06-14).

    Union of ``persona_permissions.permission_key`` over every persona the
    profile is a member of, tenant-scoped (a persona / membership in another
    tenant never leaks). Resolved FRESH from the DB on every gate so a revoked
    grant denies on the NEXT request without a re-login (mirrors core
    ``effective_permission_keys``) — every consumer reads through here.
    """
    from modules.ems.persona_repository import PersonaRepository

    return set(
        PersonaRepository(db).effective_permission_keys(profile.tenant_id, profile.id)
    )


def profile_persona_memberships(
    db: Session, profile: Profile
) -> List[Tuple[str, str, Optional[str]]]:
    """The profile's persona memberships as ``(persona_key, scope_type, scope_id)``
    tuples (tenant-scoped) — surfaces scope their data to the granting
    membership's contexts (slice-2 consumers; provided now)."""
    from modules.ems.models import Persona
    from modules.ems.persona_repository import PersonaRepository

    memberships = PersonaRepository(db).list_memberships_for_profile(
        profile.tenant_id, profile.id
    )
    persona_keys = {
        p.id: p.key
        for p in db.query(Persona).filter(Persona.tenant_id == profile.tenant_id).all()
    }
    return [
        (persona_keys.get(m.persona_id, ""), m.scope_type, m.scope_id)
        for m in memberships
    ]


def current_profile(
    token: str = Depends(portal_oauth2_scheme),
    db: Session = Depends(get_db),
) -> Profile:
    """The authenticated Profile for this request — tenant-scoped, lifecycle
    re-checked. Rejects non-portal (staff) tokens by the ``kind`` claim."""
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise _CREDENTIALS_EXC

    # A staff JWT (no kind / different kind) must never authenticate the portal.
    if payload.get("kind") != PROFILE_TOKEN_KIND:
        raise _CREDENTIALS_EXC

    profile_id: Optional[str] = payload.get("sub")
    if not profile_id:
        raise _CREDENTIALS_EXC

    tenant_id: str = payload.get("tenant_id") or DEFAULT_TENANT_ID
    profile = PortalAuthRepository(db).get_by_id(profile_id, tenant_id)
    if profile is None:
        raise _CREDENTIALS_EXC

    # Tenant lifecycle re-check per request (mirrors _resolve_user) — suspending
    # a tenant kills its live portal sessions on the next request.
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None or not tenant.signin_allowed:
        raise _TENANT_INACTIVE_EXC
    return profile


def require_portal_permission(key: str) -> Callable[..., Profile]:
    """Dependency factory: 403 unless the current Profile holds ``key`` (AC-06-14).

    Empty key set in 0a → always 403 for any gated endpoint until 0b grants
    portal keys via personas.
    """

    def dependency(
        profile: Profile = Depends(current_profile),
        db: Session = Depends(get_db),
    ) -> Profile:
        if key not in effective_portal_keys(db, profile):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing portal permission: {key}",
            )
        return profile

    return dependency
