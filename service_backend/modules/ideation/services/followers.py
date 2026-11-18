"""Followers of a feedback item (lane FEEDBACK-SUBSCRIBE).

A follower gets the same WhatsApp status update as the submitter, with their
own board link (``status_events`` writes one feed row per follower). Contract:
``documentation/plans/ideation/feedback-subscribe-behaviour-card.md``.

Rules kept here:
- the submitter is always followed and never has a row (R8);
- a row's ``contact_id`` is ALWAYS resolved with the row's own tenant (the
  polymorphic stored-id rule), so a planted foreign id resolves to nothing;
- a merged item keeps its rows; whoever reads followers of a survivor also
  reads its merged children's (R10), so merge/unmerge need no bookkeeping;
- test items cannot be followed (R12).

Writes flush; the caller (router/service) commits.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modules.omnichannel.models import Contact

from ..models import Idea, IdeaFollower
from . import history
from .history import HistoryActor


class FollowError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def contact_name(contact: Optional[Contact]) -> Optional[str]:
    """A contact as people read it (first + last name), never its id."""
    if contact is None:
        return None
    name = " ".join(p for p in (contact.first_name, getattr(contact, "last_name", None)) if p)
    return name or contact.phone or None


def contact_name_by_id(db: Session, tenant_id: str, contact_id: str) -> Optional[str]:
    return contact_name(
        db.query(Contact).filter(Contact.id == contact_id, Contact.tenant_id == tenant_id).first()
    )


def _idea_and_children_ids(db: Session, tenant_id: str, idea_id: str) -> List[str]:
    ids = [idea_id]
    ids.extend(
        cid
        for (cid,) in db.query(Idea.id).filter(
            Idea.tenant_id == tenant_id, Idea.merged_into_id == idea_id
        )
    )
    return ids


def follow(
    db: Session,
    tenant_id: str,
    idea: Idea,
    contact_id: str,
    *,
    added_by_user_id: Optional[str] = None,
) -> bool:
    """Idempotent: an existing row is kept (returns False). 422 when the
    contact is not in the idea's tenant; 404 for a test item. True when a row
    was added."""
    if idea.tenant_id != tenant_id:
        raise FollowError(404, "not_found", "Feedback not found.")
    if idea.is_test:
        raise FollowError(409, "test_item", "Test items cannot be followed.")
    contact = (
        db.query(Contact.id)
        .filter(Contact.id == contact_id, Contact.tenant_id == tenant_id)
        .first()
    )
    if contact is None:
        raise FollowError(422, "unknown_contact", "Choose a contact of this workspace.")
    # The submitter (or a same-phone sibling contact of theirs) already gets
    # every update and never has a row (R8; crew pass 70e96f2b).
    from .ownership import person_contact_ids

    person = person_contact_ids(db, tenant_id, contact_id)
    submitted = (
        db.query(Idea.id)
        .filter(
            Idea.tenant_id == tenant_id,
            Idea.id.in_(_idea_and_children_ids(db, tenant_id, idea.id)),
            Idea.submitter_contact_id.in_(person),
        )
        .first()
    )
    if submitted is not None:
        raise FollowError(
            422, "already_submitter", "This contact raised the request and already gets its updates."
        )
    exists = (
        db.query(IdeaFollower.id)
        .filter(
            IdeaFollower.tenant_id == tenant_id,
            IdeaFollower.idea_id == idea.id,
            IdeaFollower.contact_id == contact_id,
        )
        .first()
    )
    if exists is not None:
        return False
    try:
        with db.begin_nested():
            db.add(
                IdeaFollower(
                    tenant_id=tenant_id,
                    idea_id=idea.id,
                    contact_id=contact_id,
                    added_by_user_id=added_by_user_id,
                )
            )
            db.flush()
        return True
    except IntegrityError:
        # A concurrent follow won ``uq_idea_follower_contact``: same outcome.
        return False


def unfollow(db: Session, tenant_id: str, idea_id: str, contact_ids: Sequence[str]) -> int:
    """Remove the follow of every contact id of this person on the item and on
    its merged children (the survivor's page is where they unfollow it)."""
    if not contact_ids:
        return 0
    removed = db.query(IdeaFollower).filter(
        IdeaFollower.tenant_id == tenant_id,
        IdeaFollower.idea_id.in_(_idea_and_children_ids(db, tenant_id, idea_id)),
        IdeaFollower.contact_id.in_(list(contact_ids)),
    ).delete(synchronize_session=False)
    db.flush()
    return int(removed or 0)


def follower_count(db: Session, tenant_id: str, idea_id: str) -> int:
    """Distinct contacts following the item or one of its merged children."""
    return int(
        db.query(func.count(func.distinct(IdeaFollower.contact_id)))
        .filter(
            IdeaFollower.tenant_id == tenant_id,
            IdeaFollower.idea_id.in_(_idea_and_children_ids(db, tenant_id, idea_id)),
        )
        .scalar()
        or 0
    )


def is_following(db: Session, tenant_id: str, idea_id: str, contact_ids: Sequence[str]) -> bool:
    """True when this person (all their same-phone contact ids) submitted the
    item or one of its merged children, or follows any of them."""
    if not contact_ids:
        return False
    ids = _idea_and_children_ids(db, tenant_id, idea_id)
    contact_ids = list(contact_ids)
    submitted = (
        db.query(Idea.id)
        .filter(
            Idea.tenant_id == tenant_id,
            Idea.id.in_(ids),
            Idea.submitter_contact_id.in_(contact_ids),
        )
        .first()
    )
    if submitted is not None:
        return True
    return (
        db.query(IdeaFollower.id)
        .filter(
            IdeaFollower.tenant_id == tenant_id,
            IdeaFollower.idea_id.in_(ids),
            IdeaFollower.contact_id.in_(contact_ids),
        )
        .first()
        is not None
    )


def followers_of(db: Session, tenant_id: str, ideas: Iterable[Idea]) -> List[Tuple[Idea, Contact]]:
    """``(idea, contact)`` for every follower row of ``ideas`` whose contact
    resolves IN ``tenant_id`` (planted foreign ids drop out), oldest first.
    One query for the rows, one for the contacts."""
    by_id = {i.id: i for i in ideas}
    if not by_id:
        return []
    rows = (
        db.query(IdeaFollower)
        .filter(IdeaFollower.tenant_id == tenant_id, IdeaFollower.idea_id.in_(list(by_id)))
        .order_by(IdeaFollower.created_at.asc(), IdeaFollower.id.asc())
        .all()
    )
    contacts = {
        c.id: c
        for c in db.query(Contact).filter(
            Contact.tenant_id == tenant_id,
            Contact.id.in_({r.contact_id for r in rows} or {"-"}),
        )
    }
    return [(by_id[r.idea_id], contacts[r.contact_id]) for r in rows if r.contact_id in contacts]


def list_for_staff(db: Session, tenant_id: str, idea_id: str) -> List[Dict[str, Any]]:
    """The followers list on the operator idea detail (R9): the item's own rows
    and its merged children's, one entry per contact."""
    ids = _idea_and_children_ids(db, tenant_id, idea_id)
    ideas = db.query(Idea).filter(Idea.tenant_id == tenant_id, Idea.id.in_(ids)).all()
    out: Dict[str, Dict[str, Any]] = {}
    rows = {
        (r.idea_id, r.contact_id): r
        for r in db.query(IdeaFollower).filter(
            IdeaFollower.tenant_id == tenant_id, IdeaFollower.idea_id.in_(ids)
        )
    }
    for idea, contact in followers_of(db, tenant_id, ideas):
        if contact.id in out:
            continue
        row = rows[(idea.id, contact.id)]
        name = contact_name(contact)
        out[contact.id] = {
            "contactId": contact.id,
            "name": name or None,
            "phone": contact.phone,
            "addedByStaff": bool(row.added_by_user_id),
            "createdAt": row.created_at,
        }
    return list(out.values())


def remove_for_staff(db: Session, tenant_id: str, idea_id: str, contact_id: str) -> None:
    unfollow(db, tenant_id, idea_id, [contact_id])



# ── operator idea page (staff, R9) ────────────────────────────────────────────


def _idea_in_tenant(db: Session, tenant_id: str, idea_id: str) -> Idea:
    idea = db.query(Idea).filter(Idea.id == idea_id, Idea.tenant_id == tenant_id).first()
    if idea is None:
        raise FollowError(404, "not_found", "Idea not found.")
    return idea


def staff_list(db: Session, tenant_id: str, idea_id: str) -> List[Dict[str, Any]]:
    _idea_in_tenant(db, tenant_id, idea_id)
    return list_for_staff(db, tenant_id, idea_id)


def staff_add(
    db: Session, tenant_id: str, idea_id: str, contact_id: str, user_id: str, actor: HistoryActor
) -> List[Dict[str, Any]]:
    """Add a follower (idempotent) and return the list. Commits."""
    idea = _idea_in_tenant(db, tenant_id, idea_id)
    if follow(db, tenant_id, idea, contact_id, added_by_user_id=user_id):
        history.record(
            db, tenant_id, idea.id, history.ACTION_FOLLOWER_ADDED, actor,
            to_value=contact_name_by_id(db, tenant_id, contact_id),
        )
    db.commit()
    return list_for_staff(db, tenant_id, idea_id)


def staff_remove(db: Session, tenant_id: str, idea_id: str, contact_id: str, actor: HistoryActor) -> None:
    """Remove a follower (idempotent). Commits."""
    _idea_in_tenant(db, tenant_id, idea_id)
    if unfollow(db, tenant_id, idea_id, [contact_id]):
        history.record(
            db, tenant_id, idea_id, history.ACTION_FOLLOWER_REMOVED, actor,
            from_value=contact_name_by_id(db, tenant_id, contact_id),
        )
    db.commit()
