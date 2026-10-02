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


# ── round 2 - a FAILED run keeps the counters of the work it really did ─────


def test_finish_failed_with_an_explicit_summary_persists_it(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    run = _new_run(db, feed, kind="poll", dry_run=False, now=NOW)

    _finish_failed(db, run, "X", "boom", summary={"created": 7})

    assert _reload(db, run.id).summary_json == {"created": 7}


def test_a_poll_that_fails_on_a_later_chunk_keeps_the_committed_chunk_counters(session_factory, monkeypatch):
    """Chunk mechanism: the poll sink chunks by
    `settings.autocount_sink_batch_size` (one POST per that many records;
    `SORENTO_MAX_BATCH` is only the ceiling), so the vendor returns
    chunk + 1 records = 2 chunks. The sink answers the
    first records POST with a created verdict per record and every later
    POST with 400."""
    import json

    from app.config import settings

    monkeypatch.setattr("time.sleep", lambda *_: None)
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    chunk = settings.autocount_sink_batch_size
    total = chunk + 1

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"DocKey": k, "DocNo": f"DO-{k}", "DocDate": "2026-09-29",
                 "LastModified": "2026-09-29T09:00:00.000", "Details": []}
                for k in range(1, total + 1)
            ],
        )

    posts = {"n": 0}

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        posts["n"] += 1
        if posts["n"] > 1:
            return httpx.Response(400, text="denied")
        recs = json.loads(request.content.decode("utf-8")).get("records") or []
        return httpx.Response(
            200,
            json={
                "dry_run": False, "summary": {"total": len(recs), "created": len(recs)},
                "records": [
                    {"source_ref": r.get("source_ref") or f"db1:DO:{r.get('DocKey')}", "outcome": "created", "entity_id": "x"}
                    for r in recs
                ],
            },
        )

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=httpx.MockTransport(sink),
    )
    db.expire_all()
    run = (
        db.query(AcDocFeedRun).filter(AcDocFeedRun.feed_id == feed.id)
        .order_by(AcDocFeedRun.started_at.desc()).first()
    )
    assert run.outcome == "FAILED" and run.error_code == "SINK_ERROR"
    assert run.summary_json["created"] == chunk


def _sweep_helpers():
    from . import test_s14_doc_feed_sweep as sw

    return sw


def test_a_delete_guard_tripped_sweep_records_the_candidate_count(session_factory):
    from modules.autocount.doc_feed.runner import run_sweep

    sw = _sweep_helpers()
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = sw._feed(db, co, ac_conn)
    for key in range(1, 101):
        sw._ledger(db, feed, key, doc_date=sw.WINDOW_FROM)
    db.commit()

    run_sweep(
        db, feed, dry_run=False, now=sw.NOW,
        vendor_transport=sw._vendor_by_day({sw.WINDOW_FROM.strftime("%Y%m%d"): list(range(1, 50))}),
        sink_transport=httpx.MockTransport(sw._contract_first(lambda r: httpx.Response(200, json={}))),
    )
    run = sw._latest_run(db, feed)
    assert run.error_code == "DELETE_GUARD"
    assert run.summary_json["candidates"] == 51


def test_a_sweep_that_fails_at_the_sink_records_its_candidate_count(session_factory):
    """Setup mirrors the SS1 sweep SINK_ERROR test: one ledger row, no vendor
    keys, so exactly 1 candidate reaches the (400) sink."""
    from modules.autocount.doc_feed.runner import run_sweep

    sw = _sweep_helpers()
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = sw._feed(db, co, ac_conn)
    sw._ledger(db, feed, 333, doc_date=sw.WINDOW_FROM)
    db.commit()

    run_sweep(
        db, feed, dry_run=False, now=sw.NOW,
        vendor_transport=sw._vendor_by_day({}),
        sink_transport=httpx.MockTransport(sw._contract_first(lambda r: httpx.Response(400, text="denied"))),
    )
    run = sw._latest_run(db, feed)
    assert run.outcome == "FAILED" and run.error_code == "SINK_ERROR"
    assert run.summary_json["candidates"] == 1
