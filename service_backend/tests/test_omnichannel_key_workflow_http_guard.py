"""Plan 38 gap 7, slice S3: `http.request` under the API key, behind the
outbound guard (AC-38-136, AC-38-137). RED tests written before the
implementation.

The URL reaches the node as a run input (`trigger.input.url`) of an owned,
published `entity.shortcut` workflow started with `POST /workflows/{id}/runs`,
so the check under test is the run-time one. A spy over `socket.create_connection`
and `socket.socket.connect` records every attempt and refuses it, so a leak can
never really connect: the refusal tests assert ZERO attempts.
"""
import json
import socket

import pytest

from tests.test_omnichannel_key_workflow_runs import (
    BASE,
    _action,
    _chain,
    _note_node,
    _owned_workflow,
    _post_run,
    _rig,
)

SECRET = "Bearer sk_live_S3_HTTP_SECRET"


def _http_doc_nodes(extra=None):
    cfg = {"method": "GET", "url": "{{ trigger.input.url }}", "timeoutSeconds": "5",
           "headers": [{"key": "Authorization", "value": SECRET}]}
    cfg.update(extra or {})
    return [_action("http_1", "http.request", cfg),
            _note_node("after_1", "after the call {{ trigger.input.url }}")]


def _start(client, session_factory, url, extra=None):
    r = _rig(client, session_factory)
    wid = _owned_workflow(session_factory, r["ws"], nodes=_http_doc_nodes(extra))
    resp = _post_run(client, r["hdr"], wid, r["contact"], {"url": url})
    assert resp.status_code == 202, resp.text
    detail = client.get(f"{BASE}/workflows/runs/{resp.json()['id']}", headers=r["hdr"])
    assert detail.status_code == 200, detail.text
    return detail.json(), detail.text


def _node(detail, nid):
    return next(n for n in detail["nodes"] if n["nodeId"] == nid)


@pytest.fixture
def connect_spy(monkeypatch):
    """Records and refuses every TCP connect attempt."""
    attempts = []

    def refuse_create(address, *a, **k):
        attempts.append(("create_connection", address))
        raise OSError("test spy: connect refused")

    def refuse_connect(self, address, *a, **k):
        attempts.append(("connect", address))
        raise OSError("test spy: connect refused")

    def refuse_connect_ex(self, address, *a, **k):
        attempts.append(("connect_ex", address))
        return 111

    monkeypatch.setattr(socket, "create_connection", refuse_create)
    monkeypatch.setattr(socket.socket, "connect", refuse_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse_connect_ex)
    return attempts


def _resolver(monkeypatch, host, answers):
    """Make getaddrinfo answer for THAT host only; every other host is untouched.
    `answers` is a list of address lists, one per call (the last repeats)."""
    real = socket.getaddrinfo
    calls = {"n": 0}

    def fake(h, *a, **k):
        if str(h).lower() == host:
            addrs = answers[min(calls["n"], len(answers) - 1)]
            calls["n"] += 1
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in addrs]
        return real(h, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return calls


# -- AC-38-136 ------------------------------------------------------------------
class _Stream:
    def __init__(self, status_code=200, headers=None, body=b"ok"):
        self.status_code, self.headers, self._body = status_code, headers or {}, body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self):
        for i in range(0, len(self._body), 4096):
            yield self._body[i:i + 4096]


@pytest.fixture
def fake_http(monkeypatch):
    import httpx

    import app.workflow_engine.actions.http_actions as http_actions

    calls, state, clients = [], {"responses": []}, []
    real_init = httpx.Client.__init__

    def spy_init(self, *a, **k):
        clients.append(k)
        real_init(self, *a, **k)

    def fake_stream(_client, method, url, *, headers=None, content=None):
        calls.append({"method": method, "url": url, "headers": dict(headers or {})})
        if state["responses"]:
            return state["responses"].pop(0)
        return _Stream(headers={"content-type": "text/plain"})

    monkeypatch.setattr(httpx.Client, "__init__", spy_init)
    monkeypatch.setattr(http_actions.httpx.Client, "stream", fake_stream)
    return calls, state, clients


def test_ac_38_136_http_request_runs_under_guard(client, session_factory, fake_http, monkeypatch):
    import app.workflow_engine.actions.http_actions as http_actions
    from app.services.url_guard import GuardedTransport

    calls, state, clients = fake_http

    # a public https stub is reached; the call carries the configured header, the
    # trace masks its value, and the client is the guarded, no-redirect one
    detail, text = _start(client, session_factory, "https://api.example.com/ping")
    assert detail["status"] == "success", detail
    assert [c["url"] for c in calls] == ["https://api.example.com/ping"]
    assert calls[0]["headers"]["Authorization"] == SECRET
    assert _node(detail, "http_1")["status"] == "success"
    assert _node(detail, "http_1")["input"]["config"]["headers"][0]["value"] == "***"
    assert "sk_live_S3_HTTP_SECRET" not in text
    guarded = [k for k in clients if isinstance(k.get("transport"), GuardedTransport)]
    assert guarded and guarded[-1].get("follow_redirects") is False
    assert guarded[-1].get("timeout") == 5

    # https only: nothing is sent for http://
    calls.clear()
    detail, _ = _start(client, session_factory, "http://api.example.com/ping")
    assert detail["status"] == "failed" and calls == []
    assert "https" in (_node(detail, "http_1")["error"] or "").lower()
    assert _node(detail, "after_1")["status"] == "skipped"

    # a 302 is a plain non-2xx result: it is never followed (one call only)
    calls.clear()
    state["responses"] = [_Stream(302, {"location": "https://10.0.0.1/", "content-type": "text/plain"}, b"")]
    detail, _ = _start(client, session_factory, "https://api.example.com/redir")
    assert len(calls) == 1 and _node(detail, "http_1")["status"] == "failed"
    assert "302" in (_node(detail, "http_1")["error"] or "")

    # response cap: the constant is 256 KB and a bigger body is truncated
    assert http_actions.MAX_RESPONSE_BYTES == 256 * 1024
    calls.clear()
    state["responses"] = [_Stream(200, {"content-type": "text/plain"}, b"x" * (300 * 1024))]
    detail, _ = _start(client, session_factory, "https://api.example.com/big")
    out = _node(detail, "http_1")["output"]
    assert out["body"].endswith("(truncated)") and len(out["body"]) < 300 * 1024

    # wall-clock deadline: a clock already past the node's timeout truncates
    calls.clear()
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return 0.0 if ticks["n"] == 1 else 1000.0

    import time as real_time

    class _ScopedTime:
        """Only the http action sees the fake clock; the event loop keeps the real one."""

        def __getattr__(self, name):
            return getattr(real_time, name)

        monotonic = staticmethod(clock)

    monkeypatch.setattr(http_actions, "time", _ScopedTime())
    state["responses"] = [_Stream(200, {"content-type": "text/plain"}, b"slow-drip")]
    detail, _ = _start(client, session_factory, "https://api.example.com/slow")
    assert "(truncated)" in _node(detail, "http_1")["output"]["body"]


# -- AC-38-137 ------------------------------------------------------------------
PRIVATE_TARGETS = [
    "https://127.0.0.1/x", "https://[::1]/x", "https://10.0.0.1/x", "https://172.16.0.1/x",
    "https://192.168.0.1/x", "https://169.254.169.254/latest/meta-data", "https://[fe80::1]/x",
    "https://100.64.0.1/x", "https://100.127.255.254/x", "https://[fd00::1]/x",
    "https://[::ffff:10.0.0.1]/x", "https://[::ffff:100.64.0.1]/x", "https://[fec0::1]/x",
]


def _assert_refused(detail, attempts):
    assert detail["status"] == "failed", detail
    http = _node(detail, "http_1")
    assert http["status"] == "failed"
    msg = (http["error"] or "").lower()
    assert "refused" in msg or "private or reserved" in msg, http["error"]
    assert _node(detail, "after_1")["status"] == "skipped"
    assert attempts == [], f"a TCP connect was attempted: {attempts}"


@pytest.mark.parametrize("url", PRIVATE_TARGETS)
def test_ac_38_137_key_workflow_http_request_refuses_private_targets(
    client, session_factory, connect_spy, url
):
    detail, text = _start(client, session_factory, url)
    _assert_refused(detail, connect_spy)
    assert "sk_live_S3_HTTP_SECRET" not in text


HOST = "partner-api.example.com"
NAME_CASES = {
    "name-resolves-to-10.0.0.7": [["10.0.0.7"]],
    "name-public-first-then-10.0.0.7": [["93.184.216.34", "10.0.0.7"]],
    "name-rebinds-after-preflight": [["93.184.216.34"], ["10.0.0.7"]],
}


@pytest.mark.parametrize("case", list(NAME_CASES))
def test_ac_38_137_key_workflow_http_request_refuses_private_targets_by_name(
    client, session_factory, connect_spy, monkeypatch, case
):
    """A public-looking name. The resolver is patched for THAT host only; the rebind case
    answers a public address to the first lookup and 10.0.0.7 to every later one."""
    _resolver(monkeypatch, HOST, NAME_CASES[case])
    detail, _ = _start(client, session_factory, f"https://{HOST}/hook")
    _assert_refused(detail, connect_spy)


def test_ac_38_137_control_the_spy_sees_a_connect_when_the_guard_allows(
    client, session_factory, connect_spy, monkeypatch
):
    """Control: a public name that resolves to a public address is allowed through
    the guard, so the spy DOES see the connect attempt (proves the spy is wired and a
    refusal above is the guard, not a dead spy). The attempt itself is refused by the spy."""
    _resolver(monkeypatch, HOST, [["93.184.216.34"]])
    detail, _ = _start(client, session_factory, f"https://{HOST}/hook")
    assert detail["status"] == "failed"
    assert connect_spy, "the guard allowed the public address, so a connect was attempted"
    assert all("10.0.0.7" not in str(a) for a in connect_spy)


# -- review round 1: the outbound exchange (AC-38-136) --------------------------------
import gzip
import time
import zlib

CAP = 256 * 1024
CHUNK = 64 * 1024


@pytest.fixture
def decoded_bytes(monkeypatch):
    """Counts every byte any zlib decompressor produces (httpx's gzip/deflate decoders and a
    hand-rolled bounded one alike)."""
    produced = {"n": 0}
    real = zlib.decompressobj

    class Counting:
        def __init__(self, obj):
            self._o = obj

        def decompress(self, data, *a, **k):
            out = self._o.decompress(data, *a, **k)
            produced["n"] += len(out)
            return out

        def flush(self, *a, **k):
            out = self._o.flush(*a, **k)
            produced["n"] += len(out)
            return out

        def __getattr__(self, name):
            return getattr(self._o, name)

    monkeypatch.setattr(zlib, "decompressobj", lambda *a, **k: Counting(real(*a, **k)))
    return produced


def _mock_exchange(monkeypatch, body, headers):
    import httpx

    import app.workflow_engine.actions.http_actions as ha

    def handler(request):
        return httpx.Response(200, headers=headers, stream=httpx.ByteStream(body))

    monkeypatch.setattr(ha, "GuardedTransport", lambda *a, **k: httpx.MockTransport(handler))
    monkeypatch.setattr(ha, "assert_deliverable", lambda url: None)
    return ha


def _call(ha, **extra):
    cfg = {"method": "GET", "url": "https://x.example/", "timeoutSeconds": "5", **extra}
    try:
        return ha.http_request(None, "tenant", cfg, {}), None
    except ha.ActionError as exc:
        return None, str(exc)


def test_ac_38_136_gzip_bomb_is_bounded_by_the_cap(monkeypatch, decoded_bytes):
    bomb = gzip.compress(b"\0" * (20 * 1024 * 1024), compresslevel=9)
    assert len(bomb) < CAP
    ha = _mock_exchange(monkeypatch, bomb, {"content-type": "text/plain", "content-encoding": "gzip"})
    out, err = _call(ha)
    assert decoded_bytes["n"] <= CAP + CHUNK, f"decoder produced {decoded_bytes['n']} bytes"
    assert err is not None or out["body"].endswith("(truncated)"), "a bomb must fail or truncate"
    if out is not None:
        assert len(out["body"]) <= CAP + 64


def test_ac_38_136_stacked_gzip_gzip_is_refused_within_the_cap(monkeypatch, decoded_bytes):
    inner = gzip.compress(b"\0" * (20 * 1024 * 1024), compresslevel=9)
    stacked = gzip.compress(inner, compresslevel=9)
    ha = _mock_exchange(monkeypatch, stacked,
                        {"content-type": "text/plain", "content-encoding": "gzip, gzip"})
    out, err = _call(ha)
    assert out is None and err, "a second layer is not decoded: the node fails"
    assert decoded_bytes["n"] <= CAP + CHUNK, f"decoder produced {decoded_bytes['n']} bytes"


def test_ac_38_136_other_encodings_refused(monkeypatch):
    ha = _mock_exchange(monkeypatch, b"\x00\x01", {"content-type": "text/plain", "content-encoding": "br"})
    out, err = _call(ha)
    assert out is None and err


def test_ac_38_136_single_gzip_under_the_cap_decodes_and_plain_over_cap_truncates(monkeypatch):
    text = ("hello workflow " * 1000).encode()
    ha = _mock_exchange(monkeypatch, gzip.compress(text),
                        {"content-type": "text/plain", "content-encoding": "gzip"})
    out, err = _call(ha)
    assert err is None and out["body"] == text.decode()

    ha = _mock_exchange(monkeypatch, b"x" * (CAP + 50 * 1024), {"content-type": "text/plain"})
    out, err = _call(ha)
    assert err is None and out["body"].endswith("(truncated)")


# -- B6: the deadline covers a slow status line and headers ---------------------------
def _self_signed(tmp_path):
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "stub")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    c, k = tmp_path / "c.pem", tmp_path / "k.pem"
    c.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    return str(c), str(k)


def test_ac_38_136_slow_status_line_and_headers_hit_the_deadline(tmp_path, monkeypatch):
    """A local TLS stub drips the status line and headers (each gap under the per-read timeout).
    The node must fail at about timeoutSeconds, not after the whole drip."""
    import ssl
    import threading

    import app.services.url_guard as ug
    import app.workflow_engine.actions.http_actions as ha

    certfile, keyfile = _self_signed(tmp_path)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile, keyfile)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        try:
            conn, _ = srv.accept()
            with ctx.wrap_socket(conn, server_side=True) as s:
                s.recv(65536)
                s.sendall(b"HTTP/1.1 200 OK\r\n")
                for _ in range(14):
                    time.sleep(0.4)
                    s.sendall(b"X-Drip: 1\r\n")
                s.sendall(b"Content-Type: text/plain\r\nContent-Length: 2\r\n\r\nok")
        except OSError:
            pass

    threading.Thread(target=serve, daemon=True).start()
    real_blocked = ug._is_blocked_ip
    monkeypatch.setattr(ug, "_is_blocked_ip", lambda ip: False if str(ip) == "127.0.0.1" else real_blocked(ip))
    monkeypatch.setattr(ha, "GuardedTransport", lambda *a, **k: ug.GuardedTransport(verify=False))
    started = time.monotonic()
    out, err = _call(ha, url=f"https://127.0.0.1:{port}/", timeoutSeconds="1")
    elapsed = time.monotonic() - started
    srv.close()
    assert elapsed < 1 + 1.5, f"the node took {elapsed:.1f}s with a 1s deadline"
    assert out is None and err, "a response that outlives the deadline fails the node"


# -- B7: request header names that change the framing or the route ----------------------
BAD_HEADER_NAMES = ["Host", "host", "CONNECTION", "Content-Length", "transfer-encoding", "TE", "Upgrade",
                    "Keep-Alive", "TRAILER", "Expect", "Proxy-Authorization", "proxy-connection",
                    "Proxy-Anything", "Forwarded", "X-Forwarded-Host", "x-original-url", "X-REWRITE-URL"]


def _bad_header_doc(name):
    return _chain(
        {"id": "trg", "kind": "trigger", "type": "entity.shortcut",
         "config": {"entityType": "omnichannel_contact"}},
        _action("http_1", "http.request", {"method": "GET", "url": "https://api.example.com/x",
                                           "headers": [{"key": name, "value": "v"}]}),
    )


@pytest.mark.parametrize("via", ["create", "update", "validate", "publish"])
@pytest.mark.parametrize("name", BAD_HEADER_NAMES)
def test_ac_38_136_forbidden_request_header_names_refused_at_save(client, session_factory, name, via):
    from app.models.workflow import Workflow, WorkflowVersion
    from tests.test_omnichannel_key_workflows import _counts, _key, _wf_row

    r = _rig(client, session_factory)
    hdr = r["hdr"]
    good = _chain({"id": "trg", "kind": "trigger", "type": "entity.shortcut",
                   "config": {"entityType": "omnichannel_contact"}}, _note_node())
    wid = client.post(f"{BASE}/workflows", json={"name": "h", "draftDefinition": good}, headers=hdr).json()["id"]
    bad = _bad_header_doc(name)
    counts, row = _counts(session_factory), _wf_row(session_factory, wid)

    if via == "create":
        resp = client.post(f"{BASE}/workflows", json={"name": "bad", "draftDefinition": bad}, headers=hdr)
    elif via == "update":
        resp = client.patch(f"{BASE}/workflows/{wid}", json={"draftDefinition": bad}, headers=hdr)
    elif via == "validate":
        resp = client.post(f"{BASE}/workflows/validate", json={"draftDefinition": bad}, headers=hdr)
    else:
        db = session_factory()
        try:
            db.query(Workflow).filter(Workflow.id == wid).update({"draft_definition_json": bad})
            db.commit()
        finally:
            db.close()
        row = _wf_row(session_factory, wid)
        resp = client.post(f"{BASE}/workflows/{wid}/publish", headers=hdr)

    if via == "validate":
        assert resp.status_code == 200, resp.text
        issue = next(i for i in resp.json()["issues"] if i["code"] == "invalid_definition")
        assert issue["nodeId"] == "http_1" and issue["field"] == "headers"
    else:
        assert resp.status_code == 422, resp.text
        err = resp.json()["error"]
        assert err["code"] == "invalid_definition"
        assert err["details"]["nodeId"] == "http_1" and err["details"]["field"] == "headers"
    assert _counts(session_factory) == counts
    if via in ("update", "publish"):
        assert _wf_row(session_factory, wid) == row
    if via == "publish":
        db = session_factory()
        try:
            assert db.query(WorkflowVersion).filter(WorkflowVersion.workflow_id == wid).count() == 0
        finally:
            db.close()


@pytest.mark.parametrize("name", ["Host", "content-length", "Transfer-Encoding", "Proxy-Authorization",
                                  "Forwarded", "x-forwarded-host", "X-Original-URL", "x-rewrite-url"])
def test_ac_38_136_forbidden_header_name_at_run_fails_the_node_and_connects_nowhere(
    client, session_factory, connect_spy, monkeypatch, name
):
    _resolver(monkeypatch, "api.example.com", [["93.184.216.34"]])  # public: a leak WOULD connect
    r = _rig(client, session_factory)
    nodes = [_action("http_1", "http.request", {"method": "GET", "url": "https://api.example.com/x",
                                                "headers": [{"key": name, "value": "internal.localhost"}]}),
             _note_node("after_1", "after")]
    wid = _owned_workflow(session_factory, r["ws"], nodes=nodes)  # staff-written: no save check
    resp = _post_run(client, r["hdr"], wid, r["contact"])
    assert resp.status_code == 202, resp.text
    detail = client.get(f"{BASE}/workflows/runs/{resp.json()['id']}", headers=r["hdr"]).json()
    assert detail["status"] == "failed"
    assert _node(detail, "http_1")["status"] == "failed"
    assert _node(detail, "after_1")["status"] == "skipped"
    assert connect_spy == [], f"a connect was attempted: {connect_spy}"


# -- review round 2: the deadline starts at name resolution (AC-38-136) ---------------------
MANY = "many-addresses.example"


def _stalling_connects(monkeypatch):
    """Every TCP connect records its address and stalls for its own timeout, then times out.
    Nothing ever really connects."""
    attempts = []

    def stall(address, timeout=None, *a, **k):
        attempts.append(address[0])
        time.sleep(timeout if timeout else 1)
        raise socket.timeout("test stub: connect timed out")

    def refuse(self, address, *a, **k):
        attempts.append(("raw", address[0]))
        raise OSError("test spy: connect refused")

    monkeypatch.setattr(socket, "create_connection", stall)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    return attempts


def test_ac_38_136_deadline_covers_connect_to_many_resolved_addresses(monkeypatch):
    import app.workflow_engine.actions.http_actions as ha

    _resolver(monkeypatch, MANY, [[f"93.184.216.{i}" for i in range(10, 16)]])
    attempts = _stalling_connects(monkeypatch)
    started = time.monotonic()
    out, err = _call(ha, url=f"https://{MANY}/x", timeoutSeconds="1")
    elapsed = time.monotonic() - started
    assert out is None and err, "the node fails when no address connects in time"
    assert elapsed < 2.5, f"connect phase took {elapsed:.1f}s with a 1s deadline"
    assert len({a for a in attempts if isinstance(a, str)}) <= 4, f"more than 4 addresses tried: {attempts}"


def test_ac_38_136_deadline_covers_a_stalled_resolver(monkeypatch):
    import app.workflow_engine.actions.http_actions as ha

    real = socket.getaddrinfo

    def slow(host, *a, **k):
        if str(host).lower() == MANY:
            time.sleep(5)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.10", 0))]
        return real(host, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", slow)
    attempts = _stalling_connects(monkeypatch)
    started = time.monotonic()
    out, err = _call(ha, url=f"https://{MANY}/x", timeoutSeconds="1")
    elapsed = time.monotonic() - started
    assert out is None and err
    assert elapsed < 2.5, f"name resolution held the node for {elapsed:.1f}s with a 1s deadline"
