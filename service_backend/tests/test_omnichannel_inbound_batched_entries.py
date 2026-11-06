"""Inbound webhooks route EACH batched entry/change to the channel its own
metadata names (WhatsApp: ``changes[].value.metadata.phone_number_id``;
Messenger/Instagram: ``entry[].id``), with the module-active check per resolved
channel's tenant. One POST may batch several numbers/pages, possibly of
different workspaces or tenants.

RED tests written BEFORE the implementation. Black box through
``InboundService.process_payload`` and the stored rows / delivery rows.
Every test seeds its own tenants, workspaces, channels, contacts, endpoints.
Fake ids only.

Not covered (by design): template review/quality/category events carry no
phone number id (only the WABA entry id), so there is no cheap per-entry
channel key to pin for them.
"""
import itertools

import fakeredis
import pytest

from app.models import DEFAULT_TENANT_ID, Tenant
from modules.omnichannel.models import (
    Channel,
    Contact,
    ConversationMessage,
    WebhookDelivery,
    WebhookEndpoint,
    Workspace,
)
from modules.omnichannel.security import encrypt_credentials
from modules.omnichannel.services import idempotency, realtime, statuses
from modules.omnichannel.services import webhook_delivery as wd

_seq = itertools.count(1)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    realtime.set_client(fakeredis.FakeRedis(decode_responses=True))
    idempotency.set_store(idempotency.MemoryIdempotencyStore())

    class _Resp:
        status_code = 200

    monkeypatch.setattr(wd, "_post", lambda *a, **k: _Resp())
    yield
    realtime.set_client(None)
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


# ── seeding helpers ──────────────────────────────────────────────────────────
def _process(session_factory, channel_id, payload):
    from modules.omnichannel.services.inbound_service import InboundService

    db = session_factory()
    try:
        return InboundService(db).process_payload(channel_id, payload)
    finally:
        db.close()


def _tenant(session_factory, slug):
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    db = session_factory()
    tenant = TenantService(db).provision(
        name=f"Tenant {slug}", slug=slug, admin_email=f"admin-{slug}@example.com",
        admin_password="Password123!", admin_name="Admin",
    )
    db.flush()
    AppStoreService(db).install(tenant.id, "omnichannel")
    db.commit()
    tid = tenant.id
    db.close()
    return tid


def _workspace(session_factory, tenant_id, *, default):
    db = session_factory()
    try:
        if default:
            ws = db.query(Workspace).filter(
                Workspace.tenant_id == tenant_id, Workspace.is_default.is_(True)
            ).first()
            return ws.id
        ws = Workspace(tenant_id=tenant_id, name=f"Second {next(_seq)}", is_default=False)
        db.add(ws)
        db.commit()
        return ws.id
    finally:
        db.close()


def _channel(session_factory, tenant_id, ws_id, *, channel_type="WHATSAPP", pnid=None, account=None):
    db = session_factory()
    try:
        ch = Channel(
            tenant_id=tenant_id,
            workspace_id=ws_id,
            channel_type=channel_type,
            name=f"Test {channel_type}",
            credentials_json=encrypt_credentials({"dev": True}),
            phone_number_id=pnid,
            external_account_id=account,
            is_active=True,
            status_id=statuses.status_id_for(db, tenant_id, "CHANNEL", "ACTIVE"),
        )
        db.add(ch)
        db.commit()
        return ch.id
    finally:
        db.close()


def _contact(session_factory, tenant_id, ws_id, phone):
    db = session_factory()
    try:
        c = Contact(
            tenant_id=tenant_id,
            workspace_id=ws_id,
            first_name="Sam",
            phone=phone,
            status_id=statuses.status_id_for(db, tenant_id, "THREAD", "OPEN"),
            priority="MEDIUM",
        )
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


def _sent_message(session_factory, tenant_id, ws_id, channel_id, wamid, phone):
    """An outbound message already sent on `channel_id`, awaiting receipts."""
    cid = _contact(session_factory, tenant_id, ws_id, phone)
    db = session_factory()
    try:
        m = ConversationMessage(
            tenant_id=tenant_id,
            contact_id=cid,
            channel_id=channel_id,
            sender_type="AGENT",
            message_type="TEXT",
            body="out",
            external_message_id=wamid,
            delivery_status="SENT",
        )
        db.add(m)
        db.commit()
        return m.id
    finally:
        db.close()


def _endpoint(session_factory, tenant_id, ws_id, channel_id, name):
    db = session_factory()
    try:
        ep = WebhookEndpoint(
            tenant_id=tenant_id,
            workspace_id=ws_id,
            channel_id=channel_id,
            name=name,
            url=f"https://hooks.example.com/{name}",
            secret_encrypted="x",
            events_json=["message.status"],
            status="ACTIVE",
        )
        db.add(ep)
        db.commit()
        return ep.id
    finally:
        db.close()


def _stored(session_factory, wamid):
    db = session_factory()
    try:
        m = db.query(ConversationMessage).filter(ConversationMessage.external_message_id == wamid).all()
        return [(x.tenant_id, x.channel_id, x.delivery_status, x.metadata_json) for x in m]
    finally:
        db.close()


def _delivery_endpoints(session_factory, message_id):
    db = session_factory()
    try:
        rows = db.query(WebhookDelivery).filter(WebhookDelivery.event_type == "message.status").all()
        return {r.endpoint_id for r in rows if r.payload_json["data"]["messageId"] == message_id}
    finally:
        db.close()


def _in_msg(wamid, from_):
    return {
        "id": wamid, "from": from_, "timestamp": "1717550000", "type": "text",
        "text": {"body": "hi"},
    }


def _change(pnid, *, messages=None, statuses_=None):
    value = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": pnid}}
    if messages is not None:
        value["contacts"] = [{"wa_id": m["from"], "profile": {"name": "Cust"}} for m in messages]
        value["messages"] = messages
    if statuses_ is not None:
        value["statuses"] = statuses_
    return {"field": "messages", "value": value}


def _wa(*entries):
    """entries: list of lists of changes -> one entry each."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": f"waba-{i}", "changes": changes} for i, changes in enumerate(entries)],
    }


def _status(wamid, status="delivered", **extra):
    return {"id": wamid, "status": status, "timestamp": "1717550001", **extra}


def _world(session_factory, *, two_tenants):
    n = next(_seq)
    pa, pb = f"pn-batch-a-{n}", f"pn-batch-b-{n}"
    t1 = DEFAULT_TENANT_ID
    ws_a = _workspace(session_factory, t1, default=True)
    ch_a = _channel(session_factory, t1, ws_a, pnid=pa)
    if two_tenants:
        t2 = _tenant(session_factory, f"batch-t2-{n}")
        ws_b = _workspace(session_factory, t2, default=True)
    else:
        t2 = t1
        ws_b = _workspace(session_factory, t1, default=False)
    ch_b = _channel(session_factory, t2, ws_b, pnid=pb)
    return {"n": n, "pa": pa, "pb": pb, "t1": t1, "t2": t2, "ws_a": ws_a, "ws_b": ws_b, "ch_a": ch_a, "ch_b": ch_b}


def _msg_rows(session_factory, wamid):
    return _stored(session_factory, wamid)


# ── 1. batched messages, same tenant, two workspaces ─────────────────────────
@pytest.mark.parametrize("shape", ["two_changes_one_entry", "two_entries"])
def test_batched_messages_same_tenant_land_on_each_numbers_channel(session_factory, shape):
    w = _world(session_factory, two_tenants=False)
    m1, m2 = f"wamid.b1-{w['n']}", f"wamid.b2-{w['n']}"
    c1 = _change(w["pa"], messages=[_in_msg(m1, "60000000011")])
    c2 = _change(w["pb"], messages=[_in_msg(m2, "60000000012")])
    payload = _wa([c1, c2]) if shape == "two_changes_one_entry" else _wa([c1], [c2])
    _process(session_factory, w["ch_a"], payload)
    assert [(t, c) for t, c, *_ in _msg_rows(session_factory, m1)] == [(w["t1"], w["ch_a"])]
    assert [(t, c) for t, c, *_ in _msg_rows(session_factory, m2)] == [(w["t1"], w["ch_b"])]
    db = session_factory()
    try:
        contact_ws = {
            row.external_message_id: db.get(Contact, row.contact_id).workspace_id
            for row in db.query(ConversationMessage).filter(ConversationMessage.external_message_id.in_([m1, m2]))
        }
    finally:
        db.close()
    assert contact_ws == {m1: w["ws_a"], m2: w["ws_b"]}


# ── 2. batched messages, two tenants ─────────────────────────────────────────
def test_batched_messages_two_tenants_each_stored_under_its_own_tenant(session_factory):
    w = _world(session_factory, two_tenants=True)
    m1, m2 = f"wamid.t1-{w['n']}", f"wamid.t2-{w['n']}"
    payload = _wa([
        _change(w["pa"], messages=[_in_msg(m1, "60000000021")]),
        _change(w["pb"], messages=[_in_msg(m2, "60000000022")]),
    ])
    _process(session_factory, w["ch_a"], payload)
    assert [(t, c) for t, c, *_ in _msg_rows(session_factory, m1)] == [(w["t1"], w["ch_a"])]
    assert [(t, c) for t, c, *_ in _msg_rows(session_factory, m2)] == [(w["t2"], w["ch_b"])]


# ── 3. batched statuses, same tenant, two workspaces ─────────────────────────
def test_batched_statuses_same_tenant_update_each_message_and_notify_own_workspace(session_factory):
    w = _world(session_factory, two_tenants=False)
    wa, wb = f"wamid.sa-{w['n']}", f"wamid.sb-{w['n']}"
    ma = _sent_message(session_factory, w["t1"], w["ws_a"], w["ch_a"], wa, "60000000031")
    mb = _sent_message(session_factory, w["t1"], w["ws_b"], w["ch_b"], wb, "60000000032")
    ep_a = _endpoint(session_factory, w["t1"], w["ws_a"], w["ch_a"], f"a{w['n']}")
    ep_b = _endpoint(session_factory, w["t1"], w["ws_b"], w["ch_b"], f"b{w['n']}")
    payload = _wa([
        _change(w["pa"], statuses_=[_status(wa)]),
        _change(w["pb"], statuses_=[_status(wb)]),
    ])
    _process(session_factory, w["ch_a"], payload)
    assert _stored(session_factory, wa)[0][2] == "DELIVERED"
    assert _stored(session_factory, wb)[0][2] == "DELIVERED"
    assert _delivery_endpoints(session_factory, ma) == {ep_a}
    assert _delivery_endpoints(session_factory, mb) == {ep_b}


# ── 4. batched statuses, two tenants ─────────────────────────────────────────
def test_batched_statuses_two_tenants_update_each_under_its_own_tenant(session_factory):
    w = _world(session_factory, two_tenants=True)
    wa, wb = f"wamid.ta-{w['n']}", f"wamid.tb-{w['n']}"
    _sent_message(session_factory, w["t1"], w["ws_a"], w["ch_a"], wa, "60000000041")
    mb = _sent_message(session_factory, w["t2"], w["ws_b"], w["ch_b"], wb, "60000000042")
    ep_b = _endpoint(session_factory, w["t2"], w["ws_b"], w["ch_b"], f"t2b{w['n']}")
    payload = _wa([
        _change(w["pa"], statuses_=[_status(wa)]),
        _change(w["pb"], statuses_=[_status(wb)]),
    ])
    _process(session_factory, w["ch_a"], payload)
    assert _stored(session_factory, wa)[0][2] == "DELIVERED"
    assert _stored(session_factory, wb)[0][2] == "DELIVERED"
    assert _delivery_endpoints(session_factory, mb) == {ep_b}


# ── 5. pricing from a batched status lands on the right message only ─────────
def test_batched_status_pricing_lands_on_its_own_message_only(session_factory):
    w = _world(session_factory, two_tenants=True)
    wa, wb = f"wamid.pa-{w['n']}", f"wamid.pb-{w['n']}"
    _sent_message(session_factory, w["t1"], w["ws_a"], w["ch_a"], wa, "60000000051")
    _sent_message(session_factory, w["t2"], w["ws_b"], w["ch_b"], wb, "60000000052")
    meta = {"billable": True, "pricing_model": "PMP", "category": "utility", "type": "regular"}
    payload = _wa([
        _change(w["pa"], statuses_=[_status(wa)]),
        _change(w["pb"], statuses_=[_status(wb, pricing=meta)]),
    ])
    _process(session_factory, w["ch_a"], payload)
    assert "pricing" not in (_stored(session_factory, wa)[0][3] or {})
    assert (_stored(session_factory, wb)[0][3] or {}).get("pricing", {}).get("category") == "utility"


# ── 6. unknown number dropped alone ──────────────────────────────────────────
def test_unknown_number_is_dropped_and_the_rest_of_the_post_is_processed(session_factory):
    w = _world(session_factory, two_tenants=False)
    m_unknown, m_ok = f"wamid.u1-{w['n']}", f"wamid.u2-{w['n']}"
    payload = _wa([
        _change(f"pn-nobody-{w['n']}", messages=[_in_msg(m_unknown, "60000000061")]),
        _change(w["pb"], messages=[_in_msg(m_ok, "60000000062")]),
    ])
    # URL channel id is A's: an unmatched number must NOT fall back to it.
    _process(session_factory, w["ch_a"], payload)
    assert _msg_rows(session_factory, m_unknown) == []
    assert [(t, c) for t, c, *_ in _msg_rows(session_factory, m_ok)] == [(w["t1"], w["ch_b"])]


# ── 7. module inactive for one tenant ────────────────────────────────────────
def test_inactive_module_drops_only_that_tenants_change(session_factory):
    from app.services.app_store_service import AppStoreService

    w = _world(session_factory, two_tenants=True)
    db = session_factory()
    AppStoreService(db).deactivate(w["t2"], "omnichannel")
    db.commit()
    db.close()
    m1, m2 = f"wamid.i1-{w['n']}", f"wamid.i2-{w['n']}"
    payload = _wa([
        _change(w["pa"], messages=[_in_msg(m1, "60000000071")]),
        _change(w["pb"], messages=[_in_msg(m2, "60000000072")]),
    ])
    _process(session_factory, w["ch_a"], payload)
    assert [(t, c) for t, c, *_ in _msg_rows(session_factory, m1)] == [(w["t1"], w["ch_a"])]
    assert _msg_rows(session_factory, m2) == []


# ── 8. Messenger / Instagram batched entries ─────────────────────────────────
@pytest.mark.parametrize(
    "obj,ctype", [("page", "FACEBOOK"), ("instagram", "INSTAGRAM")]
)
def test_batched_page_entries_each_land_on_their_own_channel(session_factory, obj, ctype):
    n = next(_seq)
    t1 = DEFAULT_TENANT_ID
    ws_a = _workspace(session_factory, t1, default=True)
    ws_b = _workspace(session_factory, t1, default=False)
    acc_a, acc_b = f"acct-batch-a-{n}", f"acct-batch-b-{n}"
    ch_a = _channel(session_factory, t1, ws_a, channel_type=ctype, account=acc_a)
    ch_b = _channel(session_factory, t1, ws_b, channel_type=ctype, account=acc_b)

    def entry(account, psid, mid):
        return {
            "id": account,
            "time": 1717550000000,
            "messaging": [{
                "sender": {"id": psid},
                "recipient": {"id": account},
                "timestamp": 1717550000000,
                "message": {"mid": mid, "text": "hello"},
            }],
        }

    m1, m2 = f"m.pg1-{n}", f"m.pg2-{n}"
    payload = {"object": obj, "entry": [entry(acc_a, f"psid-a-{n}", m1), entry(acc_b, f"psid-b-{n}", m2)]}
    _process(session_factory, ch_a, payload)
    assert [(t, c) for t, c, *_ in _msg_rows(session_factory, m1)] == [(t1, ch_a)]
    assert [(t, c) for t, c, *_ in _msg_rows(session_factory, m2)] == [(t1, ch_b)]


# ── control: payload with no per-entry identifier keeps the URL fallback ─────
def test_payload_without_per_entry_identifier_uses_the_url_channel(session_factory):
    w = _world(session_factory, two_tenants=False)
    m = f"wamid.f1-{w['n']}"
    change = {"field": "messages", "value": {
        "messaging_product": "whatsapp",
        "contacts": [{"wa_id": "60000000091", "profile": {"name": "Cust"}}],
        "messages": [_in_msg(m, "60000000091")],
    }}
    _process(session_factory, w["ch_b"], _wa([change]))
    assert [(t, c) for t, c, *_ in _msg_rows(session_factory, m)] == [(w["t1"], w["ch_b"])]
