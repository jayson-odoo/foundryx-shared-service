"""Idea read service (AC-A-12) - list + detail, serialized to the FE Idea shape.

Reads are tenant-scoped. The Idea's ``product_id`` / ``status_id`` /
``submitter_contact_id`` are cross-schema FKs; this service resolves them to
human-readable values (product name, status key, submitter name) so the UI never
renders a raw UUID (cursor rule). Attachments are an always-present (currently
empty) section - the attachment writer lands with the create_idea slice.

Issue #94 (round 2, plan sections 5+6): status display fields, per-record
transitions and rank are ALL resolved here (from the status engine / the
idea's rank lane), never hardcoded - see ``next_capture_priority`` and the
``_transitions_and_advance`` / ``_rank_map`` helpers below.
"""
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.models.status import Status
from app.models.user import User
from app.repositories.status_repository import StatusRepository
from app.repositories.status_transition_repository import StatusTransitionRepository
from app.services import status_machine
from modules.omnichannel.models import Contact

from ..models import Idea, IdeaAttachment, IdeaVote
from ..schemas import (
    BoardColumnOut,
    BoardOut,
    IdeaAttachmentOut,
    IdeaMergedIntoOut,
    IdeaOut,
    TransitionOut,
)
from .statuses import IDEA_ENTITY


def next_capture_priority(db: Session, tenant_id: str, is_test: bool = False) -> int:
    """1 past the current max stored ``priority`` in this idea's capture lane
    (``tenant_id``, ``is_test`` - plan section 5, D11/Q4): a new capture lands
    at the BOTTOM of its lane (a triager drags it up), never colliding with an
    existing rank. Merged children (``merged_into_id`` set) never count -
    they hold no rank of their own.

    Tie tolerance (review round 1 #12): two concurrent captures can read the
    SAME ``current_max`` and both land on the same ``priority`` value - this
    is tolerated, not locked against, because ties are already broken
    deterministically everywhere this column is ordered
    (``created_at desc, id desc``); a rare concurrent-capture collision only
    ever produces a stable order, never a corrupt or crashing one, so no
    ``with_for_update()`` guard is needed here."""
    current_max = (
        db.query(func.max(Idea.priority))
        .filter(
            Idea.tenant_id == tenant_id,
            Idea.is_test.is_(is_test),
            Idea.merged_into_id.is_(None),
        )
        .scalar()
    )
    return (current_max or 0) + 1


def _submitter_name(contact: Optional[Contact]) -> str:
    if contact is None:
        return "Unknown"
    name = " ".join(p for p in (contact.first_name, contact.last_name) if p).strip()
    return name or "Unknown"


class IdeaReadService:
    def __init__(self, db: Session, content_prefix: str = "/ideation/ideas"):
        self.db = db
        # Route prefix an uploaded attachment's ``contentPath`` is built from
        # (the embed routes pass ``/embed/ideas``).
        self.content_prefix = content_prefix

    def _serialize(
        self,
        idea: Idea,
        products: Dict[str, Product],
        statuses: Dict[str, Status],
        contacts: Dict[str, Contact],
        my_votes: Optional[Dict[str, str]] = None,
        attachments: Optional[Dict[str, List[IdeaAttachmentOut]]] = None,
        transitions: Optional[List[TransitionOut]] = None,
        advance_transition_id: Optional[str] = None,
        rank: Optional[int] = None,
        merged_into: Optional[IdeaMergedIntoOut] = None,
        merged_count: int = 0,
    ) -> IdeaOut:
        product = products.get(idea.product_id)
        status = statuses.get(idea.status_id)
        contact = contacts.get(idea.submitter_contact_id) if idea.submitter_contact_id else None
        # Operator-authored ideas store the display name directly (no contact);
        # otherwise derive it from the linked contact (D-A4).
        submitter = (idea.submitter_name or "").strip() or _submitter_name(contact)
        my_vote = (my_votes or {}).get(idea.id)
        idea_attachments = (attachments or {}).get(idea.id, [])
        return IdeaOut(
            id=idea.id,
            productId=idea.product_id,
            productName=product.name if product else "Unknown product",
            status=status.key if status else "draft",
            statusId=idea.status_id,
            statusLabel=status.label if status else "",
            statusColor=status.color if status else "gray",
            statusIsArchived=bool(status.is_archived) if status else False,
            transitions=transitions or [],
            advanceTransitionId=advance_transition_id,
            title=idea.title,
            problem=idea.problem,
            proposedSolution=idea.proposed_solution,
            impact=idea.impact,
            department=idea.department,
            rawText=idea.raw_text or "",
            source=idea.source,
            submitterName=submitter,
            submitterTier=idea.submitter_tier,
            upvotes=idea.upvotes or 0,
            downvotes=0,  # plan 19: upvote only; legacy 'down' rows are ignored
            myVote="up" if my_vote == "up" else None,
            priority=idea.priority or 0,
            rank=rank,
            attachments=idea_attachments,
            createdAt=idea.created_at,
            ideaNumber=idea.idea_number,
            isTest=bool(idea.is_test),
            mergedIntoId=idea.merged_into_id,
            mergedInto=merged_into,
            mergedCount=merged_count,
        )

    def _my_votes(
        self, ideas: List[Idea], voter_id: Optional[str]
    ) -> Dict[str, str]:
        """``{idea_id: dir}`` for the caller across a set of ideas (no N+1)."""
        if not voter_id or not ideas:
            return {}
        idea_ids = [i.id for i in ideas]
        rows = (
            self.db.query(IdeaVote)
            .filter(IdeaVote.voter_id == voter_id, IdeaVote.idea_id.in_(idea_ids))
            .all()
        )
        return {r.idea_id: r.dir for r in rows}

    def _attachments_by_idea(
        self, ideas: List[Idea]
    ) -> Dict[str, List[IdeaAttachmentOut]]:
        """``{idea_id: [IdeaAttachmentOut, …]}`` for a set of ideas (no N+1),
        oldest-first. ``name`` prefers the filename, falling back to the kind."""
        if not ideas:
            return {}
        idea_ids = [i.id for i in ideas]
        rows = (
            self.db.query(IdeaAttachment)
            .filter(
                IdeaAttachment.idea_id.in_(idea_ids),
                IdeaAttachment.tenant_id.in_({i.tenant_id for i in ideas}),
            )
            .order_by(IdeaAttachment.created_at.asc(), IdeaAttachment.id.asc())
            .all()
        )
        out: Dict[str, List[IdeaAttachmentOut]] = {}
        for r in rows:
            out.setdefault(r.idea_id, []).append(
                IdeaAttachmentOut(
                    id=r.id,
                    kind=r.kind,
                    name=(r.filename or "").strip() or r.kind,
                    url=r.url or "",
                    sizeBytes=r.size_bytes,
                    contentPath=(
                        f"{self.content_prefix}/{r.idea_id}/attachments/{r.id}/content"
                        if r.storage_key
                        else None
                    ),
                )
            )
        return out

    def _merge_maps(
        self, ideas: List[Idea]
    ) -> "tuple[Dict[str, IdeaMergedIntoOut], Dict[str, int]]":
        """Issue #94, plan section 3.2 - ``mergedInto`` (batched survivor
        lookup) + ``mergedCount`` (ONE grouped count over the page's ids), no
        N+1 regardless of page size.

        Review round 1 BLOCKER #2 - both queries below are tenant-scoped
        (``Idea.tenant_id.in_(tenant_ids)``, the caller's OWN tenant ids,
        never client input): a stored ``merged_into_id`` is a polymorphic
        stored id (the same rule as ``notification_recipients.target_id``) -
        resolving it unscoped could pick up a foreign tenant's row that
        happens to share an id pattern. ``survivor.tenant_id == idea.tenant_id``
        is asserted again per-idea as a second guard (every call site here
        is single-tenant in practice, but this never trusts that)."""
        if not ideas:
            return {}, {}
        idea_ids = [i.id for i in ideas]
        tenant_ids = {i.tenant_id for i in ideas}
        survivor_ids = {i.merged_into_id for i in ideas if i.merged_into_id}
        merged_into_map: Dict[str, IdeaMergedIntoOut] = {}
        if survivor_ids:
            survivors = {
                s.id: s
                for s in self.db.query(Idea)
                .filter(Idea.id.in_(survivor_ids), Idea.tenant_id.in_(tenant_ids))
                .all()
            }
            for idea in ideas:
                survivor = survivors.get(idea.merged_into_id) if idea.merged_into_id else None
                if survivor is not None and survivor.tenant_id == idea.tenant_id:
                    merged_into_map[idea.id] = IdeaMergedIntoOut(
                        id=survivor.id,
                        ideaNumber=survivor.idea_number,
                        title=survivor.title or survivor.problem,
                    )
        rows = (
            self.db.query(Idea.merged_into_id, func.count(Idea.id))
            .filter(Idea.merged_into_id.in_(idea_ids), Idea.tenant_id.in_(tenant_ids))
            .group_by(Idea.merged_into_id)
            .all()
        )
        merged_count_map = {survivor_id: count for survivor_id, count in rows}
        return merged_into_map, merged_count_map

    def _archived_status_ids(self, tenant_id: str) -> List[str]:
        """Idea status ids with ``is_archived`` set, in the tenant's RESOLVED
        TIER (issue #94 0.1 fix: the old query read every tenant's archived
        keys - never tier-scoped)."""
        tier = StatusRepository(self.db).resolve_tier(IDEA_ENTITY, tenant_id)
        tier_filter = (
            Status.tenant_id.is_(None) if tier is None else Status.tenant_id == tier
        )
        return [
            s.id
            for s in self.db.query(Status)
            .filter(
                Status.entity_type == IDEA_ENTITY,
                Status.is_archived.is_(True),
                tier_filter,
            )
            .all()
        ]

    def _rank_lane_ids(
        self, tenant_id: str, product_id: Optional[str], is_test: bool
    ) -> List[str]:
        """Ordered ids of the ACTIVE, non-merged survivors in this rank lane
        (plan section 5) - ``priority`` ascending, ``created_at`` descending,
        ``id`` descending (matches the list's own order)."""
        archived_ids = self._archived_status_ids(tenant_id)
        q = self.db.query(Idea.id).filter(
            Idea.tenant_id == tenant_id,
            Idea.is_test.is_(is_test),
            Idea.merged_into_id.is_(None),
        )
        if product_id:
            q = q.filter(Idea.product_id == product_id)
        if archived_ids:
            q = q.filter(~Idea.status_id.in_(archived_ids))
        return [
            row.id
            for row in q.order_by(
                Idea.priority.asc(), Idea.created_at.desc(), Idea.id.desc()
            ).all()
        ]

    def _rank_map(
        self, ideas: List[Idea], tenant_id: Optional[str], product_id: Optional[str]
    ) -> Dict[str, Optional[int]]:
        """1-based rank per idea, computed once per distinct ``is_test`` lane
        present in ``ideas`` (never per record - one query per lane). ``None``
        when ``tenant_id`` isn't known (a legacy call site) or the idea sits
        outside the active lane (archived / merged)."""
        if not ideas or tenant_id is None:
            return {}
        result: Dict[str, Optional[int]] = {}
        for is_test in {bool(i.is_test) for i in ideas}:
            lane_ids = self._rank_lane_ids(tenant_id, product_id, is_test)
            lane_rank = {idea_id: idx + 1 for idx, idea_id in enumerate(lane_ids)}
            for idea in ideas:
                if bool(idea.is_test) == is_test:
                    result[idea.id] = lane_rank.get(idea.id)
        return result

    def _transitions_and_advance(
        self,
        ideas: List[Idea],
        statuses: Dict[str, Status],
        tenant_id: Optional[str],
        actor: Optional[User],
    ) -> (Dict[str, List[TransitionOut]], Dict[str, Optional[str]]):
        """Per-record fireable transitions + the single "advance" edge (plan
        section 6; rule revised issue #94 review round 1 #5, round 2 #A,
        AC-94-52). ``always=True`` (the core extension) always computes the
        per-record fireable map - ideation needs it on every request, not
        only when some edge happens to be conditioned.

        ``advanceTransitionId`` is the edge from the current status to the
        IMMEDIATELY NEXT status in the tier's ``sort_order`` - archived or
        not, so a terminal step like Delivered still advances to Closed
        (round 2 #A: filtering out archived statuses left Delivered with no
        next step at all, no UI path to close) - ONLY when that exact edge is
        fireable for the caller; otherwise ``null``. It never skips ahead to
        a LATER status (an off-ramp such as Duplicate/Rejected must never be
        offered as "advance" just because it happens to be the closest
        FIREABLE edge) - a tenant that swaps two stages' order changes the
        advance target with no code change, since it is driven purely by
        ``sort_order``, never a hardcoded key or ``category``."""
        if not ideas or tenant_id is None:
            return {}, {}
        tier = StatusRepository(self.db).resolve_tier(IDEA_ENTITY, tenant_id)
        # ONE query for the tier's whole edge set (issue #94 review round 1
        # #14) - reused both to hydrate fireable ids into full `TransitionOut`
        # objects AND passed into `fireable_edge_ids` so it skips its own
        # internal, otherwise-redundant copy of the same query.
        edges = StatusTransitionRepository(self.db).list_for_entity(IDEA_ENTITY, tier)
        edges_by_id = {e.id: e for e in edges}
        fireable = (
            status_machine.fireable_edge_ids(
                self.db,
                IDEA_ENTITY,
                ideas,
                actor,
                tenant_id=tenant_id,
                always=True,
                preloaded_edges=edges,
            )
            or {}
        )
        # Every status in the tier, sort_order ascending - archived or not
        # (round 2 #A): the immediately-next STATUS is found here regardless
        # of its archived flag; whether it is actually offered as "advance"
        # is decided below, purely by whether a fireable edge reaches it.
        tier_filter = (
            Status.tenant_id.is_(None) if tier is None else Status.tenant_id == tier
        )
        ordered_statuses = (
            self.db.query(Status)
            .filter(Status.entity_type == IDEA_ENTITY, tier_filter)
            .order_by(Status.sort_order.asc())
            .all()
        )
        transitions_map: Dict[str, List[TransitionOut]] = {}
        advance_map: Dict[str, Optional[str]] = {}
        for idea in ideas:
            idea_edges = [
                edges_by_id[eid] for eid in fireable.get(idea.id, []) if eid in edges_by_id
            ]
            transitions_map[idea.id] = [
                TransitionOut(
                    id=e.id,
                    label=e.label,
                    toStatusId=e.to_status_id,
                    toStatusLabel=e.to_status.label if e.to_status else "",
                )
                for e in idea_edges
            ]
            current = statuses.get(idea.status_id)
            current_sort = current.sort_order if current else -1
            next_status_id = next(
                (s.id for s in ordered_statuses if s.sort_order > current_sort), None
            )
            advance_map[idea.id] = next(
                (e.id for e in idea_edges if e.to_status_id == next_status_id),
                None,
            ) if next_status_id else None
        return transitions_map, advance_map

    def serialize_many(
        self,
        ideas: List[Idea],
        voter_id: Optional[str] = None,
        *,
        tenant_id: Optional[str] = None,
        product_id: Optional[str] = None,
        actor: Optional[User] = None,
    ) -> List[IdeaOut]:
        products, statuses, contacts = self._resolve_maps(ideas)
        my_votes = self._my_votes(ideas, voter_id)
        attachments = self._attachments_by_idea(ideas)
        transitions_map, advance_map = self._transitions_and_advance(
            ideas, statuses, tenant_id, actor
        )
        rank_map = self._rank_map(ideas, tenant_id, product_id)
        merged_into_map, merged_count_map = self._merge_maps(ideas)
        return [
            self._serialize(
                i,
                products,
                statuses,
                contacts,
                my_votes,
                attachments,
                transitions_map.get(i.id, []),
                advance_map.get(i.id),
                rank_map.get(i.id),
                merged_into_map.get(i.id),
                merged_count_map.get(i.id, 0),
            )
            for i in ideas
        ]

    def serialize_one(
        self,
        idea: Idea,
        voter_id: Optional[str] = None,
        *,
        tenant_id: Optional[str] = None,
        product_id: Optional[str] = None,
        actor: Optional[User] = None,
    ) -> IdeaOut:
        return self.serialize_many(
            [idea], voter_id, tenant_id=tenant_id, product_id=product_id, actor=actor
        )[0]

    def _resolve_maps(self, ideas: List[Idea]):
        """Batch-load the cross-schema references for a set of ideas (no N+1)."""
        product_ids = {i.product_id for i in ideas if i.product_id}
        status_ids = {i.status_id for i in ideas if i.status_id}
        contact_ids = {i.submitter_contact_id for i in ideas if i.submitter_contact_id}
        products = {
            p.id: p
            for p in self.db.query(Product).filter(Product.id.in_(product_ids)).all()
        } if product_ids else {}
        statuses = {
            s.id: s
            for s in self.db.query(Status).filter(Status.id.in_(status_ids)).all()
        } if status_ids else {}
        contacts = {
            c.id: c
            for c in self.db.query(Contact).filter(Contact.id.in_(contact_ids)).all()
        } if contact_ids else {}
        return products, statuses, contacts

    def list(
        self,
        tenant_id: str,
        *,
        search: Optional[str] = None,
        filter: str = "active",
        product_id: Optional[str] = None,
        voter_id: Optional[str] = None,
        include_test: bool = False,
        actor: Optional[User] = None,
    ) -> List[IdeaOut]:
        """Ideas for a tenant, rank order (priority ascending, then newest
        first). ``search`` matches problem/raw_text (case-insensitive);
        ``filter`` = ``active`` (non-archived statuses) | ``archived`` | ``all``.
        ``product_id`` (optional) additionally scopes to a single product -
        the canonical ideation scope (an idea belongs to a product, which
        belongs to a tenant); it ALSO scopes the returned ``rank`` (plan
        section 5). ``None`` = every product in the tenant (today's
        behaviour, unchanged). Always tenant-scoped first: the product filter
        never widens visibility across tenants.

        ``include_test`` (issue #1179): a console/``--say`` test turn writes a
        real Idea row flagged ``is_test`` - excluded here by default so it never
        shows on a real operator's list; pass ``True`` to see it too."""
        q = self.db.query(Idea).filter(
            Idea.tenant_id == tenant_id, Idea.merged_into_id.is_(None)
        )  # AC-94-02: survivors only, every filter mode
        if not include_test:
            q = q.filter(Idea.is_test.is_(False))
        if product_id:
            q = q.filter(Idea.product_id == product_id)
        if search:
            like = f"%{search.strip()}%"
            q = q.filter(Idea.problem.ilike(like) | Idea.raw_text.ilike(like))

        mode = (filter or "active").lower()
        if mode in ("active", "archived"):
            archived_ids = self._archived_status_ids(tenant_id)
            if mode == "active":
                if archived_ids:
                    q = q.filter(~Idea.status_id.in_(archived_ids))
            else:  # archived
                q = q.filter(Idea.status_id.in_(archived_ids)) if archived_ids else q.filter(False)

        ideas = q.order_by(
            Idea.priority.asc(), Idea.created_at.desc(), Idea.id.desc()
        ).all()
        return self.serialize_many(
            ideas, voter_id, tenant_id=tenant_id, product_id=product_id, actor=actor
        )

    def board(
        self,
        tenant_id: str,
        voter_id: Optional[str] = None,
        product_id: Optional[str] = None,
        include_test: bool = False,
        actor: Optional[User] = None,
    ) -> BoardOut:
        """The triage board (AC-A-33): ideas grouped into the board lifecycle
        columns in order, cards within a column ordered by priority ascending.
        Columns are the tenant's OWN status-engine rows (issue #94 plan
        section 6: never a hardcoded column list) - every non-
        initial, non-archived, active status, by ``sort_order`` (the "main
        path" rule also used by the public timeline). ``product_id``
        (optional) additionally scopes to a single product (the canonical
        ideation scope); ``None`` = every product in the tenant (unchanged).
        Always tenant-scoped first.

        ``include_test`` (issue #1179): off-board by default, same as ``list``."""
        tier = StatusRepository(self.db).resolve_tier(IDEA_ENTITY, tenant_id)
        tier_filter = (
            Status.tenant_id.is_(None) if tier is None else Status.tenant_id == tier
        )
        columns = (
            self.db.query(Status)
            .filter(
                Status.entity_type == IDEA_ENTITY,
                tier_filter,
                Status.is_initial.is_(False),
                Status.is_archived.is_(False),
                Status.is_active.is_(True),
            )
            .order_by(Status.sort_order.asc())
            .all()
        )
        status_ids = {s.id: s.key for s in columns}
        q = self.db.query(Idea).filter(
            Idea.tenant_id == tenant_id,
            Idea.merged_into_id.is_(None),  # AC-94-02: survivors only
            Idea.status_id.in_(list(status_ids.keys())) if status_ids else False,
        )
        if not include_test:
            q = q.filter(Idea.is_test.is_(False))
        if product_id:
            q = q.filter(Idea.product_id == product_id)
        ideas = (
            q.order_by(Idea.priority.asc(), Idea.created_at.desc(), Idea.id.desc())
            .all()
        )
        serialized = self.serialize_many(
            ideas, voter_id, tenant_id=tenant_id, product_id=product_id, actor=actor
        )
        grouped: Dict[str, List[IdeaOut]] = {s.key: [] for s in columns}
        for out in serialized:
            grouped.setdefault(out.status, []).append(out)
        return BoardOut(
            columns=[
                BoardColumnOut(
                    statusId=s.id,
                    key=s.key,
                    title=s.label,
                    color=s.color,
                    ideas=grouped.get(s.key, []),
                )
                for s in columns
            ]
        )

    def get(
        self,
        tenant_id: str,
        idea_id: str,
        voter_id: Optional[str] = None,
        *,
        product_id: Optional[str] = None,
        actor: Optional[User] = None,
    ) -> IdeaOut:
        idea = (
            self.db.query(Idea)
            .filter(Idea.id == idea_id, Idea.tenant_id == tenant_id)
            .first()
        )
        if idea is None:
            raise HTTPException(404, "Idea not found.")
        return self.serialize_one(
            idea, voter_id, tenant_id=tenant_id, product_id=product_id, actor=actor
        )

    def single_product_id(self, tenant_id: str, idea_ids: List[str]) -> str:
        """The product of the first of ``idea_ids`` (tenant-scoped) - the BR create
        rejects a mixed-product link set (422) itself. 422 when none resolve."""
        row = (
            self.db.query(Idea.product_id)
            .filter(Idea.tenant_id == tenant_id, Idea.id.in_(idea_ids or [""]))
            .order_by(Idea.created_at.asc(), Idea.id.asc())
            .first()
        )
        if row is None:
            raise HTTPException(422, "Select at least one idea to promote.")
        return row.product_id

    def merged_children(
        self,
        tenant_id: str,
        survivor_id: str,
        voter_id: Optional[str] = None,
        actor: Optional[User] = None,
    ) -> List[IdeaOut]:
        """The ideas merged into ``survivor_id`` (AC-94-03), oldest merge
        first. 404 if ``survivor_id`` itself is not in the tenant (whether or
        not it actually has any children - a plain idea just returns [])."""
        survivor = (
            self.db.query(Idea)
            .filter(Idea.id == survivor_id, Idea.tenant_id == tenant_id)
            .first()
        )
        if survivor is None:
            raise HTTPException(404, "Idea not found.")
        children = (
            self.db.query(Idea)
            .filter(Idea.tenant_id == tenant_id, Idea.merged_into_id == survivor_id)
            .order_by(Idea.merged_at.asc(), Idea.created_at.asc(), Idea.id.asc())
            .all()
        )
        return self.serialize_many(children, voter_id, tenant_id=tenant_id, actor=actor)
