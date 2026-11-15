"""Personal feedback links (lane PUBLIC-IDEAS-BOARD).

A contact (dealer) opens the EXISTING idea portal with no login through a
personal link: ``/public/feedback/{token}`` on the shared-service frontend, or
``/feedback/{token}`` on the Sorento CRM public page that iframes it. Contract:
``documentation/plans/ideation/public-ideas-board/acceptance-criteria.md``.

Security model (owner 15 Nov):
- the token is ``secrets.token_urlsafe(32)`` (unguessable), stored, one live
  row per contact; staff cancel it (``revoked_at``) and the next link mints a
  fresh token (QD a: valid until cancelled, no expiry);
- the token lookup is the only cross-tenant read (the token IS the
  credential); the contact is then resolved WITH the link row's own
  ``tenant_id`` (polymorphic-stored-id rule), so a planted/stale row pointing
  at another tenant's contact resolves to nothing;
- what the token unlocks (read the board, upvote, comment) is enforced by the
  portal principal of kind ``contact`` in ``services/portal.py``.
"""
import re
import secrets
from datetime import datetime, timezone
from typing import Optional, Tuple
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.services.catalog_service import tenant_public_link_base
from modules.omnichannel.models import Contact

from ..models import Idea, IdeaContactLink
from .sinks import LINK_PLACEHOLDERS

# 32-64 URL-safe chars: ``token_urlsafe(32)`` is 43. Anything else is rejected
# before the database is touched.
LINK_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _contact(db: Session, tenant_id: str, contact_id: Optional[str]) -> Optional[Contact]:
    if not contact_id:
        return None
    return (
        db.query(Contact)
        .filter(Contact.id == contact_id, Contact.tenant_id == tenant_id)
        .first()
    )


def _live(db: Session, tenant_id: str, contact_id: str) -> Optional[IdeaContactLink]:
    return (
        db.query(IdeaContactLink)
        .filter(
            IdeaContactLink.tenant_id == tenant_id,
            IdeaContactLink.contact_id == contact_id,
            IdeaContactLink.revoked_at.is_(None),
        )
        .order_by(IdeaContactLink.created_at.asc())
        .first()
    )


def get_or_create_link(db: Session, tenant_id: str, contact_id: str) -> IdeaContactLink:
    """The contact's live link, minted on first use (flushed, never committed:
    the caller owns the transaction)."""
    row = _live(db, tenant_id, contact_id)
    if row is not None:
        return row
    for _ in range(5):
        row = IdeaContactLink(
            tenant_id=tenant_id,
            contact_id=contact_id,
            token=secrets.token_urlsafe(32),
            created_at=_now(),
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
            return row
        except IntegrityError:
            continue
    raise RuntimeError("Could not mint a unique feedback link after 5 attempts.")


def cancel_links_for_contact(db: Session, tenant_id: str, contact_id: str) -> int:
    """Cancel every live link of this contact (tenant-scoped). Returns how many
    were cancelled. Flushed, not committed."""
    rows = (
        db.query(IdeaContactLink)
        .filter(
            IdeaContactLink.tenant_id == tenant_id,
            IdeaContactLink.contact_id == contact_id,
            IdeaContactLink.revoked_at.is_(None),
        )
        .all()
    )
    now = _now()
    for row in rows:
        row.revoked_at = now
    db.flush()
    return len(rows)


def cancel_feedback_link_for_idea(db: Session, tenant_id: str, idea_id: str) -> bool:
    """Staff action: cancel the link of ``idea_id``'s submitter contact. False
    when the idea is not in ``tenant_id`` or has no same-tenant contact.
    Commits."""
    idea = db.query(Idea).filter(Idea.id == idea_id, Idea.tenant_id == tenant_id).first()
    contact = _contact(db, tenant_id, idea.submitter_contact_id) if idea is not None else None
    if contact is None:
        return False
    cancel_links_for_contact(db, tenant_id, contact.id)
    db.commit()
    return True


def resolve_link(db: Session, token: str) -> Optional[Tuple[IdeaContactLink, Contact]]:
    """``(link, contact)`` for a live link, else ``None`` (malformed, unknown,
    cancelled, or a contact that no longer exists in the link's tenant)."""
    if not LINK_TOKEN_RE.fullmatch(token or ""):
        return None
    row = db.query(IdeaContactLink).filter(IdeaContactLink.token == token).first()
    if row is None or row.revoked_at is not None:
        return None
    contact = _contact(db, row.tenant_id, row.contact_id)
    if contact is None:
        return None
    return row, contact


def resolve_link_by_id(db: Session, tenant_id: str, link_id: str) -> Optional[Tuple[IdeaContactLink, Contact]]:
    """Per-request re-check behind a portal token (tenant-scoped)."""
    row = (
        db.query(IdeaContactLink)
        .filter(IdeaContactLink.id == link_id, IdeaContactLink.tenant_id == tenant_id)
        .first()
    )
    if row is None or row.revoked_at is not None:
        return None
    contact = _contact(db, tenant_id, row.contact_id)
    if contact is None:
        return None
    return row, contact


def board_base(db: Session, tenant_id: str) -> str:
    """Where the board lives for this tenant. A tenant ``public_link_base_url``
    that is a TEMPLATE (``{token}``/``{ideaId}``) points at the Sorento CRM: the
    board is the CRM public page ``{origin}/feedback``. A plain tenant base (or
    none) is the shared-service frontend: ``{base}/public/feedback``."""
    tenant_base = tenant_public_link_base(db, tenant_id)
    if tenant_base and any(p in tenant_base for p in LINK_PLACEHOLDERS):
        parts = urlsplit(tenant_base)
        return f"{parts.scheme}://{parts.netloc}/feedback"
    return f"{(tenant_base or settings.frontend_url).rstrip('/')}/public/feedback"


def mint_board_link(db: Session, idea: Idea, contact_id: Optional[str] = None) -> Optional[str]:
    """The personal board link for ``contact_id`` (default: the idea's
    submitter contact), opening ``idea``. ``None`` when there is no contact in
    the idea's tenant. Mints the contact's link on first use (flush only)."""
    contact = _contact(db, idea.tenant_id, contact_id or idea.submitter_contact_id)
    if contact is None:
        return None
    link = get_or_create_link(db, idea.tenant_id, contact.id)
    url = f"{board_base(db, idea.tenant_id)}/{link.token}"
    return f"{url}/{idea.idea_number}" if idea.idea_number else url
