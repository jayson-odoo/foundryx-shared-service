"""``ai_agent.run`` action (plan sprint-4/17) - send merge-rendered content to an
existing ``AiAgent`` persona and capture a user-defined structured output.

Reuses the ONE traced LLM seam (``AiClient.complete``, plan §7) every other AI
consumer in the platform calls - no new provider client, no new tracing path.
The agent owns connection + model + temperature (Bi-D1/D3); this node adds only
what's node-specific: extra instructions, the input text, and the output-param
schema. Structured output flows into the run context as ``nodes.<id>.<param>``
via the executor's normal ``set_node_output`` (D7) - no special-casing needed
downstream.

Extensibility (brief requirement - do NOT build tools/MCP here): a future tool
attachment adds a ``tools=`` argument to the single ``AiClient.complete`` call
below and a ``tool:*`` span (already reserved on ``AiSpan``, Bi-D17) - this is
the intended seam, deliberately not built out in this slice (BL-SS-031).
"""
from typing import Any, Dict, List

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.integrations.base import LLMError
from app.models.ai import AiAgent, AiSkill, AiSkillVersion
from app.repositories.ai_repository import SkillRepository
from app.workflow_engine.context import render_field
from app.workflow_engine.schemas import output_param_issues


class ActionError(Exception):
    """A node failed - halts the run (D14)."""


_ALLOWED_PARAM_TYPES = {"string", "number", "boolean"}


def _schema_from_params(params: Any) -> Dict[str, Any]:
    """Friendly config rows → a JSON Schema object, interpreted at run time -
    same "friendly config, executor interprets" shape as ``entity.update``'s
    ``assignments`` field. The action validates the full output contract before
    calling this transformer; its fallback remains defensive for direct use."""
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for row in params if isinstance(params, list) else []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        row_type = row.get("type")
        param_type = row_type if isinstance(row_type, str) and row_type in _ALLOWED_PARAM_TYPES else "string"
        if not key:
            continue
        prop: Dict[str, Any] = {"type": param_type}
        description = row.get("description")
        if description:
            prop["description"] = str(description)
        properties[key] = prop
        if row.get("required") and key not in required:
            required.append(key)
    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _build_system(db: Session, tenant_id: str, agent: AiAgent, instructions: str) -> str:
    """The agent's equipped skills (active version bodies) + this node's own
    instructions - mirrors how a grill turn assembles its system prompt
    (``app/ai/grill.py``), independently, for this second caller of the one
    ``AiClient`` seam."""
    skill_ids = [skill.id for skill in agent.skills]
    bodies_by_skill_id: Dict[str, str] = {}
    if skill_ids:
        rows = (
            SkillRepository(db)
            .visible_query(tenant_id)
            .join(
                AiSkillVersion,
                and_(
                    AiSkillVersion.skill_id == AiSkill.id,
                    AiSkillVersion.id == AiSkill.active_version_id,
                ),
            )
            .filter(
                AiSkill.id.in_(skill_ids),
                or_(
                    and_(
                        AiSkill.tenant_id == tenant_id,
                        AiSkillVersion.tenant_id == tenant_id,
                    ),
                    and_(
                        AiSkill.tenant_id.is_(None),
                        AiSkillVersion.tenant_id.is_(None),
                    ),
                ),
            )
            .with_entities(AiSkill.id, AiSkillVersion.body)
            .all()
        )
        bodies_by_skill_id = {row.id: row.body for row in rows}
    parts: List[str] = [
        bodies_by_skill_id[s.id]
        for s in agent.skills
        if bodies_by_skill_id.get(s.id)
    ]
    if instructions:
        parts.append(instructions)
    return "\n\n".join(parts)


def ai_agent_run(db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    agent_id = config.get("agentId")
    if not agent_id:
        raise ActionError("No AI agent selected.")
    agent = (
        db.query(AiAgent)
        .filter(AiAgent.id == agent_id, AiAgent.tenant_id == tenant_id)
        .first()
    )
    if agent is None:
        raise ActionError("The selected AI agent was not found.")
    if not agent.is_enabled:
        raise ActionError(f'The agent "{agent.name}" is disabled.')

    instructions = render_field(config.get("instructions"), ctx)
    system = _build_system(db, tenant_id, agent, instructions)
    user_text = render_field(config.get("inputText"), ctx)
    if not user_text.strip():
        raise ActionError("Message is empty after merging.")
    output_params = config.get("outputParams")
    param_issues = output_param_issues(output_params)
    if param_issues:
        raise ActionError(param_issues[0])
    output_schema = _schema_from_params(output_params)

    from app.ai.client import AiClient

    try:
        result, _trace = AiClient(db).complete(
            tenant_id=tenant_id,
            agent=agent,
            system=system,
            messages=[{"role": "user", "content": user_text}],
            output_schema=output_schema if output_schema.get("properties") else None,
        )
    except LLMError as exc:
        raise ActionError(str(exc)) from exc

    if result.structured is not None:
        return result.structured
    if result.text is not None:
        return {"text": result.text}
    return {}
