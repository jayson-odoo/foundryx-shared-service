"""S12 (2026-11-18, decision D3): per-number WhatsApp window enforcement, opt-in.

`omnichannel_settings.strict_number_window` (NULL/false = today). When true,
`messaging_policy` reads the WhatsApp free-form window from the TARGET
number's identity (`contact_channel_identities.window_expires_at`) instead of
the contact-level `contacts.csw_expires_at`. Every send path funnels through
`messaging_policy.authorize`; these tests drive each path with the flag off
(today's exact answer) and on.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.services import idempotency
from modules.omnichannel.services.messaging_policy import CSW_CLOSED_MESSAGE
from tests.test_omnichannel_api_gateway import _auth, _default_workspace_id, _mint, _seed_channel
from tests.test_omnichannel_embed import _assertion, _bearer, _exchange, _make_connection
from tests.test_omnichannel_webhooks import _process, _wa_payload

API = "/api/v1/omnichannel"
PHONE = "+60177000001"
DIGITS = "60177000001"


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


def _set_strict(session_factory, workspace_id, value):
    from modules.omnichannel.services.media_settings_service import MediaSettingsService

    db = session_factory()
    MediaSettingsService(db).set_overrides(
        DEFAULT_TENANT_ID, workspace_id, {"strictNumberWindow": value}
    )
    db.close()


def _contact_id(session_factory, digits=DIGITS):
    from modules.omnichannel.models import Contact

    db = session_factory()
    cid = db.query(Contact).filter(Contact.phone_digits == digits).first().id
    db.close()
    return cid


def _two_numbers_customer_wrote_to_a(session_factory):
    """Workspace with WhatsApp numbers A and B; the customer wrote to A just
    now. Contact-level window open; A's identity window open; no identity on B."""
    ws = _default_workspace_id(session_factory)
    ch_a = _seed_channel(session_factory, ws, phone_number_id="pn-s12-a")
    ch_b = _seed_channel(session_factory, ws, phone_number_id="pn-s12-b")
    _process(session_factory, ch_a, _wa_payload(wamid="wamid.s12-a", from_=DIGITS, text="hi on A"))
    return ws, ch_a, ch_b, _contact_id(session_factory)


def _contact_open_but_target_number_closed(session_factory):
    """Contact-level window open (refreshed by a number the send will not use),
    the only live identity is number B with an EXPIRED window - the internal
    send paths (dashboard, embed) resolve to B."""
    from modules.omnichannel.models import Contact, ContactChannelIdentity
    from modules.omnichannel.services import statuses

    ws = _default_workspace_id(session_factory)
    ch_b = _seed_channel(session_factory, ws, phone_number_id="pn-s12-only-b")
    db = session_factory()
    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, first_name="Two", phone=PHONE,
        phone_digits=DIGITS,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", "OPEN"),
        priority="MEDIUM", csw_expires_at=_now() + timedelta(hours=20),
    )
    db.add(contact)
    db.flush()
    db.add(ContactChannelIdentity(
        tenant_id=DEFAULT_TENANT_ID, contact_id=contact.id, channel_id=ch_b,
        external_user_id=DIGITS, window_expires_at=_now() - timedelta(hours=30),
    ))
    db.commit()
    cid = contact.id
    db.close()
    return ws, ch_b, cid


def _api_send(client, hdr, channel_id, body="free form"):
    return client.post(
        f"{API}/messages",
        json={"to": PHONE, "type": "text", "text": {"body": body}, "channelId": channel_id},
        headers=hdr,
    )


# ── Default off: today's behaviour ───────────────────────────────────────────
def test_setting_defaults_off(session_factory):
    from modules.omnichannel.services.media_settings_service import MediaSettingsService

    ws = _default_workspace_id(session_factory)
    db = session_factory()
    assert MediaSettingsService(db).strict_number_window(DEFAULT_TENANT_ID, ws) is False
    db.close()


# ── Public API ───────────────────────────────────────────────────────────────
def test_api_free_form_on_other_number_off_vs_on(client, session_factory):
    ws, ch_a, ch_b, _cid = _two_numbers_customer_wrote_to_a(session_factory)
    hdr = {"Authorization": f"Bearer {_mint(client, ws).json()['fullKey']}"}

    off = _api_send(client, hdr, ch_b)
    assert off.status_code == 202, off.text  # today: accepted (Meta later refuses)

    _set_strict(session_factory, ws, True)
    on = _api_send(client, hdr, ch_b, body="second try")
    assert on.status_code == 409
    assert on.json() == {
        "error": {"code": "csw_window_closed", "message": CSW_CLOSED_MESSAGE}
    }, "same body as today's closed-window refusal"
    # The number the customer wrote to is still open in strict mode.
    assert _api_send(client, hdr, ch_a, body="on A").status_code == 202

    _set_strict(session_factory, ws, False)
    assert _api_send(client, hdr, ch_b, body="off again").status_code == 202


def test_api_media_precheck_honours_the_flag(client, session_factory, monkeypatch):
    """The media-by-URL pre-flight peek (`window_open`) uses the same decision,
    so a strict refusal happens before any media fetch."""
    from modules.omnichannel.services import public_gateway_service

    ws, _a, ch_b, _cid = _two_numbers_customer_wrote_to_a(session_factory)
    hdr = {"Authorization": f"Bearer {_mint(client, ws).json()['fullKey']}"}
    _set_strict(session_factory, ws, True)

    def _no_fetch(*_a, **_k):
        raise AssertionError("media must not be fetched for a closed number")

    monkeypatch.setattr(public_gateway_service.PublicGatewayService, "_fetch_url", _no_fetch)
    res = client.post(
        f"{API}/messages",
        json={"to": PHONE, "type": "image", "media": {"url": "https://cdn.example.com/a.jpg"},
              "channelId": ch_b},
        headers=hdr,
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "csw_window_closed"


def test_api_template_always_allowed_when_strict(client, session_factory):
    from modules.omnichannel.models import WhatsappTemplate

    ws, _a, ch_b, _cid = _two_numbers_customer_wrote_to_a(session_factory)
    db = session_factory()
    tpl = WhatsappTemplate(
        tenant_id=DEFAULT_TENANT_ID, channel_id=ch_b, name="s12_hello", language="en",
        status="APPROVED", components_json=[{"type": "BODY", "text": "Hello"}],
    )
    db.add(tpl)
    db.commit()
    db.close()
    hdr = {"Authorization": f"Bearer {_mint(client, ws).json()['fullKey']}"}
    _set_strict(session_factory, ws, True)
    res = client.post(
        f"{API}/messages",
        json={"to": PHONE, "type": "template", "channelId": ch_b,
              "template": {"name": "s12_hello"}},
        headers=hdr,
    )
    assert res.status_code == 202, res.text


# ── Dashboard + embed (human actor, same conversations route) ───────────────
def test_dashboard_reply_off_vs_on(client, session_factory):
    ws, _b, cid = _contact_open_but_target_number_closed(session_factory)
    off = client.post(f"/omnichannel/contacts/{cid}/messages", json={"body": "hi"}, headers=_auth(client))
    assert off.status_code == 201, off.text

    _set_strict(session_factory, ws, True)
    on = client.post(f"/omnichannel/contacts/{cid}/messages", json={"body": "hi"}, headers=_auth(client))
    assert on.status_code == 422
    assert on.json() == {"detail": CSW_CLOSED_MESSAGE}, "same body as today's dashboard refusal"


def test_embed_reply_off_vs_on(client, session_factory):
    ws, _b, cid = _contact_open_but_target_number_closed(session_factory)
    conn = _make_connection(session_factory)

    def _send():
        token = _exchange(client, _assertion(iss=conn, workspace_id=ws)).json()["accessToken"]
        return client.post(
            f"/omnichannel/contacts/{cid}/messages", json={"body": "from widget"},
            headers=_bearer(token),
        )

    assert _send().status_code == 201
    _set_strict(session_factory, ws, True)
    on = _send()
    assert on.status_code == 422 and on.json() == {"detail": CSW_CLOSED_MESSAGE}


# ── Workflow action ──────────────────────────────────────────────────────────
def test_workflow_send_on_other_number_off_vs_on(session_factory):
    from modules.omnichannel.services.workflow_actions import ActionError, omnichannel_send_message

    ws, _a, ch_b, cid = _two_numbers_customer_wrote_to_a(session_factory)
    ctx = {"trigger.channel.id": ch_b}
    cfg = {"contactId": cid, "mode": "text", "message": "automated"}
    db = session_factory()
    assert omnichannel_send_message(db, DEFAULT_TENANT_ID, cfg, ctx)["messageId"]
    db.close()

    _set_strict(session_factory, ws, True)
    db = session_factory()
    with pytest.raises(ActionError) as exc:
        omnichannel_send_message(db, DEFAULT_TENANT_ID, cfg, ctx)
    assert str(exc.value) == CSW_CLOSED_MESSAGE
    db.close()


# ── Broadcast (template send through the same call it makes) ────────────────
def test_broadcast_style_template_send_unaffected_by_strict(session_factory):
    from modules.omnichannel.models import WhatsappTemplate
    from modules.omnichannel.schemas import SendMessageRequest
    from modules.omnichannel.services.message_service import MessageService

    ws, _a, ch_b, cid = _two_numbers_customer_wrote_to_a(session_factory)
    db = session_factory()
    tpl = WhatsappTemplate(
        tenant_id=DEFAULT_TENANT_ID, channel_id=ch_b, name="s12_promo", language="en",
        status="APPROVED", components_json=[{"type": "BODY", "text": "Promo"}],
    )
    db.add(tpl)
    db.commit()
    tpl_id = tpl.id
    db.close()
    _set_strict(session_factory, ws, True)
    db = session_factory()
    item = MessageService(db).send_message(
        cid, DEFAULT_TENANT_ID, None,
        SendMessageRequest(messageType="TEMPLATE", templateId=tpl_id),
        channel_id_override=ch_b,
        metadata_extra={"broadcast": {"id": "b-1", "recipientId": "r-1"}},
        actor_is_human=False,
    )
    assert item.id
    db.close()


# ── Edge cases ───────────────────────────────────────────────────────────────
def test_identity_missing_for_target_number_is_closed_when_strict(session_factory):
    from modules.omnichannel.models import Channel, Contact
    from modules.omnichannel.services import messaging_policy

    ws, _a, ch_b, cid = _two_numbers_customer_wrote_to_a(session_factory)
    db = session_factory()
    contact = db.get(Contact, cid)
    channel = db.get(Channel, ch_b)
    assert messaging_policy.window_open(db, contact, channel) is True  # off: contact-level
    db.close()
    _set_strict(session_factory, ws, True)
    db = session_factory()
    contact = db.get(Contact, cid)
    channel = db.get(Channel, ch_b)
    assert messaging_policy.window_open(db, contact, channel) is False
    with pytest.raises(messaging_policy.PolicyRejected) as exc:
        messaging_policy.authorize(db, contact, channel, kind="TEXT", actor_is_human=True)
    assert exc.value.code == "csw_window_closed"
    db.close()


def test_inbound_on_the_same_number_reopens_it(client, session_factory):
    ws, ch_a, ch_b, _cid = _two_numbers_customer_wrote_to_a(session_factory)
    hdr = {"Authorization": f"Bearer {_mint(client, ws).json()['fullKey']}"}
    _set_strict(session_factory, ws, True)
    assert _api_send(client, hdr, ch_b).status_code == 409
    _process(session_factory, ch_b, _wa_payload(wamid="wamid.s12-b", from_=DIGITS, text="now on B"))
    assert _api_send(client, hdr, ch_b, body="reply on B").status_code == 202


@pytest.mark.parametrize("strict", [False, True])
def test_one_number_contact_identical_in_both_modes(client, session_factory, strict):
    from modules.omnichannel.models import Contact, ContactChannelIdentity

    ws = _default_workspace_id(session_factory)
    ch = _seed_channel(session_factory, ws, phone_number_id="pn-s12-single")
    _process(session_factory, ch, _wa_payload(wamid="wamid.s12-one", from_=DIGITS, text="hello"))
    hdr = {"Authorization": f"Bearer {_mint(client, ws).json()['fullKey']}"}
    _set_strict(session_factory, ws, strict)
    open_send = _api_send(client, hdr, ch)
    assert open_send.status_code == 202

    # Window lapses on the number (both stamps move together on inbound).
    db = session_factory()
    past = _now() - timedelta(hours=1)
    db.query(Contact).filter(Contact.phone_digits == DIGITS).update({Contact.csw_expires_at: past})
    db.query(ContactChannelIdentity).filter(ContactChannelIdentity.channel_id == ch).update(
        {ContactChannelIdentity.window_expires_at: past}
    )
    db.commit()
    db.close()
    closed = _api_send(client, hdr, ch, body="late")
    assert closed.status_code == 409
    assert closed.json()["error"]["code"] == "csw_window_closed"


@pytest.mark.parametrize(
    "window_h, human_h, human, expected",
    [
        (10, 150, False, "RESPONSE"),
        (-1, 100, True, "MESSAGE_TAG"),
        (-1, 100, False, "automation_outside_window"),
        (-1, -1, True, "messaging_window_closed"),
    ],
)
def test_messenger_policy_unaffected_by_the_flag(session_factory, window_h, human_h, human, expected):
    from modules.omnichannel.models import Channel, Contact
    from modules.omnichannel.services import messaging_policy
    from tests.test_omnichannel_channels_messenger import _fb_channel
    from tests.test_omnichannel_channels_send import _fb_contact_with_identity

    ws = _default_workspace_id(session_factory)
    ch = _fb_channel(session_factory, external_account_id="pg-s12")
    cid = _fb_contact_with_identity(
        session_factory, ch,
        window_expires_at=_now() + timedelta(hours=window_h),
        human_agent_expires_at=_now() + timedelta(hours=human_h),
    )

    def _answer():
        db = session_factory()
        try:
            d = messaging_policy.authorize(
                db, db.get(Contact, cid), db.get(Channel, ch), kind="TEXT", actor_is_human=human
            )
            return d.messaging_type
        except messaging_policy.PolicyRejected as exc:
            return exc.code
        finally:
            db.close()

    assert _answer() == expected
    _set_strict(session_factory, ws, True)
    assert _answer() == expected


def test_webchat_unaffected_by_the_flag(session_factory):
    from modules.omnichannel.models import Channel, Contact, ContactChannelIdentity
    from modules.omnichannel.services import messaging_policy, statuses
    from tests.test_omnichannel_channels_send import _web_channel

    ws = _default_workspace_id(session_factory)
    ch = _web_channel(session_factory, widget_key="wk-s12")
    db = session_factory()
    contact = Contact(
        tenant_id=DEFAULT_TENANT_ID, workspace_id=ws, first_name="Visitor",
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", "OPEN"), priority="MEDIUM",
    )
    db.add(contact)
    db.flush()
    db.add(ContactChannelIdentity(
        tenant_id=DEFAULT_TENANT_ID, contact_id=contact.id, channel_id=ch, external_user_id="v-1",
    ))
    db.commit()
    cid = contact.id
    db.close()
    _set_strict(session_factory, ws, True)
    db = session_factory()
    decision = messaging_policy.authorize(
        db, db.get(Contact, cid), db.get(Channel, ch), kind="TEXT", actor_is_human=False
    )
    assert decision.messaging_type is None
    assert messaging_policy.window_open(db, db.get(Contact, cid), db.get(Channel, ch)) is True
    db.close()


# ── Setting resolution + management ──────────────────────────────────────────
def test_tenant_default_applies_and_workspace_value_wins(session_factory):
    from modules.omnichannel.services.media_settings_service import MediaSettingsService

    ws = _default_workspace_id(session_factory)
    db = session_factory()
    svc = MediaSettingsService(db)
    svc.set_overrides(DEFAULT_TENANT_ID, ws, {"imageMaxBytes": 1000})  # row with strict NULL
    assert svc.strict_number_window(DEFAULT_TENANT_ID, ws) is False
    svc.set_overrides(DEFAULT_TENANT_ID, None, {"strictNumberWindow": True})
    assert svc.strict_number_window(DEFAULT_TENANT_ID, ws) is True  # inherits tenant default
    svc.set_overrides(DEFAULT_TENANT_ID, ws, {"strictNumberWindow": False})
    assert svc.strict_number_window(DEFAULT_TENANT_ID, ws) is False  # workspace wins
    svc.set_overrides(DEFAULT_TENANT_ID, ws, {"strictNumberWindow": None})
    assert svc.strict_number_window(DEFAULT_TENANT_ID, ws) is True  # cleared = inherit
    db.close()


def test_settings_route_sets_and_reads_the_flag_additively(client, session_factory):
    ws = _default_workspace_id(session_factory)
    hdr = _auth(client)
    before = client.get(f"/omnichannel/settings?workspaceId={ws}", headers=hdr)
    assert before.status_code == 200
    body = before.json()
    assert {"workspaceId", "overrides", "effective"} <= set(body)
    assert body["strictNumberWindow"] is None and body["strictNumberWindowEffective"] is False

    caps = client.put(
        f"/omnichannel/settings?workspaceId={ws}", json={"imageMaxBytes": 2048}, headers=hdr
    ).json()
    assert caps["strictNumberWindow"] is None  # omitted = unchanged

    on = client.put(
        f"/omnichannel/settings?workspaceId={ws}", json={"strictNumberWindow": True}, headers=hdr
    )
    assert on.status_code == 200
    assert on.json()["strictNumberWindow"] is True and on.json()["strictNumberWindowEffective"] is True
    assert on.json()["overrides"]["imageMaxBytes"] == 2048  # media caps untouched
    assert on.json()["overrides"] == caps["overrides"] and on.json()["effective"] == caps["effective"]

    cleared = client.put(
        f"/omnichannel/settings?workspaceId={ws}", json={"strictNumberWindow": None}, headers=hdr
    ).json()
    assert cleared["strictNumberWindow"] is None and cleared["strictNumberWindowEffective"] is False


def test_migration_adds_one_nullable_column_on_top_of_0026():
    import ast
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "modules/omnichannel/alembic/versions/0029_omni_strict_number_window.py"
    )
    src = path.read_text()
    assigned = {
        t.id: ast.literal_eval(n.value)
        for n in ast.parse(src).body if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name) and t.id in ("revision", "down_revision")
    }
    assert assigned["revision"] == "0029_omni_strict_number_window"
    assert len(assigned["revision"]) <= 32
    assert assigned["down_revision"] == "0028_omni_partner_api_keys"
    assert "nullable=True" in src and "strict_number_window" in src
