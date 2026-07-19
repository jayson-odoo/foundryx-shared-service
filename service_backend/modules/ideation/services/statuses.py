"""Idea status set + core status-engine wiring (AC-A-10, D-A3).

The Idea rides the **core** status engine (``app/status_engine`` + ``public.statuses``)
as a **tenant-owned, non-scoped** entity. Its status set + transition graph are
seeded as **platform defaults** (``tenant_id = NULL``, ``is_system = True``) at
global install — two-tier resolution means every tenant uses these defaults until
it forks the set (``resolve_tier`` returns NULL when unforked). This mirrors how
core seeds the ``tenant`` lifecycle (``app/seed.py``).

Lifecycle (§3): ``draft → captured → triaged → linked → building → delivered →
closed`` with ``duplicate`` / ``rejected`` terminal off-ramps; initial ``draft``.
Ids are stable + readable so seeding is idempotent and transitions can reference
them (``statuses.id`` is a plain VARCHAR, not a uuid type).
"""
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.status import Status
from app.models.status_transition import StatusTransition
from app.repositories.status_repository import StatusRepository

IDEA_ENTITY = "idea"

# key -> stable status id (platform-default rows).
IDEA_STATUS_IDS: Dict[str, str] = {
    "draft": "idea-status-draft",
    "captured": "idea-status-captured",
    "triaged": "idea-status-triaged",
    "linked": "idea-status-linked",
    "building": "idea-status-building",
    "delivered": "idea-status-delivered",
    "closed": "idea-status-closed",
    "duplicate": "idea-status-duplicate",
    "rejected": "idea-status-rejected",
    "archived": "idea-status-archived",
}

# (key, label, color, sort_order, flags)
IDEA_STATUS_SEED: List[Tuple[str, str, str, int, Dict[str, bool]]] = [
    ("draft", "Draft", "gray", 1, {"is_initial": True, "is_default": True}),
    ("captured", "New", "blue", 2, {}),
    ("triaged", "Triaged", "indigo", 3, {}),
    ("linked", "Linked to BR", "violet", 4, {}),
    ("building", "Building", "amber", 5, {}),
    ("delivered", "Delivered", "green", 6, {}),
    ("closed", "Closed", "gray", 7, {"is_terminal": True, "is_archived": True}),
    ("duplicate", "Duplicate", "gray", 8, {"is_terminal": True, "is_archived": True}),
    ("rejected", "Rejected", "red", 9, {"is_terminal": True, "is_archived": True}),
    # Manual off-board archive (Slice 4) — restorable back to captured, so NOT
    # terminal. ``is_archived`` keeps it out of the active board / into the
    # archived filter.
    ("archived", "Archived", "gray", 10, {"is_archived": True}),
]

# (id, from_key, to_key, label, sort_order)
IDEA_TRANSITION_SEED: List[Tuple[str, str, str, str, int]] = [
    ("idea-tr-capture", "draft", "captured", "Capture", 1),
    ("idea-tr-draft-reject", "draft", "rejected", "Reject", 2),
    ("idea-tr-triage", "captured", "triaged", "Triage", 3),
    ("idea-tr-mark-dup", "captured", "duplicate", "Mark duplicate", 4),
    ("idea-tr-cap-reject", "captured", "rejected", "Reject", 5),
    ("idea-tr-link", "triaged", "linked", "Link to BR", 6),
    ("idea-tr-tri-reject", "triaged", "rejected", "Reject", 7),
    ("idea-tr-build", "linked", "building", "Start building", 8),
    ("idea-tr-deliver", "building", "delivered", "Deliver", 9),
    ("idea-tr-close", "delivered", "closed", "Close", 10),
    # Manual archive from any on-board state, + restore (Slice 4). Archive takes
    # a live idea off the board; restore returns it to captured for re-triage.
    ("idea-tr-arch-cap", "captured", "archived", "Archive", 11),
    ("idea-tr-arch-tri", "triaged", "archived", "Archive", 12),
    ("idea-tr-arch-lnk", "linked", "archived", "Archive", 13),
    ("idea-tr-arch-bld", "building", "archived", "Archive", 14),
    ("idea-tr-arch-dlv", "delivered", "archived", "Archive", 15),
    ("idea-tr-restore", "archived", "captured", "Restore", 16),
]


def seed_idea_statuses(db: Session) -> None:
    """Idempotent global seed of the Idea platform-default status set + graph.

    Statuses + transitions carry ``tenant_id = NULL`` (the platform tier); trait
    flags are re-asserted every run so a create_all DB converges."""
    existing = {
        s.id: s
        for s in db.query(Status)
        .filter(Status.entity_type == IDEA_ENTITY, Status.tenant_id.is_(None))
        .all()
    }
    for key, label, color, sort_order, flags in IDEA_STATUS_SEED:
        status_id = IDEA_STATUS_IDS[key]
        row = existing.get(status_id)
        if row is None:
            row = Status(
                id=status_id,
                entity_type=IDEA_ENTITY,
                key=key,
                category=key.upper(),  # cosmetic mirror — never branched on
                label=label,
                color=color,
                sort_order=sort_order,
                is_system=True,
                tenant_id=None,
            )
            db.add(row)
        # Trait flags are the machine semantics — always converge them.
        for flag, value in flags.items():
            setattr(row, flag, value)
    db.flush()

    have_edges = {
        t.id
        for t in db.query(StatusTransition)
        .filter(StatusTransition.entity_type == IDEA_ENTITY)
        .all()
    }
    for tr_id, from_key, to_key, label, sort_order in IDEA_TRANSITION_SEED:
        if tr_id in have_edges:
            continue
        db.add(
            StatusTransition(
                id=tr_id,
                entity_type=IDEA_ENTITY,
                tenant_id=None,
                from_status_id=IDEA_STATUS_IDS[from_key],
                to_status_id=IDEA_STATUS_IDS[to_key],
                label=label,
                sort_order=sort_order,
            )
        )
    db.flush()


def idea_status_id(db: Session, key: str, tenant_id: Optional[str] = None) -> Optional[str]:
    """Resolve the Idea ``status_id`` for a lifecycle ``key`` in the tenant's
    resolved tier (platform default unless the tenant has forked the set)."""
    tier = StatusRepository(db).resolve_tier(IDEA_ENTITY, tenant_id)
    row = (
        db.query(Status)
        .filter(
            Status.entity_type == IDEA_ENTITY,
            Status.key == key,
            Status.tenant_id.is_(None) if tier is None else Status.tenant_id == tier,
        )
        .first()
    )
    return row.id if row else None


def initial_idea_status_id(db: Session, tenant_id: Optional[str] = None) -> Optional[str]:
    """The ``is_initial`` Idea status id for a tenant (where new drafts start)."""
    tier = StatusRepository(db).resolve_tier(IDEA_ENTITY, tenant_id)
    row = (
        db.query(Status)
        .filter(
            Status.entity_type == IDEA_ENTITY,
            Status.is_initial.is_(True),
            Status.tenant_id.is_(None) if tier is None else Status.tenant_id == tier,
        )
        .first()
    )
    return row.id if row else None


# ---- status-engine record access (register_status_entity, AC-A-10) ----


def idea_count_records(db: Session, status_id: str, tenant_id: Optional[str]) -> int:
    from ..models import Idea

    q = db.query(Idea).filter(Idea.status_id == status_id)
    if tenant_id is not None:
        q = q.filter(Idea.tenant_id == tenant_id)
    return q.count()


def idea_migrate_records(
    db: Session, from_status_id: str, to_status_id: str, tenant_id: Optional[str]
) -> int:
    from ..models import Idea

    q = db.query(Idea).filter(Idea.status_id == from_status_id)
    if tenant_id is not None:
        q = q.filter(Idea.tenant_id == tenant_id)
    count = q.update({Idea.status_id: to_status_id}, synchronize_session=False)
    db.flush()
    return count
