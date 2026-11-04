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

    monkeypatch.setattr(http_actions.time, "monotonic", clock)
    state["responses"] = [_Stream(200, {"content-type": "text/plain"}, b"slow-drip")]
    detail, _ = _start(client, session_factory, "https://api.example.com/slow")
    assert "(truncated)" in _node(detail, "http_1")["output"]["body"]


# -- AC-38-137 ------------------------------------------------------------------
PRIVATE_TARGETS = [
    "https://127.0.0.1/x", "https://[::1]/x", "https://10.0.0.1/x", "https://172.16.0.1/x",
    "https://192.168.0.1/x", "https://169.254.169.254/latest/meta-data", "https://[fe80::1]/x",
    "https://100.64.0.1/x", "https://100.127.255.254/x", "https://[fd00::1]/x",
    "https://[::ffff:10.0.0.1]/x", "https://[::ffff:100.64.0.1]/x",
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
