"""Node-type registry (plan sprint-2/08 D8) - code-side, like the permissions
CSV / StatusEntity / FactSource registries. Each trigger and action declares its
config schema (drawer), output schema (dynamic-content picker) and - for actions
- an executor + connection requirement. Slice 08 registers ``manual`` +
``email.send``; modules append at install (slice 09 fans out core triggers/actions).
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    # Conditional field: only shown/required when config[field] == value.
    show_when: Optional[Tuple[str, str]] = None
    # For `entity` - restrict the picker (e.g. only status-engine entities).
    entity_filter: Optional[str] = None


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


_TRIGGERS: Dict[str, TriggerDef] = {}
_ACTIONS: Dict[str, ActionDef] = {}


def register_trigger(defn: TriggerDef) -> None:
    _TRIGGERS[defn.key] = defn


def register_action(defn: ActionDef) -> None:
    _ACTIONS[defn.key] = defn


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
