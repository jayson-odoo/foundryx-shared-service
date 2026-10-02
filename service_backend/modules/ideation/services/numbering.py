"""Idea numbering (SS-IDEATION-OWN) - the human ``IDEA-0001`` reference.

Rides the CORE numbering engine (``app/numbering`` + ``NumberingService``): the
``idea_no`` sequence is registered module-tagged (``ideation``) so it shows in
Settings > Numbering only while ideation is active, and a tenant may override the
prefix/format there. Gapless + per tenant; the increment rides the caller's
transaction (a rolled-back create does not burn a number).

Only REAL ideas get a number - :func:`ensure_idea_number` is called when an idea
leaves draft (intake promotion), and on every direct create (operator, embed,
one-shot chatbot). Drafts stay NULL so an abandoned draft never consumes one.
"""
from datetime import date

from sqlalchemy.orm import Session

from app.models.numbering import NumberCounter
from app.models.status import Status
from app.numbering.registry import (
    RESET_NEVER,
    NumberSequenceDef,
    register_number_sequence,
)
from app.services.numbering_service import NumberingService, format_number

from ..models import Idea
from .statuses import IDEA_ENTITY

IDEA_NUMBER_DOC_TYPE = "idea_no"
IDEA_NUMBER_PREFIX = "IDEA-"
IDEA_NUMBER_FORMAT = "{prefix}{NNNN}"

IDEA_NUMBER_SEQUENCE = NumberSequenceDef(
    key=IDEA_NUMBER_DOC_TYPE,
    label="Idea number",
    module="ideation",
    default_prefix=IDEA_NUMBER_PREFIX,
    default_format=IDEA_NUMBER_FORMAT,
    default_reset=RESET_NEVER,
)


def register_idea_numbering() -> None:
    """Boot-time registration (idempotent - re-registering overwrites)."""
    register_number_sequence(IDEA_NUMBER_SEQUENCE)


def ensure_idea_number(db: Session, idea: Idea) -> str:
    """Assign the idea its number once (idempotent). Flushes, never commits."""
    if idea.number:
        return idea.number
    register_idea_numbering()  # cheap; guarantees the def even off the boot path
    idea.number = NumberingService(db).next_number(idea.tenant_id, IDEA_NUMBER_DOC_TYPE)
    db.flush()
    return idea.number


def backfill_idea_numbers(db: Session) -> int:
    """Number every pre-existing NON-draft idea that has no number yet, per tenant
    in ``created_at`` order (ties by id), and advance each tenant's ``idea_no``
    counter past them so new ideas continue the sequence. Drafts (any
    ``is_initial`` idea status) stay NULL - they get a number on promotion.

    Idempotent (already-numbered ideas are skipped). Flushes, never commits - the
    caller (the module migration) owns the transaction. Uses the registered
    default format: the sequence is new, so no tenant override can exist yet.
    Returns the number of ideas numbered."""
    initial_ids = [
        sid
        for (sid,) in db.query(Status.id)
        .filter(Status.entity_type == IDEA_ENTITY, Status.is_initial.is_(True))
        .all()
    ]
    q = db.query(Idea).filter(Idea.number.is_(None))
    if initial_ids:
        q = q.filter(~Idea.status_id.in_(initial_ids))
    pending = q.order_by(Idea.tenant_id, Idea.created_at.asc(), Idea.id.asc()).all()

    by_tenant: dict = {}
    for idea in pending:
        by_tenant.setdefault(idea.tenant_id, []).append(idea)

    for tenant_id, ideas in by_tenant.items():
        counter = (
            db.query(NumberCounter)
            .filter(
                NumberCounter.tenant_id == tenant_id,
                NumberCounter.doc_type == IDEA_NUMBER_DOC_TYPE,
                NumberCounter.period_key == "",
            )
            .first()
        )
        if counter is None:
            counter = NumberCounter(
                tenant_id=tenant_id,
                doc_type=IDEA_NUMBER_DOC_TYPE,
                period_key="",
                next_val=1,
            )
            db.add(counter)
            db.flush()
        seq = counter.next_val or 1
        for idea in ideas:
            # The default format has no date token; the create date keeps it
            # correct should the default ever gain one.
            at = idea.created_at.date() if idea.created_at else date.today()
            idea.number = format_number(IDEA_NUMBER_FORMAT, IDEA_NUMBER_PREFIX, seq, at)
            seq += 1
        counter.next_val = seq
    db.flush()
    return len(pending)
