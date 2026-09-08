"""Plan 34 (A7b) Slice S2 - the public web chat visitor API.

AC-WEB-23..35 (see documentation/plans/sprint-4/
34-omnichannel-channel-web-chat-acceptance-criteria.md).
"""
import json
from types import SimpleNamespace

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from app.services.throttle import ThrottleService, Throttled
from tests.test_omnichannel_channels_webchat import _auth, _connect, _other_tenant_auth

ORIGIN = "https://shop.acme.com"
SESSION_URL = "/public/omnichannel/webchat/{key}/session"
MESSAGES_URL = "/public/omnichannel/webchat/{key}/messages"


def _session(client, widget_key, *, origin=ORIGIN, token=None, identity=None):
    body = {}
    if token:
        body["token"] = token
    if identity is not None:
        body["identity"] = identity
    return client.post(
        SESSION_URL.format(key=widget_key),
        json=body,
        headers=({"Origin": origin} if origin else {}),
    )


def _post_message(client, widget_key, token, *, text="Hello there", origin=ORIGIN, **extra):
    body = {"text": text, **extra}
    headers = {"Authorization": f"Bearer {token}"}
    if origin:
        headers["Origin"] = origin
    return client.post(MESSAGES_URL.format(key=widget_key), json=body, headers=headers)


def _get_messages(client, widget_key, token, *, params=None, origin=ORIGIN):
    headers = {"Authorization": f"Bearer {token}"}
    if origin:
        headers["Origin"] = origin
    return client.get(MESSAGES_URL.format(key=widget_key), headers=headers, params=params or {})


def _new_channel(client, *, name="Public S2 Chat", allowed_origins=None):
    h = _auth(client)
    body = _connect(
        client, h, name=name, allowed_origins=allowed_origins or [ORIGIN]
    ).json()
    return body["widgetKey"], body["id"]


# ── AC-WEB-23/24: session + origin enforcement ───────────────────────────────
def test_session_with_allowed_origin_returns_token_and_config(client):
    widget_key, _ = _new_channel(client)
    res = _session(client, widget_key)
    assert res.status_code == 200
    body = res.json()
    assert body["token"]
    assert body["visitorId"]
    assert body["expiresAt"]
    assert body["online"] is True
    assert body["messages"] == []
    cfg = body["config"]
    assert cfg["agentDisplayName"] == "Support"
    assert cfg["greeting"]
    assert cfg["preChat"] == {"askName": True, "askEmail": True, "askPhone": False}
    assert res.headers.get("access-control-allow-origin") == ORIGIN
    assert res.headers.get("vary") == "Origin"
    assert "access-control-allow-credentials" not in res.headers
    assert "set-cookie" not in res.headers


def test_session_disallowed_origin_is_uniform_404(client):
    widget_key, _ = _new_channel(client)
    res = _session(client, widget_key, origin="https://evil.example")
    assert res.status_code == 404
    assert res.json() == {"detail": "Not found."}


def test_session_missing_origin_is_uniform_404(client):
    widget_key, _ = _new_channel(client)
    res = _session(client, widget_key, origin=None)
    assert res.status_code == 404
    assert res.json() == {"detail": "Not found."}


def test_session_unknown_widget_key_is_uniform_404(client):
    res = _session(client, "wk_does_not_exist_at_all_0000000")
    assert res.status_code == 404
    assert res.json() == {"detail": "Not found."}


def test_session_uniform_404_matrix_byte_identical(client, session_factory):
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    unknown = _session(client, "wk_totally_unknown_0000000000000")

    trashed_key, trashed_id = _new_channel(client, name="Trashed")
    h = _auth(client)
    client.post("/omnichannel/channels/disconnect", headers=h, json={"ids": [trashed_id]})
    trashed = _session(client, trashed_key)

    inactive_key, inactive_id = _new_channel(client, name="Inactive")
    client.patch(f"/omnichannel/channels/{inactive_id}", headers=h, json={"isActive": False})
    inactive = _session(client, inactive_key)

    bad_origin_key, _ = _new_channel(client, name="BadOrigin")
    bad_origin = _session(client, bad_origin_key, origin="https://not-listed.example")

    module_off_key, _ = _new_channel(client, name="ModuleOff")
    db = session_factory()
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
    db.commit()
    db.close()
    try:
        module_off = _session(client, module_off_key)
    finally:
        db2 = session_factory()
        AppStoreService(db2).reactivate(DEFAULT_TENANT_ID, "omnichannel")
        db2.commit()
        db2.close()

    responses = [unknown, trashed, inactive, bad_origin, module_off]
    for res in responses:
        assert res.status_code == 404
        assert res.json() == {"detail": "Not found."}


# ── AC-WEB-25: zero rows at session start ────────────────────────────────────
def test_session_creates_zero_contact_and_identity_rows(client, session_factory):
    from modules.omnichannel.models import Contact, ContactChannelIdentity

    widget_key, _ = _new_channel(client)
    for _ in range(20):
        assert _session(client, widget_key).status_code == 200

    db = session_factory()
    assert db.query(Contact).count() == 0
    assert db.query(ContactChannelIdentity).count() == 0
    db.close()


# ── AC-WEB-26: lazy contact creation on the first message ───────────────────
def test_first_message_creates_contact_and_identity_and_publishes(client, session_factory, monkeypatch):
    from modules.omnichannel.models import Contact, ContactChannelIdentity
    from modules.omnichannel.services import realtime

    published = []
    monkeypatch.setattr(realtime, "publish", lambda *a, **kw: published.append((a, kw)))

    widget_key, channel_id = _new_channel(client)
    token = _session(client, widget_key).json()["token"]

    res = _post_message(client, widget_key, token, text="Hi, I need help")
    assert res.status_code == 201
    body = res.json()
    assert body["direction"] == "in"
    assert body["text"] == "Hi, I need help"
    assert body["agentName"] is None
    assert body["createdAt"]
    assert res.headers.get("access-control-allow-origin") == ORIGIN
    assert "set-cookie" not in res.headers

    db = session_factory()
    assert db.query(Contact).count() == 1
    identities = db.query(ContactChannelIdentity).all()
    assert len(identities) == 1
    identity = identities[0]
    assert identity.channel_id == channel_id
    assert identity.external_user_id.startswith("visitor:")
    db.close()
    assert published  # realtime.publish was called on the inbound path


def test_second_message_reuses_the_same_contact(client, session_factory):
    from modules.omnichannel.models import Contact

    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    _post_message(client, widget_key, token, text="first")
    _post_message(client, widget_key, token, text="second")

    db = session_factory()
    assert db.query(Contact).count() == 1
    db.close()


def test_pre_chat_email_matching_existing_contact_never_stitches(client, session_factory):
    """D-A7B-8/R3 seam - S2 ignores `preChat` entirely (S5 wires write-if-
    empty), so an attacker-supplied email matching an existing contact's
    email can never merge onto it: a brand new contact is always created,
    and the visitor's own history stays empty of that other contact's
    messages."""
    from modules.omnichannel.models import Contact

    h = _auth(client)
    ws = client.get("/omnichannel/workspaces", headers=h).json()["data"]
    ws_id = next(w["id"] for w in ws if w["isDefault"])

    db0 = session_factory()
    existing = Contact(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=ws_id,
        first_name="Existing",
        email="known@example.com",
        priority="MEDIUM",
    )
    db0.add(existing)
    db0.commit()
    before_count = db0.query(Contact).count()
    db0.close()

    widget_key, _ = _new_channel(client, name="NoStitch")
    token = _session(client, widget_key).json()["token"]
    res = _post_message(
        client, widget_key, token, text="hi", preChat={"email": "known@example.com"}
    )
    assert res.status_code == 201

    db = session_factory()
    after_count = db.query(Contact).count()
    db.close()
    assert after_count == before_count + 1  # a NEW contact, never a merge


# ── AC-WEB-27/28: token verification, epoch, cross-channel isolation ────────
def test_message_post_requires_bearer_token_401(client):
    widget_key, _ = _new_channel(client)
    res = client.post(
        MESSAGES_URL.format(key=widget_key), json={"text": "hi"}, headers={"Origin": ORIGIN}
    )
    assert res.status_code == 401


def test_tampered_token_signature_is_401(client):
    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    res = _post_message(client, widget_key, tampered, text="hi")
    assert res.status_code == 401


def test_expired_token_is_401(client):
    from modules.omnichannel.webchat_auth import WEBCHAT_TOKEN_TYP
    from app.security import create_access_token

    widget_key, channel_id = _new_channel(client)
    assert _session(client, widget_key).status_code == 200

    # Mint an ALREADY-expired token directly (bypassing the 30 day TTL) for
    # the SAME channel/visitor shape.
    claims = {
        "sub": "vis_expired",
        "typ": WEBCHAT_TOKEN_TYP,
        "tenantId": DEFAULT_TENANT_ID,
        "channelId": channel_id,
        "visitorId": "vis_expired",
        "contactId": None,
        "epoch": 0,
    }
    expired_token = create_access_token(claims, expires_minutes=-1)
    res = _post_message(client, widget_key, expired_token, text="hi")
    assert res.status_code == 401


def test_wrong_typ_token_is_401(client):
    from app.security import create_access_token

    widget_key, channel_id = _new_channel(client)
    not_webchat = create_access_token(
        {
            "sub": "u1",
            "typ": "access",
            "tenantId": DEFAULT_TENANT_ID,
            "channelId": channel_id,
            "visitorId": "vis_x",
            "contactId": None,
            "epoch": 0,
        }
    )
    res = _post_message(client, widget_key, not_webchat, text="hi")
    assert res.status_code == 401


def test_token_minted_for_channel_a_refused_on_channel_b(client):
    key_a, _ = _new_channel(client, name="Channel A")
    key_b, _ = _new_channel(client, name="Channel B")
    token_a = _session(client, key_a).json()["token"]

    res = _post_message(client, key_b, token_a, text="cross-channel")
    assert res.status_code == 401


def test_token_minted_for_one_tenant_refused_on_another_tenants_channel(client, session_factory):
    """Cross-TENANT isolation, not merely cross-channel within one tenant -
    a token minted against the DEFAULT tenant's channel must be refused on a
    channel that lives in a COMPLETELY DIFFERENT tenant, even though widget
    keys are globally unique and the origin allowlist happens to match."""
    key_default, _ = _new_channel(client, name="Default Tenant Chat")
    token_default = _session(client, key_default).json()["token"]

    other_h = _other_tenant_auth(client, session_factory)
    other_body = _connect(
        client, other_h, name="Other Tenant Chat", allowed_origins=[ORIGIN]
    ).json()
    key_other = other_body["widgetKey"]

    res = _post_message(client, key_other, token_default, text="cross-tenant")
    assert res.status_code == 401


def test_sign_out_visitors_revokes_previous_tokens_fresh_session_succeeds(client):
    h = _auth(client)
    widget_key, channel_id = _new_channel(client)
    old_token = _session(client, widget_key).json()["token"]

    signed_out = client.post(
        f"/omnichannel/channels/{channel_id}/widget/sign-out-visitors", headers=h
    )
    assert signed_out.status_code == 200

    refused = _post_message(client, widget_key, old_token, text="still here?")
    assert refused.status_code == 401

    # A fresh session start with the OLD (now-invalid) token immediately
    # succeeds rather than 401ing the visitor out of their own widget.
    fresh = _session(client, widget_key, token=old_token)
    assert fresh.status_code == 200
    assert fresh.json()["token"] != old_token


# ── AC-WEB-29: sliding renewal ────────────────────────────────────────────────
def test_token_far_from_expiry_returned_unchanged_on_session_resume(client):
    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    resumed = _session(client, widget_key, token=token)
    assert resumed.status_code == 200
    assert resumed.json()["token"] == token  # unchanged - far from expiry


# ── AC-WEB-30: throttle (own bucket, two namespaces, before DB work) ─────────
def test_session_throttled_per_ip_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(settings, "throttle_webchat_max_fails", 2)
    widget_key, _ = _new_channel(client)
    assert _session(client, widget_key).status_code == 200
    assert _session(client, widget_key).status_code == 200
    res = _session(client, widget_key)
    assert res.status_code == 429
    assert res.headers.get("Retry-After")


def test_throttle_ip_and_visitor_namespaces_are_independent(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "throttle_webchat_max_fails", 2)
    monkeypatch.setattr(settings, "throttle_webchat_window_minutes", 5)
    db = session_factory()
    throttle = ThrottleService(db)

    throttle.record_webchat(visitor_id="visitor-a")
    throttle.record_webchat(visitor_id="visitor-a")
    try:
        throttle.enforce_webchat(visitor_id="visitor-a")
        assert False, "expected Throttled"
    except Throttled:
        pass

    # A DIFFERENT visitor id is unaffected by visitor-a's counter.
    throttle.enforce_webchat(visitor_id="visitor-b")
    # The IP namespace is a completely separate counter.
    throttle.enforce_webchat(ip="203.0.113.5")
    db.close()


# ── AC-WEB-31/33: size cap, text cap, no media/multipart ─────────────────────
def test_text_too_long_is_422_and_stores_nothing(client, session_factory):
    from modules.omnichannel.models import ConversationMessage

    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    res = _post_message(client, widget_key, token, text="x" * 4097)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "text_too_long"

    db = session_factory()
    assert db.query(ConversationMessage).count() == 0
    db.close()


def test_oversized_body_refused_422_and_stores_nothing(client, session_factory):
    from modules.omnichannel.models import ConversationMessage

    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    huge = json.dumps({"text": "y" * 40000}).encode("utf-8")
    res = client.post(
        MESSAGES_URL.format(key=widget_key),
        content=huge,
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": ORIGIN,
            "Content-Type": "application/json",
        },
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "body_too_large"

    db = session_factory()
    assert db.query(ConversationMessage).count() == 0
    db.close()


def test_media_reference_refused_422(client):
    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    res = _post_message(client, widget_key, token, text="hi", media={"url": "http://x"})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "unsupported_content"


def test_multipart_request_refused(client):
    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    res = client.post(
        MESSAGES_URL.format(key=widget_key),
        headers={"Authorization": f"Bearer {token}", "Origin": ORIGIN},
        files={"file": ("x.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "unsupported_content"


# ── AC-WEB-32: honeypot ───────────────────────────────────────────────────────
def test_honeypot_hit_is_indistinguishable_from_a_real_send_and_stores_nothing(
    client, session_factory
):
    """Review round 1 (S2): a honeypot hit used to answer `200 {"ok": true}`
    while a real send answered `201` with the full `VisitorMessage` - one
    request told a bot which field was the trap, after which it simply stops
    filling it. The two responses now agree on status code and key set; only
    the id differs (as two real sends would)."""
    from modules.omnichannel.models import Contact, ConversationMessage

    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    trapped = _post_message(client, widget_key, token, text="buy now", hp="i-am-a-bot")
    assert trapped.status_code == 201
    body = trapped.json()
    assert body["direction"] == "in"
    assert body["text"] == "buy now"
    assert body["status"] is None
    assert body["id"]

    db = session_factory()
    assert db.query(Contact).count() == 0
    assert db.query(ConversationMessage).count() == 0
    db.close()

    # A REAL send by the same visitor - same status, same key set.
    real = _post_message(client, widget_key, token, text="buy now")
    assert real.status_code == trapped.status_code
    assert set(real.json().keys()) == set(body.keys())
    assert real.json()["id"] != body["id"]


def test_honeypot_hit_with_invalid_text_fails_exactly_like_a_real_send(client):
    """Validation runs BEFORE the honeypot check, so a bot cannot detect the
    trap by comparing error behaviour either."""
    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    trapped = _post_message(client, widget_key, token, text="x" * 5000, hp="bot")
    real = _post_message(client, widget_key, token, text="x" * 5000)
    assert trapped.status_code == real.status_code == 422
    assert trapped.json() == real.json()


# ── Review round 1, S1: non-string scalars are typed 422s / uniform 404s ─────
def test_session_with_a_non_string_token_is_the_uniform_404(client):
    """`{"token": 123}` used to reach `decode_access_token(123)` ->
    `AttributeError` -> 500 on an unauthenticated surface whose whole
    contract is a uniform 404/401/422."""
    widget_key, _ = _new_channel(client)
    res = client.post(
        SESSION_URL.format(key=widget_key), json={"token": 123}, headers={"Origin": ORIGIN}
    )
    assert res.status_code == 404
    assert res.json() == {"detail": "Not found."}
    for bad in ({"token": {"a": 1}}, {"token": []}, {"token": True}):
        other = client.post(
            SESSION_URL.format(key=widget_key), json=bad, headers={"Origin": ORIGIN}
        )
        assert other.status_code == 404, bad
        assert other.json() == res.json()


def test_session_with_a_malformed_identity_still_proceeds_anonymously(client):
    """AC-WEB-56 is explicit that a missing/malformed/non-verifying host
    identity assertion is SILENTLY ignored - so `identity` stays permissive
    at the envelope (S1 hardens `token`, which is the one that could reach
    `decode_access_token` and 500)."""
    widget_key, _ = _new_channel(client)
    for bad in (5, "not-an-object", [1, 2], {"userRef": 1}, {"userRef": "u", "hash": 9}):
        res = client.post(
            SESSION_URL.format(key=widget_key),
            json={"identity": bad},
            headers={"Origin": ORIGIN},
        )
        assert res.status_code == 200, bad
        assert res.json()["visitorId"].startswith("vis_")


def test_post_message_with_non_string_scalars_is_a_typed_422(client):
    """`{"hp": 1}` used to reach `(1 or "").strip()` -> `AttributeError` ->
    500. Every scalar is now type-checked in the router."""
    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    for bad in ({"text": "hi", "hp": 1}, {"text": []}, {"text": 5}, {"hp": "x"}):
        res = client.post(
            MESSAGES_URL.format(key=widget_key),
            json=bad,
            headers={"Authorization": f"Bearer {token}", "Origin": ORIGIN},
        )
        assert res.status_code == 422, bad
        assert res.json()["error"]["code"] == "invalid_request"
        assert res.json()["error"]["details"]["fieldErrors"]


def test_pre_chat_non_string_values_are_dropped_not_rejected(client):
    """AC-WEB-54 is explicit that a bad pre-chat value is silently dropped -
    the visitor cannot see or fix that field any more - so the envelope type
    stays permissive and `_clean_pre_chat_value` does the checking."""
    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    res = _post_message(
        client, widget_key, token, text="hi", preChat={"name": 5, "email": None, "phone": []}
    )
    assert res.status_code == 201


# ── Review round 1, B1: an in-flight status never 500s the visitor read ─────
def test_in_flight_delivery_status_still_returns_200_on_the_visitor_read(
    client, session_factory
):
    """Production-only before the fix: `_enqueue_and_finalize` commits an
    agent reply at `QUEUED` and hands the send to Celery; every test runs
    eager so the row was `SENT` before any assertion. A poll landing in that
    window raised a `ValidationError` inside the route and 500'd - taking the
    whole transcript, not just the one row."""
    from modules.omnichannel.models import ConversationMessage

    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    assert _post_message(client, widget_key, token, text="hello").status_code == 201

    for raw in ("QUEUED", "SENDING"):
        db = session_factory()
        row = db.query(ConversationMessage).first()
        row.delivery_status = raw
        db.commit()
        db.close()

        res = _get_messages(client, widget_key, token)
        assert res.status_code == 200, raw
        assert res.json()["data"][0]["status"] is None


# ── AC-WEB-34: GET history, own thread only, oldest to newest, page-capped ──
def test_get_messages_own_thread_oldest_to_newest_page_capped(client):
    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    for i in range(3):
        assert _post_message(client, widget_key, token, text=f"msg-{i}").status_code == 201

    page1 = _get_messages(client, widget_key, token, params={"limit": 2})
    assert page1.status_code == 200
    body1 = page1.json()
    assert [m["text"] for m in body1["data"]] == ["msg-0", "msg-1"]
    assert body1["nextAfter"]

    page2 = _get_messages(client, widget_key, token, params={"after": body1["nextAfter"]})
    body2 = page2.json()
    assert [m["text"] for m in body2["data"]] == ["msg-2"]
    assert body2["nextAfter"] is None


def test_get_messages_cross_visitor_isolation(client):
    widget_key, _ = _new_channel(client)
    token_a = _session(client, widget_key).json()["token"]
    token_b = _session(client, widget_key).json()["token"]
    _post_message(client, widget_key, token_a, text="from A")
    _post_message(client, widget_key, token_b, text="from B")

    res_a = _get_messages(client, widget_key, token_a)
    texts_a = [m["text"] for m in res_a.json()["data"]]
    assert texts_a == ["from A"]

    res_b = _get_messages(client, widget_key, token_b)
    texts_b = [m["text"] for m in res_b.json()["data"]]
    assert texts_b == ["from B"]


def test_get_messages_cross_channel_token_refused(client):
    key_a, _ = _new_channel(client, name="History A")
    key_b, _ = _new_channel(client, name="History B")
    token_a = _session(client, key_a).json()["token"]

    res = _get_messages(client, key_b, token_a)
    assert res.status_code == 401


def test_get_messages_excludes_internal_notes(client, session_factory):
    from modules.omnichannel.models import ConversationMessage

    widget_key, channel_id = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    _post_message(client, widget_key, token, text="visible")

    db = session_factory()
    contact_id = (
        db.query(ConversationMessage.contact_id)
        .filter(ConversationMessage.channel_id == channel_id)
        .first()[0]
    )
    note = ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID,
        contact_id=contact_id,
        channel_id=None,
        sender_type="SYSTEM",
        message_type="TEXT",
        body="internal only",
    )
    db.add(note)
    db.commit()
    db.close()

    res = _get_messages(client, widget_key, token)
    texts = [m["text"] for m in res.json()["data"]]
    assert texts == ["visible"]
    assert "internal only" not in res.text


# ── AC-WEB-35: fail-closed visitor projection ────────────────────────────────
def test_visitor_message_item_drops_unknown_sender_type():
    from modules.omnichannel.services.webchat_projection import visitor_message_item

    row = SimpleNamespace(
        id="m1", sender_type="SYSTEM", message_type="TEXT", body="note",
        created_at=None, delivery_status=None,
    )
    channel = SimpleNamespace(widget_config_json={})
    assert visitor_message_item(row, channel) is None


def test_visitor_message_item_drops_unknown_message_kind():
    from modules.omnichannel.services.webchat_projection import visitor_message_item

    row = SimpleNamespace(
        id="m2", sender_type="CONTACT", message_type="STICKER", body=None,
        created_at=None, delivery_status=None,
    )
    channel = SimpleNamespace(widget_config_json={})
    assert visitor_message_item(row, channel) is None


def test_visitor_message_item_agent_message_shows_only_configured_display_name():
    from modules.omnichannel.services.webchat_projection import visitor_message_item

    row = SimpleNamespace(
        id="m3", sender_type="AGENT", message_type="TEXT", body="hello from support",
        created_at=None, delivery_status="SENT",
    )
    channel = SimpleNamespace(
        widget_config_json={"appearance": {"agentDisplayName": "Acme Care"}}
    )
    item = visitor_message_item(row, channel)
    assert item["agentName"] == "Acme Care"
    assert item["direction"] == "out"
    assert item["status"] == "sent"


def test_visitor_frame_drops_unknown_type_and_foreign_contact():
    from modules.omnichannel.services.webchat_projection import visitor_frame

    channel = SimpleNamespace(widget_config_json={})
    unknown_type = {"type": "message.status", "message": {"contactId": "c1"}}
    assert visitor_frame(unknown_type, channel, "c1", "ch1") is None

    foreign_contact = {
        "type": "message.created",
        "message": {
            "contactId": "c2", "channelId": "ch1", "senderType": "AGENT",
            "messageType": "TEXT",
        },
    }
    assert visitor_frame(foreign_contact, channel, "c1", "ch1") is None

    ok = {
        "type": "message.created",
        "message": {
            "contactId": "c1", "channelId": "ch1", "senderType": "CONTACT",
            "messageType": "TEXT", "body": "hi", "id": "m9",
            "createdAt": "2026-01-01T00:00:00Z",
        },
    }
    projected = visitor_frame(ok, channel, "c1", "ch1")
    assert projected is not None
    assert projected["direction"] == "in"
    assert projected["text"] == "hi"


# ── Review round 1, B2: the relay is CHANNEL-scoped, not only contact-scoped ─
def test_visitor_frame_drops_a_frame_from_another_channel_on_the_same_contact():
    """One contact can hold identities on several channels at once (a web
    chat visitor who later messages the business on WhatsApp stitches onto
    the SAME contact) and the realtime room is per WORKSPACE - so the contact
    filter alone let WhatsApp frames, including agent media with its signed
    URL, reach a browser sitting on a public website."""
    from modules.omnichannel.services.webchat_projection import visitor_frame

    channel = SimpleNamespace(widget_config_json={})
    other_channel = {
        "type": "message.created",
        "message": {
            "contactId": "c1", "channelId": "ch-whatsapp", "senderType": "AGENT",
            "messageType": "TEXT", "body": "secret reply", "id": "m10",
            "createdAt": "2026-01-01T00:00:00Z",
        },
    }
    assert visitor_frame(other_channel, channel, "c1", "ch-webchat") is None


def test_visitor_frame_fails_closed_when_the_frame_carries_no_channel():
    """Fail closed, never "assume it is ours" - a frame with no `channelId`
    (or a null one) is dropped, the same discipline sender type and message
    kind follow (AC-WEB-35)."""
    from modules.omnichannel.services.webchat_projection import visitor_frame

    channel = SimpleNamespace(widget_config_json={})
    base = {
        "contactId": "c1", "senderType": "AGENT", "messageType": "TEXT",
        "body": "hi", "id": "m11", "createdAt": "2026-01-01T00:00:00Z",
    }
    assert visitor_frame({"type": "message.created", "message": base}, channel, "c1", "ch1") is None
    assert (
        visitor_frame(
            {"type": "message.created", "message": {**base, "channelId": None}},
            channel, "c1", "ch1",
        )
        is None
    )
    # ... and the socket itself is refused rather than relaying everything if
    # the principal somehow carries no channel id at all.
    assert (
        visitor_frame(
            {"type": "message.created", "message": {**base, "channelId": "ch1"}},
            channel, "c1", "",
        )
        is None
    )


# ── Review round 1, B1: in-flight delivery statuses never 500 the read ──────
def test_visitor_projection_maps_in_flight_delivery_status_to_null():
    """`QUEUED` (an agent reply committed but not yet picked up by the Celery
    send task) and `SENDING` are legitimate stored values that the wire model
    does not accept. Passing them through raised a `ValidationError` inside
    the public route - a 500 that took the visitor's whole transcript with
    it, permanently while the worker was down."""
    from modules.omnichannel.services.webchat_projection import visitor_frame, visitor_message_item

    channel = SimpleNamespace(widget_config_json={})
    for raw in ("QUEUED", "SENDING", "TOTALLY_NEW_STATUS", "", None):
        row = SimpleNamespace(
            id="m4", sender_type="AGENT", message_type="TEXT", body="hi",
            created_at=None, delivery_status=raw,
        )
        assert visitor_message_item(row, channel)["status"] is None
        frame = {
            "type": "message.created",
            "message": {
                "contactId": "c1", "channelId": "ch1", "senderType": "AGENT",
                "messageType": "TEXT", "body": "hi", "id": "m4",
                "createdAt": "2026-01-01T00:00:00Z", "deliveryStatus": raw,
            },
        }
        assert visitor_frame(frame, channel, "c1", "ch1")["status"] is None
    for raw, expected in (("SENT", "sent"), ("delivered", "delivered"), ("READ", "read"),
                          ("FAILED", "failed")):
        row = SimpleNamespace(
            id="m5", sender_type="AGENT", message_type="TEXT", body="hi",
            created_at=None, delivery_status=raw,
        )
        assert visitor_message_item(row, channel)["status"] == expected


# ── Review round 1, S7: the IP bucket is not spent on a page reload ─────────
def _webchat_fail_count(session_factory):
    from app.models.auth_throttle import THROTTLE_SCOPE_WEBCHAT, AuthThrottle

    db = session_factory()
    try:
        rows = db.query(AuthThrottle).filter(AuthThrottle.scope == THROTTLE_SCOPE_WEBCHAT).all()
        return sum(r.fail_count for r in rows)
    finally:
        db.close()


def test_session_resume_with_a_valid_token_spends_no_ip_throttle_token(
    client, session_factory
):
    """Every page view of the customer's website starts a session, and the
    whole IP budget is shared by one egress address - a NAT'd office, a
    school, a CGNAT range. A reload carrying a token that VERIFIES against
    this channel is not an attempt at anything, so it costs nothing; a FRESH
    visitor and a revoked/foreign token both still count."""
    widget_key, channel_id = _new_channel(client)

    before_fresh = _webchat_fail_count(session_factory)
    token = _session(client, widget_key).json()["token"]
    assert _webchat_fail_count(session_factory) == before_fresh + 1

    before_reload = _webchat_fail_count(session_factory)
    for _ in range(5):
        assert _session(client, widget_key, token=token).status_code == 200
    assert _webchat_fail_count(session_factory) == before_reload

    # An epoch bump makes that same token invalid - the reload starts a fresh
    # session AND spends a token again.
    h = _auth(client)
    assert client.post(
        f"/omnichannel/channels/{channel_id}/widget/sign-out-visitors", headers=h
    ).status_code == 200
    before_revoked = _webchat_fail_count(session_factory)
    assert _session(client, widget_key, token=token).status_code == 200
    assert _webchat_fail_count(session_factory) == before_revoked + 1


def test_a_throttled_webchat_request_logs_one_warning(client, caplog):
    """The loader's `.catch` is silent by design (nothing renders on the
    customer's page), so a 429 must leave a trace an operator can find."""
    import logging

    widget_key, _ = _new_channel(client)
    prev = settings.throttle_webchat_max_fails
    settings.throttle_webchat_max_fails = 1
    try:
        _session(client, widget_key)
        with caplog.at_level(logging.WARNING, logger="modules.omnichannel.routers.webchat_public"):
            res = _session(client, widget_key)
        assert res.status_code == 429
        lines = [r.getMessage() for r in caplog.records]
        assert any("webchat throttled" in line for line in lines)
        # The raw IP never lands in the log line.
        assert not any("127.0.0.1" in line for line in lines)
    finally:
        settings.throttle_webchat_max_fails = prev


# ── R7 - no ambient credential anywhere on this surface ──────────────────────
def test_no_set_cookie_header_on_any_public_webchat_response(client):
    widget_key, _ = _new_channel(client)
    session_res = _session(client, widget_key)
    assert "set-cookie" not in session_res.headers
    token = session_res.json()["token"]
    msg_res = _post_message(client, widget_key, token, text="hi")
    assert "set-cookie" not in msg_res.headers
    get_res = _get_messages(client, widget_key, token)
    assert "set-cookie" not in get_res.headers


# ── BL-SS-183: the loader mints the session, the panel only consumes it ──────
# The S2 suite above sets `Origin` on the test client directly, which a real
# browser can never be told to do for a same-document fetch. These tests pin
# WHO may legitimately send which origin, so the hole that shipped in S2 -
# the panel calling `/session` itself, which forced the app's OWN origin onto
# every channel allowlist - cannot come back unnoticed.
def _panel_origin() -> str:
    from modules.omnichannel.services.webchat_visitor_service import panel_origin

    return panel_origin()


def test_session_from_the_panels_own_origin_is_the_uniform_404(client):
    """THE defect (BL-SS-183). A session start whose `Origin` is the app's
    own origin - the ONLY value a fetch from inside the panel iframe can
    ever carry - is refused exactly like an unknown key, because the app is
    not on the channel's allowlist. This is what makes the allowlist mean
    "which customer website", instead of "any website at all"."""
    widget_key, _ = _new_channel(client)
    res = _session(client, widget_key, origin=_panel_origin())
    assert res.status_code == 404
    assert res.json() == {"detail": "Not found."}
    # (The app origin does carry an `Access-Control-Allow-Origin` here - it is
    # in the service's own `CORS_ORIGINS` env for the rest of the app - but
    # the readable body is the same uniform 404 as an unknown key, and no
    # token exists to read.)


def test_session_from_the_host_page_origin_succeeds_without_allowlisting_the_app(client):
    """The other half: the LOADER's own origin (the customer's website) is
    the only thing on the allowlist and it is enough. No app origin, no
    panel origin - just the embedding site."""
    widget_key, _ = _new_channel(client, allowed_origins=[ORIGIN])
    res = _session(client, widget_key, origin=ORIGIN)
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == ORIGIN
    assert res.json()["token"]


def test_message_routes_accept_the_panel_origin_and_no_origin_at_all(client):
    """The panel's own calls: Bearer-authorized, fetched from inside the
    iframe, so they carry the APP's origin (or none, same-origin). They must
    not require the channel's host-page allowlist - and the echo is the
    exact panel origin, never `*`, never with credentials."""
    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    panel = _panel_origin()

    posted = _post_message(client, widget_key, token, text="from the panel", origin=panel)
    assert posted.status_code == 201
    assert posted.headers.get("access-control-allow-origin") == panel
    assert "Origin" in posted.headers.get("vary", "")
    assert "access-control-allow-credentials" not in posted.headers

    listed = _get_messages(client, widget_key, token, origin=panel)
    assert listed.status_code == 200
    assert listed.headers.get("access-control-allow-origin") == panel

    no_origin = _get_messages(client, widget_key, token, origin=None)
    assert no_origin.status_code == 200
    assert "access-control-allow-origin" not in no_origin.headers


def test_message_routes_do_not_echo_a_random_third_party_origin(client):
    widget_key, _ = _new_channel(client)
    token = _session(client, widget_key).json()["token"]
    res = _get_messages(client, widget_key, token, origin="https://evil.example")
    # The Bearer token is the credential, so the request is served - but the
    # browser can never READ it from an origin we do not echo.
    assert res.status_code == 200
    assert "access-control-allow-origin" not in res.headers


def test_cors_preflight_is_answered_for_a_channel_allowlisted_origin(client):
    """A customer website lives on the CHANNEL's allowlist, never in this
    service's `CORS_ORIGINS` env - so Starlette's own `CORSMiddleware` would
    answer the loader's preflight with `400 Disallowed CORS origin` and the
    real POST would never leave the browser. The webchat prefix answers its
    own preflight ahead of it."""
    widget_key, _ = _new_channel(client)
    res = client.options(
        SESSION_URL.format(key=widget_key),
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert res.status_code == 204
    assert res.headers.get("access-control-allow-origin") == ORIGIN
    assert "POST" in res.headers.get("access-control-allow-methods", "")
    assert "authorization" in res.headers.get("access-control-allow-headers", "")
    assert res.headers.get("vary") == "Origin"
    assert "access-control-allow-credentials" not in res.headers


def test_cors_preflight_refuses_an_off_list_origin(client):
    """Review round 1 (S9): the echo IS allowlist-checked now - the module
    registers its own origin resolver, so the middleware has channel context
    after all. An off-list site still gets a `204` (a preflight always does)
    but with NO `Access-Control-Allow-Origin`, so the browser never sends the
    real request; and that real request, forged outside a browser, is still
    the uniform 404 with no readable CORS header."""
    widget_key, _ = _new_channel(client)
    pre = client.options(
        SESSION_URL.format(key=widget_key),
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert pre.status_code == 204
    assert "access-control-allow-origin" not in pre.headers
    real = _session(client, widget_key, origin="https://evil.example")
    assert real.status_code == 404
    assert "access-control-allow-origin" not in real.headers


def test_cors_preflight_admits_the_panel_origin_for_the_message_routes(client):
    """The panel iframe is served by the Next app, which is a DIFFERENT
    origin from this backend, and its calls carry `Authorization` - so they
    preflight. The app's own origin is never on a channel's allowlist
    (BL-SS-183), so the resolver admits it explicitly."""
    from modules.omnichannel.services.webchat_visitor_service import panel_origin

    widget_key, _ = _new_channel(client)
    res = client.options(
        MESSAGES_URL.format(key=widget_key),
        headers={
            "Origin": panel_origin(),
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert res.status_code == 204
    assert res.headers.get("access-control-allow-origin") == panel_origin()


def test_public_cors_middleware_leaves_every_other_path_untouched(client):
    """The middleware is registry-driven and returns immediately for a path
    outside every registered prefix (review round 1, S9/N4) - core holds no
    module path constants and no other route's CORS behaviour moved."""
    res = client.options(
        "/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    # Whatever the stock `CORSMiddleware` decides, it is NOT this middleware's
    # 204-with-no-body preflight answer.
    assert res.status_code != 204 or "access-control-max-age" not in res.headers


def test_public_cors_prefix_is_registered_by_the_module_not_by_core(client):
    """S9's actual point: `app/main.py` no longer knows any module's route
    prefix - the module registers it at boot, like a capability."""
    import app.main as main_module
    from app.module_platform import public_cors_prefixes

    entries = {p.prefix: p.provider_module for p in public_cors_prefixes()}
    assert entries["/public/omnichannel/webchat/"] == "omnichannel"
    source = open(main_module.__file__, encoding="utf-8").read()
    assert "omnichannel/webchat" not in source
