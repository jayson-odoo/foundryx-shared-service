"""Plan 34 (A7b) Slice S3 - outbound to the visitor and realtime.

AC-WEB-36..43 (see documentation/plans/sprint-4/
34-omnichannel-channel-web-chat-acceptance-criteria.md).

Covers: `WebChatAdapter.send` (no network call, immediate SENT), agent media
projected as a signed short-TTL URL bound to the message id, the WS visitor
principal (thread-scoped, fail-closed `visitor_frame` relay, cross-visitor
isolation, staff-PII exclusion), and `last_seen_at`/`visitorLastSeenAt`
presence stamped on session start / message post / WS connect.
"""
import json
import time
from urllib.parse import urlsplit

import fakeredis
import fakeredis.aioredis
import pytest
from starlette.websockets import WebSocketDisconnect

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.routers import ws as ws_module
from modules.omnichannel.schemas import SendMessageRequest
from modules.omnichannel.services import realtime
from tests.test_omnichannel_channels_webchat import _auth, _connect, _other_tenant_auth
from tests.test_omnichannel_webchat_public import (
    ORIGIN,
    _get_messages,
    _new_channel,
    _post_message,
    _session,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128


@pytest.fixture(autouse=True)
def _tmp_media(tmp_path):
    from app.config import settings
    from app.services.storage import set_storage

    prev = settings.media_root
    settings.media_root = str(tmp_path)
    set_storage(None)
    yield
    settings.media_root = prev
    set_storage(None)


@pytest.fixture
def _fake_redis(session_factory):
    server = fakeredis.FakeServer()
    realtime.set_client(fakeredis.FakeRedis(server=server, decode_responses=True))
    ws_module.set_async_redis(
        fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    )
    ws_module.set_session_factory(session_factory)
    yield
    realtime.set_client(None)
    ws_module.set_async_redis(None)
    ws_module.set_session_factory(ws_module.SessionLocal)


def _relativize(url):
    parts = urlsplit(url)
    return parts.path + ("?" + parts.query if parts.query else "")


def _contact_id_for(session_factory, channel_id, visitor_id):
    from modules.omnichannel.models import ContactChannelIdentity

    db = session_factory()
    try:
        identity = (
            db.query(ContactChannelIdentity)
            .filter(
                ContactChannelIdentity.channel_id == channel_id,
                ContactChannelIdentity.external_user_id == f"visitor:{visitor_id}",
            )
            .first()
        )
        return identity.contact_id if identity else None
    finally:
        db.close()


def _identity_for(session_factory, channel_id, visitor_id):
    from modules.omnichannel.models import ContactChannelIdentity

    db = session_factory()
    try:
        return (
            db.query(ContactChannelIdentity)
            .filter(
                ContactChannelIdentity.channel_id == channel_id,
                ContactChannelIdentity.external_user_id == f"visitor:{visitor_id}",
            )
            .first()
        )
    finally:
        db.close()


def _bootstrap_thread(client, session_factory, *, name="S3 Web Chat"):
    """Connect a channel, start a visitor session, and post the visitor's
    first message - the real public flow (D-A7B-7's lazy creation), never a
    direct DB insert. Returns
    (widget_key, channel_id, workspace_id, visitor_id, token, contact_id)."""
    widget_key, channel_id = _new_channel(client, name=name)
    s = _session(client, widget_key)
    assert s.status_code == 200
    body = s.json()
    token, visitor_id, workspace_id = body["token"], body["visitorId"], body["workspaceId"]
    assert workspace_id
    res = _post_message(client, widget_key, token, text="Hello, I need help")
    assert res.status_code == 201
    contact_id = _contact_id_for(session_factory, channel_id, visitor_id)
    assert contact_id is not None
    return widget_key, channel_id, workspace_id, visitor_id, token, contact_id


# ── AC-WEB-36: WebChatAdapter.send - no network call, immediate SENT ────────
def test_agent_reply_reaches_sent_with_no_network_call(client, session_factory):
    _wk, _cid, _ws, _vid, _tok, contact_id = _bootstrap_thread(client, session_factory)
    h = _auth(client)
    res = client.post(
        f"/omnichannel/contacts/{contact_id}/messages", headers=h, json={"body": "Hi there!"}
    )
    assert res.status_code == 201
    item = res.json()
    assert item["deliveryStatus"] == "SENT"
    assert item["externalMessageId"].startswith("web:out:")


def test_visitor_reads_agent_reply_through_history_projection(client, session_factory):
    """The poll-fallback endpoint (S2/D-A7B-16) shows the SENT reply with
    only the channel's configured display name - never a real agent name."""
    widget_key, _cid, _ws, _vid, token, contact_id = _bootstrap_thread(client, session_factory)
    h = _auth(client)
    client.post(f"/omnichannel/contacts/{contact_id}/messages", headers=h, json={"body": "Reply!"})

    res = _get_messages(client, widget_key, token)
    assert res.status_code == 200
    items = res.json()["data"]
    reply = [m for m in items if m["direction"] == "out"][0]
    assert reply["text"] == "Reply!"
    assert reply["agentName"] == "Support"
    assert reply["status"] == "sent"
    assert set(reply.keys()) == {
        "id", "direction", "text", "media", "quickReplies", "agentName", "createdAt", "status",
    }


# ── AC-WEB-41: agent media -> a signed, short-TTL URL bound to the message id
def test_agent_media_send_projects_signed_url_for_visitor(client, session_factory):
    widget_key, _cid, _ws, _vid, token, contact_id = _bootstrap_thread(
        client, session_factory, name="S3 Media Chat"
    )
    h = _auth(client)
    res = client.post(
        f"/omnichannel/contacts/{contact_id}/media",
        headers=h,
        data={"kind": "image"},
        files={"file": ("a.png", PNG, "image/png")},
    )
    assert res.status_code == 201

    got = _get_messages(client, widget_key, token)
    reply = [m for m in got.json()["data"] if m["direction"] == "out"][0]
    assert reply["media"] is not None
    url = reply["media"]["url"]
    assert "exp=" in url and "sig=" in url
    assert reply["media"]["mimeType"] == "image/png"

    # The signature IS the authorization - no header needed.
    rel = _relativize(url)
    fetched = client.get(rel)
    assert fetched.status_code == 200
    assert fetched.content == PNG

    # Tampered signature -> refused by the EXISTING media route (unchanged).
    bad = client.get(rel.replace("sig=", "sig=x"))
    assert bad.status_code == 401


def test_foreign_visitor_never_sees_another_contacts_media_message(client, session_factory):
    """AC-WEB-41 - "a visitor token for a different contact cannot obtain
    such a URL": the media message never appears in a foreign visitor's own
    history at all (the existing per-contact scoping this slice reuses), so
    there is no URL to obtain in the first place."""
    widget_key, channel_id = _new_channel(client, name="S3 Media Isolation")
    s_a = _session(client, widget_key)
    body_a = s_a.json()
    _post_message(client, widget_key, body_a["token"], text="I am A")
    contact_a = _contact_id_for(session_factory, channel_id, body_a["visitorId"])

    s_b = _session(client, widget_key)
    body_b = s_b.json()
    _post_message(client, widget_key, body_b["token"], text="I am B")

    h = _auth(client)
    res = client.post(
        f"/omnichannel/contacts/{contact_a}/media",
        headers=h,
        data={"kind": "image"},
        files={"file": ("a.png", PNG, "image/png")},
    )
    assert res.status_code == 201

    got_b = _get_messages(client, widget_key, body_b["token"])
    assert all(m["direction"] == "in" for m in got_b.json()["data"])
    assert "exp=" not in got_b.text and "sig=" not in got_b.text


def test_visitor_never_authors_media_so_own_messages_carry_none(client, session_factory):
    widget_key, _cid, _ws, _vid, token, _contact_id = _bootstrap_thread(client, session_factory)
    res = _get_messages(client, widget_key, token)
    inbound = [m for m in res.json()["data"] if m["direction"] == "in"][0]
    assert inbound["media"] is None


# ── AC-WEB-38/39: the WS visitor principal ──────────────────────────────────
def test_ws_visitor_receives_agent_reply_frame_and_nothing_else(client, session_factory, _fake_redis):
    _wk, _cid, workspace_id, _vid, token, contact_id = _bootstrap_thread(client, session_factory)
    h = _auth(client)
    with client.websocket_connect(
        f"/omnichannel/ws?workspaceId={workspace_id}&token={token}"
    ) as sock:
        client.post(
            f"/omnichannel/contacts/{contact_id}/messages", headers=h, json={"body": "Live reply"}
        )
        frame = json.loads(sock.receive_text())
        assert frame["type"] == "message.created"
        msg = frame["message"]
        assert msg["direction"] == "out"
        assert msg["text"] == "Live reply"
        assert msg["agentName"] == "Support"
        # Fail-closed allowlist (D-A7B-17/R2) - exactly these keys, never a
        # real user name/email/assignee/tag/lifecycle/close reason.
        assert set(msg.keys()) == {
            "id", "direction", "text", "media", "quickReplies", "agentName", "createdAt", "status",
        }


def test_ws_visitor_wrong_channel_token_is_rejected(client, session_factory, _fake_redis):
    """A token minted for a DIFFERENT tenant's channel/workspace cannot open
    a socket scoped to this tenant's workspace (AC-WEB-27/R4 - one
    indistinguishable rejection, never a hint about which check failed)."""
    _wk_a, _cid_a, workspace_a, _vid_a, _tok_a, _c_a = _bootstrap_thread(
        client, session_factory, name="S3 Chan A"
    )
    h_other = _other_tenant_auth(client, session_factory)
    other_body = _connect(client, h_other, name="S3 Chan B", allowed_origins=[ORIGIN]).json()
    s_b = _session(client, other_body["widgetKey"])
    tok_b = s_b.json()["token"]
    workspace_b = s_b.json()["workspaceId"]
    assert workspace_b != workspace_a

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            f"/omnichannel/ws?workspaceId={workspace_a}&token={tok_b}"
        ):
            pass
    assert exc.value.code == 4403


def test_ws_visitor_epoch_revoked_token_is_rejected(client, session_factory, _fake_redis):
    widget_key, channel_id, workspace_id, _vid, token, _cid = _bootstrap_thread(client, session_factory)
    h = _auth(client)
    res = client.post(f"/omnichannel/channels/{channel_id}/widget/sign-out-visitors", headers=h)
    assert res.status_code == 200
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            f"/omnichannel/ws?workspaceId={workspace_id}&token={token}"
        ):
            pass
    assert exc.value.code == 4403


def test_ws_visitor_without_a_thread_yet_is_refused(client, session_factory, _fake_redis):
    """D-A7B-7's lazy creation means a visitor who only ever started a
    session (never posted a message) has no identity/contact - the socket
    refuses rather than falling back to whole-workspace visibility (R1); the
    poll fallback covers this gap until the panel reconnects after the first
    POST (S4)."""
    widget_key, _channel_id = _new_channel(client, name="S3 No Thread Yet")
    s = _session(client, widget_key)
    body = s.json()
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            f"/omnichannel/ws?workspaceId={body['workspaceId']}&token={body['token']}"
        ):
            pass
    assert exc.value.code == 4403


def test_ws_two_visitors_isolated_from_each_other(client, session_factory, _fake_redis):
    """AC-WEB-39 - a message from visitor B never reaches visitor A's socket,
    and an internal note on visitor A's OWN thread never reaches it either
    (the frame passes the contact-scope pre-filter but `visitor_frame` drops
    a SYSTEM sender - R2's second layer)."""
    widget_key, channel_id = _new_channel(client, name="S3 Shared Channel")
    s_a = _session(client, widget_key)
    body_a = s_a.json()
    _post_message(client, widget_key, body_a["token"], text="I am visitor A")
    contact_a = _contact_id_for(session_factory, channel_id, body_a["visitorId"])

    s_b = _session(client, widget_key)
    body_b = s_b.json()
    _post_message(client, widget_key, body_b["token"], text="I am visitor B")

    h = _auth(client)
    with client.websocket_connect(
        f"/omnichannel/ws?workspaceId={body_a['workspaceId']}&token={body_a['token']}"
    ) as sock_a:
        # Visitor B sends another message on their OWN thread - A must not see it.
        _post_message(client, widget_key, body_b["token"], text="Second from B")
        # An internal note on A's own thread - A must not see it either.
        client.post(f"/omnichannel/contacts/{contact_a}/notes", headers=h, json={"body": "internal only"})
        # A message the AGENT sends to A's own thread - A MUST see this one.
        client.post(
            f"/omnichannel/contacts/{contact_a}/messages", headers=h, json={"body": "Reply to A"}
        )
        frame = json.loads(sock_a.receive_text())
        assert frame["message"]["text"] == "Reply to A"


# ── Review round 1, B2: the relay is CHANNEL-scoped, not only contact-scoped ─
def _wa_inbound_payload(
    *, pnid="pn-b2-relay", wa_from="60123456789", wamid="wamid.b2.inbound",
    body="my WhatsApp message",
):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": pnid},
                            "contacts": [{"wa_id": wa_from, "profile": {"name": "WA User"}}],
                            "messages": [
                                {"id": wamid, "from": wa_from, "type": "text",
                                 "text": {"body": body}}
                            ],
                        },
                    }
                ]
            }
        ]
    }


def _add_whatsapp_identity(session_factory, contact_id, *, external_user_id, phone):
    """Give an EXISTING web chat contact a second identity, on a WhatsApp
    channel in the same workspace - the ordinary end state of "a visitor
    chatted on the website, then messaged the same business on WhatsApp"
    (`InboundService._resolve_contact` stitches onto the SAME contact)."""
    from modules.omnichannel.models import Channel, Contact, ContactChannelIdentity, Workspace
    from modules.omnichannel.phone import digits_only
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    db = session_factory()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        ws = db.query(Workspace).filter(Workspace.id == contact.workspace_id).first()
        wa = Channel(
            tenant_id=contact.tenant_id, workspace_id=ws.id, channel_type="WHATSAPP",
            name="B2 WhatsApp", credentials_json=encrypt_credentials({"dev": True}),
            phone_number_id="pn-b2-relay", is_active=True,
            status_id=statuses.status_id_for(db, contact.tenant_id, "CHANNEL", "ACTIVE"),
        )
        db.add(wa)
        db.flush()
        db.add(
            ContactChannelIdentity(
                tenant_id=contact.tenant_id, contact_id=contact.id, channel_id=wa.id,
                external_user_id=external_user_id,
            )
        )
        contact.phone = phone
        contact.phone_digits = digits_only(phone)
        db.commit()
        return wa.id
    finally:
        db.close()


def test_ws_visitor_never_receives_frames_from_another_channel_on_the_same_contact(
    client, session_factory, _fake_redis
):
    """The realtime room is per WORKSPACE and the pre-filter is per CONTACT,
    so before this fix every WhatsApp inbound and every agent WhatsApp reply
    on a stitched contact - INCLUDING agent media, for which the projection
    mints a signed URL the visitor's browser can fetch - was pushed live to a
    still-open web chat panel on a public website. It also made the socket
    deliver strictly MORE than the poll, which AC-WEB-40 says it must not."""
    from modules.omnichannel.services.inbound_service import InboundService
    from modules.omnichannel.services.message_service import MessageService

    widget_key, _cid, workspace_id, _vid, token, contact_id = _bootstrap_thread(
        client, session_factory, name="B2 Cross Channel"
    )
    wa_channel_id = _add_whatsapp_identity(
        session_factory, contact_id, external_user_id="60123456789", phone="+60123456789"
    )
    h = _auth(client)

    with client.websocket_connect(
        f"/omnichannel/ws?workspaceId={workspace_id}&token={token}"
    ) as sock:
        db = session_factory()
        try:
            # 1. A WhatsApp INBOUND on the stitched contact - the real Meta
            #    envelope through the UNCHANGED `InboundService` (which keys
            #    on `phone_number_id`, not the channel id).
            InboundService(db).process_payload("pn-b2-relay", _wa_inbound_payload())
            # 2. An agent's WhatsApp TEXT reply on the same contact.
            MessageService(db).send_message(
                contact_id,
                DEFAULT_TENANT_ID,
                None,
                SendMessageRequest(messageType="TEXT", body="whatsapp only reply"),
                channel_id_override=wa_channel_id,
                actor_is_human=True,
            )
            # 3. An agent's WhatsApp MEDIA reply - the signed-URL case.
            MessageService(db).send_media(
                contact_id,
                DEFAULT_TENANT_ID,
                "u-agent",
                kind="IMAGE",
                content=PNG,
                filename="wa.png",
                caption=None,
                channel_id_override=wa_channel_id,
                actor_is_human=True,
            )
        finally:
            db.close()

        # 4. The web chat reply - the ONLY frame this socket may ever see.
        client.post(
            f"/omnichannel/contacts/{contact_id}/messages",
            headers=h,
            json={"body": "web chat reply"},
        )
        frame = json.loads(sock.receive_text())
        assert frame["message"]["text"] == "web chat reply"

    # ... and the poll agrees exactly (AC-WEB-40): the WhatsApp rows are not
    # in the visitor's history either.
    history = _get_messages(client, widget_key, token).json()["data"]
    assert "whatsapp only reply" not in json.dumps(history)
    assert "my WhatsApp message" not in json.dumps(history)


# ── Review round 1, S4: an epoch bump closes an ALREADY-OPEN socket ─────────
def test_ws_visitor_socket_closes_when_the_epoch_is_bumped_while_open(
    client, session_factory, _fake_redis
):
    """AC-WEB-28 amended: "sign out all visitors" reads to an admin as
    immediate. Before this fix the visitor principal was resolved once at the
    handshake and never re-checked, so an already-open panel kept receiving
    agent replies until the visitor happened to close the tab."""
    _wk, channel_id, workspace_id, _vid, token, _contact_id = _bootstrap_thread(
        client, session_factory, name="S4 Revoke Live"
    )
    h = _auth(client)
    ws_module.set_visitor_reverify_seconds(0.05)
    try:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(
                f"/omnichannel/ws?workspaceId={workspace_id}&token={token}"
            ) as sock:
                res = client.post(
                    f"/omnichannel/channels/{channel_id}/widget/sign-out-visitors", headers=h
                )
                assert res.status_code == 200
                sock.receive_text()  # blocks until the revalidator closes it
    finally:
        ws_module.set_visitor_reverify_seconds(60.0)
    assert exc.value.code == 4403


def test_ws_staff_socket_is_not_revalidated_on_a_timer(client, session_factory, _fake_redis):
    """Only the VISITOR branch re-verifies (S4) - the staff/embed principals
    keep their existing behaviour, which this slice is not the place to
    change. Pinned so a later reader does not "generalize" it by accident."""
    _wk, _cid, workspace_id, _vid, _token, contact_id = _bootstrap_thread(
        client, session_factory, name="S4 Staff Untouched"
    )
    h = _auth(client)
    staff_token = h["Authorization"].split(" ", 1)[1]
    ws_module.set_visitor_reverify_seconds(0.05)
    try:
        with client.websocket_connect(
            f"/omnichannel/ws?workspaceId={workspace_id}&token={staff_token}"
        ) as sock:
            client.post(
                f"/omnichannel/contacts/{contact_id}/messages",
                headers=h,
                json={"body": "still connected"},
            )
            frame = json.loads(sock.receive_text())
            assert frame["type"] == "message.created"
    finally:
        ws_module.set_visitor_reverify_seconds(60.0)


# ── Review round 2, N-new-1: revalidation must NOT stamp presence ───────────
def test_ws_visitor_revalidation_ticks_do_not_advance_last_seen_at(
    client, session_factory, _fake_redis
):
    """The periodic background re-verification is a TIMER firing, not a real
    person being present - it must not refresh `last_seen_at` (the marker
    would otherwise read "Online now" forever for a visitor who opened the
    panel and walked away). The connect-time authorization still stamps (a
    real client action); only the RECURRING revalidation ticks after it must
    not."""
    _wk, channel_id, workspace_id, visitor_id, token, _contact_id = _bootstrap_thread(
        client, session_factory, name="N-new-1 Presence"
    )

    ws_module.set_visitor_reverify_seconds(0.05)
    try:
        with client.websocket_connect(
            f"/omnichannel/ws?workspaceId={workspace_id}&token={token}"
        ):
            time.sleep(0.1)  # let the connect-time stamp land
            after_connect = _identity_for(session_factory, channel_id, visitor_id).last_seen_at
            assert after_connect is not None

            time.sleep(0.5)  # several revalidation ticks at ~0.05s (+/-20% jitter)
            after_ticks = _identity_for(session_factory, channel_id, visitor_id).last_seen_at
    finally:
        ws_module.set_visitor_reverify_seconds(60.0)

    assert after_ticks == after_connect


# ── AC-WEB-42: last_seen_at / visitorLastSeenAt presence ────────────────────
def test_last_seen_stamped_on_session_start_message_post_and_ws_connect(
    client, session_factory, _fake_redis
):
    widget_key, channel_id = _new_channel(client, name="S3 Presence")
    s = _session(client, widget_key)
    body = s.json()
    # No identity yet (D-A7B-7) - nothing to stamp, not an error.
    assert _identity_for(session_factory, channel_id, body["visitorId"]) is None

    _post_message(client, widget_key, body["token"], text="hello")
    after_post = _identity_for(session_factory, channel_id, body["visitorId"])
    assert after_post is not None
    assert after_post.last_seen_at is not None
    stamped_after_post = after_post.last_seen_at

    with client.websocket_connect(
        f"/omnichannel/ws?workspaceId={body['workspaceId']}&token={body['token']}"
    ):
        pass
    after_ws = _identity_for(session_factory, channel_id, body["visitorId"])
    assert after_ws.last_seen_at >= stamped_after_post


def test_visitor_last_seen_at_on_the_wire_thread_item(client, session_factory):
    _wk, _cid, _ws, _vid, _tok, contact_id = _bootstrap_thread(client, session_factory)
    h = _auth(client)
    res = client.get(f"/omnichannel/contacts/{contact_id}", headers=h)
    assert res.status_code == 200
    assert res.json()["visitorLastSeenAt"] is not None
