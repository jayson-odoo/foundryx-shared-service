"""Read-only share link of one feedback item (lane FEEDBACK-SUBSCRIBE).

Owner 17 Nov: "generate a general share link, then if they want to like
subscribe or comment or do anything, we prompt something to ask for their
phone number". The link carries no person: it opens the item read-only for
anyone (``portal.IdeaPortalService`` with a ``share`` principal that can never
write). Contract: ``documentation/plans/ideation/feedback-subscribe-behaviour-card.md``.

- token = ``secrets.token_urlsafe(32)``, one live row per item, valid until
  staff "Stop sharing" (``revoked_at``); the next Share mints a fresh token;
- the token lookup is the only cross-tenant read (the token IS the
  credential); the idea is then resolved WITH the row's own ``tenant_id``;
- test items are never shared.
Writes flush; the caller commits.
"""
import secrets
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Idea, IdeaShareLink
from . import history
from .history import HistoryActor
from .feedback_links import LINK_TOKEN_RE, feedback_base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _live(db: Session, tenant_id: str, idea_id: str) -> Optional[IdeaShareLink]:
    return (
        db.query(IdeaShareLink)
        .filter(
            IdeaShareLink.tenant_id == tenant_id,
            IdeaShareLink.idea_id == idea_id,
            IdeaShareLink.revoked_at.is_(None),
        )
        .first()
    )


def get_or_create_share_link(
    db: Session, idea: Idea, actor: Optional[HistoryActor] = None
) -> Optional[IdeaShareLink]:
    """The item's live share link, minted on first use (recorded in the item's
    History as "Share link created" by ``actor``). ``None`` for a test item
    (never shared). Flush only."""
    if idea.is_test:
        return None
    row = _live(db, idea.tenant_id, idea.id)
    if row is not None:
        return row
    for _ in range(5):
        row = IdeaShareLink(
            tenant_id=idea.tenant_id,
            idea_id=idea.id,
            token=secrets.token_urlsafe(32),
            created_at=_now(),
        )
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
            if actor is not None:
                history.record(db, idea.tenant_id, idea.id, history.ACTION_SHARE_CREATED, actor)
            return row
        except IntegrityError:
            existing = _live(db, idea.tenant_id, idea.id)
            if existing is not None:
                return existing
    raise RuntimeError("Could not mint a unique share link after 5 attempts.")


def share_url(db: Session, row: IdeaShareLink) -> str:
    return f"{feedback_base(db, row.tenant_id)}/share/{row.token}"


def stop_sharing(db: Session, tenant_id: str, idea_id: str) -> int:
    """Cancel the item's live share link(s). Flush only."""
    rows = (
        db.query(IdeaShareLink)
        .filter(
            IdeaShareLink.tenant_id == tenant_id,
            IdeaShareLink.idea_id == idea_id,
            IdeaShareLink.revoked_at.is_(None),
        )
        .all()
    )
    now = _now()
    for row in rows:
        row.revoked_at = now
    db.flush()
    return len(rows)


def resolve_share(db: Session, token: str) -> Optional[Tuple[IdeaShareLink, Idea]]:
    """``(link, idea)`` for a live share token, else ``None`` (malformed,
    unknown, cancelled, a test item, or an idea no longer in the link's
    tenant)."""
    if not LINK_TOKEN_RE.fullmatch(token or ""):
        return None
    row = db.query(IdeaShareLink).filter(IdeaShareLink.token == token).first()
    if row is None or row.revoked_at is not None:
        return None
    idea = (
        db.query(Idea)
        .filter(Idea.id == row.idea_id, Idea.tenant_id == row.tenant_id)
        .first()
    )
    if idea is None or idea.is_test:
        return None
    return row, idea


# ── operator idea page (staff) ────────────────────────────────────────────────


def staff_share_url(db: Session, tenant_id: str, idea_id: str, actor: HistoryActor) -> Optional[str]:
    """The item's share link (minted on first use), ``None`` when the idea is
    not in the tenant or is a test item. Commits."""
    idea = db.query(Idea).filter(Idea.id == idea_id, Idea.tenant_id == tenant_id).first()
    row = get_or_create_share_link(db, idea, actor) if idea is not None else None
    if row is None:
        return None
    db.commit()
    return share_url(db, row)


def staff_stop_sharing(db: Session, tenant_id: str, idea_id: str, actor: HistoryActor) -> bool:
    """"Stop sharing" (R12). False when the idea is not in the tenant. Commits."""
    exists = db.query(Idea.id).filter(Idea.id == idea_id, Idea.tenant_id == tenant_id).first()
    if exists is None:
        return False
    if stop_sharing(db, tenant_id, idea_id):
        history.record(db, tenant_id, idea_id, history.ACTION_SHARE_STOPPED, actor)
    db.commit()
    return True
