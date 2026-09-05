"""Core-provided Teams capability seam (plan 28 S1, D-A8-3).

The core `teams`/`team_members` tables are the ONLY door a module gets to
teams data - never a cross-schema join. `ensure_team_capabilities()`
registers four `provider_module="core"` capabilities:

    team.resolve@1   (db, tenant_id, {"id"})              -> {id, name, isActive} | None
    teams.list@1     (db, tenant_id, {"activeOnly"?})     -> [{id, name, isActive}]
    teams.members@1  (db, tenant_id, {"id"})               -> [{userId, role, name}] | None
    teams.of_user@1  (db, tenant_id, {"userId"})           -> [{id, name}]

Every handler tenant-scopes INTERNALLY via `TeamRepository` (defense-in-depth
- the polymorphic stored-id rule: a foreign or unknown id must resolve to
`None`/`[]`, never another tenant's data). Core is implicitly always-active
(`active_modules` returns `{"core"} | <installed modules>`), so once
registered these resolve for every tenant - the registration itself must run
in EVERY process that might resolve them, hence the three call sites: the
FastAPI lifespan (`app/main.py`) and BOTH `app.module_loader` entry points
(`load_modules` for the API process, `boot_module_hooks` for a Celery worker
that never calls `load_modules`).
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.module_platform import CapabilityDef, register_capability
from app.repositories.team_repository import TeamRepository

PROVIDER_MODULE = "core"


def _team_resolve(db: Session, tenant_id: str, payload: Optional[dict]) -> Optional[dict]:
    team_id = (payload or {}).get("id")
    if not team_id:
        return None
    team = TeamRepository(db).get(team_id, tenant_id)
    if team is None:
        return None
    return {"id": team.id, "name": team.name, "isActive": team.is_active}


def _teams_list(db: Session, tenant_id: str, payload: Optional[dict]) -> List[dict]:
    active_only = bool((payload or {}).get("activeOnly"))
    # No paging concept for a picker source - a tenant's team count is small.
    rows, _ = TeamRepository(db).list(tenant_id, page=0, page_size=10_000)
    return [
        {"id": t.id, "name": t.name, "isActive": t.is_active}
        for t in rows
        if not active_only or t.is_active
    ]


def _teams_members(db: Session, tenant_id: str, payload: Optional[dict]) -> Optional[List[dict]]:
    team_id = (payload or {}).get("id")
    if not team_id:
        return None
    team = TeamRepository(db).get(team_id, tenant_id)
    if team is None:
        return None
    return [
        {
            "userId": m.user_id,
            "role": m.role,
            "name": (m.user.name or m.user.email) if m.user else "",
        }
        for m in team.members
    ]


def _teams_of_user(db: Session, tenant_id: str, payload: Optional[dict]) -> List[dict]:
    user_id = (payload or {}).get("userId")
    if not user_id:
        return []
    teams = TeamRepository(db).teams_for_user(user_id, tenant_id)
    return [{"id": t.id, "name": t.name} for t in teams]


def ensure_team_capabilities() -> None:
    """Idempotent boot-time registration (AC-TEM-13) - safe to call repeatedly
    from the API lifespan and from both module_loader entry points."""
    register_capability(
        CapabilityDef(
            key="team.resolve", version=1, provider_module=PROVIDER_MODULE, handler=_team_resolve
        )
    )
    register_capability(
        CapabilityDef(
            key="teams.list", version=1, provider_module=PROVIDER_MODULE, handler=_teams_list
        )
    )
    register_capability(
        CapabilityDef(
            key="teams.members",
            version=1,
            provider_module=PROVIDER_MODULE,
            handler=_teams_members,
        )
    )
    register_capability(
        CapabilityDef(
            key="teams.of_user",
            version=1,
            provider_module=PROVIDER_MODULE,
            handler=_teams_of_user,
        )
    )
