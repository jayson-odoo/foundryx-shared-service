"""Profile-portal surface routes (sprint-4/06 slice 0b) — ``/portal/*``.

Profile-authed (``current_profile``). ``GET /portal/surfaces`` composes the
portal nav/dashboard: the surfaces whose gating key the Profile holds (AC-06-23),
each with the Profile's scoped contexts (memberships whose persona grants that
surface's gating key) so the dashboard scopes data per AC-06-24.

Wired as a ``"public": true`` manifest router so the loader does NOT inject the
staff ``require_module`` gate — these are Profile-authed, not staff-authed.
"""
from typing import Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.terminology import TermLabels
from app.services.terminology_service import TerminologyService
from modules.ems.models import Persona, Profile
from modules.ems.persona_repository import PersonaRepository
from modules.ems.persona_schemas import (
    PortalSurfaceContextOut,
    PortalSurfaceOut,
)
from modules.ems.portal_deps import current_profile
from modules.ems.portal_surfaces import visible_surfaces

router = APIRouter()


@router.get("/terminology", response_model=Dict[str, TermLabels])
def get_portal_terminology(
    profile: Profile = Depends(current_profile),
    db: Session = Depends(get_db),
):
    """Profile-authed mirror of staff ``GET /terminology`` (Cluster E portal fix).

    The portal review surfaces (My Submissions / My Reviews / Decisions) need the
    tenant's terminology labels, but the staff ``GET /terminology`` is gated by
    ``get_current_user`` and rejects a Profile JWT with 401 — which the portal
    api-client treats as a signed-out session. This returns the SAME merged map
    (defaults ⊕ tenant overrides), tenant scoped from the Profile's JWT (never
    client input), so the ``(portal)`` tree never touches the staff client.
    """
    return TerminologyService(db).merged_map(profile.tenant_id)


@router.get("/surfaces", response_model=List[PortalSurfaceOut])
def list_surfaces(
    profile: Profile = Depends(current_profile),
    db: Session = Depends(get_db),
) -> List[PortalSurfaceOut]:
    """The Profile's visible portal surfaces + per-surface scoped contexts.

    A surface's contexts = the memberships whose persona grants that surface's
    gating key. Resolved tenant-scoped (AC-06-57), FRESH from the DB.
    """
    repo = PersonaRepository(db)
    memberships = repo.list_memberships_for_profile(profile.tenant_id, profile.id)
    persona_by_id = {
        p.id: p
        for p in db.query(Persona).filter(Persona.tenant_id == profile.tenant_id).all()
    }
    # Resolve project-scope context labels (AC-06-25 — real event names) in ONE
    # batched, tenant-scoped query so the filter pill reads "Annual Summit" not
    # "Event {id-prefix}". EMS reads its own projects table here (no core edit).
    from modules.ems.models import Project

    project_scope_ids = {
        m.scope_id
        for m in memberships
        if m.scope_type == "project" and m.scope_id
    }
    project_titles: dict[str, str] = {}
    if project_scope_ids:
        project_titles = {
            pid: title
            for pid, title in db.query(Project.id, Project.title)
            .filter(
                Project.tenant_id == profile.tenant_id,
                Project.id.in_(project_scope_ids),
            )
            .all()
        }

    def _context_label(m) -> str | None:
        if m.scope_type == "project" and m.scope_id:
            return project_titles.get(m.scope_id)
        return None
    # persona_id -> set of portal keys it grants (one query, grouped in-Python).
    persona_keys: dict[str, set[str]] = {}
    for persona in persona_by_id.values():
        persona_keys[persona.id] = {
            pp.permission_key for pp in repo.list_permissions(profile.tenant_id, persona.id)
        }

    out: List[PortalSurfaceOut] = []
    for surface in visible_surfaces(db, profile):
        contexts = [
            PortalSurfaceContextOut(
                scopeType=m.scope_type,
                scopeId=m.scope_id,
                label=_context_label(m),
            )
            for m in memberships
            if surface.gating_permission in persona_keys.get(m.persona_id, set())
        ]
        out.append(
            PortalSurfaceOut(
                key=surface.key,
                label=surface.label,
                gatingPermission=surface.gating_permission,
                module=surface.module,
                sortOrder=surface.sort_order,
                description=surface.description,
                contexts=contexts,
            )
        )
    return out
