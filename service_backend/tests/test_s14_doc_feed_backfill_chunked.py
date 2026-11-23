"""SS-BACKFILL-CHUNKED - a doc-feed backfill survives the job time limit.

Prod 23 Nov: a 7632-day registrations dry run ran as ONE ``jobs.run`` job
under a 7200 s soft limit (~1.8 s/day, so it could never finish). The limit
fired outside the per-day ``try`` and left the row ``running`` with no
worker: Stop only set ``stopping`` forever, Resume needs ``stopped``.

AC ids (plan ``documentation/plans/sprint-5/ss-backfill-chunked.md``):
- AC-BFC-1 chained segments under a time budget, one logical backfill.
- AC-BFC-2 time limit / crash anywhere ends the row ``stopped`` + resumable.
- AC-BFC-3 stale-row reaper (job ended, or no heartbeat > 15 min).
- AC-BFC-4 a set of finished dry runs that together cover the live range.

A fake monotonic clock (``runner._segment_clock``) stands in for wall time,
so no test sleeps.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List

import httpx
import pytest
from celery.exceptions import SoftTimeLimitExceeded

from app.config import settings
from app.models.background_job import BackgroundJob
from modules.autocount.doc_feed import runner
from modules.autocount.doc_feed.runner import run_backfill
from modules.autocount.models import AcDocFeed, AcDocFeedBackfill, AcDocFeedRun
from modules.autocount.services.doc_feed_service import DocFeedConflictError, DocFeedService

from .s14_doc_feed_helpers import wired_company

NOW = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)
DO = "delivery_orders"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


def _feed(db, company, ac_conn, *, mode="push") -> AcDocFeed:
    row = AcDocFeed(
        tenant_id=company.tenant_id, company_id=company.id, feed=DO,
        connection_id=ac_conn.id, book="db1", mode=mode, cursor_day=date(2026, 9, 29),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _backfill(db, feed, *, from_day, to_day, status="running", dry_run=True, job_id=None,
              next_day=None) -> AcDocFeedBackfill:
    row = AcDocFeedBackfill(
        tenant_id=feed.tenant_id, company_id=feed.company_id, feed_id=feed.id, feed=feed.feed,
        book=feed.book, dry_run=dry_run, from_day=from_day, to_day=to_day,
        next_day=next_day or from_day, status=status,
        days_total=(to_day - from_day).days + 1, days_done=0, started_at=NOW, job_id=job_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _job(db, tenant_id, *, status="running", heartbeat_at=None, started_at=None) -> BackgroundJob:
    job = BackgroundJob(
        tenant_id=tenant_id, type="autocount_doc_feed_backfill", status=status,
        heartbeat_at=heartbeat_at, started_at=started_at,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _sink() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": [DO, "branches"]})
        return httpx.Response(200, json={"dry_run": True, "summary": {}, "records": []})

    return httpx.MockTransport(handler)


class _Vendor:
    """Empty days, recording each day read; ``on_day`` may raise."""

    def __init__(self, on_day=None):
        self.seen: List[str] = []
        self.on_day = on_day

    def client(self) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            day = request.url.params.get("DocDate")
            self.seen.append(day)
            if self.on_day is not None:
                self.on_day(day)
            return httpx.Response(200, json=[])

        return httpx.Client(transport=httpx.MockTransport(handler))


class _Transport:
    """The single route-level override ``_split_transport`` accepts: a raw
    transport serving BOTH the vendor reads and the CRM probe/ingest."""

    def __init__(self, vendor: _Vendor):
        self.vendor = vendor
        sink = _sink()
        vclient = vendor.client()

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.startswith("/api/v1/external"):
                return sink.handle_request(request)
            return vclient._transport.handle_request(request)  # noqa: SLF001

        self.transport = httpx.MockTransport(handler)


@pytest.fixture
def fake_clock(monkeypatch):
    """Each read of the segment clock advances 100 s."""
    state = {"t": 0.0}

    def tick() -> float:
        state["t"] += 100.0
        return state["t"]

    monkeypatch.setattr(runner, "_segment_clock", tick)
    return state


# ── AC-BFC-1 chained segments ───────────────────────────────────────────────


def test_bfc1_a_segment_stops_at_its_time_budget_and_leaves_the_backfill_running(db, fake_clock, monkeypatch):
    monkeypatch.setattr(settings, "autocount_doc_feed_backfill_segment_seconds", 250)
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2026, 9, 20), to_day=date(2026, 9, 29))
    vendor = _Vendor()

    run_backfill(db, bf, now=NOW, vendor_transport=vendor.client(), sink_transport=_sink())

    db.refresh(bf)
    # Clock: start 100, after day 1 200, day 2 300, day 3 400 -> 300 s >= 250.
    assert vendor.seen == ["20260920", "20260921", "20260922"]
    assert bf.status == "running"
    assert bf.next_day == date(2026, 9, 23)
    assert bf.days_done == 3
    run = db.query(AcDocFeedRun).filter_by(feed_id=feed.id).one()
    assert run.outcome == "SUCCESS"
    assert (run.day_from, run.day_to) == (date(2026, 9, 20), date(2026, 9, 22))


def test_bfc1_the_whole_backfill_finishes_across_chained_jobs_reading_each_day_once(db, fake_clock, monkeypatch):
    monkeypatch.setattr(settings, "autocount_doc_feed_backfill_segment_seconds", 250)
    co, ac_conn, _ = wired_company(db)
    _feed(db, co, ac_conn)
    vendor = _Vendor()
    route = _Transport(vendor)

    bf = DocFeedService(db).start_backfill(
        co.tenant_id, co.id, DO, dry_run=True,
        from_day=date(2026, 9, 20), to_day=date(2026, 9, 29), transport=route.transport,
    )

    db.refresh(bf)
    expected = [(date(2026, 9, 20) + timedelta(days=i)).strftime("%Y%m%d") for i in range(10)]
    assert vendor.seen == expected  # in order, never a day twice
    assert bf.status == "done"
    assert bf.days_done == 10 and bf.next_day == date(2026, 9, 30)
    jobs = db.query(BackgroundJob).filter_by(type="autocount_doc_feed_backfill").all()
    assert len(jobs) == 4  # 3 + 3 + 3 + 1 days
    assert {j.status for j in jobs} == {"done"}
    assert bf.job_id in {j.id for j in jobs}
    runs = db.query(AcDocFeedRun).filter_by(feed_id=bf.feed_id).order_by(AcDocFeedRun.day_from).all()
    assert [(r.day_from, r.day_to) for r in runs] == [
        (date(2026, 9, 20), date(2026, 9, 22)), (date(2026, 9, 23), date(2026, 9, 25)),
        (date(2026, 9, 26), date(2026, 9, 28)), (date(2026, 9, 29), date(2026, 9, 29)),
    ]


def test_bfc1_stop_between_segments_closes_the_row_stopped(db, fake_clock, monkeypatch):
    monkeypatch.setattr(settings, "autocount_doc_feed_backfill_segment_seconds", 250)
    co, ac_conn, _ = wired_company(db)
    _feed(db, co, ac_conn)

    def stop_after_first_segment(day):
        if day == "20260922":
            other = db.get_bind()
            with other.begin() as conn:
                conn.execute(
                    AcDocFeedBackfill.__table__.update().values(status="stopping")
                )

    vendor = _Vendor(on_day=stop_after_first_segment)
    bf = DocFeedService(db).start_backfill(
        co.tenant_id, co.id, DO, dry_run=True,
        from_day=date(2026, 9, 20), to_day=date(2026, 9, 29),
        transport=_Transport(vendor).transport,
    )
    db.refresh(bf)
    assert bf.status == "stopped"
    assert "20260923" not in vendor.seen


def test_bfc1_a_job_that_is_no_longer_the_backfills_job_does_nothing(db):
    """Kill-proof fence: a stale queued segment (the backfill was reaped and
    resumed under a NEWER job) must never read a day."""
    from modules.autocount.doc_feed.jobs import run_doc_feed_backfill_job

    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    current = _job(db, co.tenant_id)
    stale = _job(db, co.tenant_id)
    bf = _backfill(db, feed, from_day=date(2026, 9, 28), to_day=date(2026, 9, 29), job_id=current.id)
    stale.payload_json = {"backfillId": bf.id}
    db.commit()
    vendor = _Vendor()

    run_doc_feed_backfill_job(db, stale, transport=_Transport(vendor).transport)

    assert vendor.seen == []
    db.refresh(bf)
    db.refresh(stale)
    assert bf.status == "running" and bf.job_id == current.id
    assert stale.status == "done"


# ── AC-BFC-2 time limit / crash anywhere ends the row stopped ───────────────


def _start(db, co, vendor):
    return DocFeedService(db).start_backfill(
        co.tenant_id, co.id, DO, dry_run=True,
        from_day=date(2026, 9, 27), to_day=date(2026, 9, 29),
        transport=_Transport(vendor).transport,
    )


def _raise_on(day_to_fail, exc):
    def on_day(day):
        if day == day_to_fail:
            raise exc

    return on_day


def test_bfc2_the_soft_time_limit_during_the_vendor_call_ends_the_row_stopped_and_resumable(db):
    co, ac_conn, _ = wired_company(db)
    _feed(db, co, ac_conn)
    bf = _start(db, co, _Vendor(on_day=_raise_on("20260928", SoftTimeLimitExceeded())))

    db.refresh(bf)
    assert bf.status == "stopped"
    assert bf.error_code == "TIME_LIMIT"
    assert bf.error
    assert bf.next_day == date(2026, 9, 28)  # day 1 kept, day 2 re-read on resume
    job = db.get(BackgroundJob, bf.job_id)
    assert job.status == "failed"

    vendor = _Vendor()
    resumed = DocFeedService(db).resume_backfill(
        co.tenant_id, co.id, DO, transport=_Transport(vendor).transport,
    )
    db.refresh(resumed)
    assert resumed.status == "done"
    assert vendor.seen == ["20260928", "20260929"]


def test_bfc2_the_soft_time_limit_during_the_sink_write_is_a_time_limit_not_a_sink_error(db, monkeypatch):
    from modules.autocount.sinks_sorento import SorentoSink

    def boom(self, *a, **k):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(SorentoSink, "write_batch", boom)
    co, ac_conn, _ = wired_company(db)
    _feed(db, co, ac_conn)
    bf = _start(db, co, _Vendor())
    db.refresh(bf)
    assert bf.status == "stopped"
    assert bf.error_code == "TIME_LIMIT"


def test_bfc2_the_soft_time_limit_during_the_day_pause_ends_the_row_stopped(db, monkeypatch, fake_clock):
    co, ac_conn, _ = wired_company(db)
    _feed(db, co, ac_conn)
    calls = {"n": 0}

    def pause_then_limit(seconds):
        calls["n"] += 1
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(runner, "_day_pause", pause_then_limit)
    monkeypatch.setattr(runner, "PROJNO_FEEDS", frozenset({DO}))
    bf = _start(db, co, _Vendor())
    db.refresh(bf)
    assert calls["n"] == 1
    assert bf.status == "stopped" and bf.error_code == "TIME_LIMIT"
    assert bf.next_day == date(2026, 9, 28)


def test_bfc2_a_crash_anywhere_in_the_loop_ends_the_row_stopped(db):
    co, ac_conn, _ = wired_company(db)
    _feed(db, co, ac_conn)
    bf = _start(db, co, _Vendor(on_day=_raise_on("20260927", RuntimeError("boom"))))
    db.refresh(bf)
    assert bf.status == "stopped"
    assert bf.error_code == "CRASHED"
    assert bf.error


def test_bfc2_a_stopping_row_hit_by_the_limit_still_ends_stopped(db):
    co, ac_conn, _ = wired_company(db)
    _feed(db, co, ac_conn)

    def stop_then_limit(day):
        if day == "20260928":
            with db.get_bind().begin() as conn:
                conn.execute(AcDocFeedBackfill.__table__.update().values(status="stopping"))
            raise SoftTimeLimitExceeded()

    bf = _start(db, co, _Vendor(on_day=stop_then_limit))
    db.refresh(bf)
    assert bf.status == "stopped"


# ── AC-BFC-3 stale-row reaper ───────────────────────────────────────────────


def test_bfc3_reaper_stops_rows_whose_job_has_ended_or_gone_quiet(db):
    from modules.autocount.doc_feed.scheduler import reap_stale_backfills

    from types import SimpleNamespace

    co, ac_conn, _ = wired_company(db)
    # The reaper reads only the backfill + job rows; one fake feed id per
    # case keeps the one-open-backfill-per-feed index happy.
    def feed_of(n):
        return SimpleNamespace(tenant_id=co.tenant_id, company_id=co.id, id=f"feed-{n}",
                               feed=DO, book="db1")

    failed_job = _job(db, co.tenant_id, status="failed")
    stale_job = _job(db, co.tenant_id, status="running", heartbeat_at=NOW - timedelta(minutes=20))
    fresh_job = _job(db, co.tenant_id, status="running", heartbeat_at=NOW - timedelta(minutes=2))
    pending_job = _job(db, co.tenant_id, status="pending")

    dead = _backfill(db, feed_of(1), from_day=date(2026, 9, 1), to_day=date(2026, 9, 29), job_id=failed_job.id)
    quiet = _backfill(db, feed_of(2), from_day=date(2026, 9, 1),
                      to_day=date(2026, 9, 29), job_id=stale_job.id, status="stopping")
    live = _backfill(db, feed_of(3), from_day=date(2026, 9, 1),
                     to_day=date(2026, 9, 29), job_id=fresh_job.id)
    queued = _backfill(db, feed_of(4), from_day=date(2026, 9, 1),
                       to_day=date(2026, 9, 29), job_id=pending_job.id)
    no_job = _backfill(db, feed_of(5), from_day=date(2026, 9, 1),
                       to_day=date(2026, 9, 29), job_id=None)

    reaped = reap_stale_backfills(db, now=NOW)

    for row in (dead, quiet, live, queued, no_job):
        db.refresh(row)
    assert reaped == 3
    assert dead.status == "stopped" and dead.error_code == "JOB_ENDED" and dead.error
    assert quiet.status == "stopped"
    assert no_job.status == "stopped"
    assert live.status == "running"
    assert queued.status == "running"
    db.refresh(stale_job)
    assert stale_job.status == "failed"  # Resume's job_is_live check now passes


def test_bfc3_the_doc_feed_beat_runs_the_reaper(db):
    from modules.autocount.doc_feed.scheduler import sweep_doc_feeds

    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    job = _job(db, co.tenant_id, status="failed")
    bf = _backfill(db, feed, from_day=date(2026, 9, 1), to_day=date(2026, 9, 29), job_id=job.id)
    out = sweep_doc_feeds(db, now=NOW)
    db.refresh(bf)
    assert out["reapedBackfills"] == 1
    assert bf.status == "stopped"


def test_bfc3_stop_on_a_row_whose_job_is_gone_stops_it_at_once_and_resume_works(db):
    """The prod symptom: the row says running, its job is FAILED - Stop must
    not leave it `stopping` forever."""
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    job = _job(db, co.tenant_id, status="failed")
    bf = _backfill(db, feed, from_day=date(2026, 9, 28), to_day=date(2026, 9, 29), job_id=job.id)

    stopped = DocFeedService(db).stop_backfill(co.tenant_id, co.id, DO)
    assert stopped.status == "stopped"

    vendor = _Vendor()
    resumed = DocFeedService(db).resume_backfill(
        co.tenant_id, co.id, DO, transport=_Transport(vendor).transport,
    )
    db.refresh(resumed)
    assert resumed.status == "done"
    assert vendor.seen == ["20260928", "20260929"]


def test_bfc3_resume_and_discard_reap_a_stuck_stopping_row_first(db):
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    job = _job(db, co.tenant_id, status="failed")
    bf = _backfill(db, feed, from_day=date(2026, 9, 28), to_day=date(2026, 9, 29),
                   job_id=job.id, status="stopping")
    discarded = DocFeedService(db).discard_backfill(co.tenant_id, co.id, DO)
    assert discarded.id == bf.id
    assert discarded.status == "done" and discarded.error_code == "DISCARDED"


# ── AC-BFC-4 dry runs that together cover the live range ────────────────────

PR = "project_registrations"


def _pr_feed(db, co, ac_conn):
    row = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed=PR, connection_id=ac_conn.id,
        book="db3", mode="push",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _done_dry(db, feed, from_day, to_day, *, error_code=None):
    row = _backfill(db, feed, from_day=from_day, to_day=to_day, status="done", dry_run=True)
    row.error_code = error_code
    db.commit()
    return row


def _live_start(db, co, from_day, to_day, monkeypatch):
    service = DocFeedService(db)
    monkeypatch.setattr(service, "_dispatch", lambda *a, **k: None)
    return service.start_backfill(co.tenant_id, co.id, PR, dry_run=False,
                                  from_day=from_day, to_day=to_day)


def test_bfc4_two_dry_run_pieces_that_together_cover_the_range_satisfy_the_gate(db, monkeypatch):
    from .test_autocount_project_registrations_feed import _wired

    co, ac_conn = _wired(db)
    feed = _pr_feed(db, co, ac_conn)
    _done_dry(db, feed, date(2006, 1, 1), date(2006, 6, 30))
    _done_dry(db, feed, date(2006, 7, 1), date(2006, 12, 31))
    bf = _live_start(db, co, date(2006, 1, 1), date(2006, 12, 31), monkeypatch)
    assert bf.status == "running" and not bf.dry_run


def test_bfc4_overlapping_pieces_also_cover(db, monkeypatch):
    from .test_autocount_project_registrations_feed import _wired

    co, ac_conn = _wired(db)
    feed = _pr_feed(db, co, ac_conn)
    _done_dry(db, feed, date(2006, 1, 1), date(2006, 8, 31))
    _done_dry(db, feed, date(2006, 3, 1), date(2007, 1, 31))
    bf = _live_start(db, co, date(2006, 2, 1), date(2006, 12, 31), monkeypatch)
    assert bf.status == "running"


@pytest.mark.parametrize("second", [
    (date(2006, 7, 2), date(2006, 12, 31), None),          # one-day gap on 1 Jul
    (date(2006, 7, 1), date(2006, 12, 30), None),          # last day missing
    (date(2006, 7, 1), date(2006, 12, 31), "DISCARDED"),   # a discarded piece never counts
])
def test_bfc4_a_gap_or_a_discarded_piece_is_still_refused(db, monkeypatch, second):
    from .test_autocount_project_registrations_feed import _wired

    co, ac_conn = _wired(db)
    feed = _pr_feed(db, co, ac_conn)
    _done_dry(db, feed, date(2006, 1, 1), date(2006, 6, 30))
    _done_dry(db, feed, second[0], second[1], error_code=second[2])
    with pytest.raises(DocFeedConflictError) as exc:
        _live_start(db, co, date(2006, 1, 1), date(2006, 12, 31), monkeypatch)
    assert exc.value.code == "DRY_RUN_FIRST"


def test_bfc3_kill_proof_a_hard_killed_segment_is_reaped_and_resume_reads_only_the_unread_days(db):
    """A hard time limit / SIGKILL raises nothing: the job row stays RUNNING
    and the backfill `running` after day 2 of 4 committed. The beat reaper
    must stop it once the heartbeat is 15 minutes old, and Resume must read
    only days 3-4 (never a committed day again)."""
    from modules.autocount.doc_feed.scheduler import sweep_doc_feeds

    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    killed = _job(db, co.tenant_id, status="running", started_at=NOW - timedelta(hours=2),
                  heartbeat_at=NOW - timedelta(minutes=16))
    bf = _backfill(db, feed, from_day=date(2026, 9, 26), to_day=date(2026, 9, 29),
                   next_day=date(2026, 9, 28), job_id=killed.id)
    bf.days_done = 2
    db.commit()

    # Not yet stale at 14 minutes: the reaper leaves a possibly-alive job alone.
    assert sweep_doc_feeds(db, now=NOW - timedelta(minutes=2))["reapedBackfills"] == 0
    db.refresh(bf)
    assert bf.status == "running"

    assert sweep_doc_feeds(db, now=NOW)["reapedBackfills"] == 1
    db.refresh(bf)
    db.refresh(killed)
    assert bf.status == "stopped" and bf.error
    assert killed.status == "failed"

    vendor = _Vendor()
    resumed = DocFeedService(db).resume_backfill(
        co.tenant_id, co.id, DO, transport=_Transport(vendor).transport,
    )
    db.refresh(resumed)
    assert vendor.seen == ["20260928", "20260929"]
    assert resumed.status == "done" and resumed.days_done == 4


# ── review round 1 ──────────────────────────────────────────────────────────


def test_r1_the_reaper_never_stops_a_chain_that_moved_to_its_next_segment(db, monkeypatch):
    """The pass loads rows up front; segment A then hands over to B and
    finishes. The reaper must judge the FRESH row (job B, pending), not A."""
    from modules.autocount.doc_feed import scheduler
    from modules.autocount.repositories.doc_feed_repository import DocFeedBackfillRepository

    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    seg_a = _job(db, co.tenant_id, status="running", heartbeat_at=NOW)
    bf = _backfill(db, feed, from_day=date(2026, 9, 1), to_day=date(2026, 9, 29), job_id=seg_a.id)

    real_in_flight = DocFeedBackfillRepository.in_flight

    def in_flight_then_hand_over(self, **kw):
        rows = real_in_flight(self, **kw)
        seg_b = _job(db, co.tenant_id, status="pending")
        with db.get_bind().begin() as conn:
            conn.execute(AcDocFeedBackfill.__table__.update().values(job_id=seg_b.id))
            conn.execute(BackgroundJob.__table__.update()
                         .where(BackgroundJob.__table__.c.id == seg_a.id).values(status="done"))
        return rows

    monkeypatch.setattr(DocFeedBackfillRepository, "in_flight", in_flight_then_hand_over)
    assert scheduler.reap_stale_backfills(db, now=NOW) == 0
    db.refresh(bf)
    assert bf.status == "running"


def test_r1_the_guarded_stop_refuses_when_the_job_id_changed(db):
    from modules.autocount.repositories.doc_feed_repository import DocFeedBackfillRepository

    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2026, 9, 1), to_day=date(2026, 9, 29), job_id="job-new")
    repo = DocFeedBackfillRepository(db)
    assert not repo.stop_if_job_unchanged(co.tenant_id, bf.id, "job-old", error="x", error_code="JOB_ENDED")
    assert repo.stop_if_job_unchanged(co.tenant_id, bf.id, "job-new", error="x", error_code="JOB_ENDED")
    db.commit()
    db.refresh(bf)
    assert bf.status == "stopped"


def test_r1_start_creates_the_row_running_with_its_job_in_one_step(db, monkeypatch):
    co, ac_conn, _ = wired_company(db)
    _feed(db, co, ac_conn)
    service = DocFeedService(db)
    monkeypatch.setattr(service, "_dispatch", lambda *a, **k: None)
    bf = service.start_backfill(co.tenant_id, co.id, DO, dry_run=True,
                                from_day=date(2026, 9, 1), to_day=date(2026, 9, 29))
    assert bf.job_id
    job = db.get(BackgroundJob, bf.job_id)
    assert job.status == "pending" and job.payload_json == {"backfillId": bf.id}
    # The beat right after Start (job still queued) leaves it running.
    from modules.autocount.doc_feed.scheduler import reap_stale_backfills
    assert reap_stale_backfills(db, now=NOW) == 0


def test_r1_an_old_segment_orphaned_late_never_stops_a_newer_live_segment(db):
    from modules.autocount.bootstrap import on_job_orphaned

    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    old = _job(db, co.tenant_id, status="failed")
    new = _job(db, co.tenant_id, status="running", heartbeat_at=NOW)
    bf = _backfill(db, feed, from_day=date(2026, 9, 1), to_day=date(2026, 9, 29), job_id=new.id)
    old.payload_json = {"backfillId": bf.id}
    db.commit()
    on_job_orphaned(db, old, now=NOW)
    db.commit()
    db.refresh(bf)
    assert bf.status == "running"
    # ... while the job the row points at still stops it.
    new.payload_json = {"backfillId": bf.id}
    on_job_orphaned(db, new, now=NOW)
    db.commit()
    db.refresh(bf)
    assert bf.status == "stopped"


def test_r1_stop_while_the_next_segment_is_still_queued_stops_at_once(db):
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    queued = _job(db, co.tenant_id, status="pending")
    bf = _backfill(db, feed, from_day=date(2026, 9, 28), to_day=date(2026, 9, 29), job_id=queued.id)

    stopped = DocFeedService(db).stop_backfill(co.tenant_id, co.id, DO)
    assert stopped.status == "stopped"
    db.refresh(queued)
    assert queued.status == "aborted"

    vendor = _Vendor()
    resumed = DocFeedService(db).resume_backfill(co.tenant_id, co.id, DO,
                                                 transport=_Transport(vendor).transport)
    db.refresh(resumed)
    assert resumed.status == "done" and vendor.seen == ["20260928", "20260929"]


def test_r1_stop_while_a_segment_is_reading_asks_it_to_stop(db):
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    reading = _job(db, co.tenant_id, status="running", heartbeat_at=datetime.now(timezone.utc))
    _backfill(db, feed, from_day=date(2026, 9, 28), to_day=date(2026, 9, 29), job_id=reading.id)
    assert DocFeedService(db).stop_backfill(co.tenant_id, co.id, DO).status == "stopping"


def test_r1_resume_reaps_a_stuck_stopping_row_first(db):
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    job = _job(db, co.tenant_id, status="failed")
    _backfill(db, feed, from_day=date(2026, 9, 28), to_day=date(2026, 9, 29),
              job_id=job.id, status="stopping")
    vendor = _Vendor()
    resumed = DocFeedService(db).resume_backfill(co.tenant_id, co.id, DO,
                                                 transport=_Transport(vendor).transport)
    db.refresh(resumed)
    assert resumed.status == "done" and vendor.seen == ["20260928", "20260929"]


def test_r1_resume_aborts_a_stopped_rows_never_started_old_segment(db):
    co, ac_conn, _ = wired_company(db)
    feed = _feed(db, co, ac_conn)
    stale = _job(db, co.tenant_id, status="pending")
    _backfill(db, feed, from_day=date(2026, 9, 28), to_day=date(2026, 9, 29),
              job_id=stale.id, status="stopped")
    vendor = _Vendor()
    resumed = DocFeedService(db).resume_backfill(co.tenant_id, co.id, DO,
                                                 transport=_Transport(vendor).transport)
    db.refresh(resumed)
    db.refresh(stale)
    assert stale.status == "aborted"
    assert resumed.status == "done"
