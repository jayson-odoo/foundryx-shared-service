"""Status-transition repository (sprint-2/01) - pure SQLAlchemy, two-tier.

Edges live in the same tier as their statuses: the tenant's fork when one
exists for the entity_type, else the platform defaults (``tenant_id NULL``).
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.status_transition import StatusTransition


class StatusTransitionRepository:
    def __init__(self, db: Session):
        self.db = db

    def _tier_filter(self, q, tier: Optional[str]):
        return q.filter(
            StatusTransition.tenant_id.is_(None)
            if tier is None
            else StatusTransition.tenant_id == tier
        )

    def list_for_entity(self, entity_type: str, tier: Optional[str]) -> List[StatusTransition]:
        q = self.db.query(StatusTransition).filter(StatusTransition.entity_type == entity_type)
        q = self._tier_filter(q, tier)
        return q.order_by(StatusTransition.sort_order.asc(), StatusTransition.created_at.asc()).all()

    def list_for_statuses(self, status_ids: List[str], tier: Optional[str]) -> List[StatusTransition]:
        """Edges whose SOURCE lives in the given status set - a scoped graph's
        edge list (sprint-3/01 D4; edges carry no scope column, their
        endpoints do)."""
        if not status_ids:
            return []
        q = self.db.query(StatusTransition).filter(
            StatusTransition.from_status_id.in_(status_ids)
        )
        q = self._tier_filter(q, tier)
        return q.order_by(StatusTransition.sort_order.asc(), StatusTransition.created_at.asc()).all()

    def outgoing(self, from_status_id: str, tier: Optional[str]) -> List[StatusTransition]:
        q = self.db.query(StatusTransition).filter(
            StatusTransition.from_status_id == from_status_id
        )
        q = self._tier_filter(q, tier)
        return q.order_by(StatusTransition.sort_order.asc()).all()

    def find_edge(
        self, from_status_id: str, to_status_id: str, tier: Optional[str]
    ) -> Optional[StatusTransition]:
        q = self.db.query(StatusTransition).filter(
            StatusTransition.from_status_id == from_status_id,
            StatusTransition.to_status_id == to_status_id,
        )
        return self._tier_filter(q, tier).first()

    def get_by_id(self, transition_id: str) -> Optional[StatusTransition]:
        return (
            self.db.query(StatusTransition)
            .filter(StatusTransition.id == transition_id)
            .first()
        )

    def references_status(self, status_id: str) -> bool:
        """Any edge touching this status (delete validation, D8)."""
        return (
            self.db.query(StatusTransition.id)
            .filter(
                (StatusTransition.from_status_id == status_id)
                | (StatusTransition.to_status_id == status_id)
            )
            .first()
            is not None
        )

    def delete_for_status(self, status_id: str) -> int:
        """Drop every edge touching a status (used by hard status delete)."""
        count = (
            self.db.query(StatusTransition)
            .filter(
                (StatusTransition.from_status_id == status_id)
                | (StatusTransition.to_status_id == status_id)
            )
            .delete(synchronize_session=False)
        )
        self.db.flush()
        return count

    # ---- writes ----

    def add(self, transition: StatusTransition) -> StatusTransition:
        self.db.add(transition)
        self.db.flush()
        return transition

    def delete(self, transition: StatusTransition) -> None:
        self.db.delete(transition)
        self.db.flush()
