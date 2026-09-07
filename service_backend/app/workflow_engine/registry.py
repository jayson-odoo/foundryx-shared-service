"""Node-type registry (plan sprint-2/08 D8) - code-side, like the permissions
CSV / StatusEntity / FactSource registries. Each trigger and action declares its
config schema (drawer), output schema (dynamic-content picker) and - for actions
- an executor + connection requirement. Slice 08 registers ``manual`` +
``email.send``; modules append at install (slice 09 fans out core triggers/actions).
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from sqlalchemy.orm import Session

from app.lazy_registry import lazy_once


@dataclass(frozen=True)
class NodeField:
    key: str
    # text | textarea | select | template | inputs | entity | status | field
    # | cron | assignments (slice 09 field types resolve options on the client
    # from the workflow metadata + the node's own entityType).
    label: str
    type: str
    required: bool = False
    mergeable: bool = False
    options: Optional[List[Dict[str, str]]] = None
    # Conditional field: only shown/required when config[field] matches value
    # - one literal, or one of several (SF-9, plan 31 S3 review; mirrors the
    # frontend `showWhen` tuple-of-values form the HTTP body field needs).
    show_when: Optional[Tuple[str, Union[str, Tuple[str, ...]]]] = None
    # For `entity` - restrict the picker (e.g. only status-engine entities).
    entity_filter: Optional[str] = None
    # True = this field's VALUE(S) are secret-shaped (e.g. an HTTP header
    # value) and must be scrubbed at the trace boundary, not left to a
    # `mergeable=False` convention (plan sprint-4/31 review B1). A `keyValue`
    # field's rows get their `value` masked to `"***"` (key kept); any other
    # field's whole value is masked. Enforced by `executor._node_input_json`.
    redacted: bool = False


def matches_show_when(
    config: Dict[str, Any], field_def: "NodeField", sibling_fields: Sequence["NodeField"]
) -> bool:
    """Whether `field_def` is visible/required given `config`, resolving the
    CONTROLLING field's default when it is absent from `config` (plan 31 S3
    review SF-2) - an absent controlling key falls back to that field's FIRST
    declared option, so a node saved before the controlling field existed
    (e.g. a plan-17 `omnichannel.send_message` node with no `mode` key) keeps
    its dependent field visible/required instead of being silently hidden.
    Mirrors the frontend `lib/workflow-doc.ts matchesShowWhen` exactly,
    including the tuple/list-of-values form (SF-9)."""
    if field_def.show_when is None:
        return True
    controlling_key, wanted = field_def.show_when
    if controlling_key in config:
        actual = config.get(controlling_key)
    else:
        controlling_field = next(
            (f for f in sibling_fields if f.key == controlling_key), None
        )
        actual = (
            controlling_field.options[0]["value"]
            if controlling_field and controlling_field.options
            else None
        )
    if isinstance(wanted, (list, tuple)):
        return str(actual) in {str(w) for w in wanted}
    return str(actual) == str(wanted)


@dataclass(frozen=True)
class NodeOutput:
    key: str
    label: str


# Module callbacks keep trigger-specific test discovery/validation out of core.
TriggerTestMetadataProvider = Callable[
    [Session, str, Dict[str, Any]], Dict[str, Any]
]
TriggerTestPayloadBuilder = Callable[
    [Session, str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]
]


class TriggerTestDataError(Exception):
    """A test-trigger selection failed structural or tenant validation."""


# Registry-driven dispatch (plan sprint-4/31, D-A5-1/D-A5-4, closes A4's F3):
# a TriggerDef declares everything ``_trigger_types_for``/publish denorm/
# ``_passes_refine``/"trigger once per contact" need, so a NEW module trigger
# requires NO further core edit (AC-WFP-07).
RefineFn = Callable[[Dict[str, Any], Dict[str, Any]], bool]
# (db, workflow, trigger_config, event) -> True = create the run, False = skip
# (module-owned "trigger once per contact" claim, D-A5-4 - no core table).
FireGuardFn = Callable[[Session, Any, Dict[str, Any], Dict[str, Any]], bool]
# (trigger_config, event) -> extra ``trigger.<dotted key>`` context (merged by
# the executor's generic ``payload["eventData"]`` flattening) - lets a
# registry-driven trigger add context the fixed payload keys don't cover
# without a per-trigger hardcoded branch in the executor.
ContextExtraFn = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


@dataclass(frozen=True)
class TriggerDef:
    key: str
    label: str
    description: str
    icon: str
    category: str
    fields: List[NodeField] = field(default_factory=list)
    outputs: List[NodeOutput] = field(default_factory=list)
    module: str = "core"
    test_metadata_provider: Optional[TriggerTestMetadataProvider] = None
    test_payload_builder: Optional[TriggerTestPayloadBuilder] = None
    # The domain-event ``action`` this trigger listens to (``emit_entity_event``/
    # ``notify_entity_event``'s second arg) - drives ``_trigger_types_for``.
    event_action: Optional[str] = None
    # Denormalized ``Workflow.trigger_entity_type`` at publish (only needed when
    # it is a FIXED constant, not the author-picked ``config.entityType`` the
    # generic ``entity.*`` triggers already use).
    event_entity_type: Optional[str] = None
    # In-Python refinement the indexed candidate query can't do.
    refine: Optional[RefineFn] = None
    # "Trigger once per contact"-style guards, called once per candidate
    # workflow right before a run would be created.
    fire_guard: Optional[FireGuardFn] = None
    # Release a WINNING `fire_guard` claim when the run was never actually
    # created after all (plan 31 S3 review nit) - e.g. a `CodeNotAuthorized`
    # skip inside `_create_run` would otherwise burn the once-per-contact
    # marker permanently with no run ever produced.
    fire_release: Optional[FireGuardFn] = None
    context_extra: Optional[ContextExtraFn] = None


# An action executor: (db, tenant_id, config, ctx) -> output dict. ``ctx`` is the
# flat run-context (trigger.*, nodes.<id>.*); ``config`` is the node's raw config
# (the executor merge-renders its own string fields against ``ctx``).
ActionExecutor = Callable[[Session, str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


@dataclass(frozen=True)
class ActionDef:
    key: str
    label: str
    description: str
    icon: str
    category: str
    executor: ActionExecutor
    fields: List[NodeField] = field(default_factory=list)
    outputs: List[NodeOutput] = field(default_factory=list)
    requires_connection: Optional[str] = None  # 'email' | 'storage'
    destructive: bool = False
    module: str = "core"
    # Non-empty = a BRANCHING action (mirrors the IF node): the executor
    # activates only the outgoing edges whose ``sourcePort`` matches the
    # executor output's ``branch`` key (plan sprint-4/31 S2+, D-A5-14).
    ports: Tuple[str, ...] = ()
    # Optional extra permission gate beyond ``workflows.manage`` (e.g.
    # ``workflows.http``), checked at publish like ``workflows.code``.
    permission: Optional[str] = None
    # True = the action PARKS the run keyed by something outside it (a contact),
    # so two concurrent runs of the same workflow would race that key. Publish
    # then REFUSES a graph carrying it unless `execution.mode = "serialized"`
    # with a correlation key (plan sprint-4/31 D-A5-7, AC-WFP-51) - the same
    # rule stateful AI outputs already carry, expressed on the registry instead
    # of a hardcoded node-type check in `definition_issues`.
    requires_serialized: bool = False


_TRIGGERS: Dict[str, TriggerDef] = {}
_ACTIONS: Dict[str, ActionDef] = {}


def register_trigger(defn: TriggerDef) -> None:
    _TRIGGERS[defn.key] = defn


def register_action(defn: ActionDef) -> None:
    _ACTIONS[defn.key] = defn


# ---- generic NodeField option providers (plan 28, roadmap A8, BL-090) ----
# A `NodeField.type` -> resolver seam so the canvas can render a searchable
# picker for a field type WITHOUT any consumer (core or module) special-casing
# `if module == "..."`. Whoever owns the underlying data registers itself here
# once (e.g. core teams registers "team" from `team_capabilities.py`); any
# action/trigger that declares a field of that `type` gets the same options
# resolution for free - the pattern `omnichannel.assign_conversation`'s
# `teamId` field uses today, and the one a future core-entity assignment
# (BL-090) or another module's picker can reuse without touching this file.
OptionProvider = Callable[[Session, str], List[Dict[str, Any]]]

_OPTION_PROVIDERS: Dict[str, OptionProvider] = {}


def register_option_provider(field_type: str, provider: OptionProvider) -> None:
    _OPTION_PROVIDERS[field_type] = provider


def get_option_provider(field_type: str) -> Optional[OptionProvider]:
    _ensure_core()
    return _OPTION_PROVIDERS.get(field_type)


def get_trigger(key: str) -> Optional[TriggerDef]:
    _ensure_core()
    return _TRIGGERS.get(key)


def get_action(key: str) -> Optional[ActionDef]:
    _ensure_core()
    return _ACTIONS.get(key)


def list_triggers() -> List[TriggerDef]:
    _ensure_core()
    return list(_TRIGGERS.values())


def list_actions() -> List[ActionDef]:
    _ensure_core()
    return list(_ACTIONS.values())


# ---- core nodes ("module zero") ----


# ── registry-driven refine callables (plan sprint-4/31, closes A4's F3) ─────
# Moved out of ``entity_events._passes_refine``'s old if-chain (AC-WFP-07) so
# a module trigger's refine logic lives with its own TriggerDef.


def _refine_field_changed(config: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    from app.workflow_engine.entities import attr_for

    wanted = config.get("field")
    if not wanted:
        return False
    # The picker stores a camelCase field key; most emitters' change-diff keys
    # are snake_case model attrs, but some (omnichannel_contact, AC-CDM-23)
    # deliberately emit wire camelCase (incl. dotted `customFields.<key>`).
    # Canonicalize BOTH sides through the SAME `attr_for` (plan-25 B7).
    wanted_attr = attr_for(str(wanted))
    return any(attr_for(str(key)) == wanted_attr for key in (ev.get("changes") or {}))


def _refine_status_changed(config: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    extra = ev.get("extra") or {}
    from_ok = not config.get("fromStatus") or config.get("fromStatus") == extra.get("from_status_id")
    to_ok = not config.get("toStatus") or config.get("toStatus") == extra.get("to_status_id")
    return from_ok and to_ok


def _refine_form_submitted(config: Dict[str, Any], ev: Dict[str, Any]) -> bool:
    wanted = config.get("formId")
    return bool(wanted) and wanted == (ev.get("extra") or {}).get("formId")


_ENTITY_TRIGGER_OUTPUTS = [
    NodeOutput("trigger.record.id", "Record · id"),
    NodeOutput("trigger.action", "Action"),
    NodeOutput("trigger.actor.name", "Actor name"),
    NodeOutput("trigger.actor.email", "Actor email"),
]


def _register_core() -> None:
    from app.workflow_engine.actions.email_send import email_send
    from app.workflow_engine.actions.entity_actions import (
        entity_transition_status,
        entity_update,
    )
    from app.workflow_engine.actions.storage_actions import (
        storage_delete,
        storage_get,
        storage_put,
    )

    register_trigger(
        TriggerDef(
            key="manual",
            label="Manual",
            description="Run on demand from a button (with optional inputs).",
            icon="MousePointerClick",
            category="Triggers",
            fields=[NodeField(key="inputs", label="Run inputs", type="inputs")],
            outputs=[
                NodeOutput("trigger.triggeredBy", "Triggered by"),
                NodeOutput("trigger.actor.name", "Actor name"),
                NodeOutput("trigger.actor.email", "Actor email"),
            ],
        )
    )
    # ---- entity triggers (D7) ----
    register_trigger(
        TriggerDef(
            key="entity.created",
            label="Record created",
            description="Fires when a record of the chosen entity is created.",
            icon="FilePlus2",
            category="Triggers",
            fields=[NodeField(key="entityType", label="Entity", type="entity", required=True)],
            outputs=_ENTITY_TRIGGER_OUTPUTS,
        )
    )
    register_trigger(
        TriggerDef(
            key="entity.updated",
            label="Record updated",
            description="Fires when a record of the chosen entity is updated.",
            icon="FilePenLine",
            category="Triggers",
            fields=[NodeField(key="entityType", label="Entity", type="entity", required=True)],
            outputs=[*_ENTITY_TRIGGER_OUTPUTS, NodeOutput("trigger.changedFields", "Changed fields")],
        )
    )
    register_trigger(
        TriggerDef(
            key="entity.deleted",
            label="Record deleted",
            description="Fires when a record of the chosen entity is deleted.",
            icon="FileX",
            category="Triggers",
            fields=[NodeField(key="entityType", label="Entity", type="entity", required=True)],
            outputs=_ENTITY_TRIGGER_OUTPUTS,
        )
    )
    register_trigger(
        TriggerDef(
            key="entity.field_changed",
            label="Field changed",
            description="Fires when a specific field on the chosen entity changes.",
            icon="PencilLine",
            category="Triggers",
            fields=[
                NodeField(key="entityType", label="Entity", type="entity", required=True),
                NodeField(key="field", label="Field", type="field", required=True),
            ],
            outputs=[*_ENTITY_TRIGGER_OUTPUTS, NodeOutput("trigger.changedFields", "Changed fields")],
            refine=_refine_field_changed,
        )
    )
    register_trigger(
        TriggerDef(
            key="entity.status_changed",
            label="Status changed",
            description="Fires when the chosen entity moves between statuses.",
            icon="Activity",
            category="Triggers",
            fields=[
                NodeField(key="entityType", label="Entity", type="entity", required=True, entity_filter="status"),
                NodeField(key="fromStatus", label="From status", type="status"),
                NodeField(key="toStatus", label="To status", type="status"),
            ],
            outputs=[
                NodeOutput("trigger.record.id", "Record · id"),
                NodeOutput("trigger.fromStatus", "From status"),
                NodeOutput("trigger.toStatus", "To status"),
                NodeOutput("trigger.actor.name", "Actor name"),
            ],
            refine=_refine_status_changed,
        )
    )
    # Plan sprint-4/27 (A3, D-A3-5/D-A3-10) - a GENERIC "run this workflow
    # against ONE record" trigger, fired from that record's own UI (an agent
    # clicking Shortcuts on the omnichannel conversation drawer is the first
    # consumer). Any entity that opts in via `WorkflowEntity.supports_shortcut`
    # may use it - the `entityFilter="shortcut"` restricts the entity picker
    # to those entities the same way `entity.status_changed` restricts to
    # status-engine entities. A shortcut always executes the PUBLISHED version
    # through `create_run_for_event` (never the draft) - see `WorkflowService.
    # run_shortcut` + `app/workflow_engine/entity_events.py`.
    register_trigger(
        TriggerDef(
            key="entity.shortcut",
            label="Shortcut",
            description="Fires when an agent runs this workflow as a shortcut on a record.",
            icon="Zap",
            category="Triggers",
            fields=[
                NodeField(
                    key="entityType", label="Entity", type="entity", required=True, entity_filter="shortcut"
                )
            ],
            outputs=_ENTITY_TRIGGER_OUTPUTS,
        )
    )
    register_trigger(
        TriggerDef(
            key="schedule.cron",
            label="Schedule",
            description="Runs on a recurring schedule in a chosen timezone.",
            icon="CalendarClock",
            category="Triggers",
            fields=[NodeField(key="cron", label="Runs", type="cron", required=True)],
            outputs=[NodeOutput("trigger.firedAt", "Fired at")],
        )
    )
    # slice sprint-3/02 - a form submission starts a workflow. The form is picked
    # via a searchable `form` field; `trigger.answers.<key>` outputs are dynamic
    # per selected form (the frontend resolves them from /workflows/metadata).
    register_trigger(
        TriggerDef(
            key="form.submitted",
            label="Form submitted",
            description="Fires when a chosen form receives a submission.",
            icon="ClipboardCheck",
            category="Triggers",
            fields=[NodeField(key="formId", label="Form", type="form", required=True)],
            outputs=[
                NodeOutput("trigger.formId", "Form id"),
                NodeOutput("trigger.submissionId", "Submission id"),
            ],
            event_action="submitted",
            event_entity_type="form_submission",
            refine=_refine_form_submitted,
        )
    )
    register_action(
        ActionDef(
            key="email.send",
            label="Send email",
            description="Render a template and enqueue it to the outbox.",
            icon="Mail",
            category="Actions",
            executor=email_send,
            requires_connection="email",
            fields=[
                NodeField(
                    key="mode",
                    label="Email type",
                    type="select",
                    options=[
                        {"value": "template", "label": "Use a template"},
                        {"value": "custom", "label": "Write a custom email"},
                    ],
                ),
                NodeField(key="templateId", label="Template", type="template", required=True, show_when=("mode", "template")),
                NodeField(key="subject", label="Subject", type="text", required=True, mergeable=True, show_when=("mode", "custom")),
                NodeField(key="body", label="Body", type="textarea", required=True, mergeable=True, show_when=("mode", "custom")),
                NodeField(key="to", label="To", type="text", required=True, mergeable=True),
                NodeField(key="subjectOverride", label="Subject override", type="text", mergeable=True, show_when=("mode", "template")),
            ],
            outputs=[NodeOutput("messageId", "Message id"), NodeOutput("status", "Enqueue status")],
        )
    )
    # ---- storage actions (D8) ----
    register_action(
        ActionDef(
            key="storage.put",
            label="Store a file",
            description="Write content to storage and output its URL + metadata.",
            icon="HardDriveUpload",
            category="Actions",
            executor=storage_put,
            requires_connection="storage",
            fields=[
                NodeField(key="key", label="Storage key", type="text", required=True, mergeable=True),
                NodeField(key="content", label="Content", type="textarea", required=True, mergeable=True),
            ],
            outputs=[
                NodeOutput("url", "URL"),
                NodeOutput("key", "Key"),
                NodeOutput("size", "Size (bytes)"),
                NodeOutput("mime", "MIME type"),
            ],
        )
    )
    register_action(
        ActionDef(
            key="storage.get",
            label="Resolve a file",
            description="Resolve a stored key to a URL + metadata (no bytes loaded).",
            icon="HardDriveDownload",
            category="Actions",
            executor=storage_get,
            requires_connection="storage",
            fields=[NodeField(key="key", label="Storage key", type="text", required=True, mergeable=True)],
            outputs=[
                NodeOutput("url", "URL"),
                NodeOutput("size", "Size (bytes)"),
                NodeOutput("mime", "MIME type"),
            ],
        )
    )
    register_action(
        ActionDef(
            key="storage.delete",
            label="Delete a file",
            description="Permanently delete a stored object by key.",
            icon="Trash2",
            category="Actions",
            executor=storage_delete,
            requires_connection="storage",
            destructive=True,
            fields=[NodeField(key="key", label="Storage key", type="text", required=True, mergeable=True)],
            outputs=[NodeOutput("deleted", "Deleted")],
        )
    )
    # ---- entity actions (D8) ----
    register_action(
        ActionDef(
            key="entity.transition_status",
            label="Change status",
            description="Move a record to a status through its state machine.",
            icon="ArrowLeftRight",
            category="Actions",
            executor=entity_transition_status,
            destructive=True,
            fields=[
                NodeField(key="entityType", label="Entity", type="entity", required=True, entity_filter="status"),
                NodeField(key="recordId", label="Record", type="text", required=True, mergeable=True),
                NodeField(key="toStatus", label="Move to status", type="status", required=True),
            ],
            outputs=[NodeOutput("status", "New status"), NodeOutput("recordId", "Record id")],
        )
    )
    register_action(
        ActionDef(
            key="entity.update",
            label="Update a record",
            description="Patch fields on a record of the chosen entity.",
            icon="PencilLine",
            category="Actions",
            executor=entity_update,
            destructive=True,
            fields=[
                NodeField(key="entityType", label="Entity", type="entity", required=True),
                NodeField(key="recordId", label="Record", type="text", required=True, mergeable=True),
                NodeField(key="assignments", label="Set fields", type="assignments", required=True),
            ],
            outputs=[NodeOutput("recordId", "Record id")],
        )
    )
    # ---- review engine actions (sprint-4/06 Part B) ----
    from app.review_engine.actions import register_review_actions

    register_review_actions()

    # ---- AI Agent action (sprint-4/17) ----
    from app.workflow_engine.actions.ai_agent_actions import ai_agent_run
    from app.workflow_engine.actions.agent_state_actions import clear_agent_state, read_agent_state

    register_action(
        ActionDef(
            key="ai_agent.run",
            label="AI Agent",
            description="Send content to an AI agent and capture structured output.",
            icon="Sparkles",
            category="Actions",
            executor=ai_agent_run,
            fields=[
                NodeField(key="agentId", label="Agent", type="aiAgent", required=True),
                NodeField(
                    key="instructions",
                    label="Instructions",
                    type="textarea",
                    mergeable=True,
                    required=True,
                ),
                NodeField(
                    key="inputText",
                    label="Message",
                    type="textarea",
                    mergeable=True,
                    required=True,
                ),
                NodeField(
                    key="outputParams",
                    label="Output parameters",
                    type="outputSchema",
                    required=True,
                ),
                NodeField(
                    key="clarificationOutputKey",
                    label="Clarification output",
                    type="clarificationOutput",
                ),
            ],
            # Dynamic - the frontend lists config.outputParams as nodes.<id>.<key>
            # (mirrors how entity/form triggers already inject dynamic outputs).
            outputs=[],
        )
    )
    register_action(
        ActionDef(
            key="ai_agent.clear_state",
            label="Clear Agent State",
            description="Clear retained values from an earlier AI Agent.",
            icon="Eraser",
            category="Actions",
            executor=clear_agent_state,
            fields=[NodeField(key="agentNodeId", label="Agent", type="agentNode", required=True)],
            outputs=[
                NodeOutput("cleared", "Cleared"),
                NodeOutput("previousRevision", "Previous revision"),
            ],
        )
    )
    register_action(
        ActionDef(
            key="ai_agent.read_state",
            label="Read Agent State",
            description="Read the current saved values from an earlier AI Agent.",
            icon="BookOpen",
            category="Actions",
            executor=read_agent_state,
            fields=[NodeField(key="agentNodeId", label="Agent", type="agentNode", required=True)],
            # Per-agent stateful fields are dynamic - the frontend resolves
            # config.agentNodeId to the referenced node's stateful output
            # params (mirrors ai_agent.run's dynamic outputs).
            outputs=[
                NodeOutput("stateRevision", "State revision"),
                NodeOutput("pendingField", "Pending field"),
                NodeOutput("exists", "State exists"),
            ],
        )
    )

    # ---- Generic Redis data action (sprint-4/19 S3) ----
    from app.workflow_engine.actions.redis_actions import redis_command

    _list_end_options = [{"value": "left", "label": "Left"}, {"value": "right", "label": "Right"}]
    register_action(
        ActionDef(
            key="redis.command",
            label="Redis",
            description="Read or mutate a value in the workflow data store.",
            icon="Database",
            category="Actions",
            executor=redis_command,
            fields=[
                NodeField(
                    key="operation",
                    label="Operation",
                    type="select",
                    required=True,
                    options=[
                        {"value": "get", "label": "Get"},
                        {"value": "set", "label": "Set"},
                        {"value": "delete", "label": "Delete"},
                        {"value": "increment", "label": "Increment"},
                        {"value": "list_push", "label": "List Push"},
                        {"value": "list_pop", "label": "List Pop"},
                        {"value": "list_length", "label": "List Length"},
                    ],
                ),
                NodeField(key="key", label="Key", type="text", required=True, mergeable=True),
                # A field may be listed once per operation that shows it - the
                # publish gate skips entries whose show_when does not match.
                NodeField(key="value", label="Value", type="text", required=True, mergeable=True, show_when=("operation", "set")),
                NodeField(key="value", label="Value", type="text", required=True, mergeable=True, show_when=("operation", "list_push")),
                NodeField(key="amount", label="Amount", type="text", required=True, mergeable=True, show_when=("operation", "increment")),
                NodeField(key="end", label="List end", type="select", options=_list_end_options, show_when=("operation", "list_push")),
                NodeField(key="end", label="List end", type="select", options=_list_end_options, show_when=("operation", "list_pop")),
                NodeField(key="ttlSeconds", label="TTL seconds", type="text", mergeable=True, show_when=("operation", "set")),
            ],
            outputs=[
                NodeOutput("value", "Value"),
                NodeOutput("stored", "Stored"),
                NodeOutput("deleted", "Deleted"),
                NodeOutput("length", "Length"),
            ],
        )
    )

    # ---- workflow.trigger (sprint-4/31 S2, AC-WFP-33) ----
    from app.workflow_engine.actions.workflow_trigger_actions import workflow_trigger

    register_action(
        ActionDef(
            key="workflow.trigger",
            label="Trigger another workflow",
            description="Start another published workflow for this contact.",
            icon="Workflow",
            category="Actions",
            executor=workflow_trigger,
            fields=[
                NodeField(key="workflowId", label="Workflow", type="workflowRef", required=True),
                NodeField(key="contactId", label="Contact", type="text", mergeable=True),
                NodeField(key="payload", label="Payload (JSON)", type="textarea", mergeable=True),
            ],
            outputs=[NodeOutput("runId", "Run id"), NodeOutput("workflowId", "Workflow id")],
        )
    )

    # ---- http.request (plan sprint-4/31 S5, AC-WFP-57..62, gated workflows.http) ----
    from app.workflow_engine.actions.http_actions import http_request

    register_action(
        ActionDef(
            key="http.request",
            label="HTTP request",
            description="Call an external HTTPS endpoint and capture the response.",
            icon="Globe",
            category="Actions",
            executor=http_request,
            # D-A5-12: an API-key-free outbound HTTP call is the same blast
            # radius as a Code node - gated the same way (`workflows.code`).
            permission="workflows.http",
            fields=[
                NodeField(
                    key="method",
                    label="Method",
                    type="select",
                    required=True,
                    options=[
                        {"value": "GET", "label": "GET"},
                        {"value": "POST", "label": "POST"},
                        {"value": "PUT", "label": "PUT"},
                        {"value": "PATCH", "label": "PATCH"},
                        {"value": "DELETE", "label": "DELETE"},
                    ],
                ),
                NodeField(key="url", label="URL", type="text", required=True, mergeable=True),
                # Deliberately NOT `mergeable=True` (plan risk "Header
                # secrets") - the generic `_node_input_json` trace helper only
                # renders fields flagged mergeable, so header VALUES never
                # reach the run trace even though the executor merge-renders
                # them at request time (AC-WFP-59). `redacted=True` closes the
                # LITERAL-secret gap the merge-token convention alone missed
                # (review B1): the raw `config` `_node_input_json` always
                # stores gets its header VALUES masked before it is written,
                # regardless of whether the author typed a merge token or a
                # literal value.
                NodeField(key="headers", label="Headers", type="keyValue", redacted=True),
                NodeField(
                    key="bodyMode",
                    label="Body",
                    type="select",
                    options=[
                        {"value": "none", "label": "No body"},
                        {"value": "json", "label": "JSON"},
                        {"value": "text", "label": "Text"},
                    ],
                ),
                NodeField(
                    key="body",
                    label="Body content",
                    type="textarea",
                    mergeable=True,
                    show_when=("bodyMode", ("json", "text")),
                ),
                NodeField(
                    key="timeoutSeconds",
                    label="Timeout (seconds)",
                    type="select",
                    options=[
                        {"value": "5", "label": "5"},
                        {"value": "10", "label": "10"},
                        {"value": "20", "label": "20"},
                        {"value": "30", "label": "30"},
                    ],
                ),
            ],
            outputs=[
                NodeOutput("statusCode", "Status code"),
                NodeOutput("ok", "Ok"),
                NodeOutput("body", "Body"),
                NodeOutput("json", "JSON (dotted path)"),
                NodeOutput("durationMs", "Duration (ms)"),
            ],
        )
    )

    # ---- Sandboxed Code action (sprint-4/19 S4) ----
    from app.workflow_engine.actions.code_actions import code_run

    register_action(
        ActionDef(
            key="code.run",
            label="Code",
            description="Transform mapped values with restricted Python.",
            icon="Code2",
            category="Actions",
            executor=code_run,
            # Plan sprint-4/31 S5 (closes BL-SS-121): `workflows.code` now
            # flows through the SAME generic `ActionDef.permission` seam
            # `http.request`'s `workflows.http` uses - `assert_node_permissions`
            # (nee `assert_code_permitted`)/`required_node_permissions` no
            # longer special-case `code.run` by
            # name. The `code_authorized_by` publish-time stamp (below, via
            # `has_code_nodes`) is a SEPARATE, additional Code-only mechanism
            # (it also captures runner-health-at-publish-time for the
            # event/scheduled-trigger path, which a permission check alone
            # cannot) - not replaced by this.
            permission="workflows.code",
            fields=[
                NodeField(key="language", label="Language", type="select", required=True, options=[{"value": "python", "label": "Python"}]),
                NodeField(key="source", label="Python", type="code", required=True),
                NodeField(key="inputs", label="Input mappings", type="codeInputs"),
                NodeField(key="outputs", label="Output parameters", type="outputSchema", required=True),
            ],
            # Dynamic - the frontend lists config.outputs as nodes.<id>.<key>.
            outputs=[],
        )
    )


_ensure_core = lazy_once(_register_core)
