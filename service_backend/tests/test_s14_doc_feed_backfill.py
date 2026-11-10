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

from app.models.background_job import BackgroundJob
from modules.autocount.doc_feed.runner import run_backfill
from modules.autocount.models import AcDocFeed, AcDocFeedBackfill, AcDocFeedRun
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
        assert request.url.path == "/api/db1/deliveryorderbydocdate"
        seen_days.append(request.url.params.get("DocDate"))
        return httpx.Response(200, json=[])

    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_sink() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        # S1 (review round 1) - the run-time contract gate now probes
        # through this SAME `sink_transport`.
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders", "branches"]})
        return httpx.Response(200, json={"dry_run": False, "summary": {}, "records": []})

    return httpx.MockTransport(handler)


# ── no branch step (AC-14-46, plan 14 section 11 / D28) ─────────────────────
# Branches left the doc feed: a backfill is the day loop and nothing else.
# (The old "branch step before the day loop" tests were removed with the step.)


def test_ac_14_46_backfill_performs_no_branch_pull_only_the_day_loop(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 27), to_day=date(2026, 9, 29))

    call_order: List[str] = []

    def vendor(request: httpx.Request) -> httpx.Response:
        call_order.append(request.url.path)
        return httpx.Response(200, json=[])

    run_backfill(db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=_ok_sink())

    # Control: the day loop really ran (a run that read nothing would pass the
    # absence assertion below for the wrong reason).
    assert call_order.count("/api/db1/deliveryorderbydocdate") == 3
    assert not any("branchbypage" in path for path in call_order), call_order
    db.refresh(bf)
    assert bf.status == "done"


def test_ac_14_46_backfill_with_a_live_branches_row_left_over_still_pulls_no_branches(session_factory):
    """A dev DB / stray `ac_doc_feed` row with feed='branches' must never make a
    backfill read /branchbypage (the step is gone, not merely defaulted off)."""
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    db.add(AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="branches",
        connection_id=ac_conn.id, book="db1", mode="push",
    ))
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 28), to_day=date(2026, 9, 29))

    call_order: List[str] = []

    def vendor(request: httpx.Request) -> httpx.Response:
        call_order.append(request.url.path)
        return httpx.Response(200, json=[])

    run_backfill(db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=_ok_sink())
    assert call_order.count("/api/db1/deliveryorderbydocdate") == 2
    assert not any("branchbypage" in path for path in call_order), call_order


def _latest_backfill_run(db, backfill: AcDocFeedBackfill) -> AcDocFeedRun:
    return (
        db.query(AcDocFeedRun)
        .filter(AcDocFeedRun.feed_id == backfill.feed_id, AcDocFeedRun.kind == "backfill")
        .order_by(AcDocFeedRun.started_at.desc())
        .first()
    )


# ── S9 (review round 1) - the run row's own dayTo is the LAST day actually
# completed, never nextDay (one day PAST it) ─────────────────────────────────


def test_a_done_backfills_run_row_records_the_exact_day_range(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 27), to_day=date(2026, 9, 29))

    run_backfill(
        db, bf, now=NOW,
        vendor_transport=_empty_vendor([]), sink_transport=_ok_sink(),
    )

    db.refresh(bf)
    assert bf.status == "done"
    run = _latest_backfill_run(db, bf)
    assert run.day_from == date(2026, 9, 27)
    # A Done 3-day (27..29) backfill's run row must read 29, never 30
    # (`next_day`, one day PAST the last day actually read).
    assert run.day_to == date(2026, 9, 29)


def test_a_stopped_backfills_run_row_records_only_the_days_actually_completed(session_factory, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
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
    run = _latest_backfill_run(db, bf)
    # Day 27 is the ONLY day actually completed before day 28 failed.
    assert run.day_to == date(2026, 9, 27)


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
    seen: List[str] = []

    def vendor(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/db1/deliveryorderbydocdate"
        seen.append(request.url.params.get("DocDate"))
        return httpx.Response(200, json=[])

    def crm(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        return httpx.Response(200, json={"dry_run": False, "summary": {}, "records": []})

    def combined(request: httpx.Request) -> httpx.Response:
        if request.url.host == "crm.example.test":
            return crm(request)
        return vendor(request)

    # S10/regression fix (review round 1) - `resume_backfill`'s OWN job
    # dispatch now runs the resumed backfill INLINE, under eager test
    # settings, exactly like a real worker picking it straight back up (the
    # `_dispatch`/`_split_transport` seam gives this ONE raw transport
    # double duty for both the vendor door and the CRM contract probe/push).
    DocFeedService(db).resume_backfill(
        co.tenant_id, co.id, "delivery_orders", transport=httpx.MockTransport(combined),
    )

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


# ── B2 (review round 1) - orphan mid-run stops the loop, never DONE ─────────


def test_a_job_failed_out_from_under_the_loop_stops_it_and_never_reaches_done(session_factory):
    """The beat's own orphan sweep (a DIFFERENT session) can mark this
    backfill's `job_id` FAILED between two days of the SAME loop; the
    per-day fence (`_job_is_dead`) must stop pushing right there, and the
    zombie loop's own end-of-loop bookkeeping must never promote the row
    back to `done`."""
    from app.models.background_job import JOB_FAILED

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    job = BackgroundJob(
        tenant_id=co.tenant_id, type="autocount_doc_feed_backfill", status="running",
    )
    db.add(job)
    db.commit()
    bf = _backfill(
        db, do_feed, from_day=date(2026, 9, 27), to_day=date(2026, 9, 29),
    )
    bf.job_id = job.id
    db.commit()

    seen: List[str] = []

    def vendor(request: httpx.Request) -> httpx.Response:
        day = request.url.params.get("DocDate")
        seen.append(day)
        if day == "20260928":
            # Simulate the orphan sweep closing THIS job out from under the
            # still-running loop, from a DIFFERENT session, right before
            # the second day is processed.
            other = session_factory()
            row = other.query(BackgroundJob).filter(BackgroundJob.id == job.id).one()
            row.status = JOB_FAILED
            other.commit()
            other.close()
        return httpx.Response(200, json=[])

    run_backfill(
        db, bf, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=_ok_sink(),
    )

    db.refresh(bf)
    assert bf.status == "stopped"
    assert bf.error_code == "JOB_ORPHANED"
    # The day AFTER the one that tripped the fence is never read.
    assert "20260929" not in seen


# ── B2 (review round 1) - Resume refused while the old job is still live ───


def test_resume_is_refused_while_the_previous_job_is_still_live(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    job = BackgroundJob(
        tenant_id=co.tenant_id, type="autocount_doc_feed_backfill", status="running",
    )
    db.add(job)
    db.commit()
    bf = _backfill(
        db, do_feed, from_day=date(2026, 9, 27), to_day=date(2026, 9, 29), status="stopped",
    )
    bf.job_id = job.id
    db.commit()

    with pytest.raises(Exception) as exc_info:
        DocFeedService(db).resume_backfill(co.tenant_id, co.id, "delivery_orders")
    assert "BACKFILL_JOB_LIVE" in str(exc_info.value)
    db.refresh(bf)
    assert bf.status == "stopped"


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


def test_resume_re_checks_the_feed_is_still_in_push_mode(session_factory):
    """N2 (review round 1) - the SAME start-time rule Start applies is
    re-checked at Resume: the feed may have left Push while the backfill
    sat stopped."""
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn, mode="push")
    bf = _backfill(
        db, do_feed, from_day=date(2026, 9, 1), to_day=date(2026, 9, 10),
        dry_run=False, status="stopped",
    )
    do_feed.mode = "dry_run"
    db.commit()

    with pytest.raises(Exception) as exc_info:
        DocFeedService(db).resume_backfill(co.tenant_id, co.id, "delivery_orders")
    assert "mode" in str(exc_info.value) or "Push" in str(exc_info.value)
    db.refresh(bf)
    assert bf.status == "stopped"


def test_ac_14_46_branches_is_no_feed_so_it_has_no_backfill(session_factory):
    """Plan 14 section 11: `branches` is not a feed at all any more (it was a
    422 for having no backfill; now it is simply unknown)."""
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


def test_a_malformed_from_day_string_422s_not_500s(client, session_factory):
    """S4 (review round 1) - a malformed ISO date is a Pydantic-level 422
    (`DocFeedBackfillStartIn.fromDay: Optional[date]`), never a bare
    `date.fromisoformat` `ValueError` escaping the router as an unhandled
    500."""
    from .s14_doc_feed_helpers import auth_headers

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    _feed(db, co, ac_conn)
    headers = auth_headers(client)

    response = client.post(
        f"/autocount/doc-feeds/{co.id}/delivery_orders/backfill",
        json={"dryRun": True, "fromDay": "2026-13-01"}, headers=headers,
    )
    assert response.status_code == 422, response.text


# ── a failing day stops the backfill, resumable (AC-14-65) ─────────────────


def test_a_day_that_cannot_be_read_stops_the_backfill_at_that_day(session_factory, monkeypatch):
    # S11 (review round 1) - the 500 is retried through the transport-error
    # ladder (1s then 4s) before that day is given up on.
    monkeypatch.setattr("time.sleep", lambda *_: None)
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
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        return httpx.Response(429, json={}, headers={"Retry-After": "1"})

    run_backfill(db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=httpx.MockTransport(sink))
    db.refresh(bf)
    assert bf.status == "stopped"


def test_a_429_after_the_first_chunk_does_not_double_count_the_already_applied_chunk(session_factory, monkeypatch):
    """N3 (review round 1) - `write_batch` calls ``on_chunk`` (and this
    COMMITS + counts) for every chunk that resolves BEFORE the chunk that
    finally raises ``SorentoRateLimited``. A bare retry of the whole day's
    ``to_send`` list used to re-verdict the already-applied chunk a second
    time, double-counting ``aggregate_summary``. Two DocKeys, batch size 1
    (two chunks): the first chunk (DocKey 1) always succeeds; the second
    (DocKey 2) 429s for its first 3 posts (exhausting the sink's own
    internal ``_max_rate_limit_waits=2`` ladder and escaping as
    ``SorentoRateLimited``), then succeeds once the day-level retry resends
    only what is left."""
    from app.config import settings

    monkeypatch.setattr("time.sleep", lambda *_: None)
    monkeypatch.setattr(settings, "autocount_sink_batch_size", 1)
    monkeypatch.setattr(settings, "autocount_sink_concurrency", 1)
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 29), to_day=date(2026, 9, 29))

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"DocKey": 1, "DocNo": "DO-1", "DocDate": "2026-09-29", "LastModified": "2026-09-29T09:00:00.000", "Details": []},
                {"DocKey": 2, "DocNo": "DO-2", "DocDate": "2026-09-29", "LastModified": "2026-09-29T09:00:00.000", "Details": []},
            ],
        )

    key2_posts = {"count": 0}

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        payload = json.loads(request.content.decode("utf-8"))
        recs = payload.get("records") or []
        assert len(recs) == 1
        key = recs[0].get("DocKey")
        if key == 2:
            key2_posts["count"] += 1
            if key2_posts["count"] <= 3:
                return httpx.Response(429, json={}, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={
                "dry_run": False, "summary": {"created": 1},
                "records": [{"source_ref": f"db1:DO:{key}", "outcome": "created", "entity_id": "x"}],
            },
        )

    run_backfill(
        db, bf, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=httpx.MockTransport(sink),
    )

    db.refresh(bf)
    assert bf.status == "done"
    # Without the fix this reads 3 (DocKey 1's chunk re-verdicted on retry).
    assert bf.summary_json["created"] == 2


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
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        assert "dry_run=true" in str(request.url)
        return httpx.Response(200, json={"dry_run": True, "summary": {"created": 1}, "records": [{"source_ref": "db1:DO:99", "outcome": "created", "entity_id": "x"}]})

    run_backfill(db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=httpx.MockTransport(sink))

    assert db.query(AcDocFeedLedger).filter(AcDocFeedLedger.company_id == co.id, AcDocFeedLedger.doc_key == 99).first() is None
    db.refresh(bf)
    assert bf.status == "done"


# ═══ review round 2 ═════════════════════════════════════════════════════════


def _do_rec(key: int, day: str = "2026-09-29") -> Dict:
    return {
        "DocKey": key, "DocNo": f"DO-{key}", "DocDate": day,
        "LastModified": f"{day}T09:00:00.000", "Details": [],
    }


def _created(key: int) -> Dict:
    return {
        "dry_run": False, "summary": {"created": 1},
        "records": [{"source_ref": f"db1:DO:{key}", "outcome": "created", "entity_id": "x"}],
    }


def test_b2_a_failed_chunk_is_never_skipped_when_a_later_chunk_429s(session_factory, monkeypatch):
    """Reviewer's repro: batch size 1, DocKey 1 -> 502s (retries exhausted,
    the chunk is NOT credited), DocKey 2 -> created, DocKey 3 -> 429 x3 then
    200. The old positional slice dropped DocKey 1 and re-sent the already-
    credited DocKey 2 (created counted 3, day marked done). Credit by
    identity: DocKey 1 is re-sent, still fails, and the day ends as an error."""
    from app.config import settings
    from modules.autocount.models import AcDocFeedLedger

    monkeypatch.setattr("time.sleep", lambda *_: None)
    monkeypatch.setattr(settings, "autocount_sink_batch_size", 1)
    monkeypatch.setattr(settings, "autocount_sink_concurrency", 1)
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 29), to_day=date(2026, 9, 29))

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_do_rec(1), _do_rec(2), _do_rec(3)])

    posts: Dict[int, int] = {1: 0, 2: 0, 3: 0}

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        key = json.loads(request.content.decode("utf-8"))["records"][0]["DocKey"]
        posts[key] += 1
        if key == 1:
            return httpx.Response(502, json={"message": "bad gateway"})
        if key == 3 and posts[3] <= 3:
            return httpx.Response(429, json={}, headers={"Retry-After": "0"})
        return httpx.Response(200, json=_created(key))

    run_backfill(
        db, bf, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=httpx.MockTransport(sink),
    )

    db.refresh(bf)
    assert bf.status == "stopped"
    assert bf.error_code == "SINK_ERROR"
    assert bf.next_day == date(2026, 9, 29)  # the day is NOT marked complete
    run = _latest_backfill_run(db, bf)
    assert run.outcome == "FAILED"
    assert run.summary_json["created"] == 2  # keys 2 and 3, each exactly once
    assert posts[2] == 1  # the credited chunk is never re-sent
    ledger_keys = {
        r.doc_key for r in db.query(AcDocFeedLedger).filter(AcDocFeedLedger.company_id == co.id).all()
    }
    assert ledger_keys == {2, 3}  # DocKey 1 is not marked delivered


def test_b2_a_failed_chunk_that_succeeds_on_the_429_retry_completes_the_day(session_factory, monkeypatch):
    from app.config import settings

    monkeypatch.setattr("time.sleep", lambda *_: None)
    monkeypatch.setattr(settings, "autocount_sink_batch_size", 1)
    monkeypatch.setattr(settings, "autocount_sink_concurrency", 1)
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 29), to_day=date(2026, 9, 29))

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_do_rec(1), _do_rec(2), _do_rec(3)])

    posts: Dict[int, int] = {1: 0, 2: 0, 3: 0}

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        key = json.loads(request.content.decode("utf-8"))["records"][0]["DocKey"]
        posts[key] += 1
        if key == 1 and posts[1] <= 3:  # the first attempt's retries all fail
            return httpx.Response(502, json={})
        if key == 3 and posts[3] <= 3:
            return httpx.Response(429, json={}, headers={"Retry-After": "0"})
        return httpx.Response(200, json=_created(key))

    run_backfill(
        db, bf, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=httpx.MockTransport(sink),
    )
    db.refresh(bf)
    assert bf.status == "done"
    assert bf.summary_json["created"] == 3


def test_b3_start_route_maps_open_backfill_to_409(client, session_factory):
    from .s14_doc_feed_helpers import auth_headers

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    _backfill(db, do_feed, from_day=date(2026, 9, 1), to_day=date(2026, 9, 10), status="running")
    response = client.post(
        f"/autocount/doc-feeds/{co.id}/delivery_orders/backfill",
        json={"dryRun": True}, headers=auth_headers(client),
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "BACKFILL_OPEN"


# ── SS1 - a sink failure never leaks the CRM body, URL or API key ───────────


def test_ss1_backfill_error_never_carries_the_crm_body_url_or_key(session_factory):
    from .s14_doc_feed_helpers import SORENTO_API_KEY

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 29), to_day=date(2026, 9, 29))

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_do_rec(1)])

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        return httpx.Response(
            400,
            text=f"denied key {SORENTO_API_KEY} at http://crm.example.test/api/v1/external/ingest/x " + "z" * 800,
        )

    run_backfill(
        db, bf, now=NOW,
        vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=httpx.MockTransport(sink),
    )
    db.refresh(bf)
    assert bf.status == "stopped"
    for text in (bf.error, _latest_backfill_run(db, bf).error):
        assert SORENTO_API_KEY not in text
        assert "http://" not in text
        assert len(text) < 400


# ── SS2 - a fromDay below the floor is a 422, not 740k vendor GETs ──────────


def test_ss2_from_day_below_the_floor_422s(client, session_factory):
    from .s14_doc_feed_helpers import auth_headers

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    _feed(db, co, ac_conn)
    response = client.post(
        f"/autocount/doc-feeds/{co.id}/delivery_orders/backfill",
        json={"dryRun": True, "fromDay": "0001-01-01"}, headers=auth_headers(client),
    )
    assert response.status_code == 422, response.text
    assert "fromDay" in response.json()["detail"]["fieldErrors"]
    assert db.query(AcDocFeedBackfill).count() == 0


# ── SS3 - the loop re-reads feed mode / tenant / module every day ───────────


def _flip_from_other_session(session_factory, feed_id: str, mode: str) -> None:
    other = session_factory()
    row = other.query(AcDocFeed).filter(AcDocFeed.id == feed_id).one()
    row.mode = mode
    other.commit()
    other.close()


def test_ss3_a_feed_switched_off_mid_backfill_stops_it(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 27), to_day=date(2026, 9, 29))
    seen: List[str] = []

    def vendor(request: httpx.Request) -> httpx.Response:
        day = request.url.params.get("DocDate")
        seen.append(day)
        if day == "20260928":
            _flip_from_other_session(session_factory, do_feed.id, "off")
        return httpx.Response(200, json=[])

    run_backfill(
        db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=_ok_sink(),
    )
    db.refresh(bf)
    assert bf.status == "stopped"
    assert bf.error_code == "FEED_OFF"
    assert "20260929" not in seen


def test_ss3_a_live_backfill_stops_when_the_feed_leaves_push(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 27), to_day=date(2026, 9, 29), dry_run=False)

    def vendor(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("DocDate") == "20260927":
            _flip_from_other_session(session_factory, do_feed.id, "dry_run")
        return httpx.Response(200, json=[])

    run_backfill(
        db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=_ok_sink(),
    )
    db.refresh(bf)
    assert bf.status == "stopped"
    assert bf.error_code == "FEED_NOT_PUSH"


def test_ss3_a_deactivated_module_stops_the_backfill(session_factory):
    from app.models.module import MODULE_STATUS_INACTIVE, Module, TenantModule

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 27), to_day=date(2026, 9, 29))

    def vendor(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("DocDate") == "20260927":
            other = session_factory()
            tm = (
                other.query(TenantModule)
                .join(Module, Module.id == TenantModule.module_id)
                .filter(TenantModule.tenant_id == co.tenant_id, Module.name == "autocount")
                .one()
            )
            tm.status = MODULE_STATUS_INACTIVE
            other.commit()
            other.close()
        return httpx.Response(200, json=[])

    run_backfill(
        db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=_ok_sink(),
    )
    db.refresh(bf)
    assert bf.status == "stopped"
    assert bf.error_code == "TENANT_INACTIVE"


def test_ss3_start_is_refused_on_an_off_feed_even_for_a_dry_run(client, session_factory):
    from .s14_doc_feed_helpers import auth_headers

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    _feed(db, co, ac_conn, mode="off")
    response = client.post(
        f"/autocount/doc-feeds/{co.id}/delivery_orders/backfill",
        json={"dryRun": True}, headers=auth_headers(client),
    )
    assert response.status_code == 422, response.text
    assert "mode" in response.json()["detail"]["fieldErrors"]


# ── RS4 - the 429 waits heartbeat (a wait can last minutes) ─────────────────


def test_rs4_every_429_wait_heartbeats_the_job(session_factory, monkeypatch):
    import modules.autocount.doc_feed.runner as runner_mod

    monkeypatch.setattr("time.sleep", lambda *_: None)
    beats: List[str] = []
    monkeypatch.setattr(runner_mod, "_heartbeat", lambda db, job_id: beats.append(job_id))
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 29), to_day=date(2026, 9, 29))
    bf.job_id = "job-heartbeat"
    db.commit()

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_do_rec(1)])

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        return httpx.Response(429, json={}, headers={"Retry-After": "1"})

    run_backfill(
        db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=httpx.MockTransport(sink),
    )
    # 1 vendor day + one beat per wait (10 waits) - never just the day beat.
    assert len(beats) >= 1 + runner_mod.MAX_BACKFILL_RATE_LIMIT_WAITS


# ── N2 - a resumed segment's run row starts at the segment's own first day ──


def test_n2_a_resumed_segments_run_row_starts_at_the_segments_first_day(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(
        db, do_feed, from_day=date(2026, 9, 23), to_day=date(2026, 9, 29),
        next_day=date(2026, 9, 27), status="running",
    )
    run_backfill(db, bf, now=NOW, vendor_transport=_empty_vendor([]), sink_transport=_ok_sink())
    run = _latest_backfill_run(db, bf)
    assert run.day_from == date(2026, 9, 27)
    assert run.day_to == date(2026, 9, 29)


def test_n2_a_zero_day_segment_has_no_day_to_before_its_day_from(session_factory, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(
        db, do_feed, from_day=date(2026, 9, 23), to_day=date(2026, 9, 29),
        next_day=date(2026, 9, 27), status="running",
    )

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "down"})

    run_backfill(db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)), sink_transport=_ok_sink())
    run = _latest_backfill_run(db, bf)
    assert run.day_from == date(2026, 9, 27)
    assert run.day_to is None


# ── N5 - two concurrent Starts: the loser is a 409, never a 500 ─────────────


def test_n5_a_lost_start_race_is_a_backfill_open_conflict(session_factory, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from modules.autocount.repositories.doc_feed_repository import DocFeedBackfillRepository

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    _feed(db, co, ac_conn)

    real_commit = db.commit
    real_add = DocFeedBackfillRepository.add
    state = {"armed": False, "raised": False}

    def add_and_arm(self, row):
        state["armed"] = True
        return real_add(self, row)

    def flaky_commit():
        # Fail exactly the commit that persists the new backfill row.
        if state["armed"] and not state["raised"]:
            state["raised"] = True
            raise IntegrityError("insert", {}, Exception("uq_ac_doc_feed_backfill_one_open"))
        return real_commit()

    monkeypatch.setattr(DocFeedBackfillRepository, "add", add_and_arm)
    monkeypatch.setattr(db, "commit", flaky_commit)
    with pytest.raises(Exception) as exc_info:
        DocFeedService(db).start_backfill(
            co.tenant_id, co.id, "delivery_orders", dry_run=True,
            from_day=date(2026, 9, 1), to_day=date(2026, 9, 2), actor_user_id=ACTOR_USER_ID,
        )
    assert "BACKFILL_OPEN" in str(exc_info.value)
    monkeypatch.setattr(db, "commit", real_commit)
    assert db.query(AcDocFeedBackfill).count() == 0


# ── N6 - Resume carries the actor onto the new job ──────────────────────────


def test_n6_resume_stamps_the_actor_on_the_new_job(session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    bf = _backfill(
        db, do_feed, from_day=date(2026, 9, 27), to_day=date(2026, 9, 29),
        status="stopped", dry_run=True,
    )
    def combined(request: httpx.Request) -> httpx.Response:
        if request.url.host == "crm.example.test":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        return httpx.Response(200, json=[])

    DocFeedService(db).resume_backfill(
        co.tenant_id, co.id, "delivery_orders", actor_user_id=ACTOR_USER_ID,
        transport=httpx.MockTransport(combined),
    )
    db.refresh(bf)
    job = db.query(BackgroundJob).filter(BackgroundJob.id == bf.job_id).one()
    assert job.actor_user_id == ACTOR_USER_ID


# ═══ review round 2 follow-ups ══════════════════════════════════════════════


def test_s2_resume_is_refused_on_an_off_feed(client, session_factory):
    from .s14_doc_feed_helpers import auth_headers

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn, mode="off")
    bf = _backfill(
        db, do_feed, from_day=date(2026, 9, 1), to_day=date(2026, 9, 10),
        dry_run=True, status="stopped",
    )
    response = client.post(
        f"/autocount/doc-feeds/{co.id}/delivery_orders/backfill/resume", headers=auth_headers(client),
    )
    assert response.status_code == 422, response.text
    assert "mode" in response.json()["detail"]["fieldErrors"]
    db.refresh(bf)
    assert bf.status == "stopped"
    assert db.query(AcDocFeedRun).filter(AcDocFeedRun.feed_id == do_feed.id).count() == 0


def test_n1_the_orphan_fence_before_a_429_sleep_stops_as_job_orphaned(session_factory, monkeypatch):
    from app.models.background_job import JOB_FAILED

    slept: List[float] = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    do_feed = _feed(db, co, ac_conn)
    job = BackgroundJob(tenant_id=co.tenant_id, type="autocount_doc_feed_backfill", status="running")
    db.add(job)
    db.commit()
    bf = _backfill(db, do_feed, from_day=date(2026, 9, 29), to_day=date(2026, 9, 29))
    bf.job_id = job.id
    db.commit()

    def vendor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_do_rec(1)])

    def sink(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/external/contract":
            return httpx.Response(200, json={"version": "2.7", "entities": ["delivery_orders"]})
        # The orphan sweep fails this job from a DIFFERENT session while the
        # sink is being rate limited.
        other = session_factory()
        other.query(BackgroundJob).filter(BackgroundJob.id == job.id).one().status = JOB_FAILED
        other.commit()
        other.close()
        return httpx.Response(429, json={}, headers={"Retry-After": "1"})

    run_backfill(
        db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(vendor)),
        sink_transport=httpx.MockTransport(sink),
    )
    db.refresh(bf)
    assert bf.status == "stopped"
    assert bf.error_code == "JOB_ORPHANED"
    # The runner's own wait (Retry-After 1, after the sink's internal ones)
    # never happens: the fence fires first, so no further POSTs either.
    assert bf.error_code != "SINK_ERROR"
