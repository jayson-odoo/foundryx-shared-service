"""A hub's History (owner standing rule): who, on behalf of, when, plain
action, old -> new. Names are written as text at the time of the action;
user ids are resolved inside the tenant (never an unscoped lookup)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.models.user import User

from ..models import HcHistory


@dataclass(frozen=True)
class Actor:
    """``who`` = the real person (stays the admin while impersonating);
    ``on_behalf_of`` = the user they act as, when that differs."""

    who: Optional[str]
    on_behalf_of: Optional[str] = None


SYSTEM = Actor(who="System")


def _name(db: Session, tenant_id: str, user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None
    row = db.query(User.name, User.email).filter(User.id == user_id, User.tenant_id == tenant_id).first()
    if row is None:
        return None
    return (row[0] or "").strip() or row[1]


def actor_for(db: Session, tenant_id: str, real_user_id: Optional[str], effective_user_id: Optional[str]) -> Actor:
    who = _name(db, tenant_id, real_user_id)
    behalf = _name(db, tenant_id, effective_user_id) if effective_user_id and effective_user_id != real_user_id else None
    return Actor(who=who, on_behalf_of=behalf)


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value).strip()
    return text[:1000] if text else None


def names(codes: Iterable[str], lookup: Dict[str, str]) -> str:
    """``WH-N`` -> ``North warehouse``; an empty policy reads "None"."""
    out = [lookup.get(c, c) for c in codes]
    return ", ".join(out) if out else "None"


def record(
    db: Session, tenant_id: str, hub_id: str, actor: Actor, action: str, before: Any = None, after: Any = None
) -> None:
    """Flushes, never commits: the caller's transaction owns the change."""
    db.add(
        HcHistory(
            tenant_id=tenant_id,
            hub_id=hub_id,
            at=datetime.now(timezone.utc),
            who=actor.who,
            on_behalf_of=actor.on_behalf_of,
            action=action[:200],
            from_text=_text(before),
            to_text=_text(after),
        )
    )
    db.flush()


def list_for_hub(db: Session, tenant_id: str, hub_id: str) -> List[HcHistory]:
    return (
        db.query(HcHistory)
        .filter(HcHistory.tenant_id == tenant_id, HcHistory.hub_id == hub_id)
        .order_by(HcHistory.at.desc(), HcHistory.id.desc())
        .limit(2000)
        .all()
    )


# ── what changed (plain words, old -> new) ──────────────────────────────────

_HUB_FIELDS = (
    ("name", "Name changed"),
    ("callback_url", "Receiver URL changed"),
    ("expose_price", "Show price changed"),
    ("active", "Active changed"),
)


def hub_snapshot(hub) -> Dict[str, Any]:
    return {field: getattr(hub, field) for field, _ in _HUB_FIELDS}


def record_hub_changes(db: Session, hub, actor: Actor, before: Dict[str, Any]) -> None:
    for field, action in _HUB_FIELDS:
        old, new = before.get(field), getattr(hub, field)
        if old != new:
            record(db, hub.tenant_id, hub.id, actor, action, old if old not in (None, "") else "-", new if new not in (None, "") else "-")


def customer_label(row) -> str:
    return f"{row.customer_name} ({row.customer_code})"


def customer_snapshot(row, locations: Dict[str, str], brands: Dict[str, str]) -> Dict[str, Any]:
    return {
        "name": row.customer_name,
        "locations": names(row.location_codes_json or [], locations),
        "brands": names(row.brand_codes_json or [], brands),
        "active": bool(row.active),
    }


_CUSTOMER_FIELDS = (
    ("name", "Customer name changed"),
    ("locations", "Customer locations changed"),
    ("brands", "Customer brands changed"),
    ("active", "Customer active changed"),
)


def record_customer_changes(db: Session, row, actor: Actor, before: Dict[str, Any], after: Dict[str, Any]) -> None:
    for field, action in _CUSTOMER_FIELDS:
        if before.get(field) != after.get(field):
            record(db, row.tenant_id, row.hub_id, actor, f"{action}: {row.customer_code}", before.get(field), after.get(field))
