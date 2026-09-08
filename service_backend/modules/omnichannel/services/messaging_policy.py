"""Per-channel-type messaging window policy (plan 32 / A7a, D-A7-5).

One contact can now be reachable on three channels with three independent
re-engagement windows, so the window instant lives on the CONTACT-CHANNEL
IDENTITY it belongs to, never on the contact alone. This module owns the
window lengths - "the ONLY module that knows a window length" (plan §2.1) -
so no other file branches on how long a channel type stays open, and it is
also the ONLY module that knows what a channel type can carry
(`CAPABILITIES`/`assert_kind_supported`) and what Meta send parameters a send
needs (`authorize`).

Slice S1 (inbound) shipped `POLICIES` + `stamp_inbound_window` (the one seam
every inbound path calls, AC-CHN-21) and `backfill_identity_windows` (the
dialect-agnostic twin of migration `0019`'s Postgres backfill SQL, AC-CHN-14).

Slice S2 (outbound, AC-CHN-22..31) adds the OUTBOUND side: `authorize` is the
ONE function every send path calls - it answers "may this message be sent on
this channel to this contact right now, and with what Meta send parameters" -
replacing the five hardcoded calls to the old private `_window_open` helper
that used to live in `message_service.py`. `assert_kind_supported`/`CAPABILITIES` reject
any message kind a channel type cannot carry, whatever the caller (AC-CHN-29).

Sources (Messenger/Instagram messaging policy - the 24h standard window, the
`HUMAN_AGENT` 7-day extension and its human-only restriction; the Send API
`messaging_type`/`tag` enum spellings, pinned per R5):
https://developers.facebook.com/documentation/business-messaging/messenger-platform/policy
https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..models import Channel, Contact, ContactChannelIdentity


@dataclass(frozen=True)
class WindowPolicy:
    channel_type: str
    window_hours: int
    human_agent_hours: Optional[int]  # None = no human-agent extension
    reengage_mode: str  # "template" (WhatsApp) | "human_agent" | "none"


# Standard messaging window + (where Meta grants one) the human-agent
# extension, per channel type (plan §5.4). WhatsApp's re-engagement mode stays
# "template" (an approved template, never a tag) - Messenger/Instagram's is
# "human_agent" (D-A7-6).
POLICIES = {
    "WHATSAPP": WindowPolicy("WHATSAPP", 24, None, "template"),
    "FACEBOOK": WindowPolicy("FACEBOOK", 24, 168, "human_agent"),
    "INSTAGRAM": WindowPolicy("INSTAGRAM", 24, 168, "human_agent"),
    # Plan 34 (A7b, D-A7B-18) - there is no provider policy to encode: a
    # web chat visitor who left is reachable again the moment they return,
    # never locked out by a window. `window_hours=0`/`human_agent_hours=None`
    # are never actually used for the "none" mode (see `stamp_inbound_window`/
    # `window_open`/`authorize` below, which all short-circuit on it first).
    "WEBCHAT": WindowPolicy("WEBCHAT", 0, None, "none"),
}


def stamp_inbound_window(
    identity: ContactChannelIdentity,
    contact: Contact,
    channel: Channel,
    *,
    now: Optional[datetime] = None,
) -> None:
    """Stamp the identity's OWN re-engagement window on any inbound message
    (AC-CHN-21) - `window_expires_at` = now + the channel type's window,
    `human_agent_expires_at` = now + its human-agent window (null where the
    type has none), `last_inbound_at` = now.

    `contacts.csw_expires_at`/`last_incoming_message_at` are a DOCUMENTED
    gateway field + the composer's window lock (D-A7-5) - `_handle_message`
    keeps dual-writing them directly for WhatsApp exactly as before this
    slice; this function only owns the three NEW per-identity columns, which
    every channel type gets."""
    now = now or datetime.now(timezone.utc)
    policy = POLICIES.get(channel.channel_type, POLICIES["WHATSAPP"])
    if policy.reengage_mode == "none":
        # Plan 34 (A7b, D-A7B-18/AC-WEB-13) - web chat has no messaging
        # window at all: leave both NULL rather than stamping a same-instant
        # "already expired" window (`window_hours=0` would otherwise compute
        # `now + 0h == now`, which reads as closed the instant it's written).
        identity.window_expires_at = None
        identity.human_agent_expires_at = None
    else:
        identity.window_expires_at = now + timedelta(hours=policy.window_hours)
        identity.human_agent_expires_at = (
            now + timedelta(hours=policy.human_agent_hours)
            if policy.human_agent_hours
            else None
        )
    identity.last_inbound_at = now


def backfill_identity_windows(db: Session, tenant_id: Optional[str] = None) -> int:
    """Dialect-agnostic backfill twin of migration `0019`'s Postgres SQL sweep
    (AC-CHN-14) - a plain Python loop so it runs identically under pytest's
    SQLite engine (the migration's raw `UPDATE ... FROM` is Postgres-only and
    never runs there - the same lesson `ContactRepository.
    backfill_phone_digits` documents). Stamps every WhatsApp identity with no
    `window_expires_at` yet from its contact's existing `csw_expires_at`/
    `last_incoming_message_at`. Idempotent - a second call changes nothing.
    Returns the number of identities stamped."""
    q = (
        db.query(ContactChannelIdentity, Contact)
        .join(Contact, Contact.id == ContactChannelIdentity.contact_id)
        .join(Channel, Channel.id == ContactChannelIdentity.channel_id)
        .filter(
            Channel.channel_type == "WHATSAPP",
            ContactChannelIdentity.window_expires_at.is_(None),
        )
    )
    if tenant_id is not None:
        q = q.filter(ContactChannelIdentity.tenant_id == tenant_id)
    count = 0
    for identity, contact in q.all():
        identity.window_expires_at = contact.csw_expires_at
        identity.last_inbound_at = contact.last_incoming_message_at
        count += 1
    db.flush()
    return count


# ── Outbound (plan 32 S2, AC-CHN-22..31) ────────────────────────────────────

# Meta Send API enum spellings (R5 - pinned against the deployed Graph
# version; Meta's own docs render them inconsistently). One adapter test
# asserts these are what actually goes on the wire.
MESSAGING_TYPE_RESPONSE = "RESPONSE"
MESSAGING_TYPE_MESSAGE_TAG = "MESSAGE_TAG"
TAG_HUMAN_AGENT = "HUMAN_AGENT"

CSW_CLOSED_MESSAGE = (
    "The 24-hour window has closed - send an approved template to re-engage."
)
MESSAGING_WINDOW_CLOSED_MESSAGE = "The messaging window has closed."
AUTOMATION_OUTSIDE_WINDOW_MESSAGE = (
    "Automated messages cannot be sent once the 24-hour window has closed - "
    "a human agent can still reply for up to 7 days."
)

_LABELS = {"WHATSAPP": "WhatsApp", "FACEBOOK": "Messenger", "INSTAGRAM": "Instagram"}


def _label(channel_type: str) -> str:
    return _LABELS.get(channel_type, channel_type.title())


class PolicyRejected(Exception):
    """A send is not authorized - carries a typed `code` (composer/workflow/
    gateway map it to the existing 422/409 shape) and a human `message`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ChannelCapabilities:
    """What a channel type can carry (plan §5.5). `text`/`image`/`video`/
    `audio`/quick-reply buttons/reply-to/inbound reactions are `yes` on every
    implemented type, so they need no flag here - only the capabilities that
    actually DIVERGE by type are modelled."""

    channel_type: str
    document: bool
    sticker: bool
    template: bool
    interactive_list: bool  # WhatsApp-native list/cta_url/location_request
    location: bool
    contacts: bool
    reaction_outbound: bool


CAPABILITIES = {
    "WHATSAPP": ChannelCapabilities(
        "WHATSAPP", document=True, sticker=True, template=True,
        interactive_list=True, location=True, contacts=True, reaction_outbound=True,
    ),
    "FACEBOOK": ChannelCapabilities(
        "FACEBOOK", document=True, sticker=False, template=False,
        interactive_list=False, location=False, contacts=False, reaction_outbound=False,
    ),
    "INSTAGRAM": ChannelCapabilities(
        "INSTAGRAM", document=False, sticker=False, template=False,
        interactive_list=False, location=False, contacts=False, reaction_outbound=False,
    ),
    # Plan 34 (A7b §5.5) - parity-pinned against `lib/channel-capabilities.ts`
    # (`CHANNEL_CAPABILITIES.WEBCHAT`).
    "WEBCHAT": ChannelCapabilities(
        "WEBCHAT", document=True, sticker=False, template=False,
        interactive_list=False, location=False, contacts=False, reaction_outbound=False,
    ),
}


def assert_kind_supported(
    channel_type: str, kind: str, *, sub_kind: Optional[str] = None
) -> None:
    """Reject any message kind the target channel type cannot carry, whatever
    the caller (AC-CHN-29 - the frontend gating is UX only). `kind` is the
    house canonical message-type vocabulary (`TEXT`/`IMAGE`/`VIDEO`/`AUDIO`/
    `VOICE`/`DOCUMENT`/`STICKER`/`TEMPLATE`/`INTERACTIVE`/`LOCATION`/
    `CONTACTS`/`REACTION`); `sub_kind` is the interactive definition's own
    `kind` (`buttons`/`list`/`cta_url`/`location_request`) - only `buttons`
    maps onto Meta quick replies for Messenger/Instagram (D-A7-13)."""
    caps = CAPABILITIES.get(channel_type, CAPABILITIES["WHATSAPP"])
    k = (kind or "").upper()
    if k == "DOCUMENT" and not caps.document:
        raise PolicyRejected(
            "kind_not_supported", f"{_label(channel_type)} does not support file attachments."
        )
    if k == "STICKER" and not caps.sticker:
        raise PolicyRejected(
            "kind_not_supported", f"{_label(channel_type)} does not support stickers."
        )
    if k == "TEMPLATE" and not caps.template:
        raise PolicyRejected(
            "kind_not_supported", f"{_label(channel_type)} does not support message templates."
        )
    if k == "LOCATION" and not caps.location:
        raise PolicyRejected(
            "kind_not_supported", f"{_label(channel_type)} does not support location messages."
        )
    if k == "CONTACTS" and not caps.contacts:
        raise PolicyRejected(
            "kind_not_supported", f"{_label(channel_type)} does not support contact-card messages."
        )
    if k == "REACTION" and not caps.reaction_outbound:
        raise PolicyRejected(
            "kind_not_supported", f"{_label(channel_type)} does not support reactions."
        )
    if k == "INTERACTIVE" and not caps.interactive_list and (sub_kind or "").lower() != "buttons":
        raise PolicyRejected(
            "kind_not_supported", f"{_label(channel_type)} only supports quick-reply buttons."
        )
    # TEXT / IMAGE / VIDEO / AUDIO / VOICE are `yes` on every implemented type.


@dataclass(frozen=True)
class SendDecision:
    """The resolved Meta send parameters for an authorized send (D-A7-8 -
    computed once, at enqueue, and used VERBATIM by `send_runner`, which never
    re-derives it). `messaging_type`/`tag` stay `None` for WhatsApp (its own
    re-engagement mode is "template", not a Meta send parameter)."""

    messaging_type: Optional[str] = None
    tag: Optional[str] = None


def send_metadata(decision: SendDecision) -> Optional[Dict[str, Any]]:
    """The `metaSend` blob persisted on the queued message row (AC-CHN-25) -
    `None` when the decision carries no Meta send parameters (WhatsApp)."""
    if decision.messaging_type is None:
        return None
    meta: Dict[str, Any] = {"messagingType": decision.messaging_type}
    if decision.tag:
        meta["tag"] = decision.tag
    return meta


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _whatsapp_window_open(contact: Contact, now: datetime) -> bool:
    expires = _aware(contact.csw_expires_at)
    return expires is not None and expires > now


def _identity_for(
    db: Session, contact: Contact, channel: Channel
) -> Optional[ContactChannelIdentity]:
    from ..repositories.contact_repository import ContactRepository

    return ContactRepository(db).find_identity_for_channel(
        contact.id, channel.id, contact.tenant_id
    )


def closed_window_message(channel_type: str) -> str:
    """The right "window closed" copy for a channel type - keeps every
    channel-type branch inside THIS module (never in a caller)."""
    policy = POLICIES.get(channel_type, POLICIES["WHATSAPP"])
    return CSW_CLOSED_MESSAGE if policy.reengage_mode == "template" else MESSAGING_WINDOW_CLOSED_MESSAGE


def window_open(
    db: Session, contact: Contact, channel: Channel, *, now: Optional[datetime] = None
) -> bool:
    """A cheap boolean peek - "is ANY send still possible right now" - for a
    pre-flight bail-out BEFORE expensive work (e.g. the gateway's SSRF-guarded
    media fetch, or sniffing/storing an interactive header blob). `authorize`
    stays the one place that answers "may THIS send happen" - this helper
    never substitutes for it."""
    now = now or datetime.now(timezone.utc)
    policy = POLICIES.get(channel.channel_type, POLICIES["WHATSAPP"])
    if policy.reengage_mode == "none":
        # Plan 34 (A7b, D-A7B-18) - no window to be closed; a pre-flight
        # peek before expensive work (media sniff/store, SSRF-guarded fetch)
        # must never bail out on a web chat send.
        return True
    if policy.reengage_mode == "template":
        return _whatsapp_window_open(contact, now)
    identity = _identity_for(db, contact, channel)
    if identity is None:
        return False
    if identity.window_expires_at and _aware(identity.window_expires_at) > now:
        return True
    if (
        policy.human_agent_hours
        and identity.human_agent_expires_at
        and _aware(identity.human_agent_expires_at) > now
    ):
        return True
    return False


def authorize(
    db: Session,
    contact: Contact,
    channel: Channel,
    *,
    kind: str,
    actor_is_human: bool,
    sub_kind: Optional[str] = None,
    now: Optional[datetime] = None,
) -> SendDecision:
    """The ONE function that answers "can this send happen, and with what
    Meta send parameters" (AC-CHN-22). Raises `PolicyRejected` when it can't.

    WhatsApp (`reengage_mode == "template"`): a TEMPLATE send is always
    allowed (exempt from the window); free-form is allowed inside the 24h
    CSW and refused with the byte-identical `CSW_CLOSED_MESSAGE` otherwise
    (AC-CHN-23 - the existing WhatsApp send/CSW tests pass unchanged).

    Messenger/Instagram (`reengage_mode == "human_agent"`, D-A7-6): inside the
    24h standard window -> `RESPONSE`; inside the 7-day human-agent window AND
    `actor_is_human` -> `MESSAGE_TAG`/`HUMAN_AGENT`; inside that SAME window
    but NOT human (a workflow action, the public gateway, a broadcast - no
    human actor) -> refused `automation_outside_window`; outside both ->
    refused `messaging_window_closed`. `actor_is_human` is computed by the
    CALLER from the presence of a real user/federated-agent identity - never
    inferred here from an opaque attribution string (the public gateway
    stamps `sender_id` with `apikey:<id>` for message attribution, which is
    truthy but is NOT a human actor)."""
    assert_kind_supported(channel.channel_type, kind, sub_kind=sub_kind)
    now = now or datetime.now(timezone.utc)
    policy = POLICIES.get(channel.channel_type, POLICIES["WHATSAPP"])

    if policy.reengage_mode == "template":
        if (kind or "").upper() == "TEMPLATE":
            return SendDecision()
        if _whatsapp_window_open(contact, now):
            return SendDecision()
        raise PolicyRejected("csw_window_closed", CSW_CLOSED_MESSAGE)

    # Plan 34 (A7b, D-A7B-18/AC-WEB-13) - the ONE new branch this slice adds.
    # Added AFTER the template branch (R11) so the WhatsApp/Messenger/
    # Instagram matrix above is untouched. There is no provider policy on
    # web chat to encode - a reply to a visitor who left is delivered
    # whenever they return, never a violation.
    if policy.reengage_mode == "none":
        return SendDecision()

    identity = _identity_for(db, contact, channel)
    inside_standard = (
        identity is not None
        and identity.window_expires_at is not None
        and _aware(identity.window_expires_at) > now
    )
    if inside_standard:
        return SendDecision(messaging_type=MESSAGING_TYPE_RESPONSE)

    inside_human_agent = (
        identity is not None
        and policy.human_agent_hours is not None
        and identity.human_agent_expires_at is not None
        and _aware(identity.human_agent_expires_at) > now
    )
    if inside_human_agent:
        if actor_is_human:
            return SendDecision(messaging_type=MESSAGING_TYPE_MESSAGE_TAG, tag=TAG_HUMAN_AGENT)
        raise PolicyRejected("automation_outside_window", AUTOMATION_OUTSIDE_WINDOW_MESSAGE)

    raise PolicyRejected("messaging_window_closed", MESSAGING_WINDOW_CLOSED_MESSAGE)
