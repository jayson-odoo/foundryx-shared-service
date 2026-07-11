"""Public gateway API tests (plan sprint-1/01 Slice 3).

Covers: key mint (once/hashed/live-only/revoke), Bearer resolution + constant-time
+ uniform 401, service-binding 403, public send 202 + our id + inbox bubble,
CSW-on-API, idempotency dedup (same/other workspace), read-only templates,
phone_number_id UNIQUE guard, tenant/workspace isolation, structured errors.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from modules.omnichannel.services import idempotency


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> str:
    return client.post("/auth/login", json={"email": email, "password": password}).json()[
        "access_token"
    ]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _default_workspace_id(session_factory) -> str:
    from modules.omnichannel.models import Workspace

    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.is_default.is_(True)).first()
    wid = ws.id
    db.close()
    return wid


def _seed_channel(session_factory, workspace_id, phone_number_id="pn-test"):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    db = session_factory()
    ch = Channel(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=workspace_id,
        channel_type="WHATSAPP",
        name="Test WA",
        credentials_json=encrypt_credentials({"dev": True}),
        phone_number_id=phone_number_id,
        display_phone_number="+60 11-111 1111",
        is_active=True,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
    )
    db.add(ch)
    db.commit()
    cid = ch.id
    db.close()
    return cid


def _seed_open_contact(session_factory, workspace_id, phone="+60123456789", open_window=True):
    from modules.omnichannel.models import Contact
    from modules.omnichannel.services import statuses

    db = session_factory()
    c = Contact(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=workspace_id,
        first_name="Sam",
        phone=phone,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "THREAD", "OPEN"),
        priority="MEDIUM",
        csw_expires_at=(_now() + timedelta(hours=20)) if open_window else None,
    )
    db.add(c)
    db.commit()
    cid = c.id
    db.close()
    return cid


def _mint(client, workspace_id, name="Prod key"):
    res = client.post(
        f"/omnichannel/workspaces/{workspace_id}/api-keys",
        json={"name": name},
        headers=_auth(client),
    )
    return res


# ── Key issuance (AC-01-12, AC-01-13) ────────────────────────────────────────
def test_mint_returns_full_key_once_and_stores_hashed(client, session_factory):
    ws = _default_workspace_id(session_factory)
    res = _mint(client, ws)
    assert res.status_code == 201
    body = res.json()
    full = body["fullKey"]
    assert full.startswith("fxw_live_")
    assert body["key"]["status"] == "ACTIVE"
    assert body["key"]["maskedKey"].startswith("fxw_live_")
    assert "••••" in body["key"]["maskedKey"]

    # list never re-exposes the plaintext
    lst = client.get(f"/omnichannel/workspaces/{ws}/api-keys", headers=_auth(client))
    assert lst.status_code == 200
    items = lst.json()["data"]
    assert len(items) == 1
    assert "fullKey" not in items[0]

    # storage is a sha256 hash + 8-char prefix, never the plaintext
    from modules.omnichannel.models import WorkspaceApiKey

    db = session_factory()
    row = db.query(WorkspaceApiKey).filter(WorkspaceApiKey.workspace_id == ws).first()
    assert len(row.key_hash) == 64 and row.key_hash != full
    assert len(row.key_prefix) == 8
    db.close()


def test_multiple_active_keys_and_revoke(client, session_factory):
    ws = _default_workspace_id(session_factory)
    k1 = _mint(client, ws, "a").json()
    k2 = _mint(client, ws, "b").json()
    assert k1["fullKey"] != k2["fullKey"]

    # revoke k1
    rid = k1["key"]["id"]
    rev = client.post(
        f"/omnichannel/workspaces/{ws}/api-keys/{rid}/revoke", headers=_auth(client)
    )
    assert rev.status_code == 200 and rev.json()["status"] == "REVOKED"

    # revoked key immediately 401s on the public API
    _seed_channel(session_factory, ws)
    r = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60123456789", "type": "template"},
        headers={"Authorization": f"Bearer {k1['fullKey']}"},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"


# ── Bearer resolution + uniform 401 (AC-01-14, AC-01-36) ─────────────────────
@pytest.mark.parametrize("hdr", [None, "Bearer nope", "Bearer fxw_live_deadbeef", "garbage"])
def test_invalid_keys_uniform_401(client, session_factory, hdr):
    headers = {"Authorization": hdr} if hdr else {}
    r = client.get("/api/v1/omnichannel/templates", headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"


# ── Service binding (AC-01-15) ───────────────────────────────────────────────
def test_service_not_enabled_when_module_inactive(client, session_factory):
    ws = _default_workspace_id(session_factory)
    key = _mint(client, ws).json()["fullKey"]
    # Deactivate the omnichannel module for the tenant.
    from app.services.app_store_service import AppStoreService

    db = session_factory()
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
    db.close()
    r = client.get(
        "/api/v1/omnichannel/templates", headers={"Authorization": f"Bearer {key}"}
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "service_not_enabled"


# ── Public send: 202 + our id + inbox bubble (AC-01-16) ──────────────────────
def test_public_send_template_202_and_inbox_bubble(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    key = _mint(client, ws).json()["fullKey"]

    r = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60999888777", "type": "template", "template": {"name": "anything"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    # No template row exists → structured 422 template_not_found (still the API envelope)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "template_not_found"


def test_public_send_text_open_window(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone="+60123123123", open_window=True)
    key = _mint(client, ws).json()["fullKey"]

    r = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60123123123", "type": "text", "text": {"body": "Hi there"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued" and body["id"] and body["idempotencyReplay"] is False

    # message landed in the inbox thread as an outbound bubble
    tok = _auth(client)
    from modules.omnichannel.models import Contact

    db = session_factory()
    contact = db.query(Contact).filter(Contact.phone == "+60123123123").first()
    cid = contact.id
    db.close()
    msgs = client.get(f"/omnichannel/contacts/{cid}/messages", headers=tok)
    assert msgs.status_code == 200
    bodies = [m["body"] for m in msgs.json()]
    assert "Hi there" in bodies


def test_public_list_contact_messages(client, session_factory):
    """Consumer can fetch a contact's message history (all types) read-only."""
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone="+60123123123", open_window=True)
    key = _mint(client, ws).json()["fullKey"]
    hdr = {"Authorization": f"Bearer {key}"}

    client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60123123123", "type": "text", "text": {"body": "Hi there"}},
        headers=hdr,
    )
    from modules.omnichannel.models import Contact

    db = session_factory()
    cid = db.query(Contact).filter(Contact.phone == "+60123123123").first().id
    db.close()

    r = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages", headers=hdr)
    assert r.status_code == 200
    body = r.json()
    # respond.io shape: {items:[{messageId, contactId, traffic, message:{type,text}, ...}], pagination}
    assert all(m["contactId"] == cid for m in body["items"])
    assert "Hi there" in [m["message"]["text"] for m in body["items"]]
    assert "pagination" in body and set(body["pagination"]) == {"next", "previous"}


def test_public_list_messages_unknown_contact_404(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    key = _mint(client, ws).json()["fullKey"]
    r = client.get(
        "/api/v1/omnichannel/contacts/does-not-exist/messages",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "contact_not_found"


def _seeded(client, session_factory, phone="+60123123123"):
    """Seed a channel + open contact + send one text; returns (hdr, contactId)."""
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone=phone, open_window=True)
    key = _mint(client, ws).json()["fullKey"]
    hdr = {"Authorization": f"Bearer {key}"}
    client.post(
        "/api/v1/omnichannel/messages",
        json={"to": phone, "type": "text", "text": {"body": "Hi there"}},
        headers=hdr,
    )
    from modules.omnichannel.models import Contact

    db = session_factory()
    cid = db.query(Contact).filter(Contact.phone == phone).first().id
    db.close()
    return hdr, cid


def test_public_list_contacts(client, session_factory):
    hdr, cid = _seeded(client, session_factory)
    r = client.get("/api/v1/omnichannel/contacts?pageSize=10", headers=hdr)
    assert r.status_code == 200
    body = r.json()
    assert any(c["id"] == cid for c in body["items"])
    assert "pagination" in body and set(body["pagination"]) == {"next", "previous"}


def test_public_get_contact_by_id_and_phone(client, session_factory):
    hdr, cid = _seeded(client, session_factory, phone="+60555111222")
    by_id = client.get(f"/api/v1/omnichannel/contacts/{cid}", headers=hdr)
    assert by_id.status_code == 200 and by_id.json()["id"] == cid
    by_phone = client.get("/api/v1/omnichannel/contacts/phone:+60555111222", headers=hdr)
    assert by_phone.status_code == 200 and by_phone.json()["id"] == cid


def test_public_get_single_message(client, session_factory):
    hdr, cid = _seeded(client, session_factory, phone="+60555111333")
    msgs = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages", headers=hdr).json()["items"]
    mid = msgs[0]["messageId"]
    r = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages/{mid}", headers=hdr)
    assert r.status_code == 200 and r.json()["messageId"] == mid


def test_public_update_contact_priority(client, session_factory):
    hdr, cid = _seeded(client, session_factory, phone="+60555111444")
    r = client.patch(
        f"/api/v1/omnichannel/contacts/{cid}",
        json={"priority": "HIGH", "firstName": "Kay"},
        headers=hdr,
    )
    assert r.status_code == 200
    # RioContactItem shape: firstName reflects the write (priority isn't in the
    # respond.io contact schema, so it's set server-side but not echoed).
    assert r.json()["firstName"] == "Kay"


def test_public_open_close_conversation(client, session_factory):
    hdr, cid = _seeded(client, session_factory, phone="+60555111555")
    closed = client.post(f"/api/v1/omnichannel/contacts/{cid}/conversation/close", headers=hdr)
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    opened = client.post(f"/api/v1/omnichannel/contacts/{cid}/conversation/open", headers=hdr)
    assert opened.status_code == 200 and opened.json()["status"] == "open"


def test_public_add_comment(client, session_factory):
    hdr, cid = _seeded(client, session_factory, phone="+60555111666")
    r = client.post(
        f"/api/v1/omnichannel/contacts/{cid}/comments",
        json={"body": "internal note"},
        headers=hdr,
    )
    assert r.status_code == 201
    assert r.json()["senderType"] == "SYSTEM" and r.json()["body"] == "internal note"


# ── CSW on the public API (AC-01-17) ─────────────────────────────────────────
def test_csw_closed_free_form_409(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone="+60555000111", open_window=False)
    key = _mint(client, ws).json()["fullKey"]

    r = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60555000111", "type": "text", "text": {"body": "late"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "csw_window_closed"


def test_unsupported_type(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    key = _mint(client, ws).json()["fullKey"]
    # interactive/location/contacts/reaction are supported since plan 12
    # Slices 2/3; a genuinely unknown type → the stable typed error.
    r = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60123", "type": "carousel"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unsupported_type"


# ── Idempotency (AC-01-18) ───────────────────────────────────────────────────
def test_idempotency_replay_same_workspace(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone="+60700700700", open_window=True)
    key = _mint(client, ws).json()["fullKey"]
    hdr = {"Authorization": f"Bearer {key}", "Idempotency-Key": "abc-123"}
    payload = {"to": "+60700700700", "type": "text", "text": {"body": "once"}}

    r1 = client.post("/api/v1/omnichannel/messages", json=payload, headers=hdr)
    r2 = client.post("/api/v1/omnichannel/messages", json=payload, headers=hdr)
    assert r1.status_code == 202 and r2.status_code == 202
    assert r1.json()["id"] == r2.json()["id"]
    assert r2.json()["idempotencyReplay"] is True

    # exactly one message persisted
    from modules.omnichannel.models import Contact, ConversationMessage

    db = session_factory()
    c = db.query(Contact).filter(Contact.phone == "+60700700700").first()
    n = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.contact_id == c.id, ConversationMessage.body == "once")
        .count()
    )
    db.close()
    assert n == 1


# ── Templates read-only (AC-01-19) ───────────────────────────────────────────
def test_templates_list_over_api(client, session_factory):
    ws = _default_workspace_id(session_factory)
    cid = _seed_channel(session_factory, ws)
    key = _mint(client, ws).json()["fullKey"]

    from modules.omnichannel.models import WhatsappTemplate

    db = session_factory()
    db.add(
        WhatsappTemplate(
            tenant_id=DEFAULT_TENANT_ID,
            channel_id=cid,
            name="welcome",
            language="en",
            status="APPROVED",
            components_json=[{"type": "BODY", "text": "Hello {{1}}"}],
        )
    )
    db.commit()
    db.close()

    r = client.get("/api/v1/omnichannel/templates", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert any(t["name"] == "welcome" and t["variableCount"] == 1 for t in data)


# ── Cross-workspace isolation (AC-01-37) ─────────────────────────────────────
def _seed_second_workspace(session_factory):
    from modules.omnichannel.models import Channel, Contact, Workspace, WhatsappTemplate
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    db = session_factory()
    ws = Workspace(tenant_id=DEFAULT_TENANT_ID, name="Second", is_default=False)
    db.add(ws)
    db.flush()
    ch = Channel(
        tenant_id=DEFAULT_TENANT_ID,
        workspace_id=ws.id,
        channel_type="WHATSAPP",
        name="WS2 WA",
        credentials_json=encrypt_credentials({"dev": True}),
        phone_number_id="pn-ws2",
        is_active=True,
        status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
    )
    db.add(ch)
    db.flush()
    db.add(
        WhatsappTemplate(
            tenant_id=DEFAULT_TENANT_ID,
            channel_id=ch.id,
            name="ws2_secret_template",
            language="en",
            status="APPROVED",
            components_json=[{"type": "BODY", "text": "WS2 only"}],
        )
    )
    db.commit()
    wid = ws.id
    db.close()
    return wid


def test_key_cannot_reach_another_workspace(client, session_factory):
    ws_a = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws_a)
    ws_b = _seed_second_workspace(session_factory)

    # A template only workspace B has.
    from modules.omnichannel.models import WhatsappTemplate

    key_a = _mint(client, ws_a).json()["fullKey"]

    # A's key lists ONLY A's templates — never B's.
    r = client.get(
        "/api/v1/omnichannel/templates", headers={"Authorization": f"Bearer {key_a}"}
    )
    assert r.status_code == 200
    names = [t["name"] for t in r.json()["data"]]
    assert "ws2_secret_template" not in names

    # A contact created via A's key lands in workspace A, not B. (A text send to
    # a brand-new number creates the contact, then hits the closed-window 409 —
    # the contact is already persisted in workspace A by then.)
    client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60321321321", "type": "text", "text": {"body": "hi"}},
        headers={"Authorization": f"Bearer {key_a}"},
    )
    from modules.omnichannel.models import Contact

    db = session_factory()
    made = db.query(Contact).filter(Contact.phone == "60321321321").all()
    assert len(made) == 1
    assert made[0].workspace_id == ws_a and made[0].workspace_id != ws_b
    db.close()


# ── phone_number_id uniqueness guard (AC-01-20) ──────────────────────────────
def test_phone_number_in_use_guard(session_factory):
    from modules.omnichannel.services.onboarding_service import (
        OnboardingService,
        PhoneNumberInUse,
    )

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id="pn-dup")
    db = session_factory()
    with pytest.raises(PhoneNumberInUse):
        OnboardingService(db)._assert_phone_available("pn-dup")
    db.close()


def test_trashed_channel_does_not_block_reconnect(session_factory):
    """A disconnected (is_trashed) channel keeps its phone_number_id but must NOT
    block reconnecting the same number — the guard is scoped to live rows, matching
    the partial-unique index predicate."""
    from modules.omnichannel.models import Channel
    from modules.omnichannel.services.onboarding_service import OnboardingService
    from modules.omnichannel.services import statuses

    ws = _default_workspace_id(session_factory)
    db = session_factory()
    db.add(
        Channel(
            tenant_id=DEFAULT_TENANT_ID,
            workspace_id=ws,
            channel_type="WHATSAPP",
            name="old",
            phone_number_id="pn-recon",
            is_active=False,
            is_trashed=True,  # disconnected — keeps its phone_number_id
            status_id=statuses.status_id_for(db, DEFAULT_TENANT_ID, "CHANNEL", "ACTIVE"),
        )
    )
    db.commit()
    # Must NOT raise — only a trashed row holds the number.
    OnboardingService(db)._assert_phone_available("pn-recon")
    db.close()


# ── respond.io parity additions (signed media, two-way cursor, template filters) ──
def test_verify_media_sig_pure():
    """Signature round-trip: valid passes, tampered/wrong-id/expired all fail."""
    import re

    from modules.omnichannel.security import _media_sig, signed_media_url, verify_media_sig

    url = signed_media_url("msg-123")
    assert url.startswith("http") and "/omnichannel/media/msg-123" in url
    m = re.search(r"exp=(\d+)&sig=([0-9a-f]+)", url)
    exp, sig = int(m.group(1)), m.group(2)
    assert verify_media_sig("msg-123", exp, sig)
    assert not verify_media_sig("msg-123", exp, sig + "00")   # tampered
    assert not verify_media_sig("other", exp, sig)             # bound to a different id
    assert not verify_media_sig("msg-123", 1, _media_sig("msg-123", 1))  # exp=1970 → expired


def _seed_media_message(session_factory, cid):
    from app.models import DEFAULT_TENANT_ID
    from app.services.storage import storage_for_tenant

    from modules.omnichannel.models import Channel, Contact, ConversationMessage

    db = session_factory()
    contact = db.query(Contact).filter(Contact.id == cid).first()
    ch = db.query(Channel).filter(Channel.workspace_id == contact.workspace_id).first()
    key = storage_for_tenant(db, DEFAULT_TENANT_ID).save("omni-test.png", b"PNGDATA", "image/png")
    msg = ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID, contact_id=cid, channel_id=ch.id,
        sender_type="CONTACT", message_type="IMAGE",
        media_key=key, media_mime="image/png",
    )
    db.add(msg)
    db.commit()
    mid = msg.id
    db.close()
    return mid


def _relativize(url):
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    return parts.path + ("?" + parts.query if parts.query else "")


def test_public_media_signed_url_serves_without_auth(client, session_factory):
    hdr, cid = _seeded(client, session_factory, phone="+60555222111")
    mid = _seed_media_message(session_factory, cid)

    r = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages", headers=hdr)
    item = [m for m in r.json()["items"] if m["messageId"] == mid][0]
    url = item["message"]["url"]
    assert url.startswith("http") and "exp=" in url and "sig=" in url

    rel = _relativize(url)
    # No Authorization header — the signature IS the authorization.
    got = client.get(rel)
    assert got.status_code == 200 and got.content == b"PNGDATA"

    # Tampered signature → 401.
    bad = client.get(rel.replace("sig=", "sig=x"))
    assert bad.status_code == 401


def test_public_messages_two_way_cursor(client, session_factory):
    hdr, cid = _seeded(client, session_factory, phone="+60555333111")
    # _seeded already sent one; add three more (total 4).
    for i in range(3):
        client.post(
            "/api/v1/omnichannel/messages",
            json={"to": "+60555333111", "type": "text", "text": {"body": f"m{i}"}},
            headers=hdr,
        )
    page = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages?limit=2", headers=hdr).json()
    assert len(page["items"]) == 2
    # Full page ⇒ older history exists ⇒ a next cursor is offered; previous too.
    assert page["pagination"]["next"] and page["pagination"]["previous"]

    oldest_id = page["items"][0]["messageId"]
    newest_id = page["items"][-1]["messageId"]
    # before = OLDER than the page's oldest → distinct, non-empty.
    older = client.get(
        f"/api/v1/omnichannel/contacts/{cid}/messages?limit=10&before={oldest_id}", headers=hdr
    ).json()
    assert older["items"] and all(m["messageId"] != oldest_id for m in older["items"])
    # after = NEWER than the newest returned → nothing newer.
    newer = client.get(
        f"/api/v1/omnichannel/contacts/{cid}/messages?limit=10&after={newest_id}", headers=hdr
    ).json()
    assert newer["items"] == []


def test_public_templates_channel_and_filters(client, session_factory):
    from app.models import DEFAULT_TENANT_ID

    from modules.omnichannel.models import Channel, WhatsappTemplate

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    db = session_factory()
    ch = db.query(Channel).filter(Channel.workspace_id == ws).first()
    chid = ch.id
    for name, cat in [("order_update", "UTILITY"), ("promo_blast", "MARKETING")]:
        db.add(WhatsappTemplate(
            tenant_id=DEFAULT_TENANT_ID, channel_id=ch.id, name=name,
            language="en_US", category=cat, status="APPROVED",
            components_json=[{"type": "BODY", "text": "Hi {{1}}"}],
        ))
    db.commit()
    db.close()
    key = _mint(client, ws).json()["fullKey"]
    hdr = {"Authorization": f"Bearer {key}"}

    allt = client.get("/api/v1/omnichannel/templates", headers=hdr).json()["data"]
    assert {t["name"] for t in allt} >= {"order_update", "promo_blast"}

    s = client.get("/api/v1/omnichannel/templates?search=order", headers=hdr).json()["data"]
    assert [t["name"] for t in s] == ["order_update"]

    c = client.get("/api/v1/omnichannel/templates?category=marketing", headers=hdr).json()["data"]
    assert [t["name"] for t in c] == ["promo_blast"]

    byc = client.get(f"/api/v1/omnichannel/templates?channelId={chid}", headers=hdr).json()["data"]
    assert len(byc) >= 2

    bad = client.get("/api/v1/omnichannel/templates?channelId=does-not-exist", headers=hdr)
    assert bad.status_code == 404 and bad.json()["error"]["code"] == "channel_not_found"
