"""Reference-guard registry (sprint-4/08 grill Q9b) — the INVERSE of soft-refs.

Soft-refs let a module point AT core data; reference-guards let core ask "is
this core row referenced by anybody?" WITHOUT core knowing which modules exist.
Modules register a usage checker for an entity type; core fans out before a
destructive op (e.g. deleting a product) and blocks (409) if any checker reports
a positive count. A module that isn't installed simply has no checker registered,
so it can't block.

Checker contract: ``checker(db, tenant_id, entity_id) -> int`` (count of
references; tenant-scopes internally). Mirrors the capability/subscriber style.
"""
from collections import defaultdict
from typing import Callable, List

# entity_type -> [(label, checker)]
ReferenceChecker = Callable[[object, str, str], int]
_GUARDS: dict[str, List[tuple[str, ReferenceChecker]]] = defaultdict(list)


def register_reference_guard(entity_type: str, label: str, checker: ReferenceChecker) -> None:
    """Idempotent per (entity_type, label) — re-registration at boot replaces."""
    existing = _GUARDS[entity_type]
    for i, (lbl, _) in enumerate(existing):
        if lbl == label:
            existing[i] = (label, checker)
            return
    existing.append((label, checker))


def reference_counts(db, tenant_id: str, entity_type: str, entity_id: str) -> dict[str, int]:
    """Per-source non-zero reference counts for one row (e.g. {'quotations': 3})."""
    out: dict[str, int] = {}
    for label, checker in _GUARDS.get(entity_type, []):
        try:
            n = int(checker(db, tenant_id, entity_id))
        except Exception:  # a broken guard must never wedge a delete decision
            n = 0
        if n > 0:
            out[label] = n
    return out


def is_referenced(db, tenant_id: str, entity_type: str, entity_id: str) -> bool:
    return bool(reference_counts(db, tenant_id, entity_type, entity_id))
