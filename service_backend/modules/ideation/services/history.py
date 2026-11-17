"""History of a feedback item for its operator History tab (lane
FEEDBACK-SUBSCRIBE, crew pass c4572865; owner standing rule: every tracked
action on a record shows in its History - who, on behalf of, when, plain
action, old -> new).

Two sources, one read:
- status moves: the existing ``idea_activity`` rows (written by the event-bus
  subscriber for every move; ``actor_name`` recorded from now on);
- everything else: ``idea_history`` rows written here by the action itself
  (field edits, follower added / removed, share link created / stopped).

Values are display text (names, labels), never ids. Every read and write is
tenant-scoped. Writes flush; the caller owns the transaction.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Idea, IdeaActivity, IdeaHistory

ACTION_STATUS = "Status changed"
ACTION_FOLLOWER_ADDED = "Follower added"
ACTION_FOLLOWER_REMOVED = "Follower removed"
ACTION_SHARE_CREATED = "Share link created"
ACTION_SHARE_STOPPED = "Share link stopped"


class HistoryNotFound(Exception):
    pass


@dataclass(frozen=True)
class HistoryActor:
    """Who did it, and on whose behalf (staff impersonating another user)."""

    name: Optional[str] = None
    on_behalf_of: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def staff_actor(real_name: Optional[str], effective_name: Optional[str]) -> HistoryActor:
    """The real staff user acts; while impersonating, on behalf of the target."""
    if real_name and effective_name and real_name != effective_name:
        return HistoryActor(name=real_name, on_behalf_of=effective_name)
    return HistoryActor(name=effective_name or real_name)


def record(
    db: Session,
    tenant_id: str,
    idea_id: str,
    action: str,
    actor: HistoryActor,
    *,
    from_value: Optional[str] = None,
    to_value: Optional[str] = None,
) -> None:
    db.add(
        IdeaHistory(
            tenant_id=tenant_id,
            idea_id=idea_id,
            action=action,
            from_value=from_value,
            to_value=to_value,
            actor_name=actor.name,
            on_behalf_of_name=actor.on_behalf_of,
            created_at=_now(),
        )
    )
    db.flush()


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = "; ".join(str(v) for v in value if v)
    value = str(value).strip()
    return value or None


def record_edits(
    db: Session,
    tenant_id: str,
    idea_id: str,
    before: Dict[str, Any],
    after: Dict[str, Any],
    labels: Dict[str, str],
    actor: HistoryActor,
) -> None:
    """One "<Field> edited" row per field whose displayed value changed."""
    for key, label in labels.items():
        old, new = _text(before.get(key)), _text(after.get(key))
        if old != new:
            record(db, tenant_id, idea_id, f"{label} edited", actor, from_value=old, to_value=new)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    aware = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return aware.isoformat().replace("+00:00", "Z")


def list_history(db: Session, tenant_id: str, idea_id: str) -> List[Dict[str, Any]]:
    """The item's History, newest first. 404 (``HistoryNotFound``) when the idea
    is not in the tenant."""
    exists = db.query(Idea.id).filter(Idea.id == idea_id, Idea.tenant_id == tenant_id).first()
    if exists is None:
        raise HistoryNotFound()
    rows: List[Dict[str, Any]] = []
    for a in db.query(IdeaActivity).filter(
        IdeaActivity.tenant_id == tenant_id,
        IdeaActivity.idea_id == idea_id,
        IdeaActivity.kind == "status_changed",
    ):
        rows.append(
            {
                "id": f"s-{a.id}",
                "at": a.created_at,
                "who": a.actor_name,
                "onBehalfOf": None,
                "action": ACTION_STATUS,
                "from": a.from_label,
                "to": a.to_label,
            }
        )
    for h in db.query(IdeaHistory).filter(IdeaHistory.tenant_id == tenant_id, IdeaHistory.idea_id == idea_id):
        rows.append(
            {
                "id": f"h-{h.id}",
                "at": h.created_at,
                "who": h.actor_name,
                "onBehalfOf": h.on_behalf_of_name,
                "action": h.action,
                "from": h.from_value,
                "to": h.to_value,
            }
        )

    def _key(r: Dict[str, Any]):
        at = r["at"]
        if at is not None and at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        return at or datetime.min.replace(tzinfo=timezone.utc)

    rows.sort(key=_key, reverse=True)
    for r in rows:
        r["at"] = _iso(r["at"])
    return rows
