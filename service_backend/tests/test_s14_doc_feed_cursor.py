"""sprint-5/14 S0 - owner test "cursor" (AC-14-11, 30..32, T1).

Exercises `modules.autocount.doc_feed.runner.run_poll(db, feed_row, *,
dry_run, now, vendor_transport=None, sink_transport=None)` (the EXACT
signature plan section 3.6 names) against a fully wired `AcDocFeed` row
(mode `push`), with the vendor and CRM both stubbed through
`httpx.MockTransport` - no network. `AcDocFeed`/`AcDocFeedRun` do not exist
yet (S0 red, D21); table names are pinned by plan section 3.1
(`ac_doc_feed`, `ac_doc_feed_run`), class names follow the house convention
(`AcCompany`/`AcEntityConfig`/`AcSyncRun` -> `AcDocFeed`/`AcDocFeedRun`).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

import httpx
import pytest

from modules.autocount.doc_feed.runner import run_poll
from modules.autocount.models import AcDocFeed, AcDocFeedRun

from .s14_doc_feed_helpers import CRM_BASE_URL, VENDOR_BASE_URL, wired_company

NOW = datetime(2026, 9, 29, 16, 30, 0, tzinfo=timezone.utc)  # 00:30 MYT on 30 Sep


def _feed(db, company, ac_conn, *, cursor_day: Optional[date] = None, mode: str = "push") -> AcDocFeed:
    feed = AcDocFeed(
        tenant_id=company.tenant_id,
        company_id=company.id,
        feed="delivery_orders",
        connection_id=ac_conn.id,
        book="db1",
        mode=mode,
        cursor_day=cursor_day,
    )
    db.add(feed)
    db.flush()
    return feed


def _empty_vendor_transport(seen_days: List[str]) -> httpx.MockTransport:
    """Every `byLastModified` day GET succeeds with an empty array; records
    the requested `lastModified` param so the test can assert WHICH days were
    actually read."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/db1/deliveryorderbyLastModified"
        seen_days.append(request.url.params.get("lastModified"))
        return httpx.Response(200, json=[])

    return httpx.Client(transport=httpx.MockTransport(handler))


def _failing_vendor_transport(*, fail_on_day: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/db1/deliveryorderbyLastModified"
        if request.url.params.get("lastModified") == fail_on_day:
            return httpx.Response(200, text="not json at all")
        return httpx.Response(200, json=[])

    return httpx.Client(transport=httpx.MockTransport(handler))


def _one_record_vendor_transport(day: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/db1/deliveryorderbyLastModified"
        if request.url.params.get("lastModified") == day:
            return httpx.Response(
                200,
                json=[
                    {
                        "DocKey": 900001,
                        "DocNo": "DO-CURSOR-1",
                        "DocDate": f"{day[:4]}-{day[4:6]}-{day[6:]}T00:00:00",
                        "LastModified": f"{day[:4]}-{day[4:6]}-{day[6:]}T10:00:00.000",
                        "Details": [],
                    }
                ],
            )
        return httpx.Response(200, json=[])

    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_sink_transport(outcome: str = "created") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "crm.example.test"
        # S1 (review round 1) - the run-time contract gate now probes
        # through this SAME `sink_transport`.
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        import json as _json

        payload = _json.loads(request.content.decode("utf-8"))
        records = payload.get("records") or []
        return httpx.Response(
            200,
            json={
                "dry_run": "dry_run=true" in str(request.url),
                "summary": {"total": len(records), outcome: len(records)},
                "records": [
                    {"source_ref": r["source_ref"] if "source_ref" in r else f"db1:DO:{r.get('DocKey')}",
                     "outcome": outcome, "entity_id": "00000000-0000-0000-0000-000000000099"}
                    for r in records
                ],
            },
        )

    return httpx.MockTransport(handler)


def _failing_sink_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        return httpx.Response(500, json={"message": "boom"})

    return httpx.MockTransport(handler)


def _latest_run(db, feed) -> AcDocFeedRun:
    return (
        db.query(AcDocFeedRun)
        .filter(AcDocFeedRun.feed_id == feed.id)
        .order_by(AcDocFeedRun.started_at.desc())
        .first()
    )


# ── no cursor = yesterday + today (AC-14-11, 30) ─────────────────────────────


def test_no_cursor_reads_yesterday_and_today_and_sets_cursor_to_tick_day(session_factory):
    db = session_factory()
    company, ac_conn, _crm_conn = wired_company(db)
    feed = _feed(db, company, ac_conn, cursor_day=None)

    seen: List[str] = []
    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_empty_vendor_transport(seen),
        sink_transport=_ok_sink_transport(),
    )

    assert sorted(seen) == ["20260929", "20260930"]
    db.refresh(feed)
    assert feed.cursor_day == date(2026, 9, 30)
    run = _latest_run(db, feed)
    assert run is not None
    assert run.outcome == "SUCCESS"


# ── 3-day catch-up in one run (AC-14-31) ─────────────────────────────────────


def test_three_day_catch_up_reads_the_whole_range_in_one_run(session_factory):
    db = session_factory()
    company, ac_conn, _crm_conn = wired_company(db)
    feed = _feed(db, company, ac_conn, cursor_day=date(2026, 9, 27))

    seen: List[str] = []
    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_empty_vendor_transport(seen),
        sink_transport=_ok_sink_transport(),
    )

    # cursor 27 Sep through today (30 Sep MYT) = 4 days.
    assert sorted(seen) == ["20260927", "20260928", "20260929", "20260930"]
    db.refresh(feed)
    assert feed.cursor_day == date(2026, 9, 30)


# ── 40-day catch-up capped at 31, continues next poll (AC-14-31) ────────────


def test_forty_day_catch_up_is_capped_at_31_days_then_continues(session_factory):
    db = session_factory()
    company, ac_conn, _crm_conn = wired_company(db)
    start = date(2026, 9, 30) - timedelta(days=40)
    feed = _feed(db, company, ac_conn, cursor_day=start)

    seen: List[str] = []
    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_empty_vendor_transport(seen),
        sink_transport=_ok_sink_transport(),
    )

    assert len(seen) == 31
    db.refresh(feed)
    capped_end = start + timedelta(days=30)
    assert feed.cursor_day == capped_end + timedelta(days=1)

    # The next poll carries on from where the first one stopped: it must
    # read from the just-set cursor day through today, never re-reading any
    # of the 31 days the first poll already covered.
    resumed_from = feed.cursor_day.strftime("%Y%m%d")
    seen_2: List[str] = []
    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_empty_vendor_transport(seen_2),
        sink_transport=_ok_sink_transport(),
    )
    assert min(seen_2) == resumed_from
    assert set(seen_2).isdisjoint(set(seen))
    db.refresh(feed)
    assert feed.cursor_day == date(2026, 9, 30)


# ── a vendor failure on any day keeps the cursor (AC-14-12, 32) ─────────────


def test_a_vendor_failure_on_any_day_fails_the_run_and_keeps_the_cursor(session_factory):
    db = session_factory()
    company, ac_conn, _crm_conn = wired_company(db)
    feed = _feed(db, company, ac_conn, cursor_day=None)

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_failing_vendor_transport(fail_on_day="20260930"),
        sink_transport=_ok_sink_transport(),
    )

    db.refresh(feed)
    assert feed.cursor_day is None
    run = _latest_run(db, feed)
    assert run.outcome == "FAILED"
    assert run.error_code == "VENDOR_NOT_JSON"


# ── a batch-level push failure keeps the cursor (AC-14-25, 32) ─────────────


def test_a_batch_level_push_failure_fails_the_run_and_keeps_the_cursor(session_factory):
    db = session_factory()
    company, ac_conn, _crm_conn = wired_company(db)
    feed = _feed(db, company, ac_conn, cursor_day=None)

    run_poll(
        db, feed, dry_run=False, now=NOW,
        vendor_transport=_one_record_vendor_transport("20260930"),
        sink_transport=_failing_sink_transport(),
    )

    db.refresh(feed)
    assert feed.cursor_day is None
    run = _latest_run(db, feed)
    assert run.outcome == "FAILED"


# ── dry run never advances the cursor (AC-14-27, 32) ─────────────────────────


def test_dry_run_never_advances_the_cursor(session_factory):
    db = session_factory()
    company, ac_conn, _crm_conn = wired_company(db)
    feed = _feed(db, company, ac_conn, cursor_day=None, mode="dry_run")

    run_poll(
        db, feed, dry_run=True, now=NOW,
        vendor_transport=_one_record_vendor_transport("20260930"),
        sink_transport=_ok_sink_transport(),
    )

    db.refresh(feed)
    assert feed.cursor_day is None
    run = _latest_run(db, feed)
    assert run.dry_run is True
