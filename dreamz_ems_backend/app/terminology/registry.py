"""TermDef registry (sprint-3/08 D2) — code-side, mirrors rule/status engines.

``register_term(TermDef)`` declares an entity's default labels. Core registers
its relabelable entities at ``lazy_once`` (``core_terms.py``); a module
registers its own at install — same contract as the permissions.csv sync. The
``key`` aligns with existing registry entity keys (``form``, ``workflow``, …)
so ONE vocabulary spans status / trigger / terminology (D2).

``module`` tag (D2 / F9 plan-10): ``'core'`` is always visible; a module's
terms are filtered by ``active_modules`` at consumption once F9 lands.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.lazy_registry import lazy_once


@dataclass(frozen=True)
class TermDef:
    """One relabelable entity. ``key`` is the stable answer key; the singular/
    plural are the CODE DEFAULTS (a tenant override row supersedes them)."""

    key: str
    default_singular: str
    default_plural: str
    module: str = "core"
    group: Optional[str] = None
    description: Optional[str] = None


_REGISTRY: Dict[str, TermDef] = {}


def register_term(term: TermDef) -> None:
    """Idempotent — re-registration on every bootstrap simply overwrites."""
    _REGISTRY[term.key] = term


def get_term(key: str) -> Optional[TermDef]:
    ensure_core()
    return _REGISTRY.get(key)


def list_terms() -> List[TermDef]:
    """All registered TermDefs, group then key ordered (drives the catalog)."""
    ensure_core()
    return sorted(
        _REGISTRY.values(), key=lambda t: (t.group or "", t.key)
    )


def is_registered(key: str) -> bool:
    ensure_core()
    return key in _REGISTRY


def defaults_map() -> Dict[str, Dict[str, str]]:
    """``{key: {singular, plural}}`` of code defaults — the base the merged
    map overlays tenant overrides onto (D6)."""
    ensure_core()
    return {
        t.key: {"singular": t.default_singular, "plural": t.default_plural}
        for t in _REGISTRY.values()
    }


# Call before any registry read — core registers exactly once.
def _register_core() -> None:
    from app.terminology.core_terms import register_core_terms

    register_core_terms()


ensure_core = lazy_once(_register_core)
