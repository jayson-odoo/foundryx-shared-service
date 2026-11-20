"""Plan 71 (lane SPO-LINK-PO-SS): move / split an SPO line onto another PO line.

Fixture (fake): SPO 7103 line L3 qty 60 tied to PO-A 7101 row A1 (qty 60); PO-B 7102 row B1, same item and
unit, qty 100, nothing on it. ``spo_move_row`` sends ONE PUT on the SPO: the old line ``"D"`` (whole move)
or kept with its rest on its old PO row (split), plus one new line tied to the target PO row.
"""

from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType

import pytest

from modules.autocount.write_back.repository import SpoPoLinkRepository
from tests.test_autocount_write_back_operations import OpHarness, _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

OP = "spo_move_row"
PUT = ("PUT", "editpurchaseorderbydockey")


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def h(db, session_factory, monkeypatch):
    return OpHarness(db, session_factory, monkeypatch)


def switch(h, on: bool = True) -> None:
    from modules.autocount.write_back import capabilities

    table = dict(capabilities.VENDOR_CAPABILITIES)
    table["spo_move"] = on
    h.monkeypatch.setattr(capabilities, "VENDOR_CAPABILITIES", MappingProxyType(table), raising=True)


class World:
    def __init__(self, h: OpHarness, *, b_over=None, l3_over=None, a_qty=60, b_qty=100):
        self.h = h
        base = dict(DeliveryDate="2026-12-01T00:00:00", Description="d")
        self.po_a = h.seed_doc("PO", 7101, [_line("ITEM-A", a_qty, 5.0, "BR1", **base)])
        self.a1 = self.po_a["Details"][0]["DtlKey"]
        self.po_b = h.seed_doc("PO", 7102, [_line("ITEM-A", b_qty, 6.0, "BR2", **base, **(b_over or {})),
                                            _line("ITEM-B", 10, 6.0, "BR2", **base),
                                            _line("ITEM-A", 10, 6.0, "BR2", **dict(base, UOM="BOX"))])
        self.b1, self.b_other_item, self.b_other_uom = [r["DtlKey"] for r in self.po_b["Details"]]
        spo_rows = [
            _line("ITEM-A", 60, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-7101", FromDocDtlKey=self.a1,
                  **(l3_over or {})),
            _line("ITEM-A", 5, 5.0, "BR1"),  # an unlinked line (ROW_NOT_LINKED)
        ]
        self.spo = h.seed_doc("SPO", 7103, spo_rows)
        self.l3, self.free = [r["DtlKey"] for r in self.spo["Details"]]

    def params(self, qty=24, **over):
        out = dict(spo_doc_key=7103, spo_dtl_key=self.l3, po_doc_key=7102, po_dtl_key=self.b1, qty=Decimal(qty))
        out.update(over)
        return out

    def spo_rows(self):
        return self.h.vendor.rows("SPO", 7103)

    def row(self, key):
        return next((r for r in self.spo_rows() if r["DtlKey"] == key), None)


@pytest.fixture
def w(h):
    switch(h)
    return World(h)


def only_spo_written(h) -> bool:
    return all((c.body or {}).get("DocKey") == 7103 for c in h.vendor.writes())


# ---- AC-71-01 split ---------------------------------------------------------------------------------

def test_ac_71_01_split_is_one_put_old_line_keeps_the_rest_on_its_po_row(h, w):
    res = h.run(OP, w.params(24))
    assert res.outcome == "done", (res.error_code, res.message)
    first = h.vendor.writes()[0]
    assert (first.method, first.leaf) == PUT and first.body["DocKey"] == 7103
    rows = first.body["Details"]
    kept = next(r for r in rows if r["DtlKey"] == w.l3)
    new = [r for r in rows if r["DtlKey"] == 0]
    assert kept.get("FullTransferOption") != "D" and kept["Qty"] == 36 and kept["FromDocDtlKey"] == w.a1
    assert len(new) == 1 and new[0]["Qty"] == 24 and new[0]["FromDocDtlKey"] == w.b1
    assert new[0]["FromDocType"] == "PO" and new[0]["FromDocNo"] == "PO-7102"
    # AutoCount (read back): 36 still on A1, 24 on B1
    assert w.row(w.l3)["Qty"] == 36 and w.row(w.l3)["FromDocDtlKey"] == w.a1
    moved = [r for r in w.spo_rows() if r["FromDocDtlKey"] == w.b1]
    assert len(moved) == 1 and moved[0]["Qty"] == 24
    assert res.batch["moved"] == {"spoDtlKey": moved[0]["DtlKey"], "fromPoDtlKey": w.a1,
                                  "toPoDtlKey": w.b1, "qty": "24"}
    assert res.batch["remainder"] == {"spoDtlKey": w.l3, "poDtlKey": w.a1, "qty": "36"}
    assert res.replaced_lines == []


# ---- AC-71-02 whole move ----------------------------------------------------------------------------

@pytest.mark.parametrize("qty", [60, 80])
def test_ac_71_02_take_at_or_above_the_open_qty_moves_the_whole_line(h, w, qty):
    res = h.run(OP, w.params(qty))
    assert res.outcome == "done", (res.error_code, res.message)
    rows = h.vendor.writes()[0].body["Details"]
    assert [r["DtlKey"] for r in rows if r.get("FullTransferOption") == "D"] == [w.l3]
    new = [r for r in rows if r["DtlKey"] == 0]
    assert len(new) == 1 and new[0]["Qty"] == 60 and new[0]["FromDocDtlKey"] == w.b1
    assert w.row(w.l3) is None
    moved = next(r for r in w.spo_rows() if r["FromDocDtlKey"] == w.b1)
    assert res.batch["moved"]["qty"] == "60" and res.batch["moved"]["spoDtlKey"] == moved["DtlKey"]
    assert res.batch["remainder"] is None
    assert res.replaced_lines == [(w.l3, moved["DtlKey"])]


# ---- AC-71-03 the PO documents are never written ------------------------------------------------------

def test_ac_71_03_no_po_document_is_written(h, w):
    assert h.run(OP, w.params(24)).outcome == "done"
    assert h.vendor.writes() and only_spo_written(h)


# ---- AC-71-04 refusals, nothing sent ------------------------------------------------------------------

def _refused(h, w, code, key="idem-r", reader="zero", **over):
    res = h.run(OP, w.params(**over), key=key, receipt_reader=reader)
    assert res.outcome == "refused" and res.error_code == code, (res.outcome, res.error_code, res.message)
    assert h.vendor.writes() == []
    return res


def test_ac_71_04_unlinked_spo_line_is_row_not_linked(h, w):
    _refused(h, w, "ROW_NOT_LINKED", spo_dtl_key=w.free)


def test_ac_71_04_target_is_the_current_po_row_is_no_change(h, w):
    _refused(h, w, "NO_CHANGE", po_doc_key=7101, po_dtl_key=w.a1)


def test_ac_71_04_other_item_is_item_mismatch(h, w):
    _refused(h, w, "ITEM_MISMATCH", po_dtl_key=w.b_other_item)


def test_ac_71_04_other_unit_is_uom_mismatch(h, w):
    _refused(h, w, "UOM_MISMATCH", po_dtl_key=w.b_other_uom)


def test_ac_71_04_unknown_target_row_is_row_not_found(h, w):
    _refused(h, w, "ROW_NOT_FOUND", po_dtl_key=999999)


def test_ac_71_04_fully_received_target_is_target_received(h):
    switch(h)
    w = World(h, b_over={"TransferedQty": 100})
    _refused(h, w, "TARGET_RECEIVED", reader="default")


def test_ac_71_04_target_without_room_is_qty_above_outstanding(h):
    switch(h)
    w = World(h, b_qty=20)
    _refused(h, w, "QTY_ABOVE_OUTSTANDING", qty=24)


def test_ac_71_04_fully_received_spo_line_is_row_received(h):
    switch(h)
    w = World(h, l3_over={"TransferedQty": 60})
    _refused(h, w, "ROW_RECEIVED", reader="default")


@pytest.mark.parametrize("qty", [0, -1])
def test_ac_71_04_qty_not_above_zero_is_invalid_params(h, w, qty):
    _refused(h, w, "INVALID_PARAMS", qty=qty)


def test_ac_71_04_cancelled_target_po_is_doc_cancelled(h, w):
    h.vendor.find("PO", 7102)["Cancelled"] = "T"
    _refused(h, w, "DOC_CANCELLED")


# ---- AC-71-05 a refusal releases the key ----------------------------------------------------------------

def test_ac_71_05_a_refusal_releases_the_key(h, w):
    _refused(h, w, "NO_CHANGE", key="same", po_doc_key=7101, po_dtl_key=w.a1)
    res = h.run(OP, w.params(24), key="same")
    assert res.outcome == "done", res.error_code


# ---- partial receipt: take = min(qty, open) ---------------------------------------------------------------

def test_partly_received_line_moves_only_its_open_qty(h):
    switch(h)
    w = World(h, l3_over={"TransferedQty": 10})
    res = h.run(OP, w.params(60), receipt_reader="default")
    assert res.outcome == "done", (res.error_code, res.message)
    assert w.row(w.l3)["Qty"] == 10 and w.row(w.l3)["FromDocDtlKey"] == w.a1
    assert res.batch["moved"]["qty"] == "50"
    assert res.batch["remainder"] == {"spoDtlKey": w.l3, "poDtlKey": w.a1, "qty": "10"}


# ---- AC-71-06 AutoCount says no ---------------------------------------------------------------------------

def test_ac_71_06_vendor_refusal_changes_nothing_and_releases_the_key(h, w):
    h.vendor.refuse_json_next("PUT", PUT[1])
    res = h.run(OP, w.params(24), key="k6")
    assert res.outcome == "vendor_error" and res.error_code == "VENDOR_REFUSED", (res.outcome, res.error_code)
    assert w.row(w.l3)["Qty"] == 60 and w.row(w.l3)["FromDocDtlKey"] == w.a1
    assert not [r for r in w.spo_rows() if r["FromDocDtlKey"] == w.b1]
    again = h.run(OP, w.params(24), key="k6")
    assert again.outcome == "done", again.error_code


# ---- AC-71-07 unknown outcome: resume reads before any retry ------------------------------------------------

def test_ac_71_07_timeout_is_pending_and_resume_confirms_without_a_second_put(h, w):
    h.vendor.apply_then_500_next("PUT", PUT[1])
    res = h.run(OP, w.params(24), key="k7")
    assert res.outcome in ("pending_verification", "done"), (res.outcome, res.error_code)
    if res.outcome == "done":
        pytest.skip("the read-back already confirmed it")
    puts = len(h.vendor.writes())
    done = h.ops().resume(tenant_id=h.company.tenant_id, company_id=h.company.id, operation_id=res.operation_id)
    assert done.outcome == "done", (done.outcome, done.error_code)
    assert len([c for c in h.vendor.writes()[puts:] if any(r.get("DtlKey") == 0 for r in c.body["Details"])]) == 0
    assert done.batch["remainder"]["qty"] == "36"


def test_ac_71_07_resume_of_a_put_that_never_landed_is_not_applied(h, w):
    h.vendor.timeout_next("PUT", PUT[1])
    res = h.run(OP, w.params(24), key="k7b")
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    out = h.ops().resume(tenant_id=h.company.tenant_id, company_id=h.company.id, operation_id=res.operation_id)
    if out.outcome == "done":  # the fake applied the timed-out PUT: confirmed, never sent twice
        assert len([r for r in w.spo_rows() if r["FromDocDtlKey"] == w.b1]) == 1
    else:
        assert out.outcome == "recovered" and out.error_code == "OPERATION_NOT_APPLIED"
        assert w.row(w.l3)["Qty"] == 60


# ---- AC-71-08 idempotency --------------------------------------------------------------------------------

def test_ac_71_08_same_key_same_body_replays_without_http(h, w):
    first = h.run(OP, w.params(24), key="k8")
    calls = len(h.vendor.calls)
    again = h.run(OP, w.params(24), key="k8")
    assert len(h.vendor.calls) == calls
    assert again.operation_id == first.operation_id and again.batch == first.batch


def test_ac_71_08_same_key_other_body_is_idempotency_conflict(h, w):
    h.run(OP, w.params(24), key="k8b")
    res = h.run(OP, w.params(25), key="k8b")
    assert res.outcome == "refused" and res.error_code == "IDEMPOTENCY_CONFLICT"


# ---- AC-71-09 switch / book ---------------------------------------------------------------------------------

def test_ac_71_09_switch_off_is_vendor_unsupported_with_no_http(h):
    switch(h, False)
    w = World(h)
    h.vendor.calls.clear()
    res = h.run(OP, w.params(24))
    assert res.outcome == "refused" and res.error_code == "VENDOR_UNSUPPORTED"
    assert h.vendor.calls == []


def test_ac_71_09_switch_is_off_by_default():
    from modules.autocount.write_back import capabilities

    assert capabilities.VENDOR_CAPABILITIES.get("spo_move") is False


def test_ac_71_09_capabilities_lists_the_move(h, w):
    items = {i["op"]: i for i in h.ops().capabilities(h.company)}
    assert items[OP]["kind"] and items[OP]["enabled"] is True


# ---- AC-71-10 every vendor call logged under the operation ----------------------------------------------------

def test_ac_71_10_the_put_is_an_action_row_of_the_operation(h, w):
    res = h.run(OP, w.params(24))
    actions = h.op_actions(res)
    assert actions and all(a.operation_id == res.operation_id for a in actions)


# ---- AC-71-11 the SPO -> PO index follows ----------------------------------------------------------------------

def test_ac_71_11_index_reads_the_new_rows(h, w):
    assert h.run(OP, w.params(24)).outcome == "done"
    repo = SpoPoLinkRepository(h.db)
    assert repo.linked_qty(h.company.tenant_id, h.company.id, w.b1) == Decimal(24)
    assert repo.linked_qty(h.company.tenant_id, h.company.id, w.a1) == Decimal(36)


# ---- U13 invariant: a split that lands wrong never strands a line ----------------------------------------------

def test_u13_kept_line_reading_back_without_its_po_row_is_needs_attention(h, w):
    original = h.vendor._edit

    def edit(kind, body):  # AutoCount drops the kept line's link (never seen; must not pass as done)
        out = original(kind, body)
        kept = w.row(w.l3)
        if kept is not None:
            kept.update(FromDocDtlKey=0, FromDocType="", FromDocNo="")
        return out

    h.vendor._edit = edit
    res = h.run(OP, w.params(24))
    assert res.outcome == "needs_attention", (res.outcome, res.error_code)
    assert h.alerts  # one alert to a person, nothing retried


# ---- the route: POST /api/v1/autocount/spo-links/move (plan 71 contract) ------------------------------------

MOVE = "/api/v1/autocount/spo-links/move"


@pytest.fixture
def gw(h, db):
    from tests.test_autocount_write_back_gateway_qtso import Gw

    switch(h)
    return Gw(h, db)


def body(w, qty=24, **over):
    out = {"companyCode": "SRT", "spoDocKey": 7103, "spoDtlKey": w.l3, "toPoDocKey": 7102,
           "toPoDtlKey": w.b1, "qty": qty}
    out.update(over)
    return out


def test_route_split_answers_moved_and_remainder(client, gw):
    w = World(gw.h)
    r = client.post(MOVE, json=body(w), headers=gw.hdr())
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["outcome"] == "done" and got["operationId"] and got["docKey"] == 7103
    assert got["moved"]["fromPoDtlKey"] == w.a1 and got["moved"]["toPoDtlKey"] == w.b1
    assert got["moved"]["qty"] == "24"
    assert got["remainder"] == {"spoDtlKey": w.l3, "poDtlKey": w.a1, "qty": "36"}
    again = client.post(MOVE, json=body(w), headers=gw.hdr())  # same key: the stored answer
    assert again.status_code == 200 and again.json()["moved"] == got["moved"]


def test_route_whole_move_has_no_remainder(client, gw):
    w = World(gw.h)
    r = client.post(MOVE, json=body(w, qty=60), headers=gw.hdr())
    assert r.status_code == 200, r.text
    assert r.json()["remainder"] is None and r.json()["moved"]["qty"] == "60"


def test_route_refusal_is_409_and_carries_both_fields_as_null(client, gw):
    w = World(gw.h)
    r = client.post(MOVE, json=body(w, toPoDocKey=7101, toPoDtlKey=w.a1), headers=gw.hdr())
    assert r.status_code == 409, r.text
    got = r.json()
    assert got["outcome"] == "refused" and got["errorCode"] == "NO_CHANGE"
    assert got["moved"] is None and got["remainder"] is None
    assert gw.h.vendor.writes() == []


def test_route_needs_the_idempotency_key(client, gw):
    w = World(gw.h)
    r = client.post(MOVE, json=body(w), headers=gw.hdr(idem=""))
    assert r.status_code == 422 and r.json().get("code") == "IDEMPOTENCY_KEY_REQUIRED", r.text
    assert gw.h.vendor.writes() == []


@pytest.mark.parametrize("bad", [{"qty": "24"}, {"qty": None}, {"toPoDtlKey": "x"}])
def test_route_bad_body_is_422(client, gw, bad):
    w = World(gw.h)
    r = client.post(MOVE, json=body(w, **bad), headers=gw.hdr())
    assert r.status_code == 422, r.text
    assert gw.h.vendor.writes() == []


def test_route_pull_only_key_is_403(client, h, db):
    from tests.test_autocount_write_back_gateway import _hdr, _key
    from tests.test_autocount_write_back_gateway_qtso import Gw

    switch(h)
    Gw(h, db)
    w = World(h)
    _row, plain = _key(db, [h.company.id])  # default scope: pull
    r = client.post(MOVE, json=body(w), headers={**_hdr(plain), "Idempotency-Key": "k"})
    assert r.status_code == 403, r.text
    assert h.vendor.writes() == []
