"""Intake ``on_complete_sink`` implementations (AC-A-16/20).

The sink is the **ONLY** promotion path: on explicit confirm it transitions the
draft Idea ``draft -> captured`` via the core status engine, mints the
``idea_number`` + ``status_token`` (S1/S5, ``numbering.mint_idea_identity``),
and returns the public status-page link. **Idempotent** - re-firing on an
already-captured draft does not create a second Idea, does not double-advance
the status, and does not re-mint the number/token; it just re-derives the
(stable) link.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.services import status_machine

from ..models import Idea
from .numbering import mint_idea_identity
from .statuses import IDEA_ENTITY, idea_status_id

# The captured_json answer keys that mirror first-class Idea columns. Kept in sync
# with the ``ideation`` IntakeDefinition schema (intake_definitions.py).
_SEGREGATED_KEYS = ("problem", "proposed_solution", "impact", "department")


def sync_idea_columns_from_captured(idea: Idea) -> None:
    """Mirror the captured intake answers onto the first-class Idea columns.

    Deterministic + idempotent: for each segregated key present as a non-empty
    string in ``captured_json``, copy it to the matching column; ``problem`` keeps
    its prior value when the captured answer is blank (it is NOT NULL). The other
    three are left untouched when absent so an explicitly-set value is not wiped."""
    captured = idea.captured_json or {}
    problem = captured.get("problem")
    if isinstance(problem, str) and problem.strip():
        idea.problem = problem.strip()
    for key in ("proposed_solution", "impact", "department"):
        value = captured.get(key)
        if isinstance(value, str) and value.strip():
            setattr(idea, key, value.strip())


def mint_idea_link(db: Session, idea: Idea) -> Optional[str]:
    """The public idea-status-page link ``{settings.frontend_url}/public/ideas/
    {status_token}`` (S5, AC-1114/1118 - retires the old SSO
    ``/ideas/{idea_id}`` shape). The page lives on the SHARED-SERVICE
    frontend, not the product's own delivery origin (``ProductDelivery.
    product_domain_base`` is the PRODUCT's domain - e.g. sorento - which does
    not serve this route; ``settings.frontend_url`` is the same origin the
    email ceremony links already use, ``app/config.py``). ``None`` only when
    the idea has no ``status_token`` yet (review round 1, should-fix #6: this
    is a pure READ - it never mints; a caller that needs one minted calls
    ``numbering.mint_idea_identity`` first, same as the sink does. A pre-lane
    captured row with no token is backfilled once by migration 0010, not
    re-minted on every read)."""
    if not idea.status_token:
        return None
    return f"{settings.frontend_url.rstrip('/')}/public/ideas/{idea.status_token}"


def ideation_on_complete_sink(
    db: Session, idea: Idea, tenant_id: str
) -> Optional[str]:
    """Promote the draft to ``captured`` (once), mint ``idea_number`` +
    ``status_token`` (idempotent), and return the public status link.

    Idempotent: if the Idea is already at ``captured`` (or past it), skip the
    transition and the number/token mint - a re-confirm is a no-op that still
    returns the (stable) link."""
    # Promote the captured answers to first-class columns on completion (idempotent).
    sync_idea_columns_from_captured(idea)
    captured_id = idea_status_id(db, "captured", tenant_id)
    if captured_id is not None and idea.status_id != captured_id:
        status_machine.transition(
            db, IDEA_ENTITY, idea, captured_id, actor=None, tenant_id=tenant_id, commit=False
        )
    mint_idea_identity(db, idea)
    return mint_idea_link(db, idea)
