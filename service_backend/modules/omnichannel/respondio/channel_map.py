"""``SOURCE_TO_CHANNEL_TYPE`` (plan 33 D-A6-10, AC-MIG-31).

The ONE place a respond.io ``ChannelSource`` value plugs into a Foundryx
``channels.channel_type`` value. ``channel_type`` is a free string column
(``modules/omnichannel/models.py`` ``Channel.channel_type``, default
``"WHATSAPP"``) - adding a future channel type is a dict row here plus,
eventually, a real channel of that type; no schema change either way.

A source value with NO row (or a genuinely unknown value the vendor adds
later) maps to ``None`` - the migration setup form always shows "Skip this
channel" preselected for it (AC-MIG-04), and its messages become channel-less
history (``channel_id`` NULL, already legal - SYSTEM notes use it). A
fabricated/guessed target type would silently misroute a real channel, which
is worse than an honest skip (BL-SS-129 - re-verify this map against the
vendor's live catalog on a schedule).
"""
from typing import Dict, Optional

# Every respond.io ``ChannelSource`` value documented in the plan's §5.1
# contract (mirrors the vendor SDK's ``src/types/common.ts``). Kept as a plain
# module-level dict (not an enum) so a future row is a one-line diff.
SOURCE_TO_CHANNEL_TYPE: Dict[str, str] = {
    "whatsapp": "WHATSAPP",
    "whatsapp_cloud": "WHATSAPP",
    "360dialog_whatsapp": "WHATSAPP",
    "twilio_whatsapp": "WHATSAPP",
    "message_bird_whatsapp": "WHATSAPP",
    "nexmo_whatsapp": "WHATSAPP",
    # A7a (plan 32) plugs in here with no A6 change (plan §6, in-flight seams).
    "facebook": "FACEBOOK",
    "instagram": "INSTAGRAM",
    "telegram": "TELEGRAM",
    "line": "LINE",
    "viber": "VIBER",
    "wechat": "WECHAT",
    "twitter": "TWITTER",
    "custom_channel": "CUSTOM",
    "gmail": "EMAIL",
    "other_email": "EMAIL",
    # Bare "twilio"/"message_bird"/"nexmo" (no "_whatsapp" suffix) are those
    # providers' generic SMS channels on respond.io - distinct from their
    # WhatsApp-specific counterparts above.
    "twilio": "SMS",
    "message_bird": "SMS",
    "nexmo": "SMS",
}

# The exact list AC-MIG-31 pins - a coverage test asserts every one of these
# has a row above (and that no OTHER key sneaked in undocumented).
DOCUMENTED_SOURCE_VALUES = (
    "whatsapp",
    "whatsapp_cloud",
    "360dialog_whatsapp",
    "twilio_whatsapp",
    "message_bird_whatsapp",
    "nexmo_whatsapp",
    "facebook",
    "instagram",
    "telegram",
    "line",
    "viber",
    "wechat",
    "twitter",
    "custom_channel",
    "gmail",
    "other_email",
    "twilio",
    "message_bird",
    "nexmo",
)


def target_channel_type_for(source: str) -> Optional[str]:
    """The Foundryx ``channel_type`` a source value maps to, or ``None`` when
    it has no compatible target (D-A6-10)."""
    return SOURCE_TO_CHANNEL_TYPE.get(source)
