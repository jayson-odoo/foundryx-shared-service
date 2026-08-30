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
import json
from typing import Any, Dict, List

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.integrations.base import LLMError
from app.models.ai import AiAgent, AiSkill, AiSkillVersion
from app.repositories.ai_repository import SkillRepository
from app.workflow_engine.agent_state import sanitize_agent_state
from app.workflow_engine.context import render_field
from app.workflow_engine.schemas import output_param_issues


class ActionError(Exception):
    """A node failed - halts the run (D14)."""


_ALLOWED_PARAM_TYPES = {"string", "number", "boolean", "enum"}


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
        prop: Dict[str, Any] = {
            "type": "string" if param_type == "enum" else param_type
        }
        if param_type == "enum":
            prop["enum"] = [v for v in row.get("enumValues", []) if isinstance(v, str)]
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


def _stateful_schema_from_params(params: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Structured contract used by stateful calls.

    Transient outputs stay under ``outputs`` while every stateful field gets a
    separate, typed patch. The platform reducer, not the provider, is the
    authority for accepting those patches.
    """
    transient = [row for row in params if row.get("stateful") is not True]
    stateful = [row for row in params if row.get("stateful") is True]
    transient_schema = _schema_from_params(transient)
    patch_properties: Dict[str, Any] = {}
    for row in stateful:
        value_schema: Dict[str, Any] = {
            "type": "string" if row["type"] == "enum" else row["type"]
        }
        if row["type"] == "enum":
            value_schema["enum"] = row.get("enumValues", [])
        patch_properties[row["key"]] = {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["set", "clear", "no_change", "ambiguous"],
                },
                "value": value_schema,
                "evidence": {"type": "string"},
            },
            "required": ["operation"],
        }
    return {
        "type": "object",
        "properties": {
            "outputs": transient_schema,
            "statePatches": {"type": "object", "properties": patch_properties},
            "pendingField": {"type": "string"},
        },
    }


def _valid_value(value: Any, definition: Dict[str, Any]) -> bool:
    row_type = definition.get("type")
    if row_type == "string":
        return isinstance(value, str)
    if row_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if row_type == "boolean":
        return isinstance(value, bool)
    if row_type == "enum":
        return isinstance(value, str) and value in definition.get("enumValues", [])
    return False


def _validated_flat_output(result: Dict[str, Any], params: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        raise ActionError("AI Agent returned an invalid structured output.")
    definitions = {row["key"]: row for row in params}
    accepted: Dict[str, Any] = {}
    for key, value in result.items():
        definition = definitions.get(key)
        if definition is None:
            continue
        if not _valid_value(value, definition):
            raise ActionError(f'AI output "{key}" does not match its configured type.')
        accepted[key] = value
    return accepted


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
    stateful_params = [
        row for row in output_params if isinstance(row, dict) and row.get("stateful") is True
    ]
    is_stateful = bool(stateful_params)
    if is_stateful:
        workflow_id = ctx.get("_workflow.workflowId")
        node_id = ctx.get("_workflow.nodeId")
        correlation_key = ctx.get("_workflow.correlationKey")
        if not workflow_id or not node_id or not isinstance(correlation_key, str) or not correlation_key.strip():
            raise ActionError("Stateful AI Agent requires a Correlation key.")
        clarification_key = config.get("clarificationOutputKey")
        if clarification_key is not None:
            clarification = next(
                (
                    row
                    for row in output_params
                    if isinstance(row, dict) and row.get("key") == clarification_key
                ),
                None,
            )
            if not (
                isinstance(clarification, dict)
                and clarification.get("type") == "string"
                and clarification.get("stateful") is not True
            ):
                raise ActionError("Clarification output must be a transient Text output.")

    from app.ai.client import AiClient

    messages = [{"role": "user", "content": user_text}]
    if is_stateful:
        from app.services.agent_state_service import AgentStateService

        state_service = AgentStateService(db)
        state_namespace = ctx.get("_workflow.agentStateNamespace") or (
            "test" if ctx.get("_workflow.isTest") is True else "prod"
        )
        state_row = state_service.load(
            tenant_id,
            str(workflow_id),
            str(node_id),
            correlation_key,
            namespace=state_namespace,
        )
        accepted_state, _accepted_provenance, _excluded_fields = sanitize_agent_state(
            state_row.state_json if state_row is not None else {},
            state_row.provenance_json if state_row is not None else {},
            output_params,
        )
        stateful_keys = {row["key"] for row in stateful_params}
        pending = (
            {
                "question": state_row.pending_question,
                "field": state_row.pending_field,
            }
            if state_row is not None
            and isinstance(state_row.pending_question, str)
            and state_row.pending_question.strip()
            and state_row.pending_field in stateful_keys
            else None
        )
        current_message = user_text
        if not current_message.strip():
            raise ActionError("Current message is unavailable for stateful AI Agent output.")
        messages = [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "currentMessage": current_message,
                        "acceptedState": accepted_state,
                        "outputParameters": [
                            {
                                key: row[key]
                                for key in (
                                    "key",
                                    "type",
                                    "description",
                                    "enumValues",
                                    "required",
                                    "stateful",
                                )
                                if key in row
                            }
                            for row in output_params
                        ],
                        "pendingClarification": pending,
                    },
                    ensure_ascii=False,
                ),
            }
        ]
        output_schema = _stateful_schema_from_params(output_params)

    try:
        result, _trace = AiClient(db).complete(
            tenant_id=tenant_id,
            agent=agent,
            system=system,
            messages=messages,
            output_schema=output_schema if output_schema.get("properties") else None,
        )
    except LLMError as exc:
        raise ActionError(str(exc)) from exc

    if result.structured is not None:
        if not is_stateful:
            return _validated_flat_output(result.structured, output_params)

        structured = result.structured
        if not isinstance(structured, dict):
            raise ActionError("AI Agent returned an invalid state patch contract.")
        transient_outputs = structured.get("outputs") or {}
        patches = structured.get("statePatches") or {}
        if not isinstance(transient_outputs, dict) or not isinstance(patches, dict):
            raise ActionError("AI Agent returned an invalid state patch contract.")
        transient_outputs = _validated_flat_output(
            transient_outputs,
            [row for row in output_params if row.get("stateful") is not True],
        )
        pending_missing = object()
        pending_value = structured.get("pendingField", pending_missing)
        pending_omitted = pending_value is pending_missing
        pending_field = pending_value
        if pending_value is pending_missing:
            pending_field = state_row.pending_field if state_row is not None else None
        if pending_field is not None and not isinstance(pending_field, str):
            raise ActionError("AI Agent returned an invalid pending field.")
        stateful_keys = {row["key"] for row in stateful_params}
        clarification_key = config.get("clarificationOutputKey")
        clarification = transient_outputs.get(clarification_key) if clarification_key else None
        if pending_field is not None:
            if pending_field not in stateful_keys:
                raise ActionError("AI Agent returned an invalid pending field.")
            if (
                not pending_omitted
                and (
                    not clarification_key
                    or not isinstance(clarification, str)
                    or not clarification.strip()
                )
            ):
                raise ActionError("pending clarification requires a question and target field.")
        from app.services.agent_state_service import AgentStateService

        state_row, reduction = AgentStateService(db).apply(
            tenant_id=tenant_id,
            workflow_id=str(workflow_id),
            node_id=str(node_id),
            correlation_key=correlation_key,
            schema=output_params,
            patches=patches,
            message=user_text,
            run_id=str(ctx.get("_workflow.runId") or ""),
            message_id=ctx.get("trigger.message.id"),
            pending_question=(
                clarification
                or (state_row.pending_question if state_row is not None else None)
            ) if pending_field is not None else None,
            pending_field=pending_field,
            namespace=state_namespace,
        )
        return {
            **state_row.state_json,
            **transient_outputs,
            "stateRevision": state_row.revision,
            "stateChangedFields": reduction.changed_fields,
            "stateRejectedFields": reduction.rejected_fields,
            "pendingField": state_row.pending_field,
        }
    if is_stateful and result.text is not None:
        raise ActionError("Stateful AI Agent requires structured output.")
    if is_stateful:
        raise ActionError("Stateful AI Agent requires structured output.")
    if result.text is not None:
        return {"text": result.text}
    return {}
