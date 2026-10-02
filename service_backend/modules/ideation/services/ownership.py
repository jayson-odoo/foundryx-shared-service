"""Idea ownership (SS-IDEATION-OWN) - "is this idea the viewer's own?".

An idea belongs to a submitter identified by EITHER:

- ``Idea.submitter_crm_user_id`` - the host CRM user id (set by the chatbot
  one-shot create and the embed create), or
- the submitter contact's phone - ``Idea.submitter_contact_id`` → an omnichannel
  ``Contact`` in the SAME tenant whose ``phone`` matches the viewer's phone.

**Never by display name** (names collide; a name is not an identity). An identity
that is blank (or a phone with too few digits to be real) matches NOTHING, so a
``mine`` query without identity returns empty - it can never widen to "all".

Every query here is tenant-scoped (the contact lookup too - a phone match in
another tenant must never count).
"""
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set

from sqlalchemy import false, or_
from sqlalchemy.orm import Query, Session

from modules.omnichannel.models import Contact

from ..models import Idea

# A real E.164 number has 8-15 digits; anything shorter is junk, not an identity.
_MIN_PHONE_DIGITS = 6
_NON_DIGIT = re.compile(r"\D")


def phone_variants(phone: Optional[str]) -> List[str]:
    """The stored spellings a phone may have (``+60123…`` / ``60123…``), from any
    input formatting (spaces, dashes, parentheses). Empty when not a real phone."""
    digits = _NON_DIGIT.sub("", phone or "")
    if len(digits) < _MIN_PHONE_DIGITS:
        return []
    return [f"+{digits}", digits]


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
    def phones(self) -> List[str]:
        return phone_variants(self.phone)

    @property
    def is_empty(self) -> bool:
        return self.crm is None and not self.phones


def _contact_ids_for(db: Session, tenant_id: str, ident: SubmitterIdentity) -> List[str]:
    phones = ident.phones
    if not phones:
        return []
    return [
        cid
        for (cid,) in db.query(Contact.id)
        .filter(Contact.tenant_id == tenant_id, Contact.phone.in_(phones))
        .all()
    ]


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
