"""Per-channel-type messaging window policy (plan 32 / A7a, D-A7-5).

One contact can now be reachable on three channels with three independent
re-engagement windows, so the window instant lives on the CONTACT-CHANNEL
IDENTITY it belongs to, never on the contact alone. This module owns the
window lengths - "the ONLY module that knows a window length" (plan §2.1) -
so no other file branches on how long a channel type stays open.

Slice S1 (inbound) ships `POLICIES` + `stamp_inbound_window` (the one seam
every inbound path calls, AC-CHN-21) and `backfill_identity_windows` (the
dialect-agnostic twin of migration `0017`'s Postgres backfill SQL, AC-CHN-14 -
mirrors `ContactRepository.backfill_phone_digits`'s "unit-test the backfill
function directly" lesson, since the migration's raw SQL never runs under
pytest). The OUTBOUND side - `authorize`, `assert_kind_supported`,
`CAPABILITIES`, the human-agent compliance rule (D-A7-6) - is plan 32 S2;
nothing here computes an outbound send decision yet.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

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
# "human_agent" (D-A7-6, enforced in S2's `authorize`, not here).
POLICIES = {
    "WHATSAPP": WindowPolicy("WHATSAPP", 24, None, "template"),
    "FACEBOOK": WindowPolicy("FACEBOOK", 24, 168, "human_agent"),
    "INSTAGRAM": WindowPolicy("INSTAGRAM", 24, 168, "human_agent"),
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
    identity.window_expires_at = now + timedelta(hours=policy.window_hours)
    identity.human_agent_expires_at = (
        now + timedelta(hours=policy.human_agent_hours)
        if policy.human_agent_hours
        else None
    )
    identity.last_inbound_at = now


def backfill_identity_windows(db: Session, tenant_id: Optional[str] = None) -> int:
    """Dialect-agnostic backfill twin of migration `0017`'s Postgres SQL sweep
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
