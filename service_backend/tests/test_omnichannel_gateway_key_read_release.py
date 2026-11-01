"""Gateway key check ends its read transaction before the route's work starts.

Rule (storage-and-background-jobs.md): never hold an app-DB read transaction
across network I/O. On the public gateway the request body is awaited after the
key check, so no session may be inside a transaction while the body is pending.

The ASGI app is driven directly with a `receive` callable that blocks until the
test releases the body, so the wait is real whatever a client transport buffers.
"""
import asyncio
import json
import time
import weakref

import httpx
import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.main import app
from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.services import idempotency
from tests.test_omnichannel_api_gateway import (
    _default_workspace_id,
    _mint,
    _seed_channel,
    _seed_open_contact,
)

BOUND = 10.0  # generous upper bound for every wait; nothing here sleeps for it


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


@pytest.fixture
def tracker():
    seen = weakref.WeakSet()

    def track(session, transaction, connection):
        seen.add(session)

    event.listen(Session, "after_begin", track)
    try:
        yield lambda: [s for s in list(seen) if s.in_transaction()]
    finally:
        event.remove(Session, "after_begin", track)


def _setup(client, session_factory, phone):
    ws = _default_workspace_id(session_factory)
    channel_id = _seed_channel(session_factory, ws, phone_number_id=f"pn-{phone[-6:]}")
    contact_id = _seed_open_contact(session_factory, ws, phone=phone, open_window=True)
    minted = _mint(client, ws).json()
    return {"Authorization": f"Bearer {minted['fullKey']}"}, contact_id, channel_id, minted["key"]["id"]


def _last_used(session_factory, key_id):
    from modules.omnichannel.models import WorkspaceApiKey

    db = session_factory()
    try:
        return db.query(WorkspaceApiKey).filter(WorkspaceApiKey.id == key_id).first().last_used_at
    finally:
        db.close()


def _message_count(session_factory, contact_id):
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    try:
        return db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact_id).count()
    finally:
        db.close()


async def _post_with_held_body(headers, payload, sample, session_factory, key_id):
    """POST the send route straight into the ASGI app; the body is withheld until
    the key check has run (last_used_at set) and `sample()` has been taken."""
    body = json.dumps(payload).encode()
    release = asyncio.Event()
    sent = []
    first_receive = []

    async def receive():
        if not first_receive:
            first_receive.append(time.monotonic())
        await release.wait()
        if sent:
            await asyncio.Event().wait()  # no disconnect during the test
        sent.append(1)
        return {"type": "http.request", "body": body, "more_body": False}

    out = {"start": None, "body": b""}

    async def send(message):
        if message["type"] == "http.response.start":
            out["start"] = message["status"]
        elif message["type"] == "http.response.body":
            out["body"] += message.get("body", b"")

    raw_headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    raw_headers += [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/omnichannel/messages",
        "raw_path": b"/api/v1/omnichannel/messages",
        "query_string": b"",
        "root_path": "",
        "headers": raw_headers,
        "client": ("testclient", 5000),
        "server": ("testserver", 80),
    }
    task = asyncio.create_task(app(scope, receive, send))
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + BOUND
        loop_ = loop
        while _last_used(session_factory, key_id) is None:  # the key check has really run
            assert loop_.time() < deadline, "the key check never ran"
            assert not task.done(), "the request ended before the body was released"
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)  # margin: the route is now parked on the withheld body
        assert not task.done()
        sampled = sample()
        release.set()
        await asyncio.wait_for(task, BOUND)
    finally:
        release.set()
        if not task.done():
            task.cancel()
    return sampled, out


def test_tracker_control_sees_open_and_closed(session_factory, tracker):
    probe = session_factory()
    probe.execute(text("select 1"))
    assert len(tracker()) == 1
    probe.close()
    assert tracker() == []


def test_no_transaction_is_open_while_the_send_waits_for_its_body(client, session_factory, tracker):
    phone = "+60700700801"
    headers, contact_id, _ch, key_id = _setup(client, session_factory, phone)
    assert _last_used(session_factory, key_id) is None  # control: the key is unused so far

    payload = {"to": phone, "type": "text", "text": {"body": "hello"}}
    sampled, out = asyncio.run(
        _post_with_held_body(headers, payload, lambda: len(tracker()), session_factory, key_id)
    )
    assert sampled == 0, f"{sampled} session(s) held a transaction while the body was pending"
    assert out["start"] == 202, out
    assert _message_count(session_factory, contact_id) == 1


@pytest.mark.parametrize("path", ["channels", "templates"])
def test_read_route_after_the_key_check_still_answers(client, session_factory, path):
    from modules.omnichannel.models import WhatsappTemplate

    headers, _cid, channel_id, _kid = _setup(client, session_factory, "+60700700802")
    db = session_factory()
    db.add(
        WhatsappTemplate(
            tenant_id=DEFAULT_TENANT_ID,
            channel_id=channel_id,
            name="welcome",
            language="en",
            status="APPROVED",
            components_json=[{"type": "BODY", "text": "Hello {{1}}"}],
        )
    )
    db.commit()
    db.close()

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.get(f"/api/v1/omnichannel/{path}", headers=headers)

    r = asyncio.run(go())
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    if path == "templates":
        assert any(t["name"] == "welcome" for t in data)
    else:
        assert len(data) >= 1


# ── key rules stay intact ────────────────────────────────────────────────────
def test_invalid_key_is_still_401(client):
    r = client.get("/api/v1/omnichannel/channels", headers={"Authorization": "Bearer fxw_live_deadbeef"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_api_key"


def test_inactive_module_is_still_service_not_enabled(client, session_factory):
    from app.services.app_store_service import AppStoreService

    headers, _cid, _ch, _kid = _setup(client, session_factory, "+60700700804")
    db = session_factory()
    AppStoreService(db).deactivate(DEFAULT_TENANT_ID, "omnichannel")
    db.close()
    r = client.get("/api/v1/omnichannel/channels", headers=headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "service_not_enabled"


def test_suspended_tenant_is_still_refused(client, session_factory):
    from app.services.tenant_service import TenantService

    headers, _cid, _ch, _kid = _setup(client, session_factory, "+60700700805")
    assert client.get("/api/v1/omnichannel/channels", headers=headers).status_code == 200
    db = session_factory()
    try:
        TenantService(db).suspend(DEFAULT_TENANT_ID)
    finally:
        db.close()
    r = client.get("/api/v1/omnichannel/channels", headers=headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "service_not_enabled"
