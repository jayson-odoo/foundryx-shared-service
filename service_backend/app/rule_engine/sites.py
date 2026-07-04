"""Rule-site registry (sprint-2/02 D12) — rules are born where they're used;
this answers "what rules exist + where". Each consumer registers a lister
returning observability rows; ``GET /rules`` aggregates, tenant-scoped via
the caller passed to every lister.
"""
from typing import Any, Callable, Dict, List

from sqlalchemy.orm import Session

from app.lazy_registry import lazy_once

# lister(db, current_user) -> [{site, siteLabel, context, summary, editUrl, updatedAt}]
Lister = Callable[[Session, Any], List[Dict[str, Any]]]

_SITES: Dict[str, Lister] = {}


def register_rule_site(key: str, lister: Lister) -> None:
    """Idempotent — consumers re-register on every bootstrap."""
    _SITES[key] = lister


def list_rules(db: Session, current_user: Any) -> List[Dict[str, Any]]:
    _ensure_core()
    rows: List[Dict[str, Any]] = []
    for lister in _SITES.values():
        rows.extend(lister(db, current_user))
    return rows


def _register_core() -> None:
    # The status engine is the first consumer (edge conditions).
    from app.status_engine import rule_site  # noqa: F401 — registers on import


_ensure_core = lazy_once(_register_core)
