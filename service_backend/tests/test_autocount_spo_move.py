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


@pytest.mark.parametrize("qty", [0, -1, "1000000001", "3.123456789"])
def test_ac_71_04_qty_outside_the_house_rule_is_qty_invalid(h, w, qty):
    _refused(h, w, "QTY_INVALID", qty=qty)


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
    h.vendor.refuse_json_next("PUT", PUT[1], "refused")
    res = h.run(OP, w.params(24), key="k6")
    assert res.outcome == "vendor_error" and res.error_code == "VENDOR_REFUSED", (res.outcome, res.error_code)
    assert w.row(w.l3)["Qty"] == 60 and w.row(w.l3)["FromDocDtlKey"] == w.a1
    assert not [r for r in w.spo_rows() if r["FromDocDtlKey"] == w.b1]
    again = h.run(OP, w.params(24), key="k6")
    assert again.outcome == "done", again.error_code


def test_ac_71_06_an_autocount_timeout_is_unknown_not_a_refusal(h, w):
    """Main #326: an AutoCount SQL timeout may still save, so the move is never answered as refused."""
    h.vendor.refuse_json_next("PUT", PUT[1])  # the fake's default text is "Timeout expired."
    res = h.run(OP, w.params(24), key="k6t")
    assert res.outcome != "vendor_error" or res.error_code != "VENDOR_REFUSED", (res.outcome, res.error_code)
    assert res.error_code == "VENDOR_TIMEOUT", (res.outcome, res.error_code)


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
    puts = len(h.vendor.writes())
    out = h.ops().resume(tenant_id=h.company.tenant_id, company_id=h.company.id, operation_id=res.operation_id)
    assert out.outcome == "recovered" and out.error_code == "OPERATION_NOT_APPLIED", (out.outcome, out.error_code)
    assert w.row(w.l3)["Qty"] == 60 and len(h.vendor.writes()) == puts  # nothing sent by the resume
    again = h.run(OP, w.params(24), key="k7b")  # the key is free again: the press runs fresh
    assert again.outcome == "done", again.error_code


def test_ac_71_07_resume_when_the_line_changed_by_hand_needs_a_person(h, w):
    h.vendor.timeout_next("PUT", PUT[1])
    res = h.run(OP, w.params(24), key="k7c")
    assert res.outcome == "pending_verification"
    w.row(w.l3)["Qty"] = 59  # edited in AutoCount meanwhile, no new line
    out = h.ops().resume(tenant_id=h.company.tenant_id, company_id=h.company.id, operation_id=res.operation_id)
    assert out.outcome == "needs_attention", (out.outcome, out.error_code)


def test_u13_resume_of_a_landed_put_whose_kept_line_lost_its_po_row_needs_a_person(h, w):
    h.vendor.apply_then_500_next("PUT", PUT[1])
    res = h.run(OP, w.params(24), key="k13")
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    w.row(w.l3).update(FromDocDtlKey=0, FromDocType="", FromDocNo="")
    out = h.ops().resume(tenant_id=h.company.tenant_id, company_id=h.company.id, operation_id=res.operation_id)
    assert out.outcome == "needs_attention", (out.outcome, out.error_code)


def test_u13_verify_refuses_a_kept_spo_row_that_lost_its_link():
    from modules.autocount.write_back.payloads import verify_link_doc

    before = {"DocKey": 1, "Details": [{"DtlKey": 10, "ItemCode": "I", "UOM": "U", "Qty": 60, "FromDocDtlKey": 5}]}
    sent = [{"ItemCode": "I", "UOM": "U", "Qty": 24, "FromDocDtlKey": 7}]
    good = {"DocKey": 1, "Details": [dict(before["Details"][0], Qty=36),
                                     {"DtlKey": 11, "ItemCode": "I", "UOM": "U", "Qty": 24, "FromDocDtlKey": 7}]}
    assert verify_link_doc("SPO", before, [(10, sent)], good).outcome == "done"
    bad = {"DocKey": 1, "Details": [dict(good["Details"][0], FromDocDtlKey=0), good["Details"][1]]}
    verdict = verify_link_doc("SPO", before, [(10, sent)], bad)
    assert verdict.outcome != "done" and verdict.code == "LINK_MISMATCH"


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


# ---- the db3 probe script runs end to end (fake vendor) ------------------------------------------------------

def _probe(h, monkeypatch, argv):
    import app.database as database
    from modules.autocount.write_back import capabilities, operations
    from scripts import autocount_spo_move_probe as probe

    real = operations.OperationService
    monkeypatch.setattr(database, "SessionLocal", h.session_factory)
    monkeypatch.setattr(operations, "OperationService",
                        lambda db, **kw: real(db, **{**h.factories(), "receipt_reader": lambda *a: Decimal(0), **kw}))
    monkeypatch.setattr(capabilities, "VENDOR_CAPABILITIES", capabilities.VENDOR_CAPABILITIES)  # restored after
    return probe.main(argv)


def test_probe_script_splits_then_moves_back_on_db3(h, monkeypatch, capsys):
    w = World(h)  # switch left OFF: the script turns it on for its own process only
    code = _probe(h, monkeypatch, ["--company", h.company.id, "--spo", "7103", "--line", str(w.l3),
                                   "--from-po", "7101", "--to-po", "7102", "--to-line", str(w.b1), "--qty", "24"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert '"outcome": "done"' in out and "## 2. whole move back" in out
    on_a = [r for r in w.spo_rows() if r["FromDocDtlKey"] == w.a1]
    assert sorted(r["Qty"] for r in on_a) == [24, 36] and not [r for r in w.spo_rows() if r["FromDocDtlKey"] == w.b1]
    assert "ac.example.test" not in out  # no host in the evidence


def test_probe_script_look_writes_nothing(h, monkeypatch, capsys):
    World(h)
    assert _probe(h, monkeypatch, ["--company", h.company.id, "--spo", "7103", "--look"]) == 0
    assert h.vendor.writes() == []


# ---- review round 1: gaps ---------------------------------------------------------------------------------------

def test_review_expected_last_modified_mismatch_is_doc_stale(h, w):
    _refused(h, w, "DOC_STALE", expected_last_modified="1999-01-01T00:00:00.00")


def test_review_spo_changed_between_read_and_put_is_doc_stale_not_sent(h, w):
    from modules.autocount.write_back import operations

    real = operations.OperationService._spo_move_plan

    def plan_then_edit(self, *a, **kw):  # someone edits the SPO in AutoCount right after our read
        snap = real(self, *a, **kw)
        doc = h.vendor.find("SPO", 7103)
        doc["LastModified"] = "2099-01-01T00:00:00.00"
        return snap

    h.monkeypatch.setattr(operations.OperationService, "_spo_move_plan", plan_then_edit)
    res = h.run(OP, w.params(24))
    assert res.outcome == "refused" and res.error_code == "DOC_STALE", (res.outcome, res.error_code)
    assert h.vendor.writes() == [] and w.row(w.l3)["Qty"] == 60


def test_review_unknown_receipt_proceeds_with_the_warning(h, w):
    res = h.run(OP, w.params(24), receipt_reader=lambda *a: None)
    assert res.outcome == "done", res.error_code
    assert "TRANSFER_STATE_UNKNOWN" in res.warnings


def test_review_pending_move_on_another_spo_holds_its_room_on_the_target(h):
    switch(h)
    w = World(h, b_qty=30)
    other = h.seed_doc("SPO", 7104, [_line("ITEM-A", 20, 5.0, "BR1", FromDocType="PO", FromDocNo="PO-7101",
                                           FromDocDtlKey=w.a1)])
    h.vendor.timeout_next("PUT", PUT[1])
    first = h.run(OP, dict(w.params(20), spo_doc_key=7104, spo_dtl_key=other["Details"][0]["DtlKey"]), key="p1")
    assert first.outcome == "pending_verification"
    second = h.run(OP, w.params(24), key="p2")  # 30 - 20 pending = 10 left on B1
    assert second.outcome == "refused" and second.error_code == "QTY_ABOVE_OUTSTANDING", second.error_code
    ok = h.run(OP, w.params(10), key="p3")
    assert ok.outcome == "done", ok.error_code


def test_review_same_key_resend_of_a_pending_move_resumes_it_without_a_second_put(h, w):
    h.vendor.apply_then_500_next("PUT", PUT[1])
    first = h.run(OP, w.params(24), key="rs")
    assert first.outcome == "pending_verification"
    adds = lambda: [c for c in h.vendor.writes() if any(r.get("DtlKey") == 0 for r in c.body["Details"])]  # noqa: E731
    assert len(adds()) == 1
    again = h.run(OP, w.params(24), key="rs")
    assert again.outcome == "done", (again.outcome, again.error_code)
    assert len(adds()) == 1 and again.batch["remainder"]["qty"] == "36"


def test_review_needs_attention_alert_names_the_take_and_the_target(h, w):
    original = h.vendor._edit

    def edit(kind, body):
        out = original(kind, body)
        kept = w.row(w.l3)
        if kept is not None:
            kept.update(FromDocDtlKey=0)
        return out

    h.vendor._edit = edit
    res = h.run(OP, w.params(24))
    assert res.outcome == "needs_attention"
    (event,) = h.alerts
    assert event["qty"] == "24" and event["mode"] == "check" and event["moveTo"].endswith(f"row {w.b1}")


def test_review_target_po_document_is_locked_for_every_spo_op_with_a_target(h, w, monkeypatch):
    from modules.autocount.write_back import operations

    seen = []
    real = operations.link_locks

    def spy(db, company_id, po_doc_keys=(), so_dtl_keys=(), spo_doc_keys=()):
        seen.append((list(po_doc_keys), list(spo_doc_keys)))
        return real(db, company_id, po_doc_keys=po_doc_keys, so_dtl_keys=so_dtl_keys, spo_doc_keys=spo_doc_keys)

    monkeypatch.setattr(operations, "link_locks", spy)
    h.run(OP, w.params(24), key="l1")
    h.delete_on()
    h.run("spo_relink_row", dict(spo_doc_key=7103, spo_dtl_key=w.free, po_doc_key=7102, po_dtl_key=w.b1), key="l2")
    # the target PO document, and (plan 71 slice 2 review round 2) the SPO itself, which a batch's follow writes
    assert seen[0] == ([7102], [7103]) and seen[1] == ([7102], [7103]), seen
