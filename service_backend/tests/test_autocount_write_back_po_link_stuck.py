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
from decimal import Decimal
from typing import Any, List

import httpx
import pytest

from app.main import app  # noqa: F401 - the gateway rig overrides dependencies on it
from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcWriteAction, AcWriteOperation
from modules.autocount.write_back import operations as ops_mod, payloads, service as service_mod
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw
from tests.test_autocount_write_back_link_batch import Rig
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


@pytest.mark.parametrize("flow", ["split", "batch"])
def test_s3_timeout_and_the_write_is_there_is_done(h, w, flow):
    h.vendor.apply_then_refuse_next("PUT", EDIT, TIMEOUT_TEXT)
    res = split(h, w, key="to-1") if flow == "split" else _batch(h, w, "to-1")
    assert (res.outcome, res.error_code) == ("done", None), (res.outcome, res.error_code, res.message)
    assert len(link_puts(h)) == 1


@pytest.mark.parametrize("flow", ["split", "batch"])
def test_s3_timeout_and_nothing_there_is_unknown_then_refused_once_settled(h, w, flow):
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    run = (lambda key: split(h, w, key=key)) if flow == "split" else (lambda key: _batch(h, w, key))
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


@pytest.mark.parametrize("flow", ["split", "batch"])
def test_s3_timeout_that_lands_after_the_answer_is_found_by_the_look_up(h, w, flow):
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    run = (lambda key: split(h, w, key=key)) if flow == "split" else (lambda key: _batch(h, w, key))
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


@pytest.mark.parametrize("flow", ["split", "batch"])
def test_s3_timeout_and_the_read_fails_needs_attention(h, w, flow):
    h.vendor.refuse_json_next("PUT", EDIT, TIMEOUT_TEXT)
    fail_po_reads_after_put(h)
    res = split(h, w, key="to-4") if flow == "split" else _batch(h, w, "to-4")
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


# ============================== s11: an SO line with no delivery date ============================
# db3 (CRM #2607 Mac pass): a change PO whose SO line has no date; the new tied row reads back 0001-01-01
# (the source PO row is dated). No date is sent, none is asked back, the read-back matches and the job ends.

EMPTY = "0001-01-01T00:00:00"
PO_DAY = "2026-11-27T00:00:00"


@pytest.fixture
def nd(h):
    h.delete_on()
    h.vendor.locations.append(SUB)
    world = World(h, so_over={"DeliveryDate": EMPTY})
    for r in h.vendor.rows("PO", 7001):
        r["DeliveryDate"] = PO_DAY  # the source PO rows are dated; the SO line is not
    return world


def _sent_dates(h) -> List[Any]:
    """Every DeliveryDate a PUT asked for on a new tied row, or on a tied row's restore (a row sent with "D"
    is the old row going away, not a date asked for)."""
    out = []
    for call in puts(h):
        for r in (call.body or {}).get("Details") or []:
            if r.get("FullTransferOption") == payloads.DELETE_ROW:
                continue
            if "DeliveryDate" in r and (not r.get("DtlKey") or r.get("FromSODtlKey") or r.get("FromDocType") == "SO"
                                        or r.get("FromDocDtlKey")):
                out.append(r["DeliveryDate"])
    return out


def _final(h, res) -> AcWriteOperation:
    h.db.expire_all()
    return h.db.get(AcWriteOperation, res.operation_id)


def _no_date(value) -> bool:
    return payloads.day_of(value) is None


def test_s11_split_no_so_date_sends_none_expects_none_and_is_done(h, nd):
    res = split(h, nd)
    assert (res.outcome, res.error_code) == ("done", None), (res.outcome, res.error_code, res.message)
    (link_put,) = link_puts(h)
    new = next(r for r in link_put.body["Details"] if not r.get("DtlKey"))
    assert _no_date(new.get("DeliveryDate")), new.get("DeliveryDate")
    assert all(_no_date(d) for d in _sent_dates(h)), _sent_dates(h)
    (tied_row,) = tied(h, nd)
    assert _no_date(tied_row["DeliveryDate"])
    assert _final(h, res).status not in ("pending_verification", "needs_attention", "in_progress")


def test_s11_split_whole_row_no_so_date_is_done(h, nd):
    res = split(h, nd, key="s11-all", qty=4)
    assert (res.outcome, res.error_code) == ("done", None), (res.outcome, res.error_code, res.message)
    assert all(_no_date(d) for d in _sent_dates(h)), _sent_dates(h)


def test_s11_link_row_no_so_date_is_done(h, nd):
    res = h.run("link_row", nd.params["link_row"], key="s11-row")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    assert all(_no_date(d) for d in _sent_dates(h)), _sent_dates(h)


def test_s11_batch_no_so_date_is_done(h, nd):
    res = h.run("link_batch", dict(doc_key=7001, dtl_key=nd.p_free, links=[
        dict(so_doc_key=7002, so_dtl_key=nd.so_a, qty=1)]), key="s11-batch")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    assert all(_no_date(d) for d in _sent_dates(h)), _sent_dates(h)


def test_s11_change_unlink_then_link_no_so_date_finishes(h, nd):
    first = split(h, nd, key="s11-c1")
    assert first.outcome == "done", (first.outcome, first.error_code)
    gone = h.run("unlink_row", dict(doc_key=7001, dtl_key=first.detail["DtlKey"]), key="s11-c2")
    assert gone.outcome in ("done", "recovered"), (gone.outcome, gone.error_code)
    again = split(h, nd, key="s11-c3")
    assert (again.outcome, again.error_code) == ("done", None), (again.outcome, again.error_code, again.message)
    for res in (first, gone, again):
        assert _final(h, res).status not in ("pending_verification", "needs_attention", "in_progress")


def test_s11_readback_of_a_dateless_tied_split_row_matches(h, nd):
    before = h.vendor.find("PO", 7001)
    import copy
    before = copy.deepcopy(before)
    res = split(h, nd, key="s11-rb")
    assert res.outcome == "done"
    (link_put,) = link_puts(h)
    after = h.vendor.find("PO", 7001)
    assert service_mod.verify_split(before, after, link_put.body, nd.p_free)


def test_s11_resume_parked_dateless_split_is_done(h, nd):
    state = fail_po_reads_after_put(h)
    res = split(h, nd, key="s11-park")
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    state["on"] = False
    out = resume(h, res)
    assert (out.outcome, out.error_code) == ("done", None), (out.outcome, out.error_code, out.message)
    assert len(link_puts(h)) == 1
    assert all(_no_date(d) for d in _sent_dates(h)), _sent_dates(h)


def test_s11_relink_to_a_dateless_so_line_sends_no_date_and_is_done(h, nd):
    so = h.vendor.find("SO", 7002)
    for r in so["Details"]:
        r["DeliveryDate"] = EMPTY
    res = h.run("relink_row", nd.params["relink_row"], key="s11-relink")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    assert all(_no_date(d) for d in _sent_dates(h)), _sent_dates(h)


def test_s11_link_row_takes_the_so_line_date_when_it_has_one(h, w):
    res = h.run("link_row", w.params["link_row"], key="s11-dated")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    new_rows = [r for c in link_puts(h) for r in c.body["Details"] if not r.get("DtlKey")]
    assert new_rows and all(r["DeliveryDate"][:10] == SO_DAY for r in new_rows)
    assert tied(h, w)[-1]["DeliveryDate"][:10] == SO_DAY


def test_s11_a_failed_relink_recovers_the_old_row_with_its_own_date(h, nd):
    """Review s11: only the NEW tied row takes the SO line's date. When a relink's replace lands wrong, the
    recovery puts the OLD row back as it was, with its own date (never the new SO line's, here none)."""
    from tests.test_autocount_write_back_operations import drop_new_row_once
    so = h.vendor.find("SO", 7002)
    so["Details"][1]["DeliveryDate"] = EMPTY  # the new SO line (so_b) has no date
    drop_new_row_once(h)
    res = h.run("relink_row", nd.params["relink_row"], key="s11-recover")
    assert res.outcome == "recovered", (res.outcome, res.error_code, res.message)
    re_add = [r for c in link_puts(h)[1:] for r in c.body["Details"] if not r.get("DtlKey")]
    assert re_add and all(r["FromDocDtlKey"] == nd.so_a for r in re_add)
    assert all(r.get("DeliveryDate") == PO_DAY for r in re_add), [r.get("DeliveryDate") for r in re_add]
