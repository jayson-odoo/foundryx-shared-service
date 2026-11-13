"""Idea ownership (SS-IDEATION-OWN) - "is this idea the viewer's own?".

An idea belongs to a submitter identified by EITHER:

- ``Idea.submitter_crm_user_id`` - the host CRM user id (set by the chatbot
  one-shot create and the embed create), or
- the submitter contact's phone - ``Idea.submitter_contact_id`` → an omnichannel
  ``Contact`` in the SAME tenant whose ``phone`` matches the viewer's phone.

**Never by display name** (names collide; a name is not an identity). Phones compare
on their normalized digits (``Contact.phone_digits``), so any formatting on
either side matches. An identity that is blank (or a phone with fewer than 8
digits) matches NOTHING, so a
``mine`` query without identity returns empty - it can never widen to "all".

Every query here is tenant-scoped (the contact lookup too - a phone match in
another tenant must never count).
"""
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set

from sqlalchemy import false, or_
from sqlalchemy.orm import Query, Session

from modules.omnichannel.models import Contact
from modules.omnichannel.phone import digits_only

from ..models import Idea

# A real E.164 number carries 8-15 digits; anything shorter is not an identity
# (it could only ever match junk contact rows).
_MIN_PHONE_DIGITS = 8


def phone_digits(phone: Optional[str]) -> str:
    """The normalized digits of ``phone`` (omnichannel's ONE ``digits_only``,
    the same normalization behind ``Contact.phone_digits``), or ``""`` when it
    is too short to be a real number. ``""`` is never a wildcard."""
    digits = digits_only(phone)
    return digits if len(digits) >= _MIN_PHONE_DIGITS else ""


def find_contacts_by_phone(db: Session, tenant_id: str, phone: Optional[str]) -> List[Contact]:
    """This tenant's contacts whose phone normalizes to the same digits, in id
    order. Indexed match on ``phone_digits``, plus the same legacy fallback
    ``ContactRepository.find_by_phone_digits`` uses for rows not stamped yet
    (``phone_digits IS NULL``) - tenant-wide, since ideas are tenant-wide."""
    digits = phone_digits(phone)
    if not digits:
        return []
    exact = (
        db.query(Contact)
        .filter(Contact.tenant_id == tenant_id, Contact.phone_digits == digits)
        .all()
    )
    legacy = [
        c
        for c in db.query(Contact)
        .filter(
            Contact.tenant_id == tenant_id,
            Contact.phone_digits.is_(None),
            Contact.phone.isnot(None),
        )
        .all()
        if digits_only(c.phone) == digits
    ]
    return sorted(exact + legacy, key=lambda c: c.id)


@dataclass(frozen=True)
class SubmitterIdentity:
    """Who "me" is. Both parts optional; neither = owns nothing."""

    crm_user_id: Optional[str] = None
    phone: Optional[str] = None

    @property
    def crm(self) -> Optional[str]:
        value = (self.crm_user_id or "").strip()
        return value or None

    @property
    def digits(self) -> str:
        return phone_digits(self.phone)

    @property
    def is_empty(self) -> bool:
        return self.crm is None and not self.digits


def _contact_ids_for(db: Session, tenant_id: str, ident: SubmitterIdentity) -> List[str]:
    if not ident.digits:
        return []
    return [c.id for c in find_contacts_by_phone(db, tenant_id, ident.phone)]


def owned_filter(db: Session, q: Query, tenant_id: str, ident: SubmitterIdentity) -> Query:
    """Narrow an ``Idea`` query to the identity's own ideas (tenant-scoped).
    An empty identity narrows to nothing."""
    clauses = []
    if ident.crm:
        clauses.append(Idea.submitter_crm_user_id == ident.crm)
    contact_ids = _contact_ids_for(db, tenant_id, ident)
    if contact_ids:
        clauses.append(Idea.submitter_contact_id.in_(contact_ids))
    if not clauses:
        return q.filter(false())
    return q.filter(Idea.tenant_id == tenant_id, or_(*clauses))


def owned_ids(
    db: Session, tenant_id: str, idea_ids: Iterable[str], ident: Optional[SubmitterIdentity]
) -> Set[str]:
    """The subset of ``idea_ids`` owned by ``ident`` (one query, no N+1)."""
    ids = [i for i in idea_ids if i]
    if not ids or ident is None or ident.is_empty:
        return set()
    q = db.query(Idea.id).filter(Idea.id.in_(ids))
    return {iid for (iid,) in owned_filter(db, q, tenant_id, ident).all()}


def merged_child_ids(db: Session, tenant_id: str, idea_id: str) -> List[str]:
    """Ids of the ideas merged into ``idea_id`` (tenant-scoped) - unmerging a
    survivor touches all of them, so the owner gate must cover them too."""
    return [
        cid
        for (cid,) in db.query(Idea.id).filter(
            Idea.tenant_id == tenant_id, Idea.merged_into_id == idea_id
        )
    ]
