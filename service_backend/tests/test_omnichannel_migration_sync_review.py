"""Lane SS-MIGRATION-SYNC (plan 52) - reviewer round 1 regression tests."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE, JOB_FAILED, JOB_PENDING, JOB_RUNNING, BackgroundJob

from modules.omnichannel.repositories.migration_sync_repository import MigrationSyncRepository
from tests.test_omnichannel_migration_sync_support import (
    SYNCS,
    aware,
    close_all_worlds,
    get_sync,
    hint_ids,
    make_due,
    new_world,
    not_due,
    post_hint,
    run_due_syncs,
    set_sync,
    start_sync,
    stub_enqueue,
    sync_jobs,
    sync_row,
    utcnow,
    webhook_path,
)
from tests.test_omnichannel_migration_sync_ticks import _ready
from tests.test_omnichannel_respondio_migration_jobs import _auth


@pytest.fixture(autouse=True)
def _close_worlds(session_factory):
    yield
    close_all_worlds()


# B1 ─────────────────────────────────────────────────────────────────────────
def test_b1_hint_arriving_mid_tick_for_an_already_processed_contact_is_kept(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch, contacts=(910001, 910002))
    path = webhook_path(client, h, sid)
    w.fake.add_message(910001, 2, text="first news")
    assert post_hint(client, path, {"contact": {"id": 910001}}).status_code == 200
    w.fake.add_message(910002, 2, text="b news")
    assert post_hint(client, path, {"contact": {"id": 910002}}).status_code == 200
    not_due(w.db, sid)
    fired = []

    def late(method, p):
        if p.endswith("/contact/id:910002/message/list") and not fired:
            w.fake.add_message(910001, 3, text="late news")
            fired.append(
                MigrationSyncRepository(w.db).add_hint(DEFAULT_TENANT_ID, sid, "910001", datetime.now(timezone.utc))
            )

    w.fake.hooks.append(late)
    run_due_syncs(w.db)
    w.fake.hooks.clear()
    assert fired, "the mid-tick webhook fired"
    assert hint_ids(w.db, sid) == ["910001"], "the late hint survives the tick"

    make_due(w.db, sid, full_sweep="not_due")
    run_due_syncs(w.db)
    assert "late news" in [m.body for m in w.messages_of(w.contact_by_cid(910001))]
    assert hint_ids(w.db, sid) == []


def _tick_job(db, sid, kind="poll", status=JOB_RUNNING):
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type="omnichannel.respondio_sync", status=status,
        payload_json={"syncId": sid, "kind": kind},
    )
    db.add(job)
    db.commit()
    return job


def _emails(db, to):
    from app.models.email_outbox import EmailOutbox

    db.expire_all()
    return db.query(EmailOutbox).filter(EmailOutbox.to_email == to).count()


# S1 ─────────────────────────────────────────────────────────────────────────
def test_s1_token_rejection_does_not_overwrite_stopping(client, session_factory, monkeypatch):
    from app.jobs.service import run_job
    from modules.omnichannel.models import MigrationSync

    w, h, sid = _ready(client, session_factory, monkeypatch)
    enqueued = stub_enqueue(monkeypatch)
    make_due(w.db, sid)
    run_due_syncs(w.db)  # tick enqueued (stubbed), not run
    (tick,) = sync_jobs(w.db)

    def stop_now(method, path):
        w.db.query(MigrationSync).filter(MigrationSync.id == sid).update({"status": "stopping"}, synchronize_session=False)

    w.fake.hooks.append(stop_now)
    w.fake.fail_all = 401
    run_job(w.db, tick.id)

    row = sync_row(w.db, sid)
    assert row.status == "stopping" and row.paused_reason is None


def test_s1_token_rejection_keeps_a_manual_pause_reason(client, session_factory, monkeypatch):
    from app.jobs.service import run_job
    from modules.omnichannel.models import MigrationSync
    from tests.conftest import ACTIVE_EMAIL

    w, h, sid = _ready(client, session_factory, monkeypatch)
    stub_enqueue(monkeypatch)
    make_due(w.db, sid)
    run_due_syncs(w.db)
    (tick,) = sync_jobs(w.db)
    before = _emails(w.db, ACTIVE_EMAIL)

    def pause_now(method, path):
        w.db.query(MigrationSync).filter(MigrationSync.id == sid).update(
            {"status": "paused", "paused_reason": "manual"}, synchronize_session=False
        )

    w.fake.hooks.append(pause_now)
    w.fake.fail_all = 401
    run_job(w.db, tick.id)

    row = sync_row(w.db, sid)
    assert row.status == "paused" and row.paused_reason == "manual"
    assert _emails(w.db, ACTIVE_EMAIL) == before, "no token email for a pause the user chose"


# S2 ─────────────────────────────────────────────────────────────────────────
def test_s2_stop_waits_while_a_migration_job_runs(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    running = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type="omnichannel.respondio_migration", status=JOB_RUNNING,
        payload_json={"workspaceId": w.ws.id, "mode": "run", "source": "api", "connectionId": w.conn.id},
    )
    w.db.add(running)
    w.db.commit()

    res = client.post(f"{SYNCS}/{sid}/stop", headers=h)
    assert res.status_code == 200 and res.json()["status"] == "stopping"
    assert sync_jobs(w.db) == [], "no final tick while a migration job is running"

    running.status = JOB_DONE
    w.db.commit()
    run_due_syncs(w.db)  # the sweep picks the stopping sync up (eager: runs inline)
    assert [j.payload_json["kind"] for j in sync_jobs(w.db)] == ["final"]
    assert get_sync(client, h, sid)["status"] == "stopped"


# S3 ─────────────────────────────────────────────────────────────────────────
def test_s3_a_dead_tick_is_failed_by_the_orphan_sweep_and_the_sync_ticks_again(client, session_factory, monkeypatch):
    from app.jobs.registry import types_that_heartbeat
    from app.jobs.service import JobService
    from modules.omnichannel.services.migration_sync_service import SYNC_JOB_TYPE

    assert SYNC_JOB_TYPE in types_that_heartbeat()
    w, h, sid = _ready(client, session_factory, monkeypatch)
    dead = _tick_job(w.db, sid)
    old = utcnow() - timedelta(hours=3)
    w.db.query(BackgroundJob).filter(BackgroundJob.id == dead.id).update(
        {"started_at": old, "heartbeat_at": old}, synchronize_session=False
    )
    set_sync(w.db, sid, running_job_id=dead.id)
    make_due(w.db, sid)
    run_due_syncs(w.db)
    assert len(sync_jobs(w.db)) == 1, "the dead tick still blocks until it is swept"

    JobService(w.db).fail_orphaned_running_jobs()
    w.db.expire_all()
    assert w.db.get(BackgroundJob, dead.id).status == JOB_FAILED

    run_due_syncs(w.db)
    assert len(sync_jobs(w.db)) == 2
    assert get_sync(client, h, sid)["runningJobId"] is None


def test_s3_a_live_tick_beats(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    beats = []
    from app.jobs.service import JobService

    real = JobService.heartbeat
    monkeypatch.setattr(JobService, "heartbeat", lambda self, job_id, **k: beats.append(job_id) or real(self, job_id, **k))
    w.fake.add_contact(910002, first="Beat")
    w.fake.add_message(910002, 1, text="b")
    make_due(w.db, sid)
    run_due_syncs(w.db)
    assert beats, "a running tick stamps its heartbeat"


# S4 ─────────────────────────────────────────────────────────────────────────
def test_s4_a_crashing_poll_backs_off_instead_of_retrying_every_minute(client, session_factory, monkeypatch):
    import modules.omnichannel.services.migration_sync_service as svc

    w, h, sid = _ready(client, session_factory, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("internal secret detail")

    monkeypatch.setattr(svc._Tick, "_mapping", boom)
    make_due(w.db, sid)
    run_due_syncs(w.db)

    item = get_sync(client, h, sid)
    assert item["status"] == "active" and item["runningJobId"] is None
    assert item["lastError"] and "internal secret detail" not in item["lastError"]
    next_at = aware(sync_row(w.db, sid).next_sync_at)
    assert next_at > utcnow() + timedelta(minutes=10), "next poll advanced by the interval"
    jobs_before = len(sync_jobs(w.db))
    run_due_syncs(w.db)
    assert len(sync_jobs(w.db)) == jobs_before, "no 60 s retry loop"


# B2 ─────────────────────────────────────────────────────────────────────────
def test_m2_running_job_id_is_cleared_after_a_successful_tick(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    make_due(w.db, sid)
    run_due_syncs(w.db)
    assert sync_row(w.db, sid).running_job_id is None
    assert get_sync(client, h, sid)["runningJobId"] is None


def test_m3_empty_source_values_never_clear_ours(client, session_factory, monkeypatch):
    from tests.test_omnichannel_migration_sync_ticks import _world_for_q3

    w, h, sid = _world_for_q3(client, session_factory, monkeypatch)
    a = w.contact_by_cid(910001)
    before = (a.first_name, a.last_name, a.email, dict(a.custom_fields_json or {}))
    w.fake.set_contact(910001, firstName=None, lastName=None, email=None, custom_fields=[{"name": "Plan", "value": ""}])
    make_due(w.db, sid, full_sweep="not_due")
    run_due_syncs(w.db)
    a = w.contact_by_cid(910001)
    assert (a.first_name, a.last_name, a.email, dict(a.custom_fields_json or {})) == before


def test_m5_a_sweep_cut_short_by_a_pause_does_not_stamp_the_sweep(client, session_factory, monkeypatch):
    from modules.omnichannel.models import MigrationSync

    w, h, sid = _ready(client, session_factory, monkeypatch, contacts=(910001, 910003))
    make_due(w.db, sid, full_sweep="due")
    stamp = aware(sync_row(w.db, sid).last_full_sweep_at)

    def pause(method, path):
        if path.endswith("/message/list"):
            w.db.query(MigrationSync).filter(MigrationSync.id == sid).update({"status": "paused"}, synchronize_session=False)

    w.fake.hooks.append(pause)
    run_due_syncs(w.db)
    assert aware(sync_row(w.db, sid).last_full_sweep_at) == stamp


def test_m5_a_sweep_that_hits_rate_limits_does_not_stamp_the_sweep(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch, contacts=(910001, 910003))
    make_due(w.db, sid, full_sweep="due")
    stamp = aware(sync_row(w.db, sid).last_full_sweep_at)

    def limit(method, path):
        if path.endswith("/message/list"):
            w.fake.rate_limited = True

    w.fake.hooks.append(limit)
    run_due_syncs(w.db)
    assert aware(sync_row(w.db, sid).last_full_sweep_at) == stamp
    w.fake.hooks.clear()
    w.fake.rate_limited = False
    make_due(w.db, sid, full_sweep=None)
    run_due_syncs(w.db)
    assert aware(sync_row(w.db, sid).last_full_sweep_at) > stamp, "the next clean tick completes the sweep"


def test_m7_a_second_claim_returns_none_and_stop_while_a_tick_runs_defers_to_it(client, session_factory, monkeypatch):
    from app.jobs.service import run_job
    from modules.omnichannel.services.migration_sync_service import _enqueue_tick

    w, h, sid = _ready(client, session_factory, monkeypatch)
    enqueued = stub_enqueue(monkeypatch)
    first = _enqueue_tick(w.db, DEFAULT_TENANT_ID, sid, "poll")
    assert first is not None and _enqueue_tick(w.db, DEFAULT_TENANT_ID, sid, "poll") is None
    assert len(sync_jobs(w.db)) == 1

    res = client.post(f"{SYNCS}/{sid}/stop", headers=h)
    assert res.status_code == 200 and res.json()["status"] == "stopping"
    assert len(sync_jobs(w.db)) == 1, "Stop while a tick is pending creates no second job"

    run_job(w.db, first.id)  # the running tick finishes ...
    by_id = {j.id: j.payload_json["kind"] for j in sync_jobs(w.db)}
    assert sorted(by_id.values()) == ["final", "poll"], "... and enqueues the final tick"
    assert by_id[enqueued[-1]] == "final"


def test_hint_repeated_at_the_cap_still_bumps(client, session_factory, monkeypatch):
    from modules.omnichannel.models import MigrationSyncHint

    w, h, sid = _ready(client, session_factory, monkeypatch)
    path = webhook_path(client, h, sid)
    old = utcnow() - timedelta(hours=1)
    w.db.bulk_insert_mappings(
        MigrationSyncHint,
        [
            {"tenant_id": DEFAULT_TENANT_ID, "sync_id": sid, "external_contact_id": str(300000 + i), "created_at": old}
            for i in range(5000)
        ],
    )
    w.db.commit()
    assert post_hint(client, path, {"contact": {"id": 300007}}).status_code == 200
    w.db.expire_all()
    stamps = {
        r.external_contact_id: aware(r.created_at)
        for r in w.db.query(MigrationSyncHint).filter(MigrationSyncHint.sync_id == sid).all()
    }
    assert len(stamps) == 5000
    assert stamps["300007"] > old + timedelta(minutes=30), "the repeat re-stamped the existing row"
    assert stamps["300008"] == old
    assert post_hint(client, path, {"contact": {"id": 399999}}).status_code in (200, 204)
    assert "399999" not in hint_ids(w.db, sid), "a NEW contact over the cap is still dropped"
