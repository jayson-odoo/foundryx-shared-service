"""Plan 34 (A7b) Slice S6 - public gateway `webchat:` `to` prefix, widened
`channelType`/`visitorLastSeenAt` on both read shapes, the consumer-guide
diff, and `omnichannel.send_message`'s no-window-refusal on a web chat
contact.

AC-WEB-58..61 (see documentation/plans/sprint-4/
34-omnichannel-channel-web-chat-acceptance-criteria.md).
"""
import pathlib

from app.models import DEFAULT_TENANT_ID
from tests.test_omnichannel_api_gateway import _default_workspace_id, _mint
from tests.test_omnichannel_channels_webchat import _auth, _connect
from tests.test_omnichannel_webchat_public import _post_message, _session

ORIGIN = "https://shop.acme.com"


def _new_webchat_channel(client, *, name="Gateway Web Chat"):
    h = _auth(client)
    body = _connect(client, h, name=name, allowed_origins=[ORIGIN]).json()
    return body["widgetKey"], body["id"]


def _key(client, workspace_id) -> str:
    return _mint(client, workspace_id).json()["fullKey"]


def _send(client, key, body):
    return client.post(
        "/api/v1/omnichannel/messages", json=body, headers={"Authorization": f"Bearer {key}"}
    )


# ── AC-WEB-58: `webchat:` resolves an EXISTING identity, never creates ──────
def test_to_webchat_visitor_resolves_the_existing_identity_and_sends(client, session_factory):
    ws = _default_workspace_id(session_factory)
    widget_key, channel_id = _new_webchat_channel(client)
    key = _key(client, ws)

    token = _session(client, widget_key).json()["token"]
    _post_message(client, widget_key, token, text="Hi, I need help")

    from modules.omnichannel.models import ContactChannelIdentity

    db = session_factory()
    identity = (
        db.query(ContactChannelIdentity)
        .filter(ContactChannelIdentity.channel_id == channel_id)
        .first()
    )
    external_user_id = identity.external_user_id
    db.close()
    assert external_user_id.startswith("visitor:")

    r = _send(
        client, key,
        {
            "to": f"webchat:{external_user_id}",
            "channelId": channel_id,
            "type": "text",
            "text": {"body": "hi there"},
        },
    )
    assert r.status_code == 202, r.text


def test_to_webchat_host_identity_resolves_the_existing_identity(client, session_factory):
    """The `host:<userRef>` namespace resolves identically to `visitor:` -
    the prefix split preserves whatever the identity's own `external_user_id`
    carries verbatim (AC-WEB-58's "check both namespaces" instruction)."""
    import hashlib
    import hmac

    ws = _default_workspace_id(session_factory)
    h = _auth(client)
    body = _connect(client, h, name="Gateway Web Chat Host", allowed_origins=[ORIGIN]).json()
    widget_key, channel_id, secret = body["widgetKey"], body["id"], body["widgetSecret"]
    key = _key(client, ws)

    user_ref = "user-4821"
    sig = hmac.new(secret.encode("utf-8"), user_ref.encode("utf-8"), hashlib.sha256).hexdigest()
    token = _session(client, widget_key, identity={"userRef": user_ref, "hash": sig}).json()["token"]
    _post_message(client, widget_key, token, text="hello")

    from modules.omnichannel.models import ContactChannelIdentity

    db = session_factory()
    identity = (
        db.query(ContactChannelIdentity)
        .filter(ContactChannelIdentity.channel_id == channel_id)
        .first()
    )
    external_user_id = identity.external_user_id
    db.close()
    assert external_user_id == f"host:{user_ref}"

    r = _send(
        client, key,
        {
            "to": f"webchat:{external_user_id}",
            "channelId": channel_id,
            "type": "text",
            "text": {"body": "hi there"},
        },
    )
    assert r.status_code == 202, r.text


def test_to_webchat_that_resolves_nothing_is_422_and_never_creates_a_contact(client, session_factory):
    ws = _default_workspace_id(session_factory)
    widget_key, channel_id = _new_webchat_channel(client)
    key = _key(client, ws)

    from modules.omnichannel.models import Contact

    db = session_factory()
    before = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID).count()
    db.close()

    r = _send(
        client, key,
        {
            "to": "webchat:visitor:no-such-visitor",
            "channelId": channel_id,
            "type": "text",
            "text": {"body": "hi"},
        },
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_recipient"

    db = session_factory()
    after = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID).count()
    db.close()
    assert after == before


def test_to_webchat_identity_on_a_different_channel_is_422(client, session_factory):
    """The identity must resolve on the CHOSEN channel - the same rule as
    `psid:`/`igsid:` (AC-WEB-58 mirrors AC-CHN-54)."""
    ws = _default_workspace_id(session_factory)
    widget_key_a, channel_a = _new_webchat_channel(client, name="Chat A")
    _widget_key_b, channel_b = _new_webchat_channel(client, name="Chat B")
    key = _key(client, ws)

    token = _session(client, widget_key_a).json()["token"]
    _post_message(client, widget_key_a, token, text="hi from A")

    from modules.omnichannel.models import ContactChannelIdentity

    db = session_factory()
    identity = (
        db.query(ContactChannelIdentity)
        .filter(ContactChannelIdentity.channel_id == channel_a)
        .first()
    )
    external_user_id = identity.external_user_id
    db.close()

    r = _send(
        client, key,
        {
            "to": f"webchat:{external_user_id}",
            "channelId": channel_b,  # WRONG channel - identity only exists on A
            "type": "text",
            "text": {"body": "hi"},
        },
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_recipient"


# ── AC-WEB-59: widened channelType + visitorLastSeenAt on BOTH shapes ───────
def test_default_and_rio_shapes_carry_webchat_type_and_no_window(client, session_factory):
    ws = _default_workspace_id(session_factory)
    widget_key, channel_id = _new_webchat_channel(client, name="Read Shapes Chat")
    key = _key(client, ws)

    token = _session(client, widget_key).json()["token"]
    _post_message(client, widget_key, token, text="hello there")

    hdr = {"Authorization": f"Bearer {key}"}
    default = client.get("/api/v1/omnichannel/contacts", headers=hdr).json()
    web_thread = next(t for t in default["data"] if t["channelId"] == channel_id)
    assert web_thread["channelType"] == "WEBCHAT"
    assert web_thread["cswExpiresAt"] is None
    assert web_thread["windowExpiresAt"] is None
    assert web_thread["humanAgentExpiresAt"] is None
    assert web_thread["visitorLastSeenAt"] is not None

    rio = client.get(
        "/api/v1/omnichannel/contacts", headers=hdr, params={"format": "rio"}
    ).json()
    web_rio = next(i for i in rio["items"] if i["channelId"] == channel_id)
    assert web_rio["channelType"] == "WEBCHAT"
    assert web_rio["cswExpiresAt"] is None
    assert web_rio["windowExpiresAt"] is None
    assert web_rio["humanAgentExpiresAt"] is None
    assert web_rio["visitorLastSeenAt"] is not None


def test_visitor_profile_is_lossless_on_both_read_shapes(client, session_factory):
    """Review round 1 (B3) - the unverified pre-chat values a visitor typed
    are on `ThreadItem.visitorProfile`, so both gateway shapes carry them
    too (the losslessness rule): a consumer has no other read source, and
    they are deliberately NOT the contact's own `phone`/`email`."""
    ws = _default_workspace_id(session_factory)
    widget_key, channel_id = _new_webchat_channel(client, name="Visitor Profile Shapes")
    key = _key(client, ws)

    token = _session(client, widget_key).json()["token"]
    _post_message(
        client, widget_key, token, text="hello there",
        preChat={"name": "Ada", "email": "ada@example.com", "phone": "+1 555 000 1111"},
    )

    hdr = {"Authorization": f"Bearer {key}"}
    default = client.get("/api/v1/omnichannel/contacts", headers=hdr).json()
    web_thread = next(t for t in default["data"] if t["channelId"] == channel_id)
    expected = {"name": "Ada", "email": "ada@example.com", "phone": "+1 555 000 1111"}
    assert web_thread["visitorProfile"] == expected
    assert web_thread["email"] is None
    assert web_thread["phone"] is None

    rio = client.get(
        "/api/v1/omnichannel/contacts", headers=hdr, params={"format": "rio"}
    ).json()
    web_rio = next(i for i in rio["items"] if i["channelId"] == channel_id)
    assert web_rio["visitorProfile"] == expected
    assert web_rio["email"] is None
    assert web_rio["phone"] is None


def test_message_item_carries_webchat_channel_type_on_both_shapes(client, session_factory):
    ws = _default_workspace_id(session_factory)
    widget_key, channel_id = _new_webchat_channel(client, name="Message Shapes Chat")
    key = _key(client, ws)

    token = _session(client, widget_key).json()["token"]
    _post_message(client, widget_key, token, text="hello there")

    hdr = {"Authorization": f"Bearer {key}"}
    contact = client.get("/api/v1/omnichannel/contacts", headers=hdr).json()["data"][0]
    cid = contact["id"]

    default = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages", headers=hdr).json()
    assert default["data"][0]["channelType"] == "WEBCHAT"

    rio = client.get(
        f"/api/v1/omnichannel/contacts/{cid}/messages", headers=hdr, params={"format": "rio"}
    ).json()
    assert rio["items"][0]["channelType"] == "WEBCHAT"


def test_a_non_webchat_contact_reads_null_visitor_last_seen_at_on_both_shapes(client, session_factory):
    """Losslessness in the other direction - `visitorLastSeenAt` stays null
    for a channel type that never stamps it."""
    from tests.test_omnichannel_api_gateway import _seed_channel, _seed_open_contact

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone="+60129990001", open_window=True)
    key = _key(client, ws)

    hdr = {"Authorization": f"Bearer {key}"}
    default = client.get("/api/v1/omnichannel/contacts", headers=hdr).json()
    assert default["data"][0]["visitorLastSeenAt"] is None

    rio = client.get(
        "/api/v1/omnichannel/contacts", headers=hdr, params={"format": "rio"}
    ).json()
    assert rio["items"][0]["visitorLastSeenAt"] is None


# ── AC-WEB-60: the guide MUST change in the same commit as the gateway diff ──
def test_consumer_guide_documents_the_webchat_prefix_and_new_fields():
    guide = (
        pathlib.Path(__file__).resolve().parents[2]
        / "documentation"
        / "omnichannel"
        / "consumer-integration-guide.md"
    ).read_text()
    assert "webchat:" in guide
    assert "visitorLastSeenAt" in guide
    assert "WEBCHAT" in guide
    # The explicit "no messaging window at all" statement (AC-WEB-60).
    assert "no messaging window" in guide.lower()
    # Review round 1 (S5) - the `webchat:` row used to point integrators at
    # §12, the AGENT-facing embed, which has a different secret
    # (`embedSecret`), a different HMAC input and a different endpoint.
    # §12a is the visitor widget's own section; the recipe has to be in it,
    # spelled out, because a wrong hash fails SILENTLY by design
    # (AC-WEB-56) and costs real debugging time.
    assert "## 12a." in guide
    assert "widgetSecret" in guide
    assert "HMAC-SHA256(key = widgetSecret, msg = userRef)" in guide
    assert "window.fxChatIdentity" in guide
    assert "fxWebchat.identify(" in guide
    assert "Allowed origins" in guide
    # Review round 1 (B3) - the unverified pre-chat values are on both read
    # shapes, so the guide documents what they are and what they are not.
    assert "visitorProfile" in guide


# ── AC-WEB-61: send_message action has no window refusal on a web chat contact ──
def test_workflow_send_message_action_has_no_window_refusal_on_webchat_contact(
    client, session_factory
):
    from modules.omnichannel.services.workflow_actions import omnichannel_send_message

    widget_key, channel_id = _new_webchat_channel(client, name="Workflow Send Chat")
    token = _session(client, widget_key).json()["token"]
    _post_message(client, widget_key, token, text="hello")

    hdr = _auth(client)
    contact = client.get("/omnichannel/contacts", headers=hdr).json()["data"][0]
    cid = contact["id"]

    db = session_factory()
    out = omnichannel_send_message(
        db, DEFAULT_TENANT_ID,
        {"contactId": cid, "mode": "text", "message": "reaching out"},
        {},
    )
    db.commit()
    db.close()
    assert out["messageId"]
    assert out["status"] in ("QUEUED", "SENT")
