"""AW-1: `POST /api/v1/omnichannel/messages` reads a JSON body up to a fixed
size (256 KiB, same as the workflow routes) and refuses a larger one with the
gateway error envelope, sending nothing and keeping no idempotency record.
The size is counted on bytes read, so a body with no Content-Length is held to
the same limit.
"""
import json

import pytest

from tests.test_omnichannel_api_gateway import (
    _default_workspace_id,
    _mint,
    _seed_channel,
    _seed_open_contact,
)
from tests.test_omnichannel_send_route_limits import _message_count
from modules.omnichannel.services import idempotency

URL = "/api/v1/omnichannel/messages"
CAP = 262144
TOO_LARGE = "Request body is too large."


@pytest.fixture(autouse=True)
def _memory_idempotency():
    idempotency.set_store(idempotency.MemoryIdempotencyStore())
    yield
    idempotency.set_store(idempotency.MemoryIdempotencyStore())


def _rig(client, session_factory, phone):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws, phone_number_id=f"pn-{phone[-6:]}")
    cid = _seed_open_contact(session_factory, ws, phone=phone, open_window=True)
    key = _mint(client, ws).json()["fullKey"]
    return {"Authorization": f"Bearer {key}"}, cid, ws


def _body(phone, pad=0):
    """A valid text send, padded with an extra field to an exact byte size."""
    base = {"to": phone, "type": "text", "text": {"body": "hello"}, "pad": ""}
    size = len(json.dumps(base).encode())
    base["pad"] = "a" * (pad - size) if pad else ""
    raw = json.dumps(base).encode()
    if pad:
        assert len(raw) == pad
    return raw


def _assert_too_large(r):
    assert r.status_code == 422, r.text
    err = r.json()["error"]
    assert err["code"] == "invalid_request"
    assert err["message"] == TOO_LARGE


def _chunks(raw, size=16384):
    for i in range(0, len(raw), size):
        yield raw[i : i + size]


def test_aw_1_a_json_body_over_the_cap_is_refused_and_nothing_is_sent(client, session_factory):
    phone = "+60810000001"
    headers, cid, ws = _rig(client, session_factory, phone)
    r = client.post(
        URL, content=_body(phone, CAP + 1),
        headers={**headers, "Content-Type": "application/json", "Idempotency-Key": "aw1-big"},
    )
    _assert_too_large(r)
    assert _message_count(session_factory, cid) == 0
    assert idempotency.get_store().lookup(ws, "aw1-big") is None


def test_aw_1_a_body_far_over_the_cap_is_refused(client, session_factory):
    phone = "+60810000002"
    headers, cid, _ws = _rig(client, session_factory, phone)
    r = client.post(URL, content=_body(phone, 3 * CAP), headers={**headers, "Content-Type": "application/json"})
    _assert_too_large(r)
    assert _message_count(session_factory, cid) == 0


def test_aw_1_a_chunked_body_over_the_cap_is_refused_and_nothing_is_sent(client, session_factory):
    phone = "+60810000003"
    headers, cid, ws = _rig(client, session_factory, phone)
    r = client.post(
        URL, content=_chunks(_body(phone, CAP + 1)),
        headers={**headers, "Content-Type": "application/json", "Idempotency-Key": "aw1-chunked"},
    )
    assert "content-length" not in {k.lower() for k in r.request.headers}, "control: sent without a length"
    _assert_too_large(r)
    assert _message_count(session_factory, cid) == 0
    assert idempotency.get_store().lookup(ws, "aw1-chunked") is None


def test_aw_1_control_a_normal_json_text_send_answers_202(client, session_factory):
    phone = "+60810000004"
    headers, cid, _ws = _rig(client, session_factory, phone)
    r = client.post(URL, json={"to": phone, "type": "text", "text": {"body": "hello"}}, headers=headers)
    assert r.status_code == 202, r.text
    assert _message_count(session_factory, cid) == 1


def test_aw_1_control_a_body_of_exactly_the_cap_is_sent(client, session_factory):
    phone = "+60810000005"
    headers, cid, _ws = _rig(client, session_factory, phone)
    r = client.post(URL, content=_body(phone, CAP), headers={**headers, "Content-Type": "application/json"})
    assert not (r.status_code == 422 and r.json().get("error", {}).get("message") == TOO_LARGE), r.text
    assert r.status_code == 202, r.text
    assert _message_count(session_factory, cid) == 1


def test_aw_1_control_malformed_json_keeps_its_message(client, session_factory):
    phone = "+60810000006"
    headers, _cid, _ws = _rig(client, session_factory, phone)
    r = client.post(URL, content=b"{not json", headers={**headers, "Content-Type": "application/json"})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "invalid_request"
    assert r.json()["error"]["message"] == "Request body must be valid JSON."


def test_aw_1_control_json_sent_as_text_plain_is_still_accepted(client, session_factory):
    phone = "+60810000007"
    headers, cid, _ws = _rig(client, session_factory, phone)
    raw = json.dumps({"to": phone, "type": "text", "text": {"body": "hello"}}).encode()
    r = client.post(URL, content=raw, headers={**headers, "Content-Type": "text/plain"})
    assert r.status_code == 202, r.text
    assert _message_count(session_factory, cid) == 1


def test_aw_1_control_a_multipart_send_is_unchanged(client, session_factory):
    phone = "+60810000008"
    headers, cid, _ws = _rig(client, session_factory, phone)
    pdf = b"%PDF-1.4\n" + b"x" * 512
    r = client.post(
        URL,
        files={"file": ("doc.pdf", pdf, "application/pdf")},
        data={"payload": json.dumps({"to": phone, "type": "document", "media": {"filename": "doc.pdf"}})},
        headers=headers,
    )
    assert r.status_code == 202, r.text
    assert _message_count(session_factory, cid) == 1


@pytest.mark.parametrize("raw", [b"[" * 200000, b'{"a":' * 50000], ids=["nested-arrays", "nested-objects"])
def test_aw_1_a_deeply_nested_body_answers_the_invalid_json_error(client, session_factory, raw):
    from starlette.testclient import TestClient

    from app.main import app

    assert len(raw) < CAP
    phone = "+60810000009"
    headers, cid, _ws = _rig(client, session_factory, phone)
    with TestClient(app, raise_server_exceptions=False) as quiet:
        r = quiet.post(URL, content=raw, headers={**headers, "Content-Type": "application/json"})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "invalid_request"
    assert r.json()["error"]["message"] == "Request body must be valid JSON."
    assert _message_count(session_factory, cid) == 0
