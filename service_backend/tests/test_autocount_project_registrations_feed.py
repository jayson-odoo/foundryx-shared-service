"""Plan 72 (lane AUTOCOUNT-PROJECT-SYNC-SS, S0) - the ``project_registrations``
doc feed: AutoCount ``GET /ProjectRegbyDate?Date=yyyymmdd`` read per day and
pushed verbatim to the CRM's ``POST /external/ingest/project_registrations``.

Red first. Built on the existing doc feed (``modules/autocount/doc_feed``):
the same poll / re-check / backfill runner, the same ledger + issue tables.
Differences pinned here:

* identity is ``ProjNo`` (text, matched trimmed + case-insensitive), not a
  numeric ``DocKey``; ``source_ref`` = ``{book}:PROJREG:{ProjNo}``;
* the only vendor door is by date (``Date``), so the poll reads by date;
* contract gate 2.15 with ``project_registrations`` advertised;
* the backfill floor is 2006-01-01, a live backfill needs a finished dry run
  over the same days first, the dry run counts records by month, and one
  backfill per book is open at a time;
* reads only from the books in ``AUTOCOUNT_PROJECT_REGISTRATIONS_FEED_BOOKS``
  (default ``db3``, the test book; never db1 / db2 in the test period);
* no deletion step (AutoCount has no deletions door for registrations).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx
import pytest

from modules.autocount.doc_feed import constants as C
from modules.autocount.doc_feed.records import (
    dedupe_latest,
    doc_date,
    doc_key,
    source_ref,
)
from modules.autocount.doc_feed.runner import run_backfill, run_poll, run_sweep
from modules.autocount.models import (
    AcDocFeed,
    AcDocFeedBackfill,
    AcDocFeedLedger,
)
from modules.autocount.services.doc_feed_service import (
    DocFeedConflictError,
    DocFeedService,
    DocFeedValidationError,
)

from .s14_doc_feed_helpers import autocount_connection, company, sorento_connection

PR = "project_registrations"
DB3_URL = "https://autocount-wrapper.example.com/api/db3"
DB1_URL = "https://autocount-wrapper.example.com/api/db1"
NOW = datetime(2026, 11, 22, 4, 0, 0, tzinfo=timezone.utc)  # 12:00 MYT, 22/11/2026


@pytest.fixture
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


def _reg(proj_no: str, day: str, **extra: Any) -> Dict[str, Any]:
    out = {
        "ProjNo": proj_no, "ProjectTitle": "Title", "DistributorName": "D",
        "SalesAgent": "A", "CustomerName": "C", "Date": f"{day}T00:00:00",
        "TypeofBuilding": "", "State": "", "Mukim": "", "Developer": "",
        "Architect": "", "MainContractor": "", "Status": "Pending",
    }
    out.update(extra)
    return out


def _wired(db, *, base_url: str = DB3_URL):
    ac_conn = autocount_connection(db, base_url=base_url, name=f"open {base_url[-3:]}")
    crm_conn = sorento_connection(db)
    co = company(db, sink_connection=crm_conn, ac_connection=ac_conn)
    return co, ac_conn


def _feed(db, co, ac_conn, *, feed: str = PR, mode: str = "push", book: str = "db3",
          cursor_day=None) -> AcDocFeed:
    row = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed=feed, connection_id=ac_conn.id,
        book=book, mode=mode, cursor_day=cursor_day,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class _Vendor:
    """``/api/db3/ProjectRegbyDate`` answering per ``Date``; records every call."""

    def __init__(self, by_day: Dict[str, List[Dict[str, Any]]], *, fail_on: str = ""):
        self.by_day = by_day
        self.fail_on = fail_on
        self.calls: List[str] = []

    def transport(self) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/ProjectRegbyDate"), request.url
            assert "/api/db3/" in request.url.path, "reads must use the db3 book only"
            day = request.url.params.get("Date")
            assert day and len(day) == 8 and day.isdigit()
            self.calls.append(day)
            if day == self.fail_on:
                return httpx.Response(404, json={"message": "nope"})
            return httpx.Response(200, json=self.by_day.get(day, []))

        # HttpApiClient takes a full client (the house test seam).
        return httpx.Client(transport=httpx.MockTransport(handler))


class _Crm:
    """A fake CRM: the contract probe plus the ingest door."""

    def __init__(self, *, version: str = "2.15", entities=(PR,), outcome: str = "created"):
        self.version = version
        self.entities = list(entities)
        self.outcome = outcome
        self.pushes: List[Dict[str, Any]] = []
        self.other_paths: List[str] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/api/v1/external/contract":
                return httpx.Response(200, json={"version": self.version, "entities": self.entities})
            if path == f"/api/v1/external/ingest/{PR}":
                body = json.loads(request.content)
                body["_dry_run"] = request.url.params.get("dry_run") == "true"
                self.pushes.append(body)
                records = [
                    {"source_ref": f"db3:PROJREG:{r['ProjNo'].strip()}", "outcome": self.outcome}
                    for r in body["records"]
                ]
                return httpx.Response(200, json={"summary": {}, "records": records})
            self.other_paths.append(path)
            return httpx.Response(404, json={})

        return httpx.MockTransport(handler)


# ── constants + record identity ─────────────────────────────────────────────


def test_feed_kind_door_and_floor_are_pinned():
    assert C.FEED_PROJECT_REGISTRATIONS == PR
    assert PR in C.ALL_FEEDS and PR in C.DOCUMENT_FEEDS
    assert C.BY_DOC_DATE_PATH[PR] == "/ProjectRegbyDate"
    assert C.BY_DOC_DATE_PARAM[PR] == "Date"
    assert PR not in C.BY_LAST_MODIFIED_PATH
    assert C.backfill_floor(PR) == date(2006, 1, 1)
    assert C.backfill_floor(C.FEED_DELIVERY_ORDERS) == date.fromisoformat(C.BACKFILL_FROM_DEFAULT)


def test_projno_is_the_identity_trimmed_and_case_insensitive():
    a = doc_key(_reg("PPF26110001", "2026-11-21"), feed=PR)
    b = doc_key(_reg("  ppf26110001 ", "2026-11-21"), feed=PR)
    assert isinstance(a, int) and a > 0 and a < 2**63
    assert a == b
    assert doc_key(_reg("PPF26110002", "2026-11-21"), feed=PR) != a
    assert doc_key(_reg("   ", "2026-11-21"), feed=PR) is None
    assert doc_key({"Date": "2026-11-21"}, feed=PR) is None
    rec = _reg(" PPF/26/1 ", "2026-11-21")
    assert source_ref(PR, "db3", rec) == "db3:PROJREG:PPF/26/1"
    assert doc_date(rec, feed=PR) == date(2026, 11, 21)


def test_delivery_order_identity_is_untouched_by_a_projno_field():
    # AutoCount documents also carry a ProjNo; a DO without a DocKey stays keyless.
    assert doc_key({"ProjNo": "P1", "DocNo": "DO-1"}) is None
    assert doc_key({"DocKey": 7, "ProjNo": "P1"}) == 7


def test_dedupe_keeps_one_record_per_projno():
    rows = [_reg("P1", "2026-11-20", Status="Pending"), _reg("p1", "2026-11-21", Status="Won")]
    out = dedupe_latest(rows, feed=PR)
    assert len(out) == 1 and out[0]["Status"] == "Won"


def test_push_chunk_never_exceeds_1000_records():
    from app.config import SORENTO_MAX_BATCH

    assert SORENTO_MAX_BATCH <= 1000


# ── poll ────────────────────────────────────────────────────────────────────


def test_poll_reads_by_date_and_pushes_verbatim(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    rec = _reg("PPF26110001", "2026-11-21", ProjectTitle="line 1\nline 2")
    vendor = _Vendor({"20261121": [rec]})
    crm = _Crm()

    run = run_poll(db, feed, dry_run=False, now=NOW,
                   vendor_transport=vendor.transport(), sink_transport=crm.transport())

    assert run.outcome == "SUCCESS", run.error
    assert vendor.calls == ["20261121", "20261122"]  # yesterday .. today, oldest first
    assert len(crm.pushes) == 1
    pushed = crm.pushes[0]
    assert pushed["records"] == [rec]  # exactly as AutoCount returned it
    assert pushed["companyCode"] == "SRT" and pushed["book"] == "db3"
    assert "backfill" not in pushed
    ledger = db.query(AcDocFeedLedger).filter_by(feed=PR).all()
    assert len(ledger) == 1
    assert ledger[0].doc_no == "PPF26110001"
    assert ledger[0].doc_date == date(2026, 11, 21)
    assert ledger[0].doc_key == doc_key(rec, feed=PR)
    db.refresh(feed)
    assert feed.cursor_day == date(2026, 11, 22)
    assert crm.other_paths == []


def test_poll_refused_when_crm_contract_is_below_2_15(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    vendor = _Vendor({})
    run = run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=vendor.transport(),
                   sink_transport=_Crm(version="2.14").transport())
    assert run.outcome == "FAILED" and run.error_code == "CONTRACT_GATE"
    assert vendor.calls == []


def test_poll_refused_when_crm_does_not_advertise_the_feed(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    run = run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=_Vendor({}).transport(),
                   sink_transport=_Crm(entities=("delivery_orders",)).transport())
    assert run.error_code == "CONTRACT_GATE"


def test_poll_on_a_book_outside_the_allowlist_never_reads(db):
    co, ac_conn = _wired(db, base_url=DB1_URL)
    feed = _feed(db, co, ac_conn, book="db1")

    def boom(request):  # pragma: no cover - must never be called
        raise AssertionError("db1 must never be read")

    run = run_poll(db, feed, dry_run=False, now=NOW, vendor_transport=httpx.Client(transport=httpx.MockTransport(boom)),
                   sink_transport=_Crm().transport())
    assert run.outcome == "FAILED" and run.error_code == "BOOK_NOT_ALLOWED"


def test_window_basis_is_always_by_date_for_registrations(db):
    from modules.autocount.doc_feed.window import resolve_window

    assert resolve_window(None, feed=PR)["pollBasis"] == "doc_date"
    assert resolve_window({"pollBasis": "last_modified"}, feed=PR)["pollBasis"] == "doc_date"
    assert resolve_window(None)["pollBasis"] == "last_modified"


# ── re-check (sweep) ────────────────────────────────────────────────────────


def test_sweep_rechecks_by_content_and_has_no_deletion_step(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    rec = _reg("P1", "2026-11-21")
    crm = _Crm()
    run_poll(db, feed, dry_run=False, now=NOW,
             vendor_transport=_Vendor({"20261121": [rec]}).transport(),
             sink_transport=crm.transport())
    assert len(crm.pushes) == 1

    edited = dict(rec, Status="Won")
    crm2 = _Crm(outcome="updated")
    # P2 sat in the ledger but AutoCount no longer answers it: no deletion call.
    run = run_sweep(db, feed, dry_run=False, now=NOW,
                    vendor_transport=_Vendor({"20261121": [edited]}).transport(),
                    sink_transport=crm2.transport())
    assert run.outcome == "SUCCESS", run.error
    assert [p["records"] for p in crm2.pushes] == [[edited]]
    assert run.summary_json["changed"] == 1
    assert "candidates" not in run.summary_json
    assert crm2.other_paths == []

    crm3 = _Crm(outcome="unchanged")
    run = run_sweep(db, feed, dry_run=False, now=NOW,
                    vendor_transport=_Vendor({"20261121": [edited]}).transport(),
                    sink_transport=crm3.transport())
    assert crm3.pushes == [] and run.summary_json["changed"] == 0


# ── backfill ────────────────────────────────────────────────────────────────


def _backfill(db, feed, *, from_day, to_day, dry_run, status="running", next_day=None):
    row = AcDocFeedBackfill(
        tenant_id=feed.tenant_id, company_id=feed.company_id, feed_id=feed.id, feed=feed.feed,
        book=feed.book, dry_run=dry_run, from_day=from_day, to_day=to_day,
        next_day=next_day or from_day, status=status,
        days_total=(to_day - from_day).days + 1, days_done=0, started_at=NOW,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_dry_run_backfill_counts_by_month_and_writes_nothing(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2006, 1, 30), to_day=date(2006, 2, 2), dry_run=True)
    vendor = _Vendor({
        "20060130": [_reg("A1", "2006-01-30"), _reg("A2", "2006-01-30")],
        "20060201": [_reg("B1", "2006-02-01")],
    })
    crm = _Crm()
    run_backfill(db, bf, now=NOW, vendor_transport=vendor.transport(), sink_transport=crm.transport())

    db.refresh(bf)
    assert bf.status == "done"
    assert vendor.calls == ["20060130", "20060131", "20060201", "20060202"]  # one day per call, oldest first
    assert bf.summary_json["byMonth"] == {"2006-01": 2, "2006-02": 1}
    assert all(p["_dry_run"] for p in crm.pushes)
    assert db.query(AcDocFeedLedger).filter_by(feed=PR).count() == 0


def test_backfill_resumes_from_its_own_cursor(db):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    bf = _backfill(db, feed, from_day=date(2006, 1, 1), to_day=date(2006, 1, 4), dry_run=False)
    data = {"20060101": [_reg("A1", "2006-01-01")], "20060103": [_reg("C1", "2006-01-03")]}
    first = _Vendor(data, fail_on="20060103")
    crm = _Crm()
    run_backfill(db, bf, now=NOW, vendor_transport=first.transport(), sink_transport=crm.transport())
    db.refresh(bf)
    assert bf.status == "stopped"
    assert bf.next_day == date(2006, 1, 3)
    assert all(p.get("backfill") is True for p in crm.pushes)

    bf.status = "running"
    db.commit()
    second = _Vendor(data)
    run_backfill(db, bf, now=NOW, vendor_transport=second.transport(), sink_transport=crm.transport())
    db.refresh(bf)
    assert second.calls == ["20060103", "20060104"]  # never re-reads finished days
    assert bf.status == "done"
    db.refresh(feed)
    assert feed.full_backfill_done_at is not None
    assert db.query(AcDocFeedLedger).filter_by(feed=PR).count() == 2


def test_backfill_start_floor_is_2006(db, monkeypatch):
    co, ac_conn = _wired(db)
    _feed(db, co, ac_conn)
    service = DocFeedService(db)
    monkeypatch.setattr(service, "_dispatch", lambda *a, **k: None)
    with pytest.raises(DocFeedValidationError):
        service.start_backfill(co.tenant_id, co.id, PR, dry_run=True, from_day=date(2005, 12, 31))
    bf = service.start_backfill(co.tenant_id, co.id, PR, dry_run=True)
    assert bf.from_day == date(2006, 1, 1)


def test_live_backfill_needs_a_finished_dry_run_over_the_same_days(db, monkeypatch):
    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    service = DocFeedService(db)
    monkeypatch.setattr(service, "_dispatch", lambda *a, **k: None)
    with pytest.raises(DocFeedConflictError) as exc:
        service.start_backfill(co.tenant_id, co.id, PR, dry_run=False,
                               from_day=date(2006, 1, 1), to_day=date(2006, 12, 31))
    assert exc.value.code == "DRY_RUN_FIRST"

    _backfill(db, feed, from_day=date(2006, 1, 1), to_day=date(2006, 6, 30), dry_run=True, status="done")
    with pytest.raises(DocFeedConflictError):  # the dry run does not cover the whole range
        service.start_backfill(co.tenant_id, co.id, PR, dry_run=False,
                               from_day=date(2006, 1, 1), to_day=date(2006, 12, 31))
    bf = service.start_backfill(co.tenant_id, co.id, PR, dry_run=False,
                                from_day=date(2006, 1, 1), to_day=date(2006, 6, 30))
    assert bf.status == "running" and not bf.dry_run


def test_one_backfill_per_book_at_a_time(db, monkeypatch):
    co, ac_conn = _wired(db)
    _feed(db, co, ac_conn)
    do_feed = _feed(db, co, ac_conn, feed="delivery_orders")
    _backfill(db, do_feed, from_day=date(2019, 1, 1), to_day=date(2019, 1, 2), dry_run=True)
    service = DocFeedService(db)
    monkeypatch.setattr(service, "_dispatch", lambda *a, **k: None)
    with pytest.raises(DocFeedConflictError) as exc:
        service.start_backfill(co.tenant_id, co.id, PR, dry_run=True)
    assert exc.value.code == "BOOK_BUSY"


def test_scheduler_leaves_a_feed_alone_while_its_backfill_runs(db):
    from modules.autocount.doc_feed.scheduler import sweep_doc_feeds

    co, ac_conn = _wired(db)
    feed = _feed(db, co, ac_conn)
    feed.next_poll_at = NOW - timedelta(minutes=1)
    db.commit()
    _backfill(db, feed, from_day=date(2006, 1, 1), to_day=date(2006, 1, 2), dry_run=True)
    out = sweep_doc_feeds(db, now=NOW)
    assert out["fired"] == 0 and out["skipped"] == 1


def test_configure_refuses_a_book_outside_the_allowlist(db):
    from modules.autocount.services import company_service as cs

    co, ac_conn = _wired(db, base_url=DB1_URL)
    service = DocFeedService(db)
    service.company_service.doc_feed_gate_error = lambda *a, **k: None  # contract gate open
    with pytest.raises(DocFeedValidationError) as exc:
        service.update(co.tenant_id, co.id, PR, connection_id=ac_conn.id, mode="dry_run")
    assert exc.value.field == "connectionId"
    assert cs  # imported for monkeypatch-free gate stubbing above


def test_view_lists_the_feed_with_its_own_floor(db):
    co, _ = _wired(db)
    service = DocFeedService(db)
    service.company_service.doc_feed_gate_error = lambda *a, **k: None
    view = service.view(co.tenant_id, co.id)
    item = next(i for i in view.feeds if i.feed == PR)
    assert item.backfillFloor == date(2006, 1, 1)
    assert item.window.pollBasis == "doc_date"
