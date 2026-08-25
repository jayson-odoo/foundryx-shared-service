"""Omnichannel workflow-engine node registration (plan sprint-4/17).

Called from ``bootstrap.py::register_engine_entities()`` - the existing,
already-wired module boot hook (``app/module_loader.py::register_module_boot``)
- so this module never needs a core file to import it directly (module
governance: hook via the predefined seam, no global-store injection).
"""
from app.workflow_engine.registry import ActionDef, NodeField, NodeOutput, TriggerDef, register_action, register_trigger

from .services.workflow_actions import omnichannel_get_contact, omnichannel_send_message

MODULE_NAME = "omnichannel"

_TRIGGER_OUTPUTS = [
    NodeOutput("trigger.message.id", "Message · id"),
    NodeOutput("trigger.message.text", "Message · text"),
    NodeOutput("trigger.message.type", "Message · type"),
    NodeOutput("trigger.message.mediaUrl", "Message · media URL"),
    NodeOutput("trigger.contact.id", "Contact · id"),
    NodeOutput("trigger.contact.name", "Contact · name"),
    NodeOutput("trigger.contact.phone", "Contact · phone"),
    NodeOutput("trigger.channel.id", "Channel · id"),
    NodeOutput("trigger.channel.name", "Channel · name"),
    NodeOutput("trigger.conversationId", "Conversation id"),
]


def register_omnichannel_workflow_nodes() -> None:
    """Idempotent (``register_trigger``/``register_action`` are dict-set)."""
    register_trigger(
        TriggerDef(
            key="omnichannel.message_received",
            label="Incoming omnichannel message",
            description="Fires when a WhatsApp message arrives on a chosen channel (or any channel).",
            icon="MessageCircle",
            category="Triggers",
            module=MODULE_NAME,
            fields=[
                NodeField(
                    key="channelId",
                    label="Channel",
                    type="omnichannelChannel",
                    required=False,
                )
            ],
            outputs=_TRIGGER_OUTPUTS,
        )
    )
    register_action(
        ActionDef(
            key="omnichannel.get_contact",
            label="Get Contact",
            description="Load a contact by id into the workflow context.",
            icon="UserRound",
            category="Actions",
            module=MODULE_NAME,
            executor=omnichannel_get_contact,
            fields=[
                NodeField(
                    key="contactId",
                    label="Contact",
                    type="text",
                    required=True,
                    mergeable=True,
                )
            ],
            outputs=[
                NodeOutput("id", "Contact id"),
                NodeOutput("name", "Name"),
                NodeOutput("phone", "Phone"),
                NodeOutput("email", "Email"),
                NodeOutput("workspaceId", "Workspace id"),
                NodeOutput("statusId", "Status id"),
                NodeOutput("status", "Status"),
            ],
        )
    )
    register_action(
        ActionDef(
            key="omnichannel.send_message",
            label="Send Message",
            description="Send a text reply into the triggering conversation.",
            icon="Send",
            category="Actions",
            module=MODULE_NAME,
            executor=omnichannel_send_message,
            fields=[
                NodeField(
                    key="contactId",
                    label="Contact",
                    type="text",
                    required=True,
                    mergeable=True,
                ),
                NodeField(
                    key="message",
                    label="Message",
                    type="textarea",
                    required=True,
                    mergeable=True,
                ),
            ],
            outputs=[
                NodeOutput("messageId", "Message id"),
                NodeOutput("status", "Send status"),
            ],
        )
    )
