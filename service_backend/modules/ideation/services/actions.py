"""Idea write actions (Slice 4) — vote / reorder / status transition / delete.

These back the FE prototype's ``vote`` / ``reorderPriority`` / ``setStatus`` /
``remove`` service methods. Status moves are server-authoritative: every change
rides the CORE status engine (``status_machine.transition``) so an illegal move
is refused at the boundary (D-A3). No LLM anywhere — deterministic paths only.
"""
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.models.user import User
from app.services import status_machine
from app.services.status_machine import (
    TransitionConditionsNotMet,
    TransitionForbidden,
    TransitionNotAllowed,
)

from ..models import Idea, IdeaVote
from ..schemas import IdeaOut
from .ideas import IdeaReadService
from .statuses import IDEA_ENTITY, idea_status_id, initial_idea_status_id


class IdeaActionService:
    def __init__(self, db: Session):
        self.db = db
        self._reader = IdeaReadService(db)

    def _idea_or_404(self, tenant_id: str, idea_id: str) -> Idea:
        idea = (
            self.db.query(Idea)
            .filter(Idea.id == idea_id, Idea.tenant_id == tenant_id)
            .first()
        )
        if idea is None:
            raise HTTPException(404, "Idea not found.")
        return idea

    def _product_or_422(self, tenant_id: str, product_id: str) -> Product:
        product = (
            self.db.query(Product)
            .filter(Product.id == product_id, Product.tenant_id == tenant_id)
            .first()
        )
        if product is None:
            raise HTTPException(422, "product_id does not resolve to a product for this workspace.")
        return product

    def create_operator(
        self,
        tenant_id: str,
        *,
        product_id: str,
        problem: str,
        proposed_solution: Optional[str] = None,
        impact: Optional[str] = None,
        department: Optional[str] = None,
        raw_text: str = "",
        source: str = "manual",
        actor: Optional[User] = None,
    ) -> IdeaOut:
        """Operator-authored create (no draft/collect/confirm gate — an operator
        typing an idea IS deliberate). Validates the product, seeds the idea at the
        initial ``draft`` status, then rides the status engine ``draft → captured``
        so the move is server-authoritative + emits the same events as any other
        transition. Submitter = the operator (``submitter_name`` set from the user;
        ``submitter_contact_id`` stays NULL — operator ideas have no contact copy).
        The segregated intake fields (proposed_solution / impact / department) are
        persisted to their first-class columns and mirrored into ``captured_json``."""
        self._product_or_422(tenant_id, product_id)
        problem = (problem or "").strip()
        proposed_solution = (proposed_solution or "").strip() or None
        impact = (impact or "").strip() or None
        department = (department or "").strip() or None
        raw_text = (raw_text or "").strip()
        captured: dict = {}
        if problem:
            captured["problem"] = problem
        if proposed_solution:
            captured["proposed_solution"] = proposed_solution
        if impact:
            captured["impact"] = impact
        if department:
            captured["department"] = department
        idea = Idea(
            tenant_id=tenant_id,
            product_id=product_id,
            status_id=initial_idea_status_id(self.db, tenant_id),
            intake_definition_key="ideation",
            problem=problem,
            proposed_solution=proposed_solution,
            impact=impact,
            department=department,
            raw_text=raw_text,
            source=(source or "manual").strip() or "manual",
            submitter_contact_id=None,
            submitter_name=(actor.name if actor else None),
            captured_json=captured,
        )
        self.db.add(idea)
        self.db.flush()
        captured_id = idea_status_id(self.db, "captured", tenant_id)
        status_machine.transition(
            self.db, IDEA_ENTITY, idea, captured_id, actor=actor, tenant_id=tenant_id
        )
        self.db.refresh(idea)
        return self._reader.serialize_one(idea, actor.id if actor else None)

    def update_operator(
        self,
        tenant_id: str,
        idea_id: str,
        *,
        product_id: Optional[str] = None,
        problem: Optional[str] = None,
        proposed_solution: Optional[str] = None,
        impact: Optional[str] = None,
        department: Optional[str] = None,
        raw_text: Optional[str] = None,
        voter_id: Optional[str] = None,
    ) -> IdeaOut:
        """Operator edit of the mutable idea fields (partial). Status moves ride
        the dedicated ``/{id}/status`` route — never duplicated here. Each provided
        segregated field updates its column AND its ``captured_json`` mirror (blank
        clears the optional ones; ``problem`` keeps its NOT-NULL value)."""
        idea = self._idea_or_404(tenant_id, idea_id)
        captured: dict = dict(idea.captured_json or {})
        if product_id is not None:
            self._product_or_422(tenant_id, product_id)
            idea.product_id = product_id
        if problem is not None:
            idea.problem = problem.strip()
            if idea.problem:
                captured["problem"] = idea.problem
        for arg, key in (
            (proposed_solution, "proposed_solution"),
            (impact, "impact"),
            (department, "department"),
        ):
            if arg is not None:
                value = arg.strip() or None
                setattr(idea, key, value)
                if value:
                    captured[key] = value
                else:
                    captured.pop(key, None)
        if raw_text is not None:
            idea.raw_text = raw_text.strip()
        idea.captured_json = captured
        self.db.commit()
        self.db.refresh(idea)
        return self._reader.serialize_one(idea, voter_id)

    def _recount(self, idea: Idea) -> None:
        """Recompute the idea's denormalized tallies from ``idea_votes`` (the
        source of truth)."""
        rows = self.db.query(IdeaVote).filter(IdeaVote.idea_id == idea.id).all()
        idea.upvotes = sum(1 for r in rows if r.dir == "up")
        idea.downvotes = sum(1 for r in rows if r.dir == "down")

    def vote(self, tenant_id: str, idea_id: str, voter_id: str, dir: str) -> IdeaOut:
        """Toggle the caller's vote (one row per ``(idea, voter)``): same ``dir``
        cancels, the other ``dir`` switches. Idempotent — recomputes tallies."""
        idea = self._idea_or_404(tenant_id, idea_id)
        existing = (
            self.db.query(IdeaVote)
            .filter(IdeaVote.idea_id == idea_id, IdeaVote.voter_id == voter_id)
            .first()
        )
        if existing is None:
            self.db.add(
                IdeaVote(
                    tenant_id=tenant_id,
                    idea_id=idea_id,
                    voter_id=voter_id,
                    dir=dir,
                )
            )
        elif existing.dir == dir:
            self.db.delete(existing)  # cancel
        else:
            existing.dir = dir  # switch
        self.db.flush()
        self._recount(idea)
        self.db.commit()
        return self._reader.serialize_one(idea, voter_id)

    def reorder(
        self, tenant_id: str, ordered_ids: List[str], voter_id: Optional[str] = None
    ) -> List[IdeaOut]:
        """Set manual priority from the given order (index = priority, ascending
        = top). Only the tenant's own ideas are touched; returns all tenant ideas
        ordered by priority."""
        ideas = {
            i.id: i
            for i in self.db.query(Idea).filter(Idea.tenant_id == tenant_id).all()
        }
        for index, idea_id in enumerate(ordered_ids):
            idea = ideas.get(idea_id)
            if idea is not None:
                idea.priority = index
        self.db.commit()
        ordered = (
            self.db.query(Idea)
            .filter(Idea.tenant_id == tenant_id)
            .order_by(Idea.priority.asc(), Idea.created_at.desc(), Idea.id.desc())
            .all()
        )
        return self._reader.serialize_many(ordered, voter_id)

    def set_status(
        self,
        tenant_id: str,
        idea_id: str,
        status_key: str,
        actor: Optional[User],
        voter_id: Optional[str] = None,
    ) -> IdeaOut:
        """Move the idea to ``status_key`` via the status engine. Illegal moves
        are refused (409); a role-blocked edge is 403; an unknown key is 422."""
        idea = self._idea_or_404(tenant_id, idea_id)
        target_id = idea_status_id(self.db, status_key, tenant_id)
        if target_id is None:
            raise HTTPException(422, f"Unknown idea status '{status_key}'.")
        try:
            status_machine.transition(
                self.db, IDEA_ENTITY, idea, target_id, actor=actor, tenant_id=tenant_id
            )
        except TransitionForbidden as exc:
            raise HTTPException(403, exc.message) from exc
        except (TransitionNotAllowed, TransitionConditionsNotMet) as exc:
            raise HTTPException(409, exc.message) from exc
        self.db.refresh(idea)
        return self._reader.serialize_one(idea, voter_id)

    def delete(self, tenant_id: str, idea_id: str) -> None:
        """Hard-delete the idea and its vote rows (no soft delete)."""
        idea = self._idea_or_404(tenant_id, idea_id)
        self.db.query(IdeaVote).filter(IdeaVote.idea_id == idea_id).delete(
            synchronize_session=False
        )
        self.db.delete(idea)
        self.db.commit()
