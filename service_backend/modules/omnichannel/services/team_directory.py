"""Teams gateway (plan 28 S2, D-A8-3) - the module's ONLY door to core teams.

Never a cross-schema join: every read goes through the core-provided
capability family (`team.resolve@1`, `teams.list@1`, `teams.members@1`),
each of which tenant-scopes internally. When the capability is NOT
registered in this process (`resolve_capability` -> None - a boot path that
skipped `ensure_team_capabilities()`, AC-TEM-15) every method here degrades
to its empty/None result - never raises, never 500s. A foreign, unknown or
deleted team id always resolves to `None`/`[]`, never another tenant's data
(the polymorphic stored-id house rule).
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.module_platform import SoftRef, resolve_capability, resolve_soft_ref

TEAM_VERSION = 1


def _ref(team_id: str) -> SoftRef:
    return SoftRef("core", "team", team_id)


def resolve(db: Session, tenant_id: str, team_id: Optional[str]) -> Optional[dict]:
    """`{id, name, isActive}` or `None` (absent id / unknown / foreign-tenant /
    deleted / capability not registered)."""
    if not team_id:
        return None
    return resolve_soft_ref(db, tenant_id, _ref(team_id), TEAM_VERSION)


def resolve_active(db: Session, tenant_id: str, team_id: Optional[str]) -> Optional[dict]:
    """Same as `resolve`, but ALSO `None` when the team is inactive
    (AC-TEM-07: an inactive team can no longer be an assignment target)."""
    team = resolve(db, tenant_id, team_id)
    if team is None or not team.get("isActive"):
        return None
    return team


def validate_assignable(db: Session, tenant_id: str, team_id: Optional[str]) -> bool:
    """Save-time gate (AC-TEM-19): `None` is always valid (means "leave/clear
    the team"); a non-None id must resolve to an ACTIVE team of this tenant."""
    if team_id is None:
        return True
    return resolve_active(db, tenant_id, team_id) is not None


def list_active(db: Session, tenant_id: str) -> List[dict]:
    """`[{id, name, isActive}]`, active-only - the picker source. `[]` when
    the capability is not registered."""
    handler = resolve_capability(db, tenant_id, "teams.list", TEAM_VERSION)
    if handler is None:
        return []
    return handler(db, tenant_id, {"activeOnly": True}) or []


def members(db: Session, tenant_id: str, team_id: Optional[str]) -> Optional[List[dict]]:
    """`[{userId, role, name}]` or `None` (absent id / unknown / foreign /
    capability not registered)."""
    if not team_id:
        return None
    handler = resolve_capability(db, tenant_id, "teams.members", TEAM_VERSION)
    if handler is None:
        return None
    return handler(db, tenant_id, {"id": team_id})


def names(db: Session, tenant_id: str, team_ids: List[Optional[str]]) -> Dict[str, Optional[str]]:
    """Batched id -> name (or `None` if unresolved), ONE `teams.list@1` call
    per page render (AC-TEM-29) - never N `resolve` calls. A stale/deleted/
    foreign team id maps to `None`, never another tenant's team name."""
    ids = {t for t in team_ids if t}
    if not ids:
        return {}
    handler = resolve_capability(db, tenant_id, "teams.list", TEAM_VERSION)
    if handler is None:
        return {tid: None for tid in ids}
    rows = handler(db, tenant_id, {}) or []
    by_id = {r["id"]: r["name"] for r in rows}
    return {tid: by_id.get(tid) for tid in ids}


def count_conversations_for_team(db: Session, tenant_id: str, team_id: str) -> int:
    """Reference-guard checker (AC-TEM-16) - registered as
    `register_reference_guard("team", "conversations", ...)` from
    `bootstrap.register_engine_entities`. Tenant-scoped count of contacts
    currently holding `assigned_team_id == team_id`; a broken/absent module
    boot never wedges the core delete decision (the registry itself swallows
    a raising checker, but this one has no reason to raise)."""
    from ..models import Contact

    return (
        db.query(Contact.id)
        .filter(Contact.tenant_id == tenant_id, Contact.assigned_team_id == team_id)
        .count()
    )
