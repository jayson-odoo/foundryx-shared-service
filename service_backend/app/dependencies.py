"""Shared FastAPI dependencies - current-user resolution, impersonation, gating.

`get_current_user` returns the *effective* user (the impersonation target when an
active session matches the `X-Impersonate-User-Id` header), so permission checks +
tenant scoping reflect the target. `get_real_user` ignores the header (used by the
impersonation endpoints). `get_actor_user_id` always returns the real admin, so
records are never attributed to the impersonated user (plan 03 §13).
"""
from typing import Callable, Optional, Set

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import DEFAULT_TENANT_ID
from app.models.user import User, UserStatus
from app.repositories.user_repository import UserRepository
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=True)

IMPERSONATE_HEADER = "X-Impersonate-User-Id"
IMPERSONATE_PERMISSION = "users.impersonate"

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

_TENANT_INACTIVE_EXC = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="This tenant is suspended. Contact support.",
)


def _resolve_user(token: str, db: Session) -> User:
    """Decode the JWT and load the real user (tenant-scoped). No impersonation.

    Also re-checks the tenant's lifecycle per request (plan 07 §4) - suspending
    or archiving a tenant kills its live sessions on their next request.
    """
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise _CREDENTIALS_EXC

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise _CREDENTIALS_EXC

    # A Profile-portal token (kind="profile") must NEVER authenticate a staff
    # endpoint - defense-in-depth so the staff/portal boundary doesn't rely on
    # id-space disjointness alone (plan sprint-4/06 AC-06-11). Staff tokens carry
    # no `kind` claim (None).
    if payload.get("kind") == "profile":
        raise _CREDENTIALS_EXC

    # An omnichannel embed access token (typ="embed", plan 11H) authenticates ONLY
    # the embed principal on the omnichannel conversation API/WS - it must never
    # authenticate a staff endpoint (defense-in-depth: the boundary can't rely on
    # id-space disjointness alone; its `sub` is an external-agent id).
    if payload.get("typ") == "embed":
        raise _CREDENTIALS_EXC

    tenant_id: str = payload.get("tenant_id") or DEFAULT_TENANT_ID
    user = UserRepository(db).get_by_id(user_id, tenant_id)
    if user is None:
        raise _CREDENTIALS_EXC

    # user.tenant (and its status) ride the user query via lazy="joined" - the
    # lifecycle re-check costs no extra round-trip.
    if user.tenant is None or not user.tenant.signin_allowed:
        raise _TENANT_INACTIVE_EXC
    return user


def effective_permission_keys(user: User) -> Set[str]:
    """Union of permission keys across all the user's roles (resolved per request).

    Read fresh from the DB (via the selectin-loaded role.permissions), NOT from
    the JWT - so RBAC edits take effect immediately, not on token refresh.
    """
    keys: Set[str] = set()
    for role in user.roles:
        for perm in role.permissions:
            keys.add(perm.key)
    return keys


def _maybe_apply_impersonation(request: Request, db: Session, real_user: User) -> User:
    """Swap to the target user when a valid active impersonation session matches.

    Stashes the real user on ``request.state.real_user`` regardless. Stale/invalid
    headers are silently ignored - the admin simply browses as themselves.
    """
    request.state.real_user = real_user
    target_id = request.headers.get(IMPERSONATE_HEADER)
    if not target_id:
        return real_user
    # Only users that may impersonate can have the header honored.
    if IMPERSONATE_PERMISSION not in effective_permission_keys(real_user):
        return real_user

    from app.models.impersonation import ImpersonationSession

    row = (
        db.query(ImpersonationSession)
        .filter(
            ImpersonationSession.admin_user_id == real_user.id,
            ImpersonationSession.target_user_id == target_id,
            ImpersonationSession.ended_at.is_(None),
        )
        .first()
    )
    if row is None:
        return real_user

    target = UserRepository(db).get_by_id(target_id, real_user.tenant_id)
    if target is None or target.status != UserStatus.ACTIVE.value:
        return real_user

    request.state.impersonation_session_id = row.id
    return target


def get_real_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """The authenticated user, ignoring impersonation - used by the impersonation
    endpoints so an impersonated session can't start/stop its own impersonation."""
    real_user = _resolve_user(token, db)
    request.state.real_user = real_user
    return real_user


def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """The *effective* user - the impersonation target when active, else the real user."""
    real_user = _resolve_user(token, db)
    return _maybe_apply_impersonation(request, db, real_user)


def get_actor_user_id(request: Request, current_user: User = Depends(get_current_user)) -> str:
    """The *real* user id for audit / created_by - stays the admin while impersonating."""
    real = getattr(request.state, "real_user", None)
    if isinstance(real, User) and real.id:
        return str(real.id)
    return str(current_user.id)


def require_permission(key: str) -> Callable[..., User]:
    """Dependency factory: 403 unless the current (effective) user holds `key`.

    No superuser bypass - Admin passes because it is seeded with every key.
    """

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if key not in effective_permission_keys(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {key}",
            )
        return current_user

    return dependency


def require_module(name: str) -> Callable[..., User]:
    """Dependency factory: 403 unless `name` is installed AND ACTIVE for the
    current user's tenant (plan 08 §6). Injected by the module loader at
    ``include_router`` time - module code stays untouched. Same fresh-from-DB
    philosophy as ``require_permission``: deactivation applies on the next
    request, no token refresh needed.
    """

    def dependency(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        from app.repositories.module_repository import ModuleRepository

        if not ModuleRepository(db).is_active(current_user.tenant_id, name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Module not installed",
            )
        return current_user

    return dependency


def module_version(db: Session, tenant_id: str, name: str) -> Optional[str]:
    """The version this tenant's DATA is provisioned at (None = not installed)."""
    from app.repositories.module_repository import ModuleRepository

    return ModuleRepository(db).installed_version(tenant_id, name)


def requires_version(name: str, spec: str) -> Callable[..., User]:
    """Version gate for endpoints introduced after a module's 1.0 (plan 08 §6).

    ``spec`` is ``">=X.Y.Z"`` - tenants provisioned below it get 403 until they
    run Update (D4: version gating, not code pinning). First real use arrives
    with the first post-1.0 module feature.
    """
    if not spec.startswith(">="):
        # Wiring error, not a request error - fail loudly at import/decoration
        # time (asserts vanish under `python -O`, so raise explicitly).
        raise ValueError(f"requires_version: only '>=' specs are supported, got {spec!r}")
    minimum = spec[2:].strip()

    def dependency(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        from app.models.module import parse_version

        installed = module_version(db, current_user.tenant_id, name)
        if installed is None or parse_version(installed) < parse_version(minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This feature requires {name} {spec}. Update the module.",
            )
        return current_user

    return dependency


def require_platform_permission(key: str) -> Callable[..., User]:
    """Dependency factory for platform-operator endpoints (plan 07 §5).

    Double lock: the user must hold `key` AND belong to the platform tenant -
    a tenant role that somehow acquired a platform key is still blocked. Keys
    off the tenant's `is_platform` flag (the schema's source of truth), not the
    seeded id constant.
    """

    def dependency(current_user: User = Depends(require_permission(key))) -> User:
        if current_user.tenant is None or not current_user.tenant.is_platform:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Platform operators only.",
            )
        return current_user

    return dependency
