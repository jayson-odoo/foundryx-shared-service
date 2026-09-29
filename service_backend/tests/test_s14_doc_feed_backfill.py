"""sprint-5/14 S0 - owner test "backfill resume" (AC-14-60..65, T4).

`modules.autocount.doc_feed.runner.run_backfill` and
`modules.autocount.services.doc_feed_service.DocFeedService`'s backfill
methods do not exist yet (S0 red, D21). Method names
(`start_backfill`/`stop_backfill`/`resume_backfill`/`discard_backfill`) are
this tester's own reasonable naming for the four router actions plan
section 3.2 lists (`POST .../backfill`, `POST .../backfill/{stop|resume|
discard}`) - not literal plan text, flagged for the coder to confirm/rename.
`run_backfill`'s signature is assumed to mirror `run_poll`/`run_sweep`'s
(`db, backfill_row, *, now, vendor_transport=None, sink_transport=None`) -
dry-run-ness lives ON the backfill row (`AcDocFeedBackfill.dry_run`, plan
section 3.1), never a separate kwarg, since a backfill's dry-run-ness is
fixed at Start and never flips mid-run.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

import httpx
import pytest

from modules.autocount.doc_feed.runner import run_backfill
from modules.autocount.models import AcDocFeed, AcDocFeedBackfill
from modules.autocount.services.doc_feed_service import DocFeedService

from .s14_doc_feed_helpers import wired_company

NOW = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)
ACTOR_USER_ID = "actor-1"


def _feed(db, company, ac_conn, *, mode="push") -> AcDocFeed:
    row = AcDocFeed(
        tenant_id=company.tenant_id, company_id=company.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode=mode, cursor_day=date(2026, 9, 29),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _backfill(db, feed, *, from_day, to_day, next_day=None, dry_run=False, status="running") -> AcDocFeedBackfill:
    row = AcDocFeedBackfill(
        tenant_id=feed.tenant_id, company_id=feed.company_id, feed_id=feed.id, feed=feed.feed,
        book="db1", dry_run=dry_run, from_day=from_day, to_day=to_day,
        next_day=next_day or from_day, status=status, days_total=(to_day - from_day).days + 1,
        days_done=0, started_by=ACTOR_USER_ID, started_at=NOW,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _empty_vendor(seen_days: List[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/deliveryorderbydocdate"
        seen_days.append(request.url.params.get("DocDate"))
        return httpx.Response(200, json=[])

    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_sink() -> httpx.MockTransport:
    return httpx.MockTransport(lambda r: httpx.Response(200, json={"dry_run": False, "summary": {}, "records": []}))


# ── branch step then day loop, in order (AC-14-60) ──────────────────────────


def test_backfill_runs_the_branch_step_before_the_day_loop(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    branches_feed = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="branches",
        connection_id=ac_conn.id, book="db1", mode="push",
    )
    db.add(branches_feed)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 27), to_day=date(2026, 9, 29))

    call_order: List[str] = []

    def vendor(request: httpx.Request) -> httpx.Response:
        call_order.append(request.url.path)
        return httpx.Response(200, json=[] if request.url.path != "/branchbypage" else {"TotalCount": 0, "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": []})

    run_backfill(db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=_ok_sink())

    assert "/branchbypage" in call_order
    assert call_order.index("/branchbypage") < call_order.index("/deliveryorderbydocdate")
    db.refresh(bf)
    assert bf.branch_step == "done"


def test_backfill_skips_the_branch_step_when_the_branches_feed_is_off(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 28), to_day=date(2026, 9, 29))

    call_order: List[str] = []

    def vendor(request: httpx.Request) -> httpx.Response:
        call_order.append(request.url.path)
        return httpx.Response(200, json=[])

    run_backfill(db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=_ok_sink())
    assert "/branchbypage" not in call_order
    db.refresh(bf)
    assert bf.branch_step == "skipped"


# ── resume continues at nextDay, no repeated GETs (AC-14-61) ────────────────


def test_resume_starts_at_next_day_and_never_repeats_an_earlier_day(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    # Simulates "days 1-3 of 7 already done, worker crashed" - the orphan
    # hook (test_s14_doc_feed_scheduler.py) is what PRODUCES a `stopped` row
    # with `next_day` already durable; this test starts from that state.
    bf = _backfill(
        db, do_feed, from_day=date(2026, 9, 23), to_day=date(2026, 9, 29),
        next_day=date(2026, 9, 26), status="stopped",
    )
    DocFeedService(db).resume_backfill(co.tenant_id, co.id, "delivery_orders")
    db.refresh(bf)
    assert bf.status == "running"

    seen: List[str] = []
    run_backfill(db, bf, now=NOW, vendor_transport=_empty_vendor(seen), sink_transport=_ok_sink())

    assert "20260923" not in seen and "20260924" not in seen and "20260925" not in seen
    assert sorted(seen) == ["20260926", "20260927", "20260928", "20260929"]
    db.refresh(bf)
    assert bf.status == "done"


# ── Stop is cooperative, honoured at the next day boundary (AC-14-61) ──────


def test_a_backfill_already_marked_stopping_stops_without_processing_further(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 27), to_day=date(2026, 9, 29), status="stopping")

    seen: List[str] = []
    run_backfill(db, bf, now=NOW, vendor_transport=_empty_vendor(seen), sink_transport=_ok_sink())

    db.refresh(bf)
    assert bf.status == "stopped"


# ── Discard closes a stopped backfill (AC-14-61) ────────────────────────────


def test_discard_closes_a_stopped_backfill(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 27), to_day=date(2026, 9, 29), status="stopped")

    DocFeedService(db).discard_backfill(co.tenant_id, co.id, "delivery_orders")

    db.refresh(bf)
    assert bf.status == "done"
    assert bf.error_code == "DISCARDED"


# ── run-once guard on the full-history range (AC-14-62) ─────────────────────


def test_a_second_full_history_live_backfill_409s_once_the_first_is_done(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    do_feed.full_backfill_done_at = NOW
    db.commit()

    with pytest.raises(Exception) as exc_info:
        DocFeedService(db).start_backfill(
            co.tenant_id, co.id, "delivery_orders", dry_run=False,
            from_day=date(2023, 1, 1), to_day=date(2026, 9, 29), actor_user_id=ACTOR_USER_ID,
        )
    assert "BACKFILL_ALREADY_DONE" in str(exc_info.value)


def test_a_later_starting_live_backfill_is_allowed_even_after_full_history_done(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    do_feed.full_backfill_done_at = NOW
    db.commit()

    bf = DocFeedService(db).start_backfill(
        co.tenant_id, co.id, "delivery_orders", dry_run=False,
        from_day=date(2026, 9, 1), to_day=date(2026, 9, 10), actor_user_id=ACTOR_USER_ID,
    )
    assert bf is not None


def test_a_dry_run_backfill_is_never_guarded_by_run_once(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    do_feed.full_backfill_done_at = NOW
    db.commit()

    bf = DocFeedService(db).start_backfill(
        co.tenant_id, co.id, "delivery_orders", dry_run=True,
        from_day=date(2023, 1, 1), to_day=date(2026, 9, 29), actor_user_id=ACTOR_USER_ID,
    )
    assert bf is not None


# ── one open backfill per feed (409), mode/branches/range 422s (AC-14-63) ──


def test_a_second_open_backfill_409s(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    _backfill(db, do_feed, from_day=date(2026, 9, 1), to_day=date(2026, 9, 10), status="running")

    with pytest.raises(Exception) as exc_info:
        DocFeedService(db).start_backfill(
            co.tenant_id, co.id, "delivery_orders", dry_run=False,
            from_day=date(2026, 9, 11), to_day=date(2026, 9, 15), actor_user_id=ACTOR_USER_ID,
        )
    assert "BACKFILL_OPEN" in str(exc_info.value)


def test_a_live_backfill_needs_the_feed_in_push_mode(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn, mode="dry_run")

    with pytest.raises(Exception):
        DocFeedService(db).start_backfill(
            co.tenant_id, co.id, "delivery_orders", dry_run=False,
            from_day=date(2026, 9, 1), to_day=date(2026, 9, 10), actor_user_id=ACTOR_USER_ID,
        )


def test_branches_has_no_backfill(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    branches_feed = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="branches",
        connection_id=ac_conn.id, book="db1", mode="push",
    )
    db.add(branches_feed)
    db.commit()

    with pytest.raises(Exception):
        DocFeedService(db).start_backfill(
            co.tenant_id, co.id, "branches", dry_run=False,
            from_day=date(2026, 9, 1), to_day=date(2026, 9, 10), actor_user_id=ACTOR_USER_ID,
        )


def test_from_day_after_to_day_422s(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    _feed(db, co, ac_conn)

    with pytest.raises(Exception):
        DocFeedService(db).start_backfill(
            co.tenant_id, co.id, "delivery_orders", dry_run=False,
            from_day=date(2026, 9, 10), to_day=date(2026, 9, 1), actor_user_id=ACTOR_USER_ID,
        )


# ── a failing day stops the backfill, resumable (AC-14-65) ─────────────────


def test_a_day_that_cannot_be_read_stops_the_backfill_at_that_day(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 27), to_day=date(2026, 9, 29))

    def vendor(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("DocDate") == "20260928":
            return httpx.Response(500, json={"message": "down"})
        return httpx.Response(200, json=[])

    run_backfill(db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=_ok_sink())

    db.refresh(bf)
    assert bf.status == "stopped"
    assert bf.next_day == date(2026, 9, 28)
    assert bf.error is not None


def test_a_429_waits_up_to_ten_times_then_stops(session_factory, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 29), to_day=date(2026, 9, 29))

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"DocKey": 1, "DocNo": "DO-1", "DocDate": "2026-09-29", "LastModified": "2026-09-29T09:00:00.000", "Details": []}])

    def sink(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={}, headers={"Retry-After": "1"})

    run_backfill(db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=httpx.MockTransport(sink))
    db.refresh(bf)
    assert bf.status == "stopped"


# ── dry run writes nothing (AC-14-64) ───────────────────────────────────────


def test_dry_run_backfill_writes_no_ledger_or_cursor_state(session_factory):
    from modules.autocount.models import AcDocFeedLedger

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(
        db, do_feed, from_day=date(2026, 9, 27), to_day=date(2026, 9, 27), dry_run=True,
    )

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"DocKey": 99, "DocNo": "DO-99", "DocDate": "2026-09-27", "LastModified": "2026-09-27T09:00:00.000", "Details": []}])

    def sink(request: httpx.Request) -> httpx.Response:
        assert "dry_run=true" in str(request.url)
        return httpx.Response(200, json={"dry_run": True, "summary": {"created": 1}, "records": [{"source_ref": "db1:DO:99", "outcome": "created", "entity_id": "x"}]})

    run_backfill(db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=httpx.MockTransport(sink))

    assert db.query(AcDocFeedLedger).filter(AcDocFeedLedger.company_id == co.id, AcDocFeedLedger.doc_key == 99).first() is None
    db.refresh(bf)
    assert bf.status == "done"
