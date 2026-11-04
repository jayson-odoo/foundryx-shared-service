"""A PENDING idempotency reservation expires on its own (short TTL), so a lost
release never blocks retries for 24 h. Finalized ids keep the 24 h TTL."""
import time

import pytest

from modules.omnichannel.services import idempotency
from modules.omnichannel.services.idempotency import PENDING, IdempotencyStore, MemoryIdempotencyStore

DAY = 24 * 60 * 60
PAST_ANY_ALLOWED_PENDING_TTL = 601  # the constant must be <= 600


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeRedis:
    """Minimal redis double with TTLs on a controllable clock."""

    def __init__(self, clock, fail_get_delete=False):
        self.clock = clock
        self.data = {}
        self.ex_seen = []
        self.fail_get_delete = fail_get_delete

    def _live(self, k):
        item = self.data.get(k)
        if item and item[1] > self.clock():
            return item[0]
        self.data.pop(k, None)
        return None

    def set(self, k, v, ex=None, nx=False):
        self.ex_seen.append((v, ex))
        if nx and self._live(k) is not None:
            return None
        self.data[k] = (v, self.clock() + ex)
        return True

    def get(self, k):
        if self.fail_get_delete:
            raise ConnectionError("down")
        return self._live(k)

    def delete(self, k):
        if self.fail_get_delete:
            raise ConnectionError("down")
        self.data.pop(k, None)


@pytest.fixture
def clock():
    return FakeClock()


def _redis_store(monkeypatch, fake):
    store = IdempotencyStore()
    monkeypatch.setattr(store, "_client", lambda: fake)
    return store


def test_reserve_uses_a_short_pending_ttl(monkeypatch, clock):
    fake = FakeRedis(clock)
    store = _redis_store(monkeypatch, fake)
    assert store.reserve("w1", "k1") is None
    ttl = idempotency._PENDING_TTL_SECONDS
    assert 120 < ttl <= 600
    assert fake.ex_seen == [(PENDING, ttl)]


def test_finalize_keeps_the_day_ttl(monkeypatch, clock):
    fake = FakeRedis(clock)
    store = _redis_store(monkeypatch, fake)
    store.reserve("w1", "k1")
    store.finalize("w1", "k1", "msg-1")
    assert fake.ex_seen[-1] == ("msg-1", DAY)


def test_failed_release_still_expires_within_the_pending_ttl(monkeypatch, clock):
    fake = FakeRedis(clock)
    store = _redis_store(monkeypatch, fake)
    assert store.reserve("w1", "k1") is None
    fake.fail_get_delete = True
    store.release("w1", "k1")  # swallowed
    fake.fail_get_delete = False
    clock.now += 30
    assert store.reserve("w1", "k1") == PENDING  # still blocking early
    clock.now += PAST_ANY_ALLOWED_PENDING_TTL
    assert store.reserve("w1", "k1") is None  # retry can claim again


def test_memory_pending_stops_blocking_after_the_pending_ttl(monkeypatch, clock):
    monkeypatch.setattr(time, "monotonic", clock)
    store = MemoryIdempotencyStore()
    assert store.reserve("w1", "k1") is None
    clock.now += 30
    assert store.reserve("w1", "k1") == PENDING
    clock.now += PAST_ANY_ALLOWED_PENDING_TTL
    assert store.reserve("w1", "k1") is None


def test_control_replay_after_finalize_returns_the_id(monkeypatch, clock):
    monkeypatch.setattr(time, "monotonic", clock)
    store = MemoryIdempotencyStore()
    store.reserve("w1", "k1")
    store.finalize("w1", "k1", "msg-1")
    clock.now += PAST_ANY_ALLOWED_PENDING_TTL
    assert store.reserve("w1", "k1") == "msg-1"
    store.release("w1", "k1")  # no-op on a finalized key
    assert store.reserve("w1", "k1") == "msg-1"


def test_control_redis_replay_after_finalize_and_release_noop(monkeypatch, clock):
    fake = FakeRedis(clock)
    store = _redis_store(monkeypatch, fake)
    store.reserve("w1", "k1")
    store.finalize("w1", "k1", "msg-1")
    store.release("w1", "k1")
    clock.now += PAST_ANY_ALLOWED_PENDING_TTL
    assert store.reserve("w1", "k1") == "msg-1"
