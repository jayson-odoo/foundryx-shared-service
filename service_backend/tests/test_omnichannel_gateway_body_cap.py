"""AW-2: every request under `/api/v1/omnichannel/` reads its body up to one
fixed size (256 KiB, 262144 bytes; multipart sends up to the media ceiling plus
a small margin). The check runs at the ASGI layer, before any route or the
workspace-key dependency, so it holds for a missing or bad key too, and a
refused request is not read past the cap.

Byte-count tests drive the ASGI app directly with a hand-built `receive()` that
records how many bytes the app pulled (the TestClient reads a request body
before the app sees it, so it cannot measure that).
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.main import app
from tests.test_omnichannel_api_gateway import (
    _default_workspace_id,
    _mint,
    _seed_channel,
    _seed_open_contact,
    _seeded,
)

CAP = 262144
CHUNK = 65536
BASE = "/api/v1/omnichannel"
JSON_CT = {"Content-Type": "application/json"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
TOO_LARGE = "Request body is too large."
# Test safety bound: a stream never hands the app more than this, then disconnects.
STREAM_LIMIT = 8 * 1024 * 1024


def _big_json(extra=300 * 1024, **fields) -> bytes:
    return json.dumps({**fields, "pad": "a" * extra}).encode()


def _assert_too_large(res):
    assert res.status_code == 422, (res.status_code, res.text[:200])
    err = res.json()["error"]
    assert err["code"] == "invalid_request", err
    assert err["message"] == TOO_LARGE, err


def _rows(session_factory):
    from modules.omnichannel.models import Contact, ConversationMessage as Message, WebhookEndpoint

    db = session_factory()
    try:
        return SimpleNamespace(
            messages=db.query(Message).count(),
            webhooks=sorted((w.id, w.name, w.url) for w in db.query(WebhookEndpoint).all()),
            contacts=sorted((c.id, c.first_name, c.priority) for c in db.query(Contact).all()),
        )
    finally:
        db.close()


def _asgi(method, path, headers, total, declared=None, chunk=CHUNK, starts=None):
    """Drive the app with a lazily produced body of `total` bytes in `chunk`
    pieces. `declared` is the Content-Length header (None = chunked, no header).
    Returns (status, json body or None, bytes the app pulled)."""
    pulled = 0
    sent = 0
    done = False
    out = {"status": None, "body": b""}
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    if declared is not None:
        raw.append((b"content-length", str(declared).encode()))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "headers": raw + [(b"host", b"localhost")],
        "client": ("127.0.0.1", 1), "server": ("localhost", 80),
    }

    async def receive():
        nonlocal pulled, sent, done
        if done or sent >= min(total, STREAM_LIMIT):
            done = True
            await asyncio.sleep(0)
            return {"type": "http.disconnect"}
        n = min(chunk, min(total, STREAM_LIMIT) - sent)
        sent += n
        pulled += n
        more = sent < min(total, STREAM_LIMIT)
        if not more:
            done = True
        return {"type": "http.request", "body": b"x" * n, "more_body": more}

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"] = msg["status"]
            if starts is not None:
                starts.append(msg["status"])
        elif msg["type"] == "http.response.body":
            out["body"] += msg.get("body", b"")

    from starlette.requests import ClientDisconnect

    try:
        asyncio.run(app(scope, receive, send))
    except ClientDisconnect:
        # the JSON send route reads the body itself and does not catch this; the
        # client already has its single 422, so only the answer is asserted
        pass
    try:
        parsed = json.loads(out["body"])
    except ValueError:
        parsed = None
    return out["status"], parsed, pulled


def _assert_stream_refused(status, body, pulled, limit):
    assert status == 422, (status, body)
    assert body["error"]["code"] == "invalid_request" and body["error"]["message"] == TOO_LARGE, body
    assert pulled <= limit, f"app pulled {pulled} bytes (limit {limit})"


def _routes(cid, eid):
    return [
        ("PATCH", f"{BASE}/contacts/{cid}"),
        ("POST", f"{BASE}/contacts/{cid}/comments"),
        ("POST", f"{BASE}/webhooks"),
        ("PATCH", f"{BASE}/webhooks/{eid}"),
    ]


def _rig(client, session_factory, phone):
    hdr, cid = _seeded(client, session_factory, phone=phone)
    made = client.post(f"{BASE}/webhooks", json={"name": "Orig", "url": "https://hooks.example.com/a",
                                                 "events": ["message.inbound"]}, headers=hdr)
    assert made.status_code == 201, made.text
    return hdr, cid, made.json()["endpoint"]["id"]


# ── rule 1: oversize non-multipart body on each of the four routes ───────────
@pytest.mark.parametrize("which", [0, 1, 2, 3])
def test_oversize_body_is_refused_and_nothing_is_written(client, session_factory, which):
    hdr, cid, eid = _rig(client, session_factory, f"+6012000010{which}")
    method, path = _routes(cid, eid)[which]
    before = _rows(session_factory)
    res = client.request(method, path, content=_big_json(), headers={**hdr, **JSON_CT})
    _assert_too_large(res)
    assert _rows(session_factory) == before


# ── rule 2: declared Content-Length over the cap is refused before reading ───
@pytest.mark.parametrize("which", [0, 1, 2, 3])
def test_declared_oversize_is_refused_before_the_body_is_read(client, session_factory, which):
    hdr, cid, eid = _rig(client, session_factory, f"+6012000020{which}")
    method, path = _routes(cid, eid)[which]
    st, body, pulled = _asgi(method, path, {**hdr, **JSON_CT}, total=2 * 1024 * 1024,
                             declared=2 * 1024 * 1024)
    _assert_stream_refused(st, body, pulled, CHUNK)


# ── rule 3: chunked / understated bodies stop at the cap ─────────────────────
@pytest.mark.parametrize("which", [0, 1, 2, 3])
def test_chunked_body_with_no_length_stops_at_the_cap(client, session_factory, which):
    hdr, cid, eid = _rig(client, session_factory, f"+6012000030{which}")
    method, path = _routes(cid, eid)[which]
    st, body, pulled = _asgi(method, path, {**hdr, **JSON_CT}, total=2 * 1024 * 1024, declared=None)
    _assert_stream_refused(st, body, pulled, CAP + CHUNK)


@pytest.mark.parametrize("which", [0, 1, 2, 3])
def test_body_longer_than_its_declared_length_stops_at_the_cap(client, session_factory, which):
    hdr, cid, eid = _rig(client, session_factory, f"+6012000040{which}")
    method, path = _routes(cid, eid)[which]
    st, body, pulled = _asgi(method, path, {**hdr, **JSON_CT}, total=2 * 1024 * 1024, declared=1000)
    _assert_stream_refused(st, body, pulled, CAP + CHUNK)


# ── rule 4: the cap runs before auth ─────────────────────────────────────────
@pytest.mark.parametrize("auth", [None, "Bearer fxw_live_notarealkey000000000000000000"])
@pytest.mark.parametrize("which", [0, 1, 2, 3])
def test_oversize_body_is_refused_without_a_valid_key(client, session_factory, which, auth):
    _hdr, cid, eid = _rig(client, session_factory, f"+6012000050{which}")
    method, path = _routes(cid, eid)[which]
    headers = dict(JSON_CT)
    if auth:
        headers["Authorization"] = auth
    res = client.request(method, path, content=_big_json(), headers=headers)
    _assert_too_large(res)
    st, body, pulled = _asgi(method, path, headers, total=2 * 1024 * 1024, declared=None)
    _assert_stream_refused(st, body, pulled, CAP + CHUNK)


# ── rule 5: multipart send ───────────────────────────────────────────────────
def _mp_rig(client, session_factory, phone):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    _seed_open_contact(session_factory, ws, phone=phone, open_window=True)
    key = _mint(client, ws).json()["fullKey"]
    return {"Authorization": f"Bearer {key}"}, json.dumps({"to": phone, "type": "image"})


def test_multipart_far_over_the_media_ceiling_is_refused_unread(client, session_factory):
    hdr, _payload = _mp_rig(client, session_factory, "+60120000601")
    ctype = {"Content-Type": "multipart/form-data; boundary=xyz"}
    st, body, pulled = _asgi("POST", f"{BASE}/messages", {**hdr, **ctype},
                             total=150 * 1024 * 1024, declared=150 * 1024 * 1024)
    _assert_stream_refused(st, body, pulled, CHUNK)


def test_multipart_two_file_parts_is_refused(client, session_factory):
    hdr, payload = _mp_rig(client, session_factory, "+60120000602")
    before = _rows(session_factory)
    res = client.post(f"{BASE}/messages", headers=hdr, data={"payload": payload},
                      files=[("file", ("a.png", PNG, "image/png")), ("file", ("b.png", PNG, "image/png"))])
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_request", res.text
    assert _rows(session_factory) == before


def test_multipart_with_many_extra_fields_is_refused(client, session_factory):
    hdr, payload = _mp_rig(client, session_factory, "+60120000603")
    before = _rows(session_factory)
    data = {"payload": payload, **{f"extra{i}": "v" for i in range(50)}}
    res = client.post(f"{BASE}/messages", headers=hdr, data=data,
                      files={"file": ("a.png", PNG, "image/png")})
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_request", res.text
    assert _rows(session_factory) == before


# ── rule 6: controls (pass today) ────────────────────────────────────────────
def test_control_normal_bodies_still_work(client, session_factory):
    hdr, cid, eid = _rig(client, session_factory, "+60120000701")
    r = client.patch(f"{BASE}/contacts/{cid}", json={"priority": "HIGH"}, headers=hdr)
    assert r.status_code == 200, r.text
    r = client.post(f"{BASE}/contacts/{cid}/comments", json={"body": "note"}, headers=hdr)
    assert r.status_code == 201, r.text
    r = client.post(f"{BASE}/webhooks", json={"name": "Two", "url": "https://hooks.example.com/b",
                                              "events": ["message.status"]}, headers=hdr)
    assert r.status_code == 201, r.text
    r = client.patch(f"{BASE}/webhooks/{eid}", json={"name": "Renamed"}, headers=hdr)
    assert r.status_code == 200, r.text


def test_control_normal_multipart_and_json_sends_are_accepted(client, session_factory):
    hdr, payload = _mp_rig(client, session_factory, "+60120000702")
    r = client.post(f"{BASE}/messages", headers=hdr, data={"payload": payload},
                    files={"file": ("a.png", PNG, "image/png")})
    assert r.status_code == 202, r.text
    r = client.post(f"{BASE}/messages", headers=hdr,
                    json={"to": "+60120000702", "type": "text", "text": {"body": "hi"}})
    assert r.status_code == 202, r.text


def test_control_routes_outside_the_prefix_are_not_capped(client, session_factory):
    # a staff JSON route and a core JSON route: whatever they answer, it is not
    # the gateway's too-large refusal. (The inbound channel webhook is left out:
    # a 200 there enqueues a task that needs a live database.)
    ws = _default_workspace_id(session_factory)
    staff = client.post(f"/omnichannel/workspaces/{ws}/api-keys", content=_big_json(name="k"),
                        headers={**JSON_CT, "Authorization": "Bearer nope"})
    core = client.post("/auth/login", content=_big_json(email="a@b.co"), headers=JSON_CT)
    for res in (staff, core):
        refused = False
        try:
            refused = res.json().get("error", {}).get("message") == TOO_LARGE
        except (ValueError, AttributeError):
            pass
        assert not refused, (res.status_code, res.text[:200])


# ── guards ───────────────────────────────────────────────────────────────────
def test_core_multipart_cap_stays_above_the_largest_media_ceiling():
    from app.gateway_body_cap import MULTIPART_BODY_CAP
    from modules.omnichannel.routers.api_v1 import META_CEILINGS

    assert MULTIPART_BODY_CAP >= max(META_CEILINGS.values())


def test_multipart_exactly_at_the_largest_ceiling_is_not_refused_as_too_large(client, session_factory):
    from modules.omnichannel.routers.api_v1 import META_CEILINGS

    hdr, _payload = _mp_rig(client, session_factory, "+60120000801")
    size = max(META_CEILINGS.values()) + 4096  # file at the ceiling plus form framing
    st, body, _pulled = _asgi("POST", f"{BASE}/messages",
                              {**hdr, "Content-Type": "multipart/form-data; boundary=xyz"},
                              total=size, declared=size)
    too_large = st == 422 and isinstance(body, dict) and body.get("error", {}).get("message") == TOO_LARGE
    assert not too_large, (st, body)


@pytest.mark.parametrize("which", [0, 1, 2, 3, 4])
def test_refused_request_never_reaches_the_handler_and_is_answered_once(client, session_factory, which):
    from modules.omnichannel.services import idempotency

    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    hdr, cid, eid = _rig(client, session_factory, f"+6012000090{which}")
    routes = _routes(cid, eid) + [("POST", f"{BASE}/messages")]
    method, path = routes[which]
    headers = {**hdr, **JSON_CT, "Idempotency-Key": f"idem-{which}"}
    before = _rows(session_factory)
    starts = []
    st, body, _pulled = _asgi(method, path, headers, total=2 * 1024 * 1024, declared=None, starts=starts)
    _assert_stream_refused(st, body, _pulled, CAP + CHUNK)
    assert starts == [422], f"exactly one response start expected, got {starts}"
    assert _rows(session_factory) == before
    assert idempotency.get_store()._memory == {}, "no idempotency record for a refused request"
