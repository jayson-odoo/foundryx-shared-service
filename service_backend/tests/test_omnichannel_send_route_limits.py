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

SLEEP = 3.0  # generous: the loop must stay free for well under this
GAP_LIMIT = 1.5  # heartbeat ticks every 50 ms; half the sleep is a wide margin

GUIDE = Path(__file__).resolve().parents[2] / "documentation" / "omnichannel" / "consumer-integration-guide.md"


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


# ── rig ──────────────────────────────────────────────────────────────────────
class _Stream(httpx.SyncByteStream, httpx.AsyncByteStream):
    """A response body (readable by a sync or an async client) that records
    whether and how far it was read. `delay` is the pause before each chunk."""

    def __init__(self, chunks, delay=0.0):
        self._chunks = chunks
        self._delay = delay
        self.iterated = False
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        self.iterated = True
        for chunk in self._chunks:
            if self._delay:
                time.sleep(self._delay)
            self.consumed += 1
            yield chunk

    async def __aiter__(self):
        self.iterated = True
        for chunk in self._chunks:
            if self._delay:
                await asyncio.sleep(self._delay)
            self.consumed += 1
            yield chunk

    def close(self):
        self.closed = True

    async def aclose(self):
        self.closed = True


def _pdf_chunks(n):
    return [PDF] + [b"x" * 1024] * (n - 1)


def _default_graph(request):
    path = request.url.path
    if path.endswith("/media"):
        return httpx.Response(200, json={"id": "MID-1"}, request=request)
    return httpx.Response(200, json={"messages": [{"id": "wamid.T1"}]}, request=request)


def _install(monkeypatch, *, media=None, graph=None, header_delay=0.0, on_fetch=None):
    """Fake every outbound call, for a sync or an async client. `rig.media_calls`
    counts fetches of the media host; `rig.graph_calls` lists the provider paths
    hit. `header_delay` pauses before the media response headers are returned."""
    rig = SimpleNamespace(media_calls=0, graph_calls=[], graph_auth=[])

    def route(request):
        host = request.url.host
        if host == GRAPH_HOST:
            rig.graph_calls.append(request.url.path)
            rig.graph_auth.append(request.headers.get("authorization", ""))
            return (graph or _default_graph)(request), 0.0
        if host == MEDIA_HOST:
            rig.media_calls += 1
            if on_fetch:
                on_fetch()
            return media(request), header_delay
        raise AssertionError(f"unexpected outbound call to {host}")

    def fake(self, request):
        resp, delay = route(request)
        if delay:
            time.sleep(delay)
        return resp

    async def fake_async(self, request):
        resp, delay = route(request)
        if delay:
            await asyncio.sleep(delay)
        return resp

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_async)
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
    body = resp.json()
    return body["error"]["code"] if isinstance(body, dict) and "error" in body else f"no error body: {resp.status_code} {resp.text[:80]}"


# ══ AC-41-01: other requests are answered while a send waits ═════════════════
def test_ac_41_01_json_media_send_leaves_the_loop_free(client, session_factory, monkeypatch):
    headers, _cid, _ch = _setup(client, session_factory, phone="+60700700701")

    _install(monkeypatch, media=_pdf_media, header_delay=SLEEP)

    async def send(ac):
        return await ac.post("/api/v1/omnichannel/messages", json=_media_body("+60700700701"), headers=headers)

    out = asyncio.run(_drive(send))
    # control: the wait really happened and the send really succeeded
    assert out.resp.status_code == 202, out.resp.text
    assert out.send_seconds >= SLEEP * 0.9
    # the rule
    assert out.max_gap < GAP_LIMIT, f"event loop was blocked for {out.max_gap:.2f}s"
    assert out.cheap_status == 200
    assert out.cheap_before_send_by > 1.0, "the cheap request waited for the send"


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
    assert out.cheap_before_send_by > 1.0, "the cheap request waited for the send"


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
    from modules.omnichannel.services import public_gateway_service as pgs

    phone = "+60700700703" if path == "media" else "+60700700704"
    headers, cid, _ch = _setup(client, session_factory, phone=phone, token="tkn-live-03")
    monkeypatch.setattr(pgs, "MEDIA_FETCH_TOTAL_SECONDS", 0.5)
    streams = []

    def drip(request):
        # every chunk arrives well inside the per-read timeout, but 40 of them
        # take 8 s against a 0.5 s total limit (budget 3 s)
        stream = _Stream(_pdf_chunks(40), delay=0.2)
        streams.append(stream)
        return httpx.Response(200, headers={"Content-Type": "application/pdf"}, stream=stream, request=request)

    rig = _install(monkeypatch, media=drip)
    before = _message_count(session_factory, cid)
    url, body = _PATHS[path](phone)
    started = time.monotonic()
    r = client.post(url, json=body, headers=headers)
    elapsed = time.monotonic() - started
    assert rig.media_calls == 1, "the fetch never happened"
    assert r.status_code == 422, r.text
    assert _error_code(r) == "media_fetch_failed"
    assert elapsed < 3.0, f"the fetch ran for {elapsed:.1f}s"
    assert streams[0].consumed < 40, "the fetch kept reading past the limit"
    assert rig.graph_calls == []
    assert _message_count(session_factory, cid) == before


def test_ac_41_03_slow_headers_over_the_total_limit_are_refused(client, session_factory, monkeypatch):
    from modules.omnichannel.services import public_gateway_service as pgs

    headers, cid, _ch = _setup(client, session_factory, phone="+60700700705", token="tkn-live-03")
    monkeypatch.setattr(pgs, "MEDIA_FETCH_TOTAL_SECONDS", 0.5)
    rig = _install(monkeypatch, media=_pdf_media, header_delay=6.0)
    before = _message_count(session_factory, cid)
    started = time.monotonic()
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700705"), headers=headers)
    elapsed = time.monotonic() - started
    assert rig.media_calls == 1
    assert r.status_code == 422, r.text
    assert _error_code(r) == "media_fetch_failed"
    assert elapsed < 3.0, f"the fetch ran for {elapsed:.1f}s"
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
    from modules.omnichannel.services import public_gateway_service as pgs

    phone = "+60700700720" if path == "media" else "+60700700721"
    headers, cid, _ch = _setup(client, session_factory, phone=phone, token="tkn-live-03")
    monkeypatch.setattr(pgs, "MEDIA_FETCH_TOTAL_SECONDS", 5.0)
    streams = []

    def drip(request):
        stream = _Stream(_pdf_chunks(5), delay=0.1)
        streams.append(stream)
        return httpx.Response(200, headers={"Content-Type": "application/pdf"}, stream=stream, request=request)

    rig = _install(monkeypatch, media=drip)
    url, body = _PATHS[path](phone)
    r = client.post(url, json=body, headers=headers)
    assert r.status_code == 202, r.text
    assert streams[0].consumed == 5  # the whole body was read
    assert rig.graph_calls, "the provider fake was never hit"
    assert _message_count(session_factory, cid) == 1


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


# ══ Review round: the deadline holds against a real peer ═════════════════════
DRIP_SECONDS = 6.0  # how long a peer drips if nothing stops it


def _frame(data: bytes) -> bytes:
    return b"%x\r\n%s\r\n" % (len(data), data)


def _drip(conn, stop, piece):
    end = time.monotonic() + DRIP_SECONDS
    while time.monotonic() < end and not stop.is_set():
        conn.sendall(piece)
        time.sleep(0.1)


_CHUNKED_PDF_HEAD = b"HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\nTransfer-Encoding: chunked\r\n"


def _peer_header_drip(conn, stop):
    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\nX-Pad: ")
    _drip(conn, stop, b"a")
    conn.sendall(b"\r\nTransfer-Encoding: chunked\r\n\r\n" + _frame(PDF) + b"0\r\n\r\n")


def _peer_empty_gzip(conn, stop):
    conn.sendall(_CHUNKED_PDF_HEAD + b"Content-Encoding: gzip\r\n\r\n")
    conn.sendall(_frame(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03"))
    _drip(conn, stop, _frame(b"\x00\x00\x00\xff\xff"))
    conn.sendall(b"0\r\n\r\n")


def _peer_body_drip(conn, stop):
    conn.sendall(_CHUNKED_PDF_HEAD + b"\r\n" + _frame(PDF))
    _drip(conn, stop, _frame(b"x"))
    conn.sendall(b"0\r\n\r\n")


def _peer_trailer_drip(conn, stop):
    conn.sendall(_CHUNKED_PDF_HEAD + b"Trailer: X-T\r\n\r\n" + _frame(PDF) + b"0\r\nX-T: ")
    _drip(conn, stop, b"a")
    conn.sendall(b"\r\n\r\n")


def _peer_stall_then_end(conn, stop):
    conn.sendall(_CHUNKED_PDF_HEAD + b"\r\n" + _frame(PDF))
    stop.wait(6.0)
    conn.sendall(b"0\r\n\r\n")


@pytest.fixture
def local_peer(monkeypatch):
    """Start real listening sockets on 127.0.0.1 (ephemeral ports) and allow
    local http URLs in the fetch's URL check, for this test only. Everything is
    shut down afterwards."""
    import socket
    import threading

    from modules.omnichannel.services import webhook_service

    monkeypatch.setattr(webhook_service, "validate_callback_url", lambda url, **k: url)
    stop = threading.Event()
    listeners = []

    def start(handler):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(5)
        srv.settimeout(0.2)
        listeners.append(srv)

        def serve(conn):
            try:
                conn.settimeout(10)
                conn.recv(65536)
                handler(conn, stop)
            except OSError:
                pass
            finally:
                conn.close()

        def accept_loop():
            while not stop.is_set():
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    return
                threading.Thread(target=serve, args=(conn,), daemon=True).start()

        threading.Thread(target=accept_loop, daemon=True).start()
        return f"http://127.0.0.1:{srv.getsockname()[1]}/file"

    yield start
    stop.set()
    for srv in listeners:
        srv.close()


_PEERS = {
    "headers-dripped": (_peer_header_drip, 3.0),
    "empty-compressed-body": (_peer_empty_gzip, 3.0),  # refused early now: still fast
    "trailers-dripped": (_peer_trailer_drip, 3.0),
    "plain-body-dripped": (_peer_body_drip, 3.0),
    "clean-end-after-the-limit": (_peer_stall_then_end, 3.0),
}


@pytest.mark.parametrize("path", ["media", "header"])
@pytest.mark.parametrize("peer", sorted(_PEERS))
def test_ac_41_03_real_peer_cannot_extend_the_total_limit(client, session_factory, monkeypatch, local_peer, peer, path):
    from modules.omnichannel.services import public_gateway_service as pgs

    handler, max_elapsed = _PEERS[peer]
    phone = "+60700700730" if path == "media" else "+60700700731"
    headers, cid, _ch = _setup(client, session_factory, phone=phone)
    monkeypatch.setattr(pgs, "MEDIA_FETCH_TOTAL_SECONDS", 0.5)
    url = local_peer(handler)
    body = _media_body(phone, url) if path == "media" else _header_body(phone, url)
    started = time.monotonic()
    r = client.post("/api/v1/omnichannel/messages", json=body, headers=headers)
    elapsed = time.monotonic() - started
    print(f"peer-elapsed {peer}/{path} {elapsed:.2f}s of {max_elapsed}s")
    assert r.status_code == 422, f"{r.status_code} {r.text} after {elapsed:.1f}s"
    assert _error_code(r) == "media_fetch_failed", f"{r.text} after {elapsed:.1f}s"
    assert elapsed < max_elapsed, f"the fetch ran for {elapsed:.1f}s against a 0.5 s limit"
    assert _message_count(session_factory, cid) == 0


# ── AC-41-08: no transaction is held while the fetch runs ────────────────────
@pytest.mark.parametrize("path", ["media", "header"])
def test_ac_41_08_no_transaction_is_open_while_the_fetch_runs(client, session_factory, monkeypatch, path):
    import weakref

    from sqlalchemy import event, text
    from sqlalchemy.orm import Session

    phone = "+60700700732" if path == "media" else "+60700700733"
    headers, cid, _ch = _setup(client, session_factory, phone=phone)
    seen = weakref.WeakSet()

    def track(session, transaction, connection):
        seen.add(session)

    def open_now():
        return [s for s in list(seen) if s.in_transaction()]

    event.listen(Session, "after_begin", track)
    try:
        # control: the tracker sees a session that is in a transaction, and
        # stops seeing it once it is closed
        probe = session_factory()
        probe.execute(text("select 1"))
        assert len(open_now()) == 1
        probe.close()
        assert open_now() == []

        at_fetch = []
        rig = _install(monkeypatch, media=_pdf_media, on_fetch=lambda: at_fetch.append(len(open_now())))
        url, body = _PATHS[path](phone)
        r = client.post(url, json=body, headers=headers)
    finally:
        event.remove(Session, "after_begin", track)
    assert r.status_code == 202, r.text
    assert rig.media_calls == 1 and len(at_fetch) == 1, "the fetch hook never ran"
    assert at_fetch == [0], f"{at_fetch[0]} session(s) held a transaction during the fetch"


# ── AC-41-09: an address the client cannot process is a typed 422 ────────────
@pytest.mark.parametrize(
    "case,url",
    [
        ("invalid idna label", "https://xn--a.b/"),
        ("url too long", f"https://{MEDIA_HOST}/" + "a" * 70000),
    ],
)
def test_ac_41_09_unprocessable_media_url_is_media_fetch_failed(client, session_factory, monkeypatch, case, url):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700734")
    _install(monkeypatch, media=_pdf_media)
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700734", url), headers=headers)
    assert r.status_code == 422, f"{case}: {r.status_code}"
    assert _error_code(r) == "media_fetch_failed", case
    assert _message_count(session_factory, cid) == 0


def test_ac_41_09_unprocessable_redirect_target_is_a_typed_422(client, session_factory, monkeypatch):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700735")
    _install(
        monkeypatch,
        media=lambda request: httpx.Response(302, headers={"Location": "https://xn--a.b/"}, request=request),
    )
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700735"), headers=headers)
    assert r.status_code == 422, r.status_code
    assert _error_code(r) in ("invalid_media_url", "media_fetch_failed")
    assert _message_count(session_factory, cid) == 0


# ── AC-41-07: the guide states the 100 MB early refusal ──────────────────────
def test_ac_41_07_section_4_2_states_the_early_refusal_ceiling():
    lines = _guide_lines()
    start = next(i for i, l in enumerate(lines) if l.startswith("### 4.2"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("### ") or lines[i].startswith("## "))
    declared = [l for l in lines[start:end] if "before its body" in l]
    assert declared, "section 4.2 lost the early refusal sentence"  # control
    assert any(re.search(r"100\s?MB", l) for l in declared), declared


# ── AC-41-04: a non-ASCII digit in Content-Length never raises ───────────────
def test_ac_41_04_non_ascii_digits_in_the_declared_length_stay_typed(client, session_factory, monkeypatch):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700736")

    def odd_length(request):
        return httpx.Response(
            200,
            headers=[(b"content-type", b"application/pdf"), (b"content-length", b"\xc2\xb2")],
            stream=_Stream([PDF]),
            request=request,
        )

    rig = _install(monkeypatch, media=odd_length)
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700736"), headers=headers)
    assert rig.media_calls == 1
    assert r.status_code == 202, r.status_code
    assert _message_count(session_factory, cid) == 1


# ── Idempotency: the in-memory claim is atomic ───────────────────────────────
class _RendezvousDict(dict):
    """A dict whose reads wait (up to 1 s) for a second reader, so two threads
    that both read before either writes are forced to overlap. A store that
    locks its check-then-set times the wait out and stays correct."""

    def __init__(self):
        super().__init__()
        import threading

        self._barrier = threading.Barrier(2, timeout=1.0)

    def _meet(self):
        import threading

        try:
            self._barrier.wait()
        except threading.BrokenBarrierError:
            pass

    def __contains__(self, key):
        found = super().__contains__(key)
        self._meet()
        return found

    def get(self, key, default=None):
        value = super().get(key, default)
        self._meet()
        return value

    def setdefault(self, key, default=None):
        value = super().setdefault(key, default)
        self._meet()
        return value


def _race(store):
    import threading

    results = []
    lock = threading.Lock()

    def claim():
        got = store.reserve("ws-race", "same-key")
        with lock:
            results.append(got)

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    return results


def test_idempotency_memory_claim_is_atomic_under_two_threads():
    store = idempotency.MemoryIdempotencyStore()
    store._memory = _RendezvousDict()
    results = _race(store)
    assert len(results) == 2
    assert results.count(None) == 1, f"both threads claimed the key: {results}"
    assert idempotency.PENDING in results


def test_idempotency_race_rig_sees_a_non_atomic_claim():
    """Control: the same rig catches a claim that checks and sets separately."""

    class NaiveStore(idempotency.MemoryIdempotencyStore):
        def reserve(self, workspace_id, idem_key):
            k = idempotency._key(workspace_id, idem_key)
            if k in self._memory:
                return self._memory[k]
            self._memory[k] = idempotency.PENDING
            return None

    store = NaiveStore()
    store._memory = _RendezvousDict()
    results = _race(store)
    assert results.count(None) == 2


# ══ Review round 2 ═══════════════════════════════════════════════════════════
# ── AC-41-10: fetch slots ────────────────────────────────────────────────────
def test_ac_41_10_limits_are_four_and_two():
    from modules.omnichannel.services import public_gateway_service as pgs

    assert pgs.MEDIA_FETCH_MAX_CONCURRENT == 4
    assert pgs.MEDIA_FETCH_MAX_PER_TENANT == 2


def _tenant_login(client, session_factory, slug):
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
    tenant_id = tenant.id
    db.close()
    res = client.post(
        "/auth/login",
        json={"email": f"admin-{slug}@example.com", "password": "Password123!", "tenantSlug": slug},
    )
    return tenant_id, {"Authorization": f"Bearer {res.json()['access_token']}"}


def _gate_world(client, session_factory, *, contacts, slug=None):
    """Channel, open-window contacts and three API keys (a, b, c) in one tenant:
    the default tenant, or a freshly provisioned one named `slug`."""
    from modules.omnichannel.models import Channel, Contact, Workspace
    from modules.omnichannel.security import encrypt_credentials
    from modules.omnichannel.services import statuses

    if slug is None:
        ws = _default_workspace_id(session_factory)
        _seed_channel(session_factory, ws)
        tenant_id, admin = DEFAULT_TENANT_ID, None
        phones = [f"+607007009{i:02d}" for i in range(contacts)]
        cids = {ph: _seed_open_contact(session_factory, ws, phone=ph, open_window=True) for ph in phones}
        keys = {n: {"Authorization": "Bearer " + _mint(client, ws, n).json()["fullKey"]} for n in ("a", "b", "c")}
        return phones, cids, keys
    tenant_id, admin = _tenant_login(client, session_factory, slug)
    db = session_factory()
    ws = db.query(Workspace).filter(Workspace.tenant_id == tenant_id, Workspace.is_default.is_(True)).first().id
    db.add(Channel(
        tenant_id=tenant_id, workspace_id=ws, channel_type="WHATSAPP", name=f"{slug} WA",
        credentials_json=encrypt_credentials({"dev": True}), phone_number_id=f"pn-{slug}"[:30],
        display_phone_number="+60 11-111 1111", is_active=True,
        status_id=statuses.status_id_for(db, tenant_id, "CHANNEL", "ACTIVE"),
    ))
    phones = [f"+607008{abs(hash(slug)) % 100:02d}{i:02d}" for i in range(contacts)]
    cids = {}
    for ph in phones:
        c = Contact(
            tenant_id=tenant_id, workspace_id=ws, first_name="Sam", phone=ph,
            status_id=statuses.status_id_for(db, tenant_id, "THREAD", "OPEN"), priority="MEDIUM",
            csw_expires_at=datetime.now(timezone.utc) + timedelta(hours=20),
        )
        db.add(c)
        db.flush()
        cids[ph] = c.id
    db.commit()
    db.close()
    keys = {}
    for n in ("a", "b", "c"):
        res = client.post(f"/omnichannel/workspaces/{ws}/api-keys", json={"name": n}, headers=admin)
        keys[n] = {"Authorization": "Bearer " + res.json()["fullKey"]}
    return phones, cids, keys


async def _wait_for(predicate, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


def _post_media(ac, headers, phone, *, header_path=False, idem=None):
    body = _header_body(phone) if header_path else _media_body(phone)
    h = dict(headers)
    if idem:
        h["Idempotency-Key"] = idem
    return ac.post("/api/v1/omnichannel/messages", json=body, headers=h)


@pytest.mark.parametrize("held_path", ["media", "header"])
def test_ac_41_10_per_tenant_and_process_limits(client, session_factory, monkeypatch, held_path):
    import threading

    phones, cids, keys = _gate_world(client, session_factory, contacts=8)
    phones2, cids2, keys2 = _gate_world(client, session_factory, contacts=4, slug="gate-two")
    phones3, cids3, keys3 = _gate_world(client, session_factory, contacts=4, slug="gate-three")
    release = threading.Semaphore(0)  # one permit lets one held fetch finish
    started = []

    def hold():
        started.append(1)
        release.acquire(timeout=6)

    rig = _install(monkeypatch, media=_pdf_media, on_fetch=hold)
    hp = held_path == "header"

    async def scenario():
        out = {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as ac:
            held = []
            try:
                # two DIFFERENT keys of one tenant share its 2 slots; a second tenant
                # then takes 2 more: the process is full
                plan = [
                    (keys["a"], phones[0]), (keys["b"], phones[1]),
                    (keys2["a"], phones2[0]), (keys2["b"], phones2[1]),
                ]
                for i, (key, phone) in enumerate(plan):
                    held.append(asyncio.create_task(_post_media(ac, key, phone, header_path=hp)))
                    assert await _wait_for(lambda n=i + 1: len(started) >= n), f"fetch {i + 1} never started"
                    if i == 1:
                        # the tenant is full while the process still has room
                        t0 = time.monotonic()
                        out["third_in_tenant"] = await _post_media(
                            ac, keys["c"], phones[2], header_path=hp, idem="retry-me"
                        )
                        out["third_secs"] = time.monotonic() - t0
                        assert len(started) == 2, "a send over the tenant limit started a fetch"
                calls_when_full = rig.media_calls
                out["third_tenant"] = await _post_media(ac, keys3["a"], phones3[0], header_path=hp)
                out["text_in_full_process"] = await ac.post(
                    "/api/v1/omnichannel/messages",
                    json={"to": phones3[1], "type": "text", "text": {"body": "hi"}},
                    headers=keys3["a"],
                )
                out["extra_fetches"] = rig.media_calls - calls_when_full
                out["held"] = []
                for t in held:
                    release.release()
                    out["held"].append(await t)
            finally:
                for _ in range(len(held) + 2):
                    release.release()
            out["retry"] = await _post_media(ac, keys["c"], phones[2], header_path=hp, idem="retry-me")
        return out

    out = asyncio.run(scenario())
    assert [r.status_code for r in out["held"]] == [202] * 4
    third = out["third_in_tenant"]
    assert (third.status_code, _error_code(third)) == (429, "media_fetch_busy")
    assert out["third_secs"] < 3.0, "the busy answer was not immediate"
    other = out["third_tenant"]
    assert (other.status_code, _error_code(other)) == (429, "media_fetch_busy")
    assert out["extra_fetches"] == 0, "a refused send still fetched"
    assert out["text_in_full_process"].status_code == 202
    assert _message_count(session_factory, cids3[phones3[0]]) == 0
    assert out["retry"].status_code == 202 and out["retry"].json()["idempotencyReplay"] is False
    assert _message_count(session_factory, cids[phones[2]]) == 1


def test_ac_41_10_a_slot_is_freed_on_every_outcome(client, session_factory, monkeypatch):
    from fastapi.testclient import TestClient

    from modules.omnichannel.services import public_gateway_service as pgs

    phones, cids, keys = _gate_world(client, session_factory, contacts=14)
    mode = {"v": "ok"}

    def media(request):
        if mode["v"] == "404":
            return httpx.Response(404, request=request)
        if mode["v"] == "boom":
            raise RuntimeError("unexpected")
        return _pdf_media(request)

    monkeypatch.setattr(pgs, "MEDIA_FETCH_TOTAL_SECONDS", 0.4)
    rig = _install(monkeypatch, media=media)
    lenient = TestClient(app, raise_server_exceptions=False)
    statuses_seen = []
    # 3 rounds x 4 outcomes = 12 fetches on one key: more than 4 in total and
    # more than 2 for the key, so a slot that was not freed would show as a 429
    for rnd in range(3):
        for outcome in ("ok", "404", "slow", "boom"):
            mode["v"] = "ok" if outcome == "slow" else outcome
            rig_delay = 1.2 if outcome == "slow" else 0.0
            monkeypatch.undo()
            monkeypatch.setattr(pgs, "MEDIA_FETCH_TOTAL_SECONDS", 0.4)
            rig = _install(monkeypatch, media=media, header_delay=rig_delay)
            r = lenient.post(
                "/api/v1/omnichannel/messages", json=_media_body(phones[rnd * 4]), headers=keys["a"]
            )
            assert r.status_code != 429, f"round {rnd} {outcome}: a slot was not freed"
            statuses_seen.append(r.status_code)
    mode["v"] = "ok"
    monkeypatch.undo()
    rig = _install(monkeypatch, media=media)
    final = client.post("/api/v1/omnichannel/messages", json=_media_body(phones[13]), headers=keys["a"])
    assert final.status_code == 202, final.text
    assert 202 in statuses_seen and 422 in statuses_seen  # control: outcomes really differed


# ── AC-41-04: no compression ─────────────────────────────────────────────────
def _gzip(data: bytes) -> bytes:
    import gzip

    return gzip.compress(data)


@pytest.mark.parametrize("encoding,wrap", [("gzip", 1), ("gzip, gzip", 2)])
def test_ac_41_04_compressed_responses_are_refused_and_none_is_asked_for(
    client, session_factory, monkeypatch, encoding, wrap
):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700740")
    asked = []
    payload = PDF
    for _ in range(wrap):
        payload = _gzip(payload)

    def compressed(request):
        asked.append(request.headers.get("accept-encoding"))
        return httpx.Response(
            200,
            headers=[(b"content-type", b"application/pdf"), (b"content-encoding", encoding.encode())],
            stream=_Stream([payload]),
            request=request,
        )

    _install(monkeypatch, media=compressed)
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700740"), headers=headers)
    assert asked == ["identity"], asked
    assert (r.status_code, _error_code(r)) == (422, "media_fetch_failed")
    assert _message_count(session_factory, cid) == 0


def test_ac_41_04_small_double_compressed_body_is_never_decoded(client, session_factory, monkeypatch, local_peer):
    import httpx._decoders as decoders

    headers, cid, _ch = _setup(client, session_factory, phone="+60700700741")
    payload = _gzip(_gzip(b"\0" * (60 * 1024 * 1024)))
    assert len(payload) < 200_000  # control: it really is small
    decoded = [0]
    real_decode = decoders.GZipDecoder.decode

    def counting(self, data):
        out = real_decode(self, data)
        decoded[0] += len(out)
        return out

    monkeypatch.setattr(decoders.GZipDecoder, "decode", counting)

    def peer(conn, stop):
        conn.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\nContent-Encoding: gzip, gzip\r\n"
            b"Content-Length: %d\r\n\r\n" % len(payload)
        )
        conn.sendall(payload)

    url = local_peer(peer)
    started = time.monotonic()
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700741", url), headers=headers)
    assert (r.status_code, _error_code(r)) == (422, "media_fetch_failed")
    assert decoded[0] == 0, f"{decoded[0]} decoded bytes were produced"
    assert time.monotonic() - started < 3.0
    assert _message_count(session_factory, cid) == 0


# ── AC-41-09: more unprocessable addresses, and fixed wording ────────────────
@pytest.mark.parametrize(
    "case,url",
    [
        ("unclosed ipv6 bracket", "https://[::1/x"),
        ("port is not a number", f"https://{MEDIA_HOST}:abc/x"),
        ("control character", f"https://{MEDIA_HOST}/a\x01b"),
    ],
)
def test_ac_41_09_more_unprocessable_addresses(client, session_factory, monkeypatch, case, url):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700742")
    _install(monkeypatch, media=_pdf_media)
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700742", url), headers=headers)
    assert (r.status_code, _error_code(r)) == (422, "media_fetch_failed"), case
    assert _message_count(session_factory, cid) == 0


def test_ac_41_09_remote_bytes_do_not_reach_the_answer(client, session_factory, monkeypatch, local_peer):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700743")

    def peer(conn, stop):
        conn.sendall(b"HTTP/1.1 200 OK\r\nBad Header REMOTEMARK7Q\r\n\r\n")

    url = local_peer(peer)
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700743", url), headers=headers)
    assert (r.status_code, _error_code(r)) == (422, "media_fetch_failed")
    assert "REMOTEMARK7Q" not in r.text
    assert "127.0.0.1" not in r.text


# ── AC-41-06: exception chain and a None token ───────────────────────────────
def _adapter(handler):
    from modules.omnichannel.adapters.whatsapp_cloud import WhatsAppCloudAdapter

    return WhatsAppCloudAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _call(adapter, path, creds):
    if path == "send":
        return adapter.send(creds, "pn-1", "60700700701", text="hi")
    return adapter.upload_media(creds, "pn-1", PDF, "application/pdf")


@pytest.mark.parametrize("path", ["send", "upload"])
def test_ac_41_06_exception_chain_holds_no_token(monkeypatch, path):
    import traceback

    from modules.omnichannel.adapters.base import SendError

    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")
    token = "tkn-chain-81f2\n"

    def refuse(request):
        raise httpx.ConnectError(f"refused {request.headers['authorization']!r} {request.headers['authorization']}")

    with pytest.raises(SendError) as info:
        _call(_adapter(refuse), path, {"access_token": token})
    exc = info.value
    assert "ConnectError" in str(exc)
    assert exc.transient is True
    rendered = "".join(traceback.format_exception(exc))
    assert "ConnectError" in rendered  # control: the chain is part of the rendered text
    assert "tkn-chain-81f2" not in rendered
    chain = [exc.__cause__, exc.__context__]
    assert all("tkn-chain-81f2" not in repr(getattr(c, "args", "")) for c in chain if c is not None)


def test_ac_41_06_upload_with_no_token_leaves_ordinary_words_alone(monkeypatch):
    from modules.omnichannel.adapters.base import SendError

    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")

    def reject(request):
        return httpx.Response(
            400, json={"error": {"message": "None of the files was valid: reason-NN", "code": 100}}, request=request
        )

    with pytest.raises(SendError) as info:
        _call(_adapter(reject), "upload", {"access_token": None})
    assert "None of the files was valid" in str(info.value)
    assert "reason-NN" in str(info.value)


# ══ Review round guards (these pass before the next change and must keep passing)
def _meta_on(monkeypatch):
    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    monkeypatch.setattr(settings, "meta_app_secret", "test-app-secret")


def _reply_400(text):
    return lambda request: httpx.Response(400, json={"error": {"message": text, "code": 100}}, request=request)


def _refuse_with_header(request):
    raise httpx.ConnectError(f"refused {request.headers['authorization']}")


@pytest.mark.parametrize("path", ["send", "upload"])
def test_guard_ac_41_06_provider_text_keeps_reason_and_loses_token(monkeypatch, path):
    from modules.omnichannel.adapters.base import SendError

    _meta_on(monkeypatch)
    token = "tkn-up-81f2c9"
    with pytest.raises(SendError) as info:
        _call(_adapter(_reply_400(f"Rejected {token} reason-UP1")), path, {"access_token": token})
    assert "reason-UP1" in str(info.value)
    assert token not in str(info.value)
    assert info.value.transient is False


@pytest.mark.parametrize("path", ["send", "upload"])
def test_guard_ac_41_06_transport_error_stores_class_name_only(monkeypatch, path):
    from modules.omnichannel.adapters.base import SendError

    _meta_on(monkeypatch)
    token = "tkn-tr-4471d0"
    with pytest.raises(SendError) as info:
        _call(_adapter(_refuse_with_header), path, {"access_token": token})
    assert "ConnectError" in str(info.value)
    assert token not in str(info.value)
    assert info.value.transient is True  # keeps its retry behaviour


@pytest.mark.parametrize("path", ["send", "upload"])
def test_guard_ac_41_06_token_pieces_are_removed_where_they_stand_apart(monkeypatch, path):
    from modules.omnichannel.adapters.base import SendError

    _meta_on(monkeypatch)
    token = "alpha-9x beta-4y"
    text = "first alpha-9x then reason-QRS and beta-4y later"
    with pytest.raises(SendError) as info:
        _call(_adapter(_reply_400(text)), path, {"access_token": token})
    assert "reason-QRS" in str(info.value)  # control: the text is kept
    assert "alpha-9x" not in str(info.value)
    assert "beta-4y" not in str(info.value)


@pytest.mark.parametrize("path", ["send", "upload"])
def test_guard_ac_41_06_short_pieces_do_not_mangle_ordinary_words(monkeypatch, path):
    from modules.omnichannel.adapters.base import SendError

    _meta_on(monkeypatch)
    token = "tkn-77ab9 to"
    with pytest.raises(SendError) as info:
        _call(_adapter(_reply_400("Failed to deliver to the number: reason-SH")), path, {"access_token": token})
    assert str(info.value) == "Failed to deliver to the number: reason-SH"


@pytest.mark.parametrize("path", ["send", "upload"])
def test_guard_ac_41_06_token_is_removed_before_the_text_is_capped(monkeypatch, path):
    from modules.omnichannel.adapters.base import SendError

    _meta_on(monkeypatch)
    token = "tkn-7f3a9c1e2b"
    text = "reason-B6 " + "word " * 56 + token  # the token straddles the 300 character cap
    with pytest.raises(SendError) as info:
        _call(_adapter(_reply_400(text)), path, {"access_token": token})
    assert "reason-B6" in str(info.value)
    assert "tkn-" not in str(info.value)


def test_guard_ac_41_02_multipart_replay_returns_the_original_and_sends_once(client, session_factory, monkeypatch):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700750", token="tkn-live-b4")
    rig = _install(monkeypatch)
    hdr = {**headers, "Idempotency-Key": "plan41-multipart"}
    first = client.post("/api/v1/omnichannel/messages", headers=hdr, **_multipart("+60700700750"))
    uploads_after_first = rig.graph_calls.count(rig.graph_calls[0]) if rig.graph_calls else 0
    again = client.post("/api/v1/omnichannel/messages", headers=hdr, **_multipart("+60700700750"))
    assert first.status_code == again.status_code == 202
    assert first.json()["idempotencyReplay"] is False and again.json()["idempotencyReplay"] is True
    assert first.json()["id"] == again.json()["id"]
    assert uploads_after_first >= 1  # control: the provider fake saw the first send
    assert len(rig.graph_calls) == 2  # one upload and one send in total, none for the replay
    assert _message_count(session_factory, cid) == 1


def test_guard_ac_41_04_a_404_with_a_large_declared_length_stays_a_fetch_failure(client, session_factory, monkeypatch):
    from modules.omnichannel.services.public_gateway_service import _MEDIA_HARD_CAP

    headers, cid, _ch = _setup(client, session_factory, phone="+60700700751")

    def big_404(request):
        return httpx.Response(
            404, headers={"Content-Length": str(_MEDIA_HARD_CAP + 1000)}, stream=_Stream([b"nope"]), request=request
        )

    rig = _install(monkeypatch, media=big_404)
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700751"), headers=headers)
    assert rig.media_calls == 1
    assert (r.status_code, _error_code(r)) == (422, "media_fetch_failed")
    assert _message_count(session_factory, cid) == 0


# ══ Fetch errors ═════════════════════════════════════════════════════════════
def _raise_ssl(request):
    import ssl

    raise ssl.SSLError("BADTLSMARK1 record layer failure")


def _raise_group(request):
    raise ExceptionGroup("grouped", [OSError("BADTLSMARK2 connection detail")])


def _raise_runtime(request):
    raise RuntimeError("BADTLSMARK3 unexpected")


@pytest.mark.parametrize("path", ["media", "header"])
@pytest.mark.parametrize(
    "raiser,marker", [(_raise_ssl, "BADTLSMARK1"), (_raise_group, "BADTLSMARK2"), (_raise_runtime, "BADTLSMARK3")]
)
def test_ac_41_09_any_error_during_the_fetch_is_a_fixed_422(client, session_factory, monkeypatch, path, raiser, marker):
    phone = "+60700700760" if path == "media" else "+60700700761"
    headers, cid, _ch = _setup(client, session_factory, phone=phone, token="tkn-live-09")
    rig = _install(monkeypatch, media=raiser)
    url, body = _PATHS[path](phone)
    r = client.post(url, json=body, headers=headers)
    assert rig.media_calls == 1, "the fetch never happened"
    assert (r.status_code, _error_code(r)) == (422, "media_fetch_failed")
    assert marker not in r.text
    assert rig.graph_calls == []
    assert _message_count(session_factory, cid) == 0


def test_ac_41_09_real_client_on_an_impossible_port_is_a_422(client, session_factory, monkeypatch, local_peer):
    # `local_peer` only allows local http URLs through the URL check here; no
    # server is started and nothing outside this machine is contacted
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700762")
    r = client.post(
        "/api/v1/omnichannel/messages",
        json=_media_body("+60700700762", "http://127.0.0.1:99999/x"),
        headers=headers,
    )
    assert r.status_code == 422, r.status_code
    assert _error_code(r) in ("media_fetch_failed", "invalid_media_url")
    assert _message_count(session_factory, cid) == 0


@pytest.mark.parametrize("value", [123, [1, 2], {"a": 1}, True, 1.5], ids=["int", "list", "dict", "bool", "float"])
def test_ac_41_09_a_header_url_that_is_not_text_is_refused(client, session_factory, monkeypatch, value):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700763", token="tkn-live-09")
    rig = _install(monkeypatch, media=_pdf_media)
    body = _header_body("+60700700763")
    body["interactive"]["header"]["url"] = value
    r = client.post("/api/v1/omnichannel/messages", json=body, headers=headers)
    assert (r.status_code, _error_code(r)) == (422, "invalid_media_url")
    assert rig.media_calls == 0 and rig.graph_calls == []
    assert _message_count(session_factory, cid) == 0


# ══ Guide: error table and limits ════════════════════════════════════════════
_PER_KEY = re.compile(r"per[ -](?:API[ -])?key", re.IGNORECASE)


def test_ac_41_07_error_table_states_the_size_refusal_and_the_compression_rule():
    rows = [l for l in _guide_lines() if l.startswith("|")]
    assert any("`oversize`" in r for r in rows)  # control: the table was found
    assert any("oversize" in r and re.search(r"100\s?MB", r) for r in rows), "no table row names the 100 MB refusal"
    assert any(re.search(r"compress|Content-Encoding", r, re.IGNORECASE) for r in rows), "no table row names compression"


_PER_TENANT = re.compile(r"per[ -]tenant", re.IGNORECASE)


def test_ac_41_07_busy_answer_is_described_per_tenant_everywhere():
    lines = _guide_lines()
    start = next(i for i, l in enumerate(lines) if l.startswith("### 4.2"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("### ") or lines[i].startswith("## "))
    first_section = next(i for i, l in enumerate(lines) if l.startswith("## 1."))
    places = {
        "section 4.2": [l for l in lines[start:end] if "media_fetch_busy" in l],
        "error table": [l for l in lines if l.startswith("| `media_fetch_busy`")],
        "changelog": [l for l in lines[:first_section] if l.startswith("> |") and "media_fetch_busy" in l],
    }
    for where, found in places.items():
        assert found, f"{where}: the busy answer is not described"
        assert any(_PER_TENANT.search(l) for l in found), f"{where} does not say per tenant"
        assert not any(_PER_KEY.search(l) for l in found), f"{where} still says per key"


# ══ Gate guards ══════════════════════════════════════════════════════════════
def test_guard_ac_41_10_the_per_tenant_limit_alone_refuses_a_third_fetch(client, session_factory, monkeypatch):
    import threading

    phones, cids, keys = _gate_world(client, session_factory, contacts=6)
    phones2, cids2, keys2 = _gate_world(client, session_factory, contacts=2, slug="gate-guard")
    release = threading.Semaphore(0)
    started = []

    def hold():
        started.append(1)
        release.acquire(timeout=6)

    rig = _install(monkeypatch, media=_pdf_media, on_fetch=hold)

    async def scenario():
        out = {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as ac:
            held = []
            try:
                for i, name in enumerate(["a", "b"]):  # two keys, two slots: the process is far from full
                    held.append(asyncio.create_task(_post_media(ac, keys[name], phones[i])))
                    assert await _wait_for(lambda n=i + 1: len(started) >= n)
                out["third_on_c"] = await _post_media(ac, keys["c"], phones[2])
                out["fetches_after_refusal"] = rig.media_calls
                held.append(asyncio.create_task(_post_media(ac, keys2["a"], phones2[0])))
                assert await _wait_for(lambda: len(started) >= 3), "another tenant was refused"
                out["held"] = []
                for t in held:
                    release.release()
                    out["held"].append(await t)
            finally:
                for _ in range(len(held)):
                    release.release()
        return out

    out = asyncio.run(scenario())
    third = out["third_on_c"]
    assert (third.status_code, _error_code(third)) == (429, "media_fetch_busy")
    assert out["fetches_after_refusal"] == 2
    assert [r.status_code for r in out["held"]] == [202, 202, 202]
    assert _message_count(session_factory, cids[phones[2]]) == 0


def _gate_state(gate):
    """Name-agnostic view of the gate: (sum of its counters, number of dict entries)."""
    values = list(vars(gate).values())
    counters = sum(v for v in values if isinstance(v, int) and not isinstance(v, bool))
    entries = sum(len(v) for v in values if isinstance(v, dict))
    return counters, entries


def test_guard_ac_41_10_the_gate_keeps_no_entry_once_fetches_end(client, session_factory, monkeypatch):
    from modules.omnichannel.services import public_gateway_service as pgs

    phones, cids, keys = _gate_world(client, session_factory, contacts=4)
    during = []
    state = {"v": "ok"}

    def media(request):
        if state["v"] == "404":
            return httpx.Response(404, request=request)
        return _pdf_media(request)

    _install(monkeypatch, media=media, on_fetch=lambda: during.append(_gate_state(pgs._FETCH_GATE)))
    for i, outcome in enumerate(["ok", "404", "ok"]):
        state["v"] = outcome
        client.post("/api/v1/omnichannel/messages", json=_media_body(phones[i]), headers=keys["a"])
    assert len(during) == 3
    assert all(counters >= 1 and entries >= 1 for counters, entries in during)  # control: the gate is seen in use
    assert _gate_state(pgs._FETCH_GATE) == (0, 0)

# ══ The slot covers the lookup and the store ═════════════════════════════════
def test_ac_41_10_a_send_held_in_the_url_lookup_counts_against_both_limits(client, session_factory, monkeypatch):
    import threading

    from modules.omnichannel.services import webhook_service

    phones, cids, keys = _gate_world(client, session_factory, contacts=4)
    phones2, cids2, keys2 = _gate_world(client, session_factory, contacts=4, slug="gate-lookup-two")
    phones3, cids3, keys3 = _gate_world(client, session_factory, contacts=2, slug="gate-lookup-three")
    release = threading.Semaphore(0)
    in_lookup = []
    rig = _install(monkeypatch, media=_pdf_media)

    def slow_lookup(url, **kwargs):
        in_lookup.append(url)
        release.acquire(timeout=6)
        return url

    monkeypatch.setattr(webhook_service, "validate_callback_url", slow_lookup)

    async def scenario():
        out = {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as ac:
            held = []
            try:
                plan = [(keys["a"], phones[0]), (keys["b"], phones[1]), (keys2["a"], phones2[0]), (keys2["b"], phones2[1])]
                for i, (key, phone) in enumerate(plan):
                    held.append(asyncio.create_task(_post_media(ac, key, phone)))
                    assert await _wait_for(lambda n=i + 1: len(in_lookup) >= n), f"send {i + 1} never reached the lookup"
                try:
                    out["tenant_full"] = await asyncio.wait_for(_post_media(ac, keys["c"], phones[2]), 3.0)
                    out["process_full"] = await asyncio.wait_for(_post_media(ac, keys3["a"], phones3[0]), 3.0)
                except asyncio.TimeoutError:
                    out["queued_into_lookup"] = True
                out["lookups_started"] = len(in_lookup)
                if "queued_into_lookup" not in out:
                    out["held"] = []
                    for t in held:  # one at a time: the test database is one shared connection
                        release.release()
                        out["held"].append(await t)
            finally:
                for _ in range(12):
                    release.release()
        return out

    out = asyncio.run(scenario())
    assert "queued_into_lookup" not in out, "a send over the limit waited in the lookup instead of being refused"
    for which in ("tenant_full", "process_full"):
        assert (out[which].status_code, _error_code(out[which])) == (429, "media_fetch_busy"), which
    assert out["lookups_started"] == 4, "a refused send still reached the lookup"
    assert [r.status_code for r in out["held"]] == [202] * 4
    assert _message_count(session_factory, cids[phones[2]]) == 0
    assert _message_count(session_factory, cids3[phones3[0]]) == 0


def _hold_storage_writes(monkeypatch, *, release=None, on_save=None):
    """Wrap the storage object `storage_for_tenant` returns so `save` can be
    observed and held; everything else passes straight through."""
    import app.services.storage as storage

    real = storage.storage_for_tenant
    calls = []

    class Wrapped:
        def __init__(self, inner):
            self._inner = inner

        def save(self, *args, **kwargs):
            calls.append(1)
            if on_save:
                on_save()
            if release is not None:
                release.acquire(timeout=6)
            return self._inner.save(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(storage, "storage_for_tenant", lambda db, tenant_id: Wrapped(real(db, tenant_id)))
    return calls


@pytest.mark.parametrize("path", ["media", "header"])
def test_ac_41_10_the_slot_is_held_until_the_media_is_stored(client, session_factory, monkeypatch, path):
    import threading

    phones, cids, keys = _gate_world(client, session_factory, contacts=6)
    release = threading.Semaphore(0)
    _install(monkeypatch, media=_pdf_media)
    saves = _hold_storage_writes(monkeypatch, release=release)
    hp = path == "header"

    async def scenario():
        out = {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as ac:
            held = []
            try:
                for i, name in enumerate(["a", "b"]):  # fetched, now waiting to be stored
                    held.append(asyncio.create_task(_post_media(ac, keys[name], phones[i], header_path=hp)))
                    assert await _wait_for(lambda n=i + 1: len(saves) >= n), f"send {i + 1} never reached the store"
                t0 = time.monotonic()
                out["while_storing"] = await _post_media(ac, keys["c"], phones[2], header_path=hp)
                out["busy_secs"] = time.monotonic() - t0
                out["held"] = []
                for t in held:
                    release.release()
                    out["held"].append(await t)
            finally:
                for _ in range(8):
                    release.release()
            out["after_store"] = await _post_media(ac, keys["c"], phones[2], header_path=hp)
        return out

    out = asyncio.run(scenario())
    busy = out["while_storing"]
    assert (busy.status_code, _error_code(busy)) == (429, "media_fetch_busy"), "the slot was freed before the store"
    assert out["busy_secs"] < 3.0
    assert [r.status_code for r in out["held"]] == [202, 202]
    assert out["after_store"].status_code == 202, out["after_store"].text  # the slot is free again
    assert _message_count(session_factory, cids[phones[2]]) == 1


def _tracker():
    """Track sessions that began a transaction; `open_now()` lists those still in one."""
    import weakref

    from sqlalchemy import event
    from sqlalchemy.orm import Session

    seen = weakref.WeakSet()

    def track(session, transaction, connection):
        seen.add(session)

    event.listen(Session, "after_begin", track)
    return seen, lambda: [x for x in list(seen) if x.in_transaction()], lambda: event.remove(Session, "after_begin", track)


class _FakeStorageAdapter:
    """A connection-backed storage adapter that writes under a temp directory."""

    def __init__(self, root, on_write):
        self._root = root
        self._on_write = on_write

    def save(self, key_hint, content, mime_type):
        self._on_write()
        name = f"fake-{abs(hash(key_hint))}-{len(content)}"
        (self._root / name).write_bytes(content)
        return name

    def resolve(self, key):
        return ("path", str(self._root / key))


def _storage_connection(session_factory):
    from app.models.connection import Connection
    from app.secrets import encrypt_secret

    db = session_factory()
    db.add(Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="s3", type="storage", name="Fake store",
        config_json={"bucket": "b", "region": "auto"},
        credentials_json=encrypt_secret({"accessKeyId": "ak", "secretAccessKey": "sk"}),
        status="ACTIVE", is_active=True,
    ))
    db.commit()
    db.close()


@pytest.mark.parametrize("variant", ["local-disk", "connection-row"])
@pytest.mark.parametrize("path", ["media", "header"])
def test_ac_41_08_no_transaction_is_open_while_the_media_is_stored(
    client, session_factory, monkeypatch, tmp_path, path, variant
):
    from sqlalchemy import text

    import app.services.storage as storage

    phone = "+60700700770" if path == "media" else "+60700700771"
    headers, cid, _ch = _setup(client, session_factory, phone=phone)
    seen, open_now, untrack = _tracker()
    try:
        # control: the tracker sees an open transaction, then none after close
        probe = session_factory()
        probe.execute(text("select 1"))
        assert len(open_now()) == 1
        probe.close()
        assert open_now() == []

        at_write = []
        _install(monkeypatch, media=_pdf_media)
        if variant == "local-disk":
            real = storage.LocalDiskStorage.save

            def sampled(self, *args, **kwargs):  # the REAL write, after the storage layer's own lookups
                at_write.append(len(open_now()))
                return real(self, *args, **kwargs)

            monkeypatch.setattr(storage.LocalDiskStorage, "save", sampled)
        else:
            _storage_connection(session_factory)
            adapter = _FakeStorageAdapter(tmp_path, lambda: at_write.append(len(open_now())))
            monkeypatch.setattr(storage, "_adapter_for", lambda connection: adapter)
        url, body = _PATHS[path](phone)
        r = client.post(url, json=body, headers=headers)
    finally:
        untrack()
    assert r.status_code == 202, r.text
    assert len(at_write) == 1, "the real write never ran"
    assert at_write == [0], f"{at_write[0]} session(s) held a transaction at the write"


# ── AC-41-08 at the storage layer ────────────────────────────────────────────
@pytest.mark.parametrize("variant", ["local-disk", "connection-row"])
def test_ac_41_08_storage_save_ends_read_transactions_and_keeps_pending_work(
    session_factory, monkeypatch, tmp_path, variant
):
    import app.services.storage as storage
    from modules.omnichannel.models import Workspace

    if variant == "connection-row":
        _storage_connection(session_factory)
    reader = session_factory()
    reader.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID).first()  # a plain read
    assert reader.in_transaction()  # control: it is in a read transaction before the write

    adder = session_factory()
    pending = Workspace(tenant_id=DEFAULT_TENANT_ID, name="Pending workspace", is_default=False)
    adder.add(pending)  # unflushed work
    assert pending in adder.new

    editor = session_factory()
    existing = editor.query(Workspace).filter(Workspace.tenant_id == DEFAULT_TENANT_ID).first()
    original_name = existing.name
    existing.name = "Renamed workspace"  # dirty work
    assert existing in editor.dirty

    at_write = {}

    def sample():
        at_write["reader_in_txn"] = reader.in_transaction()
        at_write["pending_kept"] = pending in adder.new
        at_write["dirty_kept"] = existing in editor.dirty

    if variant == "local-disk":
        real = storage.LocalDiskStorage.save

        def sampled(self, *args, **kwargs):
            sample()
            return real(self, *args, **kwargs)

        monkeypatch.setattr(storage.LocalDiskStorage, "save", sampled)
    else:
        adapter = _FakeStorageAdapter(tmp_path, sample)
        monkeypatch.setattr(storage, "_adapter_for", lambda connection: adapter)

    key = storage.TenantStorage(reader, DEFAULT_TENANT_ID).save("omnichannel/test/outbound", PDF, "application/pdf")
    assert key
    assert at_write, "the real write never ran"
    assert at_write["reader_in_txn"] is False, "a read transaction was still open at the write"
    assert at_write["pending_kept"] is True, "unflushed work was discarded or committed early"
    assert at_write["dirty_kept"] is True, "dirty work was discarded or committed early"
    # the owners can still finish their own work
    adder.commit()
    editor.commit()
    check = session_factory()
    assert check.query(Workspace).filter(Workspace.name == "Pending workspace").count() == 1
    assert check.query(Workspace).filter(Workspace.name == "Renamed workspace").count() == 1
    assert original_name != "Renamed workspace"
    for s_ in (reader, adder, editor, check):
        s_.close()


# ── AC-41-09: a media url that is not text, and other malformed bodies ───────
_NOT_TEXT = [123, [1, 2], {"a": 1}, True, 1.5]
_NOT_TEXT_IDS = ["int", "list", "dict", "bool", "float"]


@pytest.mark.parametrize("value", _NOT_TEXT, ids=_NOT_TEXT_IDS)
def test_ac_41_09_a_json_media_url_that_is_not_text_is_refused(client, session_factory, monkeypatch, value):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700780", token="tkn-live-09")
    rig = _install(monkeypatch, media=_pdf_media)
    body = _media_body("+60700700780")
    body["media"]["url"] = value
    r = client.post("/api/v1/omnichannel/messages", json=body, headers=headers)
    assert (r.status_code, _error_code(r)) == (422, "invalid_media_url")
    assert rig.media_calls == 0 and rig.graph_calls == []
    assert _message_count(session_factory, cid) == 0


def test_ac_41_09_a_recipient_that_is_a_number_is_a_typed_422(client, session_factory):
    # Chosen code: the same envelope every other body-validation failure on this
    # route already answers (`422 invalid_request`).
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700782")
    r = client.post(
        "/api/v1/omnichannel/messages",
        json={"to": 60700700782, "type": "text", "text": {"body": "hi"}},
        headers=headers,
    )
    assert (r.status_code, _error_code(r)) == (422, "invalid_request")
    assert _message_count(session_factory, cid) == 0


# ══ Compression guard ════════════════════════════════════════════════════════
@pytest.mark.parametrize("encoding", ["identity", "Identity"])
def test_guard_ac_41_04_content_encoding_identity_is_accepted(client, session_factory, monkeypatch, encoding):
    headers, cid, _ch = _setup(client, session_factory, phone="+60700700790")

    def plain(request):
        return httpx.Response(
            200,
            headers=[(b"content-type", b"application/pdf"), (b"content-encoding", encoding.encode())],
            stream=_Stream([PDF]),
            request=request,
        )

    rig = _install(monkeypatch, media=plain)
    r = client.post("/api/v1/omnichannel/messages", json=_media_body("+60700700790"), headers=headers)
    assert rig.media_calls == 1
    assert r.status_code == 202, r.text
    assert _message_count(session_factory, cid) == 1
