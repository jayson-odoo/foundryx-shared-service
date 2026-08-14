"""Static status lookup helpers (no transition engine yet - plan 04 decision).

The ``statuses`` table is seeded per tenant; services resolve ``status_id`` ↔
``key`` through these helpers so API payloads stay string-keyed.
"""
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import Status

# scope -> [(key, label, sort_order, is_terminal)]
DEFAULT_STATUSES: Dict[str, List[Tuple[str, str, int, bool]]] = {
    "WORKSPACE": [("ACTIVE", "Active", 0, False), ("INACTIVE", "Inactive", 1, True)],
    "CHANNEL": [
        ("ACTIVE", "Active", 0, False),
        ("PENDING", "Pending", 1, False),
        ("INACTIVE", "Inactive", 2, True),
        ("ERROR", "Error", 3, False),
    ],
    "THREAD": [
        ("OPEN", "Open", 0, False),
        ("SNOOZED", "Snoozed", 1, False),
        ("CLOSED", "Closed", 2, True),
    ],
}


def ensure_statuses(db: Session, tenant_id: str) -> None:
    """Create any missing status rows for a tenant (idempotent)."""
    existing = {
        (s.scope, s.key)
        for s in db.query(Status).filter(Status.tenant_id == tenant_id).all()
    }
    for scope, items in DEFAULT_STATUSES.items():
        for key, label, order, terminal in items:
            if (scope, key) not in existing:
                db.add(
                    Status(
                        tenant_id=tenant_id,
                        scope=scope,
                        key=key,
                        label=label,
                        sort_order=order,
                        is_terminal=terminal,
                    )
                )
    db.flush()


def id_to_key_map(db: Session, tenant_id: str) -> Dict[str, str]:
    return {
        s.id: s.key for s in db.query(Status).filter(Status.tenant_id == tenant_id).all()
    }


def status_id_for(db: Session, tenant_id: str, scope: str, key: str) -> Optional[str]:
    row = (
        db.query(Status)
        .filter(Status.tenant_id == tenant_id, Status.scope == scope, Status.key == key)
        .first()
    )
    return row.id if row else None
