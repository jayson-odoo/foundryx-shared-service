"""Actor-pool resolver registry (plan sprint-4/06 Part 2, AC-06-30).

The review engine is CORE and must never import the EMS module - but a PERSONA
role's actor pool is "every Profile holding persona X", which only EMS can
compute. So PERSONA/STAFF_ROLE pools are resolved through an INJECTABLE hook:

- core registers ``STAFF_ROLE`` (pool = the Users assigned a staff role) at
  import time below;
- Part B (EMS) registers ``PERSONA`` (pool = Profiles holding a persona, scoped
  to the submission's context) at module install - ``register_engine_entities``.

A resolver takes ``(db, tenant_id, role, submission)`` and returns an ordered
list of ``(actor_kind, actor_id)`` candidates (tenant-scoped internally - the
polymorphic-target_id rule). A source with NO registered resolver resolves to
``[]`` (fail-closed) - never a crash. This keeps the same shape as the
capability registry and the status-entity registry.

Mirrors the ``register_capability`` seam: a boot-time dict keyed by source.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

if TYPE_CHECKING:  # pragma: no cover - avoid an ORM import cycle at runtime
    from app.models.review import ReviewRole

logger = logging.getLogger("foundryx.reviews.resolvers")

# A resolver: (db, tenant_id, role, submission) -> ordered [(actor_kind, actor_id)].
ActorPoolResolver = Callable[
    [Session, str, "ReviewRole", object], List[Tuple[str, str]]
]

# A contact resolver: (db, tenant_id, actor_id) -> (email, name) | None. Keyed by
# actor_kind ("user" | "profile"). Core registers "user"; EMS registers "profile"
# at install - keeps core EMS-free (the same injectable-hook shape as the pool
# resolver). allocate/escalate notify reviewers through this; a missing kind or
# contact is a silent skip (failure-isolated - a notify hiccup never breaks
# allocation).
ActorContactResolver = Callable[[Session, str, str], Optional[Tuple[str, str]]]

# A context-label resolver: (db, tenant_id, context_id) -> human label | None.
# Keyed by a config's ``context_type`` ("project"). EMS registers "project" →
# the event/project name at install (keeps core EMS-free - the same injectable
# hook shape). A missing kind / unresolvable id yields None so the surface falls
# back to a generic label; never raises (label resolution is cosmetic).
ContextLabelResolver = Callable[[Session, str, str], Optional[str]]

# A surface granter: (db, tenant_id, profile_id, capability, context_type,
# context_id) -> None. The hook a PROFILE actor's portal surface key is granted
# through when the actor is BOUND TO A REVIEW ROLE (AC-06-22 - persona
# auto-derived "bound to a review role → reviewer"). Core stays EMS-free: it
# never knows about personas/portal keys, it just calls the granter. EMS
# registers one at install that maps capability → system persona key and
# grant_persona's it (via=AUTO), scoped to the config context. ``capability`` is
# one of {"submit", "review", "decide"}. With NO granter registered the
# ``grant_actor_surface`` helper is a NO-OP (never raises) - a non-EMS
# deployment has no portal surfaces to grant.
SurfaceGranter = Callable[[Session, str, str, str, Optional[str], Optional[str]], None]

_RESOLVERS: Dict[str, ActorPoolResolver] = {}
_CONTACT_RESOLVERS: Dict[str, ActorContactResolver] = {}
_CONTEXT_LABEL_RESOLVERS: Dict[str, ContextLabelResolver] = {}
_SURFACE_GRANTER: Optional[SurfaceGranter] = None


def register_actor_pool_resolver(source: str, fn: ActorPoolResolver) -> None:
    """Register the pool resolver for an ``actor_source`` (PERSONA / STAFF_ROLE).
    Idempotent overwrite - re-registering the same source replaces it (a module
    reinstall must not double-register)."""
    _RESOLVERS[source] = fn


def get_actor_pool_resolver(source: str) -> ActorPoolResolver | None:
    return _RESOLVERS.get(source)


def resolve_actor_pool(
    db: Session, tenant_id: str, role: "ReviewRole", submission: object
) -> List[Tuple[str, str]]:
    """Ordered candidate pool for a PERSONA/STAFF_ROLE role, or ``[]`` when no
    resolver is registered for the source (fail-closed, never raise)."""
    fn = _RESOLVERS.get(role.actor_source)
    if fn is None:
        return []
    return fn(db, tenant_id, role, submission)


def _staff_role_resolver(
    db: Session, tenant_id: str, role: "ReviewRole", submission: object
) -> List[Tuple[str, str]]:
    """Core STAFF_ROLE pool = the Users assigned the bound staff role, scoped to
    the tenant, in a STABLE order (user id). The bound id is resolved
    tenant-scoped - a foreign/planted staff-role id yields an empty pool."""
    from app.models.role import Role, user_roles
    from app.models.user import User

    if not role.bound_staff_role_id:
        return []
    rows = (
        db.query(User.id)
        .join(user_roles, user_roles.c.user_id == User.id)
        .join(Role, Role.id == user_roles.c.role_id)
        .filter(
            Role.id == role.bound_staff_role_id,
            Role.tenant_id == tenant_id,
            User.tenant_id == tenant_id,
        )
        .order_by(User.id.asc())
        .all()
    )
    return [("user", r[0]) for r in rows]


# Core fills STAFF_ROLE at import; EMS fills PERSONA at install (Part B).
register_actor_pool_resolver("STAFF_ROLE", _staff_role_resolver)


# ── contact resolver hook (Part B) ───────────────────────────────────────────


def register_actor_contact_resolver(kind: str, fn: ActorContactResolver) -> None:
    """Register the (email, name) resolver for an ``actor_kind``. Idempotent
    overwrite (a module reinstall must not double-register)."""
    _CONTACT_RESOLVERS[kind] = fn


def get_actor_contact_resolver(kind: str) -> Optional[ActorContactResolver]:
    return _CONTACT_RESOLVERS.get(kind)


def resolve_actor_contact(
    db: Session, tenant_id: str, kind: str, actor_id: str
) -> Optional[Tuple[str, str]]:
    """(email, name) for an actor, or None when no resolver is registered for the
    kind OR the actor can't be resolved (e.g. a deleted/foreign id). Tenant-scoped
    internally (the polymorphic-target_id rule); never raises - allocate/escalate
    notify best-effort."""
    fn = _CONTACT_RESOLVERS.get(kind)
    if fn is None:
        return None
    try:
        return fn(db, tenant_id, actor_id)
    except Exception:  # noqa: BLE001 - a resolver hiccup is a silent skip
        return None


def _user_contact_resolver(
    db: Session, tenant_id: str, actor_id: str
) -> Optional[Tuple[str, str]]:
    """Core staff-user contact, tenant-scoped. Skips trashed users."""
    from app.models.user import User

    user = (
        db.query(User)
        .filter(
            User.id == actor_id,
            User.tenant_id == tenant_id,
            User.is_trashed.is_(False),
        )
        .first()
    )
    if user is None or not user.email:
        return None
    return (user.email, user.name or user.email)


register_actor_contact_resolver("user", _user_contact_resolver)


# ── context-label resolver hook (AC-06-25 - real event names) ─────────────────


def register_context_label_resolver(context_type: str, fn: ContextLabelResolver) -> None:
    """Register the human-label resolver for a config's ``context_type``
    ("project"). Idempotent overwrite (a module reinstall must not double-register)."""
    _CONTEXT_LABEL_RESOLVERS[context_type] = fn


def resolve_context_label(
    db: Session, tenant_id: str, context_type: Optional[str], context_id: Optional[str]
) -> Optional[str]:
    """The human label for a config's bound context (e.g. the event/project name),
    or None when no resolver is registered / the id is unresolvable / either is
    unset. Tenant-scoped internally (the polymorphic-target_id rule); never raises
    (label resolution is cosmetic - the surface falls back to a generic label)."""
    if not context_type or not context_id:
        return None
    fn = _CONTEXT_LABEL_RESOLVERS.get(context_type)
    if fn is None:
        return None
    try:
        return fn(db, tenant_id, context_id)
    except Exception:  # noqa: BLE001 - a resolver hiccup is a silent skip
        return None


# ── surface granter hook (AC-06-22 - bound to a review role → persona) ─────────


def register_surface_granter(fn: SurfaceGranter) -> None:
    """Register the portal-surface granter (EMS, at install). Idempotent overwrite
    - a module reinstall must not double-register."""
    global _SURFACE_GRANTER
    _SURFACE_GRANTER = fn


def grant_actor_surface(
    db: Session,
    tenant_id: str,
    *,
    profile_id: str,
    capability: str,
    context_type: Optional[str],
    context_id: Optional[str],
) -> None:
    """Grant a PROFILE actor the portal surface for ``capability`` (one of
    "submit"/"review"/"decide") because the profile is BOUND TO A REVIEW ROLE
    (AC-06-22 - persona auto-derived from "bound to a review role → reviewer").

    PROFILE-KIND ONLY - a user-kind actor uses the STAFF surfaces gated by core
    perms and must NEVER be persona-granted; the call site is responsible for only
    passing profile actors here (this helper does not know the actor's kind).

    No granter registered (a non-EMS deployment) → NO-OP. Fully failure-isolated:
    a granter hiccup never propagates (a surface-grant failure must never break
    allocate / config save). The granter itself is expected to be idempotent
    (grant_persona is)."""
    if _SURFACE_GRANTER is None:
        return
    try:
        _SURFACE_GRANTER(db, tenant_id, profile_id, capability, context_type, context_id)
    except Exception:  # noqa: BLE001 - a grant hiccup never breaks the caller
        logger.exception(
            "surface grant failed for profile %s capability %s", profile_id, capability
        )
