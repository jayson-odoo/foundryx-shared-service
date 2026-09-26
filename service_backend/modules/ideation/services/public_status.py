"""Public idea-status lookup (S5, AC-1601..1604; widened by issue #90's
AC-90-1xx into a full page) - the DB query lives HERE, never in the router
(layering hard-fail). ``resolve(token)`` returns ``None`` for every
non-servable case - unknown/malformed token, still-draft idea, or a tenant
whose sign-in is blocked (status-engine ``blocks_access``/``is_archived``,
review round 1 nit 9) - so the router can answer a UNIFORM 404 with no
enumeration (mirrors ``FormService._resolve_public``).

Lookup is by ``status_token`` alone, across EVERY tenant (the token is the
credential, not a tenant-scoped lookup) - deliberate exception to the "every
repository query is tenant-scoped" rule, matching the analogous public
document-share route. Every OTHER read this service does (Product, Contact,
the status set) is scoped by the idea row's OWN ``tenant_id`` - never a
client-supplied value (the polymorphic-stored-id rule; a stale/forked
product or contact id must resolve to nothing, never another tenant's data,
AC-90-107).

Timeline (AC-90-102/103): built from the tenant's own status set
(``StatusRepository.list_for_entity``, ordered by ``sort_order``), never a
hardcoded key sequence and never ``category``. The "main path" is every
non-initial, non-archived status. When the idea's current status IS on the
main path, steps before it are ``done``, it is ``current``, steps after are
``upcoming``. When the current status is an off-ramp (``is_archived``, e.g.
Rejected/Duplicate/Closed) - or otherwise not found on the main path, such as
a status set that changed tier after the idea was set - the timeline is kept
truthfully short: ``[first main-path step done, current status current]``.
There is no status-history table (BL-SS-279), so this is the most truthful
statement obtainable without fabricating a position the idea never passed.
"""
import re
import unicodedata
from typing import Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.models.status import Status
from app.models.tenant import Tenant
from app.repositories.status_repository import StatusRepository

from ..models import Idea
from ..schemas import PublicIdeaStatusOut, PublicIdeaTimelineStepOut
from .statuses import IDEA_ENTITY

# 16-64 chars, URL-safe - matches ``secrets.token_urlsafe(24)`` output shape
# (AC-1603). Anything outside this shape is rejected before ever touching the
# database (also closes off path-traversal-flavoured tokens).
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")

# "What happens next" copy (AC-90-108), keyed by the PLATFORM status key (a
# tenant fork copies keys verbatim, so this is a display lookup only, never a
# behaviour branch on a tenant-added key). Tenant-editable copy is deferred
# (BL-SS-277). Plain, hyphen-free, never "Foundryx" (white-label).
PUBLIC_NEXT_STEP: Dict[str, str] = {
    "captured": "Your idea is in. The team will review it soon.",
    "triaged": "The team has reviewed your idea and is deciding where it fits.",
    "linked": "Your idea is now part of a planned requirement.",
    "building": "Your idea is being built.",
    "delivered": "Your idea has been delivered.",
    "closed": "This idea is complete. Thank you.",
    "duplicate": "A similar idea already exists, so this one was merged into it.",
    "rejected": "This idea will not go ahead for now.",
    "archived": "This idea is on hold.",
}
_NEXT_STEP_CLOSED = "This idea is closed."
_NEXT_STEP_DEFAULT = "The team will review it and update this page."


def _looks_like_a_phone_or_email(candidate: str) -> bool:
    """A phone-shaped string has 5+ digit characters ANYWHERE in it (works
    for ``+60123456789``, ``0123456789``, a formatted variant with spaces/
    hyphens, or any Unicode digit); an email contains ``@``. Callers pass
    the WHOLE NFKC-normalized string (review round 2), never a single
    whitespace token alone - splitting a phone across tokens
    (``+60 12-345 6789``) leaves a short, low-digit-count first token that
    a token-only check would miss."""
    if "@" in candidate:
        return True
    return sum(1 for ch in candidate if ch.isdigit()) >= 5


class PublicIdeaStatusService:
    def __init__(self, db: Session):
        self.db = db

    def resolve(self, token: str) -> Optional[PublicIdeaStatusOut]:
        if not _TOKEN_RE.fullmatch(token or ""):
            return None

        idea = self.db.query(Idea).filter(Idea.status_token == token).first()
        if idea is None:
            return None

        # A tenant whose sign-in is blocked (suspended/archived) never serves
        # a public surface either - the same chokepoint core checks per
        # request (`Tenant.signin_allowed`, e.g. `FormService._resolve_public`).
        tenant = self.db.query(Tenant).filter(Tenant.id == idea.tenant_id).first()
        if tenant is None or not tenant.signin_allowed:
            return None

        # Scoped by the idea row's OWN tenant_id (review round 2 nit) - a
        # platform-tier status row carries Status.tenant_id IS NULL, a
        # forked-tenant row carries the tenant's own id; either is legitimate
        # for this idea, nothing else is.
        status_row = (
            self.db.query(Status)
            .filter(
                Status.id == idea.status_id,
                or_(Status.tenant_id == idea.tenant_id, Status.tenant_id.is_(None)),
            )
            .first()
        )
        # A draft (or a row whose status somehow resolved to nothing) never
        # has a public status - uniform 404, same as "unknown token" (AC-1602).
        # Gate on the trait flag (never ``key == "draft"``), matching the
        # timeline's own exclusion of the initial step.
        if status_row is None or status_row.is_initial:
            return None

        return PublicIdeaStatusOut(
            title=idea.title,
            status=status_row.label,
            ideaNumber=idea.idea_number,
            statusColor=status_row.color,
            productName=self._product_name(idea),
            problem=idea.problem,
            proposedSolution=idea.proposed_solution,
            impact=idea.impact,
            department=idea.department,
            submitterFirstName=self._first_name(idea),
            submittedAt=idea.created_at,
            upvotes=idea.upvotes,
            nextStep=self._next_step(status_row),
            timeline=self._timeline(idea, status_row),
        )

    # ---- detail lookups (each scoped by the idea row's OWN tenant_id) ------

    def _product_name(self, idea: Idea) -> Optional[str]:
        if not idea.product_id:
            return None
        product = (
            self.db.query(Product)
            .filter(Product.id == idea.product_id, Product.tenant_id == idea.tenant_id)
            .first()
        )
        return product.name if product else None

    def _first_name(self, idea: Idea) -> Optional[str]:
        """AC-90-105/106 (security-critical): prefer the denormalized
        ``submitter_name`` (operator-authored ideas), else the linked
        Contact's ``first_name`` (tenant-scoped, polymorphic-stored-id rule).
        Only the FIRST whitespace token is ever returned, and never a
        fragment of a phone number or email - intake's find-or-create writes
        ``first_name=phone`` for every new WhatsApp contact
        (``services/intake.py``), so without this guard the page would
        publish the submitter's phone number (or a piece of it). Never falls
        back to a placeholder like "Unknown" - null simply hides the line.

        Review round 2 (a token-only digit-count check leaked fragments):
        1. NFKC-normalize the WHOLE raw name FIRST - a fullwidth ``＠``
           (U+FF20) or fullwidth digit otherwise bypasses an ASCII-only
           ``@``/``isdigit`` check (``a＠b.co`` -> ``a@b.co``).
        2. Reject on the WHOLE normalized string having 5+ digits anywhere,
           or containing ``@`` - a phone split across tokens by spaces or
           hyphens (``+60 12-345 6789``, ``0123 456 789``) leaves an
           individual token with too few digits to trip a token-only check,
           but the full string never does.
        3. Only THEN take the first token, and reject it outright if it
           carries ANY digit or has no alphabetic character at all - never
           publish a bare punctuation/digit fragment as a "name"
           (``Ali_0123`` -> the token itself carries a digit).

        DISCLOSURE (known, accepted edge cases - not bugs, not fixed here):
        - A name with NO whitespace to split on (e.g. a CJK name like
          ``"李明"``) is published WHOLE, surname included - the
          first-whitespace-token rule has nothing to split there, so it
          returns the entire string rather than "first name only".
        - The published value is the NFKC-NORMALIZED form of whatever was
          stored, not necessarily byte-identical to the original input (a
          fullwidth character, for instance, normalizes to its ASCII/
          halfwidth form before being returned)."""
        raw_name = idea.submitter_name
        if not raw_name and idea.submitter_contact_id:
            from modules.omnichannel.models import Contact

            contact = (
                self.db.query(Contact)
                .filter(
                    Contact.id == idea.submitter_contact_id,
                    Contact.tenant_id == idea.tenant_id,
                )
                .first()
            )
            if contact is not None:
                raw_name = contact.first_name

        if not raw_name:
            return None

        normalized = unicodedata.normalize("NFKC", raw_name)
        if _looks_like_a_phone_or_email(normalized):
            return None

        first_token = normalized.strip().split()[0] if normalized.strip() else None
        if not first_token:
            return None
        if any(ch.isdigit() for ch in first_token):
            return None
        if not any(ch.isalpha() for ch in first_token):
            return None
        return first_token

    def _next_step(self, status_row: Status) -> str:
        known = PUBLIC_NEXT_STEP.get(status_row.key)
        if known is not None:
            return known
        if status_row.is_terminal or status_row.is_archived:
            return _NEXT_STEP_CLOSED
        return _NEXT_STEP_DEFAULT

    def _timeline(self, idea: Idea, status_row: Status) -> List[PublicIdeaTimelineStepOut]:
        rows = StatusRepository(self.db).list_for_entity(
            IDEA_ENTITY, idea.tenant_id, include_inactive=False
        )
        main_path = [r for r in rows if not r.is_initial and not r.is_archived]

        def _step(row: Status, state: str) -> PublicIdeaTimelineStepOut:
            return PublicIdeaTimelineStepOut(label=row.label, color=row.color, state=state)

        current_index = next(
            (i for i, r in enumerate(main_path) if r.id == status_row.id), None
        )
        if current_index is not None:
            return [
                _step(row, "done" if i < current_index else "current" if i == current_index else "upcoming")
                for i, row in enumerate(main_path)
            ]

        # Off-ramp (is_archived) or a current status the resolved tier no
        # longer carries (fork happened after) - truthfully short, never a
        # fabricated position (AC-90-103).
        timeline: List[PublicIdeaTimelineStepOut] = []
        if main_path:
            timeline.append(_step(main_path[0], "done"))
        timeline.append(_step(status_row, "current"))
        return timeline
