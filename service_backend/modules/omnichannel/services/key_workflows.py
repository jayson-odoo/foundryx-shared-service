"""Workflows under the API key (plan 38 gap 7, S1: ownership and CRUD).

A key reaches only the workflows its own workspace owns (``workflow_owners``).
Tenant and workspace come from the key and nowhere else. Every miss, for any
reason, is the same ``404 not_found``. The workflow itself is created, edited
and archived by the core ``WorkflowService`` with ``actor=None`` and
``actor_id="apikey:<keyId>"``.
"""
import copy
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.models.status import Status as CoreStatus
from app.models.workflow import Workflow
from app.services.workflow_service import (
    ShortcutCodeNotAuthorized,
    ShortcutNotFound,
    ShortcutSerializationConflict,
    WorkflowService,
)
from app.workflow_engine.actions.http_actions import is_forbidden_header_name
from app.workflow_engine.executor import RunRefused, register_run_guard
from app.workflow_engine.registry import (
    get_action,
    get_trigger,
    list_actions,
    list_triggers,
)
from app.workflow_engine.schemas import definition_issues, parse_definition

from ..models import (
    Channel,
    CloseReason,
    Contact,
    ContactField,
    ContactTag,
    WhatsappTemplate,
    WorkflowOwner,
    Workspace,
    WorkspaceMember,
)
from ..repositories.workflow_owner_repository import (
    InvalidCursor,
    WorkflowOwnerRepository,
    decode_cursor,
    decode_number_cursor,
    encode_cursor,
    encode_number_cursor,
)
from ..schemas import (
    PublicCatalogResponse,
    PublicValidateResponse,
    PublicWorkflowItem,
    PublicWorkflowListResponse,
    PublicWorkflowRunDetail,
    PublicWorkflowRunItem,
    PublicWorkflowRunListResponse,
    PublicWorkflowRunNode,
    PublicWorkflowVersionItem,
    PublicWorkflowVersionListResponse,
)
from . import lifecycle_service
from .business_hours import BusinessHoursService, BusinessHoursValidationError
from .public_gateway_service import PublicGatewayService

MAX_OWNED_WORKFLOWS = 200
MAX_DEFINITION_NODES = 200
KEY_SCHEMA_VERSION = 1
SHORTCUT_ENTITY = "omnichannel_contact"
MAX_RUN_INPUTS = 20
MAX_RUN_INPUT_VALUE = 1000
_INPUT_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")

# The node types an API key may put in a workflow. Fails closed: a node type
# registered later stays off until it is added here on purpose.
KEY_WORKFLOW_NODE_TYPES = frozenset(
    {
        # triggers
        "omnichannel.message_received",
        "omnichannel.conversation_opened",
        "omnichannel.conversation_closed",
        "omnichannel.conversation_assigned",
        "omnichannel.contact_tag_added",
        "omnichannel.contact_tag_removed",
        "omnichannel.contact_field_changed",
        "omnichannel.lifecycle_changed",
        "omnichannel.broadcast_completed",
        "entity.shortcut",  # only with entityType == SHORTCUT_ENTITY
        # actions
        "omnichannel.get_contact",
        "omnichannel.send_message",
        "omnichannel.add_tag",
        "omnichannel.remove_tag",
        "omnichannel.update_field",
        "omnichannel.update_lifecycle",
        "omnichannel.open_conversation",
        "omnichannel.close_conversation",
        "omnichannel.add_comment",
        "omnichannel.ask_question",
        "omnichannel.wait",
        "omnichannel.business_hours",
        "http.request",
        # built-in branch node
        "if",
    }
)


def actor_id_for_key(key_id: str) -> str:
    return f"apikey:{key_id}"


def workflow_not_found() -> ApiError:
    """One body for every reason a workflow is not reachable by this key."""
    return ApiError(404, "not_found", "Workflow not found.")


def public_workflow_item(wf: Workflow) -> PublicWorkflowItem:
    return PublicWorkflowItem(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        isActive=bool(wf.is_active),
        publishedVersionId=wf.current_version_id,
        triggerType=wf.trigger_type,
        draftDefinition=wf.draft_definition_json or {},
        createdBy=wf.created_by or "",
        createdAt=wf.created_at,
        updatedAt=wf.updated_at,
    )


@dataclass
class DefinitionIssue:
    code: str  # node_not_allowed | invalid_definition | invalid_request
    message: str
    node_id: Optional[str] = None
    field: Optional[str] = None
    node_type: Optional[str] = None

    def to_error(self) -> ApiError:
        details: Dict[str, Any] = {}
        if self.node_id is not None:
            details["nodeId"] = self.node_id
        if self.node_type is not None:
            details["nodeType"] = self.node_type
        if self.field is not None:
            details["field"] = self.field
        return ApiError(422, self.code, self.message, details or None)


def _is_merged(value: Any) -> bool:
    return isinstance(value, str) and "{{" in value


def _literal(config: Dict[str, Any], key: str) -> Optional[str]:
    """A literal string id in a node config, or None (absent, empty, not text,
    or carrying a merge token, which is checked at run instead)."""
    value = config.get(key)
    if not isinstance(value, str) or not value.strip() or _is_merged(value):
        return None
    return value.strip()


def allow_list_issues(doc: Any) -> List[DefinitionIssue]:
    """Every node of a parsed definition whose type is off the allow-list."""
    out: List[DefinitionIssue] = []
    for node in doc.nodes:
        allowed = node.type in KEY_WORKFLOW_NODE_TYPES
        if allowed and node.type == "entity.shortcut":
            allowed = node.config.get("entityType") == SHORTCUT_ENTITY
        if not allowed:
            out.append(
                DefinitionIssue(
                    "node_not_allowed",
                    f'Node "{node.id}" has type "{node.type}", which an API key cannot use.',
                    node_id=node.id,
                    node_type=node.type,
                )
            )
    return out


def _workspace_field_key(node_type: str) -> Optional[str]:
    """The key of a trigger's own workspace field, when it has one."""
    trigger = get_trigger(node_type)
    if trigger is None:
        return None
    for f in trigger.fields:
        if f.type == "omnichannelWorkspace":
            return f.key
    return None


def stamp_trigger_workspace(definition: Dict[str, Any], workspace_id: str) -> Dict[str, Any]:
    """A copy of the definition whose workspace-bearing triggers name the key's
    own workspace (set when absent or merged; a literal other workspace is
    refused by the pinning check)."""
    stamped = copy.deepcopy(definition)
    for node in stamped.get("nodes") or []:
        if not isinstance(node, dict) or node.get("kind") != "trigger":
            continue
        key = _workspace_field_key(str(node.get("type") or ""))
        if key is None:
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            config = {}
            node["config"] = config
        if _literal(config, key) is None:
            config[key] = workspace_id
    return stamped


def pinning_issues(
    db: Session, tenant_id: str, workspace_id: str, doc: Any
) -> List[DefinitionIssue]:
    """Every literal id in a node config must belong to the key's workspace.
    Every lookup carries the tenant and the workspace."""
    out: List[DefinitionIssue] = []

    def outside(node: Any, key: str) -> None:
        out.append(
            DefinitionIssue(
                "invalid_definition",
                f'Node "{node.id}": {key} is not in this workspace.',
                node_id=node.id,
                field=key,
            )
        )

    def exists(model: Any, *conds: Any) -> bool:
        return db.query(model.id).filter(*conds).first() is not None

    for node in doc.nodes:
        definition = get_trigger(node.type) if node.kind == "trigger" else get_action(node.type)
        if definition is None:
            continue
        for f in definition.fields:
            value = _literal(node.config, f.key)
            if value is None:
                continue
            ok = True
            if f.type == "omnichannelWorkspace":
                ok = value == workspace_id
            elif f.type == "omnichannelChannel":
                ok = exists(
                    Channel,
                    Channel.id == value,
                    Channel.tenant_id == tenant_id,
                    Channel.workspace_id == workspace_id,
                )
            elif f.type == "omnichannelTag":
                ok = exists(
                    ContactTag,
                    ContactTag.id == value,
                    ContactTag.tenant_id == tenant_id,
                    ContactTag.workspace_id == workspace_id,
                )
            elif f.type == "omnichannelContactField":
                ok = exists(
                    ContactField,
                    ContactField.key == value,
                    ContactField.tenant_id == tenant_id,
                    ContactField.workspace_id == workspace_id,
                )
            elif f.type == "omnichannelLifecycleStage":
                ok = exists(
                    CoreStatus,
                    CoreStatus.id == value,
                    CoreStatus.tenant_id == tenant_id,
                    CoreStatus.entity_type == lifecycle_service.ENTITY_TYPE,
                    CoreStatus.scope_id == workspace_id,
                )
            elif f.type == "omnichannelCloseReason":
                ok = exists(
                    CloseReason,
                    CloseReason.id == value,
                    CloseReason.tenant_id == tenant_id,
                    CloseReason.workspace_id == workspace_id,
                )
            elif f.type == "omnichannelMember":
                ok = exists(
                    WorkspaceMember,
                    WorkspaceMember.user_id == value,
                    WorkspaceMember.tenant_id == tenant_id,
                    WorkspaceMember.workspace_id == workspace_id,
                )
            elif f.type == "whatsappTemplate":
                ok = (
                    db.query(WhatsappTemplate.id)
                    .join(Channel, Channel.id == WhatsappTemplate.channel_id)
                    .filter(
                        WhatsappTemplate.id == value,
                        WhatsappTemplate.tenant_id == tenant_id,
                        Channel.tenant_id == tenant_id,
                        Channel.workspace_id == workspace_id,
                    )
                    .first()
                    is not None
                )
            elif f.key == "contactId" and node.type.startswith("omnichannel."):
                ok = exists(
                    Contact,
                    Contact.id == value,
                    Contact.tenant_id == tenant_id,
                    Contact.workspace_id == workspace_id,
                )
            if not ok:
                outside(node, f.key)
    return out


def header_issues(doc: Any) -> List[DefinitionIssue]:
    """An `http.request` node may not set a header that changes the framing or
    the route of the request (the run refuses these too, for every caller)."""
    out: List[DefinitionIssue] = []
    for node in doc.nodes:
        if node.type != "http.request":
            continue
        rows = node.config.get("headers")
        for row in rows if isinstance(rows, list) else []:
            name = str(row.get("key") or "").strip() if isinstance(row, dict) else ""
            if name and is_forbidden_header_name(name):
                out.append(
                    DefinitionIssue(
                        "invalid_definition",
                        f'Node "{node.id}": the header "{name}" cannot be set.',
                        node_id=node.id,
                        field="headers",
                    )
                )
    return out


def _gate_issues(doc: Any, workflow_id: Optional[str] = None) -> List[DefinitionIssue]:
    return [
        DefinitionIssue("invalid_definition", message)
        for message in definition_issues(doc, workflow_id=workflow_id)
    ]


def _shape_issues(definition: Any) -> List[DefinitionIssue]:
    """schemaVersion and the node cap, on the raw document."""
    out: List[DefinitionIssue] = []
    if not isinstance(definition, dict) or definition.get("schemaVersion") != KEY_SCHEMA_VERSION:
        out.append(
            DefinitionIssue(
                "invalid_definition", f"schemaVersion must be {KEY_SCHEMA_VERSION}.", field="schemaVersion"
            )
        )
    nodes = definition.get("nodes") if isinstance(definition, dict) else None
    if isinstance(nodes, list) and len(nodes) > MAX_DEFINITION_NODES:
        out.append(
            DefinitionIssue(
                "invalid_request", f"A workflow can have at most {MAX_DEFINITION_NODES} nodes."
            )
        )
    return out


def _parse(definition: Dict[str, Any]) -> Any:
    try:
        return parse_definition(definition)
    except ValidationError:
        raise ApiError(422, "invalid_request", "draftDefinition is not a valid workflow definition.")


def check_for_save(
    db: Session, tenant_id: str, workspace_id: str, definition: Dict[str, Any]
) -> Dict[str, Any]:
    """The save gate (create, update): shape, schemaVersion, node cap,
    allow-list, pinning. Returns the definition with the trigger workspace
    stamped. Raises the first problem."""
    shape = _shape_issues(definition)
    doc = _parse(definition)
    if shape:
        raise shape[0].to_error()
    issues = allow_list_issues(doc)
    if issues:
        raise issues[0].to_error()
    stamped = stamp_trigger_workspace(definition, workspace_id)
    stamped_doc = _parse(stamped)
    issues = pinning_issues(db, tenant_id, workspace_id, stamped_doc)
    issues += header_issues(stamped_doc)
    if issues:
        raise issues[0].to_error()
    return stamped


def run_item(run: Any) -> PublicWorkflowRunItem:
    return PublicWorkflowRunItem(
        id=run.id,
        workflowId=run.workflow_id,
        status=run.status,
        triggeredBy=run.triggered_by,
        actorId=run.actor_id,
        error=run.error,
        startedAt=run.started_at,
        finishedAt=run.finished_at,
    )


def check_run_inputs(inputs: Any) -> Dict[str, str]:
    """AC-38-141: at most 20 keys, identifier-shaped keys, string values of at
    most 1000 characters. Anything else is a 422 and no run is created."""
    if inputs is None:
        return {}

    def bad(message: str) -> ApiError:
        return ApiError(422, "invalid_request", message)

    if not isinstance(inputs, dict):
        raise bad("inputs must be an object of text values.")
    if len(inputs) > MAX_RUN_INPUTS:
        raise bad(f"inputs can have at most {MAX_RUN_INPUTS} keys.")
    for key, value in inputs.items():
        if not isinstance(key, str) or _INPUT_KEY_RE.fullmatch(key) is None:
            raise bad("An inputs key must start with a letter and use letters, digits and underscores (40 at most).")
        if not isinstance(value, str) or len(value) > MAX_RUN_INPUT_VALUE:
            raise bad(f"An inputs value must be text of at most {MAX_RUN_INPUT_VALUE} characters.")
    return dict(inputs)


def _not_runnable(reason: str) -> ApiError:
    return ApiError(
        409, "workflow_not_runnable", f"This workflow cannot be run now: {reason}.", {"reason": reason}
    )


def _to_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


# ── catalog ──────────────────────────────────────────────────────────────────
_IF_CONDITION_FORMAT: Dict[str, Any] = {
    "configKey": "conditions",
    "type": "group",
    "combinator": ["and", "or"],
    "rule": {"kind": "condition", "field": "<merge path, e.g. trigger.message.text>", "operator": "<operator>", "value": "<value>"},
    "example": {
        "kind": "group",
        "combinator": "and",
        "rules": [
            {"kind": "condition", "field": "trigger.message.text", "operator": "contains", "value": "hello"}
        ],
    },
    "ports": ["true", "false"],
}


def _shortcut_entity_options() -> List[Dict[str, str]]:
    return [{"value": SHORTCUT_ENTITY, "label": "Contact"}]


def _field_item(f: Any, options: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    show_when = None
    if f.show_when is not None:
        controlling, wanted = f.show_when
        show_when = {"field": controlling, "value": list(wanted) if isinstance(wanted, tuple) else wanted}
    return {
        "key": f.key,
        "label": f.label,
        "type": f.type,
        "required": bool(f.required),
        "options": f.options if options is None else options,
        "showWhen": show_when,
        "mergeable": bool(f.mergeable),
    }


def _node_item(kind: str, d: Any, members: List[Dict[str, str]]) -> Dict[str, Any]:
    def options_for(f: Any) -> Optional[List[Dict[str, Any]]]:
        if d.key == "entity.shortcut" and f.key == "entityType":
            return _shortcut_entity_options()
        if f.type == "omnichannelMember":
            return members
        return None

    return {
        "type": d.key,
        "kind": kind,
        "label": d.label,
        "description": d.description,
        "fields": [_field_item(f, options_for(f)) for f in d.fields],
        "outputs": [{"key": o.key, "label": o.label} for o in d.outputs],
    }


def register_key_workflow_run_guard() -> None:
    """Hold an owned workflow's runs to the allow-list at run start, whoever
    published the version. Idempotent."""
    register_run_guard(_owned_run_guard)


def _owned_run_guard(db: Session, run: Any, doc: Any) -> None:
    owner_ws = (
        db.query(WorkflowOwner.workspace_id)
        .filter(WorkflowOwner.tenant_id == run.tenant_id, WorkflowOwner.workflow_id == run.workflow_id)
        .scalar()
    )
    if owner_ws is None:
        return
    issues = allow_list_issues(doc)
    if issues:
        raise RunRefused("node_not_allowed", issues[0].message)
    # A run started by another workflow (a staff `workflow.trigger` step) can
    # carry any contact of the tenant: the contact must be in the owner workspace.
    payload = run.trigger_payload_json or {}
    event_extra = payload.get("omnichannel") if isinstance(payload.get("omnichannel"), dict) else {}
    facts = payload.get("recordFacts") if isinstance(payload.get("recordFacts"), dict) else {}
    # The workspace the trigger event names must be the owner's, whoever
    # started the run (an event, a staff test run or a parent workflow).
    for named in (event_extra.get("workspaceId"), facts.get("record.workspaceId")):
        if named and named != owner_ws:
            raise RunRefused(
                "record_not_in_workspace", "The event is outside this workflow's workspace."
            )
    contact_ids = {str(c) for c in (payload.get("recordId"), event_extra.get("contactId")) if c}
    for contact_id in contact_ids:
        contact_ws = (
            db.query(Contact.workspace_id)
            .filter(Contact.id == contact_id, Contact.tenant_id == run.tenant_id)
            .scalar()
        )
        if contact_ws is not None and contact_ws != owner_ws:
            raise RunRefused(
                "record_not_in_workspace", "The contact is outside this workflow's workspace."
            )


class KeyWorkflowService:
    def __init__(self, db: Session):
        self.db = db
        self.owners = WorkflowOwnerRepository(db)
        self.workflows = WorkflowService(db)

    def _owned_or_404(self, tenant_id: str, workspace_id: str, workflow_id: str) -> Workflow:
        wf = self.owners.get_owned(tenant_id, workspace_id, workflow_id)
        if wf is None:
            raise workflow_not_found()
        return wf

    def list(
        self,
        tenant_id: str,
        workspace_id: str,
        *,
        limit: int,
        cursor: Optional[str],
    ) -> PublicWorkflowListResponse:
        position = None
        if cursor:
            try:
                position = decode_cursor(cursor)
            except InvalidCursor:
                raise ApiError(422, "invalid_request", "cursor is not valid.")
        rows, nxt = self.owners.list_owned(tenant_id, workspace_id, limit=limit, cursor=position)
        return PublicWorkflowListResponse(
            data=[public_workflow_item(w) for w in rows],
            nextCursor=encode_cursor(*nxt) if nxt else None,
        )

    def get(self, tenant_id: str, workspace_id: str, workflow_id: str) -> PublicWorkflowItem:
        return public_workflow_item(self._owned_or_404(tenant_id, workspace_id, workflow_id))

    def create(
        self,
        tenant_id: str,
        workspace_id: str,
        key_id: str,
        *,
        name: str,
        description: str,
        definition: Dict[str, Any],
    ) -> PublicWorkflowItem:
        definition = check_for_save(self.db, tenant_id, workspace_id, definition)
        actor_id = actor_id_for_key(key_id)
        # Serialise creates in this workspace so the count below stays true.
        # The lock is held until the commit inside the core create, and the
        # owner row is written in that same flush, so count and insert are one
        # unit. FOR NO KEY UPDATE: do not wait on child-row inserts.
        self.db.query(Workspace).filter(
            Workspace.id == workspace_id, Workspace.tenant_id == tenant_id
        ).with_for_update(key_share=True).first()
        if self.owners.count_owned(tenant_id, workspace_id) >= MAX_OWNED_WORKFLOWS:
            self.db.rollback()
            raise ApiError(
                422,
                "invalid_request",
                f"This workspace already has the maximum of {MAX_OWNED_WORKFLOWS} workflows. "
                "Delete one before adding another.",
            )

        owners = self.owners
        owned: List[str] = []

        def _own_new_workflow(session: Session, _ctx: Any, _instances: Any) -> None:
            for obj in list(session.new):
                if isinstance(obj, Workflow) and obj.tenant_id == tenant_id:
                    if obj.id is None:
                        obj.id = str(uuid.uuid4())
                    owners.add(tenant_id, workspace_id, obj.id, actor_id)
                    owned.append(obj.id)

        def _require_owner(_session: Session) -> None:
            # Fail closed: a workflow is never committed without its owner row.
            if not owned:
                raise RuntimeError("workflow owner row was not written")

        event.listen(self.db, "before_flush", _own_new_workflow, once=True)
        event.listen(self.db, "before_commit", _require_owner, once=True)
        try:
            wf = self.workflows.create(
                tenant_id,
                name=name,
                description=description,
                draft=definition,
                actor_id=actor_id,
                actor=None,
            )
        except Exception:
            self.db.rollback()
            raise
        finally:
            if event.contains(self.db, "before_flush", _own_new_workflow):
                event.remove(self.db, "before_flush", _own_new_workflow)
            if event.contains(self.db, "before_commit", _require_owner):
                event.remove(self.db, "before_commit", _require_owner)
        return public_workflow_item(wf)

    def update(
        self,
        tenant_id: str,
        workspace_id: str,
        workflow_id: str,
        *,
        name: Optional[str],
        description: Optional[str],
        definition: Optional[Dict[str, Any]],
        expected_updated_at: Optional[datetime] = None,
    ) -> PublicWorkflowItem:
        wf = self._owned_or_404(tenant_id, workspace_id, workflow_id)
        if definition is not None:
            definition = check_for_save(self.db, tenant_id, workspace_id, definition)
        # Lock the row so the stamp comparison and the write are one unit.
        locked = (
            self.db.query(Workflow)
            .filter(Workflow.id == wf.id, Workflow.tenant_id == tenant_id)
            .with_for_update()
            .first()
        )
        if locked is None or locked.is_trashed:
            self.db.rollback()
            raise workflow_not_found()
        wf = locked
        if expected_updated_at is not None and wf.updated_at is not None:
            if _to_utc(wf.updated_at) > _to_utc(expected_updated_at):
                self.db.rollback()
                raise ApiError(
                    409, "edit_conflict", "The workflow changed after the copy you edited."
                )
        updated = self.workflows.update(
            wf.id,
            tenant_id,
            name=wf.name if name is None else name,
            description=wf.description if description is None else description,
            draft=wf.draft_definition_json if definition is None else definition,
            actor=None,
        )
        return public_workflow_item(updated)

    def archive(self, tenant_id: str, workspace_id: str, workflow_id: str) -> None:
        wf = self._owned_or_404(tenant_id, workspace_id, workflow_id)
        self.workflows.archive(wf.id, tenant_id)

    # ── validate, publish, catalog ───────────────────────────────────────────
    def validate(
        self, tenant_id: str, workspace_id: str, definition: Dict[str, Any]
    ) -> PublicValidateResponse:
        """Every problem a save or publish would raise, saving nothing."""
        issues = _shape_issues(definition)
        doc = _parse(definition)
        if issues:
            # Same as a save: stop at the first class of problem, so an
            # over-size definition costs no per-node work.
            return self._validate_response(issues)
        issues += allow_list_issues(doc)
        stamped = stamp_trigger_workspace(definition, workspace_id)
        stamped_doc = _parse(stamped)
        issues += pinning_issues(self.db, tenant_id, workspace_id, stamped_doc)
        issues += header_issues(stamped_doc)
        issues += _gate_issues(stamped_doc)
        return self._validate_response(issues)

    @staticmethod
    def _validate_response(issues: List[DefinitionIssue]) -> PublicValidateResponse:
        return PublicValidateResponse(
            valid=not issues,
            issues=[
                {"code": i.code, "message": i.message, "nodeId": i.node_id, "field": i.field}
                for i in issues
            ],
        )

    def publish(
        self, tenant_id: str, workspace_id: str, key_id: str, workflow_id: str
    ) -> PublicWorkflowItem:
        wf = self._owned_or_404(tenant_id, workspace_id, workflow_id)
        doc = _parse(wf.draft_definition_json or {})
        # The allow-list runs before any core call: the core publish has no
        # user here, so it would not gate node types itself.
        issues = allow_list_issues(doc)
        issues += pinning_issues(self.db, tenant_id, workspace_id, doc)
        issues += header_issues(doc)
        issues += _gate_issues(doc, workflow_id=wf.id)
        if issues:
            raise issues[0].to_error()
        published = self.workflows.publish(wf.id, tenant_id, actor_id_for_key(key_id), actor=None)
        return public_workflow_item(published)

    def catalog(self, tenant_id: str, workspace_id: str) -> PublicCatalogResponse:
        # The same per-workspace pickers the dashboard editor reads, built for
        # the key's own workspace only.
        entries = self.workflows._omnichannel_workspace_options(tenant_id, workspace_id=workspace_id)
        entry = entries[0] if entries else {}
        members = [{"value": m["id"], "label": m["name"]} for m in entry.get("members", [])]
        nodes: List[Dict[str, Any]] = []
        for t in list_triggers():
            if t.key in KEY_WORKFLOW_NODE_TYPES:
                nodes.append(_node_item("trigger", t, members))
        for a in list_actions():
            if a.key in KEY_WORKFLOW_NODE_TYPES:
                nodes.append(_node_item("action", a, members))
        nodes.append(
            {
                "type": "if",
                "kind": "if",
                "label": "Condition",
                "description": "Branch the flow. Matching runs take the true path.",
                "fields": [],
                "outputs": [],
                "conditionFormat": _IF_CONDITION_FORMAT,
            }
        )
        channels = (
            self.db.query(Channel.id, Channel.name)
            .filter(
                Channel.tenant_id == tenant_id,
                Channel.workspace_id == workspace_id,
                Channel.is_trashed.is_(False),
                Channel.is_active.is_(True),
            )
            .order_by(Channel.name)
            .all()
        )
        options = {
            "channels": [{"id": c.id, "name": c.name} for c in channels],
            "contactTags": entry.get("contactTags", []),
            "contactFields": entry.get("contactFields", []),
            "lifecycleStages": entry.get("lifecycleStages", []),
            "closeReasons": entry.get("closeReasons", []),
            "templates": entry.get("templates", []),
        }
        return PublicCatalogResponse(nodes=nodes, options=options)

    # ── lifecycle toggles, versions, runs ────────────────────────────────────
    def unpublish(self, tenant_id: str, workspace_id: str, workflow_id: str) -> PublicWorkflowItem:
        wf = self._owned_or_404(tenant_id, workspace_id, workflow_id)
        return public_workflow_item(self.workflows.unpublish(wf.id, tenant_id))

    def set_active(
        self, tenant_id: str, workspace_id: str, workflow_id: str, is_active: bool
    ) -> PublicWorkflowItem:
        wf = self._owned_or_404(tenant_id, workspace_id, workflow_id)
        return public_workflow_item(self.workflows.set_active(wf.id, tenant_id, is_active))

    def list_versions(
        self, tenant_id: str, workspace_id: str, workflow_id: str, *, limit: int, cursor: Optional[str]
    ) -> PublicWorkflowVersionListResponse:
        wf = self._owned_or_404(tenant_id, workspace_id, workflow_id)
        before = None
        if cursor:
            try:
                before = decode_number_cursor(cursor)
            except InvalidCursor:
                raise ApiError(422, "invalid_request", "cursor is not valid.")
        rows, nxt = self.owners.list_versions(tenant_id, wf.id, limit=limit, before_number=before)
        return PublicWorkflowVersionListResponse(
            data=[
                PublicWorkflowVersionItem(
                    id=v.id,
                    versionNumber=v.version_number,
                    publishedAt=v.published_at,
                    publishedBy=v.published_by,
                    definition=v.definition_json or {},
                )
                for v in rows
            ],
            nextCursor=encode_number_cursor(nxt) if nxt is not None else None,
        )

    def list_runs(
        self, tenant_id: str, workspace_id: str, workflow_id: str, *, limit: int, cursor: Optional[str]
    ) -> PublicWorkflowRunListResponse:
        wf = self._owned_or_404(tenant_id, workspace_id, workflow_id)
        position = None
        if cursor:
            try:
                position = decode_cursor(cursor)
            except InvalidCursor:
                raise ApiError(422, "invalid_request", "cursor is not valid.")
        rows, nxt = self.owners.list_runs(tenant_id, wf.id, limit=limit, cursor=position)
        return PublicWorkflowRunListResponse(
            data=[run_item(r) for r in rows],
            nextCursor=encode_cursor(*nxt) if nxt else None,
        )

    def run_detail(self, tenant_id: str, workspace_id: str, run_id: str) -> PublicWorkflowRunDetail:
        run = self.owners.get_owned_run(tenant_id, workspace_id, run_id)
        if run is None:
            raise workflow_not_found()
        # Node input and output are the stored trace rows, which the executor
        # already masked when it wrote them.
        return PublicWorkflowRunDetail(
            **run_item(run).model_dump(),
            nodes=[
                PublicWorkflowRunNode(
                    nodeId=n.node_id,
                    nodeType=n.node_type,
                    status=n.status,
                    input=n.input_json,
                    output=n.output_json,
                    error=n.error,
                )
                for n in run.nodes
            ],
        )

    def run_for_contact(
        self,
        tenant_id: str,
        workspace_id: str,
        key_id: str,
        workflow_id: str,
        *,
        contact: str,
        inputs: Any,
    ) -> PublicWorkflowRunItem:
        """Start the published version of an owned shortcut workflow for one
        contact of the key's workspace. Order: owned, inputs, contact, runnable."""
        wf = self._owned_or_404(tenant_id, workspace_id, workflow_id)
        clean_inputs = check_run_inputs(inputs)
        # Find-only: a miss never creates a contact.
        found = PublicGatewayService(self.db)._resolve_contact(tenant_id, workspace_id, contact)
        if wf.current_version_id is None:
            raise _not_runnable("unpublished")
        if not wf.is_active:
            raise _not_runnable("inactive")
        if wf.trigger_type != "entity.shortcut" or wf.trigger_entity_type != SHORTCUT_ENTITY:
            raise _not_runnable("trigger")
        try:
            run = self.workflows.run_shortcut(
                tenant_id, wf.id, SHORTCUT_ENTITY, found, None,
                inputs=clean_inputs or None, actor_id=actor_id_for_key(key_id),
            )
        except ShortcutNotFound:
            raise _not_runnable("unpublished")
        except ShortcutSerializationConflict:
            raise ApiError(
                422,
                "invalid_request",
                "This workflow needs a value for its run key. Send the input the key is built from.",
            )
        except ShortcutCodeNotAuthorized as exc:
            raise ApiError(
                409, "workflow_not_runnable", str(exc) or "This workflow cannot be run now.",
                {"reason": "trigger"},
            )
        self.db.commit()
        self.db.refresh(run)
        return run_item(run)


def put_business_hours(
    db: Session, tenant_id: str, workspace_id: str, timezone_name: str, windows: Dict[str, Any]
) -> Dict[str, Any]:
    """Set the key's own workspace hours (never the tenant default), validated
    with the dashboard's validators. A refusal writes nothing."""
    try:
        data = BusinessHoursService(db).set(
            tenant_id, workspace_id, timezone=timezone_name, windows=windows
        )
    except BusinessHoursValidationError as exc:
        errors: Dict[str, str] = {}
        for field_key, message in exc.errors.items():
            name = field_key.split(".", 1)[0]
            detail = field_key.split(".", 1)[1] if "." in field_key else ""
            errors.setdefault(name, f"{detail}: {message}" if detail else message)
        raise ApiError(422, "invalid_request", "The business hours are not valid.", {"fieldErrors": errors})
    return {**data, "source": "workspace"}
