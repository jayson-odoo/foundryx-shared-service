"""An idempotency reservation expires on its own (short PENDING TTL) and is owned
by the request that claimed it.

Pinned store API (chosen signature): ``reserve(w, k) -> Reservation`` with
``.token`` (owner token, truthy only for the claimer) and ``.existing`` (None when
the caller claimed the slot, else the stored value: a message id or PENDING);
``finalize(w, k, message_id, token)`` and ``release(w, k, token)`` act only while
the slot still belongs to ``token``. Redis tests run on fakeredis with Lua.
"""
import logging
import time

import fakeredis
import pytest

from modules.omnichannel.services import idempotency, public_gateway_service
from modules.omnichannel.services.idempotency import PENDING, IdempotencyStore, MemoryIdempotencyStore, _key

DAY = 24 * 60 * 60
PAST_ANY_ALLOWED_PENDING_TTL = 601  # the constant must be <= 600
SECRET_KEY = "idem-secret-key-123"


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class RecordingRedis(fakeredis.FakeRedis):
    """fakeredis (real Lua) that records the command names it executes."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.commands = []

    def execute_command(self, *args, **kw):
        self.commands.append(str(args[0]).upper())
        return super().execute_command(*args, **kw)


class DownRedis:
    """Every call raises, like a dropped connection."""

    def __getattr__(self, name):
        def boom(*a, **kw):
            raise ConnectionError("down")

        return boom


@pytest.fixture
def server():
    return fakeredis.FakeServer()


@pytest.fixture
def clock():
    return FakeClock()


def _good(server):
    return RecordingRedis(server=server, decode_responses=True)


def _store(monkeypatch, holder):
    store = IdempotencyStore()
    monkeypatch.setattr(store, "_client", lambda: holder[0])
    return store


def _expire(client, w="w1", k="k1"):
    """Simulate the PENDING TTL elapsing on Redis."""
    client.delete(_key(w, k))


# ---- TTLs -----------------------------------------------------------------

def test_reserve_uses_a_short_pending_ttl(monkeypatch, server):
    good = _good(server)
    store = _store(monkeypatch, [good])
    assert store.reserve("w1", "k1").existing is None
    ttl = idempotency._PENDING_TTL_SECONDS
    assert 120 < ttl <= 600
    assert 0 < good.ttl(_key("w1", "k1")) <= ttl


def test_pending_ttl_is_derived_from_the_media_fetch_limit():
    assert idempotency._PENDING_TTL_SECONDS >= public_gateway_service.MEDIA_FETCH_TOTAL_SECONDS + 120


def test_finalize_keeps_the_day_ttl(monkeypatch, server):
    good = _good(server)
    store = _store(monkeypatch, [good])
    r = store.reserve("w1", "k1")
    store.finalize("w1", "k1", "msg-1", r.token)
    assert DAY - 60 < good.ttl(_key("w1", "k1")) <= DAY
    assert store.lookup("w1", "k1") == "msg-1"


def test_failed_release_still_expires_within_the_pending_ttl(monkeypatch, server):
    good = _good(server)
    holder = [good]
    store = _store(monkeypatch, holder)
    r = store.reserve("w1", "k1")
    holder[0] = DownRedis()
    store.release("w1", "k1", r.token)  # swallowed
    holder[0] = good
    assert 0 < good.ttl(_key("w1", "k1")) <= 600
    assert store.reserve("w1", "k1").existing == PENDING  # still blocking early
    _expire(good)
    assert store.reserve("w1", "k1").existing is None


# ---- memory fallback ------------------------------------------------------

def test_memory_pending_stops_blocking_after_the_pending_ttl(monkeypatch, clock):
    monkeypatch.setattr(time, "monotonic", clock)
    store = MemoryIdempotencyStore()
    assert store.reserve("w1", "k1").existing is None
    clock.now += 30
    assert store.reserve("w1", "k1").existing == PENDING
    clock.now += PAST_ANY_ALLOWED_PENDING_TTL
    assert store.lookup("w1", "k1") is None  # an expired PENDING reads as absent
    assert store.reserve("w1", "k1").existing is None


# ---- ownership ------------------------------------------------------------

def test_late_release_does_not_delete_a_newer_reservation_redis(monkeypatch, server):
    good = _good(server)
    store = _store(monkeypatch, [good])
    a = store.reserve("w1", "k1")
    assert a.existing is None
    _expire(good)
    b = store.reserve("w1", "k1")
    assert b.existing is None
    store.release("w1", "k1", a.token)  # A is late
    assert store.reserve("w1", "k1").existing == PENDING  # C still refused
    store.finalize("w1", "k1", "msg-B", b.token)
    assert store.lookup("w1", "k1") == "msg-B"


def test_late_finalize_does_not_overwrite_a_newer_reservation_redis(monkeypatch, server):
    good = _good(server)
    store = _store(monkeypatch, [good])
    a = store.reserve("w1", "k1")
    _expire(good)
    b = store.reserve("w1", "k1")
    store.finalize("w1", "k1", "msg-A", a.token)  # A is late
    assert store.lookup("w1", "k1") == PENDING
    assert store.reserve("w1", "k1").existing == PENDING
    store.finalize("w1", "k1", "msg-B", b.token)
    assert store.lookup("w1", "k1") == "msg-B"


def test_late_release_does_not_delete_a_newer_reservation_memory(monkeypatch, clock):
    monkeypatch.setattr(time, "monotonic", clock)
    store = MemoryIdempotencyStore()
    a = store.reserve("w1", "k1")
    clock.now += PAST_ANY_ALLOWED_PENDING_TTL
    b = store.reserve("w1", "k1")
    assert b.existing is None
    store.release("w1", "k1", a.token)
    assert store.reserve("w1", "k1").existing == PENDING
    store.finalize("w1", "k1", "msg-B", b.token)
    assert store.lookup("w1", "k1") == "msg-B"


def test_late_finalize_does_not_overwrite_a_newer_reservation_memory(monkeypatch, clock):
    monkeypatch.setattr(time, "monotonic", clock)
    store = MemoryIdempotencyStore()
    a = store.reserve("w1", "k1")
    clock.now += PAST_ANY_ALLOWED_PENDING_TTL
    b = store.reserve("w1", "k1")
    store.finalize("w1", "k1", "msg-A", a.token)
    assert store.lookup("w1", "k1") == PENDING
    store.finalize("w1", "k1", "msg-B", b.token)
    assert store.lookup("w1", "k1") == "msg-B"


# ---- atomic Redis operations ---------------------------------------------

def test_redis_release_and_finalize_are_atomic_scripts(monkeypatch, server):
    good = _good(server)
    store = _store(monkeypatch, [good])
    r = store.reserve("w1", "k1")
    good.commands.clear()
    store.release("w1", "k1", r.token)
    assert {"EVAL", "EVALSHA"} & set(good.commands)
    assert "DEL" not in good.commands and "GET" not in good.commands
    r = store.reserve("w1", "k1")
    good.commands.clear()
    store.finalize("w1", "k1", "msg-1", r.token)
    assert {"EVAL", "EVALSHA"} & set(good.commands)


# ---- logging --------------------------------------------------------------

def test_memory_fallback_on_finalize_and_release_warns_without_the_key(monkeypatch, caplog, server):
    good = _good(server)
    holder = [good]
    store = _store(monkeypatch, holder)
    r = store.reserve("w1", SECRET_KEY)
    holder[0] = DownRedis()
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        store.release("w1", SECRET_KEY, r.token)
    assert any(rec.levelno == logging.WARNING for rec in caplog.records)
    assert SECRET_KEY not in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        store.finalize("w1", SECRET_KEY, "msg-1", r.token)
    assert any(rec.levelno == logging.WARNING for rec in caplog.records)
    assert SECRET_KEY not in caplog.text


# ---- controls -------------------------------------------------------------

def test_control_replay_after_finalize_returns_the_id_redis(monkeypatch, server):
    good = _good(server)
    store = _store(monkeypatch, [good])
    r = store.reserve("w1", "k1")
    store.finalize("w1", "k1", "msg-1", r.token)
    store.release("w1", "k1", r.token)  # no-op on a finalized key
    assert store.reserve("w1", "k1").existing == "msg-1"


def test_control_replay_after_finalize_returns_the_id_memory(monkeypatch, clock):
    monkeypatch.setattr(time, "monotonic", clock)
    store = MemoryIdempotencyStore()
    r = store.reserve("w1", "k1")
    store.finalize("w1", "k1", "msg-1", r.token)
    clock.now += PAST_ANY_ALLOWED_PENDING_TTL
    assert store.reserve("w1", "k1").existing == "msg-1"
    store.release("w1", "k1", r.token)
    assert store.reserve("w1", "k1").existing == "msg-1"
