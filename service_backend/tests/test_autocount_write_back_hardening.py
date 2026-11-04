"""Plan 55 hardening batch (H1..H13), written red before the fixes.

Reuses the service harness (FakeAutoCount / Harness) and the gateway seeding
helpers. Every test seeds its own chain via the ``h`` / ``db`` fixtures.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcWriteAction
from modules.autocount.write_back import guard
from modules.autocount.write_back import payloads
from modules.autocount.write_back.client import AutoCountWriteClient, WriteTransportError
from modules.autocount.write_back.guard import WriteNotAllowed, assert_write_allowed
from modules.autocount.write_back.payloads import WriteRefusal
from modules.autocount.write_back.reader import AutoCountDocReader, DocReadError
from modules.autocount.write_back.repository import WriteActionRepository
from modules.autocount.write_back.service import WriteBackService
from app.services.url_guard import UrlGuardError
from tests.test_autocount_write_back_gateway import (
    LINK,
    LINK_BODY,
    PREFIX,
    SPO_UNLINK,
    UNLINK,
    Spy,
    _company as gw_company,
    _hdr,
    _key,
    _no_action_rows,
    _real_service,
    _stage as gw_stage,
    _use,
)
from tests.test_autocount_write_back_service import (  # noqa: F401  (fixtures)
    DB1,
    DB3,
    DBNAME,
    OTHER_TENANT,
    Harness,
    _load,
    db,
    h,
)
from tests.write_back_host_pin import (  # noqa: F401
    TEST_HOST_SHA256,
    pin_test_write_host,
)
from tests.write_back_caps import vendor_caps_all_on  # noqa: F401

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _reset_overrides():
    from app.main import app

    yield
    app.dependency_overrides.clear()


# ---- H1 AC-55-44: staged lookup is tenant + company scoped -----------------------------

def _drop_staged(h, entity):
    from modules.autocount.models import AcStagedRecord

    h.db.query(AcStagedRecord).filter(
        AcStagedRecord.company_id == h.company.id, AcStagedRecord.entity_type == entity
    ).delete()
    h.db.commit()


def test_h1_doc_staged_under_another_company_of_same_tenant_is_unknown(h):
    _drop_staged(h, "purchase_order")
    other = h._company(DEFAULT_TENANT_ID, h.conn.id, database="AED_OTHER_CO")
    h._stage("purchase_order", _load("po_202602_S0007.json"), company_id=other.id)
    res = h.link_split()
    assert res.outcome == "refused" and res.error_code == "DOC_UNKNOWN"
    h.no_http()


def test_h1_doc_staged_under_another_tenant_is_unknown(h):
    _drop_staged(h, "purchase_order")
    other_conn = h._connection(DB3, OTHER_TENANT)
    other = h._company(OTHER_TENANT, other_conn.id, database="AED_OTHER_T")
    h._stage(
        "purchase_order", _load("po_202602_S0007.json"), tenant_id=OTHER_TENANT, company_id=other.id
    )
    res = h.link_split()
    assert res.outcome == "refused" and res.error_code == "DOC_UNKNOWN"
    h.no_http()


# ---- H2 AC-55-26: DB-level busy lock -------------------------------------------------------

def test_h2_partial_unique_index_guards_one_in_flight_per_document():
    idx = [
        i for i in AcWriteAction.__table__.indexes
        if i.unique and [c.name for c in i.columns] == ["tenant_id", "company_id", "doc_key"]
    ]
    assert idx, "no unique index on (tenant_id, company_id, doc_key)"
    for dialect in ("sqlite", "postgresql"):
        where = idx[0].dialect_options[dialect]["where"]
        assert where is not None and "in_flight" in str(
            where.compile(compile_kwargs={"literal_binds": True})
        )


def test_h2_race_after_has_open_check_ends_doc_busy_without_put(h, monkeypatch):
    rival = AcWriteAction(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, action="link", doc_type="PO",
        doc_key=12008, dtl_key=12017, outcome="in_flight", request_json={},
    )
    h.db.add(rival)
    h.db.commit()
    monkeypatch.setattr(WriteActionRepository, "has_open", lambda self, *a, **k: False)
    res = h.link_split()
    assert res.outcome == "refused" and res.error_code == "DOC_BUSY"
    assert h.ac.put_calls == []
    h.db.expire_all()
    rows = h.db.query(AcWriteAction).filter(AcWriteAction.doc_key == 12008).all()
    assert sorted(r.outcome for r in rows) == ["in_flight", "refused"]


# ---- H3 stranded in_flight -----------------------------------------------------------------

class _BoomReader(AutoCountDocReader):
    """Raises RuntimeError on the n-th get_document call (1-based)."""

    def __init__(self, *a, boom_on: int, **k):
        super().__init__(*a, **k)
        self._boom_on = boom_on
        self._n = 0

    def get_document(self, *a, **k):
        self._n += 1
        if self._n == self._boom_on:
            raise RuntimeError("unexpected")
        return super().get_document(*a, **k)


def _svc_with_reader(h, boom_on):
    return WriteBackService(
        h.db,
        client_factory=lambda url: AutoCountWriteClient(url, transport=h.ac.write_transport),
        reader_factory=lambda url: _BoomReader(url, transport=h.ac.read_transport, boom_on=boom_on),
        sink_factory=lambda *a, **k: SimpleNamespace(
            name="fake", write=lambda *a, **k: None, push=lambda *a, **k: None
        ),
    )


def _row_for(h, doc_key=12008):
    h.db.expire_all()
    return (
        h.db.query(AcWriteAction)
        .filter(AcWriteAction.doc_key == doc_key)
        .order_by(AcWriteAction.created_at.desc())
        .first()
    )


def test_h3a_unexpected_error_after_put_is_pending_verification_internal_error(h):
    svc = _svc_with_reader(h, boom_on=3)  # PO read, SO read, then the read-back
    with suppress(Exception):
        svc.link(
            tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=12008,
            po_dtl_key=12017, so_doc_key=11988, so_dtl_key=11989, qty=Decimal(10),
        )
    assert len(h.ac.put_calls) == 1
    row = _row_for(h)
    assert row.outcome == "pending_verification" and row.error_code == "INTERNAL_ERROR"


def test_h3a_unexpected_error_before_put_never_leaves_in_flight(h):
    svc = _svc_with_reader(h, boom_on=1)
    with suppress(Exception):
        svc.link(
            tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=12008,
            po_dtl_key=12017, so_doc_key=11988, so_dtl_key=11989, qty=Decimal(10),
        )
    row = _row_for(h)
    assert row.outcome != "in_flight" and row.error_code == "INTERNAL_ERROR"


def test_h3b_reader_maps_url_guard_failure_to_read_failed(monkeypatch):
    def boom(*a, **k):
        raise UrlGuardError("blocked")

    monkeypatch.setattr("modules.autocount.write_back.reader.autocount_guarded_client", boom)
    reader = AutoCountDocReader(DB3)
    with pytest.raises(DocReadError) as exc:
        reader.get_document("PO", 12008, datetime(2026, 2, 1).date())
    assert exc.value.code == "READ_FAILED"


def test_h3b_reader_maps_invalid_url_to_read_failed():
    def handler(request):
        raise httpx.InvalidURL("bad")

    reader = AutoCountDocReader(DB3, transport=httpx.MockTransport(handler))
    with pytest.raises(DocReadError) as exc:
        reader.get_document("PO", 12008, datetime(2026, 2, 1).date())
    assert exc.value.code == "READ_FAILED"


def test_h3b_write_client_maps_url_guard_failure_to_write_connect(monkeypatch):
    def boom(*a, **k):
        raise UrlGuardError("blocked")

    monkeypatch.setattr("modules.autocount.write_back.client.autocount_guarded_client", boom)
    client = AutoCountWriteClient(DB3)
    with pytest.raises(WriteTransportError) as exc:
        client.put("/EditPurchaseOrderbydockey", {"DocKey": 1})
    assert exc.value.code == "WRITE_CONNECT"


def test_h3b_write_client_maps_invalid_url_to_write_connect():
    def handler(request):
        raise httpx.InvalidURL("bad")

    client = AutoCountWriteClient(DB3, transport=httpx.MockTransport(handler))
    with pytest.raises(WriteTransportError) as exc:
        client.put("/EditPurchaseOrderbydockey", {"DocKey": 1})
    assert exc.value.code == "WRITE_CONNECT"


def test_h3c_busy_window_constant_is_ten_minutes():
    from modules.autocount.write_back import service

    assert service.BUSY_WINDOW_SECONDS == 600


def _seed_row(h, outcome, age_seconds, doc_key=12008):
    created = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    row = AcWriteAction(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, action="link", doc_type="PO",
        doc_key=doc_key, dtl_key=12017, outcome=outcome, request_json={},
        created_at=created, updated_at=created,
    )
    h.db.add(row)
    h.db.commit()


def test_h3c_in_flight_older_than_busy_window_does_not_block(h):
    _seed_row(h, "in_flight", 700)
    res = h.link_split()
    assert res.outcome == "done", res.error_code


def test_h3c_in_flight_inside_busy_window_blocks(h):
    _seed_row(h, "in_flight", 60)
    res = h.link_split()
    assert res.outcome == "refused" and res.error_code == "DOC_BUSY"
    h.no_http()


def test_h3c_pending_verification_younger_than_window_blocks(h):
    _seed_row(h, "pending_verification", 60)
    res = h.link_split()
    assert res.outcome == "refused" and res.error_code == "DOC_BUSY"
    h.no_http()


# ---- H4 guard shape --------------------------------------------------------------------------

def test_h4_guard_accepts_exact_api_book_path_and_default_or_443_port():
    assert assert_write_allowed("https://ac.example.test/api/db3") == "db3"
    assert assert_write_allowed("https://ac.example.test/api/db3/") == "db3"
    assert assert_write_allowed("https://ac.example.test:443/api/db3") == "db3"


@pytest.mark.parametrize(
    "url",
    [
        "https://ac.example.test/api/db1/db3",
        "https://ac.example.test/x/api/db3",
        "https://ac.example.test/db3",
        "https://ac.example.test/api/db3/extra",
        "https://ac.example.test:8443/api/db3",
        "https://ac.example.test:444/api/db3",
        "https://ac.example.test:80/api/db3",
    ],
)
def test_h4_guard_requires_exact_api_book_path_and_port(url):
    with pytest.raises(WriteNotAllowed):
        assert_write_allowed(url)


def test_h4_guard_refuses_unknown_host_even_with_allowed_path():
    with pytest.raises(WriteNotAllowed):
        assert_write_allowed("https://other.example.test/api/db3")


def test_h4_host_allowlist_is_a_frozenset_of_sha256_hex():
    allowed = guard.ALLOWED_WRITE_HOST_SHA256
    assert isinstance(allowed, frozenset) and allowed
    assert all(len(v) == 64 and set(v) <= set("0123456789abcdef") for v in allowed)
    assert hashlib.sha256(b"ac.example.test").hexdigest() in allowed  # the test pin


def test_h4_host_allowlist_cannot_be_widened_from_env():
    evil = hashlib.sha256(b"evil.example.test").hexdigest()
    env = {
        **os.environ,
        "ALLOWED_WRITE_HOST_SHA256": evil,
        "WRITE_ALLOWED_HOSTS": "evil.example.test",
    }
    code = (
        "from modules.autocount.write_back import guard\n"
        f"print({evil!r} in guard.ALLOWED_WRITE_HOST_SHA256)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=str(BACKEND_DIR), env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stderr[-400:]
    assert out.stdout.strip().splitlines()[-1] == "False"


def _gw_stage_docs(db, company):
    gw_stage(db, company, "purchase_order", _load("po_202602_S0007.json"))
    gw_stage(db, company, "sales_order", _load("so_SO389293.json"))
    gw_stage(db, company, "shipping_order", _load("spo_db1_sample.json"))


# ---- H5 qty bounds ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "qty",
    [
        Decimal("1e-999999"), Decimal("0.000000001"), Decimal(0), Decimal(-1),
        Decimal("1000000001"),
    ],
)
def test_h5_payload_refuses_out_of_bounds_qty(qty):
    po, so = _load("po_202602_S0007.json"), _load("so_SO389293.json")
    with pytest.raises(WriteRefusal) as exc:
        payloads.build_link(po, 12017, so, 11989, qty)
    assert exc.value.code == "QTY_INVALID"


def test_h5_payload_quantizes_qty_to_eight_places():
    po, so = _load("po_202602_S0007.json"), _load("so_SO389293.json")
    body = payloads.build_link(po, 12017, so, 11989, Decimal("5.12345678"))
    assert [r["Qty"] for r in body["Details"]] == [44.87654322, 5.12345678]


@pytest.mark.parametrize("literal", ["1e-999999", "0.000000001", "0", "-1", "1000000001"])
def test_h5_gateway_qty_invalid_is_409_with_zero_vendor_requests(client, db, session_factory, literal):
    company = gw_company(db)
    _gw_stage_docs(db, company)
    _row, plain = _key(db, [company.id], scopes=["write_back"])
    service, fake = _real_service(db, session_factory)
    _use(service)
    body = json.dumps({**LINK_BODY, "qty": 0}).replace('"qty": 0', f'"qty": {literal}')
    r = client.post(
        LINK, content=body, headers={**_hdr(plain), "Content-Type": "application/json"}
    )
    assert r.status_code == 409, r.text
    assert "QTY_INVALID" in r.text
    assert fake.get_calls == [] and fake.put_calls == []


# ---- H6 gateway key ints ---------------------------------------------------------------------

_KEY_FIELDS = [
    (LINK, {**LINK_BODY}, "poDocKey"), (LINK, {**LINK_BODY}, "poDtlKey"),
    (LINK, {**LINK_BODY}, "soDocKey"), (LINK, {**LINK_BODY}, "soDtlKey"),
    (SPO_UNLINK, {"companyCode": "SRT", "spoDocKey": 1, "spoDtlKey": 2}, "spoDocKey"),
    (SPO_UNLINK, {"companyCode": "SRT", "spoDocKey": 1, "spoDtlKey": 2}, "spoDtlKey"),
]


@pytest.mark.parametrize("bad", ["0", "-5", str(2**63), "9" * 5000])
@pytest.mark.parametrize("path,base,field", _KEY_FIELDS)
def test_h6_out_of_range_key_is_422_and_no_service_call(client, db, path, base, field, bad):
    company = gw_company(db)
    _row, plain = _key(db, [company.id], scopes=["write_back"])
    spy = Spy()
    _use(spy)
    raw = json.dumps({**base, field: 1}).replace(f'"{field}": 1', f'"{field}": {bad}')
    r = client.post(path, content=raw, headers={**_hdr(plain), "Content-Type": "application/json"})
    assert r.status_code == 422, r.text[:300]
    assert spy.calls == []


@pytest.mark.parametrize("ok", ["1", str(2**63 - 1)])
def test_h6_bounds_are_inclusive(client, db, ok):
    company = gw_company(db)
    _row, plain = _key(db, [company.id], scopes=["write_back"])
    spy = Spy()
    _use(spy)
    raw = json.dumps({**LINK_BODY, "poDocKey": 1}).replace('"poDocKey": 1', f'"poDocKey": {ok}')
    r = client.post(LINK, content=raw, headers={**_hdr(plain), "Content-Type": "application/json"})
    assert r.status_code == 200, r.text[:300]


# ---- H7 pull scope on read routes ------------------------------------------------------------

_SNAP = {"companyCode": "SRT", "entity": "products"}


def _read_calls(client, plain):
    h = _hdr(plain)
    return [
        client.post(f"{PREFIX}/snapshots", json=_SNAP, headers=h),
        client.get(f"{PREFIX}/snapshots/does-not-exist", headers=h),
        client.get(f"{PREFIX}/snapshots/does-not-exist/rows", headers=h),
    ]


def test_h7_write_back_only_key_is_403_scope_required_on_read_routes(client, db):
    company = gw_company(db)
    _row, plain = _key(db, [company.id], scopes=["write_back"])
    for r in _read_calls(client, plain):
        assert r.status_code == 403, r.text
        assert "SCOPE_REQUIRED" in r.text


def test_h7_pull_key_still_reaches_read_routes(client, db):
    company = gw_company(db)
    _row, plain = _key(db, [company.id], scopes=["pull"])
    for r in _read_calls(client, plain):
        assert r.status_code != 401 and "SCOPE_REQUIRED" not in r.text


def test_h7_pull_and_write_back_key_works_on_both(client, db):
    company = gw_company(db)
    _row, plain = _key(db, [company.id], scopes=["pull", "write_back"])
    for r in _read_calls(client, plain):
        assert r.status_code != 401 and "SCOPE_REQUIRED" not in r.text
    spy = Spy()
    _use(spy)
    assert client.post(LINK, json=LINK_BODY, headers=_hdr(plain)).status_code == 200


# ---- H8 inactive company / connection --------------------------------------------------------

def test_h8_inactive_company_is_write_disabled_zero_http(h):
    h.company.is_active = False
    h.db.commit()
    res = h.link_split()
    assert res.outcome == "refused" and res.error_code == "WRITE_DISABLED"
    h.no_http()


def test_h8_inactive_write_connection_is_write_disabled_zero_http(h):
    h.conn.is_active = False
    h.db.commit()
    res = h.link_split()
    assert res.outcome == "refused" and res.error_code == "WRITE_DISABLED"
    h.no_http()


def test_h8_gateway_inactive_company_is_403(client, db, session_factory):
    company = gw_company(db)
    _gw_stage_docs(db, company)
    company.is_active = False
    db.commit()
    _row, plain = _key(db, [company.id], scopes=["write_back"])
    service, fake = _real_service(db, session_factory)
    _use(service)
    r = client.post(UNLINK, json={"companyCode": "SRT", "poDocKey": 12008, "poDtlKey": 12013},
                    headers=_hdr(plain))
    assert r.status_code == 403, r.text
    assert fake.get_calls == [] and fake.put_calls == []


def test_h8_gateway_inactive_write_connection_is_403(client, db, session_factory):
    from app.models.connection import Connection

    company = gw_company(db)
    _gw_stage_docs(db, company)
    db.query(Connection).filter(Connection.id == company.write_connection_id).update(
        {"is_active": False}
    )
    db.commit()
    _row, plain = _key(db, [company.id], scopes=["write_back"])
    service, fake = _real_service(db, session_factory)
    _use(service)
    r = client.post(UNLINK, json={"companyCode": "SRT", "poDocKey": 12008, "poDtlKey": 12013},
                    headers=_hdr(plain))
    assert r.status_code == 403, r.text
    assert fake.get_calls == [] and fake.put_calls == []


# ---- H9 header verify ------------------------------------------------------------------------

def test_h9_header_field_blanked_by_the_vendor_is_mismatch(h):
    original = h.ac._apply

    def apply_and_blank(body):
        original(body)
        for d in h.ac.docs["purchaseorderbydocdate"]:
            if d["DocKey"] == body["DocKey"]:
                d["DisplayTerm"] = ""

    h.ac._apply = apply_and_blank
    res = h.link_split()
    assert len(h.ac.put_calls) == 1
    assert res.outcome == "mismatch", res.outcome
    assert h.sink_calls == []


def test_h9_untouched_header_and_last_modified_change_stay_done(h):
    res = h.link_split()  # the fake bumps LastModified on PUT; header unchanged
    assert res.outcome == "done", res.error_code


def test_h9_spo_edit_sends_shipping_po_flag():
    spo = _load("spo_db1_sample.json")
    spo["Details"][0]["FromDocType"] = "PO"
    spo["Details"][0]["FromDocDtlKey"] = 12013
    body = payloads.build_spo_unlink(spo, spo["Details"][0]["DtlKey"])
    assert body["ShippingPO"] == "T"


def test_h9_spo_edit_through_service_puts_shipping_po_t(h, vendor_caps_all_on):
    spo = _load("spo_db1_sample.json")
    spo["Details"][0]["FromDocType"] = "PO"
    spo["Details"][0]["FromDocDtlKey"] = 12013
    h.stage_spo_pointing_at(12013)
    h.ac.serve("purchaseorderbydocdate", spo)
    h.service().spo_unlink(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, spo_doc_key=spo["DocKey"],
        spo_dtl_key=spo["Details"][0]["DtlKey"],
    )
    assert len(h.ac.put_bodies) == 1
    assert h.ac.put_bodies[0]["ShippingPO"] == "T"


# ---- H10 DOC_KIND_MISMATCH -------------------------------------------------------------------

def test_h10_po_dockey_sent_to_spo_unlink_is_kind_mismatch(h, vendor_caps_all_on):
    res = h.service().spo_unlink(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, spo_doc_key=12008, spo_dtl_key=12013
    )
    assert res.outcome == "refused" and res.error_code == "DOC_KIND_MISMATCH"
    assert h.ac.put_calls == []


def test_h10_spo_dockey_sent_to_unlink_is_kind_mismatch(h, vendor_caps_all_on):
    h.stage_spo_pointing_at(12013)
    spo = _load("spo_db1_sample.json")
    res = h.service().unlink(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=spo["DocKey"],
        po_dtl_key=spo["Details"][0]["DtlKey"],
    )
    assert res.outcome == "refused" and res.error_code == "DOC_KIND_MISMATCH"
    assert h.ac.put_calls == []


def test_h10_spo_dockey_sent_to_link_is_kind_mismatch(h):
    h.stage_spo_pointing_at(12013)
    spo = _load("spo_db1_sample.json")
    res = h.link_split(po_doc_key=spo["DocKey"], po_dtl_key=spo["Details"][0]["DtlKey"])
    assert res.outcome == "refused" and res.error_code == "DOC_KIND_MISMATCH"
    assert h.ac.put_calls == []


# ---- H11 no transaction while the sink writes ------------------------------------------------

def test_h11_no_transaction_open_while_the_sink_writes(h):
    seen = []

    def sink_factory(*a, **k):
        class _Sink:
            name = "fake"

            def write(self, record, *, request_id=""):
                seen.append(h.db.in_transaction())
                return None

            def push(self, *a, **k):
                seen.append(h.db.in_transaction())

        return _Sink()

    svc = WriteBackService(
        h.db,
        client_factory=lambda url: AutoCountWriteClient(url, transport=h.ac.write_transport),
        reader_factory=lambda url: AutoCountDocReader(url, transport=h.ac.read_transport),
        sink_factory=sink_factory,
    )
    res = svc.link(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=12008,
        po_dtl_key=12017, so_doc_key=11988, so_dtl_key=11989, qty=Decimal(10),
    )
    assert res.outcome == "done", res.error_code
    assert seen, "the sink was never called"
    assert not any(seen)


# ---- H12 set_write_connection ----------------------------------------------------------------

def _set(h, company, conn_id):
    from modules.autocount.write_back.service import set_write_connection

    return set_write_connection(
        h.db, tenant_id=company.tenant_id, company_id=company.id, connection_id=conn_id
    )


def _fresh_company(h):
    h.company.write_connection_id = None
    h.db.commit()
    return h.company


def _unchanged(h, company):
    h.db.expire_all()
    h.db.refresh(company)
    assert company.write_connection_id is None


def test_h12_sets_write_connection_for_same_tenant_autocount_db3(h):
    company = _fresh_company(h)
    conn = h._connection(DB3, DEFAULT_TENANT_ID)
    _set(h, company, conn.id)
    h.db.expire_all()
    h.db.refresh(company)
    assert company.write_connection_id == conn.id


def test_h12_refuses_other_tenants_connection(h):
    company = _fresh_company(h)
    other = h._connection(DB3, OTHER_TENANT)
    with pytest.raises(Exception) as exc:
        _set(h, company, other.id)
    assert getattr(exc.value, "code", None) in {"WRITE_NOT_ALLOWED", "CONNECTION_NOT_FOUND"}
    _unchanged(h, company)


def test_h12_refuses_non_autocount_provider(h):
    company = _fresh_company(h)
    conn = h._connection(DB3, DEFAULT_TENANT_ID)
    conn.provider = "smtp"
    h.db.commit()
    with pytest.raises(Exception) as exc:
        _set(h, company, conn.id)
    assert getattr(exc.value, "code", None) in {"WRITE_NOT_ALLOWED", "CONNECTION_NOT_FOUND"}
    _unchanged(h, company)


def test_h12_refuses_connection_outside_the_write_allowlist(h):
    company = _fresh_company(h)
    conn = h._connection(DB1, DEFAULT_TENANT_ID)
    with pytest.raises(Exception) as exc:
        _set(h, company, conn.id)
    assert getattr(exc.value, "code", None) in {"WRITE_NOT_ALLOWED", "CONNECTION_NOT_FOUND"}
    _unchanged(h, company)


def test_h12_refuses_unknown_connection_id(h):
    company = _fresh_company(h)
    with pytest.raises(Exception) as exc:
        _set(h, company, "no-such-connection")
    assert getattr(exc.value, "code", None) in {"WRITE_NOT_ALLOWED", "CONNECTION_NOT_FOUND"}
    _unchanged(h, company)


# ---- H13 AC-55-41: no relink route -----------------------------------------------------------

def test_h13_relink_route_does_not_exist(client, db):
    company = gw_company(db)
    _row, plain = _key(db, [company.id], scopes=["pull", "write_back"])
    r = client.post(f"{PREFIX}/po-links/relink", json=LINK_BODY, headers=_hdr(plain))
    assert r.status_code in (404, 405)
