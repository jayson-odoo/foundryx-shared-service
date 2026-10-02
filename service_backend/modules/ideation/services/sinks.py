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
from app.services.catalog_service import tenant_public_link_base

from ..models import Idea
from .ideas import next_capture_priority
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


# Placeholders a tenant ``public_link_base_url`` may carry when its portal path
# is not ``/public/ideas/{token}`` - e.g. the Sorento CRM customer portal
# ``https://<crm>/portal/ideas/{token}`` (IDEATION-IN-CRM, sorento #1438).
TOKEN_PLACEHOLDER = "{token}"
IDEA_ID_PLACEHOLDER = "{ideaId}"
LINK_PLACEHOLDERS = (TOKEN_PLACEHOLDER, IDEA_ID_PLACEHOLDER)


def mint_idea_link(db: Session, idea: Idea) -> Optional[str]:
    """The public idea-status-page link ``{base}/public/ideas/{status_token}``.

    ``base`` is the tenant ``public_link_base_url`` (core tenant settings,
    SS-PUBLIC-LINK-BASE - e.g. the Sorento CRM customer portal) when set, else
    ``settings.frontend_url`` (the shared-service frontend, S5, AC-1114/1118).
    A tenant base carrying ``{token}`` (and/or ``{ideaId}``) is a template
    instead: the placeholders are substituted in place, nothing appended. Links
    already sent on the shared-service domain keep working: that route is
    untouched, only newly minted links pick up the setting.

    ``None`` only when the idea has no ``status_token`` yet (review round 1,
    should-fix #6: this is a pure READ - it never mints; a caller that needs one
    minted calls ``numbering.mint_idea_identity`` first, same as the sink does.
    A pre-lane captured row with no token is backfilled once by migration 0010,
    not re-minted on every read)."""
    if not idea.status_token:
        return None
    tenant_base = tenant_public_link_base(db, idea.tenant_id)
    if tenant_base and any(p in tenant_base for p in LINK_PLACEHOLDERS):
        return tenant_base.replace(TOKEN_PLACEHOLDER, idea.status_token).replace(
            IDEA_ID_PLACEHOLDER, str(idea.id)
        )
    base = (tenant_base or settings.frontend_url).rstrip("/")
    return f"{base}/public/ideas/{idea.status_token}"


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
        # New capture lands at the bottom of its lane (Q4) - stamped right at
        # the first move into ``captured`` (plan section 5).
        idea.priority = next_capture_priority(db, tenant_id, is_test=bool(idea.is_test))
        status_machine.transition(
            db, IDEA_ENTITY, idea, captured_id, actor=None, tenant_id=tenant_id, commit=False
        )
    mint_idea_identity(db, idea)
    return mint_idea_link(db, idea)
