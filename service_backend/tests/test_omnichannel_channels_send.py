"""Plan 32 (A7a) Slice S2 - outbound send + the per-channel-type window
policy, channel addressing, the generalized send runner, Messenger outbound
(text + quick replies).

AC-CHN-22..31 (see documentation/plans/sprint-4/
32-omnichannel-channels-messenger-instagram-acceptance-criteria.md).
"""
import inspect
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from tests.test_omnichannel_channels_messenger import _fb_channel


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _wa_channel(session_factory, *, tenant_id=DEFAULT_TENANT_ID, phone_number_id="pn-send-1"):
    """A WhatsApp channel for the policy-matrix WhatsApp-unchanged tests -
    pytest's in-memory DB carries no seeded channel by default."""
    from modules.omnichannel.models import Channel, Workspace
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.tenant_id == tenant_id, Workspace.is_default.is_(True)).first()
    channel = Channel(
        tenant_id=tenant_id, workspace_id=ws.id, channel_type="WHATSAPP",
        name="Test WhatsApp (S2)", credentials_json=encrypt_credentials({"dev": True}),
        phone_number_id=phone_number_id, is_active=True,
        status_id=statuses.status_id_for(db, tenant_id, "CHANNEL", "ACTIVE"),
    )
    db.add(channel)
    db.commit()
    cid = channel.id
    db.close()
    return cid


def _fb_contact_with_identity(
    session_factory,
    channel_id,
    *,
    psid="psid-out-1",
    tenant_id=DEFAULT_TENANT_ID,
    window_expires_at=None,
    human_agent_expires_at=None,
    phone=None,
):
    """A contact reachable on a Messenger/Instagram channel - no phone by
    default (D-A7-4), an identity with the given (possibly expired) window
    timestamps."""
    from modules.omnichannel.models import Contact, ContactChannelIdentity, Workspace
    from modules.omnichannel.phone import digits_only
    from modules.omnichannel.services import statuses

    db = session_factory()
    ws = (
        db.query(Workspace)
        .filter(Workspace.tenant_id == tenant_id, Workspace.is_default.is_(True))
        .first()
    )
    contact = Contact(
        tenant_id=tenant_id,
        workspace_id=ws.id,
        first_name="Messenger",
        last_name="User",
        phone=phone,
        phone_digits=digits_only(phone) if phone else None,
        status_id=statuses.status_id_for(db, tenant_id, "THREAD", "OPEN"),
        priority="MEDIUM",
    )
    db.add(contact)
    db.flush()
    identity = ContactChannelIdentity(
        tenant_id=tenant_id,
        contact_id=contact.id,
        channel_id=channel_id,
        external_user_id=psid,
        window_expires_at=window_expires_at,
        human_agent_expires_at=human_agent_expires_at,
        last_inbound_at=_now(),
    )
    db.add(identity)
    db.commit()
    cid = contact.id
    db.close()
    return cid


# ── AC-CHN-22: ONE window-check call site, no `_window_open` outside it ─────
def test_no_window_open_symbol_survives_anywhere():
    """The old `message_service._window_open` is GONE (renamed/moved into
    `messaging_policy._whatsapp_window_open`) - a call to a function literally
    named `_window_open` must never appear in the module tree again (a word-
    boundary regex so `_whatsapp_window_open(...)` itself is not a false hit)."""
    import re

    from modules.omnichannel.services import (
        message_service,
        messaging_policy,
        public_gateway_service,
        send_runner,
    )

    pattern = re.compile(r"(?<![A-Za-z0-9_])_window_open\(")
    for mod in (message_service, messaging_policy, public_gateway_service, send_runner):
        assert not pattern.search(inspect.getsource(mod)), mod.__name__


def test_automation_call_sites_never_pass_actor_is_human_true():
    """The workflow action, the public gateway and broadcasts are automation
    by construction (D-A7-6) - their source never sets `actor_is_human=True`."""
    from modules.omnichannel.services import (
        broadcast_send_service,
        public_gateway_service,
        workflow_actions,
        workflow_waits,
    )

    for mod in (broadcast_send_service, public_gateway_service, workflow_actions, workflow_waits):
        assert "actor_is_human=True" not in inspect.getsource(mod), mod.__name__


def test_human_agent_router_always_passes_actor_is_human_true():
    """Every send/react endpoint in the internal (agent + embed) router is a
    real human actor (native or federated) - AC-CHN-24."""
    from modules.omnichannel.routers import conversations

    src = inspect.getsource(conversations)
    # send_message, template send, media, interactive, location, contacts, react.
    assert src.count("actor_is_human=True") == 7


# ── AC-CHN-22/24: messaging_policy.authorize - the window policy matrix ─────
def test_authorize_whatsapp_template_always_allowed_no_meta_params(session_factory):
    from modules.omnichannel.models import Channel, Contact
    from modules.omnichannel.services import messaging_policy

    channel_id = _wa_channel(session_factory, phone_number_id="pn-tpl-1")
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=channel.workspace_id,
        phone="+60111111111", phone_digits="60111111111", priority="MEDIUM",
        csw_expires_at=_now() - timedelta(hours=5),  # closed - templates are exempt
    )
    db.add(contact)
    db.commit()
    decision = messaging_policy.authorize(
        db, contact, channel, kind="TEMPLATE", actor_is_human=False
    )
    assert decision.messaging_type is None and decision.tag is None
    assert messaging_policy.send_metadata(decision) is None
    db.close()


def test_authorize_whatsapp_free_form_refused_verbatim_outside_csw(session_factory):
    from modules.omnichannel.models import Channel, Contact
    from modules.omnichannel.services import messaging_policy

    channel_id = _wa_channel(session_factory, phone_number_id="pn-tpl-2")
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=channel.workspace_id,
        phone="+60111111112", phone_digits="60111111112", priority="MEDIUM",
        csw_expires_at=_now() - timedelta(hours=1),
    )
    db.add(contact)
    db.commit()
    with pytest.raises(messaging_policy.PolicyRejected) as exc:
        messaging_policy.authorize(db, contact, channel, kind="TEXT", actor_is_human=False)
    assert exc.value.code == "csw_window_closed"
    assert exc.value.message == messaging_policy.CSW_CLOSED_MESSAGE
    db.close()


def test_authorize_facebook_inside_standard_window_is_response(session_factory):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.repositories.contact_repository import ContactRepository
    from modules.omnichannel.services import messaging_policy

    channel_id = _fb_channel(session_factory, external_account_id="pg-send-1")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id,
        window_expires_at=_now() + timedelta(hours=10),
        human_agent_expires_at=_now() + timedelta(hours=150),
    )
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    contact = ContactRepository(db).get_by_id(contact_id, DEFAULT_TENANT_ID)
    decision = messaging_policy.authorize(
        db, contact, channel, kind="TEXT", actor_is_human=False
    )
    assert decision.messaging_type == messaging_policy.MESSAGING_TYPE_RESPONSE
    assert decision.tag is None
    assert messaging_policy.send_metadata(decision) == {"messagingType": "RESPONSE"}
    db.close()


def test_authorize_facebook_human_agent_window_allows_human(session_factory):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.repositories.contact_repository import ContactRepository
    from modules.omnichannel.services import messaging_policy

    channel_id = _fb_channel(session_factory, external_account_id="pg-send-2")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id,
        window_expires_at=_now() - timedelta(hours=1),  # standard window closed
        human_agent_expires_at=_now() + timedelta(hours=100),  # still open
    )
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    contact = ContactRepository(db).get_by_id(contact_id, DEFAULT_TENANT_ID)
    decision = messaging_policy.authorize(
        db, contact, channel, kind="TEXT", actor_is_human=True
    )
    assert decision.messaging_type == messaging_policy.MESSAGING_TYPE_MESSAGE_TAG
    assert decision.tag == messaging_policy.TAG_HUMAN_AGENT
    assert messaging_policy.send_metadata(decision) == {
        "messagingType": "MESSAGE_TAG", "tag": "HUMAN_AGENT",
    }
    db.close()


def test_authorize_facebook_human_agent_window_refuses_automation(session_factory):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.repositories.contact_repository import ContactRepository
    from modules.omnichannel.services import messaging_policy

    channel_id = _fb_channel(session_factory, external_account_id="pg-send-3")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id,
        window_expires_at=_now() - timedelta(hours=1),
        human_agent_expires_at=_now() + timedelta(hours=100),
    )
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    contact = ContactRepository(db).get_by_id(contact_id, DEFAULT_TENANT_ID)
    with pytest.raises(messaging_policy.PolicyRejected) as exc:
        messaging_policy.authorize(db, contact, channel, kind="TEXT", actor_is_human=False)
    assert exc.value.code == "automation_outside_window"
    db.close()


def test_authorize_facebook_outside_both_windows_refused_for_everyone(session_factory):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.repositories.contact_repository import ContactRepository
    from modules.omnichannel.services import messaging_policy

    channel_id = _fb_channel(session_factory, external_account_id="pg-send-4")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id,
        window_expires_at=_now() - timedelta(hours=200),
        human_agent_expires_at=_now() - timedelta(hours=1),
    )
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    contact = ContactRepository(db).get_by_id(contact_id, DEFAULT_TENANT_ID)
    for actor_is_human in (True, False):
        with pytest.raises(messaging_policy.PolicyRejected) as exc:
            messaging_policy.authorize(
                db, contact, channel, kind="TEXT", actor_is_human=actor_is_human
            )
        assert exc.value.code == "messaging_window_closed"
    db.close()


def test_authorize_instagram_matches_facebook_policy_row(session_factory):
    from modules.omnichannel.models import Channel, Workspace
    from modules.omnichannel.repositories.contact_repository import ContactRepository
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import messaging_policy, statuses

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True)).first()
    channel = Channel(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, channel_type="INSTAGRAM",
        name="Test Instagram", credentials_json=encrypt_credentials({"dev": True}),
        external_account_id="ig-send-1", external_account_name="Test IG",
        is_active=True, status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
    )
    db.add(channel)
    db.commit()
    channel_id = channel.id
    db.close()

    contact_id = _fb_contact_with_identity(
        session_factory, channel_id, psid="igsid-1",
        window_expires_at=_now() - timedelta(hours=1),
        human_agent_expires_at=_now() + timedelta(hours=100),
    )
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    contact = ContactRepository(db).get_by_id(contact_id, DEFAULT_TENANT_ID)
    decision = messaging_policy.authorize(db, contact, channel, kind="TEXT", actor_is_human=True)
    assert decision.tag == messaging_policy.TAG_HUMAN_AGENT
    db.close()


# ── AC-CHN-29: assert_kind_supported / CAPABILITIES ─────────────────────────
def test_capabilities_pinned_list():
    from modules.omnichannel.services.messaging_policy import CAPABILITIES

    assert set(CAPABILITIES) == {"WHATSAPP", "FACEBOOK", "INSTAGRAM"}
    assert CAPABILITIES["WHATSAPP"].document is True
    assert CAPABILITIES["FACEBOOK"].document is True
    assert CAPABILITIES["INSTAGRAM"].document is False
    for kind in ("sticker", "template", "interactive_list", "location", "contacts", "reaction_outbound"):
        assert getattr(CAPABILITIES["FACEBOOK"], kind) is False
        assert getattr(CAPABILITIES["INSTAGRAM"], kind) is False
        assert getattr(CAPABILITIES["WHATSAPP"], kind) is True


def test_capabilities_and_policies_match_the_frontend_golden_mirror():
    """D-A7-10: `messaging_policy.CAPABILITIES`/`POLICIES` are the AUTHORITATIVE
    side of the pair `service_frontend/lib/channel-capabilities.ts` mirrors for
    UX only - this is the backend half of that golden pair (the frontend half
    is `channel-capabilities.test.ts`). Pins the exact values so a divergence
    is caught here, not discovered by a support ticket."""
    from modules.omnichannel.services.messaging_policy import CAPABILITIES, POLICIES

    assert POLICIES["WHATSAPP"].window_hours == 24
    assert POLICIES["WHATSAPP"].human_agent_hours is None
    assert POLICIES["WHATSAPP"].reengage_mode == "template"
    for channel_type in ("FACEBOOK", "INSTAGRAM"):
        assert POLICIES[channel_type].window_hours == 24
        assert POLICIES[channel_type].human_agent_hours == 168
        assert POLICIES[channel_type].reengage_mode == "human_agent"

    assert CAPABILITIES["WHATSAPP"].sticker is True
    assert CAPABILITIES["FACEBOOK"].document is True
    assert CAPABILITIES["FACEBOOK"].sticker is False
    assert CAPABILITIES["INSTAGRAM"].document is False
    assert CAPABILITIES["INSTAGRAM"].sticker is False


@pytest.mark.parametrize(
    "channel_type,kind,sub_kind",
    [
        ("FACEBOOK", "TEMPLATE", None),
        ("INSTAGRAM", "TEMPLATE", None),
        ("FACEBOOK", "STICKER", None),
        ("FACEBOOK", "LOCATION", None),
        ("FACEBOOK", "CONTACTS", None),
        ("FACEBOOK", "REACTION", None),
        ("INSTAGRAM", "DOCUMENT", None),
        ("FACEBOOK", "INTERACTIVE", "list"),
        ("FACEBOOK", "INTERACTIVE", "cta_url"),
    ],
)
def test_assert_kind_supported_rejects_unsupported_kinds(channel_type, kind, sub_kind):
    from modules.omnichannel.services import messaging_policy

    with pytest.raises(messaging_policy.PolicyRejected) as exc:
        messaging_policy.assert_kind_supported(channel_type, kind, sub_kind=sub_kind)
    assert exc.value.code == "kind_not_supported"


@pytest.mark.parametrize(
    "channel_type,kind,sub_kind",
    [
        ("FACEBOOK", "TEXT", None),
        ("FACEBOOK", "IMAGE", None),
        ("FACEBOOK", "DOCUMENT", None),
        ("INSTAGRAM", "AUDIO", None),
        ("FACEBOOK", "INTERACTIVE", "buttons"),
        ("WHATSAPP", "TEMPLATE", None),
        ("WHATSAPP", "INTERACTIVE", "list"),
    ],
)
def test_assert_kind_supported_allows_supported_kinds(channel_type, kind, sub_kind):
    from modules.omnichannel.services import messaging_policy

    messaging_policy.assert_kind_supported(channel_type, kind, sub_kind=sub_kind)  # no raise


# ── AC-CHN-26: channel_addressing ────────────────────────────────────────────
def test_channel_addressing_whatsapp_unchanged(session_factory):
    from modules.omnichannel.models import Channel, Contact
    from modules.omnichannel.services import channel_addressing

    channel_id = _wa_channel(session_factory, phone_number_id="pn-addr-1")
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=channel.workspace_id,
        phone="+60 12-345 6789", phone_digits="60123456789", priority="MEDIUM",
    )
    db.add(contact)
    db.commit()
    assert channel_addressing.sender_ref(channel) == channel.phone_number_id
    assert channel_addressing.recipient_ref(db, channel, contact) == "60123456789"
    db.close()


def test_channel_addressing_messenger_uses_identity(session_factory):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.repositories.contact_repository import ContactRepository
    from modules.omnichannel.services import channel_addressing

    channel_id = _fb_channel(session_factory, external_account_id="pg-addr-1")
    contact_id = _fb_contact_with_identity(session_factory, channel_id, psid="psid-addr-1")
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    contact = ContactRepository(db).get_by_id(contact_id, DEFAULT_TENANT_ID)
    assert channel_addressing.sender_ref(channel) == "pg-addr-1"
    assert channel_addressing.recipient_ref(db, channel, contact) == "psid-addr-1"
    db.close()


def test_channel_addressing_messenger_missing_identity_raises(session_factory):
    from modules.omnichannel.models import Channel, Contact, Workspace
    from modules.omnichannel.services import channel_addressing, statuses

    channel_id = _fb_channel(session_factory, external_account_id="pg-addr-2")
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    ws = db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True)).first()
    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", "OPEN"),
        priority="MEDIUM",
    )
    db.add(contact)
    db.commit()
    with pytest.raises(channel_addressing.NoChannelIdentity):
        channel_addressing.recipient_ref(db, channel, contact)
    db.close()


# ── Security review round 1, blocker 2 - MessageService._channel_for_contact
# `channel_id_override` guard, pinned in both directions (was widened for
# WhatsApp with no test on either side) ───────────────────────────────────
def test_channel_for_contact_whatsapp_override_accepted_for_an_identity_less_contact(session_factory):
    """A business-initiated (never-messaged-in) WhatsApp contact has NO
    `ContactChannelIdentity` at all (D-A7-3, addresses by phone). An explicit
    `channelId` override naming a WhatsApp channel must still be accepted -
    this is the relaxation `message_service.py:189-198` shipped this slice
    (`_override_for` in the gateway now relies on it, blocker 2)."""
    from modules.omnichannel.models import Channel, Contact, Workspace
    from modules.omnichannel.services import statuses
    from modules.omnichannel.services.message_service import MessageService

    channel_id = _wa_channel(session_factory, phone_number_id="pn-override-1")
    db = session_factory()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    ws = db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True)).first()
    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id,
        phone="+60111119999", phone_digits="60111119999",
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", "OPEN"),
        priority="MEDIUM",
    )
    db.add(contact)
    db.commit()

    resolved = MessageService(db)._channel_for_contact(contact, channel_id)
    assert resolved.id == channel.id
    db.close()


def test_channel_for_contact_messenger_override_still_refused_for_an_identity_less_contact(session_factory):
    """Messenger/Instagram address by IDENTITY, never by phone - the
    relaxation above is WhatsApp-only; a Messenger `channelId` override for
    a contact with no identity on that channel must still be refused."""
    from modules.omnichannel.models import Channel, Contact, Workspace
    from modules.omnichannel.services import statuses
    from modules.omnichannel.services.message_service import MessageService, SendRejected

    channel_id = _fb_channel(session_factory, external_account_id="pg-override-1")
    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True)).first()
    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", "OPEN"),
        priority="MEDIUM",
    )
    db.add(contact)
    db.commit()

    with pytest.raises(SendRejected):
        MessageService(db)._channel_for_contact(contact, channel_id)
    db.close()


# ── AC-CHN-31: tenant isolation ──────────────────────────────────────────────
def test_find_identity_for_channel_is_tenant_scoped(session_factory):
    from modules.omnichannel.repositories.contact_repository import ContactRepository

    channel_id = _fb_channel(session_factory, external_account_id="pg-iso-1")
    contact_id = _fb_contact_with_identity(session_factory, channel_id, psid="psid-iso-1")
    db = session_factory()
    same_tenant = ContactRepository(db).find_identity_for_channel(
        contact_id, channel_id, DEFAULT_TENANT_ID
    )
    other_tenant = ContactRepository(db).find_identity_for_channel(
        contact_id, channel_id, "some-other-tenant"
    )
    assert same_tenant is not None
    assert other_tenant is None
    db.close()


# ── AC-CHN-22/24/25/28/29: MessageService integration on a Messenger channel ─
def test_send_message_text_inside_window_persists_response_meta_send(session_factory):
    from modules.omnichannel.schemas import SendMessageRequest
    from modules.omnichannel.services.message_service import MessageService

    channel_id = _fb_channel(session_factory, external_account_id="pg-txt-1")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id,
        window_expires_at=_now() + timedelta(hours=10),
        human_agent_expires_at=_now() + timedelta(hours=150),
    )
    db = session_factory()
    item = MessageService(db).send_message(
        contact_id, DEFAULT_TENANT_ID, None,
        SendMessageRequest(messageType="TEXT", body="hi there"),
        actor_is_human=False,
    )
    from modules.omnichannel.models import ConversationMessage

    row = db.query(ConversationMessage).filter(ConversationMessage.id == item.id).first()
    assert row.metadata_json["metaSend"] == {"messagingType": "RESPONSE"}
    assert row.delivery_status == "SENT"  # dev-safe adapter, eager celery
    assert row.external_message_id.startswith("m.dev-")
    db.close()


def test_send_message_text_human_agent_window_tags_human_agent(session_factory):
    from modules.omnichannel.schemas import SendMessageRequest
    from modules.omnichannel.services.message_service import MessageService

    channel_id = _fb_channel(session_factory, external_account_id="pg-txt-2")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id,
        window_expires_at=_now() - timedelta(hours=1),
        human_agent_expires_at=_now() + timedelta(hours=100),
    )
    db = session_factory()
    item = MessageService(db).send_message(
        contact_id, DEFAULT_TENANT_ID, "user-1",
        SendMessageRequest(messageType="TEXT", body="still here"),
        actor_is_human=True,
    )
    from modules.omnichannel.models import ConversationMessage

    row = db.query(ConversationMessage).filter(ConversationMessage.id == item.id).first()
    assert row.metadata_json["metaSend"] == {"messagingType": "MESSAGE_TAG", "tag": "HUMAN_AGENT"}
    db.close()


def test_send_message_text_human_agent_window_refuses_automation(session_factory):
    from modules.omnichannel.schemas import SendMessageRequest
    from modules.omnichannel.services.message_service import MessageService, SendRejected
    from modules.omnichannel.services import messaging_policy

    channel_id = _fb_channel(session_factory, external_account_id="pg-txt-3")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id,
        window_expires_at=_now() - timedelta(hours=1),
        human_agent_expires_at=_now() + timedelta(hours=100),
    )
    db = session_factory()
    with pytest.raises(SendRejected) as exc:
        MessageService(db).send_message(
            contact_id, DEFAULT_TENANT_ID, None,
            SendMessageRequest(messageType="TEXT", body="auto reply"),
            actor_is_human=False,
        )
    assert exc.value.message == messaging_policy.AUTOMATION_OUTSIDE_WINDOW_MESSAGE
    db.close()


def test_send_message_template_on_messenger_channel_is_422(session_factory):
    from modules.omnichannel.schemas import SendMessageRequest
    from modules.omnichannel.services.message_service import MessageService, SendRejected

    channel_id = _fb_channel(session_factory, external_account_id="pg-tpl-1")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id, window_expires_at=_now() + timedelta(hours=10)
    )
    db = session_factory()
    with pytest.raises(SendRejected) as exc:
        MessageService(db).send_message(
            contact_id, DEFAULT_TENANT_ID, "user-1",
            SendMessageRequest(messageType="TEMPLATE", templateId="whatever"),
            actor_is_human=True,
        )
    assert "does not support message templates" in exc.value.message
    db.close()


def test_send_interactive_buttons_on_messenger_persists_meta_send(session_factory):
    from modules.omnichannel.services.message_service import MessageService

    channel_id = _fb_channel(session_factory, external_account_id="pg-int-1")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id, window_expires_at=_now() + timedelta(hours=10)
    )
    db = session_factory()
    item = MessageService(db).send_interactive(
        contact_id, DEFAULT_TENANT_ID, "user-1",
        defn={
            "kind": "buttons", "body": "Pick one",
            "buttons": [{"id": "yes", "title": "Yes"}, {"id": "no", "title": "No"}],
        },
        actor_is_human=True,
    )
    from modules.omnichannel.models import ConversationMessage

    row = db.query(ConversationMessage).filter(ConversationMessage.id == item.id).first()
    assert row.message_type == "INTERACTIVE"
    assert row.metadata_json["metaSend"] == {"messagingType": "RESPONSE"}
    db.close()


def test_send_interactive_list_on_messenger_is_rejected(session_factory):
    from modules.omnichannel.services.message_service import MessageService, SendRejected

    channel_id = _fb_channel(session_factory, external_account_id="pg-int-2")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id, window_expires_at=_now() + timedelta(hours=10)
    )
    db = session_factory()
    with pytest.raises(SendRejected) as exc:
        MessageService(db).send_interactive(
            contact_id, DEFAULT_TENANT_ID, "user-1",
            defn={
                "kind": "list", "body": "Pick one",
                "list": {"button": "Menu", "sections": [{"rows": [{"id": "a", "title": "A"}]}]},
            },
            actor_is_human=True,
        )
    assert "only supports quick-reply buttons" in exc.value.message
    db.close()


def test_send_location_and_contacts_rejected_on_messenger(session_factory):
    from modules.omnichannel.services.message_service import MessageService, SendRejected

    channel_id = _fb_channel(session_factory, external_account_id="pg-loc-1")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id, window_expires_at=_now() + timedelta(hours=10)
    )
    db = session_factory()
    with pytest.raises(SendRejected) as exc:
        MessageService(db).send_location(
            contact_id, DEFAULT_TENANT_ID, "user-1",
            defn={"lat": 1.23, "lng": 103.4}, actor_is_human=True,
        )
    assert "does not support location messages" in exc.value.message

    with pytest.raises(SendRejected) as exc2:
        MessageService(db).send_contacts(
            contact_id, DEFAULT_TENANT_ID, "user-1",
            defn={"contacts": [{"name": "Sam", "phones": [{"phone": "+601111"}]}]},
            actor_is_human=True,
        )
    assert "does not support contact-card messages" in exc2.value.message
    db.close()


def test_react_rejected_on_messenger(session_factory):
    from modules.omnichannel.models import ConversationMessage
    from modules.omnichannel.services.message_service import MessageService, SendRejected

    channel_id = _fb_channel(session_factory, external_account_id="pg-react-1")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id, window_expires_at=_now() + timedelta(hours=10)
    )
    db = session_factory()
    msg = ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID, contact_id=contact_id, channel_id=channel_id,
        sender_type="CONTACT", message_type="TEXT", body="hi",
        external_message_id="m.inbound-1",
    )
    db.add(msg)
    db.commit()
    with pytest.raises(SendRejected) as exc:
        MessageService(db).react(
            msg.id, DEFAULT_TENANT_ID, "user-1", emoji="\U0001F44D", actor_is_human=True,
        )
    assert "does not support reactions" in exc.value.message
    db.close()


def test_send_media_document_rejected_on_instagram_allowed_on_messenger(session_factory):
    from modules.omnichannel.models import Channel, Workspace
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses
    from modules.omnichannel.services.message_service import MessageService, SendRejected

    fb_channel_id = _fb_channel(session_factory, external_account_id="pg-doc-1")
    fb_contact_id = _fb_contact_with_identity(
        session_factory, fb_channel_id, window_expires_at=_now() + timedelta(hours=10)
    )

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True)).first()
    ig_channel = Channel(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id, channel_type="INSTAGRAM",
        name="Test IG doc", credentials_json=encrypt_credentials({"dev": True}),
        external_account_id="ig-doc-1", is_active=True,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
    )
    db.add(ig_channel)
    db.commit()
    ig_channel_id = ig_channel.id
    db.close()
    ig_contact_id = _fb_contact_with_identity(
        session_factory, ig_channel_id, psid="igsid-doc-1",
        window_expires_at=_now() + timedelta(hours=10),
    )

    db = session_factory()
    with pytest.raises(SendRejected) as exc:
        MessageService(db).send_media(
            ig_contact_id, DEFAULT_TENANT_ID, "user-1",
            kind="DOCUMENT", content=b"%PDF-1.4 fake", filename="a.pdf", caption=None,
            actor_is_human=True,
        )
    assert "does not support file attachments" in exc.value.message

    from modules.omnichannel.models import ConversationMessage

    item = MessageService(db).send_media(
        fb_contact_id, DEFAULT_TENANT_ID, "user-1",
        kind="DOCUMENT", content=b"%PDF-1.4 fake", filename="a.pdf", caption=None,
        actor_is_human=True,
    )
    row = db.query(ConversationMessage).filter(ConversationMessage.id == item.id).first()
    assert row.message_type == "DOCUMENT"
    db.close()


# ── AC-CHN-24: workflow action refuses automation past 24h ──────────────────
def test_workflow_action_send_message_refuses_automation_past_24h(session_factory):
    from modules.omnichannel.services.workflow_actions import ActionError, omnichannel_send_message

    channel_id = _fb_channel(session_factory, external_account_id="pg-wf-1")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id,
        window_expires_at=_now() - timedelta(hours=1),
        human_agent_expires_at=_now() + timedelta(hours=100),
    )
    db = session_factory()
    with pytest.raises(ActionError) as exc:
        omnichannel_send_message(
            db, DEFAULT_TENANT_ID,
            {"contactId": contact_id, "mode": "text", "message": "late reply"}, {},
        )
    assert "Automated messages cannot be sent" in str(exc.value)
    db.close()


def test_workflow_action_send_message_inside_window_succeeds(session_factory):
    from modules.omnichannel.services.workflow_actions import omnichannel_send_message

    channel_id = _fb_channel(session_factory, external_account_id="pg-wf-2")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id, window_expires_at=_now() + timedelta(hours=10)
    )
    db = session_factory()
    out = omnichannel_send_message(
        db, DEFAULT_TENANT_ID,
        {"contactId": contact_id, "mode": "text", "message": "hello"}, {},
    )
    assert out["messageId"]
    db.close()


# ── AC-CHN-27/28/30: MessengerAdapter.send (dev-safe + real payload shape) ──
def test_messenger_adapter_send_dev_safe_no_network(monkeypatch):
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    monkeypatch.setattr(settings, "meta_app_id", "")
    adapter = MessengerAdapter()
    result = adapter.send({"dev": True}, "pg-1", "psid-1", text="hi")
    assert result["external_message_id"].startswith("m.dev-")


def test_messenger_adapter_send_real_text_payload_shape(monkeypatch):
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"recipient_id": "psid-1", "message_id": "mid.123"})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    result = adapter.send(
        {"access_token": "tok"}, "pg-1", "psid-1",
        text="hi there", messaging_type="RESPONSE",
    )
    assert result["external_message_id"] == "mid.123"
    assert captured["body"]["recipient"] == {"id": "psid-1"}
    assert captured["body"]["messaging_type"] == "RESPONSE"
    assert "tag" not in captured["body"]
    assert captured["body"]["message"]["text"] == "hi there"


def test_messenger_adapter_send_real_quick_replies_payload_shape(monkeypatch):
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"recipient_id": "psid-1", "message_id": "mid.456"})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    defn = {
        "kind": "buttons", "body": "Pick one",
        "buttons": [{"id": f"b{i}", "title": f"Option {i}"} for i in range(20)],
    }
    result = adapter.send(
        {"access_token": "tok"}, "pg-1", "psid-1",
        structured=defn, messaging_type="MESSAGE_TAG", tag="HUMAN_AGENT",
    )
    assert result["external_message_id"] == "mid.456"
    assert captured["body"]["tag"] == "HUMAN_AGENT"
    quick_replies = captured["body"]["message"]["quick_replies"]
    assert len(quick_replies) == 13  # capped
    assert all(len(qr["title"]) <= 20 for qr in quick_replies)
    assert captured["body"]["message"]["text"] == "Pick one"


def test_messenger_adapter_send_error_maps_transient_on_5xx(monkeypatch):
    from modules.omnichannel.adapters.base import SendError
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "Server hiccup"}})

    fake = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = MessengerAdapter(client=fake)
    with pytest.raises(SendError) as exc:
        adapter.send({"access_token": "tok"}, "pg-1", "psid-1", text="hi")
    assert exc.value.transient is True


# ── build_quick_replies (D-A7-13) ────────────────────────────────────────────
def test_build_quick_replies_caps_and_truncates():
    from modules.omnichannel.services.structured import build_quick_replies

    defn = {
        "kind": "buttons",
        "buttons": [{"id": f"b{i}", "title": "X" * 30} for i in range(20)],
    }
    out = build_quick_replies(defn)
    assert len(out) == 13
    assert all(len(b["title"]) == 20 for b in out)
    assert all(b["content_type"] == "text" for b in out)


def test_build_quick_replies_non_buttons_kind_returns_none():
    from modules.omnichannel.services.structured import build_quick_replies

    assert build_quick_replies({"kind": "list"}) is None


# ── AC-CHN-25/26/27: send_runner end to end on a Messenger channel ──────────
def test_send_runner_generalized_addressing_and_persisted_meta_send(session_factory, monkeypatch):
    from modules.omnichannel.schemas import SendMessageRequest
    from modules.omnichannel.services.message_service import MessageService

    channel_id = _fb_channel(session_factory, external_account_id="pg-run-1")
    contact_id = _fb_contact_with_identity(
        session_factory, channel_id, psid="psid-run-1",
        window_expires_at=_now() - timedelta(hours=1),
        human_agent_expires_at=_now() + timedelta(hours=100),
    )

    captured = {}
    from modules.omnichannel.adapters.messenger import MessengerAdapter

    real_send = MessengerAdapter.send

    def spy_send(self, credentials, phone_number_id, to, **kwargs):
        captured["phone_number_id"] = phone_number_id
        captured["to"] = to
        captured["messaging_type"] = kwargs.get("messaging_type")
        captured["tag"] = kwargs.get("tag")
        return real_send(self, credentials, phone_number_id, to, **kwargs)

    monkeypatch.setattr(MessengerAdapter, "send", spy_send)

    db = session_factory()
    item = MessageService(db).send_message(
        contact_id, DEFAULT_TENANT_ID, "user-1",
        SendMessageRequest(messageType="TEXT", body="still reachable"),
        actor_is_human=True,
    )
    assert item.deliveryStatus == "SENT"
    assert captured["phone_number_id"] == "pg-run-1"
    assert captured["to"] == "psid-run-1"
    assert captured["messaging_type"] == "MESSAGE_TAG"
    assert captured["tag"] == "HUMAN_AGENT"
    db.close()


def test_send_runner_no_identity_fails_cleanly(session_factory):
    """A queued row whose contact has no identity on the chosen channel fails
    the send with a typed reason rather than addressing an empty recipient
    (AC-CHN-26)."""
    from modules.omnichannel.models import Channel, ConversationMessage, Workspace
    from modules.omnichannel.services import statuses
    from modules.omnichannel.services.send_runner import run_send

    channel_id = _fb_channel(session_factory, external_account_id="pg-run-2")
    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True)).first()
    from modules.omnichannel.models import Contact

    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws.id,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", "OPEN"),
        priority="MEDIUM",
    )
    db.add(contact)
    db.flush()
    row = ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID, contact_id=contact.id, channel_id=channel_id,
        sender_type="AGENT", message_type="TEXT", body="hi", delivery_status="QUEUED",
    )
    db.add(row)
    db.commit()
    status = run_send(db, row.id)
    assert status == "FAILED"
    db.refresh(row)
    assert "no identity" in (row.error_message or "").lower()
    db.close()
