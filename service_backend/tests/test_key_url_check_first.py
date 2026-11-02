"""Plan 49 - the callback URL is checked before database work on key routes
(AC-49-01..03, backend only).

RED tests written before the implementation. Everything is asserted from the
outside through the real gateway routes. The resolver the URL check uses is
replaced by a spy that answers a public address (offline) and records, at the
moment it runs, every database session of the process that is inside a
transaction (a session in a transaction holds a pooled connection).

Pins (tests that pass today) say so in their docstring.
"""
import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from modules.omnichannel.services import idempotency
from modules.omnichannel.services.webhook_service import WebhookService
from tests.test_omnichannel_api_gateway import _seeded
from tests.test_omnichannel_send_route_limits import _install, _pdf_media, _PATHS, _setup

HOOKS = "/api/v1/omnichannel/webhooks"
PUBLIC = [(2, 1, 6, "", ("93.184.216.34", 0))]


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


class _Rig:
    """Records, in order, the URL check and the lock calls; and what was open
    when the URL check ran."""

    def __init__(self):
        self.events = []
        self.open_at_check = []
        self._open = set()

    def attach(self, monkeypatch):
        rig = self

        def on_begin(session, transaction, connection):
            rig._open.add(session)

        def on_end(session, transaction):
            if transaction.parent is None:
                rig._open.discard(session)

        event.listen(Session, "after_begin", on_begin)
        event.listen(Session, "after_transaction_end", on_end)
        self._listeners = [(on_begin, "after_begin"), (on_end, "after_transaction_end")]

        def resolver(host, port=None, *a, **k):
            if host == "localhost":  # the realtime publisher's redis connect, not a URL check
                return PUBLIC
            rig.events.append("url")
            rig.open_at_check.append(
                [s for s in list(rig._open) if s.in_transaction()]
            )
            return PUBLIC

        monkeypatch.setattr("app.services.url_guard.socket.getaddrinfo", resolver)
        for name in ("_hold_live_key", "_lock_endpoint"):
            original = getattr(WebhookService, name)

            def wrapper(self_, *a, _o=original, _n=name, **k):
                rig.events.append(_n)
                return _o(self_, *a, **k)

            monkeypatch.setattr(WebhookService, name, wrapper)

    def detach(self):
        for fn, name in self._listeners:
            event.remove(Session, name, fn)


@pytest.fixture
def rig(monkeypatch):
    r = _Rig()
    r.attach(monkeypatch)
    yield r
    r.detach()


def _create(client, hdr, url="https://hooks.example.com/a"):
    return client.post(
        HOOKS, json={"name": "w", "url": url, "events": ["message.inbound"]}, headers=hdr
    )


def _assert_free_at_check(rig):
    assert "url" in rig.events, "the URL check never ran (test would pass for the wrong reason)"
    assert rig.open_at_check, "the resolver spy never recorded"
    for held in rig.open_at_check:
        assert held == [], (
            f"{len(held)} session(s) were in a transaction (holding a pooled "
            "connection) while the callback URL was resolved"
        )


# ── AC-49-01 ────────────────────────────────────────────────────────────────
def test_ac_49_01_key_create_checks_url_with_no_transaction_held(client, session_factory, rig):
    hdr, _ = _seeded(client, session_factory, phone="+60490000001")
    rig.events.clear(); rig.open_at_check.clear()
    r = _create(client, hdr)
    assert r.status_code == 201, r.text
    _assert_free_at_check(rig)


def test_ac_49_01_key_patch_checks_new_url_with_no_transaction_held(client, session_factory, rig):
    hdr, _ = _seeded(client, session_factory, phone="+60490000002")
    eid = _create(client, hdr).json()["endpoint"]["id"]
    rig.events.clear(); rig.open_at_check.clear()
    r = client.patch(f"{HOOKS}/{eid}", json={"url": "https://hooks.example.com/b"}, headers=hdr)
    assert r.status_code == 200, r.text
    _assert_free_at_check(rig)


# ── AC-49-02 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", ["media", "header"])
def test_ac_49_02_key_send_with_media_url_checks_it_with_no_transaction_held(
    client, session_factory, monkeypatch, path
):
    """Every other key route that resolves a host: the message send with a
    media url (body media, or interactive header). Likely a pin today."""
    phone = "+60490000003" if path == "media" else "+60490000004"
    headers, _cid, _ch = _setup(client, session_factory, phone=phone, token="tkn-49")
    _install(monkeypatch, media=_pdf_media)
    r = _Rig()
    r.attach(monkeypatch)
    # _install replaced the resolver; put the spy back on top of it.
    try:
        r.events.clear(); r.open_at_check.clear()
        url, body = _PATHS[path](phone)
        res = client.post(url, json=body, headers=headers)
        assert res.status_code in (200, 201, 202), res.text
        _assert_free_at_check(r)
    finally:
        r.detach()


# ── AC-49-03 pins ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["http://hooks.example.com/x", "https://localhost/x"])
def test_ac_49_03_pin_failing_url_answers_422_invalid_request(client, session_factory, rig, bad):
    """Pin: a URL that fails the check answers 422 invalid_request on create and PATCH."""
    hdr, _ = _seeded(client, session_factory, phone="+60490000005" if bad[4] == ":" else "+60490000006")
    r = _create(client, hdr, bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request", r.text
    eid = _create(client, hdr).json()["endpoint"]["id"]
    p = client.patch(f"{HOOKS}/{eid}", json={"url": bad}, headers=hdr)
    assert p.status_code == 422 and p.json()["error"]["code"] == "invalid_request", p.text
    kept = client.get(HOOKS, headers=hdr).json()["data"]
    assert [e["url"] for e in kept] == ["https://hooks.example.com/a"]


def test_ac_49_03_pin_create_rereads_key_after_the_url_check(client, session_factory, rig):
    """Pin: plan 43's key re-read (row lock) still happens, after the URL check."""
    hdr, _ = _seeded(client, session_factory, phone="+60490000007")
    rig.events.clear()
    assert _create(client, hdr).status_code == 201
    assert "_hold_live_key" in rig.events, rig.events
    assert rig.events.index("url") < rig.events.index("_hold_live_key"), rig.events


def test_ac_49_03_pin_patch_rereads_key_and_locks_row_after_the_url_check(
    client, session_factory, rig
):
    """Pin: on PATCH the key re-read and the endpoint row lock both run, after the URL check."""
    hdr, _ = _seeded(client, session_factory, phone="+60490000008")
    eid = _create(client, hdr).json()["endpoint"]["id"]
    rig.events.clear()
    r = client.patch(f"{HOOKS}/{eid}", json={"url": "https://hooks.example.com/c"}, headers=hdr)
    assert r.status_code == 200, r.text
    ev = rig.events
    assert "_hold_live_key" in ev and "_lock_endpoint" in ev, ev
    assert ev.index("url") < ev.index("_hold_live_key") < ev.index("_lock_endpoint"), ev


def test_ac_49_03_pin_patch_without_url_still_locks(client, session_factory, rig):
    """Pin: a name-only PATCH (no URL check) still re-reads the key and locks the row."""
    hdr, _ = _seeded(client, session_factory, phone="+60490000009")
    eid = _create(client, hdr).json()["endpoint"]["id"]
    rig.events.clear()
    r = client.patch(f"{HOOKS}/{eid}", json={"name": "renamed"}, headers=hdr)
    assert r.status_code == 200, r.text
    assert "_hold_live_key" in rig.events and "_lock_endpoint" in rig.events, rig.events


# ── staff create (review finding) ───────────────────────────────────────────
def test_ac_49_01_staff_create_checks_url_with_no_transaction_held(client, session_factory, rig):
    """Staff `POST /omnichannel/channels/{id}/webhooks` resolves the callback URL
    with no session in a transaction (WebhookService.create)."""
    from tests.test_omnichannel_conversations import _auth
    from tests.test_omnichannel_webhooks import _channel_id, _seed_thread

    _seed_thread(session_factory, messages=[{}])
    cid = _channel_id(session_factory)
    h = _auth(client)
    rig.events.clear(); rig.open_at_check.clear()
    r = client.post(
        f"/omnichannel/channels/{cid}/webhooks",
        json={"name": "staff", "url": "https://hooks.example.com/s", "events": ["message.inbound"]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    _assert_free_at_check(rig)
