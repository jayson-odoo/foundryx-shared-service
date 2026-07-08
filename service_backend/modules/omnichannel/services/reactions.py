"""Reaction propagation — plan 12 Slice 3 (AC-12-20).

ONE place that fans a reaction change to (a) the workspace WS room so open
inboxes update the emoji chip live and (b) the consumer webhook (opt-in). Both
the inbound path (a contact reacted) and the send path (an agent reacted) call
``emit_reaction`` so the two surfaces stay identical.
"""
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Channel
from . import realtime


def emit_reaction(
    db: Session,
    channel: Optional[Channel],
    *,
    workspace_id: Optional[str],
    contact_id: str,
    target_message_id: str,
    reactor_type: str,
    emoji: str,
    removed: bool,
    event_id: str,
) -> None:
    """Publish ``message.reaction`` on WS + fan to consumer webhooks. Failure of
    the webhook fan-out is isolated inside ``enqueue_event`` and never raises."""
    if workspace_id:
        realtime.publish(
            workspace_id,
            {
                "type": "message.reaction",
                "targetMessageId": target_message_id,
                "contactId": contact_id,
                "reactorType": reactor_type,
                "emoji": emoji,
                "removed": removed,
            },
        )
    if channel is not None:
        from .webhook_delivery import enqueue_event

        enqueue_event(
            db,
            channel,
            "message.reaction",
            event_id,
            {
                "targetMessageId": target_message_id,
                "reactorType": reactor_type,
                "emoji": emoji,
                "removed": removed,
            },
        )
