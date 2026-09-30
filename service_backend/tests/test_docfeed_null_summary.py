"""crew DOCFEED-NULL-SUMMARY - a doc-feed run row never carries a null summary.

Production bug (30 Sep 2026): the Document feeds tab crashed on a run whose
`summary_json` was NULL (an in-flight run, a failed run, a refused backfill
segment, an orphan-closed run). Every run row must persist a summary dict.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx

from app.models.background_job import BackgroundJob
from modules.autocount.doc_feed.runner import (
    _finish_failed,
    _new_run,
    _new_run_for_backfill,
    run_backfill,
    run_poll,
)
from modules.autocount.models import AcDocFeed, AcDocFeedBackfill, AcDocFeedRun

from .s14_doc_feed_helpers import wired_company

NOW = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)


def _feed(db, company, ac_conn) -> AcDocFeed:
    row = AcDocFeed(
        tenant_id=company.tenant_id, company_id=company.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="push", cursor_day=date(2026, 9, 29),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _reload(db, run_id: str) -> AcDocFeedRun:
    db.expire_all()
    return db.query(AcDocFeedRun).filter(AcDocFeedRun.id == run_id).one()


def test_a_new_run_row_carries_a_summary_dict_at_creation(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)

    run = _new_run(db, feed, kind="poll", dry_run=True, now=NOW)

    assert isinstance(_reload(db, run.id).summary_json, dict)


def test_a_failed_poll_run_carries_a_summary_dict(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    db.expire_all()
    run = (
        db.query(AcDocFeedRun).filter(AcDocFeedRun.feed_id == feed.id)
        .order_by(AcDocFeedRun.started_at.desc()).first()
    )
    assert run.outcome == "FAILED"  # control: the failure path really ran
    assert isinstance(run.summary_json, dict)


def test_finish_failed_keeps_an_existing_summary(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    run = _new_run(db, feed, kind="poll", dry_run=False, now=NOW)
    run.summary_json = {"created": 5}
    db.commit()

    _finish_failed(db, run, "X", "boom")

    reloaded = _reload(db, run.id)
    assert reloaded.outcome == "FAILED"
    assert reloaded.summary_json == {"created": 5}


def test_a_refused_backfill_segment_run_carries_a_summary_dict(session_factory):
    """Route taken: the REAL resolve-time refusal. The feed's company is made
    inactive so `_resolve` raises `RunRefusal("COMPANY_INACTIVE")`, and
    `run_backfill` records the FAILED segment run via `_new_run_for_backfill(
    summary=None)`."""
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    co.is_active = False
    db.commit()
    bf = AcDocFeedBackfill(
        tenant_id=feed.tenant_id, company_id=feed.company_id, feed_id=feed.id, feed=feed.feed,
        book="db1", dry_run=False, from_day=date(2026, 9, 1), to_day=date(2026, 9, 3),
        next_day=date(2026, 9, 1), status="running", days_total=3, days_done=0,
        started_by="actor-1", started_at=NOW,
    )
    db.add(bf)
    db.commit()

    run_backfill(
        db, bf, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))),
        sink_transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )

    db.expire_all()
    runs = db.query(AcDocFeedRun).filter(AcDocFeedRun.feed_id == feed.id).all()
    assert len(runs) == 1 and runs[0].outcome == "FAILED" and runs[0].error_code == "COMPANY_INACTIVE"
    assert isinstance(runs[0].summary_json, dict)


def test_new_run_for_backfill_without_a_summary_persists_a_dict(session_factory):
    """Direct route: `summary` omitted (the refused path's shape)."""
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    bf = AcDocFeedBackfill(
        tenant_id=feed.tenant_id, company_id=feed.company_id, feed_id=feed.id, feed=feed.feed,
        book="db1", dry_run=False, from_day=date(2026, 9, 1), to_day=date(2026, 9, 3),
        next_day=date(2026, 9, 1), status="running", days_total=3, days_done=0,
        started_by="actor-1", started_at=NOW,
    )
    db.add(bf)
    db.commit()

    run = _new_run_for_backfill(
        db, bf, feed, NOW, outcome="FAILED", error="x", error_code="X",
        requests=0, fetched_count=0,
    )

    assert isinstance(_reload(db, run.id).summary_json, dict)


def test_orphan_hook_fills_a_missing_summary_on_the_run_it_closes(session_factory):
    """The run is hand-built with `summary_json=None` (not via `_new_run`) so
    the hook is exercised on its own even once `_new_run` is fixed."""
    from modules.autocount.bootstrap import on_job_orphaned

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    job = BackgroundJob(
        tenant_id=co.tenant_id, type="autocount_doc_feed_run", status="running",
        payload_json={"feedId": feed.id, "kind": "poll"},
    )
    db.add(job)
    db.commit()
    run = AcDocFeedRun(
        tenant_id=co.tenant_id, company_id=co.id, feed_id=feed.id, feed=feed.feed,
        kind="poll", dry_run=False, job_id=job.id, started_at=NOW, summary_json=None,
    )
    db.add(run)
    db.commit()

    on_job_orphaned(db, job, now=NOW + timedelta(minutes=5))
    db.commit()

    reloaded = _reload(db, run.id)
    assert reloaded.outcome == "FAILED"  # control: the hook closed it
    assert isinstance(reloaded.summary_json, dict)
