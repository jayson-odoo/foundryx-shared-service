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
import asyncio
import socket
import ssl
import threading
import time
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.services import url_guard
from modules.omnichannel.models import WebhookDelivery, WebhookEndpoint
from modules.omnichannel.security import encrypt_secret
from modules.omnichannel.services import webhook_delivery as wd
from tests.test_outbound_connect_address import NAME, tls_material  # noqa: F401 - fixture
from tests.test_omnichannel_webhook_delivery_attempts import _stored_delivery, _stored_endpoint

LOW_DEADLINE = 1.5
SECRET = "whsec_limits"
MARKER = b"BODY-MARKER-TEXT"


class LocalServer:
    """One-connection-at-a-time TCP server; ``handler(conn)`` runs per accept."""

    def __init__(self, handler, host="127.0.0.1", port=0, family=socket.AF_INET, tls=None):
        self.handler = handler
        self.tls = tls
        self.sock = socket.socket(family)
        self.sock.bind((host, port))
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
                if self.tls is not None:
                    conn = self.tls.wrap_socket(conn, server_side=True)
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

    def start(handler, **kw):
        s = LocalServer(handler, **kw)
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

    def spy(request):
        seen["in_tx"] = db.in_transaction()
        return httpx.Response(200, content=b"ok")

    monkeypatch.setattr(wd, "assert_deliverable", lambda *a, **k: None)
    monkeypatch.setattr(wd, "GuardedTransport", lambda *a, **k: httpx.MockTransport(spy))
    _eid, did = _seed(session_factory, "pn-d-tx", "https://consumer.example/hook")
    try:
        assert wd.dispatch(db, did) == "success"
    finally:
        db.close()
    assert seen == {"in_tx": False}


# ── AC-51-04 pins (pass today) ──────────────────────────────────────────────
def _stub_status(monkeypatch, status, captured=None):
    def stub(request):
        if captured is not None:
            captured.append(request)
        return httpx.Response(status, content=b"nope")

    monkeypatch.setattr(wd, "assert_deliverable", lambda *a, **k: None)
    monkeypatch.setattr(wd, "GuardedTransport", lambda *a, **k: httpx.MockTransport(stub))


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


# ── review round: whole-attempt deadline, no leftover work, fixed text ──────
def _pause_or_closed(conn, seconds, state):
    """Wait ``seconds``; True (and note it) when the client closed the connection."""
    conn.settimeout(seconds)
    try:
        if conn.recv(1) == b"":
            state["closed"] = True
            return True
    except socket.timeout:
        pass
    except OSError:
        state["closed"] = True
        return True
    return False


def _slow_headers(state):
    def handler(conn, stop):
        _read_request(conn)
        head = b"HTTP/1.1 200 OK\r\nX-Pad: " + b"a" * 200
        end = time.monotonic() + 6
        for i in range(len(head)):
            if time.monotonic() > end or stop.is_set():
                return
            try:
                conn.sendall(head[i : i + 1])
            except OSError:
                state["closed"] = True
                return
            if _pause_or_closed(conn, 0.5, state):
                return

    return handler


def _continue_forever(state):
    def handler(conn, stop):
        _read_request(conn)
        end = time.monotonic() + 6
        while time.monotonic() < end and not stop.is_set():
            try:
                conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
            except OSError:
                state["closed"] = True
                return
            if _pause_or_closed(conn, 0.5, state):
                return

    return handler


def _body_trickle(state):
    def handler(conn, stop):
        _read_request(conn)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
        end = time.monotonic() + 6
        while time.monotonic() < end and not stop.is_set():
            try:
                conn.sendall(b"x")
            except OSError:
                state["closed"] = True
                return
            if _pause_or_closed(conn, 0.5, state):
                return

    return handler


@pytest.mark.parametrize(
    "make", [_slow_headers, _continue_forever, _body_trickle], ids=["slow-headers", "100-continue", "body-trickle"]
)
def test_ac_51_01_slow_phase_ends_at_deadline_leaves_no_thread_and_closes(
    make, session_factory, local_server, allow_loopback, monkeypatch
):
    state = {"closed": False}
    _lower_deadline(monkeypatch)
    srv = local_server(make(state))
    before = set(threading.enumerate())
    _eid, did = _seed(session_factory, "pn-d-" + make.__name__, srv.url)
    started = time.monotonic()
    outcome = _run(session_factory, did)
    elapsed = time.monotonic() - started
    assert elapsed < LOW_DEADLINE + 2.0, f"attempt took {elapsed:.1f}s"
    assert outcome == "retry"
    row = _row(session_factory, did)
    assert row.attempt_count == 1
    assert row.error == wd.DEADLINE_ERROR.format(seconds=wd.DELIVERY_DEADLINE_SECONDS)
    time.sleep(1.0)
    alive = _strays(before, SimpleNamespace(in_lookup=set()))
    assert alive == [], f"threads left working on the attempt: {alive}"
    assert state["closed"], "the server never saw its connection closed"


# ── AC-51-06 ────────────────────────────────────────────────────────────────
def test_ac_51_06_illegal_header_line_is_not_echoed(
    session_factory, local_server, allow_loopback
):
    def bad(conn, stop):
        _read_request(conn)
        conn.sendall(b"HTTP/1.1 200 OK\r\nBad header line " + MARKER + b"\r\n\r\n")

    srv = local_server(bad)
    _eid, did = _seed(session_factory, "pn-d-badhdr", srv.url)
    assert _run(session_factory, did) == "retry"
    row = _row(session_factory, did)
    assert row.error
    assert MARKER.decode() not in row.error
    assert "127.0.0.1" not in row.error and str(srv.port) not in row.error


def test_ac_51_06_unresolvable_address_is_not_echoed(session_factory, monkeypatch):
    host = "no-such-host.consumer-test.example"

    def fail(h, *a, **k):
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    _eid, did = _seed(session_factory, "pn-d-nohost", f"https://{host}/hook")
    assert _run(session_factory, did) == "retry"
    row = _row(session_factory, did)
    assert row.error and row.attempt_count == 1
    assert host not in row.error and "consumer-test" not in row.error


# ── AC-51-01: the address check is inside the deadline ──────────────────────
def test_ac_51_01_slow_address_check_counts_inside_the_deadline(session_factory, monkeypatch):
    def slow_dns(h, *a, **k):
        time.sleep(LOW_DEADLINE + 2.5)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]

    def quick(request):
        return httpx.Response(200, content=b"ok")

    _lower_deadline(monkeypatch)
    monkeypatch.setattr(socket, "getaddrinfo", slow_dns)
    monkeypatch.setattr(wd, "GuardedTransport", lambda *a, **k: httpx.MockTransport(quick))
    _eid, did = _seed(session_factory, "pn-d-slowdns", "https://consumer.example/hook")
    started = time.monotonic()
    outcome = _run(session_factory, did)
    elapsed = time.monotonic() - started
    assert elapsed < LOW_DEADLINE + 1.5, f"attempt took {elapsed:.1f}s"
    assert outcome == "retry"
    assert _row(session_factory, did).error == wd.DEADLINE_ERROR.format(
        seconds=wd.DELIVERY_DEADLINE_SECONDS
    )


# ── round 2: late connects, TLS, stalled lookups ────────────────────────────
# Behaviour only: no thread names. "Stray" = a thread started during the test
# that is still alive, EXCLUDING a thread that is at that moment inside the fake
# resolver (a host lookup cannot be interrupted and may finish on its own;
# ``FakeDns.in_lookup`` holds the idents of threads currently inside it).
STALL = LOW_DEADLINE + 2.5  # clearly past the LOW_DEADLINE + 2.0 bound


class FakeDns:
    """Scripted ``socket.getaddrinfo`` for ``NAME``; other names resolve for real."""

    def __init__(self, monkeypatch, addresses, stall=lambda n: 0.0):
        self.addresses = addresses  # [(family, ip)]
        self.stall = stall  # call number -> seconds to block
        self.calls = 0
        self.in_lookup = set()
        real = socket.getaddrinfo

        def fake(host, port, *a, **k):
            h = host.decode() if isinstance(host, bytes) else host
            if h != NAME:
                return real(host, port, *a, **k)
            n = self.calls
            self.calls += 1
            ident = threading.get_ident()
            self.in_lookup.add(ident)
            try:
                time.sleep(self.stall(n))
            finally:
                self.in_lookup.discard(ident)
            out = []
            for fam, ip in self.addresses:
                sa = (ip, port, 0, 0) if fam == socket.AF_INET6 else (ip, port)
                out.append((fam, socket.SOCK_STREAM, 6, "", sa))
            return out

        monkeypatch.setattr(socket, "getaddrinfo", fake)


def _strays(before, dns):
    return [
        t.name
        for t in threading.enumerate()
        if t not in before and t.is_alive() and t.ident not in dns.in_lookup
    ]


def _server_ctx(material):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(material.cert, material.key)
    return ctx


@pytest.fixture
def https_seam(monkeypatch, tls_material):
    """The live path: https only, the real address check, a real certificate check
    against a throwaway CA (httpx reads SSL_CERT_FILE when it builds the SSL
    context), and the loopback block rule lifted."""
    monkeypatch.setenv("SSL_CERT_FILE", tls_material.ca)
    monkeypatch.setattr(url_guard, "_is_blocked_ip", lambda ip: False)
    return tls_material


def _blackhole():
    """A listener whose accept queue is full: further connects stall (dropped SYN)."""
    lst = socket.socket()
    lst.bind(("127.0.0.1", 0))
    lst.listen(0)
    port = lst.getsockname()[1]
    held = []
    for _ in range(256):  # until a connect stalls (queue sizes differ by OS)
        c = socket.socket()
        c.settimeout(0.3)
        held.append(c)
        try:
            c.connect(("127.0.0.1", port))
        except OSError:
            break
    return lst, held, port


def _v6_server(local_server, handler, port, tls):
    try:
        return local_server(handler, host="::1", port=port, family=socket.AF_INET6, tls=tls)
    except OSError:
        pytest.skip("IPv6 loopback not available")


def _logging(state, body):
    """Record the time a full request was read, then run ``body``."""

    def handler(conn, stop):
        _read_request(conn)
        state["requests"].append(time.monotonic())
        body(conn, stop)

    return handler


def _slow_head_body(state):
    def body(conn, stop):
        head = b"HTTP/1.1 200 OK\r\nX-Pad: " + b"a" * 200
        for i in range(len(head)):
            if stop.is_set():
                return
            try:
                conn.sendall(head[i : i + 1])
            except OSError:
                state["closed"] = True
                return
            if _pause_or_closed(conn, 0.5, state):
                return

    return body


@pytest.mark.parametrize("tls", [False, True], ids=["http", "tls"])
def test_ac_51_01_connect_that_completes_after_the_deadline_sends_nothing(
    tls, session_factory, local_server, monkeypatch, request
):
    if tls:
        material = request.getfixturevalue("https_seam")
    else:
        monkeypatch.setattr(url_guard, "_is_blocked_ip", lambda ip: False)
        monkeypatch.setattr(wd, "assert_deliverable", lambda *a, **k: None)
    state = {"closed": False, "requests": []}
    hole, held, port = _blackhole()
    try:
        srv = _v6_server(
            local_server,
            _logging(state, _slow_head_body(state)),
            port,
            _server_ctx(material) if tls else None,
        )
        dns = FakeDns(monkeypatch, [(socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")])
        _lower_deadline(monkeypatch)
        before = set(threading.enumerate())
        scheme = "https" if tls else "http"
        _eid, did = _seed(session_factory, f"pn-d-late-{scheme}", f"{scheme}://{NAME}:{port}/hook")
        started = time.monotonic()
        outcome = _run(session_factory, did)
        ended = time.monotonic()
        assert ended - started < LOW_DEADLINE + 2.0, f"attempt took {ended - started:.1f}s"
        assert outcome == "retry"
        time.sleep(1.0)
        assert _strays(before, dns) == [], "threads still working one second after the attempt"
        time.sleep(1.5)
        late = [round(t - ended, 2) for t in state["requests"] if t and t > ended]
        assert late == [], f"request bytes reached the server {late} s after the attempt was recorded"
    finally:
        for c in held:
            c.close()
        hole.close()


def test_ac_51_01_tls_handshake_stall_ends_at_the_deadline(
    session_factory, local_server, https_seam, monkeypatch
):
    state = {"closed": False}

    def stall(conn, stop):  # raw TCP: takes the ClientHello, never answers
        conn.recv(4096)
        while not stop.is_set():
            if _pause_or_closed(conn, 0.5, state):
                return

    srv = local_server(stall)
    dns = FakeDns(monkeypatch, [(socket.AF_INET, "127.0.0.1")])
    _lower_deadline(monkeypatch)
    before = set(threading.enumerate())
    _eid, did = _seed(session_factory, "pn-d-hs", f"https://{NAME}:{srv.port}/hook")
    started = time.monotonic()
    outcome = _run(session_factory, did)
    elapsed = time.monotonic() - started
    assert elapsed < LOW_DEADLINE + 2.0, f"attempt took {elapsed:.1f}s"
    assert outcome == "retry"
    assert _row(session_factory, did).error == wd.DEADLINE_ERROR.format(
        seconds=wd.DELIVERY_DEADLINE_SECONDS
    )
    time.sleep(1.0)
    assert _strays(before, dns) == [], "threads still working one second after the attempt"
    assert state["closed"], "the server never saw its connection closed"


def test_ac_51_01_stalled_second_lookup_sends_nothing_after_the_attempt(
    session_factory, local_server, https_seam, monkeypatch
):
    state = {"closed": False, "requests": []}
    srv = local_server(_logging(state, _slow_head_body(state)), tls=_server_ctx(https_seam))
    # call 0 is the address check (fast); the connect-time lookup stalls past the deadline
    dns = FakeDns(monkeypatch, [(socket.AF_INET, "127.0.0.1")], stall=lambda n: 0.0 if n == 0 else STALL)
    _lower_deadline(monkeypatch)
    before = set(threading.enumerate())
    _eid, did = _seed(session_factory, "pn-d-lookup", f"https://{NAME}:{srv.port}/hook")
    started = time.monotonic()
    outcome = _run(session_factory, did)
    ended = time.monotonic()
    assert ended - started < LOW_DEADLINE + 2.0, f"attempt took {ended - started:.1f}s"
    assert outcome == "retry"
    time.sleep(started + STALL + 1.5 - time.monotonic())  # the lookup has finished by now
    late = [round(t - ended, 2) for t in state["requests"] if t and t > ended]
    assert late == [], f"request bytes reached the server {late} s after the attempt was recorded"
    assert _strays(before, dns) == []


def test_ac_51_01_body_read_stops_for_a_connection_that_completed_late(
    session_factory, local_server, https_seam, monkeypatch
):
    """Kills the in-loop deadline check on its own: the connection completes
    after the deadline, the answer is instant and the body is a slow trickle.
    Whatever kept this thread from reading the body must still be in place once
    the lookup is over."""
    state = {"closed": False, "requests": []}

    def body(conn, stop):
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
        end = time.monotonic() + 8
        while time.monotonic() < end and not stop.is_set():
            try:
                conn.sendall(b"x")
            except OSError:
                return
            if _pause_or_closed(conn, 0.5, state):
                return

    srv = local_server(_logging(state, body), tls=_server_ctx(https_seam))
    dns = FakeDns(monkeypatch, [(socket.AF_INET, "127.0.0.1")], stall=lambda n: 0.0 if n == 0 else STALL)
    _lower_deadline(monkeypatch)
    before = set(threading.enumerate())
    _eid, did = _seed(session_factory, "pn-d-k4", f"https://{NAME}:{srv.port}/hook")
    started = time.monotonic()
    assert _run(session_factory, did) == "retry"
    time.sleep(started + STALL + 1.5 - time.monotonic())
    assert _strays(before, dns) == [], "a thread is still reading a body after the deadline"


# ── dispatch from inside a running event loop (eager mode, async route) ─────
def test_ac_51_01_dispatch_inside_a_running_loop_succeeds(
    session_factory, local_server, allow_loopback
):
    def ok(conn, stop):
        _read_request(conn)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

    srv = local_server(ok)
    _eid, did = _seed(session_factory, "pn-d-inloop", srv.url)

    async def route():
        return _run(session_factory, did)  # sync dispatch called from an async route

    assert asyncio.run(route()) == "success"
    row = _row(session_factory, did)
    assert row.error is None, row.error
    assert row.status == "SUCCESS" and row.response_status == 200


# ── a lost cancel must not lose the deadline; a cancelled connect closes its winner ──
def _swallow_first_cancel(monkeypatch):
    """Simulate anyio absorbing ONE cancel (as it can when the cancel lands in
    the same loop pass as its own timer or group cancel): the first
    ``CancelledError`` that reaches a network read is caught and the read goes
    on. A deadline that is only an edge-triggered cancel is lost after this; a
    level-triggered one cancels again. The real two-timer race is not forced
    here (it depends on loop timing), only this effect of it."""
    import httpcore._backends.anyio as hca

    orig = hca.AnyIOStream.read
    state = {"n": 0}

    async def read(self, max_bytes, timeout=None):
        try:
            return await orig(self, max_bytes, timeout)
        except asyncio.CancelledError:
            if state["n"]:
                raise
            state["n"] += 1
            return await orig(self, max_bytes, timeout)

    monkeypatch.setattr(hca.AnyIOStream, "read", read)
    return state


def test_ac_51_01_deadline_holds_when_the_first_cancel_is_swallowed(
    session_factory, local_server, allow_loopback, monkeypatch
):
    state = {"closed": False}
    swallowed = _swallow_first_cancel(monkeypatch)
    _lower_deadline(monkeypatch)
    srv = local_server(_body_trickle(state))
    _eid, did = _seed(session_factory, "pn-d-lostcancel", srv.url)
    started = time.monotonic()
    outcome = _run(session_factory, did)
    elapsed = time.monotonic() - started
    assert elapsed < LOW_DEADLINE + 2.0, f"attempt took {elapsed:.1f}s"
    assert outcome == "retry"
    assert _row(session_factory, did).error == wd.DEADLINE_ERROR.format(
        seconds=wd.DELIVERY_DEADLINE_SECONDS
    )
    assert swallowed["n"] == 1, "the simulated lost cancel never happened"


def test_ac_51_01_cancelled_connect_closes_the_connection_that_already_won(local_server, monkeypatch):
    import anyio
    from anyio._backends._asyncio import AsyncIOBackend

    monkeypatch.setattr(url_guard, "_is_blocked_ip", lambda ip: False)
    state = {"closed": False}

    def idle(conn, stop):
        while not stop.is_set():
            if _pause_or_closed(conn, 0.3, state):
                return

    srv = local_server(idle)
    won = []
    scopes = []
    orig = AsyncIOBackend.connect_tcp.__func__

    async def connect(cls, host, port, local_address=None):
        stream = await orig(cls, host, port, local_address)
        won.append(stream)
        scopes[0].cancel()  # the caller's deadline arrives just as the connect completes
        return stream

    monkeypatch.setattr(AsyncIOBackend, "connect_tcp", classmethod(connect))

    async def go():
        backend = url_guard._GuardedAsyncBackend("Callback URL", None)
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            await backend._connect_any(["127.0.0.1"], srv.port, 5, None, None)
        await anyio.sleep(0.5)

    asyncio.run(go())
    assert len(won) == 1
    time.sleep(0.5)
    assert state["closed"], "the server still holds an open connection"


def test_ac_51_01_media_fetch_deadline_holds_when_the_first_cancel_is_swallowed(
    local_server, https_seam, monkeypatch
):
    from app.api_errors import ApiError
    from modules.omnichannel.services import public_gateway_service as pgs

    state = {"closed": False, "requests": []}

    def body(conn, stop):
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
        end = time.monotonic() + 6
        while time.monotonic() < end and not stop.is_set():
            try:
                conn.sendall(b"x")
            except OSError:
                return
            if _pause_or_closed(conn, 0.5, state):
                return

    srv = local_server(_logging(state, body), tls=_server_ctx(https_seam))
    FakeDns(monkeypatch, [(socket.AF_INET, "127.0.0.1")])
    swallowed = _swallow_first_cancel(monkeypatch)
    monkeypatch.setattr(pgs, "MEDIA_FETCH_TOTAL_SECONDS", LOW_DEADLINE)
    svc = pgs.PublicGatewayService.__new__(pgs.PublicGatewayService)
    started = time.monotonic()
    with pytest.raises(ApiError):
        svc._fetch_url(f"https://{NAME}:{srv.port}/media")
    elapsed = time.monotonic() - started
    assert elapsed < LOW_DEADLINE + 2.0, f"media fetch took {elapsed:.1f}s"
    assert swallowed["n"] == 1, "the simulated lost cancel never happened"


def test_ac_51_01_media_fetch_slow_tls_setup_ends_at_the_deadline(
    local_server, https_seam, monkeypatch
):
    """Building the TLS context is blocking work (CA file read). A media fetch
    must still end at its total deadline as media_fetch_failed. Each build stalls
    5 s, so one build alone breaks the 1.0 s deadline plus the 2.0 s margin; only
    the public builder is patched. Nothing may reach the server."""
    from app.api_errors import ApiError
    from modules.omnichannel.services import public_gateway_service as pgs

    state = {"requests": []}
    srv = local_server(_logging(state, lambda conn, stop: None), tls=_server_ctx(https_seam))
    FakeDns(monkeypatch, [(socket.AF_INET, "127.0.0.1")])
    real = httpx.create_ssl_context

    def slow(*a, **k):
        time.sleep(5.0)
        return real(*a, **k)

    monkeypatch.setattr(httpx, "create_ssl_context", slow)
    monkeypatch.setattr(pgs, "MEDIA_FETCH_TOTAL_SECONDS", 1.0)
    svc = pgs.PublicGatewayService.__new__(pgs.PublicGatewayService)
    started = time.monotonic()
    with pytest.raises(ApiError) as err:
        svc._fetch_url(f"https://{NAME}:{srv.port}/media")
    elapsed = time.monotonic() - started
    assert elapsed < 1.0 + 2.0, f"media fetch took {elapsed:.1f}s"
    assert err.value.code == "media_fetch_failed"
    assert err.value.message == pgs._FETCH_FAILED_TEXT
    # wait until the abandoned 5 s build has had time to finish and (wrongly) connect
    time.sleep(max(0.0, 5.5 - (time.monotonic() - started)))
    assert state["requests"] == [], "a request reached the server after the fetch ended"


def test_ac_51_01_deadline_during_anyio_connect_leaves_no_socket_open(local_server, monkeypatch):
    """The deadline lands after anyio's connect_tcp holds its connected stream
    but before it returns it; that stream must still be closed (no gc help)."""
    import gc

    import anyio
    from anyio._backends._asyncio import AsyncIOBackend

    monkeypatch.setattr(url_guard, "_is_blocked_ip", lambda ip: False)
    state = {"closed": False}

    def idle(conn, stop):
        while not stop.is_set():
            if _pause_or_closed(conn, 0.3, state):
                return

    srv = local_server(idle)
    scopes = []
    connected = []
    orig = AsyncIOBackend.connect_tcp.__func__

    async def connect(cls, host, port, local_address=None):
        stream = await orig(cls, host, port, local_address)
        connected.append(stream)
        scopes[0].cancel()  # the deadline arrives as the connection completes
        return stream

    monkeypatch.setattr(AsyncIOBackend, "connect_tcp", classmethod(connect))

    async def go():
        backend = url_guard._GuardedAsyncBackend("Callback URL", None)
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            await backend._connect_any(["127.0.0.1"], srv.port, 5, None, None)
        await anyio.sleep(0.5)

    gc.disable()
    try:
        asyncio.run(go())
        assert len(connected) == 1
        time.sleep(0.5)
        closed_before_gc = state["closed"]
    finally:
        gc.enable()
        gc.collect()
    assert closed_before_gc, "a connection cancelled mid-connect was left open until garbage collection"
