"""Plan 55 S1: db3-only write guard + single write client (AC-55-01..05)."""

from __future__ import annotations

import httpx
import pytest

from modules.autocount.write_back import guard as guard_mod
from modules.autocount.write_back.client import (
    AutoCountWriteClient,
    WriteResponse,
    WriteTransportError,
)
from modules.autocount.write_back.guard import (
    WRITE_ALLOWED_BOOKS,
    WriteNotAllowed,
    assert_write_allowed,
)
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

DB3 = "https://ac.example.test/api/db3"

REFUSED = [
    "https://ac.example.test/api/db1",
    "https://ac.example.test/api/db2",
    "https://ac.example.test/api/DB3",
    "https://ac.example.test/api/DB1",
    "https://ac.example.test/api/db31",
    "https://ac.example.test/api/db3x",
    "https://ac.example.test/api/",
    "https://ac.example.test",
    "https://ac.example.test/",
    "",
    "https://ac.example.test/api/db3/../db1",
    "https://ac.example.test/api/db3/./",
    "https://ac.example.test/api/db1?x=db3",
    "https://ac.example.test/api/db3?x=1",
    "https://ac.example.test/api/db1#db3",
    "https://ac.example.test/api/db3#x",
    "https://ac.example.test/api/db3;p=1",
    "http://ac.example.test/api/db3",
    "https://user:pw@ac.example.test/api/db3",
    "https://ac.example.test/api/%64b3",
    "https://ac.example.test/api/db3/%2e%2e/db1",
    "https://ac.example.test/api/db3%2fdb1",
    "https://ac.example.test/api/db1/db3/..",
]


def _recording_transport(calls: list[httpx.Request], status: int = 200, json_body=None):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json=json_body if json_body is not None else {"ok": True})

    return httpx.MockTransport(handler)


def _forbidden_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"network call made: {request.method} {request.url}")

    return httpx.MockTransport(handler)


def test_ac_55_02_allowlist_is_exactly_db3():
    # plan 63: the test books stay {db3}; the code ceiling also names db1 (production only)
    assert guard_mod.TEST_BOOKS == frozenset({"db3"})
    assert WRITE_ALLOWED_BOOKS == frozenset({"db1", "db3"})
    assert isinstance(WRITE_ALLOWED_BOOKS, frozenset)


@pytest.mark.parametrize("url", [DB3, DB3 + "/"])
def test_ac_55_02_db3_allowed(url):
    assert assert_write_allowed(url) == "db3"


@pytest.mark.parametrize("url", REFUSED)
def test_ac_55_02_refused_urls(url):
    with pytest.raises(WriteNotAllowed) as ei:
        assert_write_allowed(url)
    assert ei.value.code == "WRITE_NOT_ALLOWED"


def test_ac_55_03_refusal_names_the_book():
    with pytest.raises(WriteNotAllowed) as ei:
        assert_write_allowed("https://ac.example.test/api/db1")
    assert ei.value.book == "db1"
    assert "db1" in str(ei.value)


def test_ac_55_02_allowlist_not_widened_by_env_or_settings(monkeypatch):
    for name in ("AUTOCOUNT_WRITE_ALLOWED_BOOKS", "WRITE_ALLOWED_BOOKS", "AUTOCOUNT_WRITE_BOOKS"):
        monkeypatch.setenv(name, "db1,db2,db3")
    from app.config import settings

    # off production nothing but db3 is writable, whatever the env or the setting says
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "autocount_write_allowed_books", "db1,db2,db3")
    assert guard_mod.writable_books() == frozenset({"db3"})
    for book in ("db1", "db2"):
        with pytest.raises(WriteNotAllowed):
            assert_write_allowed(f"https://ac.example.test/api/{book}")
    assert WRITE_ALLOWED_BOOKS == frozenset({"db1", "db3"})


def test_ac_55_02_constructing_with_db1_raises():
    with pytest.raises(WriteNotAllowed):
        AutoCountWriteClient("https://ac.example.test/api/db1", transport=_forbidden_transport())


@pytest.mark.parametrize("method", ["post", "put"])
def test_ac_55_03_refused_book_makes_no_request(method):
    calls: list[httpx.Request] = []
    client = AutoCountWriteClient(DB3, transport=_recording_transport(calls))
    # Simulate a client whose base url is swapped to a non-allowed book after construction.
    client.base_url = "https://ac.example.test/api/db1"
    with pytest.raises(WriteNotAllowed) as ei:
        getattr(client, method)("/purchaseorder", {"a": 1})
    assert ei.value.code == "WRITE_NOT_ALLOWED"
    assert ei.value.book == "db1"
    assert calls == []


@pytest.mark.parametrize("method,verb", [("post", "POST"), ("put", "PUT")])
def test_ac_55_01_request_shape(method, verb):
    calls: list[httpx.Request] = []
    client = AutoCountWriteClient(DB3 + "/", transport=_recording_transport(calls, 200, {"DocKey": 5}))
    resp = getattr(client, method)("/purchaseorder", {"DocKey": 5, "Details": []})
    assert isinstance(resp, WriteResponse)
    assert resp.status_code == 200 and resp.ok is True
    assert resp.body == {"DocKey": 5}
    assert len(calls) == 1
    assert calls[0].method == verb
    assert str(calls[0].url) == "https://ac.example.test/api/db3/purchaseorder"
    assert calls[0].read() == b'{"DocKey":5,"Details":[]}' or b'"DocKey"' in calls[0].read()


def test_ac_55_01_non_2xx_returned_not_raised():
    calls: list[httpx.Request] = []
    client = AutoCountWriteClient(DB3, transport=_recording_transport(calls, 400, {"Message": "bad"}))
    resp = client.put("/purchaseorder", {"x": 1})
    assert resp.status_code == 400 and resp.ok is False
    assert resp.body == {"Message": "bad"}
    assert len(calls) == 1


def test_ac_55_01_non_json_body_is_raw_text():
    def handler(request):
        return httpx.Response(502, text="Bad Gateway")

    client = AutoCountWriteClient(DB3, transport=httpx.MockTransport(handler))
    resp = client.post("/purchaseorder", {})
    assert resp.ok is False and resp.body == "Bad Gateway"


@pytest.mark.parametrize(
    "path",
    ["purchaseorder", "/a/../b", "/purchaseorder?x=1", "/..", "", "https://evil.test/x"],
)
def test_ac_55_01_bad_path_rejected_without_request(path):
    client = AutoCountWriteClient(DB3, transport=_forbidden_transport())
    with pytest.raises(ValueError):
        client.post(path, {})
    with pytest.raises(ValueError):
        client.put(path, {})


@pytest.mark.parametrize(
    "exc,code",
    [
        (httpx.ReadTimeout("slow"), "WRITE_TIMEOUT"),
        (httpx.ConnectTimeout("slow"), "WRITE_TIMEOUT"),
        (httpx.ConnectError("refused"), "WRITE_CONNECT"),
    ],
)
@pytest.mark.parametrize("method", ["post", "put"])
def test_ac_55_05_no_retry_on_transport_failure(exc, code, method):
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        raise exc

    client = AutoCountWriteClient(DB3, transport=httpx.MockTransport(handler))
    with pytest.raises(WriteTransportError) as ei:
        getattr(client, method)("/purchaseorder", {"Secret": "tok-123"})
    assert ei.value.code == code
    assert len(calls) == 1  # exactly one attempt, never retried


def test_ac_55_04_errors_carry_no_body_or_query():
    def handler(request):
        raise httpx.ConnectError("refused")

    client = AutoCountWriteClient(DB3, transport=httpx.MockTransport(handler))
    with pytest.raises(WriteTransportError) as ei:
        client.post("/purchaseorder", {"ApiKey": "tok-123-secret"})
    text = str(ei.value)
    assert "tok-123-secret" not in text
    assert "?" not in text


def test_ac_55_04_refusal_text_has_no_credentials():
    with pytest.raises(WriteNotAllowed) as ei:
        assert_write_allowed("https://user:hunter2@ac.example.test/api/db3?key=abc123")
    assert "hunter2" not in str(ei.value)
    assert "abc123" not in str(ei.value)
