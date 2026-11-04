"""Batched webhook routing, review round 1.

RED tests written BEFORE the fixes. Black box through
``InboundService.process_payload`` and the webhook route function.
Pins: odd payload shapes never raise; a bounded number of lookups per POST;
parts handed to the adapter are minimal; an unmatched identifier is dropped
rather than sent to an unrelated URL channel; the legacy fallback for channels
with no identifier of their own; template events route by their WABA id; the
body size cap is applied before the whole body is read.

Every test seeds its own tenants, workspaces, channels, endpoints. Fake ids only.
"""
import asyncio
import json
import re

import pytest
from sqlalchemy import event

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import (
    Channel,
    ConversationMessage,
    WebhookDelivery,
    WebhookEndpoint,
    WhatsappTemplate,
)
from modules.omnichannel.services import inbound_service
from tests.test_omnichannel_inbound_batched_entries import (  # noqa: F401  (autouse fixture re-used)
    _channel,
    _change,
    _env,
    _in_msg,
    _msg_rows,
    _process,
    _tenant,
    _wa,
    _workspace,
    _world,
)
from tests.test_omnichannel_inbound_batched_entries import _seq


def _ok(rows, tenant, channel):
    return [(t, c) for t, c, *_ in rows] == [(tenant, channel)]


def _page_entry(account, psid, mid):
    return {
        "id": account,
        "time": 1717550000000,
        "messaging": [{
            "sender": {"id": psid}, "recipient": {"id": account},
            "timestamp": 1717550000000, "message": {"mid": mid, "text": "hello"},
        }],
    }


def _page_payload(obj, *entries):
    return {"object": obj, "entry": list(entries)}


# ── 1. odd shapes never raise ────────────────────────────────────────────────
ODD_CHANGES = {
    "string_value": {"field": "messages", "value": "not-an-object"},
    "list_value": {"field": "messages", "value": [1, 2]},
    "number_value": {"field": "messages", "value": 7},
    "string_metadata": {"field": "messages", "value": {"metadata": "x", "messages": []}},
    "list_metadata": {"field": "messages", "value": {"metadata": [1], "messages": []}},
    "change_is_string": "not-a-dict",
    "change_is_number": 5,
}


@pytest.mark.parametrize("name", sorted(ODD_CHANGES))
def test_odd_change_shapes_do_not_raise_and_the_sibling_is_processed(session_factory, name):
    w = _world(session_factory, two_tenants=False)
    ok = f"wamid.odd-{name}-{w['n']}"
    good = _change(w["pb"], messages=[_in_msg(ok, "60000000101")])
    counters = _process(session_factory, w["ch_a"], _wa([ODD_CHANGES[name], good]))
    assert isinstance(counters, dict)
    assert _ok(_msg_rows(session_factory, ok), w["t1"], w["ch_b"])


def test_changes_not_a_list_and_non_dict_entry_do_not_raise(session_factory):
    w = _world(session_factory, two_tenants=False)
    ok = f"wamid.odd-e-{w['n']}"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            "not-an-entry",
            {"id": "waba-x", "changes": "not-a-list"},
            {"id": "waba-y", "changes": {"field": "messages"}},
            {"id": "waba-z", "changes": [_change(w["pb"], messages=[_in_msg(ok, "60000000102")])]},
        ],
    }
    counters = _process(session_factory, w["ch_a"], payload)
    assert isinstance(counters, dict)
    assert _ok(_msg_rows(session_factory, ok), w["t1"], w["ch_b"])


@pytest.mark.parametrize("obj", ["page", "instagram"])
def test_odd_page_entries_do_not_raise(session_factory, obj):
    n = next(_seq)
    ctype = "FACEBOOK" if obj == "page" else "INSTAGRAM"
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, channel_type=ctype, account=f"acct-odd-{n}")
    mid = f"m.odd-{n}"
    payload = _page_payload(obj, "junk", 5, {"id": ["list"], "messaging": "x"},
                            _page_entry(f"acct-odd-{n}", f"psid-{n}", mid))
    counters = _process(session_factory, ch, payload)
    assert isinstance(counters, dict)
    assert _ok(_msg_rows(session_factory, mid), DEFAULT_TENANT_ID, ch)


# ── 2. bounded queries per POST ──────────────────────────────────────────────
class _Counter:
    def __init__(self, db):
        self.engine = db.get_bind()
        self.channel = 0
        self.module = 0

    def _hook(self, conn, cursor, statement, *a):
        s = statement.lower()
        if not s.lstrip().startswith("select"):
            return
        if re.search(r"from\s+(\w+\.)?channels\b", s):
            self.channel += 1
        if re.search(r"(from|join)\s+(\w+\.)?tenant_modules\b", s):
            self.module += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._hook)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._hook)


def _counted(session_factory, channel_id, payload):
    from modules.omnichannel.services.inbound_service import InboundService

    db = session_factory()
    try:
        with _Counter(db) as c:
            InboundService(db).process_payload(channel_id, payload)
        return c.channel, c.module
    finally:
        db.close()


def test_lookups_do_not_grow_with_the_number_of_whatsapp_parts(session_factory):
    w = _world(session_factory, two_tenants=False)

    def payload(count, tag):
        changes = [_change(f"pn-many-{tag}-{i}-{w['n']}", messages=[_in_msg(f"wamid.m-{tag}-{i}-{w['n']}", "60000000111")])
                   for i in range(count - 1)]
        changes.append(_change(w["pb"], messages=[_in_msg(f"wamid.k-{tag}-{w['n']}", "60000000112")]))
        return _wa(changes)

    small = _counted(session_factory, w["ch_a"], payload(5, "s"))
    large = _counted(session_factory, w["ch_a"], payload(50, "l"))
    assert large[0] <= 3 and large[1] <= 3, large
    assert large == small, (small, large)


@pytest.mark.parametrize("obj", ["page", "instagram"])
def test_lookups_do_not_grow_with_the_number_of_page_entries(session_factory, obj):
    n = next(_seq)
    ctype = "FACEBOOK" if obj == "page" else "INSTAGRAM"
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, channel_type=ctype, account=f"acct-q-{n}")

    def payload(count, tag):
        entries = [_page_entry(f"acct-none-{tag}-{i}-{n}", f"psid-{i}", f"m.q-{tag}-{i}-{n}") for i in range(count - 1)]
        entries.append(_page_entry(f"acct-q-{n}", "psid-k", f"m.qk-{tag}-{n}"))
        return _page_payload(obj, *entries)

    small = _counted(session_factory, ch, payload(5, "s"))
    large = _counted(session_factory, ch, payload(50, "l"))
    assert large[0] <= 3 and large[1] <= 3, large
    assert large == small, (small, large)


# ── 3. split parts are minimal ───────────────────────────────────────────────
def _record_parts(monkeypatch):
    seen = []
    real = inbound_service.get_adapter

    def fake(channel_type):
        adapter = real(channel_type)
        orig = adapter.parse_inbound

        def rec(payload):
            seen.append(payload)
            return orig(payload)

        monkeypatch.setattr(adapter, "parse_inbound", rec)
        return adapter

    monkeypatch.setattr(inbound_service, "get_adapter", fake)
    return seen


def test_whatsapp_part_carries_only_object_and_its_one_change(session_factory, monkeypatch):
    w = _world(session_factory, two_tenants=False)
    seen = _record_parts(monkeypatch)
    c1 = _change(w["pa"], messages=[_in_msg(f"wamid.sp1-{w['n']}", "60000000121")])
    c2 = _change(w["pb"], messages=[_in_msg(f"wamid.sp2-{w['n']}", "60000000122")])
    payload = _wa([c1, c2])
    payload["extra_top_level"] = {"big": "x" * 1000}
    _process(session_factory, w["ch_a"], payload)
    assert len(seen) == 2
    for part, change in zip(seen, (c1, c2)):
        assert set(part.keys()) == {"object", "entry"}
        assert len(part["entry"]) == 1
        assert part["entry"][0]["id"] == payload["entry"][0]["id"]
        assert part["entry"][0]["changes"] == [change]


def test_page_part_carries_only_object_and_its_one_entry(session_factory, monkeypatch):
    n = next(_seq)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    ch_a = _channel(session_factory, DEFAULT_TENANT_ID, ws, channel_type="FACEBOOK", account=f"acct-sp-a-{n}")
    ch_b = _channel(session_factory, DEFAULT_TENANT_ID, ws, channel_type="FACEBOOK", account=f"acct-sp-b-{n}")
    seen = _record_parts(monkeypatch)
    e1, e2 = _page_entry(f"acct-sp-a-{n}", "p1", f"m.sp1-{n}"), _page_entry(f"acct-sp-b-{n}", "p2", f"m.sp2-{n}")
    payload = _page_payload("page", e1, e2)
    payload["extra_top_level"] = {"big": "x" * 1000}
    _process(session_factory, ch_a, payload)
    assert len(seen) == 2
    for part, entry in zip(seen, (e1, e2)):
        assert set(part.keys()) == {"object", "entry"}
        assert part["entry"] == [entry]


# ── 4. unmatched identifier, single part, is dropped ─────────────────────────
def _inbound_endpoint(session_factory, tenant_id, ws_id, channel_id):
    db = session_factory()
    try:
        db.add(WebhookEndpoint(
            tenant_id=tenant_id, workspace_id=ws_id, channel_id=channel_id, name="inb",
            url="https://hooks.example.com/inb", secret_encrypted="x",
            events_json=["message.inbound"], status="ACTIVE",
        ))
        db.commit()
    finally:
        db.close()


def _deliveries(session_factory):
    db = session_factory()
    try:
        return db.query(WebhookDelivery).count()
    finally:
        db.close()


def test_single_whatsapp_part_with_unmatched_number_is_not_sent_to_the_url_channel(session_factory):
    n = next(_seq)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    url_ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, pnid=f"pn-own-{n}")
    _inbound_endpoint(session_factory, DEFAULT_TENANT_ID, ws, url_ch)
    mid = f"wamid.um-{n}"
    _process(session_factory, url_ch, _wa([_change(f"pn-nobody-{n}", messages=[_in_msg(mid, "60000000131")])]))
    assert _msg_rows(session_factory, mid) == []
    assert _deliveries(session_factory) == 0


def test_single_whatsapp_part_for_a_trashed_number_is_dropped(session_factory):
    n = next(_seq)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    url_ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, pnid=f"pn-own2-{n}")
    gone = _channel(session_factory, DEFAULT_TENANT_ID, ws, pnid=f"pn-gone-{n}")
    db = session_factory()
    db.query(Channel).filter(Channel.id == gone).update({"is_trashed": True})
    db.commit()
    db.close()
    mid = f"wamid.tr-{n}"
    _process(session_factory, url_ch, _wa([_change(f"pn-gone-{n}", messages=[_in_msg(mid, "60000000132")])]))
    assert _msg_rows(session_factory, mid) == []


@pytest.mark.parametrize("obj", ["page", "instagram"])
def test_single_page_entry_with_unmatched_id_is_not_sent_to_the_url_channel(session_factory, obj):
    n = next(_seq)
    ctype = "FACEBOOK" if obj == "page" else "INSTAGRAM"
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    url_ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, channel_type=ctype, account=f"acct-own-{n}")
    mid = f"m.um-{n}"
    _process(session_factory, url_ch, _page_payload(obj, _page_entry(f"acct-nobody-{n}", "psid-u", mid)))
    assert _msg_rows(session_factory, mid) == []


# ── 5. legacy fallback kept for channels with no identifier ──────────────────
def test_whatsapp_url_channel_without_a_number_still_receives_unmatched_payloads(session_factory):
    n = next(_seq)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    url_ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, pnid=None)
    mid = f"wamid.lg-{n}"
    _process(session_factory, url_ch, _wa([_change(f"pn-elsewhere-{n}", messages=[_in_msg(mid, "60000000141")])]))
    assert _ok(_msg_rows(session_factory, mid), DEFAULT_TENANT_ID, url_ch)


@pytest.mark.parametrize("obj", ["page", "instagram"])
def test_page_url_channel_without_an_account_id_still_receives_unmatched_payloads(session_factory, obj):
    n = next(_seq)
    ctype = "FACEBOOK" if obj == "page" else "INSTAGRAM"
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    url_ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, channel_type=ctype, account=None)
    mid = f"m.lg-{n}"
    _process(session_factory, url_ch, _page_payload(obj, _page_entry(f"acct-elsewhere-{n}", "psid-l", mid)))
    assert _ok(_msg_rows(session_factory, mid), DEFAULT_TENANT_ID, url_ch)


# ── 6. trashed / other-type URL channel is never a fallback target ───────────
def test_trashed_url_channel_is_not_a_whatsapp_fallback_target(session_factory):
    n = next(_seq)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    url_ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, pnid=None)
    db = session_factory()
    db.query(Channel).filter(Channel.id == url_ch).update({"is_trashed": True})
    db.commit()
    db.close()
    mid = f"wamid.tf-{n}"
    value = {"messaging_product": "whatsapp", "contacts": [{"wa_id": "60000000151", "profile": {"name": "C"}}],
             "messages": [_in_msg(mid, "60000000151")]}
    _process(session_factory, url_ch, _wa([{"field": "messages", "value": value}]))
    assert _msg_rows(session_factory, mid) == []


def test_other_type_url_channel_is_not_a_whatsapp_fallback_target(session_factory):
    n = next(_seq)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    url_ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, channel_type="FACEBOOK", account=f"acct-ty-{n}")
    mid = f"wamid.ty-{n}"
    value = {"messaging_product": "whatsapp", "contacts": [{"wa_id": "60000000152", "profile": {"name": "C"}}],
             "messages": [_in_msg(mid, "60000000152")]}
    counters = _process(session_factory, url_ch, _wa([{"field": "messages", "value": value}]))
    assert _msg_rows(session_factory, mid) == []
    assert counters["messages"] == 0


# ── 7. template events route by WABA ─────────────────────────────────────────
def _template_world(session_factory):
    n = next(_seq)
    t1 = DEFAULT_TENANT_ID
    t2 = _tenant(session_factory, f"tpl-t2-{n}")
    ws1 = _workspace(session_factory, t1, default=True)
    ws2 = _workspace(session_factory, t2, default=True)
    ch1 = _channel(session_factory, t1, ws1, pnid=f"pn-tpl-a-{n}")
    ch2 = _channel(session_factory, t2, ws2, pnid=f"pn-tpl-b-{n}")
    waba1, waba2 = f"waba-tpl-a-{n}", f"waba-tpl-b-{n}"
    db = session_factory()
    ids = {}
    for key, tenant, ch, waba in (("a", t1, ch1, waba1), ("b", t2, ch2, waba2)):
        db.query(Channel).filter(Channel.id == ch).update({"waba_id": waba})
        row = WhatsappTemplate(tenant_id=tenant, channel_id=ch, name="order_update", language="en_US",
                               status="PENDING")
        db.add(row)
        db.flush()
        ids[key] = row.id
    db.commit()
    db.close()
    return {"n": n, "ch1": ch1, "ch2": ch2, "waba1": waba1, "waba2": waba2, "ids": ids}


def _tpl_status(session_factory, tid):
    db = session_factory()
    try:
        return db.get(WhatsappTemplate, tid).status
    finally:
        db.close()


def _tpl_event(waba, status="REJECTED"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": waba, "changes": [{"field": "message_template_status_update", "value": {
            "event": status, "message_template_name": "order_update",
            "message_template_language": "en_US", "reason": "INVALID_FORMAT"}}]}],
    }


def test_template_event_for_another_wabas_template_does_not_touch_the_url_channels_template(session_factory):
    w = _template_world(session_factory)
    _process(session_factory, w["ch1"], _tpl_event(w["waba2"]))
    assert _tpl_status(session_factory, w["ids"]["a"]) == "PENDING"
    assert _tpl_status(session_factory, w["ids"]["b"]) == "REJECTED"


def test_template_event_for_a_waba_no_channel_owns_changes_nothing(session_factory):
    w = _template_world(session_factory)
    _process(session_factory, w["ch1"], _tpl_event(f"waba-nobody-{w['n']}"))
    assert _tpl_status(session_factory, w["ids"]["a"]) == "PENDING"
    assert _tpl_status(session_factory, w["ids"]["b"]) == "PENDING"


# ── 8. body cap applied before the body is read ──────────────────────────────
def _cap():
    from modules.omnichannel.routers import webhooks

    return webhooks, webhooks.MAX_BODY_BYTES


def test_oversized_content_length_answers_413_without_reading_the_body(client, monkeypatch):
    from modules.omnichannel import worker

    queued = []
    monkeypatch.setattr(worker.process_inbound_webhook, "delay", lambda *a, **k: queued.append(a))
    _, cap = _cap()
    res = client.post(
        "/omnichannel/webhooks/chn-1",
        content=b"{}",
        headers={"Content-Length": str(cap + 1), "Content-Type": "application/json"},
    )
    assert res.status_code == 413
    assert queued == []


def test_streamed_body_over_the_cap_stops_reading_at_the_cap():
    webhooks, cap = _cap()
    chunk = b"x" * 65536
    total_chunks = (cap // len(chunk)) * 3
    consumed = {"n": 0}

    async def receive():
        if consumed["n"] >= total_chunks:
            return {"type": "http.request", "body": b"", "more_body": False}
        consumed["n"] += 1
        return {"type": "http.request", "body": chunk, "more_body": True}

    from starlette.requests import Request

    scope = {"type": "http", "method": "POST", "path": "/omnichannel/webhooks/chn-1",
             "headers": [(b"content-type", b"application/json")], "query_string": b""}
    request = Request(scope, receive)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        asyncio.run(webhooks.receive_webhook("chn-1", request))
    assert exc.value.status_code == 413
    assert consumed["n"] * len(chunk) <= cap + 2 * len(chunk)


def test_normal_signed_body_still_accepted_and_bad_signature_rejected(client, monkeypatch):
    import hashlib
    import hmac

    from app.config import settings
    from modules.omnichannel import worker

    monkeypatch.setattr(worker.process_inbound_webhook, "delay", lambda *a, **k: None)
    monkeypatch.setattr(settings, "meta_app_secret", "topsecret")
    body = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()
    good = hmac.new(b"topsecret", body, hashlib.sha256).hexdigest()
    ok = client.post("/omnichannel/webhooks/chn-1", content=body, headers={"X-Hub-Signature-256": f"sha256={good}"})
    bad = client.post("/omnichannel/webhooks/chn-1", content=body, headers={"X-Hub-Signature-256": "sha256=00"})
    assert ok.status_code == 200 and bad.status_code == 403


# ── 9. a template event inside a mixed batch routes by its own WABA ──────────
def _template_change(waba_unused=None, status="REJECTED"):
    return {"field": "message_template_status_update", "value": {
        "event": status, "message_template_name": "order_update",
        "message_template_language": "en_US", "reason": "INVALID_FORMAT"}}


def test_mixed_batch_template_event_routes_by_its_waba_not_the_first_number(session_factory):
    w = _template_world(session_factory)
    db = session_factory()
    pn_b = db.get(Channel, w["ch2"]).phone_number_id
    db.close()
    mid = f"wamid.mx1-{w['n']}"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {"id": w["waba2"], "changes": [_change(pn_b, messages=[_in_msg(mid, "60000000161")])]},
            {"id": w["waba1"], "changes": [_template_change()]},
        ],
    }
    _process(session_factory, w["ch1"], payload)
    assert _ok(_msg_rows(session_factory, mid), w["ch2"] and _tenant_of(session_factory, w["ch2"]), w["ch2"])
    assert _tpl_status(session_factory, w["ids"]["a"]) == "REJECTED"
    assert _tpl_status(session_factory, w["ids"]["b"]) == "PENDING"


def test_mixed_batch_template_event_is_not_dropped_for_lacking_a_number(session_factory):
    w = _template_world(session_factory)
    db = session_factory()
    pn_a = db.get(Channel, w["ch1"]).phone_number_id
    db.close()
    mid = f"wamid.mx2-{w['n']}"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {"id": w["waba1"], "changes": [_change(pn_a, messages=[_in_msg(mid, "60000000162")])]},
            {"id": w["waba2"], "changes": [_template_change()]},
        ],
    }
    _process(session_factory, w["ch1"], payload)
    assert _tpl_status(session_factory, w["ids"]["b"]) == "REJECTED"
    assert _tpl_status(session_factory, w["ids"]["a"]) == "PENDING"


def _tenant_of(session_factory, channel_id):
    db = session_factory()
    try:
        return db.get(Channel, channel_id).tenant_id
    finally:
        db.close()


# ── 10. counters are summed across parts ─────────────────────────────────────
def test_counters_are_summed_across_parts(session_factory):
    from tests.test_omnichannel_inbound_batched_entries import _sent_message, _status

    w = _world(session_factory, two_tenants=False)
    wb = f"wamid.cs-{w['n']}"
    _sent_message(session_factory, w["t1"], w["ws_b"], w["ch_b"], wb, "60000000171")
    payload = _wa([
        _change(w["pa"], messages=[_in_msg(f"wamid.c1-{w['n']}", "60000000172"),
                                   _in_msg(f"wamid.c2-{w['n']}", "60000000173")]),
        _change(w["pb"], statuses_=[_status(wb)]),
    ])
    counters = _process(session_factory, w["ch_a"], payload)
    assert counters["messages"] == 2
    assert counters["statuses"] == 1


# ── 11. routing does not depend on how many parts the POST has ───────────────
def test_same_unmatched_number_in_two_changes_is_dropped_like_a_single_one(session_factory):
    n = next(_seq)
    ws = _workspace(session_factory, DEFAULT_TENANT_ID, default=True)
    url_ch = _channel(session_factory, DEFAULT_TENANT_ID, ws, pnid=f"pn-own3-{n}")
    m1, m2 = f"wamid.s1-{n}", f"wamid.s2-{n}"
    nobody = f"pn-nobody2-{n}"
    _process(session_factory, url_ch, _wa([
        _change(nobody, messages=[_in_msg(m1, "60000000181")]),
        _change(nobody, messages=[_in_msg(m2, "60000000182")]),
    ]))
    assert _msg_rows(session_factory, m1) == [] and _msg_rows(session_factory, m2) == []
