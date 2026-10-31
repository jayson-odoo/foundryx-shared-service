"""Plan 41: `POST /api/v1/omnichannel/messages` stays responsive while a send
waits, a media fetch has a total time limit, and send errors keep the channel
credential out of stored text.

Every outbound HTTP call is faked at the httpx transport level
(`httpx.HTTPTransport.handle_request`), so the REAL route, service, fetch and
adapter code runs and nothing leaves the process. The ASGI and TestClient
transports are different classes, so the fake never sees the test's own calls.
"""
import asyncio
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.config import settings
from app.main import app
from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.services import idempotency
from tests.test_omnichannel_api_gateway import (
    _default_workspace_id,
    _mint,
    _seed_channel,
    _seed_open_contact,
)

MEDIA_HOST = "media.example.com"
MEDIA_URL = f"https://{MEDIA_HOST}/files/doc.pdf"
GRAPH_HOST = "graph.facebook.com"
PDF = b"%PDF-1.4\n" + b"x" * 512

SLEEP = 2.0  # generous: the loop must stay free for well under this
GAP_LIMIT = 1.0  # heartbeat ticks every 50 ms; half the sleep is a wide margin

GUIDE = Path(__file__).resolve().parents[2] / "documentation" / "omnichannel" / "consumer-integration-guide.md"


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


# ── rig ──────────────────────────────────────────────────────────────────────
class _Stream(httpx.SyncByteStream):
    """A response body that records whether and how far it was read."""

    def __init__(self, chunks, on_chunk=None):
        self._chunks = chunks
        self._on_chunk = on_chunk
        self.iterated = False
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        self.iterated = True
        for chunk in self._chunks:
            if self._on_chunk:
                self._on_chunk()
            self.consumed += 1
            yield chunk

    def close(self):
        self.closed = True


def _pdf_chunks(n):
    return [PDF] + [b"x" * 1024] * (n - 1)


def _default_graph(request):
    path = request.url.path
    if path.endswith("/media"):
        return httpx.Response(200, json={"id": "MID-1"}, request=request)
    return httpx.Response(200, json={"messages": [{"id": "wamid.T1"}]}, request=request)


def _install(monkeypatch, *, media=None, graph=None):
    """Fake every outbound call. `rig.media_calls` counts fetches of the media
    host; `rig.graph_calls` lists the provider paths hit."""
    rig = SimpleNamespace(media_calls=0, graph_calls=[], graph_auth=[])

    def fake(self, request):
        host = request.url.host
        if host == GRAPH_HOST:
            rig.graph_calls.append(request.url.path)
            rig.graph_auth.append(request.headers.get("authorization", ""))
            return (graph or _default_graph)(request)
        if host == MEDIA_HOST:
            rig.media_calls += 1
            return media(request)
        raise AssertionError(f"unexpected outbound call to {host}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake)
    # The URL guard resolves hostnames; answer with a public address, offline.
    monkeypatch.setattr(
        "app.services.url_guard.socket.getaddrinfo",
        lambda host, port, *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")
    return rig


def _pdf_media(request):
    return httpx.Response(
        200, headers={"Content-Type": "application/pdf"}, stream=_Stream([PDF]), request=request
    )


def _skewed_clock(monkeypatch):
    """`time.monotonic` plus a skew a fake stream advances, so a "minute" costs
    no real time. Still monotonic and still moving in real time."""
    skew = [0.0]
    real = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real() + skew[0])
    return skew


def _live_credentials(session_factory, channel_id, token):
    from modules.omnichannel.models import Channel
    from modules.omnichannel.security import encrypt_credentials

    db = session_factory()
    ch = db.query(Channel).filter(Channel.id == channel_id).first()
    ch.credentials_json = encrypt_credentials({"access_token": token})
    db.commit()
    db.close()


def _setup(client, session_factory, *, phone, token=None):
    """Own data chain: channel (dev, or live with `token`), open-window contact,
    API key. Returns (headers, contact_id, channel_id)."""
    ws = _default_workspace_id(session_factory)
    channel_id = _seed_channel(session_factory, ws, phone_number_id=f"pn-{phone[-6:]}")
    contact_id = _seed_open_contact(session_factory, ws, phone=phone, open_window=True)
    if token is not None:
        _live_credentials(session_factory, channel_id, token)
    key = _mint(client, ws).json()["fullKey"]
    return {"Authorization": f"Bearer {key}"}, contact_id, channel_id


def _message_count(session_factory, contact_id):
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    n = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact_id).count()
    db.close()
    return n


def _media_body(phone, url=MEDIA_URL):
    return {"to": phone, "type": "document", "media": {"url": url, "filename": "doc.pdf"}}


def _header_body(phone, url=MEDIA_URL):
    return {
        "to": phone,
        "type": "interactive",
        "interactive": {
            "kind": "buttons",
            "body": "Hi",
            "header": {"type": "document", "url": url, "filename": "doc.pdf"},
            "buttons": [{"id": "a", "title": "A"}],
        },
    }


def _multipart(phone):
    return {
        "files": {"file": ("doc.pdf", PDF, "application/pdf")},
        "data": {"payload": json.dumps({"to": phone, "type": "document", "media": {"filename": "doc.pdf"}})},
    }


async def _drive(send):
    """Run `send(ac)` against the real app while a heartbeat ticks and one cheap
    request is made after the send has started. Returns timings."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        loop = asyncio.get_running_loop()
        ticks = [loop.time()]
        stop = asyncio.Event()

        async def heartbeat():
            while not stop.is_set():
                await asyncio.sleep(0.05)
                ticks.append(loop.time())

        hb = asyncio.create_task(heartbeat())

        async def timed_send():
            started = loop.time()
            resp = await send(ac)
            return resp, started, loop.time()

        send_task = asyncio.create_task(timed_send())
        await asyncio.sleep(0.4)  # the send is under way
        cheap = await ac.get("/")
        cheap_done = loop.time()
        resp, started, send_done = await send_task
        stop.set()
        await hb
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    return SimpleNamespace(
        resp=resp,
        cheap_status=cheap.status_code,
        send_seconds=send_done - started,
        cheap_before_send_by=send_done - cheap_done,
        max_gap=max(gaps),
    )


def _error_code(resp):
    return resp.json()["error"]["code"]


# ══ AC-41-01: other requests are answered while a send waits ═════════════════
def test_ac_41_01_json_media_send_leaves_the_loop_free(client, session_factory, monkeypatch):
    headers, _cid, _ch = _setup(client, session_factory, phone="+60700700701")

    def slow_media(request):
        time.sleep(SLEEP)
        return _pdf_media(request)

    _install(monkeypatch, media=slow_media)

    async def send(ac):
        return await ac.post("/api/v1/omnichannel/messages", json=_media_body("+60700700701"), headers=headers)

    out = asyncio.run(_drive(send))
    # control: the wait really happened and the send really succeeded
    assert out.resp.status_code == 202, out.resp.text
    assert out.send_seconds >= SLEEP * 0.9
    # the rule
    assert out.max_gap < GAP_LIMIT, f"event loop was blocked for {out.max_gap:.2f}s"
    assert out.cheap_status == 200
    assert out.cheap_before_send_by > 0.5, "the cheap request waited for the send"


def test_ac_41_01_multipart_send_leaves_the_loop_free(client, session_factory, monkeypatch):
    headers, _cid, _ch = _setup(client, session_factory, phone="+60700700702", token="tkn-live-01")

    def slow_graph(request):
        if request.url.path.endswith("/media"):
            time.sleep(SLEEP)
        return _default_graph(request)

    rig = _install(monkeypatch, graph=slow_graph)

    async def send(ac):
        return await ac.post("/api/v1/omnichannel/messages", headers=headers, **_multipart("+60700700702"))

    out = asyncio.run(_drive(send))
    assert out.resp.status_code == 202, out.resp.text
    assert rig.graph_calls, "the provider fake was never hit"
    assert out.send_seconds >= SLEEP * 0.9
    assert out.max_gap < GAP_LIMIT, f"event loop was blocked for {out.max_gap:.2f}s"
    assert out.cheap_before_send_by > 0.5, "the cheap request waited for the send"


# ══ AC-41-03: a media fetch has a 60 s total limit ═══════════════════════════
def test_total_limit_constant_is_sixty_seconds():
    from modules.omnichannel.services import public_gateway_service as pgs

    assert pgs.MEDIA_FETCH_TOTAL_SECONDS == 60.0


_PATHS = {
    "media": lambda phone: ("/api/v1/omnichannel/messages", _media_body(phone)),
    "header": lambda phone: ("/api/v1/omnichannel/messages", _header_body(phone)),
}


@pytest.mark.parametrize("path", ["media", "header"])
def test_ac_41_03_drip_over_the_total_limit_is_refused(client, session_factory, monkeypatch, path):
    phone = "+60700700703" if path == "media" else "+60700700704"
    headers, cid, _ch = _setup(client, session_factory, phone=phone, token="tkn-live-03")
    skew = _skewed_clock(monkeypatch)
    streams = []

    def drip(request):
        # every chunk arrives instantly in real time (inside the 15 s per-read
        # timeout) but the fake clock moves 10 s per chunk: 12 chunks = 120 s
        stream = _Stream(_pdf_chunks(12), on_chunk=lambda: skew.__setitem__(0, skew[0] + 10.0))
        streams.append(stream)
        return httpx.Response(200, headers={"Content-Type": "application/pdf"}, stream=stream, request=request)

    rig = _install(monkeypatch, media=drip)
    before = _message_count(session_factory, cid)
    url, body = _PATHS[path](phone)
    r = client.post(url, json=body, headers=headers)
    assert rig.media_calls == 1, "the fetch never happened"
    assert r.status_code == 422, r.text
    assert _error_code(r) == "media_fetch_failed"
    assert streams[0].consumed < 12, "the fetch kept reading past the limit"
    assert rig.graph_calls == []
    assert _message_count(session_factory, cid) == before


def test_ac_41_03_slow_headers_over_the_total_limit_are_refused(client, session_factory, monkeypatch):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700705", token="tkn-live-03")
    skew = _skewed_clock(monkeypatch)

    def slow_headers(request):
        skew[0] += 70.0  # connect and headers alone used up the whole budget
        return _pdf_media(request)

    rig = _install(monkeypatch, media=slow_headers)
    before = _message_count(session_factory, cid)
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700705"), headers=headers)
    assert rig.media_calls == 1
    assert r.status_code == 422, r.text
    assert _error_code(r) == "media_fetch_failed"
    assert rig.graph_calls == []
    assert _message_count(session_factory, cid) == before


# ══ AC-41-04: a declared size over the cap is refused before reading ═════════
def test_ac_41_04_declared_length_over_the_cap_is_refused_unread(client, session_factory, monkeypatch):
    from modules.omnichannel.services.public_gateway_service import _MEDIA_HARD_CAP

    headers, cid, _ch = _setup(client, session_factory, phone="+60700700706", token="tkn-live-04")
    streams = []

    def declared_big(request):
        stream = _Stream(_pdf_chunks(4))
        streams.append(stream)
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf", "Content-Length": str(_MEDIA_HARD_CAP + 1)},
            stream=stream,
            request=request,
        )

    rig = _install(monkeypatch, media=declared_big)
    before = _message_count(session_factory, cid)
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700706"), headers=headers)
    assert rig.media_calls == 1, "the fetch never happened"
    assert r.status_code == 422, r.text
    assert _error_code(r) == "oversize"
    assert streams[0].iterated is False and streams[0].consumed == 0, "the body was read"
    assert rig.graph_calls == []
    assert _message_count(session_factory, cid) == before


# ══ AC-41-06: the channel token is in no stored error text ═══════════════════
def _stored_text(session_factory, contact_id):
    """Everything an operator or a consumer could read back: every column of
    every activity row and of the message row."""
    from app.models.integration_activity import IntegrationActivity
    from modules.omnichannel.models import ConversationMessage

    db = session_factory()
    acts = db.query(IntegrationActivity).filter(IntegrationActivity.tenant_id == DEFAULT_TENANT_ID).all()
    msgs = db.query(ConversationMessage).filter(ConversationMessage.contact_id == contact_id).all()
    cols = lambda row: {c.name: getattr(row, c.name) for c in row.__table__.columns}  # noqa: E731
    out = SimpleNamespace(
        everything=json.dumps([cols(r) for r in acts] + [cols(r) for r in msgs], default=str),
        graph_errors=[a.error_message or "" for a in acts if a.operation == "graph:send"],
        graph_rows=[a for a in acts if a.operation == "graph:send"],
        message_error=(msgs[-1].error_message or "") if msgs else None,
        message_count=len(msgs),
    )
    db.expunge_all()
    db.close()
    return out


def _live_text_send(client, session_factory, monkeypatch, *, phone, token, graph):
    headers, cid, _ch = _setup(client, session_factory, phone=phone, token=token)
    rig = _install(monkeypatch, graph=graph)
    r = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": phone, "type": "text", "text": {"body": "hello"}},
        headers=headers,
    )
    return r, rig, _stored_text(session_factory, cid)


def _provider_400(text):
    return lambda request: httpx.Response(400, json={"error": {"message": text, "code": 131026}}, request=request)


def test_ac_41_06_provider_text_with_the_token_is_scrubbed_but_keeps_its_reason(client, session_factory, monkeypatch):
    token = "tkn-7f3a9c1e2b"
    reason = "reason-ZQX-quota-hold"
    r, rig, stored = _live_text_send(
        client, session_factory, monkeypatch, phone="+60700700707", token=token,
        graph=_provider_400(f"Recipient rejected for {token}: {reason}"),
    )
    # controls: the real adapter ran, sent this token, and the scan sees what was stored
    assert r.status_code == 202, r.text
    assert rig.graph_calls and rig.graph_auth[-1] == f"Bearer {token}"
    assert stored.graph_rows and stored.message_count == 1
    assert reason in stored.everything
    assert reason in stored.message_error
    assert any(reason in e for e in stored.graph_errors)
    # the rule
    assert token not in stored.everything


def test_ac_41_06_a_token_with_a_space_is_scrubbed_piece_by_piece(client, session_factory, monkeypatch):
    token = "alpha-9x beta-4y"
    reason = "reason-QRS-blocked"
    r, rig, stored = _live_text_send(
        client, session_factory, monkeypatch, phone="+60700700708", token=token,
        graph=_provider_400(f"Rejected {token} because {reason}"),
    )
    assert r.status_code == 202, r.text
    assert rig.graph_auth[-1] == f"Bearer {token}"
    assert reason in stored.everything
    assert token not in stored.everything
    assert "alpha-9x" not in stored.everything
    assert "beta-4y" not in stored.everything


def test_ac_41_06_transport_error_stores_its_class_name_not_its_text(client, session_factory, monkeypatch):
    token = "tkn-c4d8e1f0a2"

    def refuse(request):
        raise httpx.ConnectError(f"connect failed using {request.headers['authorization']}")

    r, rig, stored = _live_text_send(
        client, session_factory, monkeypatch, phone="+60700700709", token=token, graph=refuse,
    )
    assert r.status_code == 202, r.text
    assert rig.graph_calls
    assert stored.graph_rows, "no provider activity row was written"
    assert any("ConnectError" in e for e in stored.graph_errors), stored.graph_errors
    assert token not in stored.everything


def test_ac_41_06_a_token_with_an_illegal_header_character(client, session_factory, monkeypatch):
    token = "tkn-ab\ncd12xy"

    def refuse(request):
        raise httpx.LocalProtocolError(f"Illegal header value {request.headers['authorization']!r}")

    r, rig, stored = _live_text_send(
        client, session_factory, monkeypatch, phone="+60700700710", token=token, graph=refuse,
    )
    assert r.status_code == 202, r.text
    assert rig.graph_auth and "tkn-ab" in rig.graph_auth[-1], "the token never reached the transport"
    assert stored.graph_rows
    assert any("LocalProtocolError" in e for e in stored.graph_errors), stored.graph_errors
    assert "tkn-ab" not in stored.everything
    assert "cd12xy" not in stored.everything


# ══ AC-41-07: the guide states the limit ═════════════════════════════════════
_SIXTY = re.compile(r"\b60\s?(?:s|sec|secs|seconds)\b", re.IGNORECASE)


def _guide_lines():
    return GUIDE.read_text(encoding="utf-8").splitlines()


def test_ac_41_07_section_4_2_states_the_sixty_second_limit():
    lines = _guide_lines()
    start = next(i for i, l in enumerate(lines) if l.startswith("### 4.2"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("### ") or lines[i].startswith("## "))
    section = "\n".join(lines[start:end])
    assert "media_fetch_failed" in section  # control: this is the right section
    assert _SIXTY.search(section), "section 4.2 does not state the 60 s limit"


def test_ac_41_07_media_fetch_failed_error_row_states_the_limit():
    rows = [l for l in _guide_lines() if l.startswith("|") and "media_fetch_failed" in l]
    assert rows, "the error row is missing"
    assert any(_SIXTY.search(r) for r in rows), rows


def test_ac_41_07_changelog_has_a_row_for_the_limit():
    lines = _guide_lines()
    first_section = next(i for i, l in enumerate(lines) if l.startswith("## 1."))
    rows = [l for l in lines[:first_section] if l.startswith("> |")]
    assert len(rows) > 5  # control: the changelog table was found
    assert any(_SIXTY.search(r) and "media" in r.lower() for r in rows), "no changelog row mentions the limit"


# ══ Behaviour to keep (these pass before the change and must still pass) ═════
def test_rig_heartbeat_sees_a_blocked_loop():
    """Control for the AC-41-01 tests: a handler that blocks the loop DOES show
    up as a large heartbeat gap and a cheap request that waits."""

    async def blocking_send(ac):
        time.sleep(1.0)  # blocks the whole loop
        return httpx.Response(202)

    out = asyncio.run(_drive(blocking_send))
    assert out.max_gap >= 0.9
    assert out.cheap_before_send_by <= 0.1


# ── AC-41-02: nothing else on the wire changes ───────────────────────────────
def test_ac_41_02_text_send_success_body(client, session_factory):
    headers, _cid, _ch = _setup(client, session_factory, phone="+60700700711")
    r = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60700700711", "type": "text", "text": {"body": "hi"}},
        headers=headers,
    )
    assert r.status_code == 202
    body = r.json()
    assert set(body) == {"id", "status", "idempotencyReplay"}
    assert body["status"] == "queued" and body["idempotencyReplay"] is False and body["id"]


def test_ac_41_02_media_by_url_success_body(client, session_factory, monkeypatch):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700712")
    rig = _install(monkeypatch, media=_pdf_media)
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700712"), headers=headers)
    assert rig.media_calls == 1
    assert r.status_code == 202, r.text
    assert set(r.json()) == {"id", "status", "idempotencyReplay"}
    assert _message_count(session_factory, cid) == 1


def test_ac_41_02_multipart_success_body(client, session_factory, monkeypatch):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700713", token="tkn-live-02")
    rig = _install(monkeypatch)
    r = client.post("/api/v1/omnichannel/messages", headers=headers, **_multipart("+60700700713"))
    assert rig.graph_calls, "the provider fake was never hit"
    assert r.status_code == 202, r.text
    assert set(r.json()) == {"id", "status", "idempotencyReplay"}
    assert _message_count(session_factory, cid) == 1


def test_ac_41_02_api_error_body_shape(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone="+60700700714", open_window=False)
    key = _mint(client, ws).json()["fullKey"]
    r = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60700700714", "type": "text", "text": {"body": "late"}},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert r.status_code == 409
    assert set(r.json()) == {"error"}
    assert r.json()["error"]["code"] == "csw_window_closed"
    assert r.json()["error"]["message"]


def test_ac_41_02_unsupported_type_and_missing_key(client, session_factory):
    headers, _cid, _ch = _setup(client, session_factory, phone="+60700700715")
    r = client.post("/api/v1/omnichannel/messages", json={"to": "+60700700715", "type": "carousel"}, headers=headers)
    assert (r.status_code, _error_code(r)) == (400, "unsupported_type")
    denied = client.post("/api/v1/omnichannel/messages", json={"to": "+60700700715", "type": "text"})
    assert denied.status_code == 401


def test_ac_41_02_validation_errors_keep_their_codes(client, session_factory):
    headers, _cid, _ch = _setup(client, session_factory, phone="+60700700716")
    bad_json = client.post(
        "/api/v1/omnichannel/messages", content=b"{not json", headers={**headers, "Content-Type": "application/json"}
    )
    assert (bad_json.status_code, _error_code(bad_json)) == (422, "invalid_request")
    no_body = client.post(
        "/api/v1/omnichannel/messages", json={"to": "+60700700716", "type": "text"}, headers=headers
    )
    assert (no_body.status_code, _error_code(no_body)) == (422, "invalid_request")
    only_payload = client.post(
        "/api/v1/omnichannel/messages", data={"payload": "{}"}, files={"other": ("x", b"y")}, headers=headers
    )
    assert (only_payload.status_code, _error_code(only_payload)) == (422, "invalid_request")
    bad_payload = client.post(
        "/api/v1/omnichannel/messages",
        data={"payload": "{not json"},
        files={"file": ("doc.pdf", PDF, "application/pdf")},
        headers=headers,
    )
    assert (bad_payload.status_code, _error_code(bad_payload)) == (422, "invalid_request")


def test_ac_41_02_idempotency_replay_returns_the_original_and_sends_once(client, session_factory, monkeypatch):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700717")
    rig = _install(monkeypatch, media=_pdf_media)
    hdr = {**headers, "Idempotency-Key": "plan41-a"}
    first = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700717"), headers=hdr)
    again = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700717"), headers=hdr)
    assert first.status_code == again.status_code == 202
    assert first.json()["idempotencyReplay"] is False and again.json()["idempotencyReplay"] is True
    assert first.json()["id"] == again.json()["id"]
    assert rig.media_calls == 1  # the replay did not fetch again
    assert _message_count(session_factory, cid) == 1


def test_ac_41_02_a_failed_send_releases_its_idempotency_key(client, session_factory, monkeypatch):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700718")
    state = {"status": 404}

    def media(request):
        if state["status"] == 404:
            return httpx.Response(404, request=request)
        return _pdf_media(request)

    _install(monkeypatch, media=media)
    hdr = {**headers, "Idempotency-Key": "plan41-b"}
    failed = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700718"), headers=hdr)
    assert (failed.status_code, _error_code(failed)) == (422, "media_fetch_failed")
    state["status"] = 200
    retry = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700718"), headers=hdr)
    assert retry.status_code == 202 and retry.json()["idempotencyReplay"] is False
    assert _message_count(session_factory, cid) == 1


def test_ac_41_02_database_session_is_closed_after_the_request(client, session_factory):
    """Counts open and close on the session the route was handed. This rig can
    prove the session is closed once per request; it cannot prove the session
    is never used by two threads at once (sqlite runs with
    check_same_thread=False and a single shared connection)."""
    from app.database import get_db

    headers, _cid, _ch = _setup(client, session_factory, phone="+60700700719")
    opened, closed = [], []

    def counting_override():
        db = session_factory()
        opened.append(db)
        real_close = db.close

        def close():
            closed.append(db)
            real_close()

        db.close = close
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = counting_override
    # control: a plain read is counted, so the counter sees requests
    assert client.get("/api/v1/omnichannel/channels", headers=headers).status_code == 200
    seen = len(opened)
    assert seen >= 1 and [id(d) for d in closed] == [id(d) for d in opened]
    r = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": "+60700700719", "type": "text", "text": {"body": "hi"}},
        headers=headers,
    )
    assert r.status_code == 202
    assert len(opened) > seen
    assert [id(d) for d in closed] == [id(d) for d in opened]


# ── AC-41-03 controls: inside the limit works ────────────────────────────────
@pytest.mark.parametrize("path", ["media", "header"])
def test_ac_41_03_drip_inside_the_total_limit_succeeds(client, session_factory, monkeypatch, path):
    phone = "+60700700720" if path == "media" else "+60700700721"
    headers, cid, _ch = _setup(client, session_factory, phone=phone, token="tkn-live-03")
    skew = _skewed_clock(monkeypatch)
    streams = []

    def drip(request):
        stream = _Stream(_pdf_chunks(5), on_chunk=lambda: skew.__setitem__(0, skew[0] + 10.0))  # 50 s
        streams.append(stream)
        return httpx.Response(200, headers={"Content-Type": "application/pdf"}, stream=stream, request=request)

    rig = _install(monkeypatch, media=drip)
    url, body = _PATHS[path](phone)
    r = client.post(url, json=body, headers=headers)
    assert r.status_code == 202, r.text
    assert streams[0].consumed == 5  # the whole body was read
    assert rig.graph_calls, "the provider fake was never hit"
    assert _message_count(session_factory, cid) == 1
    assert skew[0] >= 50.0  # control: the fake clock really moved


# ── AC-41-04 controls ────────────────────────────────────────────────────────
def test_ac_41_04_no_declared_length_over_the_cap_is_still_refused_while_reading(
    client, session_factory, monkeypatch
):
    from modules.omnichannel.services.public_gateway_service import _MEDIA_HARD_CAP

    headers, cid, _ch = _setup(client, session_factory, phone="+60700700722", token="tkn-live-04")
    big = b"x" * (30 * 1024 * 1024)
    streams = []

    def undeclared_big(request):
        stream = _Stream([PDF] + [big] * 6)  # well over the cap in total, no length header
        assert _MEDIA_HARD_CAP < 4 * len(big) < 6 * len(big)
        streams.append(stream)
        return httpx.Response(200, headers={"Content-Type": "application/pdf"}, stream=stream, request=request)

    rig = _install(monkeypatch, media=undeclared_big)
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700722"), headers=headers)
    assert (r.status_code, _error_code(r)) == (422, "oversize")
    assert streams[0].iterated is True  # control: the rig does see a read
    assert streams[0].consumed < 7, "the body was read to the end instead of stopping at the cap"
    assert rig.graph_calls == []
    assert _message_count(session_factory, cid) == 0


def test_ac_41_04_a_normal_declared_length_succeeds(client, session_factory, monkeypatch):
    headers, _cid, _ch = _setup(client, session_factory, phone="+60700700723")

    def sized(request):
        return httpx.Response(
            200,
            headers={"Content-Type": "application/pdf", "Content-Length": str(len(PDF))},
            stream=_Stream([PDF]),
            request=request,
        )

    _install(monkeypatch, media=sized)
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700723"), headers=headers)
    assert r.status_code == 202, r.text


# ── AC-41-05: the fetch's existing rules ─────────────────────────────────────
def _refused(client, session_factory, monkeypatch, *, phone, url, resolve_to=None):
    headers, cid, _ch = _setup(client, session_factory, phone=phone)
    rig = _install(monkeypatch, media=_pdf_media)
    if resolve_to:
        monkeypatch.setattr(
            "app.services.url_guard.socket.getaddrinfo",
            lambda host, port, *a, **k: [(2, 1, 6, "", (resolve_to, 0))],
        )
    r = client.post("/api/v1/omnichannel/messages", json=_media_body(phone, url), headers=headers)
    return r, rig, _message_count(session_factory, cid)


@pytest.mark.parametrize(
    "case,url,resolve_to",
    [
        ("http", f"http://{MEDIA_HOST}/doc.pdf", None),
        ("loopback literal", "https://127.0.0.1/doc.pdf", None),
        ("host resolving to a private address", f"https://{MEDIA_HOST}/doc.pdf", "10.0.0.5"),
    ],
)
def test_ac_41_05_unsafe_urls_are_refused_before_any_fetch(client, session_factory, monkeypatch, case, url, resolve_to):
    r, rig, rows = _refused(client, session_factory, monkeypatch, phone="+60700700724", url=url, resolve_to=resolve_to)
    assert (r.status_code, _error_code(r)) == (422, "invalid_media_url"), case
    assert rig.media_calls == 0
    assert rows == 0


def test_ac_41_05_a_redirect_is_refused_not_followed(client, session_factory, monkeypatch):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700725")
    rig = _install(
        monkeypatch,
        media=lambda request: httpx.Response(302, headers={"Location": "https://127.0.0.1/secret"}, request=request),
    )
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700725"), headers=headers)
    assert (r.status_code, _error_code(r)) == (422, "invalid_media_url")
    assert rig.media_calls == 1  # control: it was fetched once and not followed
    assert _message_count(session_factory, cid) == 0


def test_ac_41_05_a_public_https_url_is_accepted(client, session_factory, monkeypatch):
    r, rig, rows = _refused(
        client, session_factory, monkeypatch, phone="+60700700726", url=MEDIA_URL
    )
    assert r.status_code == 202, r.text
    assert rig.media_calls == 1 and rows == 1
