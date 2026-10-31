"""Plan 38 gap 1 - `GET /api/v1/omnichannel/channels` (AC-38-20..26).

RED tests written before the route exists. Everything is asserted at the HTTP
route (plus the already-existing `POST /messages` for the isDefault parity
check). Every test seeds its own channels; numbers are obvious fakes.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import Channel, ConversationMessage
from modules.omnichannel.security import encrypt_credentials
from modules.omnichannel.services import idempotency, statuses
from tests.test_omnichannel_api_gateway import (
    _default_workspace_id,
    _mint,
    _seed_open_contact,
    _seed_second_workspace,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDE = REPO_ROOT / "documentation/omnichannel/consumer-integration-guide.md"
ROUTE = "/api/v1/omnichannel/channels"
ITEM_KEYS = {
    "id",
    "channelType",
    "name",
    "status",
    "isActive",
    "isDefault",
    "displayPhoneNumber",
    "verifiedName",
    "createdAt",
}
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


def _channel(
    session_factory,
    ws,
    *,
    name,
    age_rank,
    channel_type="WHATSAPP",
    active=True,
    status_key="ACTIVE",
    trashed=False,
    tenant_id=DEFAULT_TENANT_ID,
    pn=None,
):
    """`age_rank` 0 = oldest. Inserted in whatever order the caller chooses."""
    db = session_factory()
    try:
        ch = Channel(
            tenant_id=tenant_id,
            workspace_id=ws,
            channel_type=channel_type,
            name=name,
            credentials_json=encrypt_credentials({"dev": True}),
            waba_id=f"waba-{name}" if channel_type == "WHATSAPP" else None,
            phone_number_id=pn or (f"pn-{name}" if channel_type == "WHATSAPP" else None),
            external_account_id=f"ext-{name}" if channel_type == "FACEBOOK" else None,
            display_phone_number="+60 11-111 0000" if channel_type == "WHATSAPP" else None,
            verified_name=f"Verified {name}" if channel_type == "WHATSAPP" else None,
            is_active=active,
            is_trashed=trashed,
            status_id=statuses.status_id_for(db, tenant_id, "CHANNEL", status_key),
            created_at=T0 + timedelta(days=age_rank),
        )
        db.add(ch)
        db.commit()
        return ch.id
    finally:
        db.close()


def _hdr(client, ws):
    return {"Authorization": f"Bearer {_mint(client, ws).json()['fullKey']}"}


def _list(client, hdr):
    r = client.get(ROUTE, headers=hdr)
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ── AC-38-20 ─────────────────────────────────────────────────────────────────
def test_ac_38_20_lists_workspace_channels_oldest_first(client, session_factory):
    ws = _default_workspace_id(session_factory)
    newer = _channel(session_factory, ws, name="newer", age_rank=5)
    older = _channel(session_factory, ws, name="older", age_rank=1)
    hdr = _hdr(client, ws)
    items = _list(client, hdr)
    assert [i["id"] for i in items] == [older, newer]


# ── AC-38-21 ─────────────────────────────────────────────────────────────────
def test_ac_38_21_item_has_exactly_the_documented_keys(client, session_factory):
    ws = _default_workspace_id(session_factory)
    cid = _channel(session_factory, ws, name="solo", age_rank=1)
    # control: the fixture channel really carries the internal values that must be filtered
    db = session_factory()
    row = db.query(Channel).filter(Channel.id == cid).first()
    assert row.waba_id and row.phone_number_id and row.credentials_json
    db.close()

    items = _list(client, _hdr(client, ws))
    assert len(items) == 1
    item = items[0]
    assert set(item.keys()) == ITEM_KEYS
    assert item["id"] == cid and item["name"] == "solo"
    assert item["channelType"] == "WHATSAPP"
    assert item["status"] == "ACTIVE" and item["isActive"] is True
    assert item["displayPhoneNumber"] == "+60 11-111 0000"
    assert item["verifiedName"] == "Verified solo"
    assert item["createdAt"].endswith("Z")
    assert "waba-solo" not in str(items) and "pn-solo" not in str(items)


# ── AC-38-22 ─────────────────────────────────────────────────────────────────
def _post_without_channel_id(client, hdr, phone):
    return client.post(
        ROUTE.replace("/channels", "/messages"),
        json={"to": phone, "type": "text", "text": {"body": "which channel"}},
        headers=hdr,
    )


def _sent_channel_id(session_factory, message_id):
    db = session_factory()
    try:
        return db.query(ConversationMessage).filter(ConversationMessage.id == message_id).first().channel_id
    finally:
        db.close()


def test_ac_38_22_is_default_matches_the_channel_post_messages_uses(client, session_factory):
    ws = _default_workspace_id(session_factory)
    # An OLDER Messenger channel and a NEWER WhatsApp one: WhatsApp is preferred.
    fb = _channel(session_factory, ws, name="fbold", age_rank=1, channel_type="FACEBOOK")
    wa = _channel(session_factory, ws, name="wanew", age_rank=2)
    _seed_open_contact(session_factory, ws, phone="+60381000001", open_window=True)
    hdr = _hdr(client, ws)

    sent = _post_without_channel_id(client, hdr, "+60381000001")
    assert sent.status_code == 202, sent.text
    used = _sent_channel_id(session_factory, sent.json()["id"])
    assert used == wa  # control: the real send went out on the WhatsApp channel

    flags = {i["id"]: i["isDefault"] for i in _list(client, hdr)}
    assert flags == {fb: False, wa: True}
    assert [k for k, v in flags.items() if v] == [used]


def test_ac_38_22_older_inactive_whatsapp_is_not_the_default(client, session_factory):
    ws = _default_workspace_id(session_factory)
    dead = _channel(session_factory, ws, name="deadwa", age_rank=1, active=False, status_key="INACTIVE")
    live = _channel(session_factory, ws, name="livewa", age_rank=2)
    _seed_open_contact(session_factory, ws, phone="+60381000002", open_window=True)
    hdr = _hdr(client, ws)
    sent = _post_without_channel_id(client, hdr, "+60381000002")
    assert sent.status_code == 202, sent.text
    assert _sent_channel_id(session_factory, sent.json()["id"]) == live
    flags = {i["id"]: i["isDefault"] for i in _list(client, hdr)}
    assert flags == {dead: False, live: True}


def test_ac_38_22_no_active_channel_means_none_is_default(client, session_factory):
    ws = _default_workspace_id(session_factory)
    only = _channel(session_factory, ws, name="offwa", age_rank=1, active=False, status_key="INACTIVE")
    hdr = _hdr(client, ws)
    sent = _post_without_channel_id(client, hdr, "+60381000003")
    assert sent.status_code == 409  # control: send really has no default channel
    assert sent.json()["error"]["code"] == "no_active_channel"
    items = _list(client, hdr)
    assert [i["id"] for i in items] == [only]
    assert items[0]["isDefault"] is False


# ── AC-38-23 ─────────────────────────────────────────────────────────────────
def test_ac_38_23_inactive_listed_with_real_status_trashed_hidden(client, session_factory):
    ws = _default_workspace_id(session_factory)
    live = _channel(session_factory, ws, name="okwa", age_rank=1)
    broken = _channel(session_factory, ws, name="errwa", age_rank=2, active=False, status_key="ERROR")
    gone = _channel(session_factory, ws, name="trashwa", age_rank=3, trashed=True)
    # control: the trashed channel exists in the DB
    db = session_factory()
    assert db.query(Channel).filter(Channel.id == gone).count() == 1
    db.close()

    by_id = {i["id"]: i for i in _list(client, _hdr(client, ws))}
    assert set(by_id) == {live, broken}
    assert by_id[broken]["status"] == "ERROR" and by_id[broken]["isActive"] is False
    assert by_id[live]["status"] == "ACTIVE" and by_id[live]["isActive"] is True


# ── AC-38-24 ─────────────────────────────────────────────────────────────────
def test_ac_38_24_other_workspace_and_other_tenant_channels_never_appear(client, session_factory):
    ws = _default_workspace_id(session_factory)
    mine = _channel(session_factory, ws, name="mine", age_rank=1)
    other_ws = _seed_second_workspace(session_factory)
    foreign_tenant = _channel(
        session_factory, "other-tenant-ws", name="alien", age_rank=1, tenant_id="other-tenant-id"
    )
    # control: both foreign channels really exist
    db = session_factory()
    assert db.query(Channel).filter(Channel.workspace_id == other_ws).count() >= 1
    assert db.query(Channel).filter(Channel.id == foreign_tenant).count() == 1
    db.close()

    ids = [i["id"] for i in _list(client, _hdr(client, ws))]
    assert ids == [mine]


@pytest.mark.parametrize("auth", [None, "Bearer nope", "Bearer fxw_live_deadbeef"])
def test_ac_38_24_missing_or_invalid_key_matches_a_neighbouring_route(client, session_factory, auth):
    headers = {"Authorization": auth} if auth else {}
    neighbour = client.get("/api/v1/omnichannel/templates", headers=headers)
    mine = client.get(ROUTE, headers=headers)
    assert neighbour.status_code == 401  # control
    assert mine.status_code == neighbour.status_code
    assert mine.json() == neighbour.json()


def test_ac_38_24_inactive_module_matches_a_neighbouring_route(client, session_factory):
    from app.services.app_store_service import AppStoreService

    ws = _default_workspace_id(session_factory)
    _channel(session_factory, ws, name="modwa", age_rank=1)
    hdr = _hdr(client, ws)
    db = session_factory()
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
    db.close()
    neighbour = client.get("/api/v1/omnichannel/templates", headers=hdr)
    mine = client.get(ROUTE, headers=hdr)
    assert neighbour.status_code == 403  # control
    assert mine.status_code == neighbour.status_code
    assert mine.json() == neighbour.json()


# ── AC-38-26 ─────────────────────────────────────────────────────────────────
def test_ac_38_26_guide_documents_the_route_is_default_and_changelog():
    text = GUIDE.read_text()
    assert "GET /api/v1/omnichannel/channels" in text or "GET /channels" in text
    assert "isDefault" in text
    changelog = [ln for ln in text.splitlines()[:40] if ln.startswith("> |")]
    assert any("/channels" in ln for ln in changelog), "changelog needs a row for GET /channels"
    assert "without `channelId`" in text or "omit" in text.lower()
