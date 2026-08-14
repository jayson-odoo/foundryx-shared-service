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
