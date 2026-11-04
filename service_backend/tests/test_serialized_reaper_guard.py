"""Stale-run reaper only fails rows still RUNNING and still stale; the
lease heartbeat keeps stamping the live run's DB heartbeat after a lost lease."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql

from app.models import DEFAULT_TENANT_ID
from app.models.workflow import RUN_FAILED, RUN_RUNNING, RUN_SUCCESS, Workflow, WorkflowRun
from app.workflow_engine.serialization import (
    _LeaseHeartbeat,
    assign_run_correlation,
    correlation_digest,
    reap_stale_running_serialized_runs,
)

STALE = timedelta(minutes=2)
_FMT = "%Y-%m-%d %H:%M:%S.%f"


def _definition():
    return {
        "schemaVersion": 2,
        "execution": {"mode": "serialized", "correlationKey": "{{ trigger.conversationId }}"},
        "nodes": [],
        "edges": [],
    }


def _stale_running(db, key, run_id, now):
    wf = Workflow(tenant_id=DEFAULT_TENANT_ID, name="Reaper " + run_id, description="",
                  draft_definition_json=_definition())
    db.add(wf)
    db.flush()
    row = WorkflowRun(
        id=run_id,
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=wf.id,
        status=RUN_RUNNING,
        definition_snapshot_json=_definition(),
        trigger_payload_json={"triggeredBy": "event", "omnichannel": {"conversationId": key}},
        created_at=now - timedelta(minutes=10),
        started_at=now - timedelta(minutes=10),
        heartbeat_at=now - timedelta(minutes=10),
    )
    assign_run_correlation(row)
    db.add(row)
    db.commit()
    return wf, row


def _race_before_update(db, run_id, assignments, params):
    """Right before the reaper's UPDATE of workflow_runs hits the DB, another
    transaction on the same connection changes the row (the SELECT-to-write window)."""
    engine = db.get_bind()
    fired = []

    def hook(conn, cursor, statement, parameters, context, executemany):
        if fired or not statement.lstrip().upper().startswith("UPDATE WORKFLOW_RUNS"):
            return
        fired.append(1)
        cur = conn.connection.cursor()
        cur.execute(f"UPDATE workflow_runs SET {assignments} WHERE id = ?", (*params, run_id))

    event.listen(engine, "before_cursor_execute", hook)
    return engine, hook, fired


@pytest.mark.parametrize("variant", ["finished", "fresh_heartbeat"])
def test_reaper_skips_row_that_changed_after_select(session_factory, variant):
    db = session_factory()
    now = datetime.now(timezone.utc)
    _wf, row = _stale_running(db, "conv-race", "race-" + variant, now)
    if variant == "finished":
        engine, hook, fired = _race_before_update(db, row.id, "status = ?", (RUN_SUCCESS,))
    else:
        engine, hook, fired = _race_before_update(
            db, row.id, "heartbeat_at = ?", ((now + timedelta(seconds=1)).strftime(_FMT),)
        )
    try:
        scopes = reap_stale_running_serialized_runs(db, now=now, stale_after=STALE)
    finally:
        event.remove(engine, "before_cursor_execute", hook)
    assert fired, "the reaper never issued an UPDATE; the race was not exercised"
    assert scopes == []
    db.expire_all()
    got = db.query(WorkflowRun).filter(WorkflowRun.id == row.id).one()
    assert got.status == (RUN_SUCCESS if variant == "finished" else RUN_RUNNING)
    assert got.error is None


def test_reaper_control_fails_genuinely_stale_running_row(session_factory):
    db = session_factory()
    now = datetime.now(timezone.utc)
    wf, row = _stale_running(db, "conv-stale", "stale-control", now)
    scopes = reap_stale_running_serialized_runs(db, now=now, stale_after=STALE)
    assert scopes == [(DEFAULT_TENANT_ID, wf.id, correlation_digest("conv-stale"))]
    db.expire_all()
    got = db.query(WorkflowRun).filter(WorkflowRun.id == row.id).one()
    assert got.status == RUN_FAILED and "heartbeat" in got.error and got.finished_at is not None


def test_reaper_selection_skips_locked_rows_on_postgres(session_factory, monkeypatch):
    """Structural pin (sqlite cannot lock rows): with the dialect reported as
    postgresql the executed statements must carry FOR UPDATE SKIP LOCKED."""
    db = session_factory()
    now = datetime.now(timezone.utc)
    _stale_running(db, "conv-pg", "pg-shape", now)
    engine = db.get_bind()
    monkeypatch.setattr(engine.dialect, "name", "postgresql")
    seen = []

    def hook(conn, clauseelement, multiparams, params, execution_options):
        try:
            seen.append(str(clauseelement.compile(dialect=postgresql.dialect())))
        except Exception:  # noqa: BLE001 - non-compilable internals are irrelevant
            pass

    event.listen(engine, "before_execute", hook)
    try:
        reap_stale_running_serialized_runs(db, now=now, stale_after=STALE)
    finally:
        event.remove(engine, "before_execute", hook)
    assert any("FOR UPDATE SKIP LOCKED" in s for s in seen), seen


class _Stop:
    def __init__(self, waits_before_stop):
        self.n = waits_before_stop
        self.set_called = False

    def wait(self, timeout=None):
        if self.n <= 0:
            return True
        self.n -= 1
        return False

    def set(self):
        self.set_called = True


class _Client:
    def __init__(self, mode):
        self.mode = mode
        self.renew_calls = 0

    def renew(self, key, token, ttl):
        self.renew_calls += 1
        if self.mode == "raise":
            raise OSError("redis down")
        return False


@pytest.mark.parametrize("mode", ["false", "raise"])
def test_heartbeat_keeps_stamping_db_after_lease_lost(mode):
    client = _Client(mode)
    touched = []
    hb = _LeaseHeartbeat(client, "k", "t", ttl_seconds=30, touch=touched.append)
    hb.current_run_id = "live-run"
    hb._stop = _Stop(3)
    hb._run()
    assert hb.lost.is_set()
    assert client.renew_calls == 1  # no Redis renew after the loss
    assert touched == ["live-run"] * 3


def test_heartbeat_after_lease_loss_stops_without_a_current_run():
    client = _Client("false")
    touched = []
    hb = _LeaseHeartbeat(client, "k", "t", ttl_seconds=30, touch=touched.append)
    hb.current_run_id = None
    hb._stop = _Stop(3)
    hb._run()
    assert hb.lost.is_set() and client.renew_calls == 1
    assert touched == []
