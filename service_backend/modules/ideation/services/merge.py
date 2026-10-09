"""Merge and unmerge (issue #94, plan section 3.2) - ``IdeaMergeService``.

D1: ``ideas.merged_into_id`` is a plain indexed column, NO FK (BL-030 - a FK
on this hot table would lock a live deploy). D2: single level - merging an
already-a-survivor member FLATTENS its existing children onto the new
survivor, so ``merged_into_id`` never points at a row that itself points
somewhere (every read is one hop). D3: a merged child's status is FROZEN
(never touched here - guards live in ``actions.py``/``business_requirements.
py``). D4: votes MOVE to the survivor, stamped ``origin_idea_id``; a voter who
already voted on the survivor keeps their child-side row in place (shadowed -
it never counts twice on the survivor). Unmerge is LOSSLESS: the shadow row
never left the child, so restoring only moves back the STAMPED rows - see
:meth:`_restore_votes`. D10: the survivor always gets an idea number
(``mint_idea_identity``, idempotent).
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.status import Status
from app.models.user import User

from ..models import Idea, IdeaVote
from ..schemas import IdeaOut
from .actions import IdeaActionService
from .ideas import IdeaReadService
from .numbering import mint_idea_identity
from .status_events import record_flatten_events, record_merge_events, record_unmerge_events


class IdeaMergeService:
    def __init__(self, db: Session):
        self.db = db
        self._reader = IdeaReadService(db)
        self._actions = IdeaActionService(db)

    # ── merge ────────────────────────────────────────────────────────────────

    def merge(
        self,
        tenant_id: str,
        survivor_id: str,
        idea_ids: List[str],
        actor: Optional[User] = None,
    ) -> IdeaOut:
        """Collapse ``idea_ids`` onto ``survivor_id`` (AC-94-01). All
        validation (D6) happens BEFORE any write - a rejected merge changes
        nothing (AC-94-04)."""
        ids = list(dict.fromkeys(idea_ids))
        if len(ids) < 2:
            raise HTTPException(422, "Merge needs at least two ideas.")
        if survivor_id not in ids:
            raise HTTPException(422, "survivorId must be one of ideaIds.")

        # Locked, in a STABLE id order (review round 1 #4, consolidated round
        # 2 nit 1) - ONE ordered statement locks the WHOLE group (the
        # requested ideas AND any pre-existing children of any of them) so a
        # concurrent merge/unmerge touching an overlapping id set blocks
        # rather than racing past this validation; ordering by id avoids a
        # lock-order deadlock against another transaction locking the same
        # rows in a different order. SQLite (tests) ignores
        # `with_for_update()` silently (single-writer engine, ignore is
        # correct there, not a bug).
        locked_rows = (
            self.db.query(Idea)
            .filter(
                Idea.tenant_id == tenant_id,
                or_(Idea.id.in_(ids), Idea.merged_into_id.in_(ids)),
            )
            .order_by(Idea.id.asc())
            .with_for_update()
            .all()
        )
        ideas_by_id = {i.id: i for i in locked_rows if i.id in ids}
        if any(i not in ideas_by_id for i in ids):
            raise HTTPException(404, "One or more ideas were not found.")

        self._validate_merge_set(ideas_by_id.values())

        survivor = ideas_by_id[survivor_id]
        members = [ideas_by_id[i] for i in ids if i != survivor_id]

        # ── writes from here on ──────────────────────────────────────────
        mint_idea_identity(self.db, survivor)  # D10 (AC-94-12)

        now = datetime.now(timezone.utc)
        member_ids = [m.id for m in members]

        # Only recount an idea whose vote-row SET actually changed (a row
        # physically moved onto/off it) - a shadowed row never moves, so a
        # member with nothing to move leaves the survivor's existing tally
        # untouched (never zeroes a real count just because THIS member had
        # no votes of its own).
        touched_ids = set()
        flattened_children: List[Idea] = []

        # Flatten (D2, AC-94-05): any EXISTING children of an absorbed
        # member re-point straight to the new survivor - never a chain.
        # Already locked above (part of the same single group statement).
        if member_ids:
            existing_children = [
                r for r in locked_rows if r.merged_into_id in member_ids
            ]
            for child in existing_children:
                # Review round 1 #3 (D4 lossless under flatten): a grandchild's
                # votes may currently be resident on the INTERMEDIATE member
                # (the member that originally absorbed it), stamped
                # `origin_idea_id == child.id` - not on the child itself.
                # Flatten repoints `child.merged_into_id` straight to the NEW
                # survivor (D2, single hop), so any such row must follow it
                # NOW, or it is permanently stranded on a node nobody will
                # ever look at again (an intermediate member that is itself
                # about to become a frozen child) - unmerging the grandchild
                # would never find it, and the intermediate member would wrongly
                # keep counting it forever.
                touched_ids |= self._relocate_inherited_votes(
                    tenant_id, child.id, survivor_id
                )
                child.merged_into_id = survivor_id
                flattened_children.append(child)

        for index, member in enumerate(members):
            moved = self._move_votes(member.id, survivor_id)
            member.merged_into_id = survivor_id
            # Strictly increasing per member, in the given order (never a
            # single shared instant) - the "oldest merge first" ordering on
            # the Merged-from tab (AC-94-03) needs a real tie-break when a
            # whole group lands in one call.
            member.merged_at = now + timedelta(microseconds=index)
            if moved:
                touched_ids.add(member.id)
                touched_ids.add(survivor_id)

        for idea_id in touched_ids:
            row = ideas_by_id.get(idea_id) or self._idea_in_tenant(tenant_id, idea_id)
            if row is not None:
                self._actions._recount(row)

        record_merge_events(
            self.db, tenant_id=tenant_id, survivor=survivor, members=members, actor=actor
        )
        if flattened_children:
            # Review round 1 NIT #10 - a grandchild re-pointed straight onto
            # the NEW survivor (flatten) gets its OWN "merged" event too: its
            # requester was already told it was combined into the OLD
            # (intermediate) survivor, and now needs to know it tracks the
            # NEW one instead.
            record_flatten_events(
                self.db, tenant_id=tenant_id, survivor=survivor, children=flattened_children
            )

        self.db.commit()
        self.db.refresh(survivor)
        return self._reader.serialize_one(
            survivor, actor.id if actor else None, tenant_id=tenant_id, actor=actor
        )

    def _idea_in_tenant(self, tenant_id: str, idea_id: str) -> Optional[Idea]:
        return (
            self.db.query(Idea)
            .filter(Idea.id == idea_id, Idea.tenant_id == tenant_id)
            .first()
        )

    def _validate_merge_set(self, ideas) -> None:
        """D6 - refuse a mixed/invalid selection, no writes (AC-94-04)."""
        ideas = list(ideas)
        if len({i.product_id for i in ideas}) > 1:
            raise HTTPException(422, "All merged ideas must be on the same product.")
        if len({bool(i.is_test) for i in ideas}) > 1:
            raise HTTPException(422, "Cannot mix test and real ideas in a merge.")
        if any(i.merged_into_id for i in ideas):
            raise HTTPException(
                422, "One or more ideas are already merged into another idea."
            )
        status_ids = {i.status_id for i in ideas}
        archived_ids = {
            s.id
            for s in self.db.query(Status)
            .filter(Status.id.in_(status_ids), Status.is_archived.is_(True))
            .all()
        } if status_ids else set()
        if any(i.status_id in archived_ids for i in ideas):
            raise HTTPException(422, "An archived idea cannot be merged.")

    def _move_votes(self, from_id: str, to_id: str) -> int:
        """D4 - move ``from_id``'s vote rows onto ``to_id``. A voter who
        already has a row on ``to_id`` keeps their ``from_id`` row in place
        (shadowed - it is never double-counted on the survivor, and never
        counted as "moved"). Re-queries the shadow check per row so two
        absorbed members sharing one voter collapse onto a single row
        (unique ``(idea_id, voter_id)``). Returns the number of rows
        actually moved (0 = nothing to recount)."""
        rows = self.db.query(IdeaVote).filter(IdeaVote.idea_id == from_id).all()
        moved = 0
        for row in rows:
            shadow = (
                self.db.query(IdeaVote)
                .filter(IdeaVote.idea_id == to_id, IdeaVote.voter_id == row.voter_id)
                .first()
            )
            if shadow is not None:
                continue  # left in place, shadowed (AC-94-06)
            if row.origin_idea_id is None:
                row.origin_idea_id = from_id
            row.idea_id = to_id
            moved += 1
        self.db.flush()
        return moved

    def _relocate_inherited_votes(
        self, tenant_id: str, child_id: str, new_survivor_id: str
    ) -> set:
        """Review round 1 #3 (D4 lossless under flatten) - grandchild votes
        stamped ``origin_idea_id == child_id`` may currently live on an
        INTERMEDIATE absorbed member (wherever they physically moved to when
        ``child_id`` was originally merged), not on ``child_id`` itself.
        Flatten repoints ``child_id.merged_into_id`` straight to
        ``new_survivor_id`` (D2, single hop) - so each such row must follow:

        - if the new survivor does NOT already have that voter, move the row
          onto the new survivor, KEEPING its ``origin_idea_id`` stamp (a
          later ``unmerge(child_id)`` finds it there exactly as it would a
          normal single-level stamped vote);
        - if the new survivor ALREADY has that voter (a collision), send the
          row straight back to its TRUE origin (``child_id``), clearing the
          stamp - a normal resident/shadowed vote, restorable with no move at
          all, instead of a row permanently stranded on an intermediate node
          nobody will ever inspect again.

        Returns the set of idea ids whose vote-row SET changed (for the
        caller's recount pass) - the row's OLD location, and either
        ``new_survivor_id`` or ``child_id`` depending on which branch fired."""
        rows = (
            self.db.query(IdeaVote)
            .filter(IdeaVote.tenant_id == tenant_id, IdeaVote.origin_idea_id == child_id)
            .all()
        )
        touched: set = set()
        for row in rows:
            if row.idea_id == new_survivor_id:
                continue  # already resident on the target, nothing to move
            shadow = (
                self.db.query(IdeaVote)
                .filter(IdeaVote.idea_id == new_survivor_id, IdeaVote.voter_id == row.voter_id)
                .first()
            )
            touched.add(row.idea_id)
            if shadow is not None:
                touched.add(child_id)
                row.idea_id = child_id
                row.origin_idea_id = None
            else:
                touched.add(new_survivor_id)
                row.idea_id = new_survivor_id
        self.db.flush()
        return touched

    # ── unmerge ──────────────────────────────────────────────────────────────

    def unmerge(
        self, tenant_id: str, idea_id: str, actor: Optional[User] = None
    ) -> List[IdeaOut]:
        """Restore ``idea_id`` (a child - AC-94-07) or dissolve its whole
        group (a survivor - AC-94-08); 422 for a plain idea (neither)."""
        # Review round 2 nit 1: read the target UNLOCKED first, purely to
        # determine which group (root id - the survivor if idea_id is a
        # child, else idea_id itself) needs locking; the row's OWN lock
        # happens in the SAME single statement as its whole group below,
        # never a separate earlier lock.
        initial = (
            self.db.query(Idea.id, Idea.merged_into_id)
            .filter(Idea.id == idea_id, Idea.tenant_id == tenant_id)
            .first()
        )
        if initial is None:
            raise HTTPException(404, "Idea not found.")
        root = initial.merged_into_id or initial.id

        # Lock the WHOLE group (the root plus every CURRENT child) in ONE
        # ordered statement (review round 1 #4, consolidated round 2 nit 1) -
        # same reasoning as `merge()`'s single group lock.
        locked_rows = (
            self.db.query(Idea)
            .filter(
                Idea.tenant_id == tenant_id,
                or_(Idea.id == root, Idea.merged_into_id == root),
            )
            .order_by(Idea.id.asc())
            .with_for_update()
            .all()
        )
        by_id = {r.id: r for r in locked_rows}

        # Re-validate against the NOW-LOCKED state, never the unlocked read
        # above (which could be stale by the time the lock is granted).
        idea = by_id.get(idea_id)
        if idea is None:
            raise HTTPException(404, "Idea not found.")
        children = [r for r in locked_rows if r.id != root and r.merged_into_id == root]
        if idea.merged_into_id:
            targets = [idea]
        elif children:
            targets = children
        else:
            raise HTTPException(
                422, "This idea is neither merged nor the survivor of a merge."
            )

        # Captured BEFORE the loop clears the pointer - the requester-event
        # writer needs each restored child's FORMER survivor (`separated_from`,
        # AC-94-64), and by the time it runs below `merged_into_id` is already
        # None on every target.
        former_survivor_ids = {child.id: child.merged_into_id for child in targets}

        touched_ids = set()
        for child in targets:
            survivor_id = child.merged_into_id
            self._restore_votes(tenant_id, survivor_id, child.id)
            child.merged_into_id = None
            child.merged_at = None
            touched_ids.add(child.id)
            touched_ids.add(survivor_id)

        for tid in touched_ids:
            row = self._idea_in_tenant(tenant_id, tid)
            if row is not None:
                self._actions._recount(row)

        record_unmerge_events(
            self.db,
            tenant_id=tenant_id,
            restored=targets,
            former_survivor_ids=former_survivor_ids,
            actor=actor,
        )

        self.db.commit()
        restored_ids = [t.id for t in targets]
        restored = (
            self.db.query(Idea)
            .filter(Idea.id.in_(restored_ids), Idea.tenant_id == tenant_id)
            .all()
        )
        by_id = {r.id: r for r in restored}
        ordered = [by_id[i] for i in restored_ids if i in by_id]
        return self._reader.serialize_many(
            ordered, actor.id if actor else None, tenant_id=tenant_id, actor=actor
        )

    def _restore_votes(self, tenant_id: str, survivor_id: str, child_id: str) -> None:
        """D4 - unmerge is LOSSLESS: a shadowed row never left the child (D4/
        AC-94-06), so it is never touched here - only the ``origin_idea_id ==
        child_id`` STAMPED rows (the ones that actually moved onto the
        survivor) move back, with origin cleared. A shadow row plus a
        returning stamped row for the SAME voter cannot legitimately coexist
        (a stamp is only created when the survivor lacked that voter at move
        time - see ``_move_votes``), but the unique ``(idea_id, voter_id)``
        constraint is guarded defensively anyway: if the child already has a
        row for that voter, the returning stamped row is dropped rather than
        raising on the constraint."""
        moved = (
            self.db.query(IdeaVote)
            .filter(
                IdeaVote.tenant_id == tenant_id,
                IdeaVote.idea_id == survivor_id,
                IdeaVote.origin_idea_id == child_id,
            )
            .all()
        )
        for row in moved:
            shadow = (
                self.db.query(IdeaVote)
                .filter(IdeaVote.idea_id == child_id, IdeaVote.voter_id == row.voter_id)
                .first()
            )
            if shadow is not None:
                self.db.delete(row)
                continue
            row.idea_id = child_id
            row.origin_idea_id = None
        self.db.flush()
