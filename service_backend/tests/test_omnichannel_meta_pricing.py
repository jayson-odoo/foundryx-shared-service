"""Plan 56 section B - Meta pricing per message (AC-56-20..28).

RED tests written BEFORE the implementation. Black box: signed-equivalent
WhatsApp ``statuses[]`` payloads through ``InboundService.process_payload``, the
consumer ``message.status`` webhook rows, ``run_send`` for the send-side events,
and the API-key GET routes. No private helper of the unwritten code is used.

Seams the implementation must honour:
* stored shape: ``metadata_json["pricing"] == {"billable": bool|None,
  "pricingModel": str|None, "category": str|None, "type": str|None}``;
* wire: ``pricing`` (that object or null) on ``message.status`` ``data`` (receipt
  AND send-side SENT/FAILED builders) and on the default ``MessageItem`` (list and
  single GET); never on the rio shape.

Every test seeds its own channel / contact / key / endpoint. Fake values only.
"""
from pathlib import Path

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import ConversationMessage
from modules.omnichannel.services import idempotency
from modules.omnichannel.services import webhook_delivery as wd
from tests.test_omnichannel_outbound_event import (
    _api_text,
    _external_id,
    _provider_error,
    _rig,
    _status_rows,
)
from tests.test_omnichannel_webhooks import _process, _wa_payload

REPO_ROOT = Path(__file__).resolve().parents[2]
META = {"billable": True, "pricing_model": "PMP", "category": "utility", "type": "regular"}
STORED = {"billable": True, "pricingModel": "pmp", "category": "utility", "type": "regular"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    idempotency.set_store(idempotency.MemoryIdempotencyStore())

    class _Resp:
        status_code = 200

    monkeypatch.setattr(wd, "_post", lambda *a, **k: _Resp())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


# ── helpers ──────────────────────────────────────────────────────────────────
def _sent(client, session_factory, phone):
    """A rig with a message.status endpoint and one API-sent (SENT) message."""
    r = _rig(client, session_factory, phone, events=("message.status",))
    res = _api_text(client, r["hdr"], phone)
    assert res.status_code == 202, res.text
    mid = res.json()["id"]
    ext = _external_id(session_factory, mid)
    assert ext
    return r, mid, ext


def _receipt(session_factory, r, ext, status, **entry):
    item = {"id": ext, "status": status, "timestamp": "1717550001", **entry}
    return _process(session_factory, r["channel_id"], _wa_payload(statuses=[item]))


def _meta_row(session_factory, mid):
    db = session_factory()
    try:
        return dict(db.query(ConversationMessage).filter(ConversationMessage.id == mid).one().metadata_json or {})
    finally:
        db.close()


def _items(client, r):
    res = client.get(f"/api/v1/omnichannel/contacts/{r['cid']}/messages", headers=r["hdr"])
    assert res.status_code == 200, res.text
    return res.json()["data"]


def _item(client, r, mid):
    found = [m for m in _items(client, r) if m["id"] == mid]
    assert len(found) == 1
    return found[0]


def _data(session_factory, mid, suffix):
    rows = [x for x in _status_rows(session_factory, mid) if x["event_id"] == f"{mid}:{suffix}"]
    assert len(rows) == 1, [x["event_id"] for x in _status_rows(session_factory, mid)]
    return rows[0]["payload"]["data"]


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-20 - stored under metadata_json["pricing"], other keys kept
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_20_receipt_pricing_is_stored_normalised(client, session_factory):
    r, mid, ext = _sent(client, session_factory, "+60100000101")
    _receipt(session_factory, r, ext, "delivered", pricing=META)
    assert _meta_row(session_factory, mid)["pricing"] == STORED


def test_ac_56_20_other_metadata_keys_are_kept(client, session_factory):
    r, mid, ext = _sent(client, session_factory, "+60100000102")
    db = session_factory()
    try:
        row = db.query(ConversationMessage).filter(ConversationMessage.id == mid).one()
        row.metadata_json = {"reply_to": "m-1", "broadcast": {"id": "b-1"}, "message_tag": "T"}
        db.commit()
    finally:
        db.close()
    _receipt(session_factory, r, ext, "delivered", pricing=META)
    meta = _meta_row(session_factory, mid)
    assert meta["pricing"] == STORED
    assert meta["reply_to"] == "m-1" and meta["broadcast"] == {"id": "b-1"} and meta["message_tag"] == "T"


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-21 - message.status webhook carries pricing (receipt + send-side)
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_21_receipt_webhook_carries_the_same_pricing_object(client, session_factory):
    r, mid, ext = _sent(client, session_factory, "+60100000111")
    _receipt(session_factory, r, ext, "delivered", pricing=META)
    assert _data(session_factory, mid, "DELIVERED")["pricing"] == STORED


def test_ac_56_21_receipt_webhook_without_pricing_carries_null_key(client, session_factory):
    r, mid, ext = _sent(client, session_factory, "+60100000112")
    _receipt(session_factory, r, ext, "delivered")
    data = _data(session_factory, mid, "DELIVERED")
    assert "pricing" in data and data["pricing"] is None


def test_ac_56_21_send_side_sent_event_carries_pricing_key(client, session_factory):
    _r, mid, _ext = _sent(client, session_factory, "+60100000113")
    data = _data(session_factory, mid, "SENT")
    assert "pricing" in data and data["pricing"] is None


def test_ac_56_21_later_status_without_pricing_still_carries_the_stored_one(client, session_factory):
    r, mid, ext = _sent(client, session_factory, "+60100000114")
    _receipt(session_factory, r, ext, "delivered", pricing=META)
    _receipt(session_factory, r, ext, "read")  # no pricing on this entry
    assert _data(session_factory, mid, "READ")["pricing"] == STORED


def _queued_with_pricing(session_factory, r):
    db = session_factory()
    try:
        row = ConversationMessage(
            tenant_id=DEFAULT_TENANT_ID, contact_id=r["cid"], channel_id=r["channel_id"],
            sender_type="AGENT", message_type="TEXT", body="hi", delivery_status="QUEUED",
            metadata_json={"pricing": dict(STORED)},
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _swap_adapter(monkeypatch, exc=None):
    class _A:
        def upload_media(self, *a, **k):
            return "media-fake"

        def send(self, *a, **k):
            if exc is not None:
                raise exc
            return {"external_message_id": "wamid.fake-pricing"}

    monkeypatch.setattr("modules.omnichannel.services.send_runner.get_adapter", lambda *a, **k: _A())


@pytest.mark.parametrize("outcome", ["SENT", "FAILED"])
def test_ac_56_21_send_side_events_carry_the_stored_pricing(client, session_factory, monkeypatch, outcome):
    from modules.omnichannel.services.send_runner import run_send

    r = _rig(client, session_factory, f"+6010000012{len(outcome)}", events=("message.status",))
    mid = _queued_with_pricing(session_factory, r)
    _swap_adapter(monkeypatch, _provider_error("bad number", code="131026") if outcome == "FAILED" else None)
    db = session_factory()
    try:
        assert run_send(db, mid) == outcome
    finally:
        db.close()
    assert _data(session_factory, mid, outcome)["pricing"] == STORED


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-22 - MessageItem default shape has pricing, rio has none
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_22_list_get_returns_pricing_object_and_null(client, session_factory):
    r, mid, ext = _sent(client, session_factory, "+60100000131")
    other = _api_text(client, r["hdr"], "+60100000131", body="second").json()["id"]
    _receipt(session_factory, r, ext, "delivered", pricing=META)
    items = _items(client, r)
    assert all("pricing" in m for m in items)
    assert next(m for m in items if m["id"] == mid)["pricing"] == STORED
    assert next(m for m in items if m["id"] == other)["pricing"] is None


def test_ac_56_22_single_message_get_returns_pricing(client, session_factory):
    r, mid, ext = _sent(client, session_factory, "+60100000132")
    _receipt(session_factory, r, ext, "delivered", pricing=META)
    res = client.get(f"/api/v1/omnichannel/contacts/{r['cid']}/messages/{mid}", headers=r["hdr"])
    assert res.status_code == 200, res.text
    assert res.json()["pricing"] == STORED


def test_ac_56_22_rio_shape_has_no_pricing_key(client, session_factory):
    r, mid, ext = _sent(client, session_factory, "+60100000133")
    _receipt(session_factory, r, ext, "delivered", pricing=META)
    assert _item(client, r, mid)["pricing"] == STORED  # control: it IS stored and visible by default
    lst = client.get(f"/api/v1/omnichannel/contacts/{r['cid']}/messages?format=rio", headers=r["hdr"])
    one = client.get(f"/api/v1/omnichannel/contacts/{r['cid']}/messages/{mid}?format=rio", headers=r["hdr"])
    assert lst.status_code == 200 and one.status_code == 200
    assert "pricing" not in lst.text and "pricing" not in one.text


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-23 - a receipt that does not advance still stores + commits pricing
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_23_late_sent_after_delivered_stores_pricing_and_sends_no_webhook(client, session_factory):
    r, mid, ext = _sent(client, session_factory, "+60100000141")
    _receipt(session_factory, r, ext, "delivered")
    before = sorted(x["event_id"] for x in _status_rows(session_factory, mid))
    assert before == sorted([f"{mid}:SENT", f"{mid}:DELIVERED"])
    _receipt(session_factory, r, ext, "sent", pricing=META)  # backward: status must not move
    assert _meta_row(session_factory, mid)["pricing"] == STORED  # committed (read on a fresh session)
    assert sorted(x["event_id"] for x in _status_rows(session_factory, mid)) == before
    assert _item(client, r, mid)["pricing"] == STORED
    assert _item(client, r, mid)["deliveryStatus"] == "DELIVERED"


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-24 - latest non-null wins, absence never clears
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_24_latest_non_null_wins_and_absent_never_clears(client, session_factory):
    r, mid, ext = _sent(client, session_factory, "+60100000151")
    _receipt(session_factory, r, ext, "delivered", pricing=META)
    second = {"billable": False, "pricing_model": "CBP", "category": "marketing", "type": "free_customer_service"}
    _receipt(session_factory, r, ext, "read", pricing=second)
    expected = {"billable": False, "pricingModel": "cbp", "category": "marketing", "type": "free_customer_service"}
    assert _meta_row(session_factory, mid)["pricing"] == expected
    _receipt(session_factory, r, ext, "read")  # nothing new, no pricing
    _receipt(session_factory, r, ext, "delivered", pricing=None)  # explicit null never clears
    assert _meta_row(session_factory, mid)["pricing"] == expected


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-25 - sanitisation, never a webhook failure
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "bad",
    [123, "x" * 41, "has space", "UPPER-dash", "a/b", ["list"], {"o": 1}, "", None],
    ids=["int", "long", "space", "dash", "slash", "list", "dict", "empty", "null"],
)
@pytest.mark.parametrize("field", ["pricing_model", "category", "type"])
def test_ac_56_25_invalid_string_field_is_null_others_survive(client, session_factory, field, bad):
    r, mid, ext = _sent(client, session_factory, "+60100000161")
    pricing = {**META, field: bad}
    res = _receipt(session_factory, r, ext, "delivered", pricing=pricing)
    key = {"pricing_model": "pricingModel"}.get(field, field)
    stored = _meta_row(session_factory, mid)["pricing"]
    assert stored[key] is None, stored
    assert stored["billable"] is True  # the valid siblings are kept
    assert res is not None


def test_ac_56_25_valid_strings_are_lowercased_and_forty_chars_allowed(client, session_factory):
    r, mid, ext = _sent(client, session_factory, "+60100000162")
    _receipt(session_factory, r, ext, "delivered",
             pricing={**META, "category": "Utility_2", "type": "a" * 40})
    stored = _meta_row(session_factory, mid)["pricing"]
    assert stored["category"] == "utility_2" and stored["type"] == "a" * 40


@pytest.mark.parametrize("bad", ["true", 1, 0, None, "yes", [True]])
def test_ac_56_25_billable_that_is_not_a_json_bool_is_null(client, session_factory, bad):
    r, mid, ext = _sent(client, session_factory, "+60100000163")
    _receipt(session_factory, r, ext, "delivered", pricing={**META, "billable": bad})
    stored = _meta_row(session_factory, mid)["pricing"]
    assert stored["billable"] is None and stored["category"] == "utility"


@pytest.mark.parametrize("bad", ["free", 5, ["x"], True])
def test_ac_56_25_non_object_pricing_stores_nothing_and_does_not_fail(client, session_factory, bad):
    r, mid, ext = _sent(client, session_factory, "+60100000164")
    _receipt(session_factory, r, ext, "delivered", pricing=bad)
    assert _meta_row(session_factory, mid).get("pricing") is None
    assert _item(client, r, mid)["pricing"] is None
    assert _item(client, r, mid)["deliveryStatus"] == "DELIVERED"  # the receipt itself still applied


def test_ac_56_25_unknown_keys_are_dropped(client, session_factory):
    r, mid, ext = _sent(client, session_factory, "+60100000165")
    _receipt(session_factory, r, ext, "delivered",
             pricing={**META, "tier": "gold", "extra": {"a": 1}, "conversation": "x"})
    assert _meta_row(session_factory, mid)["pricing"] == STORED
    assert set(_data(session_factory, mid, "DELIVERED")["pricing"]) == set(STORED)


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-26 - inbound and older messages answer null
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_26_inbound_and_pre_change_messages_answer_null(client, session_factory):
    phone = "+60100000171"
    r, mid, _ext = _sent(client, session_factory, phone)
    _process(session_factory, r["channel_id"],
             _wa_payload(wamid="wamid.in-56-pricing", from_=phone.lstrip("+"), text="hello"))
    items = _items(client, r)
    inbound = [m for m in items if m["senderType"] == "CONTACT"]
    assert inbound, "control: the inbound message must be listed"
    assert all("pricing" in m and m["pricing"] is None for m in items)


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-27 - tenant scoping
# ═════════════════════════════════════════════════════════════════════════════
def test_ac_56_27_foreign_tenant_message_is_never_written_by_our_channels_webhook(client, session_factory):
    r, mid, ext = _sent(client, session_factory, "+60100000181")
    db = session_factory()
    try:
        foreign = ConversationMessage(
            tenant_id="other-tenant-id", contact_id=r["cid"], channel_id=r["channel_id"],
            sender_type="AGENT", message_type="TEXT", body="foreign", delivery_status="SENT",
            external_message_id="wamid.foreign-56",
        )
        db.add(foreign)
        db.commit()
        foreign_id = foreign.id
    finally:
        db.close()
    # a status entry on OUR channel that names the foreign tenant's wamid
    _receipt(session_factory, r, "wamid.foreign-56", "delivered", pricing=META)
    foreign_meta = _meta_row(session_factory, foreign_id)
    assert "pricing" not in foreign_meta
    db = session_factory()
    try:
        assert db.query(ConversationMessage).filter(ConversationMessage.id == foreign_id).one().delivery_status == "SENT"
    finally:
        db.close()
    # control: the same webhook path does write pricing on our own message
    _receipt(session_factory, r, ext, "delivered", pricing=META)
    assert _meta_row(session_factory, mid)["pricing"] == STORED


# ═════════════════════════════════════════════════════════════════════════════
# AC-56-28 - consumer guide (read lazily)
# ═════════════════════════════════════════════════════════════════════════════
def _guide() -> str:
    return (REPO_ROOT / "documentation/omnichannel/consumer-integration-guide.md").read_text()


def test_ac_56_28_message_status_section_documents_pricing():
    guide = _guide()
    i = guide.index("* `**message.status**`")
    window = guide[i : i + 6000]
    assert "pricing" in window and "pricingModel" in window
    assert "billable" in window and "null" in window


def test_ac_56_28_message_item_section_lists_pricing():
    guide = _guide()
    sec = guide[guide.index("### 9.1 Default shapes") : guide.index("### 9.2")]
    assert "pricing" in sec and "pricingModel" in sec


def test_ac_56_28_field_map_says_rio_has_no_pricing():
    guide = _guide()
    sec = guide[guide.index("### 9.3 Field map") :]
    sec = sec.split("\n## ", 1)[0]
    lines = [ln.lower() for ln in sec.splitlines() if "pricing" in ln.lower()]
    assert lines, "9.3 must list pricing"
    assert any(k in ln for ln in lines for k in ("none", "no equivalent", "not in", "no `pricing`")), lines


def test_ac_56_28_changelog_row_mentions_pricing_and_templates_category():
    guide = _guide()
    head = guide.split("## 1. The big picture")[0]
    rows = [ln for ln in head.splitlines() if ln.startswith("> | **2026-") and "pricing" in ln.lower()]
    assert rows, "changelog needs a pricing row"
    assert any("templates" in ln.lower() and "category" in ln.lower() for ln in rows), rows
    assert any("null" in ln.lower() for ln in rows), "row must say older messages answer null"
