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
from typing import Any, Dict, Optional

from ..phone import digits_only

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


# ── S3 identity derivation (AC-MIG-30, D-A6-10) ─────────────────────────────
#
# The vendor's ``ContactChannel`` shape (plan §5.1) has no dedicated "external
# user id" field - only a free-form ``meta`` bag, so the real per-channel
# identifier has to be read out of it defensively per source family. Adding a
# NEW compatible source (e.g. A7a's Messenger/Instagram) is ONE dict row here,
# same as ``SOURCE_TO_CHANNEL_TYPE`` above - no schema change either way. A
# source with no row here (or one whose row returns ``None`` for a given
# contact) is SKIPPED and reported (never a fabricated id - D-A6-10) because a
# fabricated ``external_user_id`` would poison the LIVE inbound stitch
# (``inbound_service._resolve_contact`` / ``ContactRepository.find_identity``).
_WHATSAPP_META_KEYS = ("phone", "wa_id", "waId", "number", "identifier")


def _derive_whatsapp(meta: Optional[Dict[str, Any]], contact_phone: Optional[str]) -> Optional[str]:
    """WhatsApp identity = the phone number, normalized to digits (the SAME
    normalization the live stitch uses - ``phone.digits_only``, D-A6-10's
    "WhatsApp now: phone -> phone_digits"). Prefers a per-channel value out of
    ``meta`` (a contact can carry more than one WhatsApp channel, e.g. two
    BSPs) and falls back to the contact's own ``phone`` only when ``meta``
    carries none of the candidate keys."""
    raw = None
    for key in _WHATSAPP_META_KEYS:
        candidate = (meta or {}).get(key)
        if candidate:
            raw = candidate
            break
    if not raw:
        raw = contact_phone
    digits = digits_only(str(raw)) if raw else ""
    return digits or None


# sourceChannelType (the SOURCE_TO_CHANNEL_TYPE value) -> deriver function.
# Only WhatsApp is wired today (D-A6-10); a future channel family plugs in
# with one more row, no schema change.
IDENTITY_DERIVERS: Dict[str, Any] = {
    "WHATSAPP": _derive_whatsapp,
}


def derive_external_user_id(
    target_channel_type: str, meta: Optional[Dict[str, Any]], contact_phone: Optional[str]
) -> Optional[str]:
    """Real external id for a mapped channel, or ``None`` when it cannot be
    derived (AC-MIG-30) - the caller must SKIP (never fabricate) on ``None``."""
    deriver = IDENTITY_DERIVERS.get(target_channel_type)
    if deriver is None:
        return None
    return deriver(meta, contact_phone)
