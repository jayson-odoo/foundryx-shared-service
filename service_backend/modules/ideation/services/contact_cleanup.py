"""Capability handler ``contact.erase_cleanup@1`` (plan 56 C).

Omnichannel erases a contact and asks every provider holding a link to it to
let go through the capability seam. Ideation clears `ideas.submitter_contact_id`
and keeps the idea. Tenant scoped; never raises for an absent contact."""
from typing import Any, Dict

from sqlalchemy.orm import Session

from ..models import Idea


def detach_submitter(db: Session, tenant_id: str, payload: Dict[str, Any]) -> int:
    contact_id = payload.get("contactId")
    if not contact_id:
        return 0
    return (
        db.query(Idea)
        .filter(Idea.tenant_id == tenant_id, Idea.submitter_contact_id == contact_id)
        .update({Idea.submitter_contact_id: None}, synchronize_session=False)
    )
