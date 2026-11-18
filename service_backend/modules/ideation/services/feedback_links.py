"""Personal feedback links (lane PUBLIC-IDEAS-BOARD).

A contact (dealer) opens the EXISTING idea portal with no login through a
personal link: ``/public/feedback/board/{token}`` on the shared-service frontend, or
``/feedback/board/{token}`` on the Sorento CRM public page that iframes it
(``/public/feedback/{statusToken}`` is the per-item status page after lane
FEEDBACK-RENAME, so the board has its own ``board`` segment). Contract:
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
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover
    from .history import HistoryActor
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.services.catalog_service import tenant_public_link_base
from modules.omnichannel.models import Contact

from ..db import IDEATION_SCHEMA
from ..models import Idea, IdeaContactLink
from .sinks import LINK_PLACEHOLDERS
from .numbering import display_idea_number

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


def _live(
    db: Session, tenant_id: str, contact_id: str, product_id: Optional[str] = None
) -> Optional[IdeaContactLink]:
    product = (
        IdeaContactLink.product_id.is_(None)
        if product_id is None
        else IdeaContactLink.product_id == product_id
    )
    return (
        db.query(IdeaContactLink)
        .filter(
            IdeaContactLink.tenant_id == tenant_id,
            IdeaContactLink.contact_id == contact_id,
            product,
            IdeaContactLink.revoked_at.is_(None),
        )
        .order_by(IdeaContactLink.created_at.asc())
        .first()
    )


def get_or_create_link(
    db: Session, tenant_id: str, contact_id: str, product_id: Optional[str] = None
) -> IdeaContactLink:
    """The contact's live link for ``product_id`` (lane SS-MULTI-PRODUCT-BOARD:
    one live link per contact per product; ``None`` = the whole-tenant board),
    minted on first use (flushed, never committed: the caller owns the
    transaction)."""
    row = _live(db, tenant_id, contact_id, product_id)
    if row is not None:
        return row
    for _ in range(5):
        row = IdeaContactLink(
            tenant_id=tenant_id,
            contact_id=contact_id,
            product_id=product_id,
            token=secrets.token_urlsafe(32),
            created_at=_now(),
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
            return row
        except IntegrityError:
            # A concurrent mint for the same contact won the one-live-link
            # index (``uq_idea_contact_links_live``): use its row. Otherwise a
            # (vanishingly unlikely) token collision: try a fresh token.
            existing = _live(db, tenant_id, contact_id, product_id)
            if existing is not None:
                return existing
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


def cancel_feedback_link_for_idea(
    db: Session, tenant_id: str, idea_id: str, actor: Optional["HistoryActor"] = None
) -> bool:
    """Staff action: cancel the links of ``idea_id``'s submitter contact AND
    every same-tenant contact with the same phone digits - one person, several
    workspace rows, and "My requests" spans all of them, so a sibling's link
    must die too (security review #2). False when the idea is not in
    ``tenant_id`` or has no same-tenant contact. Commits."""
    from .ownership import find_contacts_by_phone

    idea = db.query(Idea).filter(Idea.id == idea_id, Idea.tenant_id == tenant_id).first()
    contact = _contact(db, tenant_id, idea.submitter_contact_id) if idea is not None else None
    if contact is None:
        return False
    ids = {contact.id} | {c.id for c in find_contacts_by_phone(db, tenant_id, contact.phone)}
    for cid in sorted(ids):
        cancel_links_for_contact(db, tenant_id, cid)
    # The item's History tab (lane FEEDBACK-SUBSCRIBE, crew pass 5441b840).
    from . import history
    from .followers import contact_name

    history.record(
        db, tenant_id, idea.id, history.ACTION_LINK_CANCELLED, actor or history.HistoryActor(),
        from_value=contact_name(contact),
    )
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


def feedback_base(db: Session, tenant_id: str) -> str:
    """Where the public feedback pages live for this tenant. A tenant
    ``public_link_base_url`` that is a TEMPLATE (``{token}``/``{ideaId}``)
    points at the Sorento CRM: ``{origin}/feedback``. A plain tenant base (or
    none) is the shared-service frontend: ``{base}/public/feedback``.
    Pages the CRM does not frame (the share page) use ``ss_feedback_base``;
    keep the two base rules in step."""
    tenant_base = tenant_public_link_base(db, tenant_id)
    if tenant_base and any(p in tenant_base for p in LINK_PLACEHOLDERS):
        parts = urlsplit(tenant_base)
        return f"{parts.scheme}://{parts.netloc}/feedback"
    return f"{(tenant_base or settings.frontend_url).rstrip('/')}/public/feedback"


def ss_feedback_base(db: Session, tenant_id: str) -> str:
    """The shared-service frontend's own public feedback pages
    (``{base}/public/feedback``), for pages only this frontend serves (the
    read-only share page, lane FEEDBACK-SHARE-LIVE-FIX). A TEMPLATE tenant base
    points at the product's CRM, which has no share page, so it falls back to
    ``settings.frontend_url``; a plain tenant base IS this frontend."""
    tenant_base = tenant_public_link_base(db, tenant_id)
    if tenant_base and any(p in tenant_base for p in LINK_PLACEHOLDERS):
        tenant_base = None
    return f"{(tenant_base or settings.frontend_url).rstrip('/')}/public/feedback"


def board_base(db: Session, tenant_id: str) -> str:
    """Where the board lives for this tenant (``feedback_base`` + ``/board``)."""
    return f"{feedback_base(db, tenant_id)}/board"


def _owns_test_item(db: Session, idea: Idea, contact_id: str) -> bool:
    """True when ``contact_id``'s person (same-phone siblings, never by name -
    the board's own ``_owned_q`` rule) submitted the item the board opens for
    ``idea``: the idea itself, or its survivor when merged."""
    from .ownership import person_contact_ids

    opened = idea
    if idea.merged_into_id:
        opened = (
            db.query(Idea)
            .filter(Idea.id == idea.merged_into_id, Idea.tenant_id == idea.tenant_id)
            .first()
        )
    if opened is None or not opened.submitter_contact_id:
        return False
    return opened.submitter_contact_id in person_contact_ids(db, idea.tenant_id, contact_id)


# Sentinel: "the idea's own submitter contact". Distinct from an explicit
# ``None`` (a recipient with no contact), which must NEVER fall back to the
# idea's submitter - that would hand the author's personal link to whoever is
# being replied to (review B1).
SUBMITTER = object()


def mint_board_link(db: Session, idea: Idea, contact_id: object = SUBMITTER) -> Optional[str]:
    """The personal board link for ``contact_id`` (default: the idea's own
    submitter contact), opening ``idea``. ``None`` when that recipient has no
    contact in the idea's tenant. Mints the contact's link on first use (flush
    only).

    A test idea (Chatbot Console filing, ``is_test``) gets the link like a real
    filing (owner 17 Nov, lane FEEDBACK-TEST-BOARD-LINK): the reporter's own
    board lists their own test items, nobody else's does
    (``portal.IdeaPortalService._visible``). So a test idea's link goes only
    to the person who owns the item the board would open (its survivor when
    merged); anyone else would land on a "not found" page and gets ``None``
    (the per-idea status page applies)."""
    target = idea.submitter_contact_id if contact_id is SUBMITTER else contact_id
    contact = _contact(db, idea.tenant_id, target if isinstance(target, str) else None)
    if contact is None:
        return None
    if idea.is_test and not _owns_test_item(db, idea, contact.id):
        return None
    # The link opens the board of the item's product (lane
    # SS-MULTI-PRODUCT-BOARD): that board shows only that product.
    link = get_or_create_link(db, idea.tenant_id, contact.id, idea.product_id)
    url = f"{board_base(db, idea.tenant_id)}/{link.token}"
    # The URL carries the number as users read it (FB-0016), never "idea".
    return f"{url}/{display_idea_number(idea.idea_number)}" if idea.idea_number else url


def backfill_link_products_sql(schema: str) -> str:
    """Stamp a product on live links minted before links carried one (lane
    SS-MULTI-PRODUCT-BOARD, owner Q2 a): when every item the link's contact
    submitted belongs to ONE product, the link becomes that product's board; a
    contact with items on several products (or none) keeps the whole-tenant
    board, as before. Read with the link's own tenant. Skips a link whose
    contact already holds a live link for that product (the
    one-live-link-per-product index). Idempotent. One statement, valid on
    Postgres (migration 0022) and SQLite (tests)."""
    links = f'"{schema}".idea_contact_links'
    ideas = f'"{schema}".ideas'
    mine = (
        f"FROM {ideas} i WHERE i.tenant_id = idea_contact_links.tenant_id "
        "AND i.submitter_contact_id = idea_contact_links.contact_id "
        "AND i.product_id IS NOT NULL"
    )
    return (
        f"UPDATE {links} SET product_id = (SELECT MIN(i.product_id) {mine}) "
        "WHERE product_id IS NULL AND revoked_at IS NULL "
        f"AND (SELECT COUNT(DISTINCT i.product_id) {mine}) = 1 "
        f"AND NOT EXISTS (SELECT 1 FROM {links} o "
        "WHERE o.tenant_id = idea_contact_links.tenant_id "
        "AND o.contact_id = idea_contact_links.contact_id "
        "AND o.revoked_at IS NULL "
        f"AND o.product_id = (SELECT MIN(i.product_id) {mine}))"
    )


def backfill_link_products(db: Session, schema: str = IDEATION_SCHEMA) -> int:
    """Run :func:`backfill_link_products_sql` on ``db`` (no commit). Returns how
    many links were stamped."""
    from sqlalchemy import text

    return db.execute(text(backfill_link_products_sql(schema))).rowcount
