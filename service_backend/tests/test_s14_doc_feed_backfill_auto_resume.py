"""SS-BACKFILL-AUTO-RESUME - a backfill a deploy (worker loss) stopped
continues by itself from its saved day.

A deploy recreates the jobs worker with no grace: the running segment is
killed, never re-run (acks_late off). Core's orphan sweep / the doc-feed
reaper then mark the row ``stopped`` with ``ORPHANED`` / ``JOB_ENDED``. The
doc-feed beat now re-queues such a row through the SAME path as Resume, at
most ``BACKFILL_AUTO_RESUME_MAX`` times in a row without a saved day in
between; each automatic resume is logged as a run row (the feed's history).

A user Stop, a time limit, a crash and CRM / AutoCount errors keep today's
behaviour: the row stays stopped for a person to Resume.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from modules.autocount.bootstrap import on_job_orphaned
from modules.autocount.doc_feed.scheduler import (
    BACKFILL_AUTO_RESUME_MAX,
    auto_resume_lost_backfills,
    reap_stale_backfills,
    sweep_doc_feeds,
)
from modules.autocount.models import AcDocFeedRun
from modules.autocount.services.doc_feed_service import DocFeedService

from .s14_doc_feed_helpers import wired_company
from .test_s14_doc_feed_backfill_chunked import (
    DO,
    NOW,
    _backfill,
    _feed,
    _job,
    _Transport,
    _Vendor,
)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


def _history(db, feed_id):
    return (
        db.query(AcDocFeedRun)
        .filter(AcDocFeedRun.feed_id == feed_id, AcDocFeedRun.error_code.like("AUTO_RESUME%"))
        .order_by(AcDocFeedRun.started_at)
        .all()
    )


def _no_dispatch(monkeypatch):
    """Queue the resumed segment but never run it (the job stays pending)."""
    monkeypatch.setattr(DocFeedService, "_dispatch", lambda self, job, handler, *, transport: None)


# ── worker loss -> auto-resumed from the saved day ──────────────────────────


@pytest.mark.parametrize("code", ["ORPHANED", "JOB_ENDED", "JOB_ORPHANED"])
def test_a_backfill_stopped_by_a_worker_loss_is_resumed_from_its_saved_day(db, code):
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    dead = _job(db, co.tenant_id, status="failed")
    bf = _backfill(db, feed, from_day=date(2026, 9, 20), to_day=date(2026, 9, 29),
                   next_day=date(2026, 9, 27), status="stopped", job_id=dead.id)
    bf.error_code = code
    bf.error = "Interrupted"
    db.commit()
    vendor = _Vendor()

    resumed = auto_resume_lost_backfills(db, now=NOW, transport=_Transport(vendor).transport)

    db.refresh(bf)
    assert resumed == 1
    assert vendor.seen == ["20260927", "20260928", "20260929"]  # only the unread days
    assert bf.status == "done"
    [entry] = _history(db, feed.id)
    assert entry.error_code == "AUTO_RESUMED"
    assert entry.outcome == "ABORTED"
    assert entry.kind == "backfill"
    assert "27/09/2026" in entry.error and "1 of 5" in entry.error
    assert entry.day_from == date(2026, 9, 27)


def test_the_full_deploy_path_reaper_then_next_beat_resumes(db, monkeypatch):
    """Kill-proof: the segment's job is gone (worker recreated); the first
    beat reaps the row to JOB_ENDED, the next beat resumes it."""
    _no_dispatch(monkeypatch)
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    killed = _job(db, co.tenant_id, status="running", heartbeat_at=NOW - timedelta(minutes=20))
    bf = _backfill(db, feed, from_day=date(2026, 9, 1), to_day=date(2026, 9, 29),
                   next_day=date(2026, 9, 12), job_id=killed.id)

    first = sweep_doc_feeds(db, now=NOW)
    db.refresh(bf)
    assert first["reapedBackfills"] == 1
    assert bf.status == "stopped"

    second = sweep_doc_feeds(db, now=NOW + timedelta(minutes=1))
    db.refresh(bf)
    assert second["autoResumedBackfills"] == 1
    assert bf.status == "running"
    assert bf.job_id != killed.id
    assert bf.next_day == date(2026, 9, 12)  # continues from the saved day
    assert bf.error is None and bf.error_code is None


# ── stays stopped ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("code", ["TIME_LIMIT", "CRASHED", "SINK_ERROR", "FEED_GONE", "crm_switched_off", None])
def test_other_stops_stay_stopped(db, code, monkeypatch):
    _no_dispatch(monkeypatch)
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2026, 9, 20), to_day=date(2026, 9, 29), status="stopped")
    bf.error_code = code
    db.commit()

    assert auto_resume_lost_backfills(db, now=NOW) == 0
    db.refresh(bf)
    assert bf.status == "stopped" and bf.error_code == code
    assert _history(db, feed.id) == []


def test_a_user_stop_whose_job_then_ends_stays_stopped(db, monkeypatch):
    _no_dispatch(monkeypatch)
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    job = _job(db, co.tenant_id, status="running", heartbeat_at=datetime.now(timezone.utc))
    bf = _backfill(db, feed, from_day=date(2026, 9, 20), to_day=date(2026, 9, 29), job_id=job.id)

    DocFeedService(db).stop_backfill(co.tenant_id, co.id, DO)
    db.refresh(bf)
    assert bf.status == "stopping"
    # The deploy kills the worker before it closes `stopping`.
    job.status = "failed"
    db.commit()
    reap_stale_backfills(db, now=NOW)
    db.refresh(bf)
    assert bf.status == "stopped" and bf.error_code == "USER_STOPPED"

    assert auto_resume_lost_backfills(db, now=NOW) == 0
    db.refresh(bf)
    assert bf.status == "stopped"


def test_a_user_stop_whose_job_is_orphaned_stays_stopped(db, monkeypatch):
    _no_dispatch(monkeypatch)
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    job = _job(db, co.tenant_id, status="running", heartbeat_at=datetime.now(timezone.utc))
    bf = _backfill(db, feed, from_day=date(2026, 9, 20), to_day=date(2026, 9, 29), job_id=job.id)
    DocFeedService(db).stop_backfill(co.tenant_id, co.id, DO)

    on_job_orphaned(db, job, now=NOW)
    db.commit()
    db.refresh(bf)
    assert bf.status == "stopped" and bf.error_code == "USER_STOPPED"
    assert auto_resume_lost_backfills(db, now=NOW) == 0


def test_a_manually_resumed_orphaned_backfill_then_stopped_by_the_user_stays_stopped(db, monkeypatch):
    """The old `ORPHANED` code must not survive Resume + Stop."""
    _no_dispatch(monkeypatch)
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2026, 9, 20), to_day=date(2026, 9, 29), status="stopped")
    bf.error_code = "ORPHANED"
    db.commit()

    DocFeedService(db).resume_backfill(co.tenant_id, co.id, DO)
    db.refresh(bf)
    assert bf.status == "running" and bf.error_code is None
    DocFeedService(db).stop_backfill(co.tenant_id, co.id, DO)  # its job is still queued
    db.refresh(bf)
    assert bf.status == "stopped"

    assert auto_resume_lost_backfills(db, now=NOW) == 0
    db.refresh(bf)
    assert bf.status == "stopped"


def test_a_feed_switched_off_is_not_resumed(db, monkeypatch):
    _no_dispatch(monkeypatch)
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn, mode="off")
    bf = _backfill(db, feed, from_day=date(2026, 9, 20), to_day=date(2026, 9, 29), status="stopped")
    bf.error_code = "ORPHANED"
    db.commit()

    assert auto_resume_lost_backfills(db, now=NOW) == 0
    db.refresh(bf)
    assert bf.status == "stopped" and bf.error_code == "ORPHANED"  # a person can still Resume


def test_a_live_backfill_whose_feed_left_push_is_not_resumed(db, monkeypatch):
    _no_dispatch(monkeypatch)
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn, mode="pull")
    bf = _backfill(db, feed, from_day=date(2026, 9, 20), to_day=date(2026, 9, 29),
                   status="stopped", dry_run=False)
    bf.error_code = "JOB_ENDED"
    db.commit()

    assert auto_resume_lost_backfills(db, now=NOW) == 0
    db.refresh(bf)
    assert bf.status == "stopped" and bf.error_code == "JOB_ENDED"


# ── the cap ─────────────────────────────────────────────────────────────────


def _lose_worker(db, bf, now):
    """The resumed segment's job dies before it saves a day."""
    db.refresh(bf)
    from app.models.background_job import BackgroundJob

    job = db.query(BackgroundJob).filter(BackgroundJob.id == bf.job_id).one()
    job.status = "failed"
    db.commit()
    reap_stale_backfills(db, now=now)
    db.refresh(bf)
    assert bf.status == "stopped" and bf.error_code == "JOB_ENDED"


def test_a_crash_loop_is_resumed_at_most_n_times_in_a_row(db, monkeypatch):
    _no_dispatch(monkeypatch)
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    first = _job(db, co.tenant_id, status="failed")
    bf = _backfill(db, feed, from_day=date(2026, 9, 1), to_day=date(2026, 9, 29),
                   next_day=date(2026, 9, 5), job_id=first.id)
    reap_stale_backfills(db, now=NOW)

    assert BACKFILL_AUTO_RESUME_MAX == 5
    for n in range(BACKFILL_AUTO_RESUME_MAX):
        assert auto_resume_lost_backfills(db, now=NOW + timedelta(minutes=n)) == 1
        _lose_worker(db, bf, NOW + timedelta(minutes=n))

    assert auto_resume_lost_backfills(db, now=NOW + timedelta(hours=1)) == 0
    db.refresh(bf)
    assert bf.status == "stopped"
    assert bf.error_code == "AUTO_RESUME_LIMIT"
    assert "05/09/2026" in bf.error
    entries = _history(db, feed.id)
    assert [e.error_code for e in entries] == ["AUTO_RESUMED"] * 5 + ["AUTO_RESUME_LIMIT"]
    assert "5 of 5" in entries[4].error
    # Idempotent: later beats leave it alone (no more history rows).
    assert auto_resume_lost_backfills(db, now=NOW + timedelta(hours=2)) == 0
    assert len(_history(db, feed.id)) == 6

    # A person's Resume starts a fresh count.
    DocFeedService(db).resume_backfill(co.tenant_id, co.id, DO)
    _lose_worker(db, bf, NOW + timedelta(hours=3))
    assert auto_resume_lost_backfills(db, now=NOW + timedelta(hours=3)) == 1
    assert "1 of 5" in _history(db, feed.id)[-1].error


def test_a_saved_day_between_losses_restarts_the_count(db, monkeypatch):
    """Daily deploys across a long backfill: each resume that saves at
    least one day before the next loss never runs into the cap."""
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2026, 9, 1), to_day=date(2026, 9, 29),
                   next_day=date(2026, 9, 5), status="stopped")
    bf.error_code = "ORPHANED"
    bf.summary_json = {"autoResume": {"count": BACKFILL_AUTO_RESUME_MAX - 1}}
    db.commit()

    vendor = _Vendor()
    assert auto_resume_lost_backfills(db, now=NOW, transport=_Transport(vendor).transport) == 1
    db.refresh(bf)
    assert bf.status == "done"
    assert "autoResume" not in (bf.summary_json or {})


def test_two_overlapping_beats_claim_the_row_once(db):
    """The claim is a guarded UPDATE on the code the pass judged: a second
    beat that judged the same stale row gets nothing."""
    from modules.autocount.repositories.doc_feed_repository import DocFeedBackfillRepository

    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2026, 9, 1), to_day=date(2026, 9, 29), status="stopped")
    bf.error_code = "ORPHANED"
    db.commit()
    repo = DocFeedBackfillRepository(db)

    assert repo.claim_for_auto_resume(co.tenant_id, bf.id, "ORPHANED") is True
    assert repo.claim_for_auto_resume(co.tenant_id, bf.id, "ORPHANED") is False
