"""Plan 50: per-key limits on the API key routes (AC-50-01..06).

Rules, stated as behaviour: a workspace key may have a bounded number of
requests in progress and started per minute; a request over either bound is
refused with 429 `rate_limited` and `Retry-After` before any database work; a
refused request holds no slot; the slot is released when a request ends, even
on error; the bounds are settings with per-key overrides; a refusal is logged
by key id, limit name and route name only; an unreachable counter store lets
requests through with at most one warning a minute.

Redis is stubbed with fakeredis. The limiter module
`modules.omnichannel.services.key_limits` exposes `get_redis()` returning the
Redis client; these tests patch that attribute by name. Until the module exists
nothing is patched and the tests fail on behaviour (no 429), and every test
asserts the fake was reached.
"""
import json
import logging
import threading

import fakeredis
import pytest
import redis as redis_lib
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from modules.omnichannel import api_auth
from tests.test_omnichannel_api_gateway import _default_workspace_id, _mint

ROUTE = "/api/v1/omnichannel/channels"
BOUND = 30.0


class CountingRedis(fakeredis.FakeStrictRedis):
    """fakeredis that records every command name it receives."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.seen = []

    def execute_command(self, *args, **kw):
        self.seen.append(str(args[0]).upper())
        return super().execute_command(*args, **kw)


class DownRedis:
    def __init__(self):
        self.calls = 0

    def _boom(self, *a, **kw):
        self.calls += 1
        raise redis_lib.exceptions.ConnectionError("down")

    incr = decr = expire = get = pipeline = execute_command = _boom


def _patch_redis(monkeypatch, fake):
    try:
        from modules.omnichannel.services import key_limits
    except ImportError:
        return False
    monkeypatch.setattr(key_limits, "get_redis", lambda: fake, raising=False)
    return True


@pytest.fixture
def fake(monkeypatch):
    f = CountingRedis()
    _patch_redis(monkeypatch, f)
    return f


@pytest.fixture
def enabled_spy(monkeypatch):
    """Counts reaches of the post-limit database check; optional gate/raise hooks."""
    spy = {"calls": 0, "gate": None, "entered": threading.Event(), "raise_once": False}
    real = api_auth.gateway_key_enabled

    def wrapper(db, tenant_id, workspace_id):
        spy["calls"] += 1
        if spy.get("observe"):
            spy["observed"] = spy["observe"]()
        if spy["raise_once"]:
            spy["raise_once"] = False
            raise RuntimeError("handler failure")
        if spy["gate"] is not None and spy["calls"] == 1:
            spy["entered"].set()
            assert spy["gate"].wait(BOUND)
        return real(db, tenant_id, workspace_id)

    monkeypatch.setattr(api_auth, "gateway_key_enabled", wrapper)
    return spy


def _key(client, session_factory, name):
    ws = _default_workspace_id(session_factory)
    minted = _mint(client, ws, name=name).json()
    return {"Authorization": f"Bearer {minted['fullKey']}"}, minted


def _busy(fake):
    total = 0
    for k in fake.keys("*busy*"):
        total += int(fake.get(k) or 0)
    return total


def test_minute_limit_refuses_fourth_request_without_db_work(
    client, session_factory, fake, enabled_spy, monkeypatch
):
    """AC-50-01/02: 4th request in a minute is 429 rate_limited, no DB work; other key unaffected."""
    monkeypatch.setitem(settings.__dict__, "omni_key_max_per_minute", 3)
    h1, _ = _key(client, session_factory, "k1")
    h2, _ = _key(client, session_factory, "k2")
    for _ in range(3):
        assert client.get(ROUTE, headers=h1).status_code == 200
    before = enabled_spy["calls"]
    r = client.get(ROUTE, headers=h1)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) >= 1
    assert enabled_spy["calls"] == before
    assert client.get(ROUTE, headers=h2).status_code == 200
    assert fake.seen


def test_in_flight_limit_refuses_concurrent_request_and_frees_slot(
    client, session_factory, fake, enabled_spy, monkeypatch
):
    """AC-50-01/02: second concurrent request is 429 Retry-After 1, holds no slot; slot frees after the first ends."""
    monkeypatch.setitem(settings.__dict__, "omni_key_max_in_flight", 1)
    h, _ = _key(client, session_factory, "k1")
    gate = threading.Event()
    enabled_spy["gate"] = gate
    first = {}
    t = threading.Thread(target=lambda: first.update(r=client.get(ROUTE, headers=h)))
    t.start()
    try:
        assert enabled_spy["entered"].wait(BOUND)
        busy_during = _busy(fake)
        r = client.get(ROUTE, headers=h)
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "rate_limited"
        assert r.headers["Retry-After"] == "1"
        assert _busy(fake) == busy_during == 1
    finally:
        gate.set()
        t.join(BOUND)
    assert first["r"].status_code == 200
    assert _busy(fake) == 0
    assert client.get(ROUTE, headers=h).status_code == 200
    assert fake.seen


def test_failing_request_releases_its_slot(client, session_factory, fake, enabled_spy, monkeypatch):
    """AC-50-04: a request that raises still releases its slot; the next one succeeds."""
    monkeypatch.setitem(settings.__dict__, "omni_key_max_in_flight", 1)
    h, _ = _key(client, session_factory, "k1")
    quiet = TestClient(app, raise_server_exceptions=False)
    enabled_spy["raise_once"] = True
    enabled_spy["observe"] = lambda: _busy(fake)
    assert quiet.get(ROUTE, headers=h).status_code == 500
    assert enabled_spy["calls"] == 1
    assert enabled_spy["observed"] == 1  # the slot was held while the handler ran
    assert _busy(fake) == 0
    assert quiet.get(ROUTE, headers=h).status_code == 200
    assert fake.seen


def test_defaults_come_from_settings():
    """AC-50-03: defaults are 10 in flight and 600 per minute, as settings."""
    assert getattr(settings, "omni_key_max_in_flight", None) == 10
    assert getattr(settings, "omni_key_max_per_minute", None) == 600


def test_override_raises_one_key_only(client, session_factory, fake, enabled_spy, monkeypatch):
    """AC-50-03: OMNI_KEY_LIMIT_OVERRIDES changes one key's numbers, not another's."""
    h1, m1 = _key(client, session_factory, "k1")
    h2, _ = _key(client, session_factory, "k2")
    monkeypatch.setitem(settings.__dict__, "omni_key_max_per_minute", 2)
    monkeypatch.setitem(
        settings.__dict__,
        "omni_key_limit_overrides",
        json.dumps({m1["key"]["id"]: {"max_per_minute": 5}}),
    )
    assert [client.get(ROUTE, headers=h1).status_code for _ in range(5)] == [200] * 5
    assert client.get(ROUTE, headers=h1).status_code == 429
    assert [client.get(ROUTE, headers=h2).status_code for _ in range(2)] == [200, 200]
    assert client.get(ROUTE, headers=h2).status_code == 429
    assert fake.seen


def test_refusal_logs_key_id_limit_and_route_only(
    client, session_factory, fake, enabled_spy, monkeypatch, caplog
):
    """AC-50-05: one record per 429 with key id, limit name, route name; no key, prefix or body."""
    monkeypatch.setitem(settings.__dict__, "omni_key_max_per_minute", 1)
    h, m = _key(client, session_factory, "k1")
    assert client.get(ROUTE, headers=h).status_code == 200
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        r = client.request("GET", ROUTE, headers=h, content=b"BODYMARK-1234")
    assert r.status_code == 429
    recs = [x for x in caplog.records if m["key"]["id"] in str(x.__dict__)]
    assert len(recs) == 1
    text = " ".join(str(v) for v in recs[0].__dict__.values()) + recs[0].getMessage()
    assert "channels" in text
    assert "minute" in text.lower()
    for rec in caplog.records:
        blob = " ".join(str(v) for v in rec.__dict__.values()) + rec.getMessage()
        assert m["fullKey"] not in blob
        assert m["fullKey"][:12] not in blob
        assert str(m["key"].get("prefix", "\0nope")) not in blob
        assert "BODYMARK" not in blob
    assert fake.seen


def test_redis_down_allows_requests_and_warns_once_a_minute(
    client, session_factory, enabled_spy, monkeypatch, caplog
):
    """AC-50-06: counter store unreachable -> requests allowed, a single warning per minute."""
    down = DownRedis()
    reached = _patch_redis(monkeypatch, down)
    monkeypatch.setitem(settings.__dict__, "omni_key_max_per_minute", 1)
    h, _ = _key(client, session_factory, "k1")
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            assert client.get(ROUTE, headers=h).status_code == 200
    assert reached and down.calls >= 2
    warns = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "redis" in (r.name + r.getMessage()).lower()
        and "key_limits" in r.name
    ]
    assert len(warns) == 1
