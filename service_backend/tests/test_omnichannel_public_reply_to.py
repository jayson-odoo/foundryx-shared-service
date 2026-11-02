"""Plan 38 gap 4 - `replyToMessageId` on the public send (AC-38-70..77).

RED tests written before the implementation. Everything is asserted from the
outside: HTTP routes, stored message rows, the provider request at the HTTP
boundary, webhook delivery rows, and the guide text. Every test seeds its own
channels, contacts, keys and messages. Numbers and hosts are obvious fakes.
"""
import json
from pathlib import Path

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import ConversationMessage, WebhookDelivery
from modules.omnichannel.security import encrypt_credentials
from modules.omnichannel.services import idempotency
from modules.omnichannel.services import webhook_delivery as wd
from tests.test_omnichannel_api_gateway import (
    _default_workspace_id,
    _insert_message,
    _seed_open_contact,
    _seed_second_workspace,
)
from tests.test_omnichannel_broadcasts import _ensure_template
from tests.test_omnichannel_gateway_channels import _channel, _hdr

BASE = "/api/v1/omnichannel"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
FOREIGN_TENANT = "other-tenant-id"
HOOK = "https://hooks.example.com/reply"
PHONE = "+60111888001"


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


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


@pytest.fixture(autouse=True)
def _no_real_http(monkeypatch):
    class _Resp:
        status_code = 200

    monkeypatch.setattr(wd, "_post", lambda *a, **k: _Resp())


class _SpyAdapter:
    """Patched at the send_runner boundary (`get_adapter`); counts provider sends."""

    def __init__(self):
        self.sends = 0

    def upload_media(self, *a, **k):
        return "media-fake"

    def send(self, *a, **k):
        self.sends += 1
        return {"external_message_id": f"wamid.spy-{self.sends}"}


@pytest.fixture
def spy(monkeypatch):
    adapter = _SpyAdapter()
    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.get_adapter", lambda *a, **k: adapter
    )
    return adapter


# ── helpers ──────────────────────────────────────────────────────────────────
def _rig(client, session_factory, phone=PHONE, channels=1):
    ws = _default_workspace_id(session_factory)
    chans = [
        _channel(session_factory, ws, name=f"wa-{i}", age_rank=i + 1) for i in range(channels)
    ]
    cid = _seed_open_contact(session_factory, ws, phone=phone, open_window=True)
    hdr = _hdr(client, ws)
    return {"ws": ws, "channels": chans, "cid": cid, "hdr": hdr, "phone": phone}


def _quoted(session_factory, cid, channel_id=None, ext="wamid.quoted-1", **kw):
    return _insert_message(
        session_factory, cid, channel_id=channel_id, external_message_id=ext, body="quoted text", **kw
    )


def _body(r, quoted_id=None, **extra):
    body = {"to": r["phone"], "type": "text", "text": {"body": "answering"}}
    if quoted_id is not None:
        body["replyToMessageId"] = quoted_id
    body.update(extra)
    return body


def _post(client, r, body, headers=None):
    return client.post(f"{BASE}/messages", json=body, headers={**r["hdr"], **(headers or {})})


def _count(session_factory):
    db = session_factory()
    try:
        return db.query(ConversationMessage).count()
    finally:
        db.close()


def _row(session_factory, mid):
    db = session_factory()
    try:
        m = db.query(ConversationMessage).filter(ConversationMessage.id == mid).first()
        return {"meta": m.metadata_json, "channel_id": m.channel_id, "body": m.body}
    finally:
        db.close()


def _reply_id(session_factory, mid):
    meta = _row(session_factory, mid)["meta"] or {}
    return (meta.get("reply_to") or {}).get("id")


def _type_bodies(r, session_factory, monkeypatch):
    from modules.omnichannel.services.public_gateway_service import PublicGatewayService

    monkeypatch.setattr(PublicGatewayService, "_fetch_url", lambda self, url: PNG)
    _ensure_template(session_factory, r["channels"][0], name="tpl_reply")
    to = r["phone"]
    return {
        "text": {"to": to, "type": "text", "text": {"body": "hello"}},
        "template": {"to": to, "type": "template", "template": {"name": "tpl_reply", "variables": ["Sam", "shipped"]}},
        "image": {"to": to, "type": "image", "media": {"url": "https://files.example.com/a.png", "caption": "pic"}},
        "interactive": {
            "to": to,
            "type": "interactive",
            "interactive": {"kind": "buttons", "body": "Pick", "buttons": [{"id": "a", "title": "A"}]},
        },
        "location": {"to": to, "type": "location", "location": {"lat": 3.1, "lng": 101.6, "name": "HQ"}},
        "contacts": {
            "to": to,
            "type": "contacts",
            "contacts": [{"name": "Jane Doe", "phones": [{"phone": "+60123", "type": "CELL"}]}],
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-70 - the field is accepted in JSON and in the multipart payload
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_70_json_send_accepts_the_field(client, session_factory, spy):
    r = _rig(client, session_factory)
    q = _quoted(session_factory, r["cid"], r["channels"][0])
    res = _post(client, r, _body(r, q))
    assert res.status_code == 202, res.text
    assert _reply_id(session_factory, res.json()["id"]) == q


def test_ac_38_70_multipart_payload_accepts_the_field(client, session_factory, spy):
    r = _rig(client, session_factory)
    q = _quoted(session_factory, r["cid"], r["channels"][0])
    res = client.post(
        f"{BASE}/messages",
        files={"file": ("a.png", PNG, "image/png")},
        data={"payload": json.dumps({"to": r["phone"], "type": "image", "replyToMessageId": q})},
        headers=r["hdr"],
    )
    assert res.status_code == 202, res.text
    assert _reply_id(session_factory, res.json()["id"]) == q


def test_ac_38_70_control_send_without_the_field_is_unchanged(client, session_factory, spy):
    r = _rig(client, session_factory)
    res = _post(client, r, _body(r))
    assert res.status_code == 202, res.text
    assert res.json()["idempotencyReplay"] is False
    assert _reply_id(session_factory, res.json()["id"]) is None
    multipart = client.post(
        f"{BASE}/messages",
        files={"file": ("a.png", PNG, "image/png")},
        data={"payload": json.dumps({"to": r["phone"], "type": "image"})},
        headers=r["hdr"],
    )
    assert multipart.status_code == 202, multipart.text
    assert _reply_id(session_factory, multipart.json()["id"]) is None


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-71 - every content type quotes; a reaction refuses the field
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("kind", ["text", "template", "image", "interactive", "location", "contacts"])
def test_ac_38_71_each_content_type_stores_the_quoted_id(client, session_factory, monkeypatch, spy, kind):
    r = _rig(client, session_factory)
    q = _quoted(session_factory, r["cid"], r["channels"][0])
    body = _type_bodies(r, session_factory, monkeypatch)[kind]
    body["replyToMessageId"] = q
    res = _post(client, r, body)
    assert res.status_code == 202, res.text
    assert _reply_id(session_factory, res.json()["id"]) == q


def test_ac_38_71_reaction_with_the_field_is_invalid_request_and_creates_nothing(client, session_factory, spy):
    r = _rig(client, session_factory)
    q = _quoted(session_factory, r["cid"], r["channels"][0])
    before = _count(session_factory)
    res = _post(
        client,
        r,
        {
            "to": r["phone"],
            "type": "reaction",
            "reaction": {"messageId": q, "emoji": "\U0001F44D"},
            "replyToMessageId": q,
        },
    )
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "invalid_request"
    assert _count(session_factory) == before
    assert spy.sends == 0


def test_ac_38_71_control_reaction_without_the_field_is_accepted(client, session_factory, spy):
    r = _rig(client, session_factory)
    q = _quoted(session_factory, r["cid"], r["channels"][0])
    res = _post(
        client, r, {"to": r["phone"], "type": "reaction", "reaction": {"messageId": q, "emoji": "\U0001F44D"}}
    )
    assert res.status_code in (200, 202), res.text


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-72 - replyTo on reads, context.message_id on the provider request
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_72_history_read_shows_reply_to_in_both_shapes(client, session_factory, spy):
    r = _rig(client, session_factory)
    q = _quoted(session_factory, r["cid"], r["channels"][0])
    sent = _post(client, r, _body(r, q))
    assert sent.status_code == 202, sent.text
    mid = sent.json()["id"]

    default = client.get(f"{BASE}/contacts/{r['cid']}/messages", headers=r["hdr"]).json()["data"]
    item = next(m for m in default if m["id"] == mid)
    assert item["replyTo"]["id"] == q

    rio = client.get(f"{BASE}/contacts/{r['cid']}/messages?format=rio", headers=r["hdr"]).json()["items"]
    rio_item = next(m for m in rio if m["messageId"] == mid)
    assert rio_item["replyTo"]["messageId"] == q


def _capture_provider(monkeypatch, session_factory, channel_id):
    """The real WhatsApp adapter against a mocked HTTP boundary; returns the captured requests."""
    from app.config import settings
    from modules.omnichannel.adapters import get_adapter as real_get_adapter
    from modules.omnichannel.models import Channel

    monkeypatch.setattr(settings, "meta_app_id", "fake-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "fake-app-secret")
    db = session_factory()
    try:
        ch = db.query(Channel).filter(Channel.id == channel_id).first()
        ch.credentials_json = encrypt_credentials({"access_token": "fake-access-token"})
        db.commit()
    finally:
        db.close()

    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        try:
            captured.append(json.loads(request.content))
        except ValueError:
            captured.append({})
        return httpx.Response(200, json={"messages": [{"id": f"wamid.out-{len(captured)}"}]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        "modules.omnichannel.services.send_runner.get_adapter",
        lambda channel_type="WHATSAPP", recorder=None, **k: real_get_adapter(
            channel_type, client=http, recorder=recorder
        ),
    )
    return captured


def test_ac_38_72_provider_request_carries_the_quoted_provider_id(client, session_factory, monkeypatch):
    r = _rig(client, session_factory)
    q = _quoted(session_factory, r["cid"], r["channels"][0], ext="wamid.quoted-77")
    captured = _capture_provider(monkeypatch, session_factory, r["channels"][0])
    res = _post(client, r, _body(r, q))
    assert res.status_code == 202, res.text
    texts = [p for p in captured if p.get("type") == "text"]
    assert texts, captured
    assert texts[-1]["context"] == {"message_id": "wamid.quoted-77"}


def test_ac_38_72_control_plain_send_has_no_context(client, session_factory, monkeypatch):
    r = _rig(client, session_factory)
    captured = _capture_provider(monkeypatch, session_factory, r["channels"][0])
    res = _post(client, r, _body(r))
    assert res.status_code == 202, res.text
    texts = [p for p in captured if p.get("type") == "text"]
    assert texts, captured  # the provider boundary really saw the send
    assert "context" not in texts[-1]


def test_ac_38_72_quoted_message_without_provider_id_sends_unquoted_but_shows_reply_to(
    client, session_factory, monkeypatch
):
    r = _rig(client, session_factory)
    q = _quoted(session_factory, r["cid"], r["channels"][0], ext=None)
    captured = _capture_provider(monkeypatch, session_factory, r["channels"][0])
    res = _post(client, r, _body(r, q))
    assert res.status_code == 202, res.text
    texts = [p for p in captured if p.get("type") == "text"]
    assert texts, captured
    assert "context" not in texts[-1]
    assert _reply_id(session_factory, res.json()["id"]) == q
    default = client.get(f"{BASE}/contacts/{r['cid']}/messages", headers=r["hdr"]).json()["data"]
    assert next(m for m in default if m["id"] == res.json()["id"])["replyTo"]["id"] == q


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-73 - every unusable quoted id answers identically and sends nothing
# ═════════════════════════════════════════════════════════════════════════════
def _unusable_quoted_ids(session_factory, r):
    """Five ids that must all be answered alike."""
    from modules.omnichannel.models import Contact

    ws2 = _seed_second_workspace(session_factory)
    other_contact_same_ws = _seed_open_contact(session_factory, r["ws"], phone="+60111888002", open_window=True)
    other_ws_contact = _seed_open_contact(session_factory, ws2, phone="+60111888003", open_window=True)
    db = session_factory()
    try:
        alien = ConversationMessage(
            tenant_id=FOREIGN_TENANT,
            contact_id=r["cid"],  # same contact id: only the tenant scope can exclude it
            sender_type="CONTACT",
            message_type="TEXT",
            body="foreign tenant text",
            external_message_id="wamid.alien",
        )
        db.add(alien)
        db.commit()
        foreign_tenant_row = alien.id
    finally:
        db.close()
    note = _insert_message(session_factory, r["cid"], sender_type="SYSTEM", body="internal note")
    assert session_factory().query(Contact).filter(Contact.id == other_ws_contact).count() == 1  # control
    return {
        "unknown": "no-such-message-id",
        "other contact": _quoted(session_factory, other_contact_same_ws, None, ext="wamid.oc"),
        "other workspace": _quoted(session_factory, other_ws_contact, None, ext="wamid.ow"),
        "other tenant": foreign_tenant_row,
        "internal note": note,
    }


NOT_FOUND_MSG = "The message you are replying to was not found."


def _multipart(client, r, payload, headers=None):
    return client.post(
        f"{BASE}/messages",
        files={"file": ("a.png", PNG, "image/png")},
        data={"payload": json.dumps(payload)},
        headers={**r["hdr"], **(headers or {})},
    )


def _assert_not_found(res, label=""):
    assert res.status_code == 422, (label, res.text)
    err = res.json()["error"]
    assert err["code"] == "invalid_request", (label, res.text)
    assert err["message"] == NOT_FOUND_MSG, (label, res.text)


def _stored_files(tmp_path):
    return [p for p in tmp_path.rglob("*") if p.is_file()]


def test_ac_38_73_all_unusable_quoted_ids_answer_the_same_and_send_nothing(client, session_factory, spy):
    r = _rig(client, session_factory)
    ids = _unusable_quoted_ids(session_factory, r)
    answers = {}
    for label, qid in ids.items():
        before = _count(session_factory)
        res = _post(client, r, _body(r, qid))
        _assert_not_found(res, label)
        assert _count(session_factory) == before, label
        answers[label] = (res.status_code, res.json())
    assert spy.sends == 0
    distinct = {json.dumps(v, sort_keys=True) for v in answers.values()}
    assert len(distinct) == 1, answers


def test_ac_38_73_all_unusable_quoted_ids_answer_the_same_on_multipart(client, session_factory, spy, tmp_path):
    r = _rig(client, session_factory)
    ids = _unusable_quoted_ids(session_factory, r)
    answers = set()
    for label, qid in ids.items():
        before = _count(session_factory)
        res = _multipart(client, r, {"to": r["phone"], "type": "image", "replyToMessageId": qid})
        _assert_not_found(res, label)
        assert _count(session_factory) == before, label
        answers.add(json.dumps(res.json(), sort_keys=True))
    assert len(answers) == 1, answers
    assert spy.sends == 0
    assert _stored_files(tmp_path) == []


def test_ac_38_73_control_a_valid_quoted_message_sends(client, session_factory, spy):
    r = _rig(client, session_factory)
    _unusable_quoted_ids(session_factory, r)
    q = _quoted(session_factory, r["cid"], r["channels"][0])
    res = _post(client, r, _body(r, q))
    assert res.status_code == 202, res.text
    assert spy.sends == 1


def test_ac_38_73_refused_multipart_stores_nothing(client, session_factory, spy, tmp_path):
    r = _rig(client, session_factory)
    before = _count(session_factory)
    res = _multipart(client, r, {"to": r["phone"], "type": "image", "replyToMessageId": "no-such-id"})
    _assert_not_found(res)
    assert _count(session_factory) == before
    assert _stored_files(tmp_path) == []
    assert spy.sends == 0


def _to_variants(session_factory, r):
    import uuid

    return {
        "unknown id": f"id:{uuid.uuid4()}",
        "unknown psid": "psid:no-such-psid-0001",
        "malformed phone": "not-a-phone",
    }


@pytest.mark.parametrize("to_kind", ["unknown id", "unknown psid", "malformed phone"])
def test_ac_38_73_unresolved_recipient_answers_the_same_with_or_without_the_reply_id(
    client, session_factory, spy, to_kind
):
    r = _rig(client, session_factory)
    ids = _unusable_quoted_ids(session_factory, r)
    to = _to_variants(session_factory, r)[to_kind]
    before = _count(session_factory)
    baseline = _post(client, r, {"to": to, "type": "text", "text": {"body": "answering"}})
    assert baseline.status_code >= 400, baseline.text  # control: the recipient itself is refused
    for label, qid in ids.items():
        res = _post(client, r, {"to": to, "type": "text", "text": {"body": "answering"}, "replyToMessageId": qid})
        assert (res.status_code, res.json()) == (baseline.status_code, baseline.json()), (label, res.text)
        mp = _multipart(client, r, {"to": to, "type": "image", "replyToMessageId": qid})
        mp_base = _multipart(client, r, {"to": to, "type": "image"})
        assert (mp.status_code, mp.json()) == (mp_base.status_code, mp_base.json()), (label, mp.text)
    assert _count(session_factory) == before
    assert spy.sends == 0


def _count_statements(session_factory, fn):
    from sqlalchemy import event

    engine = session_factory.kw["bind"]
    n = {"n": 0}

    def _before(conn, cursor, statement, *a):
        n["n"] += 1

    event.listen(engine, "before_cursor_execute", _before)
    try:
        res = fn()
    finally:
        event.remove(engine, "before_cursor_execute", _before)
    return n["n"], res


def test_ac_38_73_unknown_and_foreign_ids_cost_the_same_work(client, session_factory, spy):
    r = _rig(client, session_factory)
    ids = _unusable_quoted_ids(session_factory, r)
    _post(client, r, _body(r, "warm-up-id"))  # warm any per-process caches
    counts = {}
    for label in ("unknown", "other workspace", "other contact"):
        n, res = _count_statements(session_factory, lambda q=ids[label]: _post(client, r, _body(r, q)))
        _assert_not_found(res, label)
        counts[label] = n
    assert len(set(counts.values())) == 1, counts


@pytest.mark.parametrize(
    "bad",
    ["x" * 65, "x" * 500, "bad\x00id", "bad\nid", "bad\tid", "\n", "\x00"],
    ids=["65 chars", "500 chars", "NUL", "newline", "tab", "only newline", "only NUL"],
)
def test_ac_38_73_malformed_reply_id_answers_like_an_unknown_one(client, session_factory, spy, tmp_path, bad):
    r = _rig(client, session_factory)
    before = _count(session_factory)
    res = _post(client, r, _body(r, bad))
    _assert_not_found(res, "json")
    mp = _multipart(client, r, {"to": r["phone"], "type": "image", "replyToMessageId": bad})
    _assert_not_found(mp, "multipart")
    unknown = _post(client, r, _body(r, "no-such-message-id"))
    assert res.json() == unknown.json()
    assert _count(session_factory) == before
    assert _stored_files(tmp_path) == []
    assert spy.sends == 0


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-74 - the resolved channel stands; a different channel is refused
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_74_quoting_a_message_on_another_channel_is_refused(client, session_factory, spy):
    r = _rig(client, session_factory, channels=2)
    a, b = r["channels"]
    q = _quoted(session_factory, r["cid"], b)
    before = _count(session_factory)
    res = _post(client, r, _body(r, q, channelId=a))
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "reply_channel_mismatch"
    assert _count(session_factory) == before
    assert spy.sends == 0


def test_ac_38_74_multipart_quoting_a_message_on_another_channel_is_refused(
    client, session_factory, spy, tmp_path
):
    r = _rig(client, session_factory, channels=2)
    a, b = r["channels"]
    q = _quoted(session_factory, r["cid"], b)
    before = _count(session_factory)
    res = _multipart(client, r, {"to": r["phone"], "type": "image", "channelId": a, "replyToMessageId": q})
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "reply_channel_mismatch"
    assert _count(session_factory) == before
    assert spy.sends == 0
    assert _stored_files(tmp_path) == []


def test_ac_38_74_quoting_a_message_on_the_same_channel_sends(client, session_factory, spy):
    r = _rig(client, session_factory, channels=2)
    a, b = r["channels"]
    q = _quoted(session_factory, r["cid"], a)
    res = _post(client, r, _body(r, q, channelId=a))
    assert res.status_code == 202, res.text
    assert _row(session_factory, res.json()["id"])["channel_id"] == a


def test_ac_38_74_quoting_a_message_with_no_channel_sends(client, session_factory, spy):
    r = _rig(client, session_factory, channels=2)
    a, b = r["channels"]
    q = _quoted(session_factory, r["cid"], None)
    res = _post(client, r, _body(r, q, channelId=a))
    assert res.status_code == 202, res.text
    assert _row(session_factory, res.json()["id"])["channel_id"] == a


def test_ac_38_74_channel_required_still_comes_first(client, session_factory, spy):
    r = _rig(client, session_factory, channels=2)
    _a, b = r["channels"]
    q = _quoted(session_factory, r["cid"], b)
    before = _count(session_factory)
    res = _post(client, r, _body(r, q))  # no channelId, two WhatsApp channels
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "channel_required"
    assert _count(session_factory) == before


def test_ac_38_74_send_never_moves_to_the_quoted_messages_channel(client, session_factory, spy):
    r = _rig(client, session_factory, channels=2)
    a, b = r["channels"]
    q = _quoted(session_factory, r["cid"], b)
    _post(client, r, _body(r, q, channelId=a))
    db = session_factory()
    try:
        sent_on_b = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.channel_id == b, ConversationMessage.sender_type != "CONTACT")
            .count()
        )
    finally:
        db.close()
    assert sent_on_b == 0


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-75 - the idempotency key alone identifies the send
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_38_75_replay_with_a_different_reply_id_returns_the_first_result(client, session_factory, spy):
    r = _rig(client, session_factory)
    q1 = _quoted(session_factory, r["cid"], r["channels"][0], ext="wamid.q-one")
    q2 = _quoted(session_factory, r["cid"], r["channels"][0], ext="wamid.q-two")
    hdrs = {"Idempotency-Key": "reply-key-1"}
    first = _post(client, r, _body(r, q1), hdrs)
    second = _post(client, r, _body(r, q2), hdrs)
    assert first.status_code == 202 and second.status_code == 202, (first.text, second.text)
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["idempotencyReplay"] is True
    assert _reply_id(session_factory, first.json()["id"]) == q1
    assert spy.sends == 1
    db = session_factory()
    try:
        n = db.query(ConversationMessage).filter(ConversationMessage.body == "answering").count()
    finally:
        db.close()
    assert n == 1


def test_ac_38_75_refused_send_frees_the_key_for_a_corrected_retry(client, session_factory, spy):
    r = _rig(client, session_factory, channels=2)
    a, b = r["channels"]
    q = _quoted(session_factory, r["cid"], b)
    hdrs = {"Idempotency-Key": "reply-key-2"}
    refused = _post(client, r, _body(r, q, channelId=a), hdrs)
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "reply_channel_mismatch"
    retry = _post(client, r, _body(r, q, channelId=b), hdrs)
    assert retry.status_code == 202, retry.text
    assert retry.json()["idempotencyReplay"] is False
    assert _reply_id(session_factory, retry.json()["id"]) == q


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-76 - the event envelopes are unchanged by the field
# ═════════════════════════════════════════════════════════════════════════════
def _keys(obj):
    return sorted(obj.keys())


def _event_rows(session_factory, event_type):
    db = session_factory()
    try:
        rows = db.query(WebhookDelivery).filter(WebhookDelivery.event_type == event_type).all()
        return [r.payload_json for r in rows]
    finally:
        db.close()


def test_ac_38_76_outbound_and_status_envelopes_match_a_plain_send(client, session_factory, spy):
    r = _rig(client, session_factory)
    reg = client.post(
        f"{BASE}/webhooks",
        json={"name": "w", "url": HOOK, "events": ["message.outbound", "message.status"]},
        headers=r["hdr"],
    )
    assert reg.status_code == 201, reg.text
    q = _quoted(session_factory, r["cid"], r["channels"][0])

    plain = _post(client, r, _body(r))
    assert plain.status_code == 202, plain.text
    reply = _post(client, r, _body(r, q))
    assert reply.status_code == 202, reply.text

    for event in ("message.outbound", "message.status"):
        rows = _event_rows(session_factory, event)
        by_msg = {p["data"]["messageId"] if "messageId" in p["data"] else p["data"]["message"]["id"]: p for p in rows}
        assert plain.json()["id"] in by_msg and reply.json()["id"] in by_msg, (event, list(by_msg))
        p_plain, p_reply = by_msg[plain.json()["id"]], by_msg[reply.json()["id"]]
        assert _keys(p_reply) == _keys(p_plain), event
        assert _keys(p_reply["data"]) == _keys(p_plain["data"]), event
        if event == "message.outbound":
            assert _keys(p_reply["data"]["message"]) == _keys(p_plain["data"]["message"])


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-77 - the guide documents the field
# ═════════════════════════════════════════════════════════════════════════════
_GUIDE = Path(__file__).resolve().parents[2] / "documentation/omnichannel/consumer-integration-guide.md"


def _section(text, start, end):
    i = text.index(start)
    j = text.index(end, i + len(start))
    return text[i:j]


def test_ac_38_77_guide_section_4_documents_the_field_and_its_rules():
    sec = _section(_GUIDE.read_text(), "## 4. Sending messages", "## 5. ")
    flat = " ".join(sec.split()).lower()
    assert "replytomessageid" in flat
    assert "reply_channel_mismatch" in flat
    assert "reaction" in flat and "invalid_request" in flat


def test_ac_38_77_guide_section_4_3_multipart_payload_mentions_the_field():
    sec = _section(_GUIDE.read_text(), "### 4.3", "### 4.4")
    assert "replyToMessageId" in sec


def test_ac_38_77_guide_error_table_lists_reply_channel_mismatch_with_422():
    errors = _section(_GUIDE.read_text(), "## 10. Error reference", "## 11.")
    rows = [ln for ln in errors.splitlines() if ln.startswith("|") and "`reply_channel_mismatch`" in ln]
    assert rows, "error table needs a reply_channel_mismatch row"
    assert any("422" in ln for ln in rows), rows


def test_ac_38_77_guide_changelog_has_a_row_for_the_field():
    lines = [ln for ln in _GUIDE.read_text().splitlines()[:40] if ln.startswith("> |")]
    assert any("replyToMessageId" in ln for ln in lines), "changelog needs a row naming replyToMessageId"


# ═════════════════════════════════════════════════════════════════════════════
# AC-38-73 - a reply id of the wrong shape is refused before any lookup
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def lookups(monkeypatch):
    from modules.omnichannel.repositories.contact_repository import ContactRepository

    seen = []
    real = ContactRepository.get_message

    def spy_get(self, message_id, tenant_id):
        seen.append(message_id)
        return real(self, message_id, tenant_id)

    monkeypatch.setattr(ContactRepository, "get_message", spy_get)
    return seen


@pytest.mark.parametrize(
    "bad",
    ["x" * 65, "x" * 500, "bad\x00id", "bad\nid", "bad\tid", "bad\x1fid", "bad\x7fid"],
    ids=["65 chars", "500 chars", "NUL", "newline", "tab", "unit separator", "DEL"],
)
def test_ac_38_73_wrong_shaped_reply_id_never_reaches_a_lookup(client, session_factory, spy, lookups, bad):
    r = _rig(client, session_factory)
    unknown = _post(client, r, _body(r, "no-such-message-id"))
    del lookups[:]
    res = _post(client, r, _body(r, bad))
    _assert_not_found(res, "json")
    mp = _multipart(client, r, {"to": r["phone"], "type": "image", "replyToMessageId": bad})
    _assert_not_found(mp, "multipart")
    assert res.json() == unknown.json()
    assert bad not in lookups, lookups
    assert spy.sends == 0


def test_ac_38_73_control_a_well_formed_unknown_reply_id_does_reach_the_lookup(
    client, session_factory, spy, lookups
):
    r = _rig(client, session_factory)
    _assert_not_found(_post(client, r, _body(r, "x" * 64)))
    _assert_not_found(_post(client, r, _body(r, "no-such-message-id")))
    assert "x" * 64 in lookups and "no-such-message-id" in lookups, lookups
