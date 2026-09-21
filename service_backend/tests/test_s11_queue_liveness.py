"""Sprint-5/11 S1 - RED tests for worker-liveness visibility (AC-11-86).

"A frozen worker is visible within minutes." During the 2026-09-20/21
incident, beat itself stayed healthy the whole 8 hours - a beat-side
heartbeat would have reported everything fine (D20). The signal has to be
stamped by the CONSUMING worker, per queue, so a wedged ``worker_jobs`` (or
a future wedged ``worker_workflow``) is caught independently.

CONTRACT this file pins (the plan names the WIRE shape precisely - "a
platform-permission route reports per queue {queue, lastSeen, stale}" - but
not the module/route path, which S1 names):
- ``app/ops_liveness.py`` (new): ``KNOWN_QUEUES = ("workflow", "jobs")``,
  ``set_client(client)`` test seam mirroring
  ``modules/omnichannel/services/realtime.py``'s existing
  ``_get_client``/``set_client`` pattern (lazy real ``redis.Redis``, real
  code never constructs its own), ``stamp_liveness(queue, *, now=None)``
  (a Redis key per queue, 300s TTL per AC-11-86), and
  ``queue_status(queue, *, now=None) -> {"queue", "lastSeen", "stale"}``.
- ``app/workflow_engine/worker.py``: a Celery task named ``"ops.ping"`` that
  calls ``stamp_liveness(queue)`` for the queue it is invoked with, PLUS
  beat entries publishing it onto EACH queue in ``KNOWN_QUEUES`` every 60s
  (``options={"queue": <that queue>}`` so the ping actually arrives at the
  worker consuming that queue, not just at whichever worker beat's own
  producer happens to default to - a ping that always lands on 'workflow'
  would never catch a wedged worker_jobs).
- ``GET /platform/ops/queues`` (new route) -> ``{"queues": [...]}``, each
  entry ``{"queue", "lastSeen", "stale"}``, gated by
  ``require_platform_permission("tenants.read")`` (R11: reuse an EXISTING
  platform permission key - grepped ``app/permissions/platform_permissions.csv``:
  ``tenants.read`` is already the key every other platform-console READ
  route uses, e.g. ``app/api/v1/platform_tenants.py``'s GET routes; no new
  CSV row, no grant sweep).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import fakeredis
import pytest

from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD, PLATFORM_EMAIL, PLATFORM_PASSWORD


def _login(client, email, password, tenant_slug=None):
    payload = {"email": email, "password": password}
    if tenant_slug is not None:
        payload["tenantSlug"] = tenant_slug
    return client.post("/auth/login", json=payload)


def _platform_headers(client):
    res = _login(client, PLATFORM_EMAIL, PLATFORM_PASSWORD, "platform")
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _demo_headers(client):
    res = _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def fake_redis():
    from app import ops_liveness

    server_client = fakeredis.FakeRedis(decode_responses=True)
    ops_liveness.set_client(server_client)
    yield server_client
    ops_liveness.set_client(None)


# ── the liveness primitives ──────────────────────────────────────────────


def test_queue_status_is_stale_with_no_ping_ever_seen(fake_redis):
    from app.ops_liveness import queue_status

    status = queue_status("jobs")
    assert status == {"queue": "jobs", "lastSeen": None, "stale": True}


def test_stamp_liveness_marks_the_queue_fresh(fake_redis):
    from app.ops_liveness import queue_status, stamp_liveness

    now = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    stamp_liveness("workflow", now=now)
    status = queue_status("workflow", now=now)
    assert status["stale"] is False
    assert status["lastSeen"] is not None


def test_a_ping_older_than_the_300s_ttl_reads_stale(fake_redis):
    from app.ops_liveness import queue_status, stamp_liveness

    started = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    stamp_liveness("jobs", now=started)
    later = started + timedelta(seconds=301)
    assert queue_status("jobs", now=later)["stale"] is True


# ── the ops.ping task + its beat wiring ──────────────────────────────────


def test_ops_ping_task_stamps_the_queue_it_is_invoked_with(fake_redis):
    from app.ops_liveness import queue_status
    from app.workflow_engine.worker import celery_app

    task = celery_app.tasks["ops.ping"]
    task(queue="jobs")
    assert queue_status("jobs")["stale"] is False


def test_beat_publishes_ops_ping_onto_every_known_queue_every_60s():
    from app.workflow_engine.worker import celery_app

    entries = [
        e for e in celery_app.conf.beat_schedule.values() if e.get("task") == "ops.ping"
    ]
    assert entries, "no ops.ping beat entry - AC-11-86"
    pinged_queues = {e.get("options", {}).get("queue") for e in entries}
    assert {"workflow", "jobs"} <= pinged_queues, (
        "a ping that only ever lands on 'workflow' would never catch a "
        "wedged worker_jobs - AC-11-86 says EACH queue"
    )
    assert all(e.get("schedule") == 60.0 for e in entries)


# ── the platform read ─────────────────────────────────────────────────────


def test_platform_ops_queues_route_403s_without_the_platform_permission(client):
    headers = _demo_headers(client)
    res = client.get("/platform/ops/queues", headers=headers)
    assert res.status_code == 403


def test_platform_ops_queues_route_401s_unauthenticated(client):
    res = client.get("/platform/ops/queues")
    assert res.status_code == 401


def test_platform_ops_queues_route_reports_stale_for_an_unpinged_queue(client, fake_redis):
    headers = _platform_headers(client)
    res = client.get("/platform/ops/queues", headers=headers)
    assert res.status_code == 200, res.text
    by_queue = {row["queue"]: row for row in res.json()["queues"]}
    assert by_queue["jobs"]["stale"] is True
    assert by_queue["jobs"]["lastSeen"] is None


def test_platform_ops_queues_route_reports_fresh_right_after_a_stamp(client, fake_redis):
    from app.ops_liveness import stamp_liveness

    stamp_liveness("workflow")
    headers = _platform_headers(client)
    res = client.get("/platform/ops/queues", headers=headers)
    by_queue = {row["queue"]: row for row in res.json()["queues"]}
    assert by_queue["workflow"]["stale"] is False
    assert by_queue["workflow"]["lastSeen"] is not None
