"""Portal-permission catalog (sprint-4/06 slice 0b) — a code-side registry.

A SEPARATE permission catalog for EMS ``Profile`` actors (AC-06-21), fully
disjoint from the core ``permissions`` table. Heed the templates.read lesson:
these keys are NEVER synced into core ``permissions`` (``sync_permissions`` is
delete-by-module on the GLOBAL ``permissions.key`` — a duplicate would collide
at bootstrap). They live ONLY in this in-memory dict + are granted to personas
via ``persona_permissions`` rows.

Mirrors the rule/status/terminology code-side registry shape: a module-global
dict + a register fn, ``lazy_once``-seeded. A portal SURFACE auto-registers its
gating key here (``portal_surfaces.register_portal_surface``) so the catalog and
the surfaces never drift.
"""
from dataclasses import dataclass
from typing import Dict, List

from app.lazy_registry import lazy_once


@dataclass(frozen=True)
class PortalPermission:
    """One portal-permission key. ``key`` is a flat ``<resource>.<action>``
    string in the portal namespace (e.g. ``my_submissions.read``)."""

    key: str
    label: str
    description: str = ""


_REGISTRY: Dict[str, PortalPermission] = {}


def register_portal_permission(key: str, label: str, description: str = "") -> None:
    """Idempotent — re-registration on every boot simply overwrites. A surface's
    gating key registers through here too."""
    _REGISTRY[key] = PortalPermission(key=key, label=label, description=description)


def list_portal_permissions() -> List[PortalPermission]:
    """The catalog for the staff persona-grant UI (AC-06-26), key-ordered."""
    ensure_seeded()
    return sorted(_REGISTRY.values(), key=lambda p: p.key)


def is_portal_permission(key: str) -> bool:
    ensure_seeded()
    return key in _REGISTRY


def _seed() -> None:
    """Seed the EMS portal keys. Surfaces also register their gating keys (see
    ``portal_surfaces``); importing the surfaces module here guarantees the
    catalog is fully populated whenever it is first read."""
    # Foundational portal keys (the personas seeded in install_tenant grant
    # these). The surface registry layers its gating keys on top.
    register_portal_permission(
        "my_submissions.read", "View my submissions", "See the Profile's own submissions in the portal"
    )
    register_portal_permission(
        "forms.submit", "Submit forms", "Create a submission where the Profile may submit"
    )
    register_portal_permission(
        "my_reviews.read", "View my reviews", "See the Profile's assigned reviews"
    )
    register_portal_permission(
        "decisions.read", "View decisions", "See decision queues for decision-maker personas"
    )
    # Importing the surfaces module registers each surface's gating key into this
    # catalog (the surfaces' keys are a superset of / overlap the above).
    import modules.ems.portal_surfaces  # noqa: F401


ensure_seeded = lazy_once(_seed)
