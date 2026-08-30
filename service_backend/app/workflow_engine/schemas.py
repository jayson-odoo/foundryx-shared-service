"""Workflow definition doc model + publish-time validation (plan sprint-2/08 D3/D17).

The doc is the forever-contract graph (mirror of frontend ``types/workflows.ts``):
``schemaVersion`` at root, ``nodes[]`` + ``edges[]``. Stored camelCase in
``draft_definition_json`` / version ``definition_json``. ``validate_definition``
is the save/publish gate - same rules the editor surfaces live.
"""
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

WORKFLOW_SCHEMA_VERSION = 2

# Conservative ASCII identifier grammar. Output keys are inserted into merge
# paths as ``nodes.<id>.<key>`` and must remain one merge-token segment.
AI_OUTPUT_PARAM_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
AI_OUTPUT_PARAM_TYPES = frozenset({"string", "number", "boolean", "enum"})
CORRELATION_KEY_RE = re.compile(r"^\{\{\s*[A-Za-z_][A-Za-z0-9_.]*\s*\}\}$")
_AI_OUTPUT_PARAM_PREFIX = 'AI Agent: "Output parameters"'


def output_param_issues(value: Any) -> List[str]:
    """Return the shared output-parameter contract errors.

    This helper is used by both the publish gate and the runtime action so a
    saved draft cannot bypass the editor's schema rules.
    """
    if not isinstance(value, list):
        return [f"{_AI_OUTPUT_PARAM_PREFIX} must be a non-empty list of parameter objects."]
    if not value:
        return [f"{_AI_OUTPUT_PARAM_PREFIX} must contain at least one parameter."]

    issues: List[str] = []
    seen: set[str] = set()
    for row in value:
        if not isinstance(row, dict):
            issues.append(f"{_AI_OUTPUT_PARAM_PREFIX} contains a parameter that is not an object.")
            continue
        key = row.get("key")
        if not isinstance(key, str) or not key.strip():
            issues.append(f'{_AI_OUTPUT_PARAM_PREFIX} contains a parameter without a key.')
            continue
        if key != key.strip():
            issues.append(f"{_AI_OUTPUT_PARAM_PREFIX} contains a key with surrounding whitespace.")
            continue
        if AI_OUTPUT_PARAM_KEY_RE.fullmatch(key) is None:
            issues.append(
                f'{_AI_OUTPUT_PARAM_PREFIX} contains an invalid key "{key}". '
                "Use letters, numbers, and underscores; start with a letter or underscore."
            )
        elif key in seen:
            issues.append(f'{_AI_OUTPUT_PARAM_PREFIX} contains duplicate key "{key}".')
        else:
            seen.add(key)
        param_type = row.get("type")
        if not isinstance(param_type, str) or param_type not in AI_OUTPUT_PARAM_TYPES:
            issues.append(f"{_AI_OUTPUT_PARAM_PREFIX} contains a parameter with an invalid type.")
        if param_type == "enum":
            values = row.get("enumValues")
            if not isinstance(values, list) or len(values) < 2:
                issues.append(f"{_AI_OUTPUT_PARAM_PREFIX} enum parameters need at least two values.")
            else:
                seen_values: set[str] = set()
                for value in values:
                    if not isinstance(value, str) or not value.strip():
                        issues.append(f"{_AI_OUTPUT_PARAM_PREFIX} enum values cannot be blank.")
                    elif value in seen_values:
                        issues.append(f"{_AI_OUTPUT_PARAM_PREFIX} enum values must be unique.")
                    else:
                        seen_values.add(value)
        elif "enumValues" in row:
            issues.append(
                f"{_AI_OUTPUT_PARAM_PREFIX} enum values are only valid for Enum parameters."
            )
    return issues


class WorkflowNodeModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    kind: str  # 'trigger' | 'action' | 'if'
    type: str
    config: Dict[str, Any] = Field(default_factory=dict)
    position: Dict[str, float] = Field(default_factory=dict)


class WorkflowEdgeModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    source: str
    target: str
    sourcePort: Optional[str] = "out"


class WorkflowExecutionModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: Literal["parallel", "serialized"] = "parallel"
    correlationKey: str = ""


class WorkflowDefinitionModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schemaVersion: int = WORKFLOW_SCHEMA_VERSION
    # v1 documents omit this object; omission retains the parallel behavior.
    execution: Optional[WorkflowExecutionModel] = None
    nodes: List[WorkflowNodeModel] = Field(default_factory=list)
    edges: List[WorkflowEdgeModel] = Field(default_factory=list)


def parse_definition(raw: Any) -> WorkflowDefinitionModel:
    """Validate the doc SHAPE (422 on malformed). Returns the typed model."""
    return WorkflowDefinitionModel.model_validate(raw or {})


class WorkflowValidationError(Exception):
    """Publish gate failed - carries the human-readable issues."""

    def __init__(self, issues: List[str]):
        super().__init__("; ".join(issues))
        self.issues = issues


def definition_issues(doc: WorkflowDefinitionModel) -> List[str]:
    """The publish-blocking issues (mirror of the frontend validateDefinition).
    Empty list = publishable. Catalog-driven required-config checks included."""
    from app.workflow_engine.registry import get_action, get_trigger

    issues: List[str] = []
    triggers = [n for n in doc.nodes if n.kind == "trigger"]
    if not triggers:
        issues.append("Add a trigger to start the workflow.")
    if len(triggers) > 1:
        issues.append("A workflow can have only one trigger.")

    trigger = triggers[0] if triggers else None
    execution = doc.execution
    correlation_key = (execution.correlationKey if execution else "").strip()
    if execution and execution.mode == "serialized" and (
        not correlation_key or CORRELATION_KEY_RE.fullmatch(correlation_key) is None
    ):
        issues.append("Serialized execution requires a valid Correlation key.")
    stateful_agent = any(
        node.type == "ai_agent.run"
        and any(
            isinstance(row, dict) and row.get("stateful") is True
            for row in (node.config.get("outputParams") or [])
        )
        for node in doc.nodes
    )
    if stateful_agent and (
        execution is None
        or execution.mode != "serialized"
        or not correlation_key
        or CORRELATION_KEY_RE.fullmatch(correlation_key) is None
    ):
        issues.append(
            "Stateful AI Agent outputs require serialized execution and a Correlation key."
        )
    if trigger and any(e.target == trigger.id for e in doc.edges):
        issues.append("The trigger cannot have an incoming connection.")

    # Unique node names (mirror of the frontend - names must not collide).
    counts: Dict[str, int] = {}
    for n in doc.nodes:
        counts[_node_label(n)] = counts.get(_node_label(n), 0) + 1
    for name, count in counts.items():
        if count > 1:
            issues.append(f'Two nodes are named "{name}" - names must be unique.')

    # Reachability from the trigger - orphans block.
    if trigger:
        reachable = {trigger.id}
        grew = True
        while grew:
            grew = False
            for e in doc.edges:
                if e.source in reachable and e.target not in reachable:
                    reachable.add(e.target)
                    grew = True
        for n in doc.nodes:
            if n.id not in reachable:
                label = _node_label(n)
                issues.append(f'"{label}" is not connected to the trigger.')

    # Required config per node (catalog-driven).
    for n in doc.nodes:
        entry = get_trigger(n.type) if n.kind == "trigger" else get_action(n.type)
        if entry is None:
            continue
        for field in entry.fields:
            if field.show_when and n.config.get(field.show_when[0]) != field.show_when[1]:
                continue  # hidden field - don't require it
            if field.required:
                value = n.config.get(field.key)
                if field.type == "outputSchema":
                    if value is None or value == "":
                        issues.append(f'{entry.label}: "{field.label}" is required.')
                    else:
                        issues.extend(output_param_issues(value))
                elif value is None or value == "" or value == []:
                    issues.append(f'{entry.label}: "{field.label}" is required.')
        if n.type == "ai_agent.run":
            params = n.config.get("outputParams")
            if isinstance(params, list) and any(
                isinstance(row, dict) and row.get("stateful") is True for row in params
            ):
                clarification_key = n.config.get("clarificationOutputKey")
                if clarification_key is not None:
                    clarification = next(
                        (
                            row
                            for row in params
                            if isinstance(row, dict) and row.get("key") == clarification_key
                        ),
                        None,
                    )
                    if not (
                        isinstance(clarification, dict)
                        and clarification.get("type") == "string"
                        and clarification.get("stateful") is not True
                    ):
                        issues.append(
                            'AI Agent: "Clarification output" must be a transient Text output.'
                        )
        if n.type == "ai_agent.read_state":
            # Read Agent State must point at a stateful AI Agent that exists
            # in the graph (parity with the frontend validateDefinition; the
            # required-field check above already blocks an empty selection).
            target_id = n.config.get("agentNodeId")
            if isinstance(target_id, str) and target_id:
                target = next((t for t in doc.nodes if t.id == target_id), None)
                is_stateful_target = target is not None and target.type == "ai_agent.run" and any(
                    isinstance(row, dict) and row.get("stateful") is True
                    for row in (target.config.get("outputParams") or [])
                )
                if not is_stateful_target:
                    issues.append(
                        "Read Agent State must reference a stateful AI Agent in this workflow."
                    )
        if n.type == "redis.command":
            from app.workflow_engine.actions.redis_actions import literal_config_issues

            issues.extend(literal_config_issues(n.config))
        if n.type == "code.run":
            from app.workflow_engine.actions.code_actions import code_config_issues

            issues.extend(code_config_issues(n.config))
    return issues


def has_code_nodes(doc: Any) -> bool:
    """True when a raw or parsed definition carries a ``code.run`` node."""
    nodes = doc.nodes if isinstance(doc, WorkflowDefinitionModel) else (doc or {}).get("nodes") or []
    for node in nodes:
        node_type = node.type if isinstance(node, WorkflowNodeModel) else (node or {}).get("type")
        if node_type == "code.run":
            return True
    return False


def _node_label(node: WorkflowNodeModel) -> str:
    """The node's display name - the user-set config.name, else the catalog
    label (mirror of the frontend nodeDisplayName)."""
    name = node.config.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    from app.workflow_engine.registry import get_action, get_trigger

    entry = get_trigger(node.type) if node.kind == "trigger" else get_action(node.type)
    return entry.label if entry else node.type


def validate_definition(raw: Any) -> WorkflowDefinitionModel:
    """Full publish gate: shape + rules. Raises WorkflowValidationError."""
    doc = parse_definition(raw)
    issues = definition_issues(doc)
    if issues:
        raise WorkflowValidationError(issues)
    return doc


def topo_order(doc: WorkflowDefinitionModel) -> List[WorkflowNodeModel]:
    """Trigger→downstream topological order; unreachable/cyclic nodes trail."""
    indegree: Dict[str, int] = {n.id: 0 for n in doc.nodes}
    for e in doc.edges:
        if e.target in indegree:
            indegree[e.target] += 1
    adjacency: Dict[str, List[str]] = {}
    for e in doc.edges:
        adjacency.setdefault(e.source, []).append(e.target)
    queue = [n.id for n in doc.nodes if indegree.get(n.id, 0) == 0]
    by_id = {n.id: n for n in doc.nodes}
    order: List[WorkflowNodeModel] = []
    seen = set()
    while queue:
        nid = queue.pop(0)
        if nid in seen:
            continue
        seen.add(nid)
        if nid in by_id:
            order.append(by_id[nid])
        for nxt in adjacency.get(nid, []):
            indegree[nxt] -= 1
            if indegree[nxt] <= 0:
                queue.append(nxt)
    for n in doc.nodes:
        if n.id not in seen:
            order.append(n)
    return order
