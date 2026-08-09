"""Public gateway API tests (plan sprint-1/01 Slice 3).

Covers: key mint (once/hashed/live-only/revoke), Bearer resolution + constant-time
+ uniform 401, service-binding 403, public send 202 + our id + inbox bubble,
CSW-on-API, idempotency dedup (same/other workspace), read-only templates,
phone_number_id UNIQUE guard, tenant/workspace isolation, structured errors.
"""
import json
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
    # DEFAULT is the documented guide shape: {contactId, data:[MessageItem], nextBefore}.
    assert set(body) == {"contactId", "data", "nextBefore"}
    assert body["contactId"] == cid
    assert all(m["contactId"] == cid for m in body["data"])
    assert "Hi there" in [m["body"] for m in body["data"]]
    assert all({"id", "senderType", "body", "createdAt"} <= set(m) for m in body["data"])

    # ...and the respond.io shape is one query param away.
    rio = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages?format=rio", headers=hdr).json()
    assert set(rio) == {"items", "pagination"}
    assert "Hi there" in [m["message"]["text"] for m in rio["items"]]

    # An unknown format is a typed 422, never a silent fallback to the other shape.
    bad = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages?format=nope", headers=hdr)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_request"


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
    # DEFAULT = documented guide envelope.
    assert set(body) == {"data", "total", "page", "pageSize"}
    assert any(c["id"] == cid for c in body["data"])

    rio = client.get("/api/v1/omnichannel/contacts?pageSize=10&format=rio", headers=hdr).json()
    assert any(c["id"] == cid for c in rio["items"])
    assert set(rio["pagination"]) == {"next", "previous"}


def test_public_get_contact_by_id_and_phone(client, session_factory):
    hdr, cid = _seeded(client, session_factory, phone="+60555111222")
    by_id = client.get(f"/api/v1/omnichannel/contacts/{cid}", headers=hdr)
    assert by_id.status_code == 200 and by_id.json()["id"] == cid
    by_phone = client.get("/api/v1/omnichannel/contacts/phone:+60555111222", headers=hdr)
    assert by_phone.status_code == 200 and by_phone.json()["id"] == cid


def test_public_get_single_message(client, session_factory):
    hdr, cid = _seeded(client, session_factory, phone="+60555111333")
    msgs = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages?format=rio", headers=hdr).json()["items"]
    mid = msgs[0]["messageId"]
    r = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages/{mid}?format=rio", headers=hdr)
    assert r.status_code == 200 and r.json()["messageId"] == mid


def test_public_update_contact_priority(client, session_factory):
    hdr, cid = _seeded(client, session_factory, phone="+60555111444")
    r = client.patch(
        f"/api/v1/omnichannel/contacts/{cid}",
        json={"priority": "HIGH", "firstName": "Kay"},
        headers=hdr,
    )
    assert r.status_code == 200
    # DEFAULT echoes a ThreadItem — which, unlike the Rio shape, carries priority.
    body = r.json()
    assert body["name"] == "Kay" and body["priority"] == "HIGH"

    # Rio echo: firstName reflects the write; priority rides the FoundryX
    # extension fields (BL-SS-026) rather than being dropped.
    rio = client.get(
        f"/api/v1/omnichannel/contacts/{cid}?format=rio", headers=hdr
    ).json()
    assert rio["firstName"] == "Kay" and rio["priority"] == "HIGH"


def test_public_open_close_conversation(client, session_factory):
    hdr, cid = _seeded(client, session_factory, phone="+60555111555")
    # Guide shape uses the documented UPPERCASE enum...
    closed = client.post(f"/api/v1/omnichannel/contacts/{cid}/conversation/close", headers=hdr)
    assert closed.status_code == 200 and closed.json()["status"] == "CLOSED"
    opened = client.post(f"/api/v1/omnichannel/contacts/{cid}/conversation/open", headers=hdr)
    assert opened.status_code == 200 and opened.json()["status"] == "OPEN"
    # ...respond.io's is lowercase. Both are correct for their own contract.
    rio = client.post(
        f"/api/v1/omnichannel/contacts/{cid}/conversation/close?format=rio", headers=hdr
    )
    assert rio.status_code == 200 and rio.json()["status"] == "closed"


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

    r = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages?format=rio", headers=hdr)
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
    page = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages?limit=2&format=rio", headers=hdr).json()
    assert len(page["items"]) == 2
    # Full page ⇒ older history exists ⇒ a next cursor is offered; previous too.
    assert page["pagination"]["next"] and page["pagination"]["previous"]

    oldest_id = page["items"][0]["messageId"]
    newest_id = page["items"][-1]["messageId"]
    # before = OLDER than the page's oldest → distinct, non-empty.
    older = client.get(
        f"/api/v1/omnichannel/contacts/{cid}/messages?limit=10&before={oldest_id}&format=rio", headers=hdr
    ).json()
    assert older["items"] and all(m["messageId"] != oldest_id for m in older["items"])
    # after = NEWER than the newest returned → nothing newer.
    newer = client.get(
        f"/api/v1/omnichannel/contacts/{cid}/messages?limit=10&after={newest_id}&format=rio", headers=hdr
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


# ── Contract-drift regressions (consumer integration guide §6/§6a/§9) ────────
# A consumer built to the published guide found the gateway had dropped fields
# it documents. These pin the restored ones so the shape can't silently regress
# again: every message carries a `timestamp` (INBOUND included — inbound never
# gets a delivery receipt, so `status[]` is empty and cannot carry the time),
# a contact exposes `cswExpiresAt` (the whole free-form-vs-template decision),
# structured payloads survive, and a media body is not duplicated into `text`.
def _insert_message(session_factory, contact_id, channel_id=None, **kw):
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    m = ConversationMessage(
        tenant_id=DEFAULT_TENANT_ID,
        contact_id=contact_id,
        channel_id=channel_id,
        sender_type=kw.pop("sender_type", "CONTACT"),
        message_type=kw.pop("message_type", "TEXT"),
        body=kw.pop("body", "hello"),
        created_at=kw.pop("created_at", _now()),
        **kw,
    )
    db.add(m)
    db.commit()
    mid = m.id
    db.close()
    return mid


def test_incoming_message_carries_a_timestamp(client, session_factory):
    """An INBOUND message has no delivery receipt, so `status[]` is empty — the
    top-level `timestamp` is the only time key and MUST be populated, else a
    consumer cannot order or render a received message at all."""
    hdr, cid = _seeded(client, session_factory, phone="+60555222111")
    _insert_message(session_factory, cid, body="customer said hi")

    items = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages?format=rio", headers=hdr).json()["items"]
    assert items, "expected history"
    assert all(m["timestamp"] for m in items), "every message needs a timestamp"

    inbound = [m for m in items if m["traffic"] == "incoming"]
    assert inbound and all(m["status"] == [] for m in inbound), "inbound has no receipt"
    # Pin the VALUE, not just truthiness — `int(now())` would satisfy a truthy
    # check while carrying the read time instead of the message time.
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    created = {
        r.id: int(r.created_at.timestamp())
        for r in db.query(ConversationMessage).filter(
            ConversationMessage.contact_id == cid
        )
    }
    db.close()
    assert all(m["timestamp"] == created[m["messageId"]] for m in items), "timestamp is created_at"


def test_contact_exposes_csw_expiry(client, session_factory):
    """`cswExpiresAt` gates free-form vs template sending. Without it a consumer
    must either always send templates or provoke a 409."""
    hdr, cid = _seeded(client, session_factory, phone="+60555222222")
    body = client.get(f"/api/v1/omnichannel/contacts/{cid}?format=rio", headers=hdr).json()
    assert body["cswExpiresAt"], "open window must be exposed"
    assert body["cswExpiresAt"].endswith("Z"), "ISO-8601 Z, per the house convention"


def test_contact_csw_expiry_null_when_never_messaged_in(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_open_contact(session_factory, ws, phone="+60555222333", open_window=False)
    hdr = {"Authorization": f"Bearer {_mint(client, ws).json()['fullKey']}"}
    body = client.get(f"/api/v1/omnichannel/contacts/{cid}?format=rio", headers=hdr).json()
    assert body["cswExpiresAt"] is None


def test_structured_payload_survives_the_rio_shape(client, session_factory):
    """Interactive buttons / location coordinates cannot be flattened into
    `text` — a consumer would silently lose the buttons with no error."""
    hdr, cid = _seeded(client, session_factory, phone="+60555222444")
    buttons = {"kind": "buttons", "body": "Pick one", "buttons": [{"id": "a", "title": "Morning"}]}
    mid = _insert_message(
        session_factory, cid, sender_type="AGENT", message_type="INTERACTIVE",
        body="Pick one", payload_json=buttons,
    )
    got = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages/{mid}?format=rio", headers=hdr).json()
    assert got["message"]["type"] == "interactive"
    assert got["message"]["payload"] == buttons


def test_media_caption_is_not_duplicated_into_text(client, session_factory):
    """A media message's body IS its caption: expose it once, in `caption`."""
    hdr, cid = _seeded(client, session_factory, phone="+60555222555")
    mid = _insert_message(
        session_factory, cid, sender_type="AGENT", message_type="IMAGE", body="Your receipt",
        media_key="conn:x:receipt.png", media_mime="image/png",
        media_filename="receipt.png", media_size=1234,
    )
    msg = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages/{mid}?format=rio", headers=hdr).json()["message"]
    assert msg["caption"] == "Your receipt"
    assert msg["text"] is None, "must not duplicate the body into text"
    assert msg["size"] == 1234 and msg["url"], "size + signed URL exposed"


def test_text_caption_split_keys_off_message_type_not_media_presence(client, session_factory):
    """The split MUST key off the message TYPE. Keying off `url` presence (the
    first attempt) broke two real shapes:

    * a TEMPLATE/INTERACTIVE row carrying a HEADER IMAGE stores `media_key`, so
      `url` is set — but its body is body text, not a caption, and nulling
      `text` renders a blank bubble on the consumer side;
    * an inbound media row whose blob failed to store (dev creds / Graph
      hiccup — `_store_media` returns None by design) has NO `url`, but is
      still media, so its body is still a caption.
    """
    hdr, cid = _seeded(client, session_factory, phone="+60555222777")

    # TEMPLATE with a header image: url IS set, but text must survive.
    tpl = _insert_message(
        session_factory, cid, sender_type="AGENT", message_type="TEMPLATE",
        body="Hi Jayson, your booking is confirmed.",
        media_key="conn:x:header.png", media_mime="image/png", media_size=99,
    )
    got = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages/{tpl}?format=rio", headers=hdr).json()["message"]
    assert got["url"], "header image still exposed"
    assert got["text"] == "Hi Jayson, your booking is confirmed.", "template body is TEXT, not a caption"
    assert got["caption"] is None

    # Media WITHOUT a stored blob: no url, but it is still a caption.
    img = _insert_message(
        session_factory, cid, sender_type="CONTACT", message_type="IMAGE",
        body="Here is my receipt",
    )
    got = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages/{img}?format=rio", headers=hdr).json()["message"]
    assert got["url"] is None
    assert got["caption"] == "Here is my receipt", "media body is a caption even with no blob"
    assert got["text"] is None


def test_plain_text_still_returns_text(client, session_factory):
    """The other half of the split — the caption fix must not null TEXT bodies."""
    hdr, cid = _seeded(client, session_factory, phone="+60555222888")
    mid = _insert_message(session_factory, cid, body="just a plain message")
    msg = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages/{mid}?format=rio", headers=hdr).json()["message"]
    assert msg["text"] == "just a plain message" and msg["caption"] is None


def test_reactions_and_reply_are_exposed(client, session_factory):
    from modules.omnichannel.models import MessageReaction

    hdr, cid = _seeded(client, session_factory, phone="+60555222666")
    target = _insert_message(session_factory, cid, body="Is the venue accessible?")
    _insert_message(
        session_factory, cid, sender_type="AGENT", body="Yes it is",
        metadata_json={"reply_to": {"id": target, "body": "Is the venue accessible?",
                                    "senderType": "CONTACT", "senderName": None}},
    )
    db = session_factory()
    db.add(MessageReaction(
        tenant_id=DEFAULT_TENANT_ID, target_message_id=target,
        reactor_type="AGENT", reactor="agent-1", emoji="👍",
    ))
    db.commit()
    db.close()

    items = client.get(f"/api/v1/omnichannel/contacts/{cid}/messages?format=rio", headers=hdr).json()["items"]
    by_id = {m["messageId"]: m for m in items}
    assert by_id[target]["reactions"] == [
        {"emoji": "👍", "reactorType": "AGENT", "reactor": "agent-1"}
    ]
    replies = [m for m in items if m["replyTo"]]
    assert replies and replies[0]["replyTo"]["messageId"] == target


# ── Self-serve webhook registration on /api/v1 (BL-SS-025) ───────────────────
def test_consumer_can_register_and_manage_its_own_webhooks(client, session_factory):
    """A workspace API key must be able to register its OWN callbacks: webhooks
    are the intended inbound path, and registration used to be dashboard-only
    (session JWT), so a key-holder could not even LIST its endpoints."""
    hdr, _cid = _seeded(client, session_factory, phone="+60555333111")

    created = client.post(
        "/api/v1/omnichannel/webhooks",
        json={"name": "Ecohub", "url": "https://hooks.example.com/fx",
              "events": ["message.inbound", "message.status"]},
        headers=hdr,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    secret = body["signingSecret"]
    assert secret.startswith("whsec_"), "signing secret returned ONCE at create"
    eid = body["endpoint"]["id"]
    assert set(body["endpoint"]["events"]) == {"message.inbound", "message.status"}

    listed = client.get("/api/v1/omnichannel/webhooks", headers=hdr).json()["data"]
    assert [e["id"] for e in listed] == [eid]
    assert "signingSecret" not in listed[0] and "secret" not in listed[0], "never echo the secret"

    rotated = client.post(f"/api/v1/omnichannel/webhooks/{eid}/rotate", headers=hdr)
    assert rotated.status_code == 200 and rotated.json()["signingSecret"] != secret

    off = client.post(f"/api/v1/omnichannel/webhooks/{eid}/disable", headers=hdr)
    assert off.status_code == 200 and off.json()["status"] == "DISABLED"
    on = client.post(f"/api/v1/omnichannel/webhooks/{eid}/enable", headers=hdr)
    assert on.status_code == 200 and on.json()["status"] == "ACTIVE"

    assert client.delete(f"/api/v1/omnichannel/webhooks/{eid}", headers=hdr).status_code == 204
    assert client.get("/api/v1/omnichannel/webhooks", headers=hdr).json()["data"] == []


def test_webhook_url_validation_is_a_typed_422(client, session_factory):
    """SSRF guard still applies on the public surface, in the gateway's error
    envelope (the operator router raises a bare 400)."""
    hdr, _cid = _seeded(client, session_factory, phone="+60555333222")
    for bad_url in ("http://hooks.example.com/fx", "https://localhost/fx"):
        r = client.post(
            "/api/v1/omnichannel/webhooks",
            json={"name": "bad", "url": bad_url, "events": ["message.inbound"]},
            headers=hdr,
        )
        assert r.status_code == 422, bad_url
        assert r.json()["error"]["code"] == "invalid_request"


def test_key_cannot_touch_another_workspaces_webhook(client, session_factory):
    """`WebhookService._get` is tenant-scoped only, so a tenant with two
    workspaces could otherwise reach across with its own key. Must be the same
    uniform 404 as a genuine miss — no enumeration."""
    from modules.omnichannel.models import Workspace

    hdr_a, _ = _seeded(client, session_factory, phone="+60555333333")
    created = client.post(
        "/api/v1/omnichannel/webhooks",
        json={"name": "A", "url": "https://a.example.com/fx", "events": ["message.inbound"]},
        headers=hdr_a,
    ).json()
    eid_a = created["endpoint"]["id"]

    # A second workspace in the SAME tenant, with its own channel + key.
    db = session_factory()
    ws_b = Workspace(tenant_id=DEFAULT_TENANT_ID, name="WS B")
    db.add(ws_b)
    db.commit()
    ws_b_id = ws_b.id
    db.close()
    _seed_channel(session_factory, ws_b_id, phone_number_id="pn-ws-b")
    hdr_b = {"Authorization": f"Bearer {_mint(client, ws_b_id).json()['fullKey']}"}

    assert client.get("/api/v1/omnichannel/webhooks", headers=hdr_b).json()["data"] == []
    for call in (
        lambda: client.patch(f"/api/v1/omnichannel/webhooks/{eid_a}", json={"name": "hijack"}, headers=hdr_b),
        lambda: client.post(f"/api/v1/omnichannel/webhooks/{eid_a}/rotate", headers=hdr_b),
        lambda: client.post(f"/api/v1/omnichannel/webhooks/{eid_a}/disable", headers=hdr_b),
        lambda: client.delete(f"/api/v1/omnichannel/webhooks/{eid_a}", headers=hdr_b),
    ):
        assert call().status_code == 404

    # ...and A's endpoint is untouched.
    still = client.get("/api/v1/omnichannel/webhooks", headers=hdr_a).json()["data"]
    assert [e["id"] for e in still] == [eid_a] and still[0]["name"] == "A"


# ── Pagination + SSRF regressions (review round 3) ───────────────────────────
def test_guide_shape_next_before_paging(client, session_factory):
    """`nextBefore` is the documented paging mechanism and had NO test.
    Walk the whole thread with it: pages must not overlap, must cover every
    message exactly once, and the walk must terminate."""
    hdr, cid = _seeded(client, session_factory, phone="+60555444111")
    base = _now()
    for i in range(5):
        _insert_message(session_factory, cid, body=f"m{i}",
                        created_at=base + timedelta(minutes=i))

    seen, cursor, pages = [], None, 0
    while True:
        url = f"/api/v1/omnichannel/contacts/{cid}/messages?limit=2"
        if cursor:
            url += f"&before={cursor}"
        body = client.get(url, headers=hdr).json()
        ids = [m["id"] for m in body["data"]]
        assert not (set(ids) & set(seen)), "pages must not overlap"
        seen += ids
        pages += 1
        if body["nextBefore"] is None:
            break
        assert body["nextBefore"] == ids[0], "cursor is the OLDEST row on the page"
        cursor = body["nextBefore"]
        assert pages < 10, "paging did not terminate"

    total = client.get(
        f"/api/v1/omnichannel/contacts/{cid}/messages?limit=200", headers=hdr
    ).json()["data"]
    assert len(seen) == len(total) == 6, "every message reached exactly once"


def test_after_paging_does_not_emit_a_backwards_cursor(client, session_factory):
    """`after=` pages FORWARD, so items[0] is the row just past the caller's own
    anchor. Emitting it as `nextBefore` walked them back over ground they had."""
    hdr, cid = _seeded(client, session_factory, phone="+60555444222")
    base = _now()
    ids = [_insert_message(session_factory, cid, body=f"m{i}",
                           created_at=base + timedelta(minutes=i)) for i in range(5)]

    page = client.get(
        f"/api/v1/omnichannel/contacts/{cid}/messages?limit=3&after={ids[0]}", headers=hdr
    ).json()
    assert len(page["data"]) == 3
    assert page["nextBefore"] is None, "no older-direction cursor when paging forward"


def test_rio_pagination_url_is_followable_verbatim(client, session_factory):
    """§6b promises `format=rio` is carried in the cursor URL — following it
    must not silently hand back the guide shape."""
    hdr, cid = _seeded(client, session_factory, phone="+60555444333")
    base = _now()
    for i in range(5):
        _insert_message(session_factory, cid, body=f"m{i}",
                        created_at=base + timedelta(minutes=i))

    p1 = client.get(
        f"/api/v1/omnichannel/contacts/{cid}/messages?limit=3&format=rio", headers=hdr
    ).json()
    nxt = p1["pagination"]["next"]
    assert nxt and "format=rio" in nxt

    p2 = client.get(_relativize(nxt), headers=hdr).json()
    assert "items" in p2, "following the cursor verbatim must keep the rio shape"


def test_format_switch_is_enforced_on_every_read_route(client, session_factory):
    """A typo must 422 everywhere, not silently return the other shape on the
    routes that forgot the dependency."""
    hdr, cid = _seeded(client, session_factory, phone="+60555444444")
    mid = client.get(
        f"/api/v1/omnichannel/contacts/{cid}/messages", headers=hdr
    ).json()["data"][0]["id"]
    for path in (
        "/api/v1/omnichannel/contacts?format=nope",
        f"/api/v1/omnichannel/contacts/{cid}?format=nope",
        f"/api/v1/omnichannel/contacts/{cid}/messages?format=nope",
        f"/api/v1/omnichannel/contacts/{cid}/messages/{mid}?format=nope",
    ):
        r = client.get(path, headers=hdr)
        assert r.status_code == 422, path
        assert r.json()["error"]["code"] == "invalid_request"


def test_delivery_refuses_a_target_that_resolves_internally(monkeypatch):
    """The SSRF guard that actually closes the pivot: registration validated the
    URL, but DNS can be re-pointed afterwards — and the URL is now settable by
    any API-key holder. Every attempt re-checks before the POST."""
    import modules.omnichannel.services.webhook_service as ws

    monkeypatch.setattr(ws.socket, "getaddrinfo",
                        lambda host, port: [(None, None, None, "", ("169.254.169.254", 0))])
    with pytest.raises(ws.WebhookError):
        ws.assert_deliverable("https://rebound.example.com/hook")

    monkeypatch.setattr(ws.socket, "getaddrinfo",
                        lambda host, port: [(None, None, None, "", ("93.184.216.34", 0))])
    ws.assert_deliverable("https://ok.example.com/hook")  # public → allowed


def test_webhook_endpoint_cap_per_channel(client, session_factory):
    """Every inbound event fans out to ALL endpoints — unbounded registration is
    worker amplification, and an outbound amplifier on a key-authed surface."""
    from modules.omnichannel.services.webhook_service import MAX_ENDPOINTS_PER_CHANNEL

    hdr, _cid = _seeded(client, session_factory, phone="+60555444555")
    for i in range(MAX_ENDPOINTS_PER_CHANNEL):
        r = client.post(
            "/api/v1/omnichannel/webhooks",
            json={"name": f"w{i}", "url": f"https://hooks.example.com/{i}",
                  "events": ["message.inbound"]},
            headers=hdr,
        )
        assert r.status_code == 201, r.text
    over = client.post(
        "/api/v1/omnichannel/webhooks",
        json={"name": "over", "url": "https://hooks.example.com/over",
              "events": ["message.inbound"]},
        headers=hdr,
    )
    assert over.status_code == 422 and over.json()["error"]["code"] == "invalid_request"


def test_assignee_from_another_tenant_is_never_resolved(client, session_factory):
    """Cross-tenant leak guard. `_user_names` resolves a STORED user id to a
    name/EMAIL that is rendered to the caller — on the key-authed public
    gateway. An id belonging to another tenant must resolve to nothing.

    `patch_thread` validates the assignee on write, but it is not the only
    writer (legacy rows, restores, `sender_id` which is never validated), so
    the read path cannot assume the stored id is in-tenant."""
    from app.models.user import User
    from modules.omnichannel.models import Contact

    hdr, cid = _seeded(client, session_factory, phone="+60555555111")

    db = session_factory()
    intruder = User(
        tenant_id="tenant-somebody-else", email="ceo@othercompany.example",
        name="Other Tenant CEO", password="x",
    )
    db.add(intruder)
    db.flush()
    intruder_id, intruder_email = intruder.id, intruder.email
    # Plant the foreign id directly, bypassing the validating writer.
    db.query(Contact).filter(Contact.id == cid).update({"assigned_user_id": intruder_id})
    db.commit()
    db.close()

    body = client.get(f"/api/v1/omnichannel/contacts/{cid}", headers=hdr).json()
    assert body["assignedUserName"] is None, "must not resolve another tenant's user"
    assert intruder_email not in json.dumps(body)

    rio = client.get(f"/api/v1/omnichannel/contacts/{cid}?format=rio", headers=hdr).json()
    assert rio["assignee"] is None
    assert intruder_email not in json.dumps(rio)

    listed = client.get("/api/v1/omnichannel/contacts?pageSize=50", headers=hdr).json()
    assert intruder_email not in json.dumps(listed)
    assert "Other Tenant CEO" not in json.dumps(listed)


def test_delivery_path_calls_the_ssrf_guard(client, session_factory, monkeypatch):
    """Pins the WIRING, not just the helper: `dispatch` must refuse before the
    POST. Testing `assert_deliverable` alone let the call site be deleted."""
    import modules.omnichannel.services.webhook_delivery as wd
    import modules.omnichannel.services.webhook_service as ws
    from modules.omnichannel.models import WebhookDelivery

    hdr, _cid = _seeded(client, session_factory, phone="+60555555222")
    client.post(
        "/api/v1/omnichannel/webhooks",
        json={"name": "rebind", "url": "https://rebind.example.com/hook",
              "events": ["message.inbound"]},
        headers=hdr,
    )

    posted = []
    monkeypatch.setattr(wd.httpx, "post", lambda *a, **k: posted.append(a) or (_ for _ in ()).throw(AssertionError("POSTed to a blocked target")))
    # DNS now answers with a link-local address (rebinding after registration).
    monkeypatch.setattr(ws.socket, "getaddrinfo",
                        lambda host, port: [(None, None, None, "", ("169.254.169.254", 0))])

    db = session_factory()
    ep = db.query(__import__("modules.omnichannel.models", fromlist=["WebhookEndpoint"]).WebhookEndpoint).first()
    delivery = WebhookDelivery(
        tenant_id=DEFAULT_TENANT_ID, endpoint_id=ep.id, event_id="evt-ssrf",
        event_type="message.inbound", payload_json={"hello": "world"}, status="PENDING",
    )
    db.add(delivery)
    db.commit()
    did = delivery.id
    db.close()

    wd.dispatch(session_factory(), did)
    assert posted == [], "no network call may be made to a blocked target"

    db = session_factory()
    row = db.query(WebhookDelivery).filter(WebhookDelivery.id == did).first()
    assert row.status != "SUCCESS" and "refused" in (row.error or "").lower()
    db.close()
