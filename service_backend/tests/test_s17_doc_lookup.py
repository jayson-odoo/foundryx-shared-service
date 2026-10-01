"""Sprint-5/17 (AC-DOC-FINDER) - find an AutoCount document by number.

UAC: documentation/plans/sprint-5/17-autocount-doc-finder-acceptance-criteria.md
Plan: documentation/plans/sprint-5/17-autocount-doc-finder.md

Red-first: written before ``modules/autocount/doc_lookup`` exists.

Vendor stubbing mirrors ``s16_do_pull_helpers.VendorStub``: the lookup resolves
its vendor through ``doc_feed.runner.resolve_vendor``, which builds
``HttpApiClient`` from the runner module's own import, so patching
``runner.HttpApiClient`` routes every read through an ``httpx.MockTransport``.
The stub here routes BOTH day doors of every registered doc type and records
the method of every request (the read-only kill test, AC-17-23).
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.doc_feed.clock import MYT, yyyymmdd
from modules.autocount.models import (
    AcDocFeed,
    AcDocFeedIssue,
    AcDocFeedLedger,
    AcDocFeedRun,
    AcPullSnapshot,
    AcPullSnapshotRow,
)

from .s14_doc_feed_helpers import (
    BOOK,
    auth_headers,
    limited_user,
    load_fixture,
    other_tenant,
)
from .s16_do_pull_helpers import add_feed, make_company, s16_isolation  # noqa: F401

BASE = "/autocount/doc-lookup"
BASE_PATH_PREFIX = "/api/db1"
DO_BY_DATE = "/deliveryorderbydocdate"
DO_BY_MOD = "/deliveryorderbyLastModified"
GRN_BY_DATE = "/goodsreceivenotebydocdate"
GRN_BY_MOD = "/goodsreceivenotebyLastModified"
DOC_NO = "PS202610-0004"


# ── dates ────────────────────────────────────────────────────────────────────


def today() -> date:
    return datetime.now(timezone.utc).astimezone(MYT).date()


def day(offset: int) -> date:
    return today() + timedelta(days=offset)


def iso_dt(d: date, time: str = "00:00:00") -> str:
    return f"{d.isoformat()}T{time}"


# ── records ──────────────────────────────────────────────────────────────────


def do_rec(
    doc_no: str = DOC_NO, *, doc_key: int = 55731, doc_date: date, modified: str,
    user: str = "AIN", cancelled: str = "F",
) -> Dict[str, Any]:
    rec = copy.deepcopy(load_fixture("do-vendor-day.json")[0])
    rec.update(
        DocKey=doc_key, DocNo=doc_no, DocDate=iso_dt(doc_date), LastModified=modified,
        LastModifiedUserID=user, Cancelled=cancelled,
    )
    for detail in rec["Details"]:
        detail["DocKey"] = doc_key
    return rec


# ── vendor stub (both doors, every method recorded) ──────────────────────────


Answer = Any  # list | httpx.Response | Exception


class DoorStub:
    """``routes[(path, yyyymmdd)] -> answer``; an unrouted (path, day) answers
    ``[]``. Any path not in ``known_paths`` raises (a wrong door is a test
    failure, never a silent empty day)."""

    def __init__(self, routes: Optional[Dict[Tuple[str, str], Answer]] = None,
                 known_paths=(DO_BY_DATE, DO_BY_MOD, GRN_BY_DATE, GRN_BY_MOD)) -> None:
        self.routes = routes or {}
        self.known_paths = set(known_paths)
        self.calls: List[Tuple[str, str, str]] = []  # (method, path, day)

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        rel = path[len(BASE_PATH_PREFIX):] if path.startswith(BASE_PATH_PREFIX) else path
        params = dict(request.url.params)
        day_param = params.get("DocDate") or params.get("lastModified") or ""
        self.calls.append((request.method, rel, day_param))
        if rel not in self.known_paths:
            raise AssertionError(f"unrouted vendor path {request.method} {request.url}")
        answer = self.routes.get((rel, day_param), [])
        if isinstance(answer, httpx.Response):
            return answer
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(200, json=answer)

    def install(self, monkeypatch) -> "DoorStub":
        import modules.autocount.doc_feed.runner as runner_module
        from modules.autocount.http_source.client import HttpApiClient as RealClient

        # A fresh inner client per connection - each lookup closes its own.
        monkeypatch.setattr(
            runner_module, "HttpApiClient",
            lambda base_url, **_kw: RealClient(
                base_url, transport=httpx.Client(transport=httpx.MockTransport(self.handler)),
            ),
        )
        return self

    @property
    def reads(self) -> List[Tuple[str, str]]:
        return [(p, d) for _m, p, d in self.calls]


# ── env ──────────────────────────────────────────────────────────────────────


def env(db, *, feeds=("delivery_orders",), tenant_id: str = DEFAULT_TENANT_ID):
    company, conn = make_company(db, tenant_id=tenant_id)
    for feed in feeds:
        add_feed(db, company, conn, feed=feed)
    return company, conn


def seed_snapshot(
    db, company, *, doc_no: str = DOC_NO, doc_date: date, modified: str,
    created_at: Optional[datetime] = None, status: str = "ready",
    entity_type: str = "delivery_orders", from_day: Optional[date] = None,
    to_day: Optional[date] = None, scope_doc_no: Optional[str] = None,
) -> AcPullSnapshot:
    created = created_at or datetime.now(timezone.utc) - timedelta(hours=2)
    snap = AcPullSnapshot(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=entity_type,
        company_code="SRT", status=status, record_count=1, complete=True,
        metadata_json={
            "fromDay": (from_day or doc_date).isoformat(),
            "toDay": (to_day or doc_date).isoformat(),
            "docNo": scope_doc_no,
        },
        created_at=created, extracted_at=created, expires_at=created + timedelta(hours=72),
    )
    db.add(snap)
    db.flush()
    rec = do_rec(doc_no, doc_date=doc_date, modified=modified)
    db.add(AcPullSnapshotRow(
        tenant_id=company.tenant_id, snapshot_id=snap.id, row_index=0,
        company_id=company.id, source_ref=f"{BOOK}:DO:{rec['DocKey']}", payload_json=rec,
    ))
    db.commit()
    return snap


def seed_ledger(db, company, *, doc_no: str = DOC_NO, doc_date: date,
                feed: str = "delivery_orders", doc_key: int = 55731) -> AcDocFeedLedger:
    row = AcDocFeedLedger(
        tenant_id=company.tenant_id, company_id=company.id, feed=feed, book=BOOK,
        doc_key=doc_key, doc_no=doc_no, doc_date=doc_date,
        source_modified_at=datetime.now(timezone.utc) - timedelta(days=1),
        last_outcome="created", pushed_at=datetime.now(timezone.utc) - timedelta(hours=20),
    )
    db.add(row)
    db.commit()
    return row


def start(client, headers, company, doc_no: str = DOC_NO, **extra):
    body = {"companyId": company.id, "docNo": doc_no}
    body.update(extra)
    return client.post(BASE, json=body, headers=headers)


def job(client, headers, job_id: str):
    return client.get(f"{BASE}/jobs/{job_id}", headers=headers)


def run_lookup(client, headers, company, doc_no: str = DOC_NO, **extra) -> Dict[str, Any]:
    """POST + poll once (eager jobs run inline) -> the finished job body."""
    response = start(client, headers, company, doc_no, **extra)
    assert response.status_code == 202, response.text
    body = job(client, headers, response.json()["jobId"])
    assert body.status_code == 200, body.text
    return body.json()


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def headers(client):
    return auth_headers(client)


# ── registry (AC-17-01..05) ──────────────────────────────────────────────────


def test_types_lists_registered_doc_types(client, headers):
    """AC-17-01"""
    response = client.get(f"{BASE}/types", headers=headers)
    assert response.status_code == 200, response.text
    by_key = {t["key"]: t for t in response.json()["data"]}
    assert {"delivery_order", "goods_receive_note"} <= set(by_key)
    do = by_key["delivery_order"]
    assert do["label"] == "Delivery order"
    assert "PS" in do["prefixes"] and "DO" in do["prefixes"]
    assert do["hasLastModified"] is True
    assert do["hasByDocNo"] is False


def test_registry_rejects_duplicate_key():
    """AC-17-03 - a duplicate registry key is a loud boot error."""
    from modules.autocount.doc_lookup.registry import (
        AcDocType,
        DocTypeRegistryError,
        register_doc_type,
    )

    with pytest.raises(DocTypeRegistryError):
        register_doc_type(AcDocType(
            key="delivery_order", label="dup", feed="delivery_orders",
            by_doc_date_path="/x",
        ))


def test_registry_drift_every_entry_points_at_a_known_feed():
    """AC-17-03"""
    from modules.autocount.doc_feed.constants import ALL_FEEDS
    from modules.autocount.doc_lookup.registry import all_doc_types

    for doc_type in all_doc_types():
        assert doc_type.feed in ALL_FEEDS, doc_type.key
        if doc_type.ledger_feed is not None:
            assert doc_type.ledger_feed in ALL_FEEDS, doc_type.key
        if doc_type.snapshot_entity_type is not None:
            assert doc_type.snapshot_entity_type == "delivery_orders", doc_type.key
        assert doc_type.by_doc_date_path.startswith("/"), doc_type.key


@pytest.mark.parametrize(
    "number, expected",
    [
        ("PS202610-0004", "delivery_order"),
        ("ps202610-0004", "delivery_order"),
        ("DO-2609/0201", "delivery_order"),
        ("GRN-0012", "goods_receive_note"),
        ("ZZ-1", "delivery_order"),
    ],
)
def test_detect_doc_type_by_prefix(number, expected):
    """AC-17-04"""
    from modules.autocount.doc_lookup.registry import detect_doc_type

    assert detect_doc_type(number).key == expected


def test_existing_feed_doors_unchanged():
    """AC-17-05 - the generic day read sends the SAME query strings the feed did."""
    from modules.autocount.doc_feed import constants

    assert constants.DO_BY_DOC_DATE_PATH == DO_BY_DATE
    assert constants.DO_BY_LAST_MODIFIED_PATH == DO_BY_MOD


def test_generic_doc_type_plugs_in_without_code_change(client, headers, db, monkeypatch):
    """AC-17-02 - a fake ``invoice`` entry (its own doors, number field and
    prefix) is found end to end through the same search code."""
    from modules.autocount.doc_lookup import registry

    fake = registry.AcDocType(
        key="invoice_test", label="Invoice (test)", feed="delivery_orders",
        by_doc_date_path="/invoicebydocdate", by_last_modified_path="/invoicebyLastModified",
        doc_no_field="InvNo", doc_no_prefixes=("IVT",),
    )
    monkeypatch.setitem(registry._REGISTRY, fake.key, fake)
    company, _conn = env(db)
    record = {"DocKey": 9, "InvNo": "IVT-0001", "DocDate": iso_dt(day(2)),
              "LastModified": iso_dt(today(), "08:00:00.000"), "Details": [{"Seq": 1}]}
    stub = DoorStub(
        {("/invoicebydocdate", yyyymmdd(day(2))): [record]},
        known_paths=("/invoicebydocdate", "/invoicebyLastModified"),
    ).install(monkeypatch)

    body = run_lookup(client, headers, company, "IVT-0001")
    result = body["result"]
    assert body["status"] == "done"
    assert result["docType"] == "invoice_test"
    assert result["found"] is True
    assert result["current"]["docNo"] == "IVT-0001"
    assert result["current"]["docDate"] == day(2).isoformat()
    assert result["foundBy"] == {"door": "by_doc_date", "day": day(2).isoformat()}
    assert all(path.startswith("/invoice") for path, _ in stub.reads)


# ── stored search (AC-17-06..09) ─────────────────────────────────────────────


def test_stored_finds_snapshot_sighting_case_insensitive(client, headers, db, monkeypatch):
    """AC-17-06 + AC-17-09"""
    company, _ = env(db)
    snap = seed_snapshot(db, company, doc_date=today(), modified=iso_dt(day(-1), "18:02:00"))
    stub = DoorStub().install(monkeypatch)

    response = client.get(
        f"{BASE}/stored",
        params={"companyId": company.id, "docNo": "  ps202610-0004 "},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["docType"] == "delivery_order"
    assert body["docNo"] == "ps202610-0004"  # trimmed input echo
    assert len(body["snapshots"]) == 1
    sighting = body["snapshots"][0]
    assert sighting["snapshotId"] == snap.id
    assert sighting["docDate"] == today().isoformat()
    assert sighting["lastModified"] == iso_dt(day(-1), "18:02:00")
    assert sighting["cancelled"] is False
    assert sighting["fromDay"] == today().isoformat()
    assert sighting["toDay"] == today().isoformat()
    assert stub.calls == []


def test_stored_returns_ledger_row(client, headers, db, monkeypatch):
    """AC-17-07"""
    company, _ = env(db)
    seed_ledger(db, company, doc_date=today())
    DoorStub().install(monkeypatch)

    body = client.get(
        f"{BASE}/stored", params={"companyId": company.id, "docNo": DOC_NO}, headers=headers,
    ).json()
    assert body["snapshots"] == []
    assert body["ledger"]["docDate"] == today().isoformat()
    assert body["ledger"]["docKey"] == 55731
    assert body["ledger"]["lastOutcome"] == "created"


def test_stored_ignores_other_company_other_tenant_and_unready(client, headers, db, monkeypatch):
    """AC-17-08"""
    company, _ = env(db)
    other_company, _ = make_company(db, code="OTH", database_name="AED_OTHER")
    seed_snapshot(db, other_company, doc_date=today(), modified=iso_dt(today()))
    seed_ledger(db, other_company, doc_date=today())
    seed_snapshot(db, company, doc_date=today(), modified=iso_dt(today()), status="building")

    tenant = other_tenant(db)
    foreign, _ = make_company(db, tenant_id=tenant, code="FRN", database_name="AED_FRN")
    seed_snapshot(db, foreign, doc_date=today(), modified=iso_dt(today()))
    DoorStub().install(monkeypatch)

    body = client.get(
        f"{BASE}/stored", params={"companyId": company.id, "docNo": DOC_NO}, headers=headers,
    ).json()
    assert body["snapshots"] == []
    assert body["ledger"] is None

    # another tenant's company id is a 404, never its data
    response = client.get(
        f"{BASE}/stored", params={"companyId": foreign.id, "docNo": DOC_NO}, headers=headers,
    )
    assert response.status_code == 404


# ── live search (AC-17-10..22) ───────────────────────────────────────────────


def test_redated_doc_found_by_last_modified(client, headers, db, monkeypatch):
    """AC-17-11 + AC-17-13 + AC-17-20 - the PS202610-0004 case."""
    company, _ = env(db)
    seed_snapshot(db, company, doc_date=today(), modified=iso_dt(day(-1), "18:02:00"))
    current = do_rec(doc_date=day(4), modified=iso_dt(today(), "07:39:22.000"))
    stub = DoorStub({(DO_BY_MOD, yyyymmdd(today())): [current]}).install(monkeypatch)

    body = run_lookup(client, headers, company)
    assert body["status"] == "done"
    result = body["result"]
    assert result["found"] is True
    assert result["foundBy"] == {"door": "by_last_modified", "day": today().isoformat()}
    cur = result["current"]
    assert cur["docNo"] == DOC_NO
    assert cur["docKey"] == 55731
    assert cur["docDate"] == day(4).isoformat()
    assert cur["lastModified"] == iso_dt(today(), "07:39:22.000")
    assert cur["lastModifiedBy"] == "AIN"
    assert cur["cancelled"] is False
    assert result["redated"] == {
        "from": today().isoformat(), "to": day(4).isoformat(), "source": "snapshot",
    }
    # header verbatim minus the lines field; lines verbatim
    assert "Details" not in cur["header"]
    assert cur["header"]["DebtorCode"] == current["DebtorCode"]
    assert cur["lines"] == current["Details"]
    # hint day (snapshot DocDate = today) first, then the hit - nothing after
    assert stub.reads == [
        (DO_BY_DATE, yyyymmdd(today())),
        (DO_BY_MOD, yyyymmdd(today())),
    ]
    statuses = [(s["door"], s["status"]) for s in result["steps"]]
    assert statuses[:2] == [("by_doc_date", "miss"), ("by_last_modified", "hit")]
    assert all(s["status"] == "skipped" for s in result["steps"][2:])


def test_step_plan_order_and_no_duplicates(client, headers, db, monkeypatch):
    """AC-17-10 + AC-17-16 - not found: every step a miss, windows echoed."""
    company, _ = env(db)
    stub = DoorStub().install(monkeypatch)

    body = run_lookup(client, headers, company, "PS202610-0099")
    result = body["result"]
    assert body["status"] == "done"
    assert result["found"] is False
    assert result["current"] is None
    steps = [(s["door"], s["day"]) for s in result["steps"]]
    expected = [("by_last_modified", day(-i).isoformat()) for i in range(0, 8)]
    expected += [("by_doc_date", day(i).isoformat()) for i in range(0, 15)]
    assert steps == expected
    assert len(set(steps)) == len(steps)
    assert all(s["status"] == "miss" for s in result["steps"])
    assert len(stub.calls) == len(expected)
    assert result["searched"] == {
        "lastModifiedFrom": day(-7).isoformat(), "lastModifiedTo": today().isoformat(),
        "docDateFrom": today().isoformat(), "docDateTo": day(14).isoformat(),
    }


def test_forward_dated_doc_found_by_doc_date(client, headers, db, monkeypatch):
    """AC-17-12"""
    company, _ = env(db)
    rec = do_rec(doc_date=day(9), modified=iso_dt(day(-20), "10:00:00.000"))
    DoorStub({(DO_BY_DATE, yyyymmdd(day(9))): [rec]}).install(monkeypatch)

    result = run_lookup(client, headers, company)["result"]
    assert result["found"] is True
    assert result["foundBy"] == {"door": "by_doc_date", "day": day(9).isoformat()}
    assert result["redated"] is None


def test_hit_saves_hint_and_next_lookup_is_one_read(client, headers, db, monkeypatch):
    """AC-17-14"""
    company, _ = env(db)
    rec = do_rec(doc_date=day(9), modified=iso_dt(day(-20), "10:00:00.000"))
    stub = DoorStub({(DO_BY_DATE, yyyymmdd(day(9))): [rec]}).install(monkeypatch)
    run_lookup(client, headers, company)

    stub.calls.clear()
    fresher = do_rec(doc_date=day(9), modified=iso_dt(day(-20), "10:00:00.000"), cancelled="T")
    stub.routes[(DO_BY_DATE, yyyymmdd(day(9)))] = [fresher]
    result = run_lookup(client, headers, company)["result"]
    assert stub.reads == [(DO_BY_DATE, yyyymmdd(day(9)))]
    assert result["current"]["cancelled"] is True  # live, never a cached copy


def test_stale_hint_falls_through_and_is_replaced(client, headers, db, monkeypatch):
    """AC-17-15"""
    company, _ = env(db)
    first = do_rec(doc_date=day(9), modified=iso_dt(day(-20), "10:00:00.000"))
    stub = DoorStub({(DO_BY_DATE, yyyymmdd(day(9))): [first]}).install(monkeypatch)
    run_lookup(client, headers, company)

    moved = do_rec(doc_date=day(3), modified=iso_dt(today(), "09:00:00.000"))
    stub.routes = {(DO_BY_MOD, yyyymmdd(today())): [moved]}
    result = run_lookup(client, headers, company)["result"]
    assert result["found"] is True
    assert result["current"]["docDate"] == day(3).isoformat()
    assert result["redated"]["from"] == day(9).isoformat()

    stub.calls.clear()
    stub.routes = {(DO_BY_DATE, yyyymmdd(day(3))): [moved]}
    run_lookup(client, headers, company)
    assert stub.reads == [(DO_BY_DATE, yyyymmdd(day(3)))]


def test_miss_writes_no_hint(client, headers, db, monkeypatch):
    """AC-17-16"""
    from modules.autocount.models import AcDocLookupHint

    company, _ = env(db)
    DoorStub().install(monkeypatch)
    run_lookup(client, headers, company, "PS202610-0099")
    assert db.query(AcDocLookupHint).count() == 0


def test_vendor_error_on_one_day_does_not_stop_the_scan(client, headers, db, monkeypatch):
    """AC-17-17"""
    company, _ = env(db)
    rec = do_rec(doc_date=day(-10), modified=iso_dt(day(-2), "11:00:00.000"))
    DoorStub({
        (DO_BY_MOD, yyyymmdd(day(-1))): httpx.Response(404, json={"Message": "nope"}),
        (DO_BY_MOD, yyyymmdd(day(-2))): [rec],
    }).install(monkeypatch)

    result = run_lookup(client, headers, company)["result"]
    assert result["found"] is True
    by_day = {(s["door"], s["day"]): s for s in result["steps"]}
    errored = by_day[("by_last_modified", day(-1).isoformat())]
    assert errored["status"] == "error"
    assert errored["error"]


def test_every_step_failing_fails_the_job(client, headers, db, monkeypatch):
    """AC-17-17"""
    company, _ = env(db)
    stub = DoorStub().install(monkeypatch)
    stub.routes = _AlwaysError()

    body = run_lookup(client, headers, company)
    assert body["status"] == "failed"
    assert body["error"]


class _AlwaysError(dict):
    def get(self, _key, _default=None):
        return httpx.Response(404, json={"Message": "No HTTP resource was found"})


def test_no_feed_connection_is_409(client, headers, db, monkeypatch):
    """AC-17-17"""
    company, _ = env(db, feeds=())
    DoorStub().install(monkeypatch)
    response = start(client, headers, company)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "NO_CONNECTION"


def test_reattach_and_in_flight(client, headers, db, monkeypatch):
    """AC-17-18 - with jobs deferred, the same lookup re-attaches; a
    different number for the same company is 409."""
    from app.jobs.service import JobService

    company, _ = env(db)
    DoorStub().install(monkeypatch)
    monkeypatch.setattr(JobService, "enqueue", lambda self, job_id: None)

    first = start(client, headers, company)
    again = start(client, headers, company, " ps202610-0004")
    other = start(client, headers, company, "PS202610-0005")
    assert first.status_code == 202
    assert again.status_code == 202
    assert again.json()["jobId"] == first.json()["jobId"]
    assert other.status_code == 409
    assert other.json()["detail"]["code"] == "LOOKUP_IN_FLIGHT"


def test_stop_aborts_at_next_step(client, headers, db, monkeypatch):
    """AC-17-19 - a stop committed mid-scan ends the job at the next step
    boundary (cooperative: the loop re-reads its own status)."""
    from app.models.background_job import JOB_ABORTED, BackgroundJob

    company, _ = env(db)
    stub = DoorStub().install(monkeypatch)
    original = stub.handler

    def handler(request):
        if len(stub.calls) == 2:
            db.query(BackgroundJob).filter(BackgroundJob.type == "autocount_doc_lookup").update(
                {"status": JOB_ABORTED}
            )
            db.commit()
        return original(request)

    stub.handler = handler
    import modules.autocount.doc_feed.runner as runner_module
    from modules.autocount.http_source.client import HttpApiClient as RealClient

    inner = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        runner_module, "HttpApiClient", lambda base_url, **_kw: RealClient(base_url, transport=inner)
    )

    body = run_lookup(client, headers, company, "PS202610-0099")
    assert body["status"] == "aborted"
    assert len(stub.calls) == 3


def test_stop_route_aborts_a_pending_job(client, headers, db, monkeypatch):
    """AC-17-19 - the route itself."""
    from app.jobs.service import JobService

    company, _ = env(db)
    DoorStub().install(monkeypatch)
    monkeypatch.setattr(JobService, "enqueue", lambda self, job_id: None)
    job_id = start(client, headers, company).json()["jobId"]

    response = client.post(f"{BASE}/jobs/{job_id}/stop", headers=headers)
    assert response.status_code == 200, response.text
    assert job(client, headers, job_id).json()["status"] == "aborted"


def test_windows_settings_and_around_day(client, headers, db, monkeypatch):
    """AC-17-21"""
    company, _ = env(db)
    stub = DoorStub().install(monkeypatch)

    got = client.get(f"{BASE}/settings", params={"companyId": company.id}, headers=headers)
    assert got.json() == {"companyId": company.id, "lastModifiedBackDays": 7, "docDateForwardDays": 14}

    too_big = client.put(
        f"{BASE}/settings",
        json={"companyId": company.id, "lastModifiedBackDays": 32, "docDateForwardDays": 1},
        headers=headers,
    )
    assert too_big.status_code == 422

    saved = client.put(
        f"{BASE}/settings",
        json={"companyId": company.id, "lastModifiedBackDays": 1, "docDateForwardDays": 2},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text

    around = day(-100)
    result = run_lookup(client, headers, company, "PS202610-0099", aroundDay=around.isoformat())["result"]
    steps = [(s["door"], s["day"]) for s in result["steps"]]
    hint_days = [around] + [around + timedelta(days=d) for k in (1, 2, 3) for d in (-k, k)]
    expected = [("by_doc_date", d.isoformat()) for d in hint_days]
    expected += [("by_last_modified", day(0).isoformat()), ("by_last_modified", day(-1).isoformat())]
    expected += [("by_doc_date", day(i).isoformat()) for i in (0, 1, 2)]
    assert steps == expected
    assert len(stub.calls) == len(expected)


def test_settings_put_needs_companies_manage(client, db, monkeypatch):
    """AC-17-21 - reading needs pull.read, saving needs companies.manage."""
    company, _ = env(db)
    limited_user(db, ["autocount.pull.read"], email="s17-reader@example.com")
    reader = auth_headers(client, "s17-reader@example.com", "limited1234")
    assert client.get(f"{BASE}/settings", params={"companyId": company.id}, headers=reader).status_code == 200
    response = client.put(
        f"{BASE}/settings",
        json={"companyId": company.id, "lastModifiedBackDays": 3, "docDateForwardDays": 3},
        headers=reader,
    )
    assert response.status_code == 403


def test_vendor_calls_are_activity_logged(client, headers, db, monkeypatch):
    """AC-17-22"""
    from app.models.integration_activity import IntegrationActivity as ActivityLog

    company, _ = env(db)
    DoorStub().install(monkeypatch)
    before = db.query(ActivityLog).count()
    run_lookup(client, headers, company, "PS202610-0099")
    assert db.query(ActivityLog).count() - before == 23


# ── read-only + security (AC-17-23..26) ─────────────────────────────────────


def _row_state(db) -> Dict[str, Any]:
    db.expire_all()
    feeds = db.query(AcDocFeed).all()
    return {
        "snapshots": db.query(AcPullSnapshot).count(),
        "snapshot_rows": db.query(AcPullSnapshotRow).count(),
        "ledger": [(r.doc_key, r.doc_date, r.pushed_at) for r in db.query(AcDocFeedLedger).all()],
        "issues": db.query(AcDocFeedIssue).count(),
        "runs": db.query(AcDocFeedRun).count(),
        "feeds": [(f.id, f.cursor_day, f.updated_at, f.last_poll_at, f.mode) for f in feeds],
    }


def test_kill_lookup_is_read_only(client, headers, db, monkeypatch):
    """AC-17-23 - only GETs leave the process; no snapshot / ledger / feed /
    cursor / issue / run row changes."""
    company, _ = env(db, feeds=("delivery_orders", "goods_receive_notes"))
    seed_snapshot(db, company, doc_date=today(), modified=iso_dt(day(-1)))
    seed_ledger(db, company, doc_date=today())
    current = do_rec(doc_date=day(4), modified=iso_dt(today(), "07:39:22.000"))
    stub = DoorStub({(DO_BY_MOD, yyyymmdd(day(-3))): [current]}).install(monkeypatch)
    before = _row_state(db)

    client.get(f"{BASE}/stored", params={"companyId": company.id, "docNo": DOC_NO}, headers=headers)
    run_lookup(client, headers, company)
    run_lookup(client, headers, company, "GRN-0001")

    assert stub.calls, "the lookup never reached the vendor - the kill test proves nothing"
    assert {method for method, _p, _d in stub.calls} == {"GET"}
    assert _row_state(db) == before


def test_kill_non_get_vendor_request_is_refused(monkeypatch):
    """AC-17-23 - the lookup's vendor reader refuses to send anything but a GET."""
    from modules.autocount.doc_lookup.reader import DocLookupReader, ReadOnlyViolation

    class _Client:
        def get(self, path, params):  # pragma: no cover - never reached
            raise AssertionError

        def post(self, *_a, **_k):  # pragma: no cover - never reached
            raise AssertionError("POST reached the vendor")

    reader = DocLookupReader(_Client())
    with pytest.raises(ReadOnlyViolation):
        reader.send("POST", "/deliveryorderbydocdate", {"DocDate": "20261001"})


def test_routes_need_pull_read(client, db, monkeypatch):
    """AC-17-24"""
    company, _ = env(db)
    DoorStub().install(monkeypatch)
    limited_user(db, ["autocount.companies.read"], email="s17-nopull@example.com")
    h = auth_headers(client, "s17-nopull@example.com", "limited1234")
    assert client.get(f"{BASE}/types", headers=h).status_code == 403
    assert client.get(
        f"{BASE}/stored", params={"companyId": company.id, "docNo": DOC_NO}, headers=h,
    ).status_code == 403
    assert start(client, h, company).status_code == 403


def test_routes_403_when_module_inactive(client, headers, db):
    """AC-17-24"""
    from app.models.module import MODULE_STATUS_INACTIVE, Module, TenantModule

    module = db.query(Module).filter(Module.name == "autocount").one()
    row = db.query(TenantModule).filter(
        TenantModule.tenant_id == DEFAULT_TENANT_ID, TenantModule.module_id == module.id,
    ).one()
    row.status = MODULE_STATUS_INACTIVE
    db.commit()
    response = client.get(f"{BASE}/types", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Module not installed"


@pytest.mark.parametrize(
    "doc_no, needle",
    [("", "docNo"), ("   ", "docNo"), ("A" * 65, "docNo"), ("PS\x00-1", "docNo")],
)
def test_doc_no_validation(client, headers, db, monkeypatch, doc_no, needle):
    """AC-17-25"""
    company, _ = env(db)
    DoorStub().install(monkeypatch)
    response = start(client, headers, company, doc_no)
    assert response.status_code == 422
    text = response.text
    assert needle in text
    if doc_no.strip():
        assert doc_no not in text


def test_unknown_doc_type_is_422(client, headers, db, monkeypatch):
    """AC-17-25"""
    company, _ = env(db)
    DoorStub().install(monkeypatch)
    response = start(client, headers, company, docType="purchase_order_nope")
    assert response.status_code == 422


def test_job_lookup_is_tenant_scoped(client, headers, db, monkeypatch):
    """AC-17-26 - another tenant's job id is 404; so is a foreign job type."""
    from app.jobs.service import JobService

    tenant = other_tenant(db)
    foreign = JobService(db).create(
        type="autocount_doc_lookup", tenant_id=tenant,
        payload={"companyId": "x", "docNo": DOC_NO, "docType": "delivery_order"},
    )
    assert job(client, headers, foreign.id).status_code == 404
    assert client.post(f"{BASE}/jobs/{foreign.id}/stop", headers=headers).status_code == 404

    other_type = JobService(db).create(type="autocount_doc_feed_run", tenant_id=DEFAULT_TENANT_ID)
    assert job(client, headers, other_type.id).status_code == 404
