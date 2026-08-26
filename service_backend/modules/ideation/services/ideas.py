"""Idea read service (AC-A-12) - list + detail, serialized to the FE Idea shape.

Reads are tenant-scoped. The Idea's ``product_id`` / ``status_id`` /
``submitter_contact_id`` are cross-schema FKs; this service resolves them to
human-readable values (product name, status key, submitter name) so the UI never
renders a raw UUID (cursor rule). Attachments are an always-present (currently
empty) section - the attachment writer lands with the create_idea slice.
"""
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.models.status import Status
from modules.omnichannel.models import Contact

from ..models import Idea, IdeaAttachment, IdeaVote
from ..schemas import BoardColumnOut, BoardOut, IdeaAttachmentOut, IdeaOut

# Idea lifecycle keys whose statuses are "archived" (terminal off-ramps + closed).
# The active board shows non-archived ideas; the archived filter shows the rest.
_ARCHIVED_KEYS = {"closed", "duplicate", "rejected", "archived"}

# Triage board columns (key, title) in lifecycle order - mirrors the FE
# ``IDEA_BOARD_COLUMNS`` (types/ideation.ts) byte-for-byte. Only these statuses
# appear on the board; archived / terminal ideas are off-board (AC-A-33).
BOARD_COLUMNS: List[tuple] = [
    ("captured", "New"),
    ("triaged", "Triaged"),
    ("linked", "Linked to BR"),
    ("building", "Building"),
    ("delivered", "Delivered"),
]


def _submitter_name(contact: Optional[Contact]) -> str:
    if contact is None:
        return "Unknown"
    name = " ".join(p for p in (contact.first_name, contact.last_name) if p).strip()
    return name or "Unknown"


class IdeaReadService:
    def __init__(self, db: Session):
        self.db = db

    def _serialize(
        self,
        idea: Idea,
        products: Dict[str, Product],
        statuses: Dict[str, Status],
        contacts: Dict[str, Contact],
        my_votes: Optional[Dict[str, str]] = None,
        attachments: Optional[Dict[str, List[IdeaAttachmentOut]]] = None,
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
            problem=idea.problem,
            proposedSolution=idea.proposed_solution,
            impact=idea.impact,
            department=idea.department,
            rawText=idea.raw_text or "",
            source=idea.source,
            submitterName=submitter,
            upvotes=idea.upvotes or 0,
            downvotes=idea.downvotes or 0,
            myVote=my_vote if my_vote in ("up", "down") else None,
            priority=idea.priority or 0,
            attachments=idea_attachments,
            createdAt=idea.created_at,
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
            .filter(IdeaAttachment.idea_id.in_(idea_ids))
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
                )
            )
        return out

    def serialize_many(
        self, ideas: List[Idea], voter_id: Optional[str] = None
    ) -> List[IdeaOut]:
        products, statuses, contacts = self._resolve_maps(ideas)
        my_votes = self._my_votes(ideas, voter_id)
        attachments = self._attachments_by_idea(ideas)
        return [
            self._serialize(i, products, statuses, contacts, my_votes, attachments)
            for i in ideas
        ]

    def serialize_one(self, idea: Idea, voter_id: Optional[str] = None) -> IdeaOut:
        return self.serialize_many([idea], voter_id)[0]

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
    ) -> List[IdeaOut]:
        """Ideas for a tenant, newest first. ``search`` matches problem/raw_text
        (case-insensitive); ``filter`` = ``active`` (non-archived statuses) |
        ``archived`` | ``all``. ``product_id`` (optional) additionally scopes to a
        single product - the canonical ideation scope (an idea belongs to a
        product, which belongs to a tenant). ``None`` = every product in the
        tenant (today's behaviour, unchanged). Always tenant-scoped first: the
        product filter never widens visibility across tenants."""
        q = self.db.query(Idea).filter(Idea.tenant_id == tenant_id)
        if product_id:
            q = q.filter(Idea.product_id == product_id)
        if search:
            like = f"%{search.strip()}%"
            q = q.filter(Idea.problem.ilike(like) | Idea.raw_text.ilike(like))

        mode = (filter or "active").lower()
        if mode in ("active", "archived"):
            archived_ids = [
                s.id
                for s in self.db.query(Status)
                .filter(Status.entity_type == "idea", Status.key.in_(_ARCHIVED_KEYS))
                .all()
            ]
            if mode == "active":
                if archived_ids:
                    q = q.filter(~Idea.status_id.in_(archived_ids))
            else:  # archived
                q = q.filter(Idea.status_id.in_(archived_ids)) if archived_ids else q.filter(False)

        ideas = q.order_by(Idea.created_at.desc(), Idea.id.desc()).all()
        return self.serialize_many(ideas, voter_id)

    def board(
        self,
        tenant_id: str,
        voter_id: Optional[str] = None,
        product_id: Optional[str] = None,
    ) -> BoardOut:
        """The triage board (AC-A-33): ideas grouped into the board lifecycle
        columns in order, cards within a column ordered by priority ascending.
        Only board-lifecycle statuses appear - archived / terminal ideas are
        off-board. ``product_id`` (optional) additionally scopes to a single
        product (the canonical ideation scope); ``None`` = every product in the
        tenant (unchanged). Always tenant-scoped first."""
        board_keys = [k for k, _ in BOARD_COLUMNS]
        status_ids = {
            s.id: s.key
            for s in self.db.query(Status)
            .filter(Status.entity_type == "idea", Status.key.in_(board_keys))
            .all()
        }
        q = self.db.query(Idea).filter(
            Idea.tenant_id == tenant_id,
            Idea.status_id.in_(list(status_ids.keys())) if status_ids else False,
        )
        if product_id:
            q = q.filter(Idea.product_id == product_id)
        ideas = (
            q.order_by(Idea.priority.asc(), Idea.created_at.desc(), Idea.id.desc())
            .all()
        )
        serialized = self.serialize_many(ideas, voter_id)
        grouped: Dict[str, List[IdeaOut]] = {k: [] for k, _ in BOARD_COLUMNS}
        for out in serialized:
            grouped.setdefault(out.status, []).append(out)
        return BoardOut(
            columns=[
                BoardColumnOut(key=key, title=title, ideas=grouped.get(key, []))
                for key, title in BOARD_COLUMNS
            ]
        )

    def get(self, tenant_id: str, idea_id: str, voter_id: Optional[str] = None) -> IdeaOut:
        idea = (
            self.db.query(Idea)
            .filter(Idea.id == idea_id, Idea.tenant_id == tenant_id)
            .first()
        )
        if idea is None:
            raise HTTPException(404, "Idea not found.")
        return self.serialize_one(idea, voter_id)
