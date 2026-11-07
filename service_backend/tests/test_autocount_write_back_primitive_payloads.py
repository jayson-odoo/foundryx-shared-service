"""Plan 57 S2 red tests: level-1 builders, answer parser, verifiers (AC-57-10..18).

Contract assumed (plan 5.2): builders take a kind NAME ("QT"/"SO"/"PO"/"SPO") and
return ``VendorRequest(method, path, body)`` or raise ``WriteRefusal`` (``.code``).
``edit`` line changes = list of dicts ``{"DtlKey": n, <field>: v}``. Verifiers
return an object with ``.outcome`` ("done" | "mismatch"), ``.code`` and
``.warnings`` (list of codes); ``verify_edit`` returns the ignored field names.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from modules.autocount.write_back import payloads as P
from modules.autocount.write_back.payloads import WriteRefusal

FIX = Path(__file__).parent / "fixtures" / "autocount_write_back"


def _load(name):
    return json.loads((FIX / name).read_text())


QT_FIX = _load("qt_P-QT1.json")
SO_FIX = _load("so_P-SO0.json")


def qt_doc():
    return copy.deepcopy(QT_FIX["after"])


def so_doc():
    return copy.deepcopy(SO_FIX["after"])


def header(kind="QT"):
    h = {
        "DocDate": "2026-11-04T00:00:00",
        "DisplayTerm": "C.B.D.",
        "CurrencyCode": "MYR",
        "CurrencyRate": 1.0,
        "Ref": "R1",
    }
    h["CreditorCode" if kind in ("PO", "SPO") else "DebtorCode"] = "301-B018"
    return h


def line(**kw):
    base = {"ItemCode": "SRTKT38SS", "UOM": "UNIT", "Qty": 2, "UnitPrice": 126.0, "Location": "HQ"}
    base.update(kw)
    return base


def refusal(fn, *a, **k):
    with pytest.raises(WriteRefusal) as ei:
        fn(*a, **k)
    return ei.value


# ---- create (AC-57-10, 11, 13) -------------------------------------------------------


@pytest.mark.parametrize("kind,path", [("QT", "/NewQuotation"), ("SO", "/NewSalesOrder"), ("PO", "/NewPurchaseOrder")])
def test_ac_57_10_create_happy_shape(kind, path):
    req = P.build_create(kind, header(kind), [line()])
    assert req.method == "POST" and req.path == path
    assert req.body["Details"][0]["ItemCode"] == "SRTKT38SS"
    assert req.body["DocDate"] == "2026-11-04T00:00:00"


@pytest.mark.parametrize("kind", ["QT", "SO", "PO"])
@pytest.mark.parametrize("missing", ["DocDate", "DisplayTerm", "CurrencyCode", "CurrencyRate", "party"])
def test_ac_57_10_create_missing_header_field(kind, missing):
    h = header(kind)
    field = ("CreditorCode" if kind == "PO" else "DebtorCode") if missing == "party" else missing
    h.pop(field)
    err = refusal(P.build_create, kind, h, [line()])
    assert err.code == "FIELD_REQUIRED" and field in str(err)


def test_ac_57_10_create_wrong_party_field_for_kind():
    h = header("QT")  # DebtorCode on a PO is not a CreditorCode
    err = refusal(P.build_create, "PO", h, [line()])
    assert err.code == "FIELD_REQUIRED" and "CreditorCode" in str(err)


@pytest.mark.parametrize("lines", [[], None])
def test_ac_57_10_create_no_lines(lines):
    assert refusal(P.build_create, "QT", header(), lines).code == "FIELD_REQUIRED"


@pytest.mark.parametrize("missing", ["ItemCode", "UOM", "Qty", "UnitPrice", "Location"])
def test_ac_57_10_create_missing_line_field(missing):
    ln = line()
    ln.pop(missing)
    err = refusal(P.build_create, "QT", header(), [ln])
    assert err.code == "FIELD_REQUIRED" and missing in str(err)


@pytest.mark.parametrize("qty", [0, -1, Decimal("-0.5")])
def test_ac_57_10_create_qty_must_be_positive(qty):
    err = refusal(P.build_create, "QT", header(), [line(Qty=qty)])
    assert err.code == "FIELD_REQUIRED" and "Qty" in str(err)


def test_ac_57_10_create_negative_price_refused_zero_allowed():
    err = refusal(P.build_create, "QT", header(), [line(UnitPrice=-1)])
    assert err.code == "FIELD_REQUIRED" and "UnitPrice" in str(err)
    req = P.build_create("QT", header(), [line(UnitPrice=0)])
    assert req.body["Details"][0]["UnitPrice"] == 0


def test_ac_57_10_second_line_error_is_found():
    err = refusal(P.build_create, "QT", header(), [line(), line(Location="")])
    assert err.code == "FIELD_REQUIRED" and "Location" in str(err)


def test_ac_57_10_pre_1753_dates_never_sent():
    h = header()
    h["DocDate"] = "2026-11-04T00:00:00"
    req = P.build_create("QT", h, [line(DeliveryDate="0001-01-01T00:00:00")])
    assert "DeliveryDate" not in req.body["Details"][0]
    h["DocDate"] = "0001-01-01T00:00:00"
    # a pre-1753 required date counts as missing
    assert refusal(P.build_create, "QT", h, [line()]).code == "FIELD_REQUIRED"


def test_ac_57_13_docno_absent_sends_new_sentinel():
    req = P.build_create("QT", header(), [line()])
    assert req.body["DocNo"] == "<<New>>"


@pytest.mark.parametrize("docno", [None, ""])
def test_ac_57_13_docno_blank_sends_sentinel_never_omitted(docno):
    h = header()
    h["DocNo"] = docno
    assert P.build_create("SO", h, [line()]).body["DocNo"] == "<<New>>"


def test_ac_57_13_docno_given_is_kept():
    h = header()
    h["DocNo"] = "FXT-1"
    assert P.build_create("QT", h, [line()]).body["DocNo"] == "FXT-1"


def test_ac_57_13_auto_docno_off_requires_docno(monkeypatch):
    from modules.autocount.write_back import capabilities

    monkeypatch.setattr(capabilities, "AUTO_DOCNO", False, raising=True)
    assert refusal(P.build_create, "QT", header(), [line()]).code == "DOCNO_REQUIRED"
    h = header()
    h["DocNo"] = "X-1"
    assert P.build_create("QT", h, [line()]).body["DocNo"] == "X-1"


def test_ac_57_11_so_lines_carry_qt_link_as_given():
    ln = line(FromDocType="QT", FromDocNo="FXT-1104q-QT1", FromDocDtlKey=12061)
    d = P.build_create("SO", header("SO"), [ln]).body["Details"][0]
    assert (d["FromDocType"], d["FromDocNo"], d["FromDocDtlKey"]) == ("QT", "FXT-1104q-QT1", 12061)


def test_ac_57_10_real_p_qt1_request_is_reproducible():
    req_body = QT_FIX["request"]
    h = {k: v for k, v in req_body.items() if k != "Details"}
    out = P.build_create("QT", h, req_body["Details"])
    assert out.body["DebtorCode"] == "301-B018" and len(out.body["Details"]) == 2
    assert [d["Location"] for d in out.body["Details"]] == ["HQ", "BRW-AM"]


# ---- parse_create_answer (AC-57-12) --------------------------------------------------


def test_ac_57_12_parse_real_answer():
    assert P.parse_create_answer(QT_FIX["answer"]) == ("FXT-1104q-QT1", 12060)
    assert P.parse_create_answer("DocNo=QT-000001 ,DocKey=12069 ... Created Successful.") == ("QT-000001", 12069)


@pytest.mark.parametrize("junk", ["", "ok", None, {"DocKey": 1}, "DocNo=X ,DocKey=abc ... Created", "DocKey=5"])
def test_ac_57_12_parse_junk_is_none(junk):
    assert P.parse_create_answer(junk) is None


# ---- edit (AC-57-14) -----------------------------------------------------------------


def test_ac_57_14_edit_header_allowlist_only():
    err = refusal(P.build_edit, "QT", qt_doc(), {"DebtorCode": "X"}, [])
    assert err.code and err.code.isupper() and err.code != "FIELD_REQUIRED"
    assert refusal(P.build_edit, "QT", qt_doc(), {"Cancelled": "T"}, []).code == err.code
    assert refusal(P.build_edit, "QT", qt_doc(), {"NetTotal": 1}, []).code == err.code


@pytest.mark.parametrize("key", ["Ref", "Description", "Remark1", "Remark4", "DisplayTerm", "SalesAgent", "YourPONo", "InvAddr1", "DeliverAddr3"])
def test_ac_57_14_edit_allowlisted_headers_accepted(key):
    req = P.build_edit("QT", qt_doc(), {key: "NEW"}, [])
    assert req.method == "PUT" and req.path == "/EditQuotationbydockey"
    assert req.body[key] == "NEW"


def test_ac_57_14_edit_full_header_plus_changes_and_only_changed_rows():
    doc = qt_doc()
    keys = [r["DtlKey"] for r in doc["Details"]]
    req = P.build_edit("QT", doc, {"Ref": "NEW"}, [{"DtlKey": keys[0], "Qty": 3, "Discount": "5%"}])
    b = req.body
    assert b["DocKey"] == 12060 and b["DocNo"] == "FXT-1104q-QT1" and b["DebtorCode"] == "301-B018"
    assert b["Ref"] == "NEW" and b["Description"] == doc["Description"]
    assert [r["DtlKey"] for r in b["Details"]] == [keys[0]]
    assert b["Details"][0]["Qty"] == 3 and b["Details"][0]["Discount"] == "5%"
    assert b["Details"][0]["ItemCode"] == doc["Details"][0]["ItemCode"]


def test_ac_57_14_edit_line_fields_limited():
    d = qt_doc()
    k = d["Details"][0]["DtlKey"]
    for field in ("Qty", "UnitPrice", "Discount", "Location", "Description", "DeliveryDate"):
        val = "2026-11-05T00:00:00" if field == "DeliveryDate" else ("HQ" if field in ("Location", "Description", "Discount") else 4)
        assert P.build_edit("QT", d, {}, [{"DtlKey": k, field: val}]).body["Details"][0][field] == val
    for field in ("ItemCode", "UOM"):
        assert refusal(P.build_edit, "QT", d, {}, [{"DtlKey": k, field: "Z"}]).code


def test_ac_57_18_edit_unknown_dtlkey_row_not_found():
    assert refusal(P.build_edit, "QT", qt_doc(), {}, [{"DtlKey": 999999, "Qty": 1}]).code == "ROW_NOT_FOUND"


def test_ac_57_14_edit_qty_zero_or_negative_refused():
    d = qt_doc()
    k = d["Details"][0]["DtlKey"]
    assert refusal(P.build_edit, "QT", d, {}, [{"DtlKey": k, "Qty": -1}]).code
    assert refusal(P.build_edit, "QT", d, {}, [{"DtlKey": k, "UnitPrice": -1}]).code


def test_ac_57_14_edit_does_not_mutate_input():
    d = qt_doc()
    before = copy.deepcopy(d)
    P.build_edit("QT", d, {"Ref": "N"}, [{"DtlKey": d["Details"][0]["DtlKey"], "Qty": 9}])
    assert d == before


def test_ac_57_14_edit_so_and_spo_paths():
    assert P.build_edit("SO", so_doc(), {"Ref": "N"}, []).path == "/EditSalesOrderbydockey"
    spo = {"DocKey": 1, "DocNo": "S1", "ShippingPO": "T", "Cancelled": "F", "CreditorCode": "C1",
           "Details": [{"DtlKey": 5, "ItemCode": "A", "UOM": "U", "Qty": 1.0, "UnitPrice": 1.0, "Location": "HQ"}]}
    req = P.build_edit("SPO", spo, {"Ref": "N"}, [{"DtlKey": 5, "Qty": 2}])
    assert req.path == "/EditPurchaseOrderbydockey" and req.body["ShippingPO"] == "T"


# ---- add line (AC-57-15) -------------------------------------------------------------


def test_ac_57_15_add_line_single_dtlkey_zero_row():
    d = qt_doc()
    req = P.build_add_line("QT", d, line())
    assert req.method == "PUT" and req.path == "/EditQuotationbydockey"
    assert len(req.body["Details"]) == 1 and req.body["Details"][0]["DtlKey"] == 0
    assert req.body["DocKey"] == 12060


def test_ac_57_15_add_line_validates_line_fields():
    ln = line()
    ln.pop("Location")
    err = refusal(P.build_add_line, "QT", qt_doc(), ln)
    assert err.code == "FIELD_REQUIRED" and "Location" in str(err)
    assert refusal(P.build_add_line, "QT", qt_doc(), line(Qty=0)).code == "FIELD_REQUIRED"


# ---- delete line / doc / cancel (AC-57-16, 17, 18) -------------------------------------


@pytest.mark.parametrize("kind", ["QT", "SO", "PO", "SPO"])
def test_ac_57_16_delete_line_uses_kind_shape(kind):
    from modules.autocount.write_back import doc_kinds

    shape = doc_kinds.kind_of(kind).delete_line
    doc = qt_doc()
    if kind in ("PO", "SPO"):
        doc["ShippingPO"] = "T" if kind == "SPO" else "F"
    dtl = doc["Details"][0]["DtlKey"]
    req = P.build_delete_line(kind, doc, dtl)
    assert (req.method, req.path) == (shape.method, shape.path)
    assert req.body == {"DocKey": 12060, "DtlKey": dtl}


def test_ac_57_18_delete_line_unknown_row():
    assert refusal(P.build_delete_line, "QT", qt_doc(), 424242).code == "ROW_NOT_FOUND"


def test_ac_57_16_delete_doc_uses_kind_shape():
    from modules.autocount.write_back import doc_kinds

    shape = doc_kinds.kind_of("QT").delete_doc
    req = P.build_delete_doc("QT", qt_doc())
    assert (req.method, req.path) == (shape.method, shape.path)
    assert req.body["DocKey"] == 12060


def test_ac_57_17_cancel_body_is_edit_door_full_header_cancelled_t():
    d = qt_doc()
    req = P.build_cancel("QT", d)
    assert req.method == "PUT" and req.path == "/EditQuotationbydockey"
    assert req.body["Cancelled"] == "T"
    assert req.body["DocKey"] == 12060 and req.body["DebtorCode"] == "301-B018"
    assert req.body["DocNo"] == "FXT-1104q-QT1"


def test_ac_57_17_cancel_so_door():
    assert P.build_cancel("SO", so_doc()).path == "/EditSalesOrderbydockey"


def test_ac_57_18_cancelled_doc_refused_everywhere():
    d = qt_doc()
    d["Cancelled"] = "T"
    k = d["Details"][0]["DtlKey"]
    calls = [
        lambda: P.build_edit("QT", d, {"Ref": "x"}, []),
        lambda: P.build_add_line("QT", d, line()),
        lambda: P.build_delete_line("QT", d, k),
        lambda: P.build_cancel("QT", d),
        lambda: P.build_delete_doc("QT", d),
    ]
    for fn in calls:
        assert refusal(fn).code == "DOC_CANCELLED"


def test_ac_57_18_qt_with_target_document_cannot_cancel():
    d = qt_doc()
    d["ToDocType"] = "SO"
    assert refusal(P.build_cancel, "QT", d).code == "DOC_HAS_TRANSFERS"


def test_ac_57_18_qt_without_target_cancel_ok_control():
    d = qt_doc()
    d["ToDocType"] = ""
    assert P.build_cancel("QT", d).body["Cancelled"] == "T"


def test_ac_57_18_kind_mismatch():
    spo = {"DocKey": 1, "DocNo": "S1", "ShippingPO": "T", "Cancelled": "F", "Details": []}
    assert refusal(P.build_edit, "PO", spo, {"Ref": "x"}, []).code == "DOC_KIND_MISMATCH"


# ---- verifiers (AC-57-11, 12, 14, 16, 17) ----------------------------------------------


def _created(doc, sent_lines):
    return P.verify_create("QT", {"Details": sent_lines}, doc)


def test_ac_57_12_verify_create_happy():
    sent = [{k: r[k] for k in ("ItemCode", "UOM", "Qty", "UnitPrice", "Location")} for r in qt_doc()["Details"]]
    res = _created(qt_doc(), sent)
    assert res.outcome == "done" and not res.warnings


def test_ac_57_12_verify_create_dropped_line_is_rows_dropped():
    sent = [{k: r[k] for k in ("ItemCode", "UOM", "Qty", "UnitPrice", "Location")} for r in qt_doc()["Details"]]
    doc = qt_doc()
    doc["Details"].pop()
    res = _created(doc, sent)
    assert res.outcome == "mismatch" and res.code == "ROWS_DROPPED"


def test_ac_57_12_verify_create_value_mismatch_not_done():
    sent = [{k: r[k] for k in ("ItemCode", "UOM", "Qty", "UnitPrice", "Location")} for r in qt_doc()["Details"]]
    doc = qt_doc()
    doc["Details"][0]["Qty"] = Decimal("7")
    assert _created(doc, sent).outcome == "mismatch"


def test_ac_57_12_verify_create_extra_line_is_mismatch():
    sent = [{k: r[k] for k in ("ItemCode", "UOM", "Qty", "UnitPrice", "Location")} for r in qt_doc()["Details"]][:1]
    assert _created(qt_doc(), sent).outcome == "mismatch"


def test_ac_57_11_so_link_unconfirmed_is_warning_not_failure():
    sent = SO_FIX["request"]["Details"]
    doc = so_doc()
    assert doc["Details"][0]["FromDocDtlKey"] == 0  # real read-back (probe P-SO0)
    res = P.verify_create("SO", {"Details": sent}, doc)
    assert res.outcome == "done"
    assert "QT_ROW_LINK_UNCONFIRMED" in res.warnings


def test_ac_57_11_so_link_wrong_doc_no_is_mismatch():
    sent = SO_FIX["request"]["Details"]
    doc = so_doc()
    doc["Details"][0]["FromDocNo"] = "OTHER"
    assert P.verify_create("SO", {"Details": sent}, doc).outcome == "mismatch"


def test_ac_57_14_verify_edit_clean_returns_no_ignored():
    before = qt_doc()
    k = before["Details"][0]["DtlKey"]
    after = copy.deepcopy(before)
    after["Ref"] = "NEW"
    after["Details"][0]["Qty"] = 3.0
    assert P.verify_edit("QT", before, {"Ref": "NEW"}, [{"DtlKey": k, "Qty": 3}], after) == []


def test_ac_57_14_verify_edit_names_ignored_fields():
    before = qt_doc()
    k = before["Details"][0]["DtlKey"]
    after = copy.deepcopy(before)  # vendor changed nothing
    ignored = P.verify_edit("QT", before, {"Ref": "NEW"}, [{"DtlKey": k, "Qty": 3}], after)
    assert "Ref" in ignored and any("Qty" in str(i) for i in ignored)


def test_ac_57_14_verify_edit_untouched_change_is_reported():
    before = qt_doc()
    after = copy.deepcopy(before)
    after["Details"][1]["Location"] = "ELSEWHERE"  # an untouched row moved
    assert P.verify_edit("QT", before, {}, [], after)


def test_ac_57_16_verify_delete_line():
    before = qt_doc()
    k = before["Details"][0]["DtlKey"]
    after = copy.deepcopy(before)
    after["Details"] = [r for r in after["Details"] if r["DtlKey"] != k]
    assert P.verify_delete_line("QT", before, k, after).outcome == "done"
    assert P.verify_delete_line("QT", before, k, copy.deepcopy(before)).outcome == "mismatch"
    after2 = copy.deepcopy(after)
    after2["Details"][0]["Qty"] = 99.0  # another row changed
    assert P.verify_delete_line("QT", before, k, after2).outcome == "mismatch"


def test_ac_57_17_verify_cancel():
    after = qt_doc()
    after["Cancelled"] = "T"
    assert P.verify_cancel("QT", after).outcome == "done"
    after["Cancelled"] = "F"  # probe P-CX1: vendor answered 200 and changed nothing
    assert P.verify_cancel("QT", after).outcome == "mismatch"


# F13 (AC-E2E-DB3, db3 6 Nov, QT DocKey 12147): the wrapper copies Remark1 into
# Remark2..4 on an edit. Echoed old Remark2..4 reading back as the NEW Remark1 is the
# vendor mirroring, not an ignored field.
def _remarks(doc, value):
    for n in (1, 2, 3, 4):
        doc[f"Remark{n}"] = value


@pytest.mark.parametrize("kind,make", [("QT", qt_doc), ("SO", so_doc)])
def test_f13_remark1_mirrored_into_remark2_to_4_is_not_ignored(kind, make):
    before = make()
    _remarks(before, "QT-2026-0001 (R1)")
    after = copy.deepcopy(before)
    _remarks(after, "QT-2026-0001 (R2)")
    assert P.verify_edit(kind, before, {"Remark1": "QT-2026-0001 (R2)"}, [], after) == []


def test_f13_remark2_drift_to_another_value_is_still_reported():
    before = qt_doc()
    _remarks(before, "R1")
    after = copy.deepcopy(before)
    after["Remark1"] = "R2"
    after["Remark2"] = "SOMETHING ELSE"
    assert P.verify_edit("QT", before, {"Remark1": "R2"}, [], after) == ["Remark2"]


def test_f13_remark2_drift_without_a_remark1_change_is_still_reported():
    before = qt_doc()
    _remarks(before, "R1")
    after = copy.deepcopy(before)
    after["Remark2"] = after["Remark3"] = after["Remark4"] = "R2"
    assert P.verify_edit("QT", before, {"Ref": after.get("Ref")}, [], after) == ["Remark2", "Remark3", "Remark4"]


def test_f13_explicit_remark2_overwritten_by_the_mirror_is_reported():
    before = qt_doc()
    _remarks(before, "R1")
    after = copy.deepcopy(before)
    _remarks(after, "R2")
    ignored = P.verify_edit("QT", before, {"Remark1": "R2", "Remark2": "MINE"}, [], after)
    assert ignored == ["Remark2"]


def test_f13_remark1_itself_ignored_is_still_reported():
    before = qt_doc()
    _remarks(before, "R1")
    after = copy.deepcopy(before)
    assert P.verify_edit("QT", before, {"Remark1": "R2"}, [], after) == ["Remark1"]
