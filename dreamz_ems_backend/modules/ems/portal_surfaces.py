"""Portal-surface registry (sprint-4/06 slice 0b) — AC-06-23.

Mirrors the status-entity / terminology / importer registries: a module-global
list + a register fn, ``lazy_once``-seeded. A surface declares a gating
portal-permission key; the portal composes + filters visible surfaces (like the
staff ``filterMenu`` — childless/empty hidden).

Registering a surface AUTO-REGISTERS its gating key into the portal-permission
catalog (``portal_rbac.register_portal_permission``) so the catalog and the
surfaces never drift. Other modules can register surfaces at boot
(``register_engine_entities``) WITHOUT core edits — this registry is the seam.
"""
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session

from app.lazy_registry import lazy_once
from modules.ems.models import Profile


@dataclass(frozen=True)
class PortalSurface:
    """One portal app surface (a dashboard section / nav item). ``gating_permission``
    is the portal key a Profile must hold for the surface to render."""

    key: str
    label: str
    gating_permission: str
    module: str = "ems"
    sort_order: int = 0
    description: Optional[str] = None


_REGISTRY: List[PortalSurface] = []


def register_portal_surface(surface: PortalSurface) -> None:
    """Idempotent (replace-by-key). Auto-registers the gating key into the
    portal-permission catalog so a surface can never gate on an unknown key."""
    from modules.ems.portal_rbac import register_portal_permission

    register_portal_permission(
        surface.gating_permission,
        f"{surface.label} (portal)",
        surface.description or "",
    )
    global _REGISTRY
    _REGISTRY = [s for s in _REGISTRY if s.key != surface.key]
    _REGISTRY.append(surface)


def list_portal_surfaces() -> List[PortalSurface]:
    ensure_seeded()
    return sorted(_REGISTRY, key=lambda s: (s.sort_order, s.key))


def visible_surfaces(db: Session, profile: Profile) -> List[PortalSurface]:
    """The surfaces whose gating key the Profile holds (AC-06-23 — childless /
    empty hidden, mirroring ``filterMenu``). Resolves portal keys FRESH from the
    DB (like ``effective_portal_keys``)."""
    from modules.ems.portal_deps import effective_portal_keys

    keys = effective_portal_keys(db, profile)
    return [s for s in list_portal_surfaces() if s.gating_permission in keys]


def _seed() -> None:
    """Register the EMS placeholder surfaces (slices 1/2 flesh them out; the
    registry + gating must work today). My Submissions, My Reviews, Decisions."""
    register_portal_surface(
        PortalSurface(
            key="my_submissions",
            label="My Submissions",
            gating_permission="my_submissions.read",
            sort_order=10,
            description="The Profile's own submissions and their status",
        )
    )
    register_portal_surface(
        PortalSurface(
            key="my_reviews",
            label="My Reviews",
            gating_permission="my_reviews.read",
            sort_order=20,
            description="Reviews assigned to the Profile",
        )
    )
    register_portal_surface(
        PortalSurface(
            key="decisions",
            label="Decisions",
            gating_permission="decisions.read",
            sort_order=30,
            description="Decision queues for decision-maker personas",
        )
    )


ensure_seeded = lazy_once(_seed)
