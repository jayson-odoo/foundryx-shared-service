"""Safe synthetic data for testing an omnichannel workflow draft.

The synthetic message exists only in ``WorkflowRun.trigger_payload_json``.
Nothing here calls inbound processing, writes an inbound message, publishes
realtime events, or dispatches another workflow.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal
from uuid import uuid4

from cryptography.fernet import InvalidToken
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.repositories.module_repository import ModuleRepository
from app.workflow_engine.entity_events import build_event_trigger_payload
from app.workflow_engine.registry import TriggerTestDataError

from ..models import Contact
from ..repositories.channel_repository import ChannelRepository
from ..repositories.contact_repository import ContactRepository
from ..security import decrypt_credentials


class OmnichannelMessageTestTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["omnichannel.message_received"]
    channelId: str = Field(min_length=1, max_length=120)
    contactId: str = Field(min_length=1, max_length=120)
    messageText: str = Field(min_length=1, max_length=4096)


def _contact_name(contact: Contact) -> str:
    name = " ".join(
        part for part in (contact.first_name, contact.last_name) if part
    ).strip()
    return name or contact.phone or ""


def _is_dev_channel(channel) -> bool:
    if not channel.credentials_json:
        return False
    try:
        return decrypt_credentials(channel.credentials_json).get("dev") is True
    except (InvalidToken, ValueError, TypeError, KeyError):
        return False


def test_metadata(
    db: Session, tenant_id: str, trigger_config: Dict[str, Any]
) -> Dict[str, Any]:
    """Flat, safe channel/contact pairs for the workflow test dialog."""
    if not ModuleRepository(db).is_active(tenant_id, "omnichannel"):
        return {"omnichannelTestSources": []}

    channels = [
        channel
        for channel in ChannelRepository(db).active_scoped(tenant_id)
        if _is_dev_channel(channel)
    ]
    configured_channel_id = str(trigger_config.get("channelId") or "")
    if configured_channel_id:
        channels = [
            channel for channel in channels if channel.id == configured_channel_id
        ]
    pairs = ContactRepository(db).testable_for_channels(
        tenant_id,
        [channel.id for channel in channels],
        now=datetime.now(timezone.utc),
    )
    contacts_by_channel: Dict[str, List[Contact]] = {}
    for channel_id, contact in pairs:
        contacts_by_channel.setdefault(channel_id, []).append(contact)

    sources: List[Dict[str, str]] = []
    seen = set()
    for channel in channels:
        for contact in contacts_by_channel.get(channel.id, []):
            pair = (channel.id, contact.id)
            if pair in seen:
                continue
            seen.add(pair)
            sources.append(
                {
                    "channelId": channel.id,
                    "channelName": channel.name,
                    "contactId": contact.id,
                    "contactName": _contact_name(contact),
                    "contactPhone": contact.phone or "",
                }
            )
    return {"omnichannelTestSources": sources}


def build_test_payload(
    db: Session,
    tenant_id: str,
    trigger_config: Dict[str, Any],
    raw: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate client IDs, derive server facts, and return the live envelope."""
    if not ModuleRepository(db).is_active(tenant_id, "omnichannel"):
        raise TriggerTestDataError("The omnichannel service is not active.")
    try:
        data = OmnichannelMessageTestTrigger.model_validate(raw)
    except ValidationError as exc:
        raise TriggerTestDataError("Invalid omnichannel test data.") from exc

    channel = ChannelRepository(db).get_active_by_id(data.channelId, tenant_id)
    contact_repo = ContactRepository(db)
    contact = contact_repo.get_by_id(data.contactId, tenant_id)
    now = datetime.now(timezone.utc)
    if (
        channel is None
        or contact is None
        or not _is_dev_channel(channel)
        or contact.workspace_id != channel.workspace_id
        or not contact_repo.is_attached_to_channel(contact.id, channel.id, tenant_id)
        or contact.csw_expires_at is None
        or contact.csw_expires_at <= now
    ):
        raise TriggerTestDataError("Selected sandbox source is unavailable.")

    configured_channel_id = str(trigger_config.get("channelId") or "")
    if configured_channel_id and configured_channel_id != channel.id:
        raise TriggerTestDataError("Selected sandbox source is unavailable.")

    message_id = f"test-{uuid4()}"
    event = {
        "action": "received",
        "actor": None,
        "record_id": message_id,
        "changes": None,
        "record_facts": {},
        "extra": {
            "channelId": channel.id,
            "channelName": channel.name,
            "workspaceId": channel.workspace_id,
            "contactId": contact.id,
            "contactName": _contact_name(contact),
            "contactPhone": contact.phone or "",
            "conversationId": contact.id,
            "messageId": message_id,
            "messageType": "TEXT",
            "messageText": data.messageText,
            "mediaUrl": None,
            "mediaMime": None,
        },
    }
    payload = build_event_trigger_payload(event)
    # Internal execution marker: the executor carries this to outbound actions,
    # which persist a durable sandbox-only constraint on the queued message.
    payload["_workflowTest"] = {"sandboxOnly": True}
    return payload
