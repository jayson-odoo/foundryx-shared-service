"""SS-AC-BLANK-MASTER-REF B6: ``GET /api/v1/autocount/documents/{kind}/{docKey}``.

CRM #2173 reads a quotation / sales order before it edits one (the update flow
needs ``LastModified`` and the row keys) and got 405: SS only had POST / PATCH on
that path. The read goes through the same frame as the write routes (``X-API-Key``,
``write_back`` scope, company from the key, the db3 write guard) and answers the
primitive envelope with ``document`` = the fresh AutoCount read. It never writes.
"""

from __future__ import annotations

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcWriteAction
from tests.test_autocount_write_back_gateway import _hdr, _key
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw, code, gw, no_secret  # noqa: F401
from tests.test_autocount_write_back_operations import db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

SLUGS = {
    "QT": ("quotations", "qt"), "SO": ("sales-orders", "so"),
    "PO": ("purchase-orders", "po"), "SPO": ("shipping-purchase-orders", "spo"),
}
KEYS = {"QT": 6101, "SO": 6201, "PO": 6301, "SPO": 6401}


def _seed(gw, kind, **kw):
    return gw.h.seed_doc(kind, KEYS[kind], [_line("A", 3, 7.5), _line("B", 2, 1.0, "BR1")], **kw)


def _get(client, gw, slug, doc_key, query="companyCode=SRT", headers=None):
    return client.get(f"{PREFIX}/documents/{slug}/{doc_key}?{query}",
                      headers=headers if headers is not None else _hdr(gw.plain))


@pytest.mark.parametrize("kind", ["QT", "SO", "PO", "SPO"])
@pytest.mark.parametrize("which", [0, 1])
def test_get_returns_the_fresh_document_in_the_primitive_envelope(client, gw, kind, which):
    doc = _seed(gw, kind)
    # a quotation is not staged: like PATCH, its date comes from the caller (or a past write)
    query = "companyCode=SRT&docDate=2026-11-04" if kind == "QT" else "companyCode=SRT"
    r = _get(client, gw, SLUGS[kind][which], KEYS[kind], query)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "done" and body["errorCode"] is None
    assert body["operationId"] is None and body["actionId"] is None
    assert body["docKey"] == KEYS[kind] and body["docNo"] == doc["DocNo"]
    got = body["document"]
    assert got["DocKey"] == KEYS[kind] and got["LastModified"] == doc["LastModified"]
    assert [d["DtlKey"] for d in got["Details"]] == [d["DtlKey"] for d in doc["Details"]]
    assert gw.h.vendor.writes() == []  # a read never writes
    assert gw.db.query(AcWriteAction).count() == 0  # and is not a write action
    no_secret(r)


def test_get_reads_fresh_not_staged(client, gw):
    _seed(gw, "SO")
    gw.h.vendor.rows("SO", KEYS["SO"])[0]["Qty"] = 99  # changed in AutoCount after staging
    r = _get(client, gw, "sales-orders", KEYS["SO"])
    assert r.json()["document"]["Details"][0]["Qty"] == 99


def test_get_route_exists_next_to_patch():
    from app.main import app

    paths = app.openapi()["paths"]
    assert set(paths[f"{PREFIX}/documents/{{kind}}/{{docKey}}"]) == {"get", "patch"}


def test_get_doc_date_from_the_query_for_an_unstaged_document(client, gw):
    _seed(gw, "QT", stage=False)
    r = _get(client, gw, "quotations", KEYS["QT"])
    assert r.status_code == 409 and code(r) == "DOC_DATE_REQUIRED"
    ok = _get(client, gw, "quotations", KEYS["QT"], "companyCode=SRT&docDate=2026-11-04")
    assert ok.status_code == 200, ok.text
    assert _get(client, gw, "quotations", KEYS["QT"], "companyCode=SRT&docDate=04/11/2026").status_code == 422


def test_get_unknown_doc_is_409_doc_not_found(client, gw):
    _seed(gw, "QT", stage=False)
    r = _get(client, gw, "quotations", KEYS["QT"], "companyCode=SRT&docDate=2026-11-05")
    assert r.status_code == 409 and code(r) == "DOC_NOT_FOUND"


def test_get_po_key_of_an_spo_is_doc_kind_mismatch(client, gw):
    _seed(gw, "SPO")
    r = _get(client, gw, "purchase-orders", KEYS["SPO"], "companyCode=SRT&docDate=2026-11-04")
    assert r.status_code == 409 and code(r) in ("DOC_KIND_MISMATCH", "DOC_NOT_FOUND")


def test_get_needs_the_write_back_scope(client, gw, db):
    _seed(gw, "SO")
    _row, plain = _key(db, [gw.h.company.id])  # pull scope only
    r = _get(client, gw, "sales-orders", KEYS["SO"], headers=_hdr(plain))
    assert r.status_code == 403 and code(r) == "SCOPE_REQUIRED"
    assert gw.h.vendor.calls == []


def test_get_without_key_is_401(client, gw):
    assert client.get(f"{PREFIX}/documents/sales-orders/1?companyCode=SRT").status_code == 401


def test_get_needs_company_code_and_a_known_kind_and_integer_key(client, gw):
    assert _get(client, gw, "sales-orders", 1, "").status_code == 422
    r = _get(client, gw, "invoices", 1)
    assert r.status_code == 404 and code(r) == "UNKNOWN_KIND"
    assert _get(client, gw, "sales-orders", "abc").status_code == 422
    assert gw.h.vendor.calls == []


def test_get_honours_the_db3_write_guard(client, gw):
    from tests.test_autocount_write_back_service import DB1

    _seed(gw, "SO")
    gw.h.company.write_connection_id = gw.h._connection(DB1, DEFAULT_TENANT_ID).id
    gw.db.commit()
    r = _get(client, gw, "sales-orders", KEYS["SO"])
    assert r.status_code == 403 and code(r) == "WRITE_NOT_ALLOWED"
    assert "db1" not in r.text
    assert gw.h.vendor.calls == []


def test_get_without_a_write_connection_is_403_write_disabled(client, gw):
    _seed(gw, "SO")
    gw.h.company.write_connection_id = None
    gw.db.commit()
    r = _get(client, gw, "sales-orders", KEYS["SO"])
    assert r.status_code == 403 and code(r) == "WRITE_DISABLED"
    assert gw.h.vendor.calls == []


def test_get_vendor_read_failure_is_502_read_failed(client, gw):
    _seed(gw, "SO")
    gw.h.vendor.fail_next("GET", "salesorderbydocdate", 500, "boom")
    r = _get(client, gw, "sales-orders", KEYS["SO"])
    assert code(r) == "READ_FAILED" and r.status_code in (409, 502), r.text
    no_secret(r)
