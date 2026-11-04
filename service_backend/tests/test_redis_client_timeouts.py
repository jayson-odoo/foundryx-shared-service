"""Sync Redis clients use bounded connect and read timeouts.

For each client: (1) the kwargs handed to ``redis.Redis.from_url`` carry positive
bounds within the stated seconds; (2) a Redis timeout keeps that client's current
failure handling. Singletons and seams are restored after each test.
"""
import logging

import pytest
import redis

from app.models import DEFAULT_TENANT_ID

TIMEOUT = redis.exceptions.TimeoutError("timed out")


class _Broken:
    """A client whose every command times out."""

    def __getattr__(self, name):
        def call(*a, **k):
            raise TIMEOUT

        return call


def _capture_from_url(monkeypatch):
    seen = {}

    def fake_from_url(url, **kwargs):
        seen.update(kwargs)
        return _Broken()

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(fake_from_url))
    return seen


def _bounded(seen, connect_max, read_max):
    connect, read = seen.get("socket_connect_timeout"), seen.get("socket_timeout")
    assert isinstance(connect, (int, float)) and 0 < connect <= connect_max, seen
    assert isinstance(read, (int, float)) and 0 < read <= read_max, seen


# ── idempotency store ────────────────────────────────────────────────────────
def test_idempotency_client_is_built_with_bounded_timeouts(monkeypatch):
    from modules.omnichannel.services.idempotency import IdempotencyStore

    seen = _capture_from_url(monkeypatch)
    IdempotencyStore()._client()
    _bounded(seen, 1.0, 1.0)


def test_idempotency_store_falls_back_to_memory_when_redis_times_out(monkeypatch):
    from modules.omnichannel.services.idempotency import IdempotencyStore

    store = IdempotencyStore()
    monkeypatch.setattr(store, "_client", lambda: _Broken())
    assert store.reserve("ws-t", "key-1") is None  # claimed in memory
    assert store.reserve("ws-t", "key-1") is not None  # second claim sees it
    store.finalize("ws-t", "key-1", "msg-1")
    assert store.lookup("ws-t", "key-1") == "msg-1"
    store.release("ws-t", "key-2")  # no exception


# ── ops liveness ─────────────────────────────────────────────────────────────
@pytest.fixture
def liveness():
    from app import ops_liveness

    ops_liveness.set_client(None)
    yield ops_liveness
    ops_liveness.set_client(None)


def test_ops_liveness_client_is_built_with_bounded_timeouts(monkeypatch, liveness):
    seen = _capture_from_url(monkeypatch)
    liveness._get_client()
    _bounded(seen, 1.0, 1.0)


def test_ops_liveness_timeout_is_a_warning_and_reads_stale(caplog, liveness):
    liveness.set_client(_Broken())
    with caplog.at_level(logging.WARNING):
        assert liveness.stamp_liveness("workflow") is None
        status = liveness.queue_status("workflow", consuming={})
    assert status["stale"] is True and status["lastSeen"] is None
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) >= 2


# ── workflow Redis data action ───────────────────────────────────────────────
def test_workflow_data_client_is_built_with_bounded_timeouts(monkeypatch):
    from app.workflow_engine.actions.redis_actions import _default_client

    seen = _capture_from_url(monkeypatch)
    _default_client()
    _bounded(seen, 1.0, 2.0)


def test_workflow_data_timeout_becomes_the_unavailable_action_error():
    from app.workflow_engine.actions.redis_actions import (
        ActionError,
        redis_command,
        use_workflow_redis_client,
    )

    with use_workflow_redis_client(_Broken()):
        with pytest.raises(ActionError) as err:
            redis_command(None, DEFAULT_TENANT_ID, {"operation": "get", "key": "k1"}, {})
    assert "unavailable" in str(err.value)


# ── serialized-run lease client ──────────────────────────────────────────────
def test_lease_client_is_built_with_bounded_timeouts(monkeypatch):
    from app.workflow_engine.serialization import RedisLeaseClient

    seen = _capture_from_url(monkeypatch)
    RedisLeaseClient()
    _bounded(seen, 1.0, 2.0)


def test_lease_acquire_timeout_raises_coordination_unavailable(session_factory):
    from app.workflow_engine.serialization import (
        RedisLeaseClient,
        SerializedCoordinationUnavailable,
        drain_serialized_runs,
    )

    db = session_factory()
    try:
        with pytest.raises(SerializedCoordinationUnavailable):
            drain_serialized_runs(db, DEFAULT_TENANT_ID, "wf-t", "digest-t",
                                  lease_client=RedisLeaseClient(client=_Broken()))
    finally:
        db.close()


def test_lease_renew_timeout_marks_the_lease_lost():
    from app.workflow_engine.serialization import RedisLeaseClient, _LeaseHeartbeat

    class _OneTick:
        def wait(self, interval):
            return False  # the interval elapsed once

        def set(self):
            pass

    beat = _LeaseHeartbeat(RedisLeaseClient(client=_Broken()), "k", "tok", 30)
    beat._stop = _OneTick()
    beat._run()
    assert beat.lost.is_set()


def test_lease_release_timeout_is_logged_and_swallowed(session_factory, caplog):
    from app.workflow_engine.serialization import drain_serialized_runs

    class _ReleaseTimesOut:
        def acquire(self, key, token, ttl_seconds):
            return True

        def renew(self, key, token, ttl_seconds):
            return True

        def release(self, key, token):
            raise TIMEOUT

    db = session_factory()
    try:
        with caplog.at_level(logging.ERROR):
            result = drain_serialized_runs(db, DEFAULT_TENANT_ID, "wf-t2", "digest-t2",
                                           lease_client=_ReleaseTimesOut())
    finally:
        db.close()
    assert result == {"admitted": True, "drained": 0}
    assert "lease release failed" in caplog.text
