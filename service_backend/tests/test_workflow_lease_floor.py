"""Settings floor for workflow_serialized_lease_seconds (lease renew safety)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

LEASE_FLOOR = 30


@pytest.mark.parametrize("value", [0, 1, 29])
def test_lease_below_floor_is_refused(monkeypatch, value):
    monkeypatch.setenv("WORKFLOW_SERIALIZED_LEASE_SECONDS", str(value))
    with pytest.raises(ValidationError) as exc:
        Settings()
    assert "workflow_serialized_lease_seconds" in str(exc.value)


@pytest.mark.parametrize("value", [30, 120])
def test_lease_at_or_above_floor_loads(monkeypatch, value):
    monkeypatch.setenv("WORKFLOW_SERIALIZED_LEASE_SECONDS", str(value))
    assert Settings().workflow_serialized_lease_seconds == value


def test_default_lease_loads(monkeypatch):
    monkeypatch.delenv("WORKFLOW_SERIALIZED_LEASE_SECONDS", raising=False)
    assert Settings().workflow_serialized_lease_seconds == 120


def test_renew_interval_at_floor_exceeds_worst_case_renew_wait():
    from app.workflow_engine import serialization as s

    worst = (
        s._LEASE_SOCKET_CONNECT_TIMEOUT_SECONDS + s._LEASE_SOCKET_READ_TIMEOUT_SECONDS
    )
    assert s._renew_interval(LEASE_FLOOR) > worst


@pytest.mark.parametrize("ttl", [30, 120])
def test_heartbeat_waits_the_shared_renew_interval(ttl):
    from app.workflow_engine import serialization as s

    waits = []

    class _Stop:
        def wait(self, timeout=None):
            waits.append(timeout)
            return True  # stop after the first wait

    class _Client:
        def renew(self, key, token, ttl_seconds):
            return True

    heartbeat = s._LeaseHeartbeat(_Client(), "k", "t", ttl_seconds=ttl)
    heartbeat._stop = _Stop()
    heartbeat._run()
    assert waits == [s._renew_interval(ttl)]
