"""Realtime publish client: bounded Redis timeouts, best-effort publish.

The sync client behind ``realtime.publish`` is built with a connect and a read
timeout so an unreachable or stalled Redis returns quickly. The WS subscriber's
own async client stays free of a read timeout (a pub/sub listen blocks).
"""
import logging

import pytest
import redis

from modules.omnichannel.routers import ws
from modules.omnichannel.services import realtime


@pytest.fixture(autouse=True)
def _reset_clients():
    realtime.set_client(None)
    ws.set_async_redis(None)
    yield
    realtime.set_client(None)
    ws.set_async_redis(None)


def test_publish_client_is_built_with_bounded_connect_and_read_timeouts(monkeypatch):
    seen = {}

    class _Client:
        def publish(self, *a, **k):
            return 0

    def fake_from_url(url, **kwargs):
        seen.update(kwargs)
        return _Client()

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(fake_from_url))
    realtime.publish("ws-timeouts", {"type": "ping"})
    for name in ("socket_connect_timeout", "socket_timeout"):
        value = seen.get(name)
        assert isinstance(value, (int, float)) and 0 < value <= 5, (name, seen)


@pytest.mark.parametrize("exc", [redis.exceptions.TimeoutError("slow"), redis.exceptions.ConnectionError("down")])
def test_publish_never_raises_and_logs_one_warning_when_redis_fails(caplog, exc):
    class _Broken:
        def publish(self, *a, **k):
            raise exc

    realtime.set_client(_Broken())
    with caplog.at_level(logging.WARNING, logger=realtime.logger.name):
        assert realtime.publish("ws-timeouts", {"type": "ping"}) is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_ws_async_client_keeps_no_read_timeout(monkeypatch):
    seen = {}

    def fake_from_url(url, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(ws.aioredis, "from_url", fake_from_url)
    ws.get_async_redis()
    assert "socket_timeout" not in seen, seen
