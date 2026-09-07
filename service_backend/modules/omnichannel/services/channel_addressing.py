"""Channel addressing (plan 32 / A7a, AC-CHN-26) - resolves WHO the parties of
an outbound send are, so `send_runner` never branches on `channel_type` for
addressing. WhatsApp keeps `digits(contact.phone)` sent from `channel.
phone_number_id` (byte-identical to before this slice); Messenger/Instagram
address the contact's OWN identity on THIS channel (`external_user_id` - the
PSID/IGSID) sent from `channel.external_account_id` (the PAGE_ID / IG account
id the connect flow stored).
"""
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Channel, Contact
from ..phone import digits_only
from ..repositories.contact_repository import ContactRepository


class NoChannelIdentity(Exception):
    """The contact has no identity on the chosen channel - a send must fail
    cleanly with a typed reason rather than address an empty recipient."""


def sender_ref(channel: Channel) -> str:
    """The ref Meta expects as the routing id in the send URL: the phone
    number id for WhatsApp, the PAGE_ID / IG account id for Messenger/
    Instagram (D-A7-3, the same design as `phone_number_id`)."""
    if channel.channel_type == "WHATSAPP":
        return channel.phone_number_id or ""
    return channel.external_account_id or ""


def recipient_ref(db: Session, channel: Channel, contact: Contact) -> str:
    """The ref Meta expects as the recipient: digits-only phone for WhatsApp
    (unchanged), or the contact's own PSID/IGSID identity on THIS channel for
    Messenger/Instagram. Raises `NoChannelIdentity` when the contact has no
    identity there - never sends to an empty recipient (AC-CHN-26)."""
    if channel.channel_type == "WHATSAPP":
        return digits_only(contact.phone or "")
    identity = ContactRepository(db).find_identity_for_channel(
        contact.id, channel.id, contact.tenant_id
    )
    if identity is None or not identity.external_user_id:
        raise NoChannelIdentity(
            "This contact has no identity on the selected channel."
        )
    return identity.external_user_id
