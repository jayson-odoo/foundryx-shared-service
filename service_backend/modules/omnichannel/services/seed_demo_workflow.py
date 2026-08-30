"""DEV-ONLY demo AI workflow (plan sprint-4/17) - mirrors ``seed_demo_conversations``'
gating (``ENVIRONMENT=development`` only, called right after it so the
``chn-demo`` channel already exists). Demonstrates the full brief end to end:
an inbound message on the sandbox channel triggers a workflow, an AI Agent node
classifies intent/domain/urgency via the deterministic stub LLM (no API key
needed - the seeded agent carries no connection, so ``AiClient`` resolves the
stub automatically), and a reply lands back in the conversation.

Idempotent - keyed on the seeded agent's stable ``key``.
"""
from sqlalchemy.orm import Session

AGENT_KEY = "omnichannel_demo_classifier"
WORKFLOW_NAME = "Demo: classify & reply"


def seed_demo_ai_workflow(db: Session, tenant_id: str) -> None:
    from app.models.ai import AiAgent
    from app.services.workflow_service import WorkflowService

    if db.query(AiAgent).filter(AiAgent.tenant_id == tenant_id, AiAgent.key == AGENT_KEY).first():
        return

    agent = AiAgent(
        tenant_id=tenant_id,
        key=AGENT_KEY,
        name="Message Classifier",
        description="Classifies inbound WhatsApp messages by intent, domain and urgency.",
        is_system=True,
        connection_id=None,  # no LLM connection configured → AiClient stubs it
        model="stub-model-1",
        temperature=0.0,
    )
    db.add(agent)
    db.flush()

    # Node ids: underscore, never hyphen - the merge-token regex (`app.template_
    # engine.merge.TOKEN_RE`, `[\w.]+`) doesn't match `-`, so a hyphenated id
    # inside `{{ nodes.<id>.<key> }}` silently fails to substitute. Matches the
    # frontend's own id-minting convention (`lib/workflow-doc.ts` - `prefix_<rand>`).
    ai_node_id = "ai_classify"
    doc = {
        "schemaVersion": 1,
        "nodes": [
            {
                "id": "trg_inbound",
                "kind": "trigger",
                "type": "omnichannel.message_received",
                "config": {"channelId": "chn-demo"},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": ai_node_id,
                "kind": "action",
                "type": "ai_agent.run",
                "config": {
                    "agentId": agent.id,
                    "instructions": (
                        "Classify the incoming WhatsApp message's intent, "
                        "domain and urgency."
                    ),
                    "inputText": "{{ trigger.message.text }}",
                    "outputParams": [
                        {
                            "key": "intent",
                            "type": "string",
                            "description": "The message's primary intent",
                            "required": True,
                        },
                        {
                            "key": "domain",
                            "type": "string",
                            "description": "The business domain or topic",
                            "required": True,
                        },
                        {
                            "key": "urgency",
                            "type": "string",
                            "description": "low, medium, or high",
                            "required": True,
                        },
                    ],
                },
                "position": {"x": 320, "y": 0},
            },
            {
                "id": "send_reply",
                "kind": "action",
                "type": "omnichannel.send_message",
                "config": {
                    "contactId": "{{ trigger.contact.id }}",
                    "message": (
                        "Thanks - I've logged this as a "
                        f"{{{{ nodes.{ai_node_id}.intent }}}} request about "
                        f"{{{{ nodes.{ai_node_id}.domain }}}}. Someone will follow "
                        "up shortly."
                    ),
                },
                "position": {"x": 640, "y": 0},
            },
        ],
        "edges": [
            {"id": "e1", "source": "trg_inbound", "target": ai_node_id, "sourcePort": "out"},
            {"id": "e2", "source": ai_node_id, "target": "send_reply", "sourcePort": "out"},
        ],
    }

    service = WorkflowService(db)
    wf = service.create(
        tenant_id, name=WORKFLOW_NAME, description="Seeded demo - plan sprint-4/17.",
        draft=doc, actor_id=None,
    )
    service.set_active(wf.id, tenant_id, True)
    service.publish(wf.id, tenant_id, actor_id=None)


# ── Progress Update Agent (plan sprint-4/19 S5, AC-SAR-49/50) ────────────────
PROGRESS_AGENT_KEY = "omnichannel_demo_progress_updater"
PROGRESS_WORKFLOW_NAME = "Demo: progress update agent"


def seed_demo_progress_workflow(db: Session, tenant_id: str, *, channel_id: str = "chn-demo") -> None:
    """DEV-ONLY stateful proof built ONLY from generic nodes: inbound message →
    AI Agent (stateful task/status/blocker, transient decision/reply) → IF on
    decision → true: Send confirmation + Clear Agent State; false: Send the
    clarification. Serialized by ``{{ trigger.conversationId }}``. The seeded
    agent binds to the tenant's dev ``stub`` connection (or none when no LLM
    connection exists), so the dev stub LLM derives evidence-backed patches
    deterministically (``app.ai.stub._derive_stateful``).

    Stub limits (proof-only heuristics, not language understanding): enum
    fields match by SUBSTRING - a message merely containing "blocked" /
    "completed" / "in progress" sets the status whatever the surrounding
    words say; a message with no enum word and no ``key: value`` marker is
    taken WHOLE as the first missing required text field (the task); a short
    reply while a clarification is pending resolves that field verbatim. Real
    agents on a real connection are not bound by any of this."""
    from app.models.ai import AiAgent
    from app.services.workflow_service import WorkflowService

    if db.query(AiAgent).filter(AiAgent.tenant_id == tenant_id, AiAgent.key == PROGRESS_AGENT_KEY).first():
        return

    # Bi-D21: an agent with NO connection stubs only while the tenant has no
    # LLM connection at all. Bind to an existing dev `stub` connection when
    # one exists so the proof keeps running offline next to real providers.
    from app.models.connection import Connection

    stub_connection = (
        db.query(Connection)
        .filter(
            Connection.type == "llm",
            Connection.provider == "stub",
            Connection.tenant_id == tenant_id,
            Connection.is_active.is_(True),
        )
        .first()
    )
    agent = AiAgent(
        tenant_id=tenant_id,
        key=PROGRESS_AGENT_KEY,
        name="Progress Updater",
        description="Collects a task's status update over several short WhatsApp messages.",
        is_system=True,
        connection_id=stub_connection.id if stub_connection is not None else None,
        model="stub-model-1",
        temperature=0.0,
    )
    db.add(agent)
    db.flush()

    agent_node = "ai_progress"
    doc = {
        "schemaVersion": 2,
        "execution": {"mode": "serialized", "correlationKey": "{{ trigger.conversationId }}"},
        "nodes": [
            {
                "id": "trg_inbound",
                "kind": "trigger",
                "type": "omnichannel.message_received",
                "config": {"channelId": channel_id},
                "position": {"x": 0, "y": 0},
            },
            {
                "id": agent_node,
                "kind": "action",
                "type": "ai_agent.run",
                "config": {
                    "name": "Progress agent",
                    "agentId": agent.id,
                    "instructions": (
                        "You collect a progress update. Interpret ONLY the current message "
                        "against the accepted state. Propose evidence-backed patches for "
                        "task, status and blocker; ask one focused question when something "
                        "is missing; emit decision=ready when the update is complete."
                    ),
                    "inputText": "{{ trigger.message.text }}",
                    "outputParams": [
                        {"key": "task", "type": "string", "description": "What is being worked on", "required": True, "stateful": True},
                        {"key": "status", "type": "enum", "enumValues": ["in_progress", "blocked", "completed"], "description": "Current status", "required": True, "stateful": True},
                        {"key": "blocker", "type": "string", "description": "What is blocking progress, when blocked", "required": False, "stateful": True},
                        {"key": "decision", "type": "enum", "enumValues": ["ready", "needs_clarification"], "description": "Whether the update is complete", "required": True},
                        {"key": "reply", "type": "string", "description": "The clarification question or confirmation to send", "required": True},
                    ],
                    "clarificationOutputKey": "reply",
                },
                "position": {"x": 320, "y": 0},
            },
            {
                "id": "if_ready",
                "kind": "if",
                "type": "if",
                "config": {
                    "name": "Update complete?",
                    "conditions": {
                        "kind": "group",
                        "combinator": "and",
                        "rules": [
                            {
                                "kind": "condition",
                                "fact": f"nodes.{agent_node}.decision",
                                "operator": "eq",
                                "valueKind": "literal",
                                "value": "ready",
                            }
                        ],
                    },
                },
                "position": {"x": 640, "y": 0},
            },
            {
                "id": "send_confirm",
                "kind": "action",
                "type": "omnichannel.send_message",
                "config": {
                    "name": "Send confirmation",
                    "contactId": "{{ trigger.contact.id }}",
                    "message": (
                        "Update recorded - task: {{ nodes." + agent_node + ".task }}, "
                        "status: {{ nodes." + agent_node + ".status }}"
                        "{{ nodes." + agent_node + ".blocker }}"
                    ),
                },
                "position": {"x": 960, "y": -120},
            },
            {
                "id": "clear_state",
                "kind": "action",
                "type": "ai_agent.clear_state",
                "config": {"name": "Clear update", "agentNodeId": agent_node},
                "position": {"x": 1280, "y": -120},
            },
            {
                "id": "send_question",
                "kind": "action",
                "type": "omnichannel.send_message",
                "config": {
                    "name": "Send clarification",
                    "contactId": "{{ trigger.contact.id }}",
                    "message": "{{ nodes." + agent_node + ".reply }}",
                },
                "position": {"x": 960, "y": 120},
            },
        ],
        "edges": [
            {"id": "e1", "source": "trg_inbound", "target": agent_node, "sourcePort": "out"},
            {"id": "e2", "source": agent_node, "target": "if_ready", "sourcePort": "out"},
            {"id": "e3", "source": "if_ready", "target": "send_confirm", "sourcePort": "true"},
            {"id": "e4", "source": "send_confirm", "target": "clear_state", "sourcePort": "out"},
            {"id": "e5", "source": "if_ready", "target": "send_question", "sourcePort": "false"},
        ],
    }

    service = WorkflowService(db)
    wf = service.create(
        tenant_id,
        name=PROGRESS_WORKFLOW_NAME,
        description="Seeded stateful proof - plan sprint-4/19.",
        draft=doc,
        actor_id=None,
    )
    service.set_active(wf.id, tenant_id, True)
    service.publish(wf.id, tenant_id, actor_id=None)
