"""Idea → BR grill - the FIRST ``GrillDefinition`` instance (Bi-D7, AC-BI-20).

The generic engine lives in core ``app/ai/grill.py``; this module supplies the
ideation-coupled bindings for the Idea → BR pairing:

- **target template resolver** - the BR's STAMPED template field list + doc,
  so the prompt/extraction schema follow the version the BR was created under.
- **source artifacts** - the linked ideas' text (grounding, AC-BI-28).
- **agent resolver** - the per-tenant auto-seeded ``Ideation grill`` agent
  (AC-BI-20b); if it has no connection yet it lazily heals to any resolvable LLM
  connection so grilling lights up the moment a key is added - no re-seed.
- **skill** - the platform-tier ``grill-me-business`` skill's active body.
- **persist** - writes ``answers_json`` on the BR, which STAYS draft (AC-BI-27):
  the model never writes, our code does, and it never promotes.

Adding BR → FR later is a NEW ``GrillDefinition`` row + template here - the core
engine is untouched (Bi-D7).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.ai import (
    GrillContext,
    GrillDefinition,
    GrillEngine,
    GrillError,
    get_grill_definition,
    register_grill_definition,
)
from app.ai.client import any_llm_connection
from app.ai.grill import set_definition_target_type
from app.form_engine.schemas import FormDocument
from app.models.ai import AiAgent, AiSkill, AiSkillVersion
from app.repositories.ai_repository import AgentRepository, SkillRepository

from ..models import BusinessRequirement, Idea, IdeaBusinessRequirement
from ..schemas import (
    GrillFieldOut,
    GrillGenerateOut,
    GrillMessageOut,
    GrillStateOut,
    GrillTurnOut,
)
from .br_templates import get_stamped_doc
from .business_requirements import BusinessRequirementService
from .statuses import BR_ENTITY

GRILL_DEFINITION_KEY = "idea_to_br"
GRILL_SKILL_KEY = "grill-me-business"
# The STABLE binding key (never the display name - a tenant may rename the agent,
# AC-BI-20b). ``GRILL_AGENT_NAME`` is only the seeded display default.
GRILL_AGENT_KEY = "ideation-grill"
GRILL_AGENT_NAME = "Ideation grill"
GRILL_MODEL = "gemini-2.5-flash"
SOURCE_TYPE = "idea"


# ── readiness (AC-BI-11 / AC-BI-20b prerequisite warning) ─────────────────────


def grill_readiness(db: Session, tenant_id: str) -> Tuple[bool, Optional[str]]:
    """Is the grill runnable for this tenant? ``(ready, warning)``.

    Ready = the auto-seeded agent exists AND an LLM connection resolves (its own
    or the agent's or the platform fallback). Otherwise a clear prerequisite
    warning (AC-BI-11) - never a silent runtime failure. Resolves by the STABLE
    key so a renamed agent (AC-BI-20b) still binds."""
    agent = AgentRepository(db).get_by_key(tenant_id, GRILL_AGENT_KEY)
    if agent is None:
        return False, "The AI grill agent has not been set up for this workspace yet."
    if not agent.is_enabled:
        return False, f'The "{GRILL_AGENT_NAME}" agent is disabled.'
    connection_id = agent.connection_id or (
        c.id if (c := any_llm_connection(db, tenant_id)) is not None else None
    )
    if connection_id is None:
        return (
            False,
            "No AI connection configured - add an LLM connection under "
            "Settings → Integrations to start grilling.",
        )
    return True, None


# ── resolvers ─────────────────────────────────────────────────────────────────


def _br_or_error(db: Session, tenant_id: str, br_id: str) -> BusinessRequirement:
    br = (
        db.query(BusinessRequirement)
        .filter(
            BusinessRequirement.id == br_id,
            BusinessRequirement.tenant_id == tenant_id,
        )
        .first()
    )
    if br is None:
        raise GrillError("Business requirement not found.")
    return br


def _target_fields(db: Session, br: BusinessRequirement) -> Tuple[List[Dict[str, str]], dict]:
    """The BR's STAMPED template field list (key + label) + its doc - extraction
    validates against the STAMPED version, never the active one (AC-BI-16)."""
    doc = get_stamped_doc(db, br.template_key, br.template_version, br.tenant_id)
    if not doc:
        raise GrillError("The BR template version could not be resolved.")
    form = FormDocument.model_validate(doc)
    fields = [
        {"key": f.key, "label": f.label or f.key}
        for f in form.input_fields()
        if f.key
    ]
    return fields, doc


def _source_artifacts(db: Session, tenant_id: str, br: BusinessRequirement) -> Tuple[List[str], List[str]]:
    """The linked ideas as grounding text + their ids (tenant-scoped, AC-BI-17)."""
    idea_ids = [
        r.idea_id
        for r in db.query(IdeaBusinessRequirement.idea_id).filter(
            IdeaBusinessRequirement.business_requirement_id == br.id,
            IdeaBusinessRequirement.tenant_id == tenant_id,
        )
    ]
    if not idea_ids:
        return [], []
    ideas = (
        db.query(Idea)
        .filter(Idea.id.in_(idea_ids), Idea.tenant_id == tenant_id)
        .order_by(Idea.created_at.asc(), Idea.id.asc())
        .all()
    )
    artifacts: List[str] = []
    for idea in ideas:
        parts = [f"Problem: {idea.problem or ''}".strip()]
        if idea.proposed_solution:
            parts.append(f"Proposed solution: {idea.proposed_solution}")
        if idea.impact:
            parts.append(f"Impact: {idea.impact}")
        if idea.department:
            parts.append(f"Department: {idea.department}")
        # The raw captured text (WhatsApp/voice/manual) grounds the grill in the
        # submitter's own words (AC-BI-32b) - included only when it adds signal
        # beyond the already-listed problem headline.
        raw = (idea.raw_text or "").strip()
        if raw and raw != (idea.problem or "").strip():
            parts.append(f"Original message: {raw}")
        artifacts.append("\n".join(parts))
    return artifacts, [i.id for i in ideas]


def _resolve_agent(db: Session, tenant_id: str) -> AiAgent:
    """The auto-seeded ``Ideation grill`` agent (AC-BI-20b). If it carries no
    connection but one resolves now, lazily heal it so grilling lights up the
    moment a platform/tenant key is added (no re-seed needed). Bound by the
    STABLE key so a renamed agent (AC-BI-20b) still resolves."""
    agent = AgentRepository(db).get_by_key(tenant_id, GRILL_AGENT_KEY)
    if agent is None:
        raise GrillError(
            "The AI grill agent has not been set up for this workspace yet."
        )
    if not agent.connection_id:
        conn = any_llm_connection(db, tenant_id)
        if conn is not None:
            agent.connection_id = conn.id
            db.flush()
    return agent


def _resolve_skill(db: Session, tenant_id: str) -> Tuple[str, str, Optional[int]]:
    """The active ``grill-me-business`` body + (key, version int) for stamping."""
    skill: Optional[AiSkill] = SkillRepository(db).get_by_key(tenant_id, GRILL_SKILL_KEY)
    if skill is None:
        raise GrillError("The grill-me-business skill is not installed.")
    body = ""
    version: Optional[int] = None
    if skill.active_version_id:
        row = (
            db.query(AiSkillVersion)
            .filter(AiSkillVersion.id == skill.active_version_id)
            .first()
        )
        if row is not None:
            body = row.body or ""
            version = row.version
    return body, skill.key, version


def resolve_idea_to_br_context(db: Session, tenant_id: str, br_id: str) -> GrillContext:
    """Assemble the full grill context for one draft BR (AC-BI-20)."""
    br = _br_or_error(db, tenant_id, br_id)
    fields, doc = _target_fields(db, br)
    artifacts, idea_ids = _source_artifacts(db, tenant_id, br)
    agent = _resolve_agent(db, tenant_id)
    skill_body, skill_key, prompt_version = _resolve_skill(db, tenant_id)
    return GrillContext(
        tenant_id=tenant_id,
        target_id=br_id,
        target_fields=fields,
        target_doc=doc,
        source_artifacts=artifacts,
        source_type=SOURCE_TYPE,
        source_ids=idea_ids,
        template_version=br.template_version,
        agent=agent,
        skill_body=skill_body,
        skill_key=skill_key,
        prompt_version=prompt_version,
    )


def persist_br_answers(
    db: Session, tenant_id: str, br_id: str, answers: Dict, actor
) -> None:
    """Write the extracted ``answers_json`` on the BR (AC-BI-27). Write-only:
    the answers are already ``form_engine``-validated by the engine, the BR STAYS
    draft (no status touch), and the engine owns the commit (flush only here)."""
    br = _br_or_error(db, tenant_id, br_id)
    br.answers_json = dict(answers or {})
    if actor is not None:
        br.updated_by = actor.id
    db.flush()


def register_idea_to_br_grill() -> None:
    """Register the Idea → BR grill definition (idempotent; boot hook)."""
    set_definition_target_type(GRILL_DEFINITION_KEY, BR_ENTITY)
    register_grill_definition(
        GrillDefinition(
            key=GRILL_DEFINITION_KEY,
            source_type=SOURCE_TYPE,
            skill_key=GRILL_SKILL_KEY,
            resolve_context=resolve_idea_to_br_context,
            persist_answers=persist_br_answers,
        )
    )


def _turn_out(result) -> GrillTurnOut:
    """Map a core ``TurnResult`` to the wire schema (AC-BI-24b/24c)."""
    return GrillTurnOut(
        replyText=result.reply_text,
        coveredFields=result.covered_fields,
        capturedSummary=result.captured_summary,
        generateSignal=result.generate_signal,
    )


# ── the ideation grill service (the router stays HTTP-only) ───────────────────


class IdeationGrillService:
    """The BR-grill surface (AC-BI-29). Wraps the generic ``GrillEngine`` with
    ideation readiness + the BR detail refresh Generate returns."""

    def __init__(self, db: Session):
        self.db = db
        self.engine = GrillEngine(db)
        self.br = BusinessRequirementService(db)

    def _definition(self) -> GrillDefinition:
        definition = get_grill_definition(GRILL_DEFINITION_KEY)
        if definition is None:  # boot-registered - a missing one is a config bug
            raise HTTPException(500, "The idea→BR grill definition is not registered.")
        return definition

    def state(self, tenant_id: str, br_id: str) -> GrillStateOut:
        # 404 cleanly if the BR is gone (never leak another tenant's BR).
        self.br._br_or_404(tenant_id, br_id)
        ready, warning = grill_readiness(self.db, tenant_id)
        state = self.engine.state(self._definition(), tenant_id, br_id)
        return GrillStateOut(
            ready=ready,
            warning=warning,
            agentName=GRILL_AGENT_NAME,
            fields=[GrillFieldOut(key=f["key"], label=f["label"]) for f in state.fields],
            messages=[
                GrillMessageOut(
                    id=m["id"],
                    role=m["role"],
                    content=m["content"],
                    coveredFields=m["coveredFields"],
                    createdAt=m["createdAt"],
                )
                for m in state.messages
            ],
            coveredFields=state.covered_fields,
            capturedSummary=state.captured_summary,
        )

    def open_grill(self, tenant_id: str, br_id: str, actor) -> GrillTurnOut:
        """Fire the opening turn on a fresh promoted BR (AC-BI-29b): the agent
        greets + summarizes the absorbed idea(s) + asks its first question, with
        NO user message. Idempotent at the engine (an already-opened transcript
        returns its latest reply, no new LLM call). 409 if the grill is not ready
        (never auto-fire without a resolved connection)."""
        self.br._br_or_404(tenant_id, br_id)
        ready, warning = grill_readiness(self.db, tenant_id)
        if not ready:
            raise HTTPException(409, warning or "The grill is not available yet.")
        try:
            result = self.engine.open(self._definition(), tenant_id, br_id, actor)
        except GrillError as exc:
            raise HTTPException(502, str(exc)) from exc
        return _turn_out(result)

    def turn(self, tenant_id: str, br_id: str, message: str, actor) -> GrillTurnOut:
        self.br._br_or_404(tenant_id, br_id)
        text = (message or "").strip()
        if not text:
            raise HTTPException(422, "A message is required.")
        ready, warning = grill_readiness(self.db, tenant_id)
        if not ready:
            raise HTTPException(409, warning or "The grill is not available yet.")
        try:
            result = self.engine.turn(self._definition(), tenant_id, br_id, text, actor)
        except GrillError as exc:
            raise HTTPException(502, str(exc)) from exc
        return _turn_out(result)

    def generate(self, tenant_id: str, br_id: str, actor) -> GrillGenerateOut:
        self.br._br_or_404(tenant_id, br_id)
        ready, warning = grill_readiness(self.db, tenant_id)
        if not ready:
            raise HTTPException(409, warning or "The grill is not available yet.")
        try:
            result = self.engine.generate(self._definition(), tenant_id, br_id, actor)
        except GrillError as exc:
            raise HTTPException(502, str(exc)) from exc
        if not result.ok:
            return GrillGenerateOut(status="needs_review", fieldErrors=result.field_errors)
        # BR STAYS draft (AC-BI-27) - return the refreshed detail so the Details
        # tab reflects the new answers.
        detail = self.br.get(tenant_id, br_id)
        return GrillGenerateOut(status="ok", br=detail, answers=result.answers)
