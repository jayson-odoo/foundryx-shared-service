"""Plan 72 - the project registrations feed against the CRM contract 2.15 and
UAC S0-1..S0-14 (sorento-crm #2676). AutoCount and the CRM are faked; all
data is fake. Red first: each test names the UAC id it pins.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import httpx
import pytest

from modules.autocount.doc_feed.runner import run_backfill, run_poll
from modules.autocount.models import (
    AcApiCallLog,
    AcDocFeedIssue,
    AcDocFeedLedger,
)
from modules.autocount.services.doc_feed_service import DocFeedService

from .test_autocount_project_registrations_feed import (
    DB3_URL,
    NOW,
    PR,
    _backfill,
    _feed,
    _reg,
    _Vendor,
    _wire,
    _wired,
    db,  # noqa: F401 - the shared session fixture
)


@pytest.fixture(autouse=True)
def _no_day_pause(monkeypatch):
    """The pause between backfill days is pinned in its own test."""
    from app.config import settings

    monkeypatch.setattr(settings, "autocount_project_registrations_day_pause_seconds", 0.0)


class _Crm:
    """A fake CRM: contract probe + ingest door, with per-record outcomes/codes
    and an optional HTTP failure on the n-th push."""

    def __init__(self, *, outcome: str = "created", code: Optional[str] = None,
                 outcomes: Optional[Dict[str, Any]] = None, fail_status: int = 0,
                 fail_pushes: int = 0):
        self.outcome = outcome
        self.code = code
        self.outcomes = outcomes or {}
        self.fail_status = fail_status
        self.fail_pushes = fail_pushes
        self.pushes: List[Dict[str, Any]] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/api/v1/external/contract":
                return httpx.Response(200, json={"version": "2.15", "entities": [PR]})
            assert path == f"/api/v1/external/ingest/{PR}", path
            body = json.loads(request.content)
            body["_dry_run"] = request.url.params.get("dry_run") == "true"
            self.pushes.append(body)
            if self.fail_pushes > 0:
                self.fail_pushes -= 1
                return httpx.Response(self.fail_status, json={"detail": "fake failure"})
            records = []
            for r in body["records"]:
                outcome, code = self.outcomes.get(r["ProjNo"], (self.outcome, self.code))
                verdict = {"source_ref": r["source_ref"], "outcome": outcome, "warnings": []}
                if code:
                    verdict["code"] = code
                records.append(verdict)
            return httpx.Response(200, json={"summary": {}, "records": records})

        return httpx.MockTransport(handler)


def _transient_sleep(monkeypatch):
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda *_a, **_k: None)


# ── S0-1 logged reader ──────────────────────────────────────────────────────


def test_s0_1_each_day_read_is_one_api_call_log_row(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    vendor = _Vendor({"20261121": [_reg("P1", "2026-11-21")]})
    run = run_poll(db, feed, dry_run=False, now=NOW,
                   vendor_transport=vendor.transport(), sink_transport=_Crm().transport())
    assert run.outcome == "SUCCESS", run.error
    rows = db.query(AcApiCallLog).order_by(AcApiCallLog.created_at).all()
    assert [r.path for r in rows] == [
        "/ProjectRegbyDate?Date=20261121", "/ProjectRegbyDate?Date=20261122",
    ]
    assert {r.book for r in rows} == {"db3"}
    assert {r.method for r in rows} == {"GET"}
    assert {r.response_status for r in rows} == {200}
    assert {r.outcome for r in rows} == {"ok"}
    assert {r.company_id for r in rows} == {co.id}
    assert all(DB3_URL.split("/")[2] not in (r.path + (r.response_body or "")) for r in rows)


def test_s0_1_a_failed_day_read_is_logged_too(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    vendor = _Vendor({}, fail_on="20261121")
    run = run_poll(db, feed, dry_run=False, now=NOW,
                   vendor_transport=vendor.transport(), sink_transport=_Crm().transport())
    assert run.outcome == "FAILED"
    rows = db.query(AcApiCallLog).all()
    assert len(rows) == 1 and rows[0].response_status == 404 and rows[0].outcome == "http_error"


def test_s0_1_delivery_order_feed_reads_are_not_moved_onto_the_call_log(db):
    """Blast radius: only the registrations feed writes ac_api_call_log rows."""
    from .s14_doc_feed_helpers import autocount_connection, company, sorento_connection

    ac_conn = autocount_connection(db, base_url=DB3_URL, name="open do")
    co = company(db, sink_connection=sorento_connection(db), ac_connection=ac_conn)
    feed = _feed(db, co, ac_conn, feed="delivery_orders")

    def handler(request):
        if request.url.path.endswith("/contract"):
            return httpx.Response(200, json={"version": "2.15", "entities": ["delivery_orders"]})
        if "/ingest/" in request.url.path:
            return httpx.Response(200, json={"summary": {}, "records": []})
        return httpx.Response(200, json=[])

    run_poll(db, feed, dry_run=False, now=NOW,
             vendor_transport=httpx.Client(transport=httpx.MockTransport(handler)),
             sink_transport=httpx.MockTransport(handler))
    assert db.query(AcApiCallLog).count() == 0


# ── S0-2 / S0-3 / S0-4 / S0-11 ──────────────────────────────────────────────


def test_s0_2_an_empty_day_pushes_nothing_and_advances_the_cursor(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2006, 1, 1), to_day=date(2006, 1, 3), dry_run=False)
    crm = _Crm()
    run_backfill(db, bf, now=NOW, vendor_transport=_Vendor({}).transport(),
                 sink_transport=crm.transport())
    db.refresh(bf)
    assert crm.pushes == []
    assert bf.status == "done" and bf.next_day == date(2006, 1, 4) and bf.days_done == 3


def test_s0_3_records_pass_through_with_source_ref_and_a_day_date(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    rec = _reg("PPF0603000123X", "2006-03-14",
               ProjectTitle="Project 001 Block A\r\nUntuk Tetuan Company 001 Sdn. Bhd.",
               CustomerName="customer 001 ", Developer="")
    bf = _backfill(db, feed, from_day=date(2006, 3, 14), to_day=date(2006, 3, 14), dry_run=False)
    crm = _Crm()
    run_backfill(db, bf, now=NOW, vendor_transport=_Vendor({"20060314": [rec]}).transport(),
                 sink_transport=crm.transport())
    sent = crm.pushes[0]["records"][0]
    assert sent == _wire(rec)
    assert sent["source_ref"] == "db3:PROJREG:PPF0603000123X"
    assert sent["Date"] == "2006-03-14"
    assert sent["ProjectTitle"].count("\r\n") == 1
    assert sent["CustomerName"] == "customer 001 "  # no trim, no case change
    assert len(sent["ProjNo"]) == 14


def test_s0_3_an_unparseable_date_is_sent_as_read(db):
    from modules.autocount.doc_feed.records import RawVendorRecord, project_registration_wire

    rec = _reg("P1", "2006-01-01", Date="not a date")
    assert project_registration_wire(rec, "db3:PROJREG:P1")["Date"] == "not a date"
    assert RawVendorRecord(source_ref="x", entity_type="delivery_orders",
                           raw={"DocKey": 1}).sink_payload() == {"DocKey": 1}


def test_s0_4_a_day_of_1001_records_goes_out_as_two_pushes(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    rows = [_reg(f"P{i:05d}", "2006-01-01") for i in range(1001)]
    bf = _backfill(db, feed, from_day=date(2006, 1, 1), to_day=date(2006, 1, 1), dry_run=False)
    crm = _Crm()
    run_backfill(db, bf, now=NOW, vendor_transport=_Vendor({"20060101": rows}).transport(),
                 sink_transport=crm.transport())
    assert [len(p["records"]) for p in crm.pushes] == [1000, 1]
    assert all(p.get("backfill") is True for p in crm.pushes)  # S0-11


def test_s0_11_poll_pushes_never_carry_backfill(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    crm = _Crm()
    run_poll(db, feed, dry_run=False, now=NOW,
             vendor_transport=_Vendor({"20261121": [_reg("P1", "2026-11-21")]}).transport(),
             sink_transport=crm.transport())
    assert crm.pushes and all("backfill" not in p for p in crm.pushes)


# ── S0-5 pause between days ─────────────────────────────────────────────────


def test_s0_5_backfill_pauses_between_days(db, monkeypatch):
    from app.config import settings
    from modules.autocount.doc_feed import runner

    monkeypatch.setattr(settings, "autocount_project_registrations_day_pause_seconds", 0.25)
    sleeps: List[float] = []
    monkeypatch.setattr(runner, "_day_pause", lambda seconds: sleeps.append(seconds))
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2006, 1, 1), to_day=date(2006, 1, 3), dry_run=True)
    vendor = _Vendor({})
    run_backfill(db, bf, now=NOW, vendor_transport=vendor.transport(), sink_transport=_Crm().transport())
    assert vendor.calls == ["20060101", "20060102", "20060103"]
    assert sleeps == [0.25, 0.25]  # between days, not after the last


# ── S0-6 / S0-7 / S0-8 cursor ───────────────────────────────────────────────


def test_s0_7_a_vendor_timeout_on_day_n_keeps_the_cursor_on_n(db, monkeypatch):
    _transient_sleep(monkeypatch)
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2006, 1, 1), to_day=date(2006, 1, 3), dry_run=False)
    calls: List[str] = []

    def handler(request):
        day = request.url.params.get("Date")
        calls.append(day)
        if day == "20060102":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json=[_reg("A" + day, "2006-01-01")])

    run_backfill(db, bf, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(handler)),
                 sink_transport=_Crm().transport())
    db.refresh(bf)
    assert bf.status == "stopped" and bf.next_day == date(2006, 1, 2)
    bf.status = "running"
    db.commit()
    again = _Vendor({})
    run_backfill(db, bf, now=NOW, vendor_transport=again.transport(), sink_transport=_Crm().transport())
    assert again.calls == ["20060102", "20060103"]  # retries N; never re-reads N-1


@pytest.mark.parametrize("status", [400, 422, 500])
def test_s0_8_a_crm_error_keeps_the_cursor_and_resends_the_same_batch(db, monkeypatch, status):
    _transient_sleep(monkeypatch)
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2006, 1, 1), to_day=date(2006, 1, 2), dry_run=False)
    data = {"20060101": [_reg("A1", "2006-01-01")], "20060102": [_reg("B1", "2006-01-02")]}
    crm = _Crm(fail_status=status, fail_pushes=99)
    run_backfill(db, bf, now=NOW, vendor_transport=_Vendor(data).transport(),
                 sink_transport=crm.transport())
    db.refresh(bf)
    assert bf.status == "stopped" and bf.next_day == date(2006, 1, 1)
    first_batch = crm.pushes[0]["records"]

    bf.status = "running"
    db.commit()
    ok = _Crm()
    run_backfill(db, bf, now=NOW, vendor_transport=_Vendor(data).transport(), sink_transport=ok.transport())
    db.refresh(bf)
    assert ok.pushes[0]["records"] == first_batch
    assert bf.status == "done"


def test_s0_8_a_crm_timeout_keeps_the_cursor(db, monkeypatch):
    _transient_sleep(monkeypatch)
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2006, 1, 1), to_day=date(2006, 1, 1), dry_run=False)

    def handler(request):
        if request.url.path.endswith("/contract"):
            return httpx.Response(200, json={"version": "2.15", "entities": [PR]})
        raise httpx.ReadTimeout("slow", request=request)

    run_backfill(db, bf, now=NOW, vendor_transport=_Vendor({"20060101": [_reg("A1", "2006-01-01")]}).transport(),
                 sink_transport=httpx.MockTransport(handler))
    db.refresh(bf)
    assert bf.status == "stopped" and bf.next_day == date(2006, 1, 1)


# ── S0-9 skipped: switched_off ──────────────────────────────────────────────


def test_s0_9_switched_off_keeps_the_backfill_cursor(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2006, 1, 1), to_day=date(2006, 1, 2), dry_run=False)
    vendor = _Vendor({"20060101": [_reg("A1", "2006-01-01")], "20060102": [_reg("B1", "2006-01-02")]})
    run_backfill(db, bf, now=NOW, vendor_transport=vendor.transport(),
                 sink_transport=_Crm(outcome="skipped", code="switched_off").transport())
    db.refresh(bf)
    assert bf.status == "stopped"
    assert bf.next_day == date(2006, 1, 1)
    assert bf.error_code == "CRM_SWITCHED_OFF"
    assert bf.error == "CRM project sync is switched off"
    assert vendor.calls == ["20060101"]
    assert db.query(AcDocFeedLedger).filter_by(feed=PR).count() == 0
    assert db.query(AcDocFeedIssue).filter_by(feed=PR).count() == 0
    db.refresh(feed)
    assert feed.full_backfill_done_at is None


def test_s0_9_switched_off_is_the_polls_last_error(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn, cursor_day=date(2026, 11, 21))
    run = run_poll(db, feed, dry_run=False, now=NOW,
                   vendor_transport=_Vendor({"20261121": [_reg("P1", "2026-11-21")]}).transport(),
                   sink_transport=_Crm(outcome="skipped", code="switched_off").transport())
    assert run.outcome == "FAILED"
    assert run.error_code == "CRM_SWITCHED_OFF"
    assert run.error == "CRM project sync is switched off"
    db.refresh(feed)
    assert feed.cursor_day == date(2026, 11, 21)
    item = next(i for i in DocFeedService(db).view(co.tenant_id, co.id).feeds if i.feed == PR)
    assert item.lastRun.error == "CRM project sync is switched off"


def test_s0_9_other_skips_and_needs_review_are_final_not_retried(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2006, 1, 1), to_day=date(2006, 1, 1), dry_run=False)
    rows = [_reg("A1", "2006-01-01"), _reg("A2", "2006-01-01"), _reg("A3", "2006-01-01")]
    crm = _Crm(outcomes={"A1": ("skipped", "duplicate"), "A2": ("failed", "needs_review"),
                         "A3": ("created", None)})
    run_backfill(db, bf, now=NOW, vendor_transport=_Vendor({"20060101": rows}).transport(),
                 sink_transport=crm.transport())
    db.refresh(bf)
    assert bf.status == "done"
    month = bf.summary_json["byMonth"]["2006-01"]
    assert month == {"read": 3, "created": 1, "updated": 0, "unchanged": 0,
                     "needsReview": 1, "skipped": 1}
    kinds = {i.doc_no: i.kind for i in db.query(AcDocFeedIssue).filter_by(feed=PR).all()}
    assert "retryable" not in kinds.values()


# ── S0-10 dry run ───────────────────────────────────────────────────────────


def test_s0_10_dry_run_marks_every_push_and_the_real_pass_starts_at_the_floor(db, monkeypatch):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2006, 1, 1), to_day=date(2006, 1, 2), dry_run=True)
    crm = _Crm(outcomes={"A1": ("created", None), "A2": ("updated", None)})
    run_backfill(db, bf, now=NOW,
                 vendor_transport=_Vendor({"20060101": [_reg("A1", "2006-01-01"), _reg("A2", "2006-01-01")]}).transport(),
                 sink_transport=crm.transport())
    db.refresh(bf)
    assert crm.pushes and all(p["_dry_run"] for p in crm.pushes)
    assert bf.summary_json["byMonth"]["2006-01"]["created"] == 1
    assert bf.summary_json["byMonth"]["2006-01"]["updated"] == 1
    db.refresh(feed)
    assert feed.full_backfill_done_at is None and feed.cursor_day is None

    service = DocFeedService(db)
    monkeypatch.setattr(service, "_dispatch", lambda *a, **k: None)
    real = service.start_backfill(co.tenant_id, co.id, PR, dry_run=False,
                                  from_day=date(2006, 1, 1), to_day=date(2006, 1, 2))
    assert real.id != bf.id and real.next_day == date(2006, 1, 1) and not real.dry_run


class _FakeJobs:
    def __init__(self, sink):
        self.sink = sink

    @classmethod
    def factory(cls, sink):
        return lambda _db: cls(sink)

    def create_and_enqueue(self, *, type, tenant_id, payload):
        self.sink.append((type, payload))


# ── S0-12 schedule + S0-13 book without a feed row ──────────────────────────


def test_s0_12_the_scheduled_poll_fires_the_feed(db, monkeypatch):
    from modules.autocount.doc_feed import scheduler

    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    feed.next_poll_at = NOW - timedelta(minutes=1)
    db.commit()
    enqueued: List[Any] = []
    monkeypatch.setattr(scheduler, "JobService", _FakeJobs.factory(enqueued))
    out = scheduler.sweep_doc_feeds(db, now=NOW)
    assert out["fired"] == 1
    assert enqueued == [("autocount_doc_feed_run", {"feedId": feed.id, "kind": "poll"})]
    item = next(i for i in DocFeedService(db).view(co.tenant_id, co.id).feeds if i.feed == PR)
    assert item.nextPollAt is not None


def test_s0_13_an_allowed_book_without_a_feed_row_fails_loudly_and_others_run(db, monkeypatch, caplog):
    from app.config import settings
    from modules.autocount.doc_feed import scheduler

    from .s14_doc_feed_helpers import autocount_connection

    monkeypatch.setattr(settings, "autocount_project_registrations_feed_books", "db3,db4")
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    feed.next_poll_at = NOW - timedelta(minutes=1)
    db.commit()
    autocount_connection(db, base_url="https://autocount-wrapper.example.com/api/db4", name="open db4")
    monkeypatch.setattr(scheduler, "JobService", _FakeJobs.factory([]))
    with caplog.at_level(logging.ERROR, logger="foundryx.autocount"):
        out = scheduler.sweep_doc_feeds(db, now=NOW)
    assert out["fired"] == 1  # db3 still runs
    assert out["missingFeedBooks"] == 1
    assert any("db4" in r.getMessage() and "project registrations" in r.getMessage()
               for r in caplog.records)
    missing = DocFeedService(db).missing_feed_books(co.tenant_id, PR)
    assert missing == ["db4"]
