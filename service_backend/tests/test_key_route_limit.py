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
Redis client; the autouse `key_limit_redis` fixture in conftest patches that
attribute by name with a fresh fake per test, and resets the module's state.
The Redis-down test swaps in a client whose every call raises.
"""
import json
import logging
import threading
import time

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


class DownRedis:
    def __init__(self):
        self.calls = 0

    def _boom(self, *a, **kw):
        self.calls += 1
        raise redis_lib.exceptions.ConnectionError("down")

    incr = decr = expire = get = pipeline = execute_command = _boom


@pytest.fixture
def ideation_client(ideation_session_factory):
    from app.database import get_db

    def override_get_db():
        db = ideation_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._factory = ideation_session_factory
        yield c
    app.dependency_overrides.clear()


def _patch_redis(monkeypatch, fake):
    try:
        from modules.omnichannel.services import key_limits
    except ImportError:
        return False
    monkeypatch.setattr(key_limits, "get_redis", lambda: fake, raising=False)
    return True


@pytest.fixture
def fake(key_limit_redis):
    return key_limit_redis


class Clock:
    """Patches time.time (used by the limiter and by fakeredis expiry)."""

    def __init__(self, monkeypatch):
        self._mp = monkeypatch
        self.now = None

    def freeze(self, t):
        self.now = t
        self._mp.setattr(time, "time", lambda: self.now)

    def advance(self, dt):
        self.now += dt


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch)


def _reached(fake):
    assert fake.dbsize() > 0, "the fake Redis was never written"


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
    """Requests in progress, whether stored as one counter or one entry each."""
    total = 0
    for k in fake.keys("*busy*"):
        kind = fake.type(k).decode()
        if kind == "string":
            v = fake.get(k)
            total += int(v) if k.decode().endswith(":busy") else 1
        elif kind == "zset":
            total += fake.zcard(k)
        elif kind == "hash":
            total += fake.hlen(k)
        elif kind == "set":
            total += fake.scard(k)
        elif kind == "list":
            total += fake.llen(k)
    return total


def _last_used(session_factory, key_id):
    from modules.omnichannel.models import WorkspaceApiKey

    db = session_factory()
    try:
        return db.query(WorkspaceApiKey).filter(WorkspaceApiKey.id == key_id).first().last_used_at
    finally:
        db.close()


def _text(rec):
    return " ".join(str(v) for v in rec.__dict__.values()) + rec.getMessage()


def _limit_warnings(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING and "key_limits" in r.name]


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
    _reached(fake)


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
    _reached(fake)


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
    _reached(fake)


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
    _reached(fake)


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
    _reached(fake)


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


def test_bad_overrides_json_does_not_silence_the_redis_down_warning(
    client, session_factory, enabled_spy, monkeypatch, caplog
):
    """AC-50-06: the overrides warning and the Redis-down warning run on separate timers."""
    down = DownRedis()
    reached = _patch_redis(monkeypatch, down)
    monkeypatch.setitem(settings.__dict__, "omni_key_limit_overrides", "{not json")
    h, _ = _key(client, session_factory, "k1")
    with caplog.at_level(logging.WARNING):
        assert client.get(ROUTE, headers=h).status_code == 200
    assert reached and down.calls >= 1
    msgs = [r.getMessage().lower() for r in _limit_warnings(caplog)]
    assert any("json" in m or "override" in m for m in msgs)
    assert any("redis" in m for m in msgs)


def test_retry_after_is_seconds_left_in_the_minute(client, session_factory, fake, enabled_spy, monkeypatch, clock):
    """AC-50-02: the per-minute Retry-After is the seconds to the next minute (clock fixed at :17.4 -> 43)."""
    monkeypatch.setitem(settings.__dict__, "omni_key_max_per_minute", 1)
    h, _ = _key(client, session_factory, "k1")
    clock.freeze(1_900_000_020 + 17.4)
    assert client.get(ROUTE, headers=h).status_code == 200
    r = client.get(ROUTE, headers=h)
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "43"
    _reached(fake)


def test_in_flight_refusal_gives_back_the_minute_count(
    client, session_factory, fake, enabled_spy, monkeypatch
):
    """AC-50-02: a request refused for in-flight does not count toward the minute."""
    monkeypatch.setitem(settings.__dict__, "omni_key_max_in_flight", 1)
    monkeypatch.setitem(settings.__dict__, "omni_key_max_per_minute", 3)
    h, _ = _key(client, session_factory, "k1")
    gate = threading.Event()
    enabled_spy["gate"] = gate
    t = threading.Thread(target=lambda: client.get(ROUTE, headers=h))
    t.start()
    try:
        assert enabled_spy["entered"].wait(BOUND)
        assert client.get(ROUTE, headers=h).status_code == 429
    finally:
        gate.set()
        t.join(BOUND)
    assert client.get(ROUTE, headers=h).status_code == 200
    assert client.get(ROUTE, headers=h).status_code == 200
    assert client.get(ROUTE, headers=h).status_code == 429
    _reached(fake)


def test_refused_request_does_not_stamp_last_used(client, session_factory, fake, enabled_spy, monkeypatch):
    """AC-50-02: a refused request writes nothing, so last_used_at is unchanged."""
    monkeypatch.setitem(settings.__dict__, "omni_key_max_per_minute", 1)
    h, m = _key(client, session_factory, "k1")
    assert client.get(ROUTE, headers=h).status_code == 200
    stamped = _last_used(session_factory, m["key"]["id"])
    assert stamped is not None
    time.sleep(0.05)
    assert client.get(ROUTE, headers=h).status_code == 429
    assert _last_used(session_factory, m["key"]["id"]) == stamped
    _reached(fake)


def test_abandoned_slots_expire_while_the_key_keeps_calling(fake, clock):
    """AC-50-04: slots left by a dead worker expire on time; refused calls do not extend them."""
    from modules.omnichannel.services import key_limits

    clock.freeze(1_900_000_020.0)
    for _ in range(10):
        key_limits.acquire("abandoned-key")
    for _ in range(3):
        clock.advance(10)
        with pytest.raises(Exception):
            key_limits.acquire("abandoned-key")
    clock.advance(31)  # 61s after the slots were taken
    assert key_limits.acquire("abandoned-key") is not None
    _reached(fake)


def test_endpoint_error_releases_the_slot(client, session_factory, fake, enabled_spy, monkeypatch):
    """AC-50-04: an endpoint that answers an error itself (404) still gives its slot back."""
    monkeypatch.setitem(settings.__dict__, "omni_key_max_in_flight", 1)
    h, _ = _key(client, session_factory, "k1")
    enabled_spy["observe"] = lambda: _busy(fake)
    url = "/api/v1/omnichannel/contacts/no-such-contact"
    assert client.get(url, headers=h).status_code == 404
    assert enabled_spy["observed"] == 1  # the slot was held while the endpoint ran
    assert _busy(fake) == 0
    assert client.get(url, headers=h).status_code == 404  # not 429
    _reached(fake)


@pytest.mark.parametrize("bad", [0, -3, 2.5], ids=["zero", "negative", "fraction"])
def test_invalid_setting_is_ignored_with_a_warning(
    client, session_factory, fake, enabled_spy, monkeypatch, caplog, bad
):
    """AC-50-03: an in-flight/per-minute setting below 1 or not whole falls back to the default."""
    monkeypatch.setitem(settings.__dict__, "omni_key_max_in_flight", bad)
    monkeypatch.setitem(settings.__dict__, "omni_key_max_per_minute", bad)
    h, _ = _key(client, session_factory, "k1")
    with caplog.at_level(logging.WARNING):
        assert [client.get(ROUTE, headers=h).status_code for _ in range(4)] == [200] * 4
    assert _limit_warnings(caplog)
    _reached(fake)


@pytest.mark.parametrize("bad", [0, 1.5], ids=["zero", "fraction"])
def test_invalid_override_is_ignored_with_a_warning(
    client, session_factory, fake, enabled_spy, monkeypatch, caplog, bad
):
    """AC-50-03: an override below 1 or not whole is ignored; the setting still applies."""
    h, m = _key(client, session_factory, "k1")
    monkeypatch.setitem(settings.__dict__, "omni_key_max_per_minute", 2)
    monkeypatch.setitem(
        settings.__dict__,
        "omni_key_limit_overrides",
        json.dumps({m["key"]["id"]: {"max_per_minute": bad}}),
    )
    with caplog.at_level(logging.WARNING):
        assert client.get(ROUTE, headers=h).status_code == 200
        assert client.get(ROUTE, headers=h).status_code == 200
        assert client.get(ROUTE, headers=h).status_code == 429
    assert _limit_warnings(caplog)
    _reached(fake)


def test_overrides_are_parsed_once(client, session_factory, fake, enabled_spy, monkeypatch):
    """AC-50-03: the overrides string is parsed once, not on every request."""
    raw = json.dumps({"some-other-key": {"max_per_minute": 7}})
    monkeypatch.setitem(settings.__dict__, "omni_key_limit_overrides", raw)
    h, _ = _key(client, session_factory, "k1")
    real = json.loads
    parses = []

    def spy(s, *a, **kw):
        if s == raw:
            parses.append(1)
        return real(s, *a, **kw)

    monkeypatch.setattr(json, "loads", spy)
    for _ in range(5):
        assert client.get(ROUTE, headers=h).status_code == 200
    assert len(parses) <= 1
    _reached(fake)


def test_media_route_counts_requests_per_key(client, session_factory, fake, enabled_spy, monkeypatch):
    """AC-50-01: GET /omnichannel/media/{id} with a workspace key is counted."""
    monkeypatch.setitem(settings.__dict__, "omni_key_max_per_minute", 1)
    h, _ = _key(client, session_factory, "k1")
    url = "/omnichannel/media/no-such-message"
    assert client.get(url, headers=h).status_code == 404
    assert client.get(url, headers=h).status_code == 429
    _reached(fake)


def test_ideation_intake_route_counts_requests_per_key(ideation_client, monkeypatch, fake):
    """AC-50-01: the ideation intake routes with a workspace key are counted."""
    from tests.test_ideation_intake_products import _key_auth, _mint_key

    monkeypatch.setitem(settings.__dict__, "omni_key_max_per_minute", 1)
    h = _key_auth(_mint_key(ideation_client._factory))
    url = "/ideation/intake/products"
    assert ideation_client.get(url, headers=h).status_code == 200
    assert ideation_client.get(url, headers=h).status_code == 429
    _reached(fake)
