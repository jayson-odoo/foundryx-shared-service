"""Intake ``on_complete_sink`` implementations (AC-A-16/20).

The sink is the **ONLY** promotion path: on explicit confirm it transitions the
draft Idea ``draft -> captured`` via the core status engine and mints the
product-domain deep link. **Idempotent** - re-firing on an already-captured draft
does not create a second Idea and does not double-advance the status; it just
re-mints the (stable) link.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.services import status_machine
from app.services.catalog_service import tenant_public_link_base

from ..models import Idea, ProductDelivery
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


# Placeholder a tenant ``public_link_base_url`` may carry when its portal path
# does not end in ``/ideas/{id}``.
IDEA_ID_PLACEHOLDER = "{ideaId}"


def mint_idea_link(db: Session, idea: Idea) -> Optional[str]:
    """The public idea tracking link.

    A tenant ``public_link_base_url`` (core tenant settings, SS-PUBLIC-LINK-BASE)
    wins: ``{base}/ideas/{idea_id}``, or the base with ``{ideaId}`` substituted
    when it carries the placeholder (e.g. the Sorento CRM customer portal).
    Otherwise the product-domain deep link ``{product_domain_base}/ideas/{idea_id}``
    (AC-A-38 / §5.3). ``None`` when neither is configured. Links minted earlier
    stay valid: the old route is untouched, only new links pick up the setting."""
    tenant_base = tenant_public_link_base(db, idea.tenant_id)
    if tenant_base:
        if IDEA_ID_PLACEHOLDER in tenant_base:
            return tenant_base.replace(IDEA_ID_PLACEHOLDER, str(idea.id))
        return f"{tenant_base.rstrip('/')}/ideas/{idea.id}"
    row = (
        db.query(ProductDelivery)
        .filter(
            ProductDelivery.tenant_id == idea.tenant_id,
            ProductDelivery.product_id == idea.product_id,
        )
        .first()
    )
    base = (row.product_domain_base or "").rstrip("/") if row else ""
    if not base:
        return None
    return f"{base}/ideas/{idea.id}"


def ideation_on_complete_sink(
    db: Session, idea: Idea, tenant_id: str
) -> Optional[str]:
    """Promote the draft to ``captured`` (once) and return the minted link.

    Idempotent: if the Idea is already at ``captured`` (or past it), skip the
    transition - a re-confirm is a no-op that still returns the link."""
    # Promote the captured answers to first-class columns on completion (idempotent).
    sync_idea_columns_from_captured(idea)
    captured_id = idea_status_id(db, "captured", tenant_id)
    if captured_id is not None and idea.status_id != captured_id:
        status_machine.transition(
            db, IDEA_ENTITY, idea, captured_id, actor=None, tenant_id=tenant_id, commit=False
        )
    return mint_idea_link(db, idea)
