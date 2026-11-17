"""S5 (2026-11-18): key-scoped webhook delivery history + contact list filters.

- `GET /api/v1/omnichannel/webhooks/{id}/deliveries?status=&limit=&before=`:
  own endpoint only (another workspace's id = the same 404 as unknown), newest
  first, paged, bounded limit, no payload body or secret, typed 422s.
- `GET /api/v1/omnichannel/contacts?updatedSince=&channelId=`: optional; absent
  = today's exact response; `?format=rio` keeps working with and without them.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.services import idempotency
from tests.test_omnichannel_api_gateway import (
    _default_workspace_id,
    _mint,
    _seed_channel,
    _seed_open_contact,
)

API = "/api/v1/omnichannel"


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


def _hdr(client, workspace_id):
    return {"Authorization": f"Bearer {_mint(client, workspace_id).json()['fullKey']}"}


def _second_workspace(session_factory, phone_number_id="pn-s5-b"):
    from modules.omnichannel.models import Workspace

    db = session_factory()
    ws = Workspace(tenant_id=DEFAULT_TENANT_ID, name="S5 B")
    db.add(ws)
    db.commit()
    wid = ws.id
    db.close()
    channel_id = _seed_channel(session_factory, wid, phone_number_id=phone_number_id)
    return wid, channel_id


def _endpoint(client, hdr, name="hook"):
    res = client.post(
        f"{API}/webhooks",
        json={"name": name, "url": "https://hooks.example.com/fx", "events": ["message.inbound"]},
        headers=hdr,
    )
    assert res.status_code == 201, res.text
    return res.json()["endpoint"]["id"]


def _deliveries(session_factory, endpoint_id, specs):
    """specs: list of (status, minutes_ago). Returns ids in insert order."""
    from modules.omnichannel.models import WebhookDelivery

    now = datetime.now(timezone.utc)
    db = session_factory()
    ids = []
    for i, (st, ago) in enumerate(specs):
        row = WebhookDelivery(
            tenant_id=DEFAULT_TENANT_ID,
            endpoint_id=endpoint_id,
            event_id=f"evt-{i}",
            event_type="message.inbound",
            payload_json={"secretish": "payload body must never be returned"},
            status=st,
            attempt_count=1 if st == "SUCCESS" else 3,
            response_status=200 if st == "SUCCESS" else 500,
            response_ms=12,
            error=None if st == "SUCCESS" else "Consumer returned 500.",
            last_attempt_at=now - timedelta(minutes=ago),
            next_attempt_at=(now + timedelta(minutes=5)) if st == "PENDING" else None,
            created_at=now - timedelta(minutes=ago),
        )
        db.add(row)
        db.flush()
        ids.append(row.id)
    db.commit()
    db.close()
    return ids


# ── Delivery history ─────────────────────────────────────────────────────────
def test_delivery_history_newest_first_with_documented_fields_only(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    hdr = _hdr(client, ws)
    eid = _endpoint(client, hdr)
    ids = _deliveries(session_factory, eid, [("SUCCESS", 30), ("FAILED", 20), ("PENDING", 10)])

    res = client.get(f"{API}/webhooks/{eid}/deliveries", headers=hdr)
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {"data", "nextBefore"}
    assert [d["id"] for d in body["data"]] == list(reversed(ids))
    assert body["nextBefore"] is None  # short page = last page
    item = body["data"][1]
    assert set(item) == {
        "id", "eventId", "eventType", "status", "attemptCount", "responseStatus",
        "responseMs", "error", "lastAttemptAt", "nextAttemptAt", "createdAt",
    }
    assert item["eventId"] == "evt-1" and item["status"] == "FAILED"
    assert item["responseStatus"] == 500 and item["attemptCount"] == 3
    assert item["error"] == "Consumer returned 500."
    assert body["data"][0]["nextAttemptAt"] is not None
    assert "payload body" not in res.text and "whsec_" not in res.text


def test_delivery_history_status_filter_and_paging(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    hdr = _hdr(client, ws)
    eid = _endpoint(client, hdr)
    specs = [("SUCCESS", 50), ("FAILED", 40), ("SUCCESS", 30), ("FAILED", 20), ("SUCCESS", 10)]
    ids = _deliveries(session_factory, eid, specs)

    failed = client.get(f"{API}/webhooks/{eid}/deliveries?status=failed", headers=hdr).json()
    assert [d["id"] for d in failed["data"]] == [ids[3], ids[1]]

    first = client.get(f"{API}/webhooks/{eid}/deliveries?limit=2", headers=hdr).json()
    assert [d["id"] for d in first["data"]] == [ids[4], ids[3]]
    assert first["nextBefore"] == ids[3]
    second = client.get(
        f"{API}/webhooks/{eid}/deliveries?limit=2&before={first['nextBefore']}", headers=hdr
    ).json()
    assert [d["id"] for d in second["data"]] == [ids[2], ids[1]]
    third = client.get(
        f"{API}/webhooks/{eid}/deliveries?limit=2&before={second['nextBefore']}", headers=hdr
    ).json()
    assert [d["id"] for d in third["data"]] == [ids[0]] and third["nextBefore"] is None

    combined = client.get(
        f"{API}/webhooks/{eid}/deliveries?status=SUCCESS&before={ids[4]}", headers=hdr
    ).json()
    assert [d["id"] for d in combined["data"]] == [ids[2], ids[0]]


@pytest.mark.parametrize(
    "query",
    ["status=DONE", "limit=0", "limit=201", "limit=abc", "before=not-a-delivery"],
)
def test_delivery_history_validation_errors_are_typed(client, session_factory, query):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    hdr = _hdr(client, ws)
    eid = _endpoint(client, hdr)
    res = client.get(f"{API}/webhooks/{eid}/deliveries?{query}", headers=hdr)
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "invalid_request"


def test_delivery_history_is_workspace_scoped(client, session_factory):
    ws_a = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws_a)
    hdr_a = _hdr(client, ws_a)
    eid_a = _endpoint(client, hdr_a)
    ids_a = _deliveries(session_factory, eid_a, [("SUCCESS", 5)])

    ws_b, _ = _second_workspace(session_factory)
    hdr_b = _hdr(client, ws_b)
    eid_b = _endpoint(client, hdr_b, name="b")
    _deliveries(session_factory, eid_b, [("FAILED", 5)])

    foreign = client.get(f"{API}/webhooks/{eid_a}/deliveries", headers=hdr_b)
    unknown = client.get(f"{API}/webhooks/does-not-exist/deliveries", headers=hdr_b)
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()
    assert foreign.json()["error"]["code"] == "not_found"

    # B's cursor cannot page A's history, and B only ever sees its own rows.
    own_b = client.get(f"{API}/webhooks/{eid_b}/deliveries", headers=hdr_b).json()
    assert ids_a[0] not in [d["id"] for d in own_b["data"]]
    cross_cursor = client.get(
        f"{API}/webhooks/{eid_b}/deliveries?before={ids_a[0]}", headers=hdr_b
    )
    assert cross_cursor.status_code == 422


def test_staff_delivery_log_is_unchanged(client, session_factory):
    """The dashboard log reuses the same service call; its shape is untouched."""
    from tests.test_omnichannel_api_gateway import _auth

    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    hdr = _hdr(client, ws)
    eid = _endpoint(client, hdr)
    ids = _deliveries(session_factory, eid, [("SUCCESS", 20), ("FAILED", 10)])
    res = client.get(f"/omnichannel/webhooks/{eid}/deliveries", headers=_auth(client))
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"data"}
    assert [d["id"] for d in body["data"]] == [ids[1], ids[0]]


# ── Contact list filters ─────────────────────────────────────────────────────
def _identity(session_factory, contact_id, channel_id, ext):
    from modules.omnichannel.models import ContactChannelIdentity

    db = session_factory()
    db.add(
        ContactChannelIdentity(
            tenant_id=DEFAULT_TENANT_ID, contact_id=contact_id, channel_id=channel_id,
            external_user_id=ext,
        )
    )
    db.commit()
    db.close()


def _age(session_factory, contact_id, when):
    """Set both activity stamps explicitly (an explicit value beats onupdate)."""
    from modules.omnichannel.models import Contact

    db = session_factory()
    db.query(Contact).filter(Contact.id == contact_id).update(
        {Contact.updated_at: when, Contact.last_message_at: when}, synchronize_session=False
    )
    db.commit()
    db.close()


def _two_contacts(client, session_factory):
    ws = _default_workspace_id(session_factory)
    ch_a = _seed_channel(session_factory, ws, phone_number_id="pn-s5-a")
    ch_b = _seed_channel(session_factory, ws, phone_number_id="pn-s5-a2")
    old = _seed_open_contact(session_factory, ws, phone="+60111000001")
    new = _seed_open_contact(session_factory, ws, phone="+60111000002")
    now = datetime.now(timezone.utc)
    _age(session_factory, old, now - timedelta(days=3))
    _age(session_factory, new, now - timedelta(hours=1))
    _identity(session_factory, old, ch_a, "60111000001")
    _identity(session_factory, new, ch_b, "60111000002")
    return ws, _hdr(client, ws), ch_a, ch_b, old, new, now


def _ids(res):
    body = res.json()
    return {c["id"] for c in body.get("data", body.get("items", []))}


def test_updated_since_filter(client, session_factory):
    ws, hdr, _a, _b, old, new, now = _two_contacts(client, session_factory)
    since = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = client.get(f"{API}/contacts?updatedSince={since}", headers=hdr)
    assert res.status_code == 200, res.text
    assert _ids(res) == {new}
    assert res.json()["total"] == 1

    # No offset = UTC; an offset is honoured.
    naive = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    assert _ids(client.get(f"{API}/contacts?updatedSince={naive}", headers=hdr)) == {new}
    plus8 = (now - timedelta(days=4)).astimezone(timezone(timedelta(hours=8)))
    res = client.get(f"{API}/contacts", params={"updatedSince": plus8.isoformat()}, headers=hdr)
    assert _ids(res) == {old, new}


def test_updated_since_sees_a_new_inbound_message(client, session_factory):
    """Activity counts: a message on an aged contact brings it back."""
    from tests.test_omnichannel_webhooks import _process, _wa_payload

    ws, hdr, ch_a, _b, old, new, now = _two_contacts(client, session_factory)
    since = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _ids(client.get(f"{API}/contacts?updatedSince={since}", headers=hdr)) == {new}
    _process(session_factory, ch_a, _wa_payload(wamid="wamid.s5-in", from_="60111000001", text="back"))
    assert _ids(client.get(f"{API}/contacts?updatedSince={since}", headers=hdr)) == {old, new}


def test_channel_id_filter_and_scope(client, session_factory):
    ws, hdr, ch_a, ch_b, old, new, _now = _two_contacts(client, session_factory)
    assert _ids(client.get(f"{API}/contacts?channelId={ch_a}", headers=hdr)) == {old}
    assert _ids(client.get(f"{API}/contacts?channelId={ch_b}", headers=hdr)) == {new}

    _ws_b, foreign_channel = _second_workspace(session_factory)
    foreign = client.get(f"{API}/contacts?channelId={foreign_channel}", headers=hdr)
    unknown = client.get(f"{API}/contacts?channelId=nope", headers=hdr)
    templates = client.get(f"{API}/templates?channelId={foreign_channel}", headers=hdr)
    assert foreign.status_code == unknown.status_code == templates.status_code == 404
    assert foreign.json() == unknown.json() == templates.json()
    assert foreign.json()["error"]["code"] == "channel_not_found"


def test_filters_combine(client, session_factory):
    ws, hdr, ch_a, ch_b, old, new, now = _two_contacts(client, session_factory)
    since = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _ids(client.get(f"{API}/contacts?updatedSince={since}&channelId={ch_a}", headers=hdr)) == set()
    assert _ids(client.get(f"{API}/contacts?updatedSince={since}&channelId={ch_b}", headers=hdr)) == {new}


def test_invalid_updated_since_is_typed_422(client, session_factory):
    ws, hdr, *_ = _two_contacts(client, session_factory)
    res = client.get(f"{API}/contacts?updatedSince=yesterday", headers=hdr)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_request"


def test_absent_filters_give_todays_exact_response(client, session_factory):
    """No new parameter = the same bytes the pre-S5 call path produces."""
    from modules.omnichannel.schemas import PublicContactListResponse
    from modules.omnichannel.services.conversation_service import ConversationService

    ws, hdr, *_ = _two_contacts(client, session_factory)
    res = client.get(f"{API}/contacts?pageSize=10", headers=hdr)
    assert res.status_code == 200
    db = session_factory()
    items, total = ConversationService(db).list_threads(
        DEFAULT_TENANT_ID, workspace_id=ws, status_key=None, assignee="all",
        priority=None, search=None, page=0, page_size=10,
    )
    expected = PublicContactListResponse(data=items, total=total, page=0, pageSize=10)
    db.close()
    assert res.json() == expected.model_dump(mode="json")
    assert set(res.json()) == {"data", "total", "page", "pageSize"}


def test_rio_format_with_and_without_filters(client, session_factory):
    ws, hdr, ch_a, ch_b, old, new, now = _two_contacts(client, session_factory)
    plain = client.get(f"{API}/contacts?format=rio&pageSize=1", headers=hdr)
    assert plain.status_code == 200
    nxt = plain.json()["pagination"]["next"]
    assert nxt is not None
    q = parse_qs(urlparse(nxt).query)
    assert "channelId" not in q and "updatedSince" not in q  # unchanged link shape

    since = (now - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    filtered = client.get(
        f"{API}/contacts?format=rio&pageSize=1&updatedSince={since}&channelId={ch_a}", headers=hdr
    )
    assert filtered.status_code == 200
    assert {c["id"] for c in filtered.json()["items"]} == {old}
    assert filtered.json()["pagination"]["next"] is None

    both = client.get(f"{API}/contacts?format=rio&pageSize=1&updatedSince={since}", headers=hdr)
    link = both.json()["pagination"]["next"]
    assert parse_qs(urlparse(link).query)["updatedSince"] == [since]
