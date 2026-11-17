"""Lane AUTOCOUNT-STRANDED-OPS-B (card: documentation/plans/sprint-5/67-autocount-stranded-ops-b.md).

R1: a single-document write (edit / add line / delete line) whose outcome is unknown
(``pending_verification``: swept after a crash, or timed out) is looked up before a same-key resend is
answered: in AutoCount -> ``done`` (locked, no second write); not in AutoCount -> key released, runs fresh;
unreadable -> the stored answer stands, never "in progress" for ever.
R2: the shipping-PO refusal carries plain reason text; a refusal releases the key.
Fake vendor only (db3-shaped); no AutoCount book is touched.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List

import pytest

from app.main import app  # noqa: F401 - the gateway rig overrides dependencies on it
from modules.autocount.models import AcWriteAction, AcWriteOperation
from modules.autocount.write_back.primitives import PrimitiveService
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw
from tests.test_autocount_write_back_operations import (  # noqa: F401
    KEY_ID,
    OpHarness,
    World,
    db,
    h,
)
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

EDIT = f"{PREFIX}/documents/purchase-orders/7001"
ADD = f"{PREFIX}/documents/purchase-orders/7001/lines"


@pytest.fixture
def world(h):
    h.delete_on()
    return World(h)


@pytest.fixture
def gw(h, db, world):
    return Gw(h, db)


def puts(h) -> List[Any]:
    return [c for c in h.vendor.writes() if c.method == "PUT"]


def op_row(h, key) -> AcWriteOperation:
    h.db.expire_all()
    return (h.db.query(AcWriteOperation)
            .filter(AcWriteOperation.idempotency_key == key, AcWriteOperation.company_id == h.company.id).one())


def edit_body(remark="checked"):
    return {"companyCode": "SRT", "header": {"remark1": remark}}


def add_body():
    return {"companyCode": "SRT", "line": {"itemCode": "ITEM-A", "uom": "UNIT", "qty": 3, "unitPrice": 5,
                                           "location": "BR1"}}


def _send(client, gw, path, body, key):
    if path == EDIT:
        return client.patch(path, json=body, headers=gw.hdr(key))
    return client.post(path, json=body, headers=gw.hdr(key))


def _strand(h, monkeypatch, client, gw, path, body, key, *, after_put: bool):
    """The state a worker killed mid-write leaves (gunicorn SIGKILL / OOM: no finally ran): the operation
    ``in_progress`` with no answer, its action ``in_flight`` with no read-back. ``after_put`` = the PUT
    reached AutoCount (landed) or not (the fake vendor times out before applying it)."""
    if not after_put:
        leaf = "EditPurchaseOrderbydockey"
        h.vendor.timeout_next("PUT", leaf)
    _send(client, gw, path, body, key)
    row = op_row(h, key)
    row.status, row.error_code, row.result_json = "in_progress", None, None
    for action in h.db.query(AcWriteAction).filter(AcWriteAction.company_id == h.company.id,
                                                   AcWriteAction.created_at >= row.created_at):
        action.outcome, action.error_code, action.after_json = "in_flight", None, None
    h.db.commit()
    return op_row(h, key)


def _sweep(h, row):
    from modules.autocount.write_back.frame import BUSY_WINDOW_SECONDS
    from modules.autocount.write_back.operations import sweep_stranded_operations

    old = datetime.now(timezone.utc) - timedelta(seconds=BUSY_WINDOW_SECONDS + 60)
    row.created_at = row.updated_at = old
    for action in h.db.query(AcWriteAction).filter(AcWriteAction.company_id == h.company.id):
        action.created_at = old
    h.db.commit()
    assert sweep_stranded_operations(h.db) >= 1
    h.db.expire_all()
    assert op_row(h, row.idempotency_key).status == "pending_verification"


# ---- R1: swept edit, landed -> done, locked, no second PUT --------------------------------------

def test_swept_edit_that_landed_is_done_on_the_same_key_resend(client, h, gw, monkeypatch):
    row = _strand(h, monkeypatch, client, gw, EDIT, edit_body(), "b-1", after_put=True)
    assert len(puts(h)) == 1 and h.vendor.find("PO", 7001)["Remark1"] == "checked"
    _sweep(h, row)
    r = client.patch(EDIT, json=edit_body(), headers=gw.hdr("b-1"))
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "done"
    assert len(puts(h)) == 1  # looked up, never re-sent
    assert op_row(h, "b-1").status == "done"
    again = client.patch(EDIT, json=edit_body(), headers=gw.hdr("b-1"))  # locked: replayed
    assert again.json()["outcome"] == "done" and len(puts(h)) == 1


def test_swept_edit_that_never_landed_runs_fresh_on_the_same_key_resend(client, h, gw, monkeypatch):
    row = _strand(h, monkeypatch, client, gw, EDIT, edit_body(), "b-2", after_put=False)
    assert h.vendor.find("PO", 7001).get("Remark1") != "checked"  # the PUT never applied
    _sweep(h, row)
    r = client.patch(EDIT, json=edit_body(), headers=gw.hdr("b-2"))
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "done"
    assert len(puts(h)) == 2  # the timed-out one, then the one fresh PUT
    assert h.vendor.find("PO", 7001)["Remark1"] == "checked"
    h.db.expire_all()
    old = h.db.get(AcWriteOperation, row.id)
    assert old.status == "recovered" and old.idempotency_key != "b-2"  # kept for history, re-keyed


def test_stale_in_progress_add_line_is_looked_up_without_waiting_for_the_sweep(client, h, gw, monkeypatch):
    row = _strand(h, monkeypatch, client, gw, ADD, add_body(), "b-3", after_put=True)
    lines = len(h.vendor.rows("PO", 7001))
    from modules.autocount.write_back.frame import BUSY_WINDOW_SECONDS

    old = datetime.now(timezone.utc) - timedelta(seconds=BUSY_WINDOW_SECONDS + 60)
    row.created_at = row.updated_at = old
    h.db.commit()
    r = client.post(ADD, json=add_body(), headers=gw.hdr("b-3"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "done" and len(body["document"]["Details"]) == lines
    assert len(h.vendor.rows("PO", 7001)) == lines  # never added twice
    assert len(puts(h)) == 1


def test_added_line_found_even_when_someone_else_edited_the_po_meanwhile(client, h, gw, world, monkeypatch):
    """The lookup asks only "is OUR line there": another person's edit since (a remark, another line) must not
    make it look not-landed, which would add the line a second time."""
    row = _strand(h, monkeypatch, client, gw, ADD, add_body(), "b-10", after_put=True)
    _sweep(h, row)
    po = h.vendor.find("PO", 7001)
    po["Remark2"] = "changed by someone in AutoCount"
    po["Details"].append(dict(po["Details"][0], DtlKey=99001, Qty=9))  # their own new line
    lines = len(po["Details"])
    r = client.post(ADD, json=add_body(), headers=gw.hdr("b-10"))
    assert r.json()["outcome"] == "done", r.text
    assert len(h.vendor.rows("PO", 7001)) == lines and len(puts(h)) == 1


def test_deleted_line_found_even_when_another_line_changed_meanwhile(client, h, gw, world, monkeypatch):
    from modules.autocount.write_back.reader import DocReadError

    def broken(self, *a, **kw):
        raise DocReadError("READ_FAILED")

    path = f"{PREFIX}/documents/purchase-orders/7001/lines/{world.p_free}/delete"
    with monkeypatch.context() as patch:  # the PUT lands, its read-back fails
        patch.setattr(PrimitiveService, "_read_back", broken)
        first = client.post(path, json={"companyCode": "SRT"}, headers=gw.hdr("b-11"))
    assert first.json()["outcome"] == "pending_verification", first.text
    world.row_by_key(h.vendor.rows("PO", 7001), world.p_other)["Qty"] = 99  # someone else's edit
    r = client.post(path, json={"companyCode": "SRT"}, headers=gw.hdr("b-11"))
    assert r.json()["outcome"] == "done", r.text
    assert len(puts(h)) == 1


def test_change_landed_judges_only_this_change():
    from modules.autocount.write_back.payloads import change_landed

    before = {"DocKey": 1, "Remark1": "a", "Details": [{"DtlKey": 10, "ItemCode": "X", "Qty": 1}]}
    after = {"DocKey": 1, "Remark1": "b", "Remark2": "other", "Details": [{"DtlKey": 10, "ItemCode": "X", "Qty": 5}]}
    assert change_landed("PO", "edit_doc", before, after, header_changes={"Remark1": "b"}) == (True, None)
    assert change_landed("PO", "edit_doc", before, after, header_changes={"Remark1": "c"})[0] is False
    assert change_landed("PO", "edit_doc", before, after, line_changes=[{"DtlKey": 10, "Qty": 5}])[0] is True
    assert change_landed("PO", "edit_doc", before, after, line_changes=[{"DtlKey": 11, "Qty": 5}])[0] is False
    assert change_landed("PO", "delete_line", before, {"Details": []}, dtl_key=10)[0] is True
    assert change_landed("PO", "delete_line", before, after, dtl_key=10)[0] is False
    assert change_landed("PO", "delete_line", before, {"Details": []}, dtl_key=77)[0] is False  # never ours
    assert change_landed("PO", "cancel_doc", before, {"Cancelled": "T"})[0] is True
    assert change_landed("PO", "cancel_doc", before, {"Cancelled": "F"})[0] is False


def test_young_in_progress_still_answers_in_progress(client, h, gw, monkeypatch):
    _strand(h, monkeypatch, client, gw, EDIT, edit_body(), "b-4", after_put=True)
    r = client.patch(EDIT, json=edit_body(), headers=gw.hdr("b-4"))
    assert r.json()["errorCode"] == "OPERATION_IN_PROGRESS"
    assert len(puts(h)) == 1


# ---- R1: a timed-out write (stored pending) is looked up too ------------------------------------

def test_timed_out_add_line_that_never_landed_is_added_once_on_the_same_key(client, h, gw):
    lines = len(h.vendor.rows("PO", 7001))
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    first = client.post(ADD, json=add_body(), headers=gw.hdr("b-5"))
    assert first.json()["outcome"] == "pending_verification", first.text
    r = client.post(ADD, json=add_body(), headers=gw.hdr("b-5"))
    assert r.json()["outcome"] == "done", r.text
    assert len(h.vendor.rows("PO", 7001)) == lines + 1


def test_delete_line_whose_read_back_failed_is_done_on_lookup_without_a_second_put(client, h, gw, world):
    path = f"{PREFIX}/documents/purchase-orders/7001/lines/{world.p_free}/delete"
    real = PrimitiveService._read_back

    def broken(self, *a, **kw):
        from modules.autocount.write_back.reader import DocReadError
        raise DocReadError("READ_FAILED")

    PrimitiveService._read_back = broken
    try:
        first = client.post(path, json={"companyCode": "SRT"}, headers=gw.hdr("b-6"))
    finally:
        PrimitiveService._read_back = real
    assert first.json()["outcome"] == "pending_verification", first.text
    assert world.row_by_key(h.vendor.rows("PO", 7001), world.p_free) is None  # it landed
    r = client.post(path, json={"companyCode": "SRT"}, headers=gw.hdr("b-6"))
    assert r.json()["outcome"] == "done", r.text
    assert len(puts(h)) == 1


def test_lookup_that_cannot_read_keeps_the_pending_answer(client, h, gw, monkeypatch):
    row = _strand(h, monkeypatch, client, gw, EDIT, edit_body(), "b-7", after_put=True)
    _sweep(h, row)
    for _ in range(5):
        h.vendor.fail_next("GET", "purchaseorderbydocdate", status=503)
        h.vendor.fail_next("GET", "purchaseorderbydocno", status=503)
    r = client.patch(EDIT, json=edit_body(), headers=gw.hdr("b-7"))
    body = r.json()
    assert body["outcome"] == "pending_verification", r.text
    assert body["errorCode"] != "OPERATION_IN_PROGRESS"
    assert body["message"]  # plain reason
    assert len(puts(h)) == 1


def test_lookup_read_is_logged_under_the_operation(client, h, gw, monkeypatch):
    from modules.autocount.models import AcApiCallLog as AcCallLog

    row = _strand(h, monkeypatch, client, gw, EDIT, edit_body(), "b-8", after_put=True)
    _sweep(h, row)
    client.patch(EDIT, json=edit_body(), headers=gw.hdr("b-8"))
    h.db.expire_all()
    logged = h.db.query(AcCallLog).filter(AcCallLog.operation_id == row.id).all()
    assert any(c.method == "GET" for c in logged)


def test_another_body_under_the_same_key_is_still_a_conflict_and_never_looked_up(client, h, gw, monkeypatch):
    row = _strand(h, monkeypatch, client, gw, EDIT, edit_body(), "b-9", after_put=True)
    _sweep(h, row)
    gets = len(h.vendor.gets())
    r = client.patch(EDIT, json=edit_body("other"), headers=gw.hdr("b-9"))
    assert r.json()["errorCode"] == "IDEMPOTENCY_CONFLICT"
    assert len(h.vendor.gets()) == gets


# ---- R2: shipping-PO reason + released key ------------------------------------------------------

@pytest.mark.parametrize("op", ["link_row", "unlink_row", "relink_row"])
def test_row_on_spo_carries_a_plain_reason(h, world, op):
    res = h.run(op, dict(world.params[op], dtl_key=world.p_spo), key=f"spo-{op}")
    assert (res.outcome, res.error_code) == ("refused", "ROW_ON_SPO")
    assert "shipping purchase order" in res.message and "try again" in res.message.lower()
    assert "SPO-7003" in res.message


def test_row_on_spo_refusal_releases_the_key(h, world):
    params = dict(world.params["link_row"], dtl_key=world.p_spo)
    first = h.run("link_row", params, key="spo-key")
    again = h.run("link_row", params, key="spo-key")  # same key, same body: runs fresh, not replayed
    assert again.error_code == "ROW_ON_SPO" and again.operation_id != first.operation_id


def test_primitive_delete_line_on_spo_row_carries_the_plain_reason(client, h, gw, world):
    path = f"{PREFIX}/documents/purchase-orders/7001/lines/{world.p_spo}/delete"
    r = client.post(path, json={"companyCode": "SRT"}, headers=gw.hdr("spo-prim"))
    body = r.json()
    assert body["errorCode"] == "ROW_ON_SPO", r.text
    assert "shipping purchase order" in body["message"] and "try again" in body["message"].lower()
