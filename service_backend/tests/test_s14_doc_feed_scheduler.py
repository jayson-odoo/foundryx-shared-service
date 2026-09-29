"""sprint-5/14 S0 - beat sweep, job registration, orphan hook (AC-14-33, 83).

`modules.autocount.doc_feed.scheduler.sweep_doc_feeds` does not exist yet
(S0 red, D21). Mirrors `tests/test_autocount_scheduler.py`'s own house
pattern (direct `AcDocFeed`/`BackgroundJob` manipulation, no HTTP).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import BackgroundJob
from app.models.module import MODULE_STATUS_INACTIVE, Module, TenantModule
from app.models.tenant import Tenant
from modules.autocount.doc_feed.scheduler import sweep_doc_feeds
from modules.autocount.models import AcDocFeed

from .s14_doc_feed_helpers import wired_company

NOW = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)


def _feed(db, company, ac_conn, *, feed_key="delivery_orders", mode="push", next_poll_at=None, next_sweep_at=None) -> AcDocFeed:
    row = AcDocFeed(
        tenant_id=company.tenant_id, company_id=company.id, feed=feed_key,
        connection_id=ac_conn.id, book="db1", mode=mode,
        next_poll_at=next_poll_at, next_sweep_at=next_sweep_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _jobs_for(db, feed_id: str):
    return db.query(BackgroundJob).filter(BackgroundJob.payload_json["feedId"].as_string() == feed_id).all()


def _deactivate_autocount_module(db, tenant_id: str = DEFAULT_TENANT_ID) -> None:
    tm = (
        db.query(TenantModule)
        .join(Module, Module.id == TenantModule.module_id)
        .filter(TenantModule.tenant_id == tenant_id, Module.name == "autocount")
        .one()
    )
    tm.status = MODULE_STATUS_INACTIVE
    db.commit()


# ── due poll hourly (AC-14-33) ───────────────────────────────────────────────


def test_a_due_poll_is_enqueued_and_rearmed_60_minutes_out(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, next_poll_at=NOW - timedelta(minutes=1))

    sweep_doc_feeds(db, now=NOW)

    jobs = _jobs_for(db, feed.id)
    assert len(jobs) == 1
    assert jobs[0].payload_json.get("kind") == "poll"
    db.refresh(feed)
    assert feed.next_poll_at >= NOW + timedelta(minutes=59)


def test_a_due_sweep_is_enqueued_and_rearmed_24_hours_out(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(
        db, co, ac_conn,
        next_poll_at=NOW + timedelta(hours=1),  # NOT due
        next_sweep_at=NOW - timedelta(minutes=1),  # due
    )

    sweep_doc_feeds(db, now=NOW)

    jobs = _jobs_for(db, feed.id)
    assert len(jobs) == 1
    assert jobs[0].payload_json.get("kind") == "sweep"
    db.refresh(feed)
    assert feed.next_sweep_at >= NOW + timedelta(hours=23)


def test_a_due_branch_pull_is_enqueued_and_rearmed_24_hours_out(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, feed_key="branches", next_poll_at=NOW - timedelta(minutes=1))

    sweep_doc_feeds(db, now=NOW)

    jobs = _jobs_for(db, feed.id)
    assert len(jobs) == 1
    assert jobs[0].payload_json.get("kind") == "branch"
    db.refresh(feed)
    assert feed.next_poll_at >= NOW + timedelta(hours=23)


# ── a busy feed is not claimed (no lost tick) ───────────────────────────────


def test_a_feed_with_an_unfinished_run_job_is_not_claimed_again(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, next_poll_at=NOW - timedelta(minutes=1))
    db.add(
        BackgroundJob(
            tenant_id=co.tenant_id, type="autocount_doc_feed_run", status="running",
            payload_json={"feedId": feed.id, "kind": "poll"},
        )
    )
    db.commit()

    sweep_doc_feeds(db, now=NOW)

    jobs = _jobs_for(db, feed.id)
    assert len(jobs) == 1  # the pre-existing one only - nothing NEW enqueued
    db.refresh(feed)
    # Not re-armed either - it stays due so the NEXT beat minute picks it up.
    assert feed.next_poll_at <= NOW


def test_two_concurrent_sweeps_only_one_claims_the_due_feed(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, next_poll_at=NOW - timedelta(minutes=1))

    sweep_doc_feeds(db, now=NOW)
    sweep_doc_feeds(db, now=NOW)  # simulates a second beat tick racing the first

    assert len(_jobs_for(db, feed.id)) == 1


# ── exclusions (AC-14-33) ────────────────────────────────────────────────────


def test_an_off_feed_is_never_swept(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, mode="off", next_poll_at=NOW - timedelta(minutes=1))

    sweep_doc_feeds(db, now=NOW)
    assert _jobs_for(db, feed.id) == []


def test_a_feed_of_an_inactive_company_is_never_swept(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, next_poll_at=NOW - timedelta(minutes=1))
    co.is_active = False
    db.commit()

    sweep_doc_feeds(db, now=NOW)
    assert _jobs_for(db, feed.id) == []


def test_a_feed_of_a_tenant_with_the_module_inactive_is_never_swept(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, next_poll_at=NOW - timedelta(minutes=1))
    _deactivate_autocount_module(db, co.tenant_id)

    sweep_doc_feeds(db, now=NOW)
    assert _jobs_for(db, feed.id) == []


def test_a_feed_of_a_suspended_tenant_is_never_swept(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn, next_poll_at=NOW - timedelta(minutes=1))
    tenant = db.query(Tenant).filter(Tenant.id == co.tenant_id).one()
    tenant.status.blocks_access = True
    db.commit()

    sweep_doc_feeds(db, now=NOW)
    assert _jobs_for(db, feed.id) == []


# ── job handler registration (AC-14-83) ─────────────────────────────────────


def test_both_doc_feed_job_types_are_registered_on_worker_boot():
    """Mirrors `tests/test_worker_module_boot.py`'s subprocess pattern (the
    `autocount_http` prod incident) - a bare worker import, no FastAPI
    lifespan, must resolve both new job types."""
    import subprocess
    import sys
    import os
    from pathlib import Path

    result = subprocess.run(
        [
            sys.executable, "-c",
            "import app.workflow_engine.worker\n"
            "from app.jobs.registry import handler_for\n"
            "handler_for('autocount_doc_feed_run')\n"
            "handler_for('autocount_doc_feed_backfill')\n"
            "print('ok')\n",
        ],
        cwd=str(Path(__file__).resolve().parent.parent),
        env={**os.environ, "DATABASE_URL": "sqlite://", "CELERY_TASK_ALWAYS_EAGER": "true"},
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


# ── orphan hook (AC-14-83) ───────────────────────────────────────────────────


def test_orphan_hook_fails_an_open_feed_run_as_interrupted(session_factory):
    from modules.autocount.bootstrap import on_job_orphaned
    from modules.autocount.models import AcDocFeedRun

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    job = BackgroundJob(
        tenant_id=co.tenant_id, type="autocount_doc_feed_run", status="running",
        payload_json={"feedId": feed.id, "kind": "poll"},
    )
    db.add(job)
    db.flush()
    run = AcDocFeedRun(
        tenant_id=co.tenant_id, company_id=co.id, feed_id=feed.id, feed="delivery_orders",
        kind="poll", dry_run=False, job_id=job.id, started_at=NOW,
    )
    db.add(run)
    db.commit()

    on_job_orphaned(db, job, now=NOW + timedelta(minutes=5))
    db.commit()

    db.refresh(run)
    assert run.outcome == "FAILED"
    assert run.finished_at is not None
    assert "Interrupted" in (run.error or "")


def test_orphan_hook_stops_an_interrupted_backfill(session_factory):
    from modules.autocount.bootstrap import on_job_orphaned
    from modules.autocount.models import AcDocFeedBackfill

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    job = BackgroundJob(
        tenant_id=co.tenant_id, type="autocount_doc_feed_backfill", status="running",
        payload_json={"backfillId": "placeholder"},
    )
    db.add(job)
    db.flush()
    backfill = AcDocFeedBackfill(
        tenant_id=co.tenant_id, company_id=co.id, feed_id=feed.id, feed="delivery_orders",
        book="db1", dry_run=False, from_day=date(2023, 1, 1), to_day=date(2026, 9, 29),
        next_day=date(2024, 5, 1), status="running", job_id=job.id, started_at=NOW,
    )
    db.add(backfill)
    db.commit()
    job.payload_json = {"backfillId": backfill.id}
    db.commit()

    on_job_orphaned(db, job, now=NOW + timedelta(minutes=5))
    db.commit()

    db.refresh(backfill)
    assert backfill.status == "stopped"
