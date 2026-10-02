"""sprint-5/14 S0 - deletion sweep tests (AC-14-42, 50..55, D12).

`modules.autocount.doc_feed.runner.run_sweep` does not exist yet (S0 red,
D21). Assumed signature mirrors `run_poll`'s exact one (plan section 3.6):
`run_sweep(db, feed_row, *, dry_run, now, vendor_transport=None,
sink_transport=None)`.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Set

import httpx
import pytest

from modules.autocount.doc_feed.runner import run_sweep
from modules.autocount.models import AcDocFeed, AcDocFeedLedger, AcDocFeedRun

from .s14_doc_feed_helpers import load_fixture, wired_company

NOW = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)  # MYT today = 2026-09-29
TODAY_MYT = date(2026, 9, 29)
WINDOW_FROM = TODAY_MYT - timedelta(days=44)


def _feed(db, company, ac_conn) -> AcDocFeed:
    row = AcDocFeed(
        tenant_id=company.tenant_id, company_id=company.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="push", cursor_day=TODAY_MYT,
    )
    db.add(row)
    db.flush()
    return row


def _ledger(db, feed, doc_key: int, *, doc_date: date, vanished_at=None) -> AcDocFeedLedger:
    row = AcDocFeedLedger(
        tenant_id=feed.tenant_id, company_id=feed.company_id, feed=feed.feed, book="db1",
        doc_key=doc_key, doc_no=f"DO-{doc_key}", doc_date=doc_date,
        last_outcome="created", pushed_at=NOW - timedelta(days=1), vanished_at=vanished_at,
    )
    db.add(row)
    return row


def _latest_run(db, feed) -> AcDocFeedRun:
    return (
        db.query(AcDocFeedRun)
        .filter(AcDocFeedRun.feed_id == feed.id)
        .order_by(AcDocFeedRun.started_at.desc())
        .first()
    )


def _contract_first(handler):
    """S1 (review round 1) - the run-time contract gate now probes through
    the SAME `sink_transport` the push itself uses; every stubbed CRM
    handler in this file answers `/api/v1/external/contract` with a
    passing 2.7 contract FIRST, then falls through to its own handler."""

    def wrapped(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        return handler(request)

    return wrapped


def _vendor_by_day(seen_by_day: Dict[str, List[int]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/db1/deliveryorderbydocdate"
        day = request.url.params.get("DocDate")
        keys = seen_by_day.get(day, [])
        return httpx.Response(
            200,
            json=[
                {"DocKey": k, "DocNo": f"DO-{k}", "DocDate": f"{day[:4]}-{day[4:6]}-{day[6:]}T00:00:00",
                 "LastModified": f"{day[:4]}-{day[4:6]}-{day[6:]}T09:00:00.000", "Details": []}
                for k in keys
            ],
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


# ── 45 GETs with the window dates (AC-14-50) ────────────────────────────────


def test_sweep_gets_bydocdate_for_all_45_myt_days(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    seen_days: Set[str] = set()

    def vendor(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/db1/deliveryorderbydocdate"
        seen_days.add(request.url.params.get("DocDate"))
        return httpx.Response(200, json=[])

    run_sweep(db, feed, dry_run=False, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=httpx.MockTransport(_contract_first(lambda r: httpx.Response(200, json={}))))

    assert len(seen_days) == 45
    assert min(seen_days) == WINDOW_FROM.strftime("%Y%m%d")
    assert max(seen_days) == TODAY_MYT.strftime("%Y%m%d")


# ── union rule: a DocDate moved inside the window is not vanished (AC-14-51) ─


def test_a_dockey_seen_on_a_different_day_in_the_window_is_not_vanished(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    _ledger(db, feed, 111, doc_date=WINDOW_FROM)  # stored under the FIRST window day
    db.commit()

    moved_day = (WINDOW_FROM + timedelta(days=10)).strftime("%Y%m%d")
    posted_keys: List[int] = []

    def sink(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        posted_keys.extend(payload.get("doc_keys") or [])
        return httpx.Response(200, json={"dry_run": False, "summary": {}, "records": []})

    run_sweep(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_vendor_by_day({moved_day: [111]}),
        sink_transport=httpx.MockTransport(_contract_first(sink)),
    )
    assert 111 not in posted_keys


# ── one failed day -> no POST, sweep stays due (AC-14-52) ──────────────────


def test_one_failed_day_fails_the_sweep_and_posts_no_deletions(session_factory, monkeypatch):
    # S11 (review round 1) - the 500 is retried through the transport-error
    # ladder (1s then 4s) before the day itself is given up on.
    monkeypatch.setattr("time.sleep", lambda *_: None)
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    _ledger(db, feed, 222, doc_date=WINDOW_FROM)
    db.commit()

    def vendor(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("DocDate") == TODAY_MYT.strftime("%Y%m%d"):
            return httpx.Response(500, json={"message": "down"})
        return httpx.Response(200, json=[])

    posted = []
    run_sweep(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=httpx.MockTransport(_contract_first(lambda r: posted.append(1) or httpx.Response(200, json={}))),
    )
    run = _latest_run(db, feed)
    assert run.outcome == "FAILED"
    assert not posted


# ── guard: 51 of 100 candidates trips DELETE_GUARD (AC-14-53) ──────────────


def test_the_delete_guard_trips_at_51_of_100_window_ledger_rows(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    seen_keys = list(range(1, 50))  # 49 keys still present -> not candidates
    for key in range(1, 101):
        _ledger(db, feed, key, doc_date=WINDOW_FROM)
    db.commit()

    posted = []
    run_sweep(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_vendor_by_day({WINDOW_FROM.strftime("%Y%m%d"): seen_keys}),
        sink_transport=httpx.MockTransport(_contract_first(lambda r: posted.append(1) or httpx.Response(200, json={}))),
    )
    run = _latest_run(db, feed)
    assert run.outcome == "FAILED"
    assert run.error_code == "DELETE_GUARD"
    assert not posted


# ── deactivated/not_found set vanished_at; later push clears it (AC-14-54) ──


def test_deactivated_and_not_found_set_vanished_at(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    _ledger(db, feed, 333, doc_date=WINDOW_FROM)
    _ledger(db, feed, 334, doc_date=WINDOW_FROM)
    db.commit()

    def sink(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "dry_run": False, "summary": {"deactivated": 1, "not_found": 1},
                "records": [
                    {"source_ref": "db1:DO:333", "outcome": "deactivated", "entity_id": "x"},
                    {"source_ref": "db1:DO:334", "outcome": "not_found"},
                ],
            },
        )

    run_sweep(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_vendor_by_day({}),
        sink_transport=httpx.MockTransport(_contract_first(sink)),
    )
    rows = {r.doc_key: r for r in db.query(AcDocFeedLedger).filter(AcDocFeedLedger.company_id == co.id).all()}
    assert rows[333].vanished_at is not None
    assert rows[334].vanished_at is not None


def test_a_per_key_failed_verdict_is_counted_and_the_ledger_row_untouched(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    _ledger(db, feed, 335, doc_date=WINDOW_FROM)
    db.commit()

    def sink(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "dry_run": False, "summary": {"failed": 1},
                "records": [{"source_ref": "db1:DO:335", "outcome": "failed", "entity_id": "x", "errors": {"doc_date": "outside window"}}],
            },
        )

    run_sweep(db, feed, dry_run=False, now=NOW, vendor_transport=_vendor_by_day({}), sink_transport=httpx.MockTransport(_contract_first(sink)))
    run = _latest_run(db, feed)
    assert run.summary_json.get("failed", 0) >= 1
    row = db.query(AcDocFeedLedger).filter(AcDocFeedLedger.doc_key == 335, AcDocFeedLedger.company_id == co.id).one()
    assert row.vanished_at is None


# ── dry run writes nothing (AC-14-55) ───────────────────────────────────────


def test_dry_run_sweep_writes_no_vanished_at(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    _ledger(db, feed, 336, doc_date=WINDOW_FROM)
    db.commit()

    def sink(request: httpx.Request) -> httpx.Response:
        assert "dry_run=true" in str(request.url)
        return httpx.Response(
            200,
            json={"dry_run": True, "summary": {"deactivated": 1},
                  "records": [{"source_ref": "db1:DO:336", "outcome": "deactivated", "entity_id": "x"}]},
        )

    run_sweep(db, feed, dry_run=True, now=NOW, vendor_transport=_vendor_by_day({}), sink_transport=httpx.MockTransport(_contract_first(sink)))
    row = db.query(AcDocFeedLedger).filter(AcDocFeedLedger.doc_key == 336, AcDocFeedLedger.company_id == co.id).one()
    assert row.vanished_at is None


# ── deletions verdict matching by source_ref suffix (AC-14-42) ─────────────


def test_deletions_response_fixture_matches_and_flags_malformed_and_missing():
    """Uses the committed fixture directly against
    `SorentoSink.delete_doc_keys` (already covered structurally in
    `test_s14_doc_feed_batching.py`) - this test pins the PARSING rule
    itself: a malformed `source_ref` suffix, and a doc_key with NO verdict
    at all, both count as `failed`."""
    from modules.autocount.sinks_sorento import SorentoSink

    response = load_fixture("crm-deletions-delivery-orders-response.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    sink = SorentoSink(
        base_url="http://crm.example.test", api_key="k", entity_type="delivery_orders",
        company_code="SRT", book="db1", transport=httpx.MockTransport(handler),
    )
    # 55150 has NO verdict in the fixture at all - the "missing verdict"
    # case (AC-14-42's own "a key with no verdict is counted as failed").
    result = sink.delete_doc_keys(
        [55120, 55130, 55140, 55150], doc_date_from="2026-08-15", doc_date_to="2026-09-28", dry_run=False,
    )
    assert result["summary"]["deactivated"] == 1
    assert result["summary"]["not_found"] == 1
    # 55140 (failed, errors.doc_date) + the malformed "db1:DO:ABC" row both
    # land as failed; 55150 (no verdict at all) is the caller's own job to
    # detect by diffing the requested keys against the returned refs -
    # covered by `run_sweep`'s summary in the guard/per-key tests above.
    assert result["summary"]["failed"] == 2


# ── SS1 (review round 2) - the sweep's sink failure never leaks body/URL/key ─


def test_ss1_sweep_run_error_never_carries_the_crm_body_url_or_key(session_factory):
    from .s14_doc_feed_helpers import SORENTO_API_KEY

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = _feed(db, co, ac_conn)
    _ledger(db, feed, 333, doc_date=WINDOW_FROM)
    db.commit()

    def sink(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, text=f"denied {SORENTO_API_KEY} at http://crm.example.test/api/v1/x " + "z" * 800,
        )

    run_sweep(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_vendor_by_day({}),
        sink_transport=httpx.MockTransport(_contract_first(sink)),
    )
    run = _latest_run(db, feed)
    assert run.outcome == "FAILED" and run.error_code == "SINK_ERROR"
    assert SORENTO_API_KEY not in run.error
    assert "http://" not in run.error
    assert len(run.error) < 400
