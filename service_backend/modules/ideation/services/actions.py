"""Idea write actions (Slice 4) - vote / reorder / status transition / delete.

These back the FE prototype's ``vote`` / ``reorderPriority`` / ``setStatus`` /
``remove`` service methods. Status moves are server-authoritative: every change
rides the CORE status engine (``status_machine.transition``) so an illegal move
is refused at the boundary (D-A3). No LLM anywhere - deterministic paths only.
"""
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.models.status import Status
from app.models.user import User
from app.repositories.status_repository import StatusRepository
from app.services import status_machine
from app.services.status_machine import (
    TransitionConditionsNotMet,
    TransitionForbidden,
    TransitionNotAllowed,
)

from ..models import Idea, IdeaVote
from ..schemas import IdeaOut
from .ideas import IdeaReadService, next_capture_priority
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

    def _refuse_if_merged_child(self, idea: Idea) -> None:
        """D3/AC-94-09 - a merged child is frozen: no vote, no status move.
        409 naming the survivor's idea number (falling back to its id when it
        has none yet)."""
        if not idea.merged_into_id:
            return
        survivor = (
            self.db.query(Idea)
            .filter(Idea.id == idea.merged_into_id, Idea.tenant_id == idea.tenant_id)
            .first()
        )
        label = (survivor.idea_number if survivor else None) or idea.merged_into_id
        raise HTTPException(409, f"This idea was merged into {label}.")

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
        submitter_crm_user_id: Optional[str] = None,
        submitter_name: Optional[str] = None,
    ) -> IdeaOut:
        """Operator-authored create (no draft/collect/confirm gate - an operator
        typing an idea IS deliberate). Validates the product, seeds the idea at the
        initial ``draft`` status, then rides the status engine ``draft → captured``
        so the move is server-authoritative + emits the same events as any other
        transition. Submitter = the operator (``submitter_name`` set from the user;
        ``submitter_contact_id`` stays NULL - operator ideas have no contact copy).
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
            # Embed create passes the viewing CRM user (SS-IDEATION-OWN);
            # operator create keeps the operator's name.
            submitter_name=(
                (submitter_name or "").strip() or (actor.name if actor else None)
            ),
            submitter_crm_user_id=(submitter_crm_user_id or "").strip() or None,
            captured_json=captured,
        )
        self.db.add(idea)
        self.db.flush()
        captured_id = idea_status_id(self.db, "captured", tenant_id)
        # New capture lands at the bottom of its lane (Q4) - stamped right at
        # the first move into ``captured`` (plan section 5).
        idea.priority = next_capture_priority(self.db, tenant_id, is_test=False)
        status_machine.transition(
            self.db, IDEA_ENTITY, idea, captured_id, actor=actor, tenant_id=tenant_id
        )
        self.db.refresh(idea)
        return self._reader.serialize_one(
            idea,
            actor.id if actor else None,
            tenant_id=tenant_id,
            actor=actor,
        )

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
        the dedicated ``/{id}/status`` route - never duplicated here. Each provided
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
        return self._reader.serialize_one(idea, voter_id, tenant_id=tenant_id)

    def _recount(self, idea: Idea) -> None:
        """Recompute the idea's denormalized tallies from ``idea_votes`` (the
        source of truth)."""
        rows = self.db.query(IdeaVote).filter(IdeaVote.idea_id == idea.id).all()
        idea.upvotes = sum(1 for r in rows if r.dir == "up")
        # Plan 19: upvote only. Legacy 'down' rows are kept but ignored.
        idea.downvotes = 0

    def vote(self, tenant_id: str, idea_id: str, voter_id: str, dir: str) -> IdeaOut:
        """Toggle the caller's upvote (one row per ``(idea, voter)``): an existing
        ``up`` cancels; a legacy ``down`` row is switched to ``up``. Idempotent -
        recomputes tallies."""
        idea = self._idea_or_404(tenant_id, idea_id)
        self._refuse_if_merged_child(idea)
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
        return self._reader.serialize_one(idea, voter_id, tenant_id=tenant_id)

    def reorder(
        self,
        tenant_id: str,
        ordered_ids: List[str],
        voter_id: Optional[str] = None,
        actor: Optional[User] = None,
    ) -> List[IdeaOut]:
        """Slot-preserving reorder (issue #94, AC-94-45): densify each
        affected lane's priority first (heals any legacy ties into 1..N, no
        gaps), then take the GIVEN ids' current (now-dense) slots, sorted
        ascending, and reassign them in the given order. A page-subset
        ``/reorder`` call therefore only ever rewrites the slots the given
        ids already occupied - the other rows' priority never moves (fixes
        the page-2-drag-corrupts-page-1 bug, plan section 5). Ids outside the
        tenant, or that are merged children, are silently ignored (they hold
        no rank of their own, AC-94-19).

        Review round 1 NIT #12: the RESPONSE is scoped to the caller's own
        lane (survivors, the SAME ``is_test`` lane the reordered ids belong
        to) instead of the whole tenant across every product/lane - a bulk
        reorder response has no business returning rows the caller never
        asked about. ``actor`` is threaded through to serialization so
        per-record transitions/advance respect the caller's own role
        (previously always computed with no actor)."""
        ideas_by_id = {
            i.id: i
            for i in self.db.query(Idea)
            .filter(
                Idea.id.in_(ordered_ids),
                Idea.tenant_id == tenant_id,
                Idea.merged_into_id.is_(None),
            )
            .all()
        }
        requested = [i for i in ordered_ids if i in ideas_by_id]
        lanes = sorted({ideas_by_id[i].is_test for i in requested})
        for is_test in lanes:
            lane_requested = [i for i in requested if ideas_by_id[i].is_test == is_test]
            lane_ideas = (
                self.db.query(Idea)
                .filter(
                    Idea.tenant_id == tenant_id,
                    Idea.is_test.is_(is_test),
                    Idea.merged_into_id.is_(None),
                )
                .order_by(Idea.priority.asc(), Idea.created_at.desc(), Idea.id.desc())
                .all()
            )
            for slot, lane_idea in enumerate(lane_ideas, start=1):
                lane_idea.priority = slot
            self.db.flush()
            slot_by_id = {lane_idea.id: lane_idea.priority for lane_idea in lane_ideas}
            taken_slots = sorted(slot_by_id[i] for i in lane_requested)
            for slot, idea_id in zip(taken_slots, lane_requested):
                ideas_by_id[idea_id].priority = slot
        self.db.commit()
        if not requested:
            return []
        ordered = (
            self.db.query(Idea)
            .filter(
                Idea.tenant_id == tenant_id,
                Idea.merged_into_id.is_(None),
                Idea.is_test.in_(lanes),
            )
            .order_by(Idea.priority.asc(), Idea.created_at.desc(), Idea.id.desc())
            .all()
        )
        return self._reader.serialize_many(
            ordered, voter_id, tenant_id=tenant_id, actor=actor
        )

    def _validated_target_status_id(self, tenant_id: str, to_status_id: str) -> str:
        """422 unless ``to_status_id`` resolves to an idea-entity status row in
        the tenant's resolved tier (issue #94 AC-94-53) - a status id from a
        different entity (e.g. the core tenant lifecycle) is refused before
        ever reaching the status machine's generic "no edge" 409."""
        tier = StatusRepository(self.db).resolve_tier(IDEA_ENTITY, tenant_id)
        tier_filter = (
            Status.tenant_id.is_(None) if tier is None else Status.tenant_id == tier
        )
        row = (
            self.db.query(Status)
            .filter(Status.id == to_status_id, Status.entity_type == IDEA_ENTITY, tier_filter)
            .first()
        )
        if row is None:
            raise HTTPException(422, "toStatusId does not resolve to an idea status.")
        return row.id

    def set_status(
        self,
        tenant_id: str,
        idea_id: str,
        status_key: Optional[str] = None,
        actor: Optional[User] = None,
        voter_id: Optional[str] = None,
        *,
        to_status_id: Optional[str] = None,
    ) -> IdeaOut:
        """Move the idea via the status engine - by lifecycle KEY (kept for the
        deferred Archive handler) or by status-engine ``toStatusId`` (issue #94
        plan section 6, never a hardcoded key). Illegal moves are refused
        (409); a role-blocked edge is 403; an unknown key or an out-of-entity
        target id is 422."""
        idea = self._idea_or_404(tenant_id, idea_id)
        self._refuse_if_merged_child(idea)
        if to_status_id is not None:
            target_id = self._validated_target_status_id(tenant_id, to_status_id)
        else:
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
        return self._reader.serialize_one(
            idea, voter_id, tenant_id=tenant_id, actor=actor
        )

    def delete(self, tenant_id: str, idea_id: str) -> None:
        """Hard-delete the idea and its vote + comment rows (no soft delete). AC-94-10:
        deleting a survivor restores its children FIRST (unmerge, votes moved
        back) so no child is left pointing at a row that no longer exists.

        Review round 1 NIT #11: deleting a merged CHILD outright (still
        pointing at a survivor) also removes its STAMPED vote rows still
        resident on the survivor (``origin_idea_id == idea_id``) - they can
        never be restored to an idea that no longer exists, and the
        survivor's tally must not silently keep counting a voter whose
        origin record is gone."""
        idea = self._idea_or_404(tenant_id, idea_id)
        has_children = (
            self.db.query(Idea.id)
            .filter(Idea.tenant_id == tenant_id, Idea.merged_into_id == idea_id)
            .first()
            is not None
        )
        if has_children:
            from .merge import IdeaMergeService

            IdeaMergeService(self.db).unmerge(tenant_id, idea_id)
            idea = self._idea_or_404(tenant_id, idea_id)
        elif idea.merged_into_id:
            survivor_id = idea.merged_into_id
            self.db.query(IdeaVote).filter(
                IdeaVote.tenant_id == tenant_id,
                IdeaVote.idea_id == survivor_id,
                IdeaVote.origin_idea_id == idea_id,
            ).delete(synchronize_session=False)
            self.db.flush()
            survivor = (
                self.db.query(Idea)
                .filter(Idea.id == survivor_id, Idea.tenant_id == tenant_id)
                .first()
            )
            if survivor is not None:
                self._recount(survivor)
        self.db.query(IdeaVote).filter(IdeaVote.idea_id == idea_id).delete(
            synchronize_session=False
        )
        # AC-19-09: comments go with the idea (replies first, then parents).
        from .comments import IdeaCommentService

        IdeaCommentService(self.db).purge_for_idea(tenant_id, idea_id)
        self.db.delete(idea)
        self.db.commit()
