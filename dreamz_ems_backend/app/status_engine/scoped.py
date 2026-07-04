"""Scoped status machines (sprint-3/01 D4) — one graph per owning record.

For entities registered ``scoped`` (first adopter: ``form_submission``), the
status set is NOT resolved two-tier: creating the owning record (a form)
**materializes** a seed graph into ``(tenant_id, scope_id)`` rows, tenant-owned
from birth and directly editable. Deleting the owner deletes its graph.

The seed stays minimal by design (plan D4): tenants add review states per
scope themselves. Flag semantics, never labels — ``is_active`` on a scoped
status means *the respondent may still edit answers*.
"""
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.status import Status
from app.models.status_transition import StatusTransition


@dataclass(frozen=True)
class ScopeSeedStatus:
    """One status in a scope's seed set."""

    key: str
    label: str
    color: str = "gray"
    sort_order: int = 0
    flags: Dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class ScopeSeedEdge:
    """One edge in a scope's seed graph (keys reference seed statuses)."""

    from_key: str
    to_key: str
    label: str
    sort_order: int = 0
    # Derived status (sprint-4/03) — a scoped graph can seed an auto-edge
    # (e.g. participant Checked-in). Auto requires conditions; both ride along.
    trigger_mode: str = "manual"
    conditions: Optional[Dict] = None


def materialize_scope(
    db: Session,
    entity_type: str,
    tenant_id: str,
    scope_id: str,
    statuses: List[ScopeSeedStatus],
    edges: List[ScopeSeedEdge],
) -> Dict[str, Status]:
    """Create the seed graph for a new scope. Flushes, does NOT commit — the
    caller's unit of work (e.g. form creation) owns the transaction.

    Idempotent per scope: refuses to double-seed (caller bug surface)."""
    existing = (
        db.query(Status.id)
        .filter(
            Status.entity_type == entity_type,
            Status.tenant_id == tenant_id,
            Status.scope_id == scope_id,
        )
        .first()
    )
    if existing is not None:
        raise ValueError(f"Scope '{scope_id}' already has statuses for '{entity_type}'.")

    by_key: Dict[str, Status] = {}
    for seed in statuses:
        row = Status(
            id=str(uuid.uuid4()),
            entity_type=entity_type,
            key=seed.key,
            category=seed.key.upper(),  # cosmetic mirror — never branched on
            label=seed.label,
            color=seed.color,
            sort_order=seed.sort_order,
            is_system=False,
            tenant_id=tenant_id,
            scope_id=scope_id,
            **{flag: bool(value) for flag, value in seed.flags.items()},
        )
        db.add(row)
        by_key[seed.key] = row
    db.flush()

    for seed in edges:
        db.add(
            StatusTransition(
                id=str(uuid.uuid4()),
                entity_type=entity_type,
                tenant_id=tenant_id,
                from_status_id=by_key[seed.from_key].id,
                to_status_id=by_key[seed.to_key].id,
                label=seed.label,
                sort_order=seed.sort_order,
                trigger_mode=seed.trigger_mode,
                conditions_json=seed.conditions,
            )
        )
    db.flush()
    return by_key


def copy_scope(
    db: Session,
    entity_type: str,
    tenant_id: str,
    from_scope_id: str,
    to_scope_id: str,
) -> Dict[str, str]:
    """Materialize a new scope by COPYING another scope's graph (sprint-3/11 D4).

    EMS create-from-template: a Project's eligibility graph is a per-project
    editable copy of the TEMPLATE's graph (Option A — not live-inherit). Copies
    statuses (new ids, preserving keys/labels/colors/flags/order) + the edges
    between them. Flushes, no commit — rides the Project-creation txn. Refuses to
    double-seed the target. Returns ``{old_status_id: new_status_id}``."""
    if scope_status_ids(db, entity_type, tenant_id, to_scope_id):
        raise ValueError(f"Scope '{to_scope_id}' already has '{entity_type}' statuses.")
    src = (
        db.query(Status)
        .filter(
            Status.entity_type == entity_type,
            Status.tenant_id == tenant_id,
            Status.scope_id == from_scope_id,
        )
        .all()
    )
    if not src:
        raise ValueError(f"Source scope '{from_scope_id}' has no '{entity_type}' graph.")
    id_map: Dict[str, str] = {}
    flag_cols = (
        "is_initial",
        "is_terminal",
        "is_active",
        "blocks_access",
        "is_archived",
        "is_default",
    )
    for s in src:
        new_id = str(uuid.uuid4())
        id_map[s.id] = new_id
        db.add(
            Status(
                id=new_id,
                entity_type=entity_type,
                key=s.key,
                category=s.category,
                label=s.label,
                color=s.color,
                sort_order=s.sort_order,
                is_system=s.is_system,
                tenant_id=tenant_id,
                scope_id=to_scope_id,
                **{f: getattr(s, f) for f in flag_cols},
            )
        )
    db.flush()
    src_ids = list(id_map.keys())
    for edge in (
        db.query(StatusTransition)
        .filter(
            StatusTransition.entity_type == entity_type,
            StatusTransition.from_status_id.in_(src_ids),
            StatusTransition.to_status_id.in_(src_ids),
        )
        .all()
    ):
        db.add(
            StatusTransition(
                id=str(uuid.uuid4()),
                entity_type=entity_type,
                tenant_id=tenant_id,
                from_status_id=id_map[edge.from_status_id],
                to_status_id=id_map[edge.to_status_id],
                label=edge.label,
                sort_order=edge.sort_order,
                # Carry conditions + trigger mode so a copied graph keeps its
                # auto-edges (sprint-4/03 — the flag-copy-list lesson).
                conditions_json=edge.conditions_json,
                trigger_mode=edge.trigger_mode,
            )
        )
    db.flush()
    return id_map


def scope_status_ids(
    db: Session, entity_type: str, tenant_id: str, scope_id: str
) -> List[str]:
    rows = (
        db.query(Status.id)
        .filter(
            Status.entity_type == entity_type,
            Status.tenant_id == tenant_id,
            Status.scope_id == scope_id,
        )
        .all()
    )
    return [r[0] for r in rows]


def delete_scope(
    db: Session, entity_type: str, tenant_id: str, scope_id: str
) -> Tuple[int, int]:
    """Drop a scope's whole graph (owner deleted). Flushes, no commit.
    Returns (statuses_deleted, edges_deleted). Caller deletes the records
    first — block-delete-if-referenced does not apply to a dying scope."""
    ids = scope_status_ids(db, entity_type, tenant_id, scope_id)
    if not ids:
        return (0, 0)
    edge_count = (
        db.query(StatusTransition)
        .filter(
            (StatusTransition.from_status_id.in_(ids))
            | (StatusTransition.to_status_id.in_(ids))
        )
        .delete(synchronize_session=False)
    )
    status_count = (
        db.query(Status)
        .filter(Status.id.in_(ids))
        .delete(synchronize_session=False)
    )
    db.flush()
    return (status_count, edge_count)


def get_scope_status(
    db: Session, entity_type: str, tenant_id: str, scope_id: str, status_id: str
) -> Optional[Status]:
    """Tenant- AND scope-scoped status resolution (polymorphic target_id
    rule — never resolve a stored id unscoped)."""
    return (
        db.query(Status)
        .filter(
            Status.id == status_id,
            Status.entity_type == entity_type,
            Status.tenant_id == tenant_id,
            Status.scope_id == scope_id,
        )
        .first()
    )


def initial_scope_status(
    db: Session, entity_type: str, tenant_id: str, scope_id: str
) -> Optional[Status]:
    """The scope's ``is_initial`` row — where new records start."""
    return (
        db.query(Status)
        .filter(
            Status.entity_type == entity_type,
            Status.tenant_id == tenant_id,
            Status.scope_id == scope_id,
            Status.is_initial.is_(True),
        )
        .order_by(Status.sort_order.asc())
        .first()
    )
