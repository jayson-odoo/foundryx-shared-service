"""Plan 51: limits on one webhook delivery attempt (AC-51-01..04).

Names the coder must provide in ``modules.omnichannel.services.webhook_delivery``:
- ``DELIVERY_DEADLINE_SECONDS`` (default 10): total time for one attempt, read at
  call time so a test can lower it.
- ``RESPONSE_BYTE_CAP`` (65536): most response-body bytes read.

The real-socket tests run a local server on 127.0.0.1. An httpx timeout is per
read, so only a real slow trickle shows a missing total deadline. The guard seam:
``url_guard._is_blocked_ip`` is told loopback is allowed and the https-only
pre-flight is skipped; ``GuardedTransport`` stays in the path.
"""
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.services import url_guard
from modules.omnichannel.models import WebhookDelivery, WebhookEndpoint
from modules.omnichannel.security import encrypt_secret
from modules.omnichannel.services import webhook_delivery as wd
from tests.test_omnichannel_webhook_delivery_attempts import _stored_delivery, _stored_endpoint

LOW_DEADLINE = 1.5
SECRET = "whsec_limits"
MARKER = b"BODY-MARKER-TEXT"


class LocalServer:
    """One-connection-at-a-time TCP server; ``handler(conn)`` runs per accept."""

    def __init__(self, handler):
        self.handler = handler
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/hook"

    def _loop(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                conn.settimeout(15)
                self.handler(conn, self.stop)
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
        self.sock.close()


def _read_request(conn):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            return data
        data += chunk
    return data


@pytest.fixture
def local_server():
    servers = []

    def start(handler):
        s = LocalServer(handler)
        servers.append(s)
        return s

    yield start
    for s in servers:
        s.close()


@pytest.fixture
def allow_loopback(monkeypatch):
    monkeypatch.setattr(url_guard, "_is_blocked_ip", lambda ip: False)
    monkeypatch.setattr(wd, "assert_deliverable", lambda *a, **k: None)


def _seed(session_factory, phone, url):
    eid = _stored_endpoint(session_factory, phone, url)
    db = session_factory()
    try:
        ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == eid).one()
        ep.secret_encrypted = encrypt_secret(SECRET)
        db.commit()
    finally:
        db.close()
    return eid, _stored_delivery(session_factory, eid, f"evt-{phone}")


def _row(session_factory, did):
    db = session_factory()
    try:
        row = db.query(WebhookDelivery).filter(WebhookDelivery.id == did).one()
        db.expunge(row)
        return row
    finally:
        db.close()


def _run(session_factory, did):
    db = session_factory()
    try:
        return wd.dispatch(db, did)
    finally:
        db.close()


def _lower_deadline(monkeypatch):
    # raising=False so a missing name fails on the behaviour asserted below
    monkeypatch.setattr(wd, "DELIVERY_DEADLINE_SECONDS", LOW_DEADLINE, raising=False)


# ── AC-51-01 ────────────────────────────────────────────────────────────────
def test_ac_51_01_default_deadline_is_ten_seconds():
    assert wd.DELIVERY_DEADLINE_SECONDS == 10


def test_ac_51_01_slow_trickle_ends_at_the_total_deadline(
    session_factory, local_server, allow_loopback, monkeypatch
):
    def trickle(conn, stop):
        _read_request(conn)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
        end = time.monotonic() + 6  # the spec says 30 s; 6 s is enough past a 1.5 s deadline
        i = 0
        while time.monotonic() < end and not stop.is_set():
            conn.sendall(MARKER[i % len(MARKER) : i % len(MARKER) + 1])
            i += 1
            time.sleep(0.5)

    _lower_deadline(monkeypatch)
    srv = local_server(trickle)
    _eid, did = _seed(session_factory, "pn-d-trickle", srv.url)
    started = time.monotonic()
    outcome = _run(session_factory, did)
    elapsed = time.monotonic() - started
    assert elapsed < LOW_DEADLINE + 2.0, f"attempt took {elapsed:.1f}s"
    row = _row(session_factory, did)
    assert outcome == "retry"
    assert row.attempt_count == 1
    assert row.error
    assert MARKER.decode() not in row.error
    assert str(srv.port) not in row.error and "127.0.0.1" not in row.error


def test_ac_51_01_server_that_never_answers_ends_at_the_deadline(
    session_factory, local_server, allow_loopback, monkeypatch
):
    def silent(conn, stop):
        _read_request(conn)
        stop.wait(12)

    _lower_deadline(monkeypatch)
    srv = local_server(silent)
    _eid, did = _seed(session_factory, "pn-d-silent", srv.url)
    started = time.monotonic()
    outcome = _run(session_factory, did)
    elapsed = time.monotonic() - started
    assert elapsed < LOW_DEADLINE + 2.0, f"attempt took {elapsed:.1f}s"
    row = _row(session_factory, did)
    assert outcome == "retry"
    assert row.attempt_count == 1 and row.response_status is None
    assert row.error and str(srv.port) not in row.error


# ── AC-51-02 ────────────────────────────────────────────────────────────────
def test_ac_51_02_large_body_is_read_only_up_to_the_cap(
    session_factory, local_server, allow_loopback
):
    total = 50 * 1024 * 1024
    sent = {"n": 0}

    def big(conn, stop):
        _read_request(conn)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        conn.sendall(f"HTTP/1.1 200 OK\r\nContent-Length: {total}\r\n\r\n".encode())
        chunk = b"x" * 16384
        while sent["n"] < total and not stop.is_set():
            conn.sendall(chunk)  # blocks once the client stops reading
            sent["n"] += len(chunk)

    srv = local_server(big)
    _eid, did = _seed(session_factory, "pn-d-big", srv.url)
    assert _run(session_factory, did) == "success"  # the status decides
    row = _row(session_factory, did)
    assert row.status == "SUCCESS" and row.response_status == 200
    # the 50 MiB body was not pulled: only cap + socket buffers worth left the server
    assert sent["n"] < 8 * 1024 * 1024, f"server sent {sent['n']} bytes"
    assert wd.RESPONSE_BYTE_CAP == 65536


# ── AC-51-03 ────────────────────────────────────────────────────────────────
def test_ac_51_03_no_transaction_is_open_during_the_post(session_factory, monkeypatch):
    db = session_factory()
    seen = {}

    class SpyTransport(httpx.BaseTransport):
        def handle_request(self, request):
            seen["in_tx"] = db.in_transaction()
            return httpx.Response(200, content=b"ok")

    monkeypatch.setattr(wd, "assert_deliverable", lambda *a, **k: None)
    monkeypatch.setattr(wd, "GuardedTransport", lambda *a, **k: SpyTransport())
    _eid, did = _seed(session_factory, "pn-d-tx", "https://consumer.example/hook")
    try:
        assert wd.dispatch(db, did) == "success"
    finally:
        db.close()
    assert seen == {"in_tx": False}


# ── AC-51-04 pins (pass today) ──────────────────────────────────────────────
def _stub_status(monkeypatch, status, captured=None):
    class Stub(httpx.BaseTransport):
        def handle_request(self, request):
            if captured is not None:
                captured.append(request)
            return httpx.Response(status, content=b"nope")

    monkeypatch.setattr(wd, "assert_deliverable", lambda *a, **k: None)
    monkeypatch.setattr(wd, "GuardedTransport", lambda *a, **k: Stub())


def test_ac_51_04_pin_200_is_success_with_signed_request(session_factory, monkeypatch):
    reqs = []
    _stub_status(monkeypatch, 200, reqs)
    eid, did = _seed(session_factory, "pn-d-pin200", "https://consumer.example/hook")
    assert _run(session_factory, did) == "success"
    row = _row(session_factory, did)
    assert row.status == "SUCCESS" and row.attempt_count == 1
    assert row.next_attempt_at is None and row.error is None
    assert row.response_status == 200
    req = reqs[0]
    ts = req.headers["X-Fx-Timestamp"]
    assert req.headers["X-Fx-Signature"] == wd.sign_body(SECRET, ts, req.content)
    assert req.headers["X-Fx-Event-Id"] == "evt-pn-d-pin200"
    db = session_factory()
    try:
        ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == eid).one()
        assert ep.consecutive_failures == 0 and ep.last_success_at is not None
    finally:
        db.close()


def test_ac_51_04_pin_500_is_one_failed_attempt_with_backoff(session_factory, monkeypatch):
    _stub_status(monkeypatch, 500)
    eid, did = _seed(session_factory, "pn-d-pin500", "https://consumer.example/hook")
    assert _run(session_factory, did) == "retry"
    row = _row(session_factory, did)
    assert row.status == "PENDING" and row.attempt_count == 1
    assert row.response_status == 500 and row.error == "Consumer returned 500."
    nxt = row.next_attempt_at
    nxt = nxt if nxt.tzinfo else nxt.replace(tzinfo=timezone.utc)
    delta = (nxt - datetime.now(timezone.utc)).total_seconds()
    assert 30 < delta <= 60 + 5
    db = session_factory()
    try:
        ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == eid).one()
        assert ep.consecutive_failures == 0
    finally:
        db.close()


def test_ac_51_04_pin_last_attempt_dead_letters_and_counts_once(session_factory, monkeypatch):
    _stub_status(monkeypatch, 500)
    eid, did = _seed(session_factory, "pn-d-pindead", "https://consumer.example/hook")
    db = session_factory()
    try:
        r = db.query(WebhookDelivery).filter(WebhookDelivery.id == did).one()
        r.attempt_count = wd.MAX_ATTEMPTS - 1
        db.commit()
    finally:
        db.close()
    assert _run(session_factory, did) == "dead"
    row = _row(session_factory, did)
    assert row.status == "FAILED" and row.attempt_count == wd.MAX_ATTEMPTS
    assert row.next_attempt_at is None
    db = session_factory()
    try:
        ep = db.query(WebhookEndpoint).filter(WebhookEndpoint.id == eid).one()
        assert ep.consecutive_failures == 1
    finally:
        db.close()
