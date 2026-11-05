"""Plan 57 S6 (RED): the new gateway routes (AC-57-60..63).

The spec is `documentation/plans/sprint-5/57-autocount-write-qtso-contract.md`
(section numbers below refer to it). Routes run the REAL primitive / operation
services over the fake vendor through the FastAPI dependencies
``get_primitive_service`` and ``get_operation_service`` (new, in
``modules.autocount.write_back.deps``); the plan 55 dependency
``get_write_back_service`` is overridden with a real ``WriteBackService`` over the
same fake vendor. Error envelope = the plan 55 flat one (``code`` / ``message``);
an answer body carries ``errorCode``. ``code(r)`` reads whichever is present.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from app.main import app
from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcWriteAction
from modules.autocount.write_back.deps import get_write_back_service
from modules.autocount.write_back.service import WriteBackService
from tests.test_autocount_write_back_gateway import (
    OTHER_TENANT,
    _company,
    _hdr,
    _key,
    _other_tenant,
)
from tests.test_autocount_write_back_operations import (  # noqa: F401
    DEL_PO,
    PUT_PO,
    OpHarness,
    World,
    db,
    h,
)
from tests.test_autocount_write_back_primitives import _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

PREFIX = "/api/v1/autocount"
IDEM = {"Idempotency-Key": "gw-key-1"}
SLUG = {"QT": "quotations", "SO": "sales-orders", "PO": "purchase-orders", "SPO": "shipping-purchase-orders"}
HOST_BITS = ("ac.example.test", "api/db3")


def _deps():
    from modules.autocount.write_back import deps

    return deps.get_primitive_service, deps.get_operation_service


class Gw:
    """Gateway rig: OpHarness + company code SRT + a write_back key + overrides."""

    def __init__(self, h: OpHarness, db):
        self.h = h
        self.db = db
        h.company.sorento_company_code = "SRT"
        db.commit()
        row, plain = _key(db, [h.company.id], scopes=["write_back"])
        self.key, self.plain = row, plain
        get_prim, get_ops = _deps()
        app.dependency_overrides[get_prim] = lambda: h.service()
        app.dependency_overrides[get_ops] = lambda: h.ops()
        app.dependency_overrides[get_write_back_service] = lambda: WriteBackService(db, **h.factories())

    def hdr(self, idem: str = "gw-key-1", **extra) -> Dict[str, str]:
        out = _hdr(self.plain)
        if idem:
            out["Idempotency-Key"] = idem
        out.update(extra)
        return out


@pytest.fixture
def gw(h, db):
    h.delete_on()
    return Gw(h, db)


@pytest.fixture
def world(gw):
    return World(gw.h)


def code(r) -> str:
    body = r.json()
    return body.get("errorCode") or body.get("code")


def no_secret(r) -> None:
    for bit in HOST_BITS + ("app-secret-1", "pw-secret-9"):
        assert bit not in r.text


def create_body(kind="QT", **over) -> Dict[str, Any]:
    party = "creditorCode" if kind == "PO" else "debtorCode"
    body = {
        "companyCode": "SRT",
        "header": {party: "PARTY-1", "docDate": "2026-11-04", "displayTerm": "30 DAYS",
                   "currencyCode": "MYR", "currencyRate": 1, "ref": "r1"},
        "lines": [{"itemCode": "ITEM-1", "uom": "UNIT", "qty": 2, "unitPrice": 10.5, "location": "HQ",
                   "discount": "5%", "description": "first"}],
    }
    body.update(over)
    return body


# ---- AC-57-60: scope, auth, tenant / company only from the key --------------------------------

NEW_ROUTES = [
    ("post", f"{PREFIX}/documents/quotations", create_body()),
    ("patch", f"{PREFIX}/documents/sales-orders/1", {"companyCode": "SRT", "header": {"ref": "x"}}),
    ("post", f"{PREFIX}/documents/sales-orders/1/lines", {"companyCode": "SRT", "line": {}}),
    ("post", f"{PREFIX}/documents/sales-orders/1/lines/2/delete", {"companyCode": "SRT"}),
    ("post", f"{PREFIX}/documents/sales-orders/1/cancel", {"companyCode": "SRT"}),
    ("post", f"{PREFIX}/po-links/relink", {"companyCode": "SRT", "poDocKey": 1, "poDtlKey": 2, "soDocKey": 3, "soDtlKey": 4}),
    ("post", f"{PREFIX}/spo-links", {"companyCode": "SRT", "spoDocKey": 1, "spoDtlKey": 2, "poDocKey": 3, "poDtlKey": 4}),
    ("post", f"{PREFIX}/spo-links/relink", {"companyCode": "SRT", "spoDocKey": 1, "spoDtlKey": 2, "poDocKey": 3, "poDtlKey": 4}),
    ("post", f"{PREFIX}/write-operations/abc/resume", {"companyCode": "SRT"}),
]
READ_ROUTES = [
    ("get", f"{PREFIX}/write-operations/abc?companyCode=SRT"),
    ("get", f"{PREFIX}/write-capabilities?companyCode=SRT"),
]


@pytest.mark.parametrize("method,path,body", NEW_ROUTES)
def test_ac_57_60_pull_only_key_is_403_scope_required_and_nothing_is_sent(client, h, db, method, path, body):
    Gw(h, db)
    _row, plain = _key(db, [h.company.id])  # default scope: pull
    r = getattr(client, method)(path, json=body, headers={**_hdr(plain), **IDEM})
    assert r.status_code == 403 and code(r) == "SCOPE_REQUIRED", r.text
    h.no_http()


@pytest.mark.parametrize("method,path", READ_ROUTES)
def test_ac_57_60_read_routes_need_the_write_back_scope(client, h, db, method, path):
    Gw(h, db)
    _row, plain = _key(db, [h.company.id])
    r = getattr(client, method)(path, headers=_hdr(plain))
    assert r.status_code == 403 and code(r) == "SCOPE_REQUIRED", r.text


@pytest.mark.parametrize("method,path,body", NEW_ROUTES)
def test_ac_57_60_no_key_is_401(client, gw, method, path, body):
    assert getattr(client, method)(path, json=body, headers=IDEM).status_code == 401
    gw.h.no_http()


@pytest.mark.parametrize("method,path", READ_ROUTES)
def test_ac_57_60_read_routes_without_key_are_401(client, gw, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_ac_57_60_body_tenant_and_company_ids_are_ignored(client, gw):
    body = create_body(tenantId="evil", companyId="evil", tenant_id="evil")
    r = client.post(f"{PREFIX}/documents/quotations", json=body, headers=gw.hdr())
    assert r.status_code == 200, r.text
    row = gw.db.query(AcWriteAction).one()
    assert row.tenant_id == DEFAULT_TENANT_ID and row.company_id == gw.h.company.id and row.key_id == gw.key.id


def test_ac_57_60_unknown_company_code_is_404_and_nothing_is_sent(client, gw):
    r = client.post(f"{PREFIX}/documents/quotations", json=create_body(companyCode="NOPE"), headers=gw.hdr())
    assert r.status_code == 404
    gw.h.no_http()


def test_ac_57_60_other_tenants_company_is_unreachable_with_this_key(client, gw, db):
    _other_tenant(db)
    theirs = _company(db, OTHER_TENANT, code="THEIRS", database="AED_THEIRS")
    r = client.post(f"{PREFIX}/documents/quotations", json=create_body(companyCode="THEIRS"), headers=gw.hdr())
    assert r.status_code in (403, 404), r.text
    gw.h.no_http()
    assert theirs.id != gw.h.company.id


def test_ac_57_60_a_dockey_of_another_tenants_company_cannot_be_edited(client, gw, db):
    # same DocKey exists only in the OTHER tenant's staged data: this key must not see it
    _other_tenant(db)
    other = _company(db, OTHER_TENANT, code="SRT", database="AED_OTHER")
    gw.h.vendor.seed("SO", __import__("tests.autocount_write_back_fake_vendor", fromlist=["new_doc"]).new_doc(
        "SO", 8800, "SO-8800", "D", [_line()]))
    r = client.patch(f"{PREFIX}/documents/sales-orders/8800",
                     json={"companyCode": "SRT", "header": {"ref": "x"}}, headers=gw.hdr())
    assert r.status_code in (404, 409), r.text  # DOC_UNKNOWN / DOC_DATE_REQUIRED, never an edit
    assert gw.h.vendor.writes() == []
    assert other.id != gw.h.company.id


# ---- AC-57-63 / 61: the route table -----------------------------------------------------------------

def _autocount_routes():
    """(path, [METHODS]) of every autocount route, read from the OpenAPI document."""
    return [(path, sorted(m.upper() for m in ops)) for path, ops in app.openapi()["paths"].items()
            if "/autocount/" in path]


def test_ac_57_04_no_route_can_delete_a_document():
    paths = _autocount_routes()
    for path, methods in paths:
        assert "DELETE" not in methods, (path, methods)
        if "/documents/" in path:
            tail = path.split("/documents/")[1]
            assert not tail.endswith("/delete") or "/lines/" in tail, path  # only the line delete
            assert not path.endswith("/documents/{kind}/{docKey}") or methods == ["PATCH"], (path, methods)
    assert not any(p.endswith("/delete") and "/lines/" not in p for p, _m in paths)


def test_ac_57_61_every_contract_route_exists():
    have = {(m, path) for path, methods in _autocount_routes() for m in methods}
    for method, path in [
        ("POST", f"{PREFIX}/documents/{{kind}}"),
        ("PATCH", f"{PREFIX}/documents/{{kind}}/{{docKey}}"),
        ("POST", f"{PREFIX}/documents/{{kind}}/{{docKey}}/lines"),
        ("POST", f"{PREFIX}/documents/{{kind}}/{{docKey}}/lines/{{dtlKey}}/delete"),
        ("POST", f"{PREFIX}/documents/{{kind}}/{{docKey}}/cancel"),
        ("POST", f"{PREFIX}/po-links"), ("POST", f"{PREFIX}/po-links/unlink"),
        ("POST", f"{PREFIX}/po-links/relink"), ("POST", f"{PREFIX}/spo-links"),
        ("POST", f"{PREFIX}/spo-links/unlink"), ("POST", f"{PREFIX}/spo-links/relink"),
        ("GET", f"{PREFIX}/write-operations/{{operationId}}"),
        ("POST", f"{PREFIX}/write-operations/{{operationId}}/resume"),
        ("GET", f"{PREFIX}/write-capabilities"),
    ]:
        assert (method, path) in have, (method, path)


# ---- AC-57-62: idempotency header rules (section 2) ---------------------------------------------------

@pytest.mark.parametrize("method,path,body", NEW_ROUTES[:8])
def test_ac_57_62_new_routes_require_the_idempotency_key(client, gw, method, path, body):
    r = getattr(client, method)(path, json=body, headers=_hdr(gw.plain))
    assert r.status_code == 422, r.text
    assert code(r) == "IDEMPOTENCY_KEY_REQUIRED"
    gw.h.no_http()


@pytest.mark.parametrize("bad", ["", "x" * 129, "line\nbreak"])
def test_ac_57_62_bad_idempotency_key_is_422(client, gw, bad):
    r = client.post(f"{PREFIX}/documents/quotations", json=create_body(),
                    headers={**_hdr(gw.plain), "Idempotency-Key": bad})
    assert r.status_code == 422
    gw.h.no_http()


def test_ac_57_62_replay_returns_the_stored_answer_without_http(client, gw):
    first = client.post(f"{PREFIX}/documents/quotations", json=create_body(), headers=gw.hdr())
    assert first.status_code == 200, first.text
    calls = len(gw.h.vendor.calls)
    second = client.post(f"{PREFIX}/documents/quotations", json=create_body(), headers=gw.hdr())
    assert second.status_code == 200 and len(gw.h.vendor.calls) == calls
    assert second.json()["actionId"] == first.json()["actionId"] and second.json()["docNo"] == first.json()["docNo"]
    assert len(gw.h.vendor.docs["QT"]) == 1


def test_ac_57_62_same_key_other_body_or_route_is_409_conflict(client, gw):
    client.post(f"{PREFIX}/documents/quotations", json=create_body(), headers=gw.hdr())
    other_body = create_body()
    other_body["lines"][0]["qty"] = 9
    r = client.post(f"{PREFIX}/documents/quotations", json=other_body, headers=gw.hdr())
    assert r.status_code == 409 and code(r) == "IDEMPOTENCY_CONFLICT"
    r = client.post(f"{PREFIX}/documents/sales-orders", json=create_body("SO"), headers=gw.hdr())
    assert r.status_code == 409 and code(r) == "IDEMPOTENCY_CONFLICT"
    assert len(gw.h.vendor.docs["QT"]) == 1 and gw.h.vendor.docs["SO"] == []


def test_ac_57_62_operation_replay_and_conflict(client, gw, world):
    body = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked, "soDocKey": 7002, "soDtlKey": world.so_b}
    first = client.post(f"{PREFIX}/po-links/relink", json=body, headers=gw.hdr())
    assert first.status_code == 200, first.text
    calls = len(gw.h.vendor.calls)
    again = client.post(f"{PREFIX}/po-links/relink", json=body, headers=gw.hdr())
    assert again.status_code == 200 and again.json()["operationId"] == first.json()["operationId"]
    assert len(gw.h.vendor.calls) == calls
    clash = client.post(f"{PREFIX}/po-links/relink", json={**body, "soDtlKey": world.so_a}, headers=gw.hdr())
    assert clash.status_code == 409 and code(clash) == "IDEMPOTENCY_CONFLICT"


def test_ac_57_62_plan_55_routes_keep_working_without_a_key_and_with_one(client, gw, world):
    body = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_free, "soDocKey": 7002,
            "soDtlKey": world.so_a, "qty": 2}
    r = client.post(f"{PREFIX}/po-links", json=body, headers=_hdr(gw.plain))  # no Idempotency-Key
    assert r.status_code == 200, r.text
    assert {"actionId", "outcome", "errorCode", "document"} <= set(r.json())
    assert r.json()["outcome"] == "done"


def test_ac_57_40_plan_55_split_link_accepts_an_idempotency_key(client, gw, world):
    body = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_free, "soDocKey": 7002,
            "soDtlKey": world.so_a, "qty": 2}
    first = client.post(f"{PREFIX}/po-links", json=body, headers=gw.hdr())
    calls = len(gw.h.vendor.calls)
    again = client.post(f"{PREFIX}/po-links", json=body, headers=gw.hdr())
    assert first.status_code == again.status_code == 200
    assert len(gw.h.vendor.calls) == calls


# ---- primitives through the routes ------------------------------------------------------------------------

def test_ac_57_12_create_quotation_maps_camel_to_vendor_fields(client, gw):
    r = client.post(f"{PREFIX}/documents/quotations", json=create_body(), headers=gw.hdr())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "done" and body["docNo"] == "QT-000001" and isinstance(body["docKey"], int)
    assert body["operationId"] is None and body["actionId"]
    assert body["errorCode"] is None and body["warnings"] == []
    assert len(body["document"]["Details"]) == 1
    sent = gw.h.vendor.writes()[0].body
    assert sent["DocNo"] == "<<New>>" and sent["DebtorCode"] == "PARTY-1" and sent["DisplayTerm"] == "30 DAYS"
    assert sent["Ref"] == "r1" and sent["CurrencyRate"] == 1
    line = sent["Details"][0]
    assert (line["ItemCode"], line["UOM"], line["Qty"], line["UnitPrice"], line["Location"], line["Discount"]) == (
        "ITEM-1", "UNIT", 2, 10.5, "HQ", "5%")
    no_secret(r)


@pytest.mark.parametrize("kind", ["SO", "PO"])
def test_ac_57_12_create_sales_and_purchase_orders(client, gw, kind):
    r = client.post(f"{PREFIX}/documents/{SLUG[kind]}", json=create_body(kind), headers=gw.hdr(f"k-{kind}"))
    assert r.status_code == 200, r.text
    assert r.json()["docNo"].startswith(kind + "-")
    party = "CreditorCode" if kind == "PO" else "DebtorCode"
    assert gw.h.vendor.writes()[0].body[party] == "PARTY-1"


def test_ac_57_13_create_with_explicit_doc_no(client, gw):
    body = create_body()
    body["header"]["docNo"] = "FXT-QT-1"
    r = client.post(f"{PREFIX}/documents/quotations", json=body, headers=gw.hdr())
    assert r.status_code == 200 and r.json()["docNo"] == "FXT-QT-1"


def test_ac_57_11_sales_order_line_from_quotation_warns(client, gw):
    body = create_body("SO")
    body["lines"][0]["fromQuotation"] = {"docNo": "QT-000009", "dtlKey": 555}
    r = client.post(f"{PREFIX}/documents/sales-orders", json=body, headers=gw.hdr())
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == ["QT_ROW_LINK_UNCONFIRMED"]
    line = gw.h.vendor.writes()[0].body["Details"][0]
    assert (line["FromDocType"], line["FromDocNo"], line["FromDocDtlKey"]) == ("QT", "QT-000009", 555)


def test_ac_57_11_from_quotation_only_on_sales_order_lines(client, gw):
    body = create_body("QT")
    body["lines"][0]["fromQuotation"] = {"docNo": "QT-1", "dtlKey": 1}
    r = client.post(f"{PREFIX}/documents/quotations", json=body, headers=gw.hdr())
    assert r.status_code == 422
    gw.h.no_http()


@pytest.mark.parametrize("missing", ["debtorCode", "docDate", "displayTerm", "currencyCode", "currencyRate"])
def test_ac_57_10_missing_header_field_is_422_field_required_naming_it(client, gw, missing):
    body = create_body()
    del body["header"][missing]
    r = client.post(f"{PREFIX}/documents/quotations", json=body, headers=gw.hdr())
    assert r.status_code == 422 and code(r) == "FIELD_REQUIRED", r.text
    assert missing in r.text
    gw.h.no_http()


def test_ac_57_10_missing_line_field_and_no_lines_are_422(client, gw):
    body = create_body()
    del body["lines"][0]["location"]
    r = client.post(f"{PREFIX}/documents/quotations", json=body, headers=gw.hdr())
    assert r.status_code == 422 and code(r) == "FIELD_REQUIRED" and "location" in r.text
    r = client.post(f"{PREFIX}/documents/quotations", json=create_body(lines=[]), headers=gw.hdr("k2"))
    assert r.status_code == 422 and code(r) == "FIELD_REQUIRED"
    gw.h.no_http()


@pytest.mark.parametrize("path,body", [
    ("documents/quotations", {"header": {}, "lines": []}),                       # no companyCode
    ("documents/quotations", {"companyCode": "SRT", "header": "x", "lines": []}),
    ("documents/not-a-kind", {"companyCode": "SRT", "header": {}, "lines": []}),
])
def test_ac_57_60_malformed_bodies_are_4xx_without_http(client, gw, path, body):
    r = client.post(f"{PREFIX}/{path}", json=body, headers=gw.hdr())
    assert r.status_code in (404, 422), r.text
    gw.h.no_http()


def _set_spo_qty(h, dtl_key, qty):
    """Set an SPO row's qty on the vendor and in the staged copy."""
    import copy as _copy

    from modules.autocount.models import AcStagedRecord

    next(r for r in h.vendor.rows("SPO", 7003) if r["DtlKey"] == dtl_key)["Qty"] = qty
    row = h.db.query(AcStagedRecord).filter(AcStagedRecord.source_ref == "AED_TEST:7003").one()
    raw = _copy.deepcopy(row.raw_json)
    next(r for r in raw["_lines"] if r["DtlKey"] == dtl_key)["Qty"] = qty
    row.raw_json = raw
    h.db.commit()


def _so(gw):
    doc = gw.h.seed_doc("SO", 5001, [_line("A", 10, 5.0), _line("B", 4, 6.0, "BR1")])
    return doc, [r["DtlKey"] for r in doc["Details"]]


def test_ac_57_14_edit_maps_allowlisted_fields_and_reads_back(client, gw):
    _doc, keys = _so(gw)
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr(), json={
        "companyCode": "SRT", "header": {"ref": "new ref", "remark1": "hello"},
        "lines": [{"dtlKey": keys[0], "qty": 8, "unitPrice": 5.5, "location": "HQ"}]})
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "done" and r.json()["document"]["Remark1"] == "hello"
    put = gw.h.vendor.writes()[0]
    assert put.body["Ref"] == "new ref" and put.body["Details"][0]["Qty"] == 8
    assert gw.h.vendor.rows("SO", 5001)[0]["UnitPrice"] == 5.5


@pytest.mark.parametrize("body,field", [
    ({"header": {"debtorCode": "OTHER"}}, "debtorCode"),
    ({"header": {"docNo": "X"}}, "docNo"),
    ({"header": {"cancelled": "T"}}, "cancelled"),
    ({"lines": [{"dtlKey": 1, "itemCode": "Z"}]}, "itemCode"),
    ({"lines": [{"dtlKey": 1, "fromDocType": "SO"}]}, "fromDocType"),
])
def test_ac_57_14_fields_outside_the_allowlist_are_422_field_not_editable(client, gw, body, field):
    _so(gw)
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr(),
                     json={"companyCode": "SRT", **body})
    assert r.status_code == 422 and code(r) == "FIELD_NOT_EDITABLE", r.text
    assert field in r.text
    gw.h.no_http()


def test_ac_57_14_a_change_autocount_ignores_is_502_mismatch_naming_the_field(client, gw):
    _so(gw)
    gw.h.vendor.ignored_fields = {"Remark1"}
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr(),
                     json={"companyCode": "SRT", "header": {"remark1": "x"}})
    assert r.status_code == 502 and r.json()["outcome"] == "mismatch"
    assert "Remark1" in r.text or "remark1" in r.text


def test_ac_57_18_stale_edit_is_409_doc_stale(client, gw):
    _so(gw)
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr(), json={
        "companyCode": "SRT", "header": {"ref": "x"}, "expectedLastModified": "1999-01-01T00:00:00.00"})
    assert r.status_code == 409 and code(r) == "DOC_STALE"
    assert gw.h.vendor.writes() == []


def test_ac_57_20_doc_date_is_forwarded_and_required_for_an_unstaged_document(client, gw):
    gw.h.seed_doc("QT", 6001, [_line("A", 1, 9.0)], stage=False)
    r = client.patch(f"{PREFIX}/documents/quotations/6001", headers=gw.hdr(),
                     json={"companyCode": "SRT", "header": {"ref": "x"}})
    assert r.status_code == 409 and code(r) == "DOC_DATE_REQUIRED"
    gw.h.no_http()
    ok = client.patch(f"{PREFIX}/documents/quotations/6001", headers=gw.hdr("k2"),
                      json={"companyCode": "SRT", "docDate": "2026-11-04", "header": {"ref": "x"}})
    assert ok.status_code == 200, ok.text
    bad = client.patch(f"{PREFIX}/documents/quotations/6001", headers=gw.hdr("k3"),
                       json={"companyCode": "SRT", "docDate": "2026-11-05", "header": {"ref": "y"}})
    assert bad.status_code == 409 and code(bad) == "DOC_NOT_FOUND"
    assert client.patch(f"{PREFIX}/documents/quotations/6001", headers=gw.hdr("k4"),
                        json={"companyCode": "SRT", "docDate": "04/11/2026", "header": {"ref": "y"}}).status_code == 422


def test_ac_57_15_add_line(client, gw):
    _so(gw)
    r = client.post(f"{PREFIX}/documents/sales-orders/5001/lines", headers=gw.hdr(), json={
        "companyCode": "SRT", "line": {"itemCode": "C", "uom": "UNIT", "qty": 1, "unitPrice": 3, "location": "HQ"}})
    assert r.status_code == 200, r.text
    assert len(r.json()["document"]["Details"]) == 3
    assert gw.h.vendor.writes()[0].body["Details"][0]["DtlKey"] == 0


def test_ac_57_03_delete_line_and_cancel_are_vendor_unsupported_409_when_off(client, h, db):
    gw = Gw(h, db)  # delete / cancel shipped off
    h.seed_doc("SO", 5001, [_line("A", 10, 5.0)])
    dtl = h.vendor.rows("SO", 5001)[0]["DtlKey"]
    r = client.post(f"{PREFIX}/documents/sales-orders/5001/lines/{dtl}/delete", headers=gw.hdr(),
                    json={"companyCode": "SRT"})
    assert r.status_code == 409 and code(r) == "VENDOR_UNSUPPORTED"
    r = client.post(f"{PREFIX}/documents/sales-orders/5001/cancel", headers=gw.hdr("k2"), json={"companyCode": "SRT"})
    assert r.status_code == 409 and code(r) == "VENDOR_UNSUPPORTED"
    h.no_http()


def test_ac_57_16_delete_line_route_when_the_flag_is_on(client, gw):
    gw.h.flag("SO", "delete_line", True)
    _doc, keys = _so(gw)
    r = client.post(f"{PREFIX}/documents/sales-orders/5001/lines/{keys[0]}/delete", headers=gw.hdr(),
                    json={"companyCode": "SRT"})
    assert r.status_code == 200, r.text
    assert [x["DtlKey"] for x in gw.h.vendor.rows("SO", 5001)] == [keys[1]]


# ---- status mapping (section 4) -------------------------------------------------------------------------------------

def test_ac_57_61_status_mapping_for_every_outcome(client, gw, world):
    # 202 pending_verification (leaves PO 7001 busy)
    gw.h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    r = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr("k-pending"),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked})
    assert r.status_code == 202 and r.json()["outcome"] == "pending_verification"
    # 409 DOC_BUSY: the timed-out operation still holds PO 7001
    r = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr("k-busy"),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked})
    assert r.status_code == 409 and code(r) == "DOC_BUSY"
    # 502 vendor_error
    _so(gw)
    gw.h.vendor.fail_next("PUT", "EditSalesOrderbydockey", 500, "kaput")
    r = client.patch(f"{PREFIX}/documents/sales-orders/5001", headers=gw.hdr("k-vendor"),
                     json={"companyCode": "SRT", "header": {"ref": "x"}})
    assert r.status_code == 502 and r.json()["outcome"] == "vendor_error"
    # 502 recovered, on its OWN document (PO 7101)
    link = dict(FromDocType="SO", FromDocNo="SO-7002", FromDocDtlKey=world.so_a, FromSODtlKey=world.so_a)
    doc = gw.h.seed_doc("PO", 7101, [_line("ITEM-A", 4, 5.0, "BR1", **link)])
    gw.h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "add failed")
    r = client.post(f"{PREFIX}/po-links/relink", headers=gw.hdr("k-recovered"), json={
        "companyCode": "SRT", "poDocKey": 7101, "poDtlKey": doc["Details"][0]["DtlKey"],
        "soDocKey": 7002, "soDtlKey": world.so_b})
    assert r.status_code == 502 and r.json()["outcome"] == "recovered", r.text


def test_ac_57_61_needs_attention_is_502_and_resume_is_available(client, gw, world):
    gw.h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "add failed")
    gw.h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "recovery failed")
    r = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr("k-na"),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked})
    assert r.status_code == 502 and r.json()["outcome"] == "needs_attention"
    op_id = r.json()["operationId"]
    got = client.get(f"{PREFIX}/write-operations/{op_id}?companyCode=SRT", headers=_hdr(gw.plain))
    assert got.status_code == 200 and got.json()["outcome"] == "needs_attention"
    assert got.json()["operationId"] == op_id
    resumed = client.post(f"{PREFIX}/write-operations/{op_id}/resume", headers=gw.hdr("k-resume"),
                          json={"companyCode": "SRT"})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["outcome"] in ("done", "recovered")


@pytest.mark.parametrize("code_,status", [("WRITE_DISABLED", 403), ("DOC_BUSY", 409), ("ROW_NOT_FOUND", 409),
                                           ("ROW_ALREADY_LINKED", 409)])
def test_ac_57_61_refusals_map_to_403_or_409(client, gw, world, code_, status):
    if code_ == "WRITE_DISABLED":
        gw.h.company.write_connection_id = None
        gw.db.commit()
        body = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked}
    elif code_ == "DOC_BUSY":
        gw.db.add(AcWriteAction(tenant_id=DEFAULT_TENANT_ID, company_id=gw.h.company.id, action="edit_doc",
                                doc_type="PO", doc_key=7001, outcome="in_flight", request_json={}))
        gw.db.commit()
        body = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked}
    elif code_ == "ROW_NOT_FOUND":
        body = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": 999999}
    else:
        body = {"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked,
                "soDocKey": 7002, "soDtlKey": world.so_a}
    path = "po-links/relink" if code_ == "ROW_ALREADY_LINKED" else "po-links/unlink"
    if code_ == "ROW_ALREADY_LINKED":
        path = "po-links/relink"  # relink to the same SO row is NO_CHANGE
        code_ = "NO_CHANGE"
    r = client.post(f"{PREFIX}/{path}", headers=gw.hdr(), json=body)
    assert r.status_code == status and code(r) == code_, r.text


# ---- operation routes -----------------------------------------------------------------------------------------------------

def test_ac_57_61_po_relink_route_answers_replaced_lines(client, gw, world):
    r = client.post(f"{PREFIX}/po-links/relink", headers=gw.hdr(), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked, "soDocKey": 7002, "soDtlKey": world.so_b})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "done" and body["operationId"] and body["actionId"] is None
    (pair,) = body["replacedLines"]
    assert pair["oldDtlKey"] == world.p_linked and pair["newDtlKey"] != pair["oldDtlKey"]
    assert body["docKey"] == 7001
    no_secret(r)


def test_ac_57_61_spo_link_and_relink_routes(client, gw, world):
    r = client.post(f"{PREFIX}/spo-links", headers=gw.hdr("a"), json={
        "companyCode": "SRT", "spoDocKey": 7003, "spoDtlKey": world.s_free, "poDocKey": 7001, "poDtlKey": world.p_other})
    assert r.status_code == 200, r.text
    r = client.post(f"{PREFIX}/spo-links/relink", headers=gw.hdr("b"), json={
        "companyCode": "SRT", "spoDocKey": 7003, "spoDtlKey": world.s_linked, "poDocKey": 7001,
        "poDtlKey": world.p_free})  # p_other is now taken by the row just linked (AC-57-32)
    assert r.status_code == 200, r.text
    assert r.json()["replacedLines"]


def test_ac_57_61_plan_55_unlink_routes_run_the_operations(client, gw, world):
    r = client.post(f"{PREFIX}/po-links/unlink", headers=_hdr(gw.plain),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked})
    assert r.status_code == 200 and r.json()["replacedLines"]
    r = client.post(f"{PREFIX}/spo-links/unlink", headers=gw.hdr("spo"),
                    json={"companyCode": "SRT", "spoDocKey": 7003, "spoDtlKey": world.s_linked})
    assert r.status_code == 200 and r.json()["replacedLines"]


def test_ac_57_32_plan_55_unlink_routes_are_vendor_unsupported_with_delete_off(client, h, db):
    gw = Gw(h, db)  # shipped flags: delete_line off
    world = World(h)
    for path, body in (("po-links/unlink", {"poDocKey": 7001, "poDtlKey": world.p_linked}),
                       ("spo-links/unlink", {"spoDocKey": 7003, "spoDtlKey": world.s_linked})):
        r = client.post(f"{PREFIX}/{path}", headers=_hdr(gw.plain), json={"companyCode": "SRT", **body})
        assert r.status_code == 409 and code(r) == "VENDOR_UNSUPPORTED", (path, r.text)
    h.no_http()


def test_ac_57_61_operation_read_is_tenant_and_key_scoped(client, gw, world, db):
    r = client.post(f"{PREFIX}/po-links/unlink", headers=gw.hdr(),
                    json={"companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked})
    op_id = r.json()["operationId"]
    assert client.get(f"{PREFIX}/write-operations/{op_id}?companyCode=SRT", headers=_hdr(gw.plain)).status_code == 200
    assert client.get(f"{PREFIX}/write-operations/nope?companyCode=SRT", headers=_hdr(gw.plain)).status_code == 404
    from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule

    _other_tenant(db)
    theirs = _company(db, OTHER_TENANT, code="OTH", database="AED_OTH")
    _row, plain = _key(db, [theirs.id], scopes=["write_back"], tenant_id=OTHER_TENANT)
    # a tenant without the module installed never reaches the lookup: shared auth says 403
    blocked = client.get(f"{PREFIX}/write-operations/{op_id}?companyCode=OTH", headers=_hdr(plain))
    assert blocked.status_code == 403 and code(blocked) == "SERVICE_NOT_ENABLED"
    module = db.query(Module).filter(Module.name == "autocount").one()
    db.add(TenantModule(tenant_id=OTHER_TENANT, module_id=module.id, status=MODULE_STATUS_ACTIVE,
                        installed_version="1.0.0"))
    db.commit()
    leak = client.get(f"{PREFIX}/write-operations/{op_id}?companyCode=OTH", headers=_hdr(plain))
    assert leak.status_code == 404
    assert op_id not in leak.text


def test_ac_57_61_resume_unknown_operation_is_404(client, gw):
    r = client.post(f"{PREFIX}/write-operations/nope/resume", headers=gw.hdr(), json={"companyCode": "SRT"})
    assert r.status_code == 404
    gw.h.no_http()


# ---- GET /write-capabilities -------------------------------------------------------------------------------------------------

def _caps(client, gw, **kw):
    r = client.get(f"{PREFIX}/write-capabilities?companyCode=SRT", headers=_hdr(gw.plain))
    assert r.status_code == 200, r.text
    body = r.json()
    items = body if isinstance(body, list) else body["capabilities"]
    short = {"quotations": "QT", "sales-orders": "SO", "purchase-orders": "PO", "shipping-purchase-orders": "SPO"}
    assert {i["kind"] for i in items} <= set(short), {i["kind"] for i in items}  # wire kind names only
    return {(i["op"], short[i["kind"]]): {**i, "kind": short[i["kind"]]} for i in items}


def test_ac_57_61_write_capabilities_lists_enabled_and_reason_codes(client, h, db):
    gw = Gw(h, db)  # shipped state: delete / cancel off, create / edit / add on
    caps = _caps(client, gw)
    assert caps[("create_doc", "QT")] == {"op": "create_doc", "kind": "QT", "enabled": True, "reasonCode": None}
    assert caps[("edit_doc", "SO")]["enabled"] is True
    for key in (("delete_line", "SO"), ("cancel_doc", "QT"), ("delete_line", "PO"), ("create_doc", "SPO")):
        assert caps[key]["enabled"] is False and caps[key]["reasonCode"] == "VENDOR_UNSUPPORTED", key
    assert ("delete_doc", "QT") not in caps or caps[("delete_doc", "QT")]["enabled"] is False
    for op in ("link_row", "unlink_row", "relink_row"):
        assert caps[(op, "PO")]["enabled"] is False and caps[(op, "PO")]["reasonCode"] == "VENDOR_UNSUPPORTED"
    for op in ("spo_link_row", "spo_unlink_row", "spo_relink_row"):
        assert caps[(op, "SPO")]["enabled"] is False
    h.no_http()


def test_ac_57_61_write_capabilities_follow_the_flags_at_call_time(client, h, db):
    gw = Gw(h, db)
    h.delete_on()
    caps = _caps(client, gw)
    assert caps[("delete_line", "PO")] == {"op": "delete_line", "kind": "PO", "enabled": True, "reasonCode": None}
    assert caps[("link_row", "PO")]["enabled"] is True and caps[("spo_link_row", "SPO")]["enabled"] is True


def test_ac_57_61_write_capabilities_unknown_company_404_and_write_disabled_company(client, gw):
    r = client.get(f"{PREFIX}/write-capabilities?companyCode=NOPE", headers=_hdr(gw.plain))
    assert r.status_code == 404
    gw.h.company.write_connection_id = None
    gw.db.commit()
    body = client.get(f"{PREFIX}/write-capabilities?companyCode=SRT", headers=_hdr(gw.plain))
    assert body.status_code == 200
    items = body.json() if isinstance(body.json(), list) else body.json()["capabilities"]
    assert items and all(i["enabled"] is False and i["reasonCode"] == "WRITE_DISABLED" for i in items)
    assert body.json()["book"] is None  # no write connection = no book SS would write to


def test_ss_writecap_book_names_the_book_ss_writes_to(client, gw):
    """SS-WRITECAP-BOOK: the CRM keys orders ``{book}:{DocKey}`` and must refuse an
    Update / Cancel whose book is not the one SS writes to for this company."""
    r = client.get(f"{PREFIX}/write-capabilities?companyCode=SRT", headers=_hdr(gw.plain))
    assert r.status_code == 200, r.text
    assert r.json()["book"] == "db3"


def test_ss_writecap_book_is_null_when_the_connection_names_a_refused_book(client, gw):
    from tests.test_autocount_write_back_service import DB1

    # DB1 shares the pinned allowed host, so the refusal comes from the BOOK, not the host.

    gw.h.company.write_connection_id = gw.h._connection(DB1, DEFAULT_TENANT_ID).id
    gw.db.commit()
    body = client.get(f"{PREFIX}/write-capabilities?companyCode=SRT", headers=_hdr(gw.plain)).json()
    assert body["book"] is None and "db1" not in str(body)  # a refused book is never named (AC-57-47)
    assert all(i["reasonCode"] == "WRITE_NOT_ALLOWED" for i in body["capabilities"])


# ---- hygiene -------------------------------------------------------------------------------------------------------------------

def test_ac_57_19_answers_and_error_bodies_never_hold_host_key_or_secrets(client, gw, world):
    r1 = client.post(f"{PREFIX}/documents/quotations", json=create_body(), headers=gw.hdr())
    gw.h.vendor.fail_next("PUT", "EditPurchaseOrderbydockey", 500, "boom")
    r2 = client.post(f"{PREFIX}/po-links/relink", headers=gw.hdr("k2"), json={
        "companyCode": "SRT", "poDocKey": 7001, "poDtlKey": world.p_linked, "soDocKey": 7002, "soDtlKey": world.so_b})
    r3 = client.post(f"{PREFIX}/documents/quotations", json=create_body(companyCode="NOPE"), headers=gw.hdr("k3"))
    for r in (r1, r2, r3):
        no_secret(r)
        assert gw.plain not in r.text
        assert r.headers.get("cache-control") == "no-store"


def test_ac_57_61_spo_link_then_relink_flow_stays_green_with_consistent_data(client, gw, world):
    r = client.post(f"{PREFIX}/spo-links", headers=gw.hdr("a"), json={
        "companyCode": "SRT", "spoDocKey": 7003, "spoDtlKey": world.s_free, "poDocKey": 7001,
        "poDtlKey": world.p_other})
    assert r.status_code == 200, r.text
    new_key = r.json()["replacedLines"][0]["newDtlKey"]
    r = client.post(f"{PREFIX}/spo-links/relink", headers=gw.hdr("b"), json={
        "companyCode": "SRT", "spoDocKey": 7003, "spoDtlKey": new_key, "poDocKey": 7001,
        "poDtlKey": world.p_free})
    assert r.status_code == 200, r.text
    moved = r.json()["replacedLines"][0]["newDtlKey"]
    row = next(x for x in gw.h.vendor.rows("SPO", 7003) if x["DtlKey"] == moved)
    assert row["FromDocDtlKey"] == world.p_free


def test_ac_57_32_spo_link_above_the_target_po_rows_outstanding_is_409(client, gw, world):
    gw.h.vendor.rows("SPO", 7003)  # keep the world alive
    _set_spo_qty(gw.h, world.s_free, 5)  # PO row p_other has 4
    r = client.post(f"{PREFIX}/spo-links", headers=gw.hdr(), json={
        "companyCode": "SRT", "spoDocKey": 7003, "spoDtlKey": world.s_free, "poDocKey": 7001,
        "poDtlKey": world.p_other})
    assert r.status_code == 409 and code(r) == "QTY_ABOVE_OUTSTANDING"
    assert gw.h.vendor.writes() == []


# ---- VENDOR_REFUSED through the gateway -----------------------------------------------------------------

CREDIT = "This account had violated the credit limit. You are not allow to save."


def test_ac_57_61_vendor_refused_is_502_with_the_code_and_autocount_message(client, gw):
    import json as _json

    gw.h.vendor.fail_next("POST", "NewQuotation", 500, _json.dumps(
        {"Message": "An error has occurred.", "ExceptionMessage": CREDIT,
         "ExceptionType": "System.Exception", "StackTrace": "at Foo.Bar() in C:\\src\\x.cs:line 9"}))
    r = client.post(f"{PREFIX}/documents/quotations", json=create_body(), headers=gw.hdr())
    assert r.status_code == 502, r.text
    body = r.json()
    assert body["outcome"] == "vendor_error" and body["errorCode"] == "VENDOR_REFUSED"
    assert CREDIT in body["message"]
    for bad in ("StackTrace", "ExceptionType", "System.Exception", "x.cs"):
        assert bad not in r.text
    no_secret(r)
