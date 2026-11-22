"""PO-LINK-STUCK-RECONCILE-B (RED first): Link PO read-backs and resumes are truthful after a stuck write.

Prod 20 Nov (masked): a split_link on a ~96-row PO landed, but SS parked it ``pending_verification`` /
``READBACK_MISMATCH`` because AutoCount recomputed the header money / tax fields (TaxEntityID, totals) on the
save; Resume and every same-key resend then answered the stored state for ever. The same day an edit PUT
answered an AutoCount SQL timeout, was released as ``VENDOR_REFUSED`` after one read, and landed later.

s5  split_link is judged by the ONE link comparator the batches use; the new tied row takes the SO line's date.
s2  a parked split re-verifies on Resume and on a same-key resend (never a second link PUT); an operator may
    close a parked operation as superseded (final ``refused`` / ``SUPERSEDED``, no AutoCount call); a link of
    the same qty again from the same PO row while SS's earlier tie still stands = ``ROW_ALREADY_LINKED``.
s3/4 an AutoCount SQL timeout is unknown (``vendor_error`` / ``VENDOR_TIMEOUT``), then a read decides:
    landed = done, absent once the save had time to finish = refused (released), unreadable = needs_attention.
    No second PUT in any case.

World (``tests.test_autocount_write_back_operations.World``): PO 7001 free row ``p_free`` qty 4 at BR1, SO 7002
row ``so_a`` qty 10 dated 2027-01-01 (the SO line date), PO doc date 2026-11-04.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from decimal import Decimal
from typing import Any, List

import httpx
import pytest

from app.main import app  # noqa: F401 - the gateway rig overrides dependencies on it
from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcWriteAction, AcWriteOperation
from modules.autocount.write_back import operations as ops_mod, payloads, service as service_mod
from modules.autocount.write_back.frame import BUSY_WINDOW_SECONDS
from modules.autocount.write_back.primitives import PrimitiveService
from modules.autocount.write_back.reader import DocReadError
from modules.autocount.write_back.repository import OperationRepository
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw
from tests.test_autocount_write_back_link_batch import Rig
from tests.test_autocount_plan63_gate import DB1, _logs, _point_at, _set  # noqa: F401
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

EDIT = "EditPurchaseOrderbydockey"
SO_DAY = "2027-01-01"
SUB = "BRW-NTC"  # a sub-location (its parent BRW also exists)
TIMEOUT_TEXT = ("Timeout expired.  The timeout period elapsed prior to completion of the operation or the server "
                "is not responding. Operation cancelled by user.")


@pytest.fixture(autouse=True)
def _no_reread_wait(monkeypatch):
    monkeypatch.setattr(service_mod, "SPLIT_REREAD_WAIT_SECONDS", 0, raising=False)


@pytest.fixture
def w(h):
    h.delete_on()
    h.vendor.locations.append(SUB)
    return World(h, so_over={"DeliveryDate": f"{SO_DAY}T00:00:00"})


def split(h, w, key="s-1", qty=2, **kw):
    return h.run("split_link", dict(po_doc_key=7001, po_dtl_key=w.p_free, so_doc_key=7002, so_dtl_key=w.so_a,
                                    qty=Decimal(qty), location=SUB, **kw), key=key)


def resume(h, res):
    return h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=res.operation_id)


def puts(h) -> List[Any]:
    return [c for c in h.vendor.writes() if c.method == "PUT"]


def link_puts(h) -> List[Any]:
    """The PUTs that create a new linked row (the link write itself, never the restore)."""
    return [c for c in puts(h) if any(not r.get("DtlKey") for r in (c.body or {}).get("Details") or [])]


def tied(h, w) -> List[dict]:
    return [r for r in h.vendor.rows("PO", 7001) if r.get("FromSODtlKey") == w.so_a and r["DtlKey"] != w.p_linked]


def row(h, key):
    return next((r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == key), None)


def after_link_put(h, change) -> None:
    """``change(doc)`` runs on the PO right after the next link PUT lands (the vendor's own doing)."""
    original = h.vendor._edit
    state = {"done": False}

    def edit(kind, body):
        resp = original(kind, body)
        if (not state["done"] and kind == "PO" and resp.status_code < 300
                and any(not r.get("DtlKey") for r in body.get("Details") or [])):
            state["done"] = True
            change(h.vendor.find("PO", body["DocKey"]))
        return resp

    h.vendor._edit = edit


def age_actions(h, res, seconds=ops_mod.LOOKUP_SETTLE_SECONDS + 60):
    """The operation's writes happened ``seconds`` ago (the save had time to finish)."""
    h.db.expire_all()
    for action in h.db.query(AcWriteAction).filter(AcWriteAction.operation_id == res.operation_id).all():
        action.created_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    h.db.commit()


def fail_po_reads_after_put(h):
    """Every PO read after the next PUT answers 500 until ``state["on"]`` is cleared."""
    original = h.vendor._route
    state = {"put": False, "on": True}

    def route(method, leaf, call):
        state["put"] = state["put"] or any(c.method == "PUT" for c in h.vendor.calls)
        if state["on"] and state["put"] and method == "GET" and "purchaseorder" in leaf:
            return httpx.Response(500, text="read failed")
        return original(method, leaf, call)

    h.vendor._route = route
    return state


# ============================== s5: the read-back comparator =====================================

def _derived_header_and_parent_location(doc):
    """What AutoCount did on the prod save: money / tax header recomputed, the new tied row at the parent."""
    doc["TaxEntityID"] = 7
    doc["Total"] = 1234.5
    doc["FinalTotal"] = 1234.5
    doc["LocalTaxableAmt"] = 99.0
    doc["Details"][-1]["Location"] = "BRW"


def test_s5_masked_prod_split_reads_back_done(h, w):
    po = h.vendor.find("PO", 7001)
    po.update(TaxEntityID=3, Total=40.0, FinalTotal=40.0, LocalTaxableAmt=0.0)
    after_link_put(h, _derived_header_and_parent_location)
    res = split(h, w)
    assert (res.outcome, res.error_code) == ("done", None), (res.outcome, res.error_code, res.message)
    (new,) = tied(h, w)
    assert new["Qty"] == 2 and new["Location"] == SUB and new["DeliveryDate"][:10] == SO_DAY
    assert row(h, w.p_free)["Qty"] == 2  # the kept row as sent
    assert len(link_puts(h)) == 1


def test_s5_split_and_batch_share_the_one_comparator(h, w, monkeypatch):
    seen: List[int] = []
    real = payloads.verify_link_doc

    def spy(kind, before, groups, after):
        seen.append(len(groups))
        return real(kind, before, groups, after)

    monkeypatch.setattr(payloads, "verify_link_doc", spy)
    assert split(h, w).outcome == "done"
    after_split = len(seen)
    assert after_split >= 1, "split_link did not use the link comparator"
    res = h.run("link_batch", dict(doc_key=7001, dtl_key=w.p_other, links=[
        dict(so_doc_key=7002, so_dtl_key=w.so_b, qty=1)]), key="b-1")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(seen) > after_split, "link_batch did not use the link comparator"


@pytest.mark.parametrize("wrong", ["qty", "extra_row", "missing_row", "untouched_row", "kept_row", "kept_row_moved",
                                   "link"])
def test_s5_a_real_wrong_write_is_still_a_mismatch(h, w, wrong):
    def change(doc):
        rows = doc["Details"]
        if wrong == "qty":
            rows[-1]["Qty"] = 3
        elif wrong == "extra_row":
            rows.append(dict(rows[-1], DtlKey=999001))
        elif wrong == "missing_row":
            rows.pop()
        elif wrong == "untouched_row":
            next(r for r in rows if r["DtlKey"] == w.p_other)["Qty"] = 9
        elif wrong == "kept_row":
            next(r for r in rows if r["DtlKey"] == w.p_free)["Qty"] = 4
        elif wrong == "kept_row_moved":  # the kept row's qty is right but it moved / was repriced
            next(r for r in rows if r["DtlKey"] == w.p_free).update(Location="HQ", UnitPrice=0.0)
        elif wrong == "link":
            rows[-1]["FromSODtlKey"] = w.so_b

    after_link_put(h, change)
    res = split(h, w)
    assert res.outcome != "done", wrong
    assert res.outcome == "pending_verification" and res.error_code == "READBACK_MISMATCH", (res.outcome, res.error_code)
    assert len(puts(h)) == 1  # no restore on a wrong write


def test_s5_header_field_we_did_not_send_still_counts(h, w):
    h.vendor.find("PO", 7001)["Note"] = "keep me"
    after_link_put(h, lambda doc: doc.update(Note=""))
    res = split(h, w)
    assert (res.outcome, res.error_code) == ("pending_verification", "READBACK_MISMATCH")


def test_s5_a_slow_save_is_read_again_once_before_a_mismatch(h, w, monkeypatch):
    monkeypatch.setattr(service_mod, "SPLIT_REREAD_WAIT_SECONDS", 0.01)
    original = h.vendor._route
    state = {"put": False, "reads": 0}

    def route(method, leaf, call):
        resp = original(method, leaf, call)
        if method == "PUT":
            state["put"] = True
        elif state["put"] and method == "GET" and "purchaseorder" in leaf:
            state["reads"] += 1
            if state["reads"] == 1:  # the first read-back still shows the old kept row
                import json as _json
                body = _json.loads(resp.content)
                docs = body if isinstance(body, list) else [body]
                for d in docs:
                    for r in d.get("Details") or []:
                        if r["DtlKey"] == w.p_free:
                            r["Qty"] = 4
                return httpx.Response(resp.status_code, json=body)
        return resp

    h.vendor._route = route
    res = split(h, w)
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(link_puts(h)) == 1


# ============================== s5: the new row's delivery date ==================================

def test_s5_split_new_row_takes_the_so_line_date_not_the_po_date(h, w):
    res = split(h, w)
    assert res.outcome == "done"
    (link_put,) = link_puts(h)
    new = next(r for r in link_put.body["Details"] if not r.get("DtlKey"))
    assert new["DeliveryDate"][:10] == SO_DAY
    assert tied(h, w)[0]["DeliveryDate"][:10] == SO_DAY


def test_s5_batch_new_row_takes_the_so_line_date(h, w):
    res = h.run("link_batch", dict(doc_key=7001, dtl_key=w.p_free, links=[
        dict(so_doc_key=7002, so_dtl_key=w.so_a, qty=1)]), key="b-date")
    assert res.outcome == "done", (res.outcome, res.error_code)
    (link_put,) = link_puts(h)
    new = next(r for r in link_put.body["Details"] if not r.get("DtlKey"))
    assert new["DeliveryDate"][:10] == SO_DAY


# ============================== s2: Resume / resend of a parked split ============================

def _parked_split(h, w, key="s-park"):
    state = fail_po_reads_after_put(h)
    res = split(h, w, key=key)
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    state["on"] = False
    return res


def test_s2_resume_parked_split_whose_row_stands_as_sent_is_done(h, w):
    res = _parked_split(h, w)
    out = resume(h, res)
    assert (out.outcome, out.error_code) == ("done", None), (out.outcome, out.error_code, out.message)
    (new,) = tied(h, w)
    assert out.detail["DtlKey"] == new["DtlKey"]
    assert new["Location"] == SUB and new["DeliveryDate"][:10] == SO_DAY and new["UnitPrice"] == 5.0
    assert len(link_puts(h)) == 1  # the link PUT is never sent again (only the restore)


def test_s2_resume_parked_split_autocount_already_derived_is_done_without_a_put(h, w):
    res = _parked_split(h, w)
    (new,) = tied(h, w)
    new.update(Location=SUB, DeliveryDate=f"{SO_DAY}T00:00:00", UnitPrice=5.0)  # AutoCount / a person did it
    before = len(puts(h))
    out = resume(h, res)
    assert out.outcome == "done", (out.outcome, out.error_code, out.message)
    assert len(puts(h)) == before


def test_s2_resume_the_masked_prod_park_is_done(h, w):
    """The prod row exactly: parked READBACK_MISMATCH on a derived header (before this lane), the row later
    as AutoCount derived it. Re-judged with today's comparator: done, nothing sent."""
    res = _parked_split(h, w)
    po = h.vendor.find("PO", 7001)
    po.update(TaxEntityID=9, Total=1.0)
    (new,) = tied(h, w)
    new.update(Location=SUB, DeliveryDate=f"{SO_DAY}T00:00:00", UnitPrice=5.0)
    out = resume(h, res)
    assert out.outcome == "done", (out.outcome, out.error_code, out.message)


def test_s2_resume_parked_split_absent_is_refused_once_the_save_had_time(h, w):
    h.vendor.timeout_next("PUT", EDIT)  # the PUT never reached AutoCount's save
    res = split(h, w, key="s-abs")
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    young = resume(h, res)
    assert young.outcome == "pending_verification", (young.outcome, young.error_code)  # may still be saving
    age_actions(h, res)
    out = resume(h, res)
    assert (out.outcome, out.error_code) == ("refused", "OPERATION_NOT_APPLIED"), (out.outcome, out.error_code)
    assert len(link_puts(h)) == 1 and tied(h, w) == []
    again = split(h, w, key="s-abs")  # the key is released: a press runs fresh
    assert again.outcome == "done" and again.operation_id != res.operation_id


def test_s2_resume_parked_split_partly_there_needs_a_person(h, w):
    res = _parked_split(h, w)
    (new,) = tied(h, w)
    new["Qty"] = 1  # someone changed it by hand
    out = resume(h, res)
    assert out.outcome == "needs_attention", (out.outcome, out.error_code)
    assert "AutoCount" in out.message and "READBACK" not in out.message
    assert len(link_puts(h)) == 1


def test_s2_same_key_resend_of_a_parked_split_reverifies_and_never_puts_again(h, w):
    res = _parked_split(h, w, key="s-resend")
    again = split(h, w, key="s-resend")
    assert again.operation_id == res.operation_id
    assert again.outcome == "done", (again.outcome, again.error_code)
    assert len(link_puts(h)) == 1
    third = split(h, w, key="s-resend")  # done = locked: replayed, nothing sent
    assert third.outcome == "done" and len(link_puts(h)) == 1


def test_s2_close_as_superseded_is_final_refused_and_calls_nothing(h, w):
    res = _parked_split(h, w, key="s-sup")
    age_actions(h, res)
    calls = len(h.vendor.calls)
    out = h.ops().close_superseded(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                                   operation_id=res.operation_id)
    assert (out.outcome, out.error_code) == ("refused", "SUPERSEDED")
    assert len(h.vendor.calls) == calls
    look = split(h, w, key="s-sup")  # the CRM's look-up: the same answer, never a write
    assert (look.outcome, look.error_code) == ("refused", "SUPERSEDED")
    assert len(h.vendor.calls) == calls
    assert resume(h, res).error_code == "SUPERSEDED"


def test_s2_close_as_superseded_waits_while_a_timed_out_save_may_land(h, w):
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    res = split(h, w, key="s-sup-young")
    assert res.error_code == "VENDOR_TIMEOUT"
    out = h.ops().close_superseded(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                                   operation_id=res.operation_id)
    assert (out.outcome, out.error_code) == ("vendor_error", "VENDOR_TIMEOUT")  # not closed yet
    age_actions(h, res)
    out = h.ops().close_superseded(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                                   operation_id=res.operation_id)
    assert (out.outcome, out.error_code) == ("refused", "SUPERSEDED")


def test_s3_a_business_refusal_quoting_timeout_words_is_still_a_refusal(h, w):
    original = h.vendor._route

    def route(method, leaf, call):
        if method == "PUT":
            return httpx.Response(500, json={"ExceptionMessage": "Note 'timeout expired' is not allowed.",
                                             "ExceptionType": "AutoCount.Invoicing.SomeBusinessException"})
        return original(method, leaf, call)

    h.vendor._route = route
    res = _batch(h, w, "to-biz")
    assert (res.outcome, res.error_code) == ("vendor_error", "VENDOR_REFUSED")


def test_s2_close_as_superseded_leaves_a_final_operation_as_it_is(h, w):
    res = split(h, w, key="s-final")
    out = h.ops().close_superseded(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                                   operation_id=res.operation_id)
    assert out.outcome == "done"


# ============================== s2: a standing tie is never split again ==========================

def test_s2_link_again_while_ss_tie_from_the_same_row_stands_is_refused(h, w):
    assert split(h, w, key="t-1").outcome == "done"
    before = len(puts(h))
    again = split(h, w, key="t-2")
    assert (again.outcome, again.error_code) == ("refused", "ROW_ALREADY_LINKED")
    assert len(puts(h)) == before and len(tied(h, w)) == 1


def test_s2_batch_again_while_ss_tie_from_the_same_row_stands_is_skipped(h, w):
    params = dict(doc_key=7001, dtl_key=w.p_free, links=[dict(so_doc_key=7002, so_dtl_key=w.so_a, qty=1)])
    assert h.run("link_batch", params, key="tb-1").outcome == "done"
    again = h.run("link_batch", params, key="tb-2")
    assert again.outcome == "refused" and again.batch["skipped"][0]["code"] == "ROW_ALREADY_LINKED"


def test_s2_change_unlink_then_link_is_allowed(h, w):
    first = split(h, w, key="c-1")
    assert first.outcome == "done"
    gone = h.run("unlink_row", dict(doc_key=7001, dtl_key=first.detail["DtlKey"]), key="c-2")
    assert gone.outcome in ("done", "recovered"), (gone.outcome, gone.error_code)
    again = split(h, w, key="c-3")
    assert again.outcome == "done", (again.outcome, again.error_code)


# ============================== s3/s4: an AutoCount SQL timeout ==================================

def _batch(h, w, key):
    return h.run("link_batch", dict(doc_key=7001, dtl_key=w.p_free, links=[
        dict(so_doc_key=7002, so_dtl_key=w.so_a, qty=1)]), key=key)


def _doc_batch(h, w, key):
    return h.run("link_doc_batch", dict(doc_key=7001, links=[
        dict(po_dtl_key=w.p_free, so_doc_key=7002, so_dtl_key=w.so_a, qty=1)]), key=key)


def _flow(h, w, flow, key):
    if flow == "split":
        return split(h, w, key=key)
    return (_batch if flow == "batch" else _doc_batch)(h, w, key)


@pytest.mark.parametrize("flow", ["split", "batch", "doc_batch"])
def test_s3_timeout_and_the_write_is_there_is_done(h, w, flow):
    h.vendor.apply_then_refuse_next("PUT", EDIT, TIMEOUT_TEXT)
    res = _flow(h, w, flow, "to-1")
    assert (res.outcome, res.error_code) == ("done", None), (res.outcome, res.error_code, res.message)
    assert len(link_puts(h)) == 1


@pytest.mark.parametrize("flow", ["split", "batch", "doc_batch"])
def test_s3_timeout_and_nothing_there_is_unknown_then_refused_once_settled(h, w, flow):
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    run = lambda key: _flow(h, w, flow, key)  # noqa: E731
    res = run("to-2")
    assert (res.outcome, res.error_code) == ("vendor_error", "VENDOR_TIMEOUT"), (res.outcome, res.error_code)
    look = run("to-2")  # the CRM's look-up while AutoCount may still be saving: still unknown, nothing sent
    assert (look.outcome, look.error_code) == ("vendor_error", "VENDOR_TIMEOUT"), (look.outcome, look.error_code)
    assert len(link_puts(h)) == 1
    age_actions(h, res)
    settled = run("to-2")
    assert (settled.outcome, settled.error_code) == ("refused", "OPERATION_NOT_APPLIED"), (
        settled.outcome, settled.error_code)
    assert len(link_puts(h)) == 1  # decided by a read, never by a second PUT
    fresh = run("to-2")  # released: the next press runs fresh
    assert fresh.outcome == "done" and len(link_puts(h)) == 2


@pytest.mark.parametrize("flow", ["split", "batch", "doc_batch"])
def test_s3_timeout_that_lands_after_the_answer_is_found_by_the_look_up(h, w, flow):
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    run = lambda key: _flow(h, w, flow, key)  # noqa: E731
    res = run("to-3")
    assert res.error_code == "VENDOR_TIMEOUT"
    # AutoCount commits the save after hapi answered (prod 20 Nov): the link row appears
    sent = link_puts(h)[0].body
    new_sent = next(r for r in sent["Details"] if not r.get("DtlKey"))
    kept = next((r for r in sent["Details"] if r.get("DtlKey")), None)
    h.vendor._edit("PO", {"DocKey": 7001, "Details": [r for r in (kept, new_sent) if r]})
    look = run("to-3")
    assert look.outcome == "done", (look.outcome, look.error_code, look.message)
    assert len(link_puts(h)) == 1


@pytest.mark.parametrize("flow", ["split", "batch", "doc_batch"])
def test_s3_timeout_and_the_read_fails_needs_attention(h, w, flow):
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    fail_po_reads_after_put(h)
    res = _flow(h, w, flow, "to-4")
    assert (res.outcome, res.error_code) == ("needs_attention", "VENDOR_TIMEOUT"), (res.outcome, res.error_code)
    assert len(link_puts(h)) == 1


def test_s3_a_lock_wait_is_still_a_refusal(h, w):
    h.vendor.refuse_json_next("PUT", EDIT, "Lock request time out period exceeded.")
    res = _batch(h, w, "to-5")
    assert (res.outcome, res.error_code) == ("vendor_error", "VENDOR_REFUSED")


# ============================== routes ===========================================================

@pytest.fixture
def gw(h, db, w):
    return Gw(h, db)


def test_route_close_superseded(client, h, gw, w):
    res = _parked_split(h, w, key="r-sup")
    age_actions(h, res)
    r = client.post(f"{PREFIX}/write-operations/{res.operation_id}/close-superseded", headers=gw.hdr("r-sup-c"),
                    json={"companyCode": "SRT"})
    assert r.status_code == 200, r.text
    assert (r.json()["outcome"], r.json()["errorCode"]) == ("refused", "SUPERSEDED")
    h.db.expire_all()
    assert h.db.query(AcWriteOperation).filter(AcWriteOperation.id == res.operation_id).one().status == "refused"


def test_route_resume_parked_split_answers_done(client, h, gw, w):
    res = _parked_split(h, w, key="r-res")
    r = client.post(f"{PREFIX}/write-operations/{res.operation_id}/resume", headers=gw.hdr("r-res-c"),
                    json={"companyCode": "SRT"})
    assert r.status_code == 200, r.text
    assert r.json()["outcome"] == "done"
    assert r.json()["document"] is not None


def test_route_unknown_operation_close_is_404(client, h, gw, w):
    r = client.post(f"{PREFIX}/write-operations/nope/close-superseded", headers=gw.hdr("r-404"),
                    json={"companyCode": "SRT"})
    assert r.status_code == 404


# ============================== review round 1 ===================================================



def test_review_partial_link_add_timeout_is_unknown_never_undone_at_once(h, w):
    """A partly received row: cut, then add the remainder. The add times out: no undo write, key kept."""
    reader = lambda kind, doc, r: Decimal(1) if r["DtlKey"] == w.p_free else Decimal(0)  # noqa: E731
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT, after=1)  # the second PUT = the add
    params = dict(w.params["link_row"], so_dtl_key=w.so_a)
    res = h.run("link_row", params, key="p-1", receipt_reader=reader)
    assert (res.outcome, res.error_code) == ("vendor_error", "VENDOR_TIMEOUT"), (res.outcome, res.error_code)
    assert len(puts(h)) == 2  # cut + the timed-out add, no undo
    look = h.run("link_row", params, key="p-1", receipt_reader=reader)
    assert (look.outcome, look.error_code) == ("vendor_error", "VENDOR_TIMEOUT")
    assert len(puts(h)) == 2  # a young look-up never writes
    age_actions(h, res)
    settled = h.run("link_row", params, key="p-1", receipt_reader=reader)
    assert settled.outcome in ("recovered", "refused"), (settled.outcome, settled.error_code)
    assert row(h, w.p_free)["Qty"] == 4  # only now, the add proven absent, the cut is undone


def test_review_a_timed_out_split_whose_look_up_breaks_is_parked_not_stuck(h, w, monkeypatch):
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    res = split(h, w, key="tb-x")
    assert res.error_code == "VENDOR_TIMEOUT"
    age_actions(h, res)

    real = ops_mod.OperationService._read_snapshot_doc
    state = {"boom": True}

    def once(self, *a, **kw):
        if state.pop("boom", False):
            raise RuntimeError("transient")
        return real(self, *a, **kw)

    monkeypatch.setattr(ops_mod.OperationService, "_read_snapshot_doc", once)
    look = split(h, w, key="tb-x")
    assert (look.outcome, look.error_code) == ("needs_attention", "VENDOR_TIMEOUT"), (look.outcome, look.error_code)
    out = resume(h, res)  # still reconcilable afterwards
    assert (out.outcome, out.error_code) == ("refused", "OPERATION_NOT_APPLIED"), (out.outcome, out.error_code)


def test_review_a_timed_out_link_counts_against_the_so_line(h, w):
    from modules.autocount.write_back.repository import OperationRepository

    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    res = split(h, w, key="ov-1")
    assert res.error_code == "VENDOR_TIMEOUT"
    held = OperationRepository(h.db).pending_link_qty(DEFAULT_TENANT_ID, h.company.id, w.so_a, None)
    assert held == Decimal(2)


def test_review_a_2xx_split_that_does_not_read_back_waits_before_absent(h, w):
    res = _parked_split(h, w, key="ok-lag")
    rows = h.vendor.find("PO", 7001)["Details"]  # the save "has not shown yet": undo it in the fake
    new = tied(h, w)[0]
    rows.remove(new)
    next(r for r in rows if r["DtlKey"] == w.p_free)["Qty"] = 4
    out = resume(h, res)
    assert out.outcome == "pending_verification", (out.outcome, out.error_code)  # not released yet


# ============================== review round 2 (kill-test pins "P", red tests "R") ================

PO_URL = f"{PREFIX}/documents/purchase-orders/7001"
ADD_URL = f"{PREFIX}/documents/purchase-orders/7001/lines"


def _op(h, key) -> AcWriteOperation:
    h.db.expire_all()
    return (h.db.query(AcWriteOperation)
            .filter(AcWriteOperation.idempotency_key == key, AcWriteOperation.company_id == h.company.id).one())


def _age_op(h, op_id):
    age_actions(h, SimpleNamespace(operation_id=op_id))


def _close(h, op_id):
    return h.ops().close_superseded(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=op_id)


def _gets_between(h, first, second) -> bool:
    calls = h.vendor.calls
    return any(c.method == "GET" and "purchaseorder" in c.leaf for c in calls[calls.index(first):calls.index(second)])


# ---- P1 (pin, K20): a half-applied split is never judged absent --------------------------------------

def test_p1_resume_half_applied_split_new_row_absent_kept_row_cut_needs_attention(h, w):
    res = _parked_split(h, w, key="p1")
    (new,) = tied(h, w)
    h.vendor.rows("PO", 7001).remove(new)  # the tied row is not there ...
    assert row(h, w.p_free)["Qty"] == 2  # ... but the kept row is still at its cut qty
    age_actions(h, res)
    before = len(puts(h))
    out = resume(h, res)
    assert (out.outcome, out.error_code) != ("refused", "OPERATION_NOT_APPLIED")
    assert out.outcome == "needs_attention", (out.outcome, out.error_code)
    assert len(puts(h)) == before


# ---- P2 (pin, K19): the tied row stands but something else moved -> a person looks -------------------

@pytest.mark.parametrize("moved", ["untouched_row", "header_note"])
def test_p2_resume_split_tied_row_stands_but_something_else_changed_needs_attention(h, w, moved):
    h.vendor.find("PO", 7001)["Note"] = "keep me"
    res = _parked_split(h, w, key=f"p2-{moved}")
    if moved == "untouched_row":
        next(r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == w.p_other)["Qty"] = 9
    else:
        h.vendor.find("PO", 7001)["Note"] = ""
    age_actions(h, res)
    before = len(puts(h))
    out = resume(h, res)
    assert out.outcome == "needs_attention", (out.outcome, out.error_code)
    assert len(puts(h)) == before


# ---- P4 (pin, K25): the document batch's new row takes the SO line date -------------------------------

def test_p4_doc_batch_new_row_takes_the_so_line_date_never_the_doc_date(h, w):
    res = _doc_batch(h, w, "p4")
    assert res.outcome == "done", (res.outcome, res.error_code)
    (link_put,) = link_puts(h)
    new = next(r for r in link_put.body["Details"] if not r.get("DtlKey"))
    assert new["DeliveryDate"][:10] == SO_DAY != "2026-11-04"
    assert tied(h, w)[0]["DeliveryDate"][:10] == SO_DAY


# ---- P5 (pin, K17): a close that loses the race to a claim closes nothing ------------------------------

@pytest.mark.parametrize("flip", ["in_progress", "done"])
def test_p5_close_superseded_never_closes_a_row_no_longer_parked(h, w, monkeypatch, flip):
    res = _parked_split(h, w, key=f"p5-{flip}")
    age_actions(h, res)
    real = ops_mod.OperationService._write_settled

    def racing(self, row_):
        settled = real(self, row_)  # the check passed ... then a resume claimed / finished it
        h.db.query(AcWriteOperation).filter(AcWriteOperation.id == row_.id).update(
            {"status": flip}, synchronize_session=False)
        h.db.commit()
        return settled

    monkeypatch.setattr(ops_mod.OperationService, "_write_settled", racing)
    out = _close(h, res.operation_id)
    assert out.error_code != "SUPERSEDED"
    stored = _op(h, f"p5-{flip}")
    assert stored.status == flip and stored.error_code != "SUPERSEDED"
    assert (stored.result_json or {}).get("errorCode") != "SUPERSEDED"
    if flip == "in_progress":
        assert out.error_code == "OPERATION_IN_PROGRESS"


# ---- R1 (security): a parked document primitive is never closed-superseded ----------------------------

def _broken_read_back(self, *a, **kw):
    raise DocReadError("READ_FAILED")


@pytest.mark.parametrize("prim", ["add_line", "edit_doc"])
def test_r1_close_superseded_refuses_a_parked_document_primitive_and_a_resend_never_writes_again(
        client, h, gw, w, monkeypatch, prim):
    key = f"r1-{prim}"
    send = (lambda: client.post(ADD_URL, headers=gw.hdr(key), json={
        "companyCode": "SRT", "line": {"itemCode": "ITEM-A", "uom": "UNIT", "qty": 3, "unitPrice": 5,
                                       "location": "BR1"}})) if prim == "add_line" else (
        lambda: client.patch(PO_URL, headers=gw.hdr(key), json={"companyCode": "SRT", "header": {"remark1": "x"}}))
    with monkeypatch.context() as patch:  # the PUT lands, its read-back cannot be read: parked
        patch.setattr(PrimitiveService, "_read_back", _broken_read_back)
        first = send()
    assert first.json()["outcome"] == "pending_verification", first.text
    parked = _op(h, key)
    _age_op(h, parked.id)
    rows_before, put_count = len(h.vendor.rows("PO", 7001)), len(puts(h))
    assert put_count == 1
    out = _close(h, parked.id)
    assert (out.outcome, out.error_code) == ("refused", "OPERATION_NOT_RESUMABLE"), (out.outcome, out.error_code)
    after = _op(h, key)
    assert after.status == "pending_verification" and after.error_code != "SUPERSEDED"
    assert (after.result_json or {}).get("errorCode") != "SUPERSEDED"
    again = send()  # the same key: looked up (landed = done), never written a second time
    assert len(puts(h)) == put_count, "a closed primitive released its key: the write was sent again"
    assert len(h.vendor.rows("PO", 7001)) == rows_before
    assert again.json()["outcome"] == "done", again.text


def test_r1_route_close_superseded_of_a_primitive_is_refused_not_resumable(client, h, gw, w, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(PrimitiveService, "_read_back", _broken_read_back)
        first = client.post(ADD_URL, headers=gw.hdr("r1-route"), json={
            "companyCode": "SRT", "line": {"itemCode": "ITEM-A", "uom": "UNIT", "qty": 3, "unitPrice": 5,
                                           "location": "BR1"}})
    assert first.json()["outcome"] == "pending_verification", first.text
    parked = _op(h, "r1-route")
    _age_op(h, parked.id)
    r = client.post(f"{PREFIX}/write-operations/{parked.id}/close-superseded", headers=gw.hdr("r1-route-c"),
                    json={"companyCode": "SRT"})
    assert r.json()["errorCode"] == "OPERATION_NOT_RESUMABLE", r.text
    assert _op(h, "r1-route").status == "pending_verification"


# ---- R2: closing a parked split whose tie still stands never reopens a second split -------------------

def test_r2_a_new_key_split_after_close_superseded_of_a_standing_tie_is_refused_row_already_linked(h, w):
    res = _parked_split(h, w, key="r2-1")
    assert len(tied(h, w)) == 1  # the parked split DID land: its tie stands in AutoCount
    age_actions(h, res, seconds=BUSY_WINDOW_SECONDS + 120)  # past the busy window too: only the tie can refuse
    closed = _close(h, res.operation_id)
    assert (closed.outcome, closed.error_code) == ("refused", "SUPERSEDED")
    before = len(puts(h))
    again = split(h, w, key="r2-2")  # a new press: same PO row, same SO line, same qty
    assert (again.outcome, again.error_code) == ("refused", "ROW_ALREADY_LINKED"), (again.outcome, again.error_code)
    assert len(puts(h)) == before, "a second split PUT was sent over a standing tie"
    assert len(tied(h, w)) == 1


# ---- R3: the timeout classifier judges AutoCount's raw text -------------------------------------------

def _vendor_says(h, body, status=500):
    original = h.vendor._route

    def route(method, leaf, call):
        if method == "PUT":
            return httpx.Response(status, json=body)
        return original(method, leaf, call)

    h.vendor._route = route


_GENERIC_BODY = {"Message": "An error has occurred."}
_TIMEOUT_BODIES = {
    "win32_top": dict(_GENERIC_BODY, ExceptionMessage="The wait operation timed out",
                      ExceptionType="System.ComponentModel.Win32Exception"),
    "sql_later_line": dict(_GENERIC_BODY, ExceptionMessage="Save failed.\r\n" + TIMEOUT_TEXT,
                           ExceptionType="System.Data.SqlClient.SqlException"),
    "sql_inner": dict(_GENERIC_BODY, ExceptionMessage="Save failed.", ExceptionType="AutoCount.Data.CriticalSqlException",
                      InnerException=dict(_GENERIC_BODY, ExceptionMessage=TIMEOUT_TEXT,
                                          ExceptionType="System.Data.SqlClient.SqlException")),
    "win32_inner": dict(_GENERIC_BODY, ExceptionMessage="Save failed.",
                        ExceptionType="System.Data.SqlClient.SqlException",
                        InnerException=dict(_GENERIC_BODY, ExceptionMessage="The wait operation timed out",
                                            ExceptionType="System.ComponentModel.Win32Exception")),
}


@pytest.mark.parametrize("flow", ["split", "batch"])
@pytest.mark.parametrize("shape", sorted(_TIMEOUT_BODIES))
def test_r3_an_autocount_timeout_in_any_shape_is_unknown_with_the_key_kept(h, w, shape, flow):
    _vendor_says(h, _TIMEOUT_BODIES[shape])
    res = _flow(h, w, flow, f"r3-{shape}")
    assert (res.outcome, res.error_code) == ("vendor_error", "VENDOR_TIMEOUT"), (res.outcome, res.error_code)
    assert len(link_puts(h)) == 1
    look = _flow(h, w, flow, f"r3-{shape}")  # the key is kept: the same answer, nothing sent
    assert (look.outcome, look.error_code) == ("vendor_error", "VENDOR_TIMEOUT")
    assert len(link_puts(h)) == 1


def test_r3_a_lock_wait_in_a_multi_line_sql_answer_is_still_a_refusal(h, w):
    _vendor_says(h, dict(_GENERIC_BODY, ExceptionMessage="Save failed.\r\nLock request time out period exceeded.",
                         ExceptionType="System.Data.SqlClient.SqlException"))
    res = _batch(h, w, "r3-lock")
    assert (res.outcome, res.error_code) == ("vendor_error", "VENDOR_REFUSED")


# ---- R4: a single-document primitive that timed out is reconciled, never replayed for ever -------------

def _send_prim(client, gw, prim, key):
    if prim == "add_line":
        return client.post(ADD_URL, headers=gw.hdr(key), json={
            "companyCode": "SRT", "line": {"itemCode": "ITEM-A", "uom": "UNIT", "qty": 3, "unitPrice": 5,
                                           "location": "BR1"}})
    return client.patch(PO_URL, headers=gw.hdr(key), json={"companyCode": "SRT", "header": {"remark1": "checked"}})


@pytest.mark.parametrize("prim", ["add_line", "edit_doc"])
def test_r4_timeout_nothing_saved_is_unknown_before_the_settle_time(client, h, gw, w, prim):
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    first = _send_prim(client, gw, prim, f"r4a-{prim}").json()
    assert (first["outcome"], first["errorCode"]) == ("vendor_error", "VENDOR_TIMEOUT"), first
    again = _send_prim(client, gw, prim, f"r4a-{prim}").json()
    assert (again["outcome"], again["errorCode"]) == ("vendor_error", "VENDOR_TIMEOUT"), again
    assert len(puts(h)) == 1


@pytest.mark.parametrize("prim", ["add_line", "edit_doc"])
def test_r4_timeout_nothing_saved_is_released_once_the_save_had_time(client, h, gw, w, prim):
    key = f"r4b-{prim}"
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    assert _send_prim(client, gw, prim, key).json()["errorCode"] == "VENDOR_TIMEOUT"
    stuck = _op(h, key)
    _age_op(h, stuck.id)
    again = _send_prim(client, gw, prim, key).json()
    assert (again["outcome"], again.get("errorCode")) != ("vendor_error", "VENDOR_TIMEOUT"), (
        "the timed-out write is replayed for ever", again)
    released = h.db.get(AcWriteOperation, stuck.id)
    h.db.refresh(released)
    assert released.idempotency_key != key and released.status in ("refused", "recovered"), (
        released.status, released.error_code)
    sent = puts(h)
    if len(sent) > 1:  # a fresh run may follow, but only after a read showed nothing
        assert _gets_between(h, sent[0], sent[1])


@pytest.mark.parametrize("prim", ["add_line", "edit_doc"])
def test_r4_timeout_and_the_write_landed_later_is_done_without_a_second_put(client, h, gw, w, prim):
    key = f"r4c-{prim}"
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    assert _send_prim(client, gw, prim, key).json()["errorCode"] == "VENDOR_TIMEOUT"
    h.vendor._edit("PO", puts(h)[0].body)  # AutoCount commits the save after hapi answered
    again = _send_prim(client, gw, prim, key).json()
    assert again["outcome"] == "done", again
    assert len(puts(h)) == 1


# ---- R5: who closed it, and when -----------------------------------------------------------------------

def test_r5_close_superseded_records_closed_at_and_closed_by(client, h, gw, w):
    res = _parked_split(h, w, key="r5")
    age_actions(h, res)
    r = client.post(f"{PREFIX}/write-operations/{res.operation_id}/close-superseded", headers=gw.hdr("r5-c"),
                    json={"companyCode": "SRT"})
    assert r.status_code == 200, r.text
    stored = _op(h, "r5").result_json
    assert stored.get("closedAt"), stored
    assert stored.get("closedBy"), stored
    assert str(gw.key.id) in str(stored["closedBy"]), stored["closedBy"]


# ---- R6: a resume that lost the claim to a close answers the closed answer ------------------------------

def test_r6_resume_that_loses_the_claim_to_a_close_answers_superseded_not_in_progress(h, w, monkeypatch):
    res = _parked_split(h, w, key="r6")
    age_actions(h, res)
    real_claim = OperationRepository.claim

    def racing(self, tenant_id, company_id, operation_id, from_statuses):
        _close(h, operation_id)  # the operator's close lands between the resume's read and its claim
        return real_claim(self, tenant_id, company_id, operation_id, from_statuses)

    monkeypatch.setattr(OperationRepository, "claim", racing)
    out = resume(h, res)
    assert (out.outcome, out.error_code) == ("refused", "SUPERSEDED"), (out.outcome, out.error_code)
    assert len(link_puts(h)) == 1


# ---- R7: the settle clock of an operation with no owned actions -----------------------------------------

def _legacy_parked(h, w, key, age_seconds):
    stamp = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    row_ = AcWriteOperation(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id=None, idempotency_key=key, request_hash="legacy",
        op="split_link", doc_type="PO", doc_key=7001, dtl_key=w.p_free, status="pending_verification",
        snapshot_json={"mode": "split", "links": [{"soDtlKey": w.so_a, "qty": "2"}]},  # no OWNED_ACTIONS marker
    )
    h.db.add(row_)
    h.db.commit()
    row_.created_at = row_.updated_at = stamp
    h.db.commit()
    return row_.id


def test_r7_a_freshly_parked_legacy_operation_is_not_settled(h, w):
    op_id = _legacy_parked(h, w, "r7-young", 5)
    out = _close(h, op_id)
    assert out.error_code != "SUPERSEDED", "closed while its write may still be saving"
    stored = h.db.get(AcWriteOperation, op_id)
    h.db.refresh(stored)
    assert stored.status == "pending_verification" and stored.error_code != "SUPERSEDED"


def test_r7_an_old_legacy_operation_is_settled_and_closes(h, w):
    op_id = _legacy_parked(h, w, "r7-old", ops_mod.LOOKUP_SETTLE_SECONDS + 120)
    out = _close(h, op_id)
    assert (out.outcome, out.error_code) == ("refused", "SUPERSEDED")


# ============================== review round 3 ====================================================

def _lines_of(out) -> List[dict]:
    return list((out.batch or {}).get("lines") or [])


def test_k21_resume_of_a_young_timed_out_doc_batch_chunk_waits_and_marks_nothing(h, w):
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    res = _doc_batch(h, w, "k21")
    assert (res.outcome, res.error_code) == ("vendor_error", "VENDOR_TIMEOUT"), (res.outcome, res.error_code)
    before = len(puts(h))
    out = resume(h, res)  # the chunk reads untouched, its write is younger than the settle time
    assert (out.outcome, out.error_code) == ("vendor_error", "VENDOR_TIMEOUT"), (out.outcome, out.error_code)
    assert len(puts(h)) == before
    assert not any(line.get("errorCode") == "OPERATION_NOT_APPLIED" or line.get("code") == "OPERATION_NOT_APPLIED"
                   for line in _lines_of(out)), _lines_of(out)
    stored = _op(h, "k21")
    assert stored.status == "vendor_error" and not stored.idempotency_key.count("released")
    again = _doc_batch(h, w, "k21")  # the key is still held
    assert (again.outcome, again.error_code) == ("vendor_error", "VENDOR_TIMEOUT")
    assert len(link_puts(h)) == 1


def _two_line_doc_batch(h, w, key):
    """Two PO rows, one chunk each (``max_lines_per_put`` 1): line 1 = p_free -> so_a, line 2 = p_other -> so_b."""
    return h.run("link_doc_batch", dict(doc_key=7001, max_lines_per_put=1, links=[
        dict(po_dtl_key=w.p_free, so_doc_key=7002, so_dtl_key=w.so_a, qty=1),
        dict(po_dtl_key=w.p_other, so_doc_key=7002, so_dtl_key=w.so_b, qty=1)]), key=key)


def _tied_to(h, so_dtl):
    return [r for r in h.vendor.rows("PO", 7001) if r.get("FromSODtlKey") == so_dtl]


def test_sec2_closing_a_partial_doc_batch_keeps_the_tie_of_its_timed_out_line(h, w):
    """Line 1 linked, line 2 timed out and landed later; the operator closes it: a new press cannot link line 2 again."""
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT, after=2)  # chunk 1 link + its restore land, chunk 2 times out
    res = _two_line_doc_batch(h, w, "sec2")
    assert res.error_code == "VENDOR_TIMEOUT", (res.outcome, res.error_code)
    h.vendor._edit("PO", link_puts(h)[1].body)  # AutoCount commits line 2 after hapi answered
    so_b_rows = len(_tied_to(h, w.so_b))
    assert so_b_rows >= 1
    age_actions(h, res, seconds=BUSY_WINDOW_SECONDS + 120)
    closed = _close(h, res.operation_id)
    assert (closed.outcome, closed.error_code) == ("refused", "SUPERSEDED"), (closed.outcome, closed.error_code)
    before = len(puts(h))
    again = _two_line_doc_batch(h, w, "sec2-new")
    assert len(puts(h)) == before, "a new press linked a line that already stands"
    assert len(_tied_to(h, w.so_b)) == so_b_rows
    assert again.outcome != "done", (again.outcome, again.error_code)


# ---- S3 / S4: a closed tie counts in the over-link sum until the staged index shows it ----------------

def _staged_index(h, rows):
    """Swap the staged over-link index of PO 7001 for ``rows`` = [(po_dtl_key, so_dtl_key, qty)]."""
    from modules.autocount.write_back.repository import PoSoLinkRepository

    PoSoLinkRepository(h.db).replace_for_po(
        DEFAULT_TENANT_ID, h.company.id, f"{h.company.database_name}:7001", rows)
    h.db.commit()


def _pending_qty(h, so_dtl):
    h.db.expire_all()
    return OperationRepository(h.db).pending_link_qty(DEFAULT_TENANT_ID, h.company.id, so_dtl, None)


def test_s3_a_closed_split_tie_counts_until_the_staged_index_shows_its_row(h, w):
    res = _parked_split(h, w, key="n5")
    (new,) = tied(h, w)
    known = {r["DtlKey"] for r in h.vendor.rows("PO", 7001)} - {new["DtlKey"]}
    age_actions(h, res)
    assert _close(h, res.operation_id).error_code == "SUPERSEDED"
    _staged_index(h, [])  # nothing of it staged yet
    assert _pending_qty(h, w.so_a) == Decimal(2)
    _staged_index(h, [(w.p_linked, w.so_a, Decimal(3))])  # an old row (known before the write) is not this tie
    assert _pending_qty(h, w.so_a) == Decimal(2)
    assert w.p_linked in known
    _staged_index(h, [(new["DtlKey"], w.so_a, Decimal(2))])  # the new row is staged: the index counts it
    assert _pending_qty(h, w.so_a) == Decimal(0)


def test_s3_a_closed_tie_has_no_time_window(h, w):
    res = _parked_split(h, w, key="n5-old")
    age_actions(h, res)
    assert _close(h, res.operation_id).error_code == "SUPERSEDED"
    h.db.expire_all()
    op = h.db.query(AcWriteOperation).filter(AcWriteOperation.id == res.operation_id).one()
    op.updated_at = datetime.now(timezone.utc) - timedelta(days=30)
    h.db.commit()
    _staged_index(h, [])
    assert _pending_qty(h, w.so_a) == Decimal(2)


def test_s4_a_closed_whole_row_link_keeps_its_qty_in_the_over_link_sum(h, w):
    state = fail_po_reads_after_put(h)
    params = dict(w.params["link_row"], so_dtl_key=w.so_a)
    res = h.run("link_row", params, key="s4-row")
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    state["on"] = False
    _staged_index(h, [])
    held = _pending_qty(h, w.so_a)
    assert held > 0
    age_actions(h, res)
    assert _close(h, res.operation_id).error_code == "SUPERSEDED"
    assert _pending_qty(h, w.so_a) == held  # the tie did not vanish with the close
    new_key = next(r["DtlKey"] for r in h.vendor.rows("PO", 7001)
                   if r.get("FromSODtlKey") == w.so_a and r["DtlKey"] not in (w.p_linked, w.p_free))
    _staged_index(h, [(new_key, w.so_a, held)])
    assert _pending_qty(h, w.so_a) == 0


# ---- K17b: the close's updated_at guard matters ------------------------------------------------------

def test_k17b_a_close_loses_to_a_resume_that_finished_parked_again_with_a_fresh_result(h, w, monkeypatch):
    res = _parked_split(h, w, key="k17b")
    age_actions(h, res)
    real = ops_mod.OperationService._write_settled
    fresh_result = {"outcome": "needs_attention", "errorCode": "RESUMED", "message": "fresh", "warnings": []}

    def racing(self, row_):
        settled = real(self, row_)
        h.db.query(AcWriteOperation).filter(AcWriteOperation.id == row_.id).update(
            {"status": "needs_attention", "error_code": "RESUMED", "result_json": fresh_result,
             "updated_at": datetime.now(timezone.utc) + timedelta(seconds=5)},  # a whole second later
            synchronize_session=False)
        h.db.commit()
        return settled

    monkeypatch.setattr(ops_mod.OperationService, "_write_settled", racing)
    out = _close(h, res.operation_id)
    assert out.error_code == "RESUMED", (out.outcome, out.error_code)
    stored = _op(h, "k17b")
    assert stored.status == "needs_attention" and stored.error_code == "RESUMED"
    assert stored.result_json == fresh_result


# ---- N3d: a non-English SqlException timeout, by number ---------------------------------------------

def test_n3d_a_sql_timeout_by_number_with_a_non_english_message_is_unknown(h, w):
    body = dict(_GENERIC_BODY, ExceptionMessage="Waktu tamat telah tamat tempoh.",
                ExceptionType="System.Data.SqlClient.SqlException", Number=-2)
    _vendor_says(h, body)
    res = _batch(h, w, "n3d")
    assert (res.outcome, res.error_code) == ("vendor_error", "VENDOR_TIMEOUT"), (res.outcome, res.error_code)
    assert len(link_puts(h)) == 1


# ---- N11: a Resume of a split stopped by the write gate leaves a guard_refused call-log row ----------

def test_n11_resume_of_a_parked_split_stopped_by_the_gate_logs_guard_refused(h, w, monkeypatch):
    res = _parked_split(h, w, key="n11")
    age_actions(h, res)
    assert [x for x in _logs(h) if x.outcome == "guard_refused"] == []
    _set(monkeypatch, env="development", books="db1,db3")
    _point_at(h, DB1)
    before = len(h.vendor.calls)
    out = resume(h, res)
    assert out.outcome == "pending_verification", (out.outcome, out.error_code)
    assert len(h.vendor.calls) == before
    refused = [x for x in _logs(h) if x.outcome == "guard_refused"]
    assert len(refused) == 1 and refused[0].error_code == "WRITE_NOT_ALLOWED", [x.error_code for x in refused]


# ---- round 4: the SEC2 merge's per-pair subtraction and row de-dup, and qty minus received -------------

def _same_so_doc_batch(h, w, key):
    """Two PO rows to the SAME SO line, one chunk each: line 1 = p_free -> so_a, line 2 = p_other -> so_a."""
    return h.run("link_doc_batch", dict(doc_key=7001, max_lines_per_put=1, links=[
        dict(po_dtl_key=w.p_free, so_doc_key=7002, so_dtl_key=w.so_a, qty=1),
        dict(po_dtl_key=w.p_other, so_doc_key=7002, so_dtl_key=w.so_a, qty=1)]), key=key)


@pytest.mark.parametrize("late", [True, False])
def test_r4a_closed_partial_doc_batch_to_one_so_line_pins_each_line_to_its_own_row(h, w, late):
    """Line 1 linked, line 2 (another PO row, same SO line, same qty) timed out. Closed. ``late``: line 2 landed
    after the answer (both lines stand) or never did (only line 1 stands)."""
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT, after=2)
    res = _same_so_doc_batch(h, w, "r4a")
    assert res.error_code == "VENDOR_TIMEOUT", (res.outcome, res.error_code)
    if late:
        h.vendor._edit("PO", link_puts(h)[1].body)
    stands = len(_tied_to(h, w.so_a))  # p_linked + line 1 (+ line 2 when it landed late)
    assert stands == (3 if late else 2), stands
    age_actions(h, res, seconds=BUSY_WINDOW_SECONDS + 120)
    assert _close(h, res.operation_id).error_code == "SUPERSEDED"
    sent = len(link_puts(h))
    _same_so_doc_batch(h, w, "r4a-new")
    if late:  # both lines stand: neither is linked again
        assert len(link_puts(h)) == sent, "a line that stands was linked again"
        assert len(_tied_to(h, w.so_a)) == stands
    else:  # line 1 stands (skipped), line 2 never landed: it is not hidden by line 1's row
        assert len(link_puts(h)) == sent + 1, "line 2 was refused although it never landed"
        assert len(_tied_to(h, w.so_a)) == stands + 1


def test_r4b_a_closed_part_received_row_link_counts_qty_minus_received(h, w):
    reader = lambda kind, doc, r: Decimal(1) if r["DtlKey"] == w.p_free else Decimal(0)  # noqa: E731
    state = fail_po_reads_after_put(h)
    params = dict(w.params["link_row"], so_dtl_key=w.so_a)
    res = h.run("link_row", params, key="r4b", receipt_reader=reader)
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    state["on"] = False
    _staged_index(h, [])
    held = _pending_qty(h, w.so_a)
    assert held == Decimal(3), held  # the row qty 4 less the 1 received
    age_actions(h, res)
    assert _close(h, res.operation_id).error_code == "SUPERSEDED"
    assert _pending_qty(h, w.so_a) == Decimal(3)


def test_r4c_a_closed_never_landed_tie_is_not_pinned_to_a_row_another_operation_made(h, w):
    """B (p_other -> so_a) timed out and never landed; A (p_free -> so_a, same qty) then linked; B is closed. A's
    new row is not B's tie: a new press of B's link must still run."""
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    lost = h.run("link_batch", dict(doc_key=7001, dtl_key=w.p_other, links=[
        dict(so_doc_key=7002, so_dtl_key=w.so_a, qty=1)]), key="r4c-b")
    assert lost.error_code == "VENDOR_TIMEOUT", (lost.outcome, lost.error_code)
    age_actions(h, lost, seconds=BUSY_WINDOW_SECONDS + 120)
    other = h.run("link_batch", dict(doc_key=7001, dtl_key=w.p_free, links=[
        dict(so_doc_key=7002, so_dtl_key=w.so_a, qty=1)]), key="r4c-a")
    assert other.outcome == "done", (other.outcome, other.error_code)
    assert _close(h, lost.operation_id).error_code == "SUPERSEDED"
    sent = len(link_puts(h))
    again = h.run("link_batch", dict(doc_key=7001, dtl_key=w.p_other, links=[
        dict(so_doc_key=7002, so_dtl_key=w.so_a, qty=1)]), key="r4c-c")
    assert again.outcome == "done", (again.outcome, again.error_code, again.batch)
    assert len(link_puts(h)) == sent + 1
