"""Seed the ``grill-me-business`` skill (platform-tier) + the per-tenant
``Ideation grill`` agent (AC-BI-28 / AC-BI-20b).

Both are INSERT-IF-MISSING so an operator's edits survive a reseed. The skill is
a **business-register** rewrite of Claude's developer ``grill-me`` — the
*"explore the codebase instead"* line is dropped (a shared-service agent has no
repository) and replaced with a grounding rule over the linked ideas + BR fields,
a question budget, and the emit contract (it never generates on its own — the
human hits Generate).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.ai.client import any_llm_connection
from app.models.ai import AiAgent, AiSkill, AiSkillVersion
from app.repositories.ai_repository import AgentRepository, SkillRepository

from .grill import GRILL_AGENT_KEY, GRILL_AGENT_NAME, GRILL_MODEL, GRILL_SKILL_KEY

GRILL_SKILL_NAME = "Business grill"

# The authored skill body (AC-BI-28). Carries the two injected tokens
# ``{{ target_fields }}`` and ``{{ source_artifacts }}`` — composition is
# SUBSTITUTION ONLY (AC-BI-08), so this text is never evaluated.
GRILL_SKILL_BODY = """\
You are a business analyst running a focused clarifying interview to turn a rough \
idea into a well-formed Business Requirement. Interview the user about the \
requirement until you have grounded, specific answers for every target field \
below. This is a conversation, not a form: ask, listen, and sharpen.

Target fields to establish:
{{ target_fields }}

Linked source ideas (the raw material — ground your questions in these; do not \
ask for what they already tell you):
{{ source_artifacts }}

How to run the interview:
- Ask ONE question at a time. Keep each question short and concrete.
- Ground every question in the linked ideas and the fields already established. \
Ask about what is still MISSING or vague, never about what is already clear.
- For each question, offer your own recommended answer so the user can simply \
confirm or correct it.
- Prefer specifics: a measurable success metric, named stakeholders, an explicit \
scope boundary, real constraints. Push back on vague answers.
- Stay in business language. You have no access to any codebase or repository — \
never suggest exploring code; reason only from the ideas and the user's answers.
- Keep it tight: aim to resolve the fields within about eight questions. When \
every field is grounded, say so and invite the user to generate the requirement.

You never write the requirement yourself and you never finish the conversation on \
your own. The human ends the interview by pressing Generate; your job is only to \
ask, sharpen, and track what has been covered.\
"""


def seed_grill_skill(db: Session) -> None:
    """Idempotent global seed of the platform-tier ``grill-me-business`` skill +
    its v1 version (insert-if-missing; an operator's edits survive a reseed)."""
    existing = (
        db.query(AiSkill)
        .filter(AiSkill.tenant_id.is_(None), AiSkill.key == GRILL_SKILL_KEY)
        .first()
    )
    if existing is not None:
        return
    skill = AiSkill(
        tenant_id=None,
        key=GRILL_SKILL_KEY,
        name=GRILL_SKILL_NAME,
        description="Grills a rough idea into a well-formed Business Requirement.",
        is_system=True,
    )
    db.add(skill)
    db.flush()
    version = AiSkillVersion(
        skill_id=skill.id,
        tenant_id=None,
        version=1,
        body=GRILL_SKILL_BODY,
        created_by=None,
    )
    db.add(version)
    db.flush()
    skill.active_version_id = version.id
    db.flush()


def seed_grill_agent(db: Session, tenant_id: str) -> Optional[AiAgent]:
    """Idempotent per-tenant seed of the ``Ideation grill`` agent (AC-BI-20b).

    Insert-if-missing (survives reseed). Bound to the resolved LLM connection
    (tenant → platform → None) via ``any_llm_connection`` — NOT
    ``resolve_for_type`` (non-deterministic under the multi-LLM carve-out). Model
    ``gemini-2.5-flash``, temperature 0, equips the ``grill-me-business`` skill.
    If no connection resolves it is seeded connectionless — the Grill tab shows
    the prerequisite warning and lights up when a key is later added (no reseed).

    Resolved + seeded by the STABLE ``key`` (not the display name), so a tenant
    renaming the agent (AC-BI-20b) never causes a duplicate re-seed. The agent is
    ``is_system`` — its key is locked and it can't be deleted (name/model/skills
    stay editable)."""
    repo = AgentRepository(db)
    existing = repo.get_by_key(tenant_id, GRILL_AGENT_KEY)
    if existing is not None:
        return existing
    skill = SkillRepository(db).get_by_key(tenant_id, GRILL_SKILL_KEY)
    connection = any_llm_connection(db, tenant_id)
    agent = AiAgent(
        tenant_id=tenant_id,
        key=GRILL_AGENT_KEY,
        is_system=True,
        name=GRILL_AGENT_NAME,
        description="Auto-configured agent that grills ideas into business requirements.",
        connection_id=connection.id if connection is not None else None,
        model=GRILL_MODEL,
        temperature=0.0,
        skills=[skill] if skill is not None else [],
        is_enabled=True,
    )
    repo.add(agent)
    db.flush()
    return agent
