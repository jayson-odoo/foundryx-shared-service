"""Plan 55 S4: wrapper day pull (AC-55-30, AC-55-31)."""

from __future__ import annotations

import copy
import json
from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.models import (
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    SOURCE_IMPL_SQL_DB,
    STAGED_PUSHED,
    AcCompany,
    AcEntityConfig,
    AcStagedRecord,
)
from modules.autocount.sinks import WriteResult
from modules.autocount.write_back.pull_docs import pull_documents
from modules.autocount.write_back.reader import AutoCountDocReader
from tests.test_autocount_write_back_service import DBNAME, _load

DB3 = "https://ac.example.test/api/db3"
SO_DAY = "20260126"
PO_DAY = "20260204"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


class FakeWrapper:
    def __init__(self, db):
        self.db = db
        self.requests: List[Tuple[str, str]] = []
        self.answers: Dict[Tuple[str, str], Any] = {}
        self.fail_day: Tuple[str, str] | None = None
        self.violations: List[str] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.db.in_transaction():
            self.violations.append("transaction open during GET")
        name = request.url.path.rsplit("/", 1)[-1].lower()
        param = "lastModified" if "lastmodified" in name else "DocDate"
        day = request.url.params[param]
        self.requests.append((name, day))
        if self.fail_day == (name, day):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=copy.deepcopy(self.answers.get((name, day), [])))


class Sink:
    name = "fake"

    def __init__(self):
        self.records: List[Any] = []

    def write(self, record, *, request_id=""):
        self.records.append(record)
        return WriteResult(ok=True, sink="fake", delivered=True, outcome="delivered")


def _so_doc():
    d = _load("so_SO389293.json")
    d.update(DebtorCode="300-C001", DebtorName="Example Customer", Cancelled="F")
    return d


def _setup(db, *, write=True, mode="last_modified", configs=True):
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="AC",
        config_json={"baseUrl": DB3, "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "a", "password": "p"}), is_active=True,
    )
    db.add(conn)
    db.commit()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DBNAME,
        company_name=DBNAME, name=DBNAME, is_active=True, sink_impl="logging",
        write_connection_id=conn.id if write else None,
    )
    db.add(company)
    db.commit()
    for entity in (("purchase_order", "shipping_order", "sales_order") if configs else ()):
        db.add(AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=entity,
            source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP, etl_status="active", delivery_mode="push",
            source_config={},
        ))
    db.commit()
    wrapper = FakeWrapper(db)
    if mode == "last_modified":
        so_name, po_name = "salesorderbylastmodified", "purchaseorderbylastmodified"
    else:
        so_name, po_name = "salesorderbydocdate", "purchaseorderbydocdate"
    wrapper.answers[(so_name, SO_DAY)] = [_so_doc()]
    wrapper.answers[(po_name, PO_DAY)] = [_load("po_202602_S0007.json")]
    sink = Sink()
    return SimpleNamespace(
        company=company, wrapper=wrapper, sink=sink, so_name=so_name, po_name=po_name,
    )


def _run(db, s, d_from=date(2026, 1, 26), d_to=date(2026, 2, 4), **kw):
    return pull_documents(
        db, tenant_id=DEFAULT_TENANT_ID, company_id=s.company.id, date_from=d_from, date_to=d_to,
        reader_factory=lambda url: AutoCountDocReader(url, transport=s.wrapper.transport),
        sink_factory=lambda *a, **k: s.sink, **kw,
    )


def _staged(db, entity):
    db.expire_all()
    return db.query(AcStagedRecord).filter(
        AcStagedRecord.company_id != None, AcStagedRecord.entity_type == entity  # noqa: E711
    ).all()


def test_ac_55_30_last_modified_mode_paths_and_params(db):
    s = _setup(db)
    _run(db, s)
    names = {n for n, _d in s.wrapper.requests}
    assert names == {"salesorderbylastmodified", "purchaseorderbylastmodified"}
    assert all(len(d) == 8 and d.isdigit() for _n, d in s.wrapper.requests)


def test_ac_55_30_doc_date_mode_paths_and_params(db):
    s = _setup(db, mode="doc_date")
    _run(db, s, mode="doc_date")
    assert {n for n, _d in s.wrapper.requests} == {"salesorderbydocdate", "purchaseorderbydocdate"}


def test_ac_55_31_all_so_days_first_then_all_po_days_inclusive(db):
    s = _setup(db)
    _run(db, s)
    reqs = s.wrapper.requests
    days = [f"202601{d}" for d in range(26, 32)] + [f"202602{d:02d}" for d in range(1, 5)]
    assert len(days) == 10
    assert reqs == [(s.so_name, d) for d in days] + [(s.po_name, d) for d in days]


def test_ac_55_30_stages_maps_and_pushes_each_doc(db):
    s = _setup(db)
    res = _run(db, s)
    assert (res.docs_seen, res.staged, res.pushed) == (2, 2, 2)
    assert not res.failed
    po = _staged(db, "purchase_order")
    assert len(po) == 1 and po[0].source_ref == f"{DBNAME}:12008"
    assert po[0].raw_json["_lines"][0]["DtlKey"] == 12009
    assert po[0].status == STAGED_PUSHED and po[0].canonical_json is not None
    assert len(_staged(db, "sales_order")) == 1
    assert len(s.sink.records) == 2


def test_ac_55_31_so_staged_first_so_po_line_refs_resolve(db):
    s = _setup(db)
    _run(db, s)
    po_rec = next(r for r in s.sink.records if getattr(r, "entity_type", "") == "purchase_order")
    line = next(l for l in po_rec.lines if l.source_ref.endswith(":12011"))
    assert line.from_so_line_ref == f"{DBNAME}:11988:11990"
    assert line.from_so_numbers == ["SO389293"]


def test_ac_55_30_unchanged_repull_is_not_pushed_again(db):
    s = _setup(db)
    _run(db, s)
    pushed_before = len(s.sink.records)
    again = _run(db, s)
    assert again.docs_seen == 2 and again.pushed == 0
    assert len(s.sink.records) == pushed_before
    assert len(_staged(db, "purchase_order")) == 1  # upsert by source_ref, never a second row


def test_ac_55_30_changed_repull_is_pushed_again(db):
    s = _setup(db)
    _run(db, s)
    changed = _load("po_202602_S0007.json")
    changed["Details"][0]["Qty"] = 2.0
    s.wrapper.answers[(s.po_name, PO_DAY)] = [changed]
    again = _run(db, s)
    assert again.pushed == 1


def test_ac_55_30_range_over_31_days_refused_with_zero_requests(db):
    s = _setup(db)
    with pytest.raises(Exception) as ei:
        _run(db, s, d_from=date(2026, 1, 1), d_to=date(2026, 2, 1))  # 32 days inclusive
    assert getattr(ei.value, "code", None) == "RANGE_TOO_LONG"
    assert s.wrapper.requests == []


def test_ac_55_30_range_of_exactly_31_days_is_allowed(db):
    s = _setup(db)
    _run(db, s, d_from=date(2026, 1, 1), d_to=date(2026, 1, 31))
    assert len(s.wrapper.requests) == 62


def test_ac_55_45_null_write_connection_is_write_disabled(db):
    s = _setup(db, write=False)
    with pytest.raises(Exception) as ei:
        _run(db, s)
    assert getattr(ei.value, "code", None) == "WRITE_DISABLED"
    assert s.wrapper.requests == []


def test_ac_55_30_failed_day_stops_the_run_keeps_earlier_docs(db):
    s = _setup(db)
    s.wrapper.fail_day = (s.so_name, "20260128")
    res = _run(db, s)
    assert res.failed
    assert s.wrapper.requests[-1] == (s.so_name, "20260128")
    assert (s.so_name, "20260129") not in s.wrapper.requests
    assert not any(n == s.po_name for n, _d in s.wrapper.requests)
    # the SO day before the failure was already staged and stays
    assert len(_staged(db, "sales_order")) == 1


def test_ac_55_27_no_transaction_open_during_any_get(db):
    s = _setup(db)
    _run(db, s)
    assert s.wrapper.violations == []
    assert len(s.wrapper.requests) == 20


def test_ac_55_30_company_without_entity_configs_pushes(db):
    s = _setup(db, configs=False)
    res = _run(db, s)
    assert (res.docs_seen, res.pushed) == (2, 2)
    assert len(s.sink.records) == 2


def test_ac_55_30_sql_sourced_po_config_skips_push_and_stays_staged(db):
    s = _setup(db, configs=False)
    db.add(AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=s.company.id, entity_type="purchase_order",
        source_impl=SOURCE_IMPL_SQL_DB, etl_status="active", delivery_mode="push", source_config={},
    ))
    db.commit()
    res = _run(db, s)
    assert res.pushed == 1  # only the sales order
    po = _staged(db, "purchase_order")
    assert len(po) == 1 and po[0].status == "STAGED" and po[0].canonical_json is None
