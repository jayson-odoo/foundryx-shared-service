"""Plan 69 slice A: the document batch (AC-69-01..06), operation ``link_doc_batch``, route
``POST /api/v1/autocount/po-links/doc-batch``.

Every listed row of ONE PO document, each to its SO rows, in ONE operation: per chunk of
``MAX_LINES_PER_PUT`` new rows ONE link PUT and at most ONE restore PUT (the PO is still read before each
link PUT). Each line answers its own ``result``: linked / skipped / failed / checking.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Tuple

import pytest

from app.main import app  # noqa: F401
from tests.test_autocount_write_back_gateway import _hdr
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw
from tests.test_autocount_write_back_link_batch import Rig, puts
from tests.test_autocount_write_back_operations import OpHarness, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

ROUTE = f"{PREFIX}/po-links/doc-batch"
OP = "link_doc_batch"
EDIT = "EditPurchaseOrderbydockey"


@pytest.fixture
def rig(h):
    return Rig(h)


@pytest.fixture
def gw(h, db, rig):
    return Gw(h, db)


# (poDtlKey, soDocKey, soDtlKey, qty)
Link = Tuple[int, int, int, Any]


def params(links: List[Link], doc_key: int = 7001, **extra) -> Dict[str, Any]:
    return dict(doc_key=doc_key, links=[dict(po_dtl_key=p, so_doc_key=d, so_dtl_key=k, qty=q)
                                        for p, d, k, q in links], **extra)


def body(links: List[Link], doc_key: int = 7001) -> Dict[str, Any]:
    return {"companyCode": "SRT", "poDocKey": doc_key, "links": [
        {"poDtlKey": p, "soDocKey": d, "soDtlKey": k, "qty": q} for p, d, k, q in links]}


def two_rows(rig) -> List[Link]:
    """Row p_free (qty 4): two SO rows of SO 7005, 1 each (2 stay free). Row p_other (qty 4): both rows of SO
    7006, 2 each (the whole row: it goes)."""
    w = rig.w
    return [(w.p_free, 7005, rig.s5[0], 1), (w.p_free, 7005, rig.s5[1], 1),
            (w.p_other, 7006, rig.s6[0], 2), (w.p_other, 7006, rig.s6[1], 2)]


def linked(h, doc_key=7001) -> Dict[int, Dict[str, Any]]:
    return {r["FromSODtlKey"]: r for r in h.vendor.rows("PO", doc_key) if r.get("FromSODtlKey")}


def results(res) -> List[str]:
    return [line["result"] for line in res.batch["lines"]]


# ============================== AC-69-01 one PUT per PO document ==================================

def test_ac_69_01_two_rows_four_links_is_one_link_put_and_one_restore_put(h, rig):
    res = h.run(OP, params(two_rows(rig)), key="d-1")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    sent = puts(h)
    assert len(sent) == 2, [c.body for c in sent]
    first = sent[0]
    new = [r for r in first.body["Details"] if r["DtlKey"] == 0]
    assert len(new) == 4
    assert {r.get("FullTransferOption") for r in first.body["Details"] if r["DtlKey"] == rig.w.p_other} == {"D"}
    kept = next(r for r in first.body["Details"] if r["DtlKey"] == rig.w.p_free)
    assert Decimal(str(kept["Qty"])) == 2
    got = linked(h)
    for so_row in (rig.s5[0], rig.s5[1], rig.s6[0], rig.s6[1]):
        assert so_row in got
        assert got[so_row]["UnitPrice"] == 5.0  # the restore ran on every new row (both PO rows)
    assert results(res) == ["linked"] * 4
    assert all(line["newPoDtlKey"] == got[line["soDtlKey"]]["DtlKey"] for line in res.batch["lines"])
    assert res.batch["freeLines"] == [{"poDtlKey": rig.w.p_free, "qty": "2"}]


def test_ac_69_01_the_po_is_read_before_the_link_put(h, rig):
    h.run(OP, params(two_rows(rig)), key="d-read")
    calls = h.vendor.calls
    put_at = calls.index(puts(h)[0])
    assert any(c.method == "GET" and "purchaseorder" in c.leaf for c in calls[:put_at])


# ============================== AC-69-02 no cap: chunks ==========================================

def test_ac_69_02_a_batch_longer_than_a_chunk_is_split_and_all_linked(h, rig):
    res = h.run(OP, params(two_rows(rig), max_lines_per_put=2), key="d-chunks")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    assert len(puts(h)) == 4  # 2 chunks x (link PUT + restore PUT)
    assert results(res) == ["linked"] * 4
    assert len(linked(h)) >= 4


def test_ac_69_02_one_row_with_45_links_runs_in_two_puts_of_new_rows(h, rig):
    po = h.seed_doc("PO", 7101, [_line("ITEM-A", 50, 5.0, "BR1")])
    so = h.seed_doc("SO", 7105, [_line("ITEM-A", 10, 5.0, "HQ") for _ in range(45)])
    po_dtl = po["Details"][0]["DtlKey"]
    res = h.run(OP, params([(po_dtl, 7105, r["DtlKey"], 1) for r in so["Details"]], doc_key=7101), key="d-45")
    assert res.outcome == "done", (res.outcome, res.error_code, res.message)
    link_puts = [c for c in puts(h) if any(r["DtlKey"] == 0 for r in c.body["Details"])]
    assert [sum(1 for r in c.body["Details"] if r["DtlKey"] == 0) for c in link_puts] == [40, 5]
    assert results(res) == ["linked"] * 45
    assert res.batch["freeLines"] == [{"poDtlKey": po_dtl, "qty": "5"}]


# ============================== AC-69-03 a bad line is skipped and named ==========================

def test_ac_69_03_a_row_on_an_spo_skips_its_lines_and_the_rest_links(h, rig):
    links = two_rows(rig) + [(rig.w.p_spo, 7005, rig.s5[2], 1)]
    res = h.run(OP, params(links), key="d-spo")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert results(res) == ["linked"] * 4 + ["skipped"]
    assert res.batch["lines"][4]["code"] == "ROW_ON_SPO"


def test_ac_69_03_two_po_rows_cannot_take_more_than_the_so_row_outstanding(h, rig):
    w = rig.w  # SO 7006 row 0 has qty 10: 4 + 4 = 8 fits, then 3 more does not
    h.seed_doc("PO", 7101, [_line("ITEM-A", 4, 5.0, "BR1"), _line("ITEM-A", 4, 5.0, "BR1"),
                            _line("ITEM-A", 4, 5.0, "BR1")])
    rows = [r["DtlKey"] for r in h.vendor.rows("PO", 7101)]
    res = h.run(OP, params([(rows[0], 7006, rig.s6[0], 4), (rows[1], 7006, rig.s6[0], 4),
                            (rows[2], 7006, rig.s6[0], 3)], doc_key=7101), key="d-out")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert results(res) == ["linked", "linked", "skipped"]
    assert res.batch["lines"][2]["code"] == "QTY_ABOVE_OUTSTANDING"
    assert w  # World is seeded (PO 7001) but untouched


def test_ac_69_03_every_line_skipped_is_refused_and_nothing_sent(h, rig):
    res = h.run(OP, params([(rig.w.p_free, 7005, 999999, 1)]), key="d-none")
    assert (res.outcome, res.error_code) == ("refused", "ALL_LINKS_SKIPPED")
    assert h.vendor.writes() == []
    assert results(res) == ["skipped"]


# ============================== AC-69-04 a refused chunk =========================================

def test_ac_69_04_chunk_two_refused_keeps_chunk_one_and_fails_only_its_own_lines(h, rig):
    h.vendor.refuse_json_next("PUT", EDIT, "Lock request time out period exceeded.", after=2)
    res = h.run(OP, params(two_rows(rig), max_lines_per_put=2), key="d-ref2")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert results(res) == ["linked", "linked", "failed", "failed"]
    assert "Lock request time out" in res.batch["lines"][2]["message"]
    assert rig.s6[0] not in linked(h)


def test_ac_69_04_chunk_two_refused_then_unsent_chunks_are_not_sent(h, rig):
    h.vendor.refuse_json_next("PUT", EDIT, "refused", after=0)
    res = h.run(OP, params(two_rows(rig), max_lines_per_put=1), key="d-ref1")
    assert res.outcome == "vendor_error" and res.error_code == "VENDOR_REFUSED"
    assert [(x["result"], x["code"]) for x in res.batch["lines"]] == [
        ("failed", "VENDOR_REFUSED"), ("failed", "NOT_SENT"), ("failed", "NOT_SENT"), ("failed", "NOT_SENT")]
    assert len(puts(h)) == 1


def test_ac_69_04_a_refused_first_chunk_releases_the_key_and_try_again_links(h, rig):
    h.vendor.refuse_json_next("PUT", EDIT, "Lock request time out period exceeded.")
    first = h.run(OP, params(two_rows(rig)), key="d-again")
    assert first.outcome == "vendor_error"
    again = h.run(OP, params(two_rows(rig)), key="d-again")
    assert again.outcome == "done", (again.outcome, again.error_code)
    assert results(again) == ["linked"] * 4


# ============================== unknown outcome -> resume =========================================

def test_a_timed_out_link_put_is_checking_and_resume_finds_nothing_landed(h, rig):
    h.vendor.timeout_next("PUT", EDIT)
    res = h.run(OP, params(two_rows(rig)), key="d-to")
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    assert results(res) == ["checking"] * 4
    back = h.ops().resume(tenant_id=h.company.tenant_id, company_id=h.company.id, operation_id=res.operation_id)
    assert (back.outcome, back.error_code) == ("recovered", "OPERATION_NOT_APPLIED"), (back.outcome, back.error_code)


def test_a_landed_link_put_answered_with_a_bare_500_is_finished_by_resume_with_one_restore(h, rig):
    h.vendor.apply_then_500_next("PUT", EDIT)
    res = h.run(OP, params(two_rows(rig)), key="d-500")
    assert res.outcome == "pending_verification", (res.outcome, res.error_code)
    back = h.ops().resume(tenant_id=h.company.tenant_id, company_id=h.company.id, operation_id=res.operation_id)
    assert back.outcome == "done", (back.outcome, back.error_code, back.message)
    assert len(puts(h)) == 2  # the link PUT once (never re-sent) + one restore
    assert [line["result"] for line in back.batch["lines"]] == ["linked"] * 4
    assert all(linked(h)[k]["UnitPrice"] == 5.0 for k in (rig.s5[0], rig.s6[1]))


def test_a_pending_doc_batch_holds_its_rows_against_another_link(h, rig):
    h.vendor.timeout_next("PUT", EDIT)
    res = h.run(OP, params(two_rows(rig)), key="d-hold")
    assert res.outcome == "pending_verification"
    other = h.run("link_batch", dict(doc_key=7001, dtl_key=rig.w.p_other, links=[
        dict(so_doc_key=7005, so_dtl_key=rig.s5[2], qty=1)]), key="d-hold-2")
    assert other.outcome == "refused", (other.outcome, other.error_code)


# ============================== route =============================================================

def test_ac_69_01_route_answers_every_line(client, h, gw, rig):
    r = client.post(ROUTE, json=body(two_rows(rig)), headers=gw.hdr("d-route"))
    assert r.status_code == 200, r.text
    ans = r.json()
    assert ans["outcome"] == "done" and [x["result"] for x in ans["lines"]] == ["linked"] * 4
    assert ans["freeLines"] == [{"poDtlKey": rig.w.p_free, "qty": "2"}]
    assert ans["linkedAt"] and ans["requestedAt"] and ans["finishedAt"]
    got = client.get(f"{PREFIX}/write-operations/{ans['operationId']}?companyCode=SRT", headers=_hdr(gw.plain))
    assert got.status_code == 200 and [x["result"] for x in got.json()["lines"]] == ["linked"] * 4


def test_route_rejects_a_repeated_pair_with_zero_puts(client, h, gw, rig):
    links = two_rows(rig)[:1] * 2
    r = client.post(ROUTE, json=body(links), headers=gw.hdr("d-dup"))
    assert r.status_code == 422, r.text
    assert h.vendor.writes() == []


def test_route_without_the_write_key_sends_nothing(client, h, gw, rig):
    r = client.post(ROUTE, json=body(two_rows(rig)))
    assert r.status_code == 401
    assert h.vendor.writes() == []


# ============================== the db3 probe suite (plan 69 D4): db3 only =========================

def _run_bulk(h):
    from app.models import DEFAULT_TENANT_ID
    from modules.autocount.write_back import runner

    h.vendor.stamp_created = True
    return runner.run_bulk_suite(h.db, tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                                 creditor_code="400-N004", debtor_code="301-B018", run_tag="T69", **h.factories())


@pytest.mark.parametrize("env", ["production", "development"])
def test_the_bulk_probe_suite_refuses_db1_before_any_request(h, monkeypatch, env):
    from tests.test_autocount_plan63_gate import DB1, _point_at, _set

    _set(monkeypatch, env=env, books="db1,db3")
    _point_at(h, DB1)
    with pytest.raises(Exception) as ei:
        _run_bulk(h)
    assert getattr(ei.value, "code", None) == "WRITE_NOT_ALLOWED", repr(ei.value)
    h.no_http()


def test_control_the_bulk_probe_suite_runs_on_db3_and_the_doc_batch_is_one_link_put(h, monkeypatch):
    from tests.test_autocount_plan63_gate import _set

    _set(monkeypatch, env="production", books="db1,db3")
    result = _run_bulk(h)
    by_id = {c.case_id: c for c in result.cases}
    assert set(by_id) == {"R00", "R01", "F01", "F02"}
    assert h.vendor.calls, "the control suite sent no request, so the refusal test proves nothing"
    assert by_id["F02"].status == "PASS", by_id["F02"].observed


def test_resume_finishes_only_the_chunk_in_doubt_and_leaves_later_chunks_not_sent(h, rig):
    h.vendor.apply_then_500_next("PUT", EDIT)
    res = h.run(OP, params(two_rows(rig), max_lines_per_put=2), key="d-resume-2")
    assert res.outcome == "pending_verification"
    assert [x["result"] for x in res.batch["lines"]] == ["checking", "checking", "failed", "failed"]
    back = h.ops().resume(tenant_id=h.company.tenant_id, company_id=h.company.id, operation_id=res.operation_id)
    assert back.outcome == "done", (back.outcome, back.error_code)
    assert [(x["result"], x["code"]) for x in back.batch["lines"]] == [
        ("linked", None), ("linked", None), ("failed", "NOT_SENT"), ("failed", "NOT_SENT")]
    assert len(puts(h)) == 2  # the first chunk's link PUT + its restore; the second chunk never sent


def test_resending_the_whole_list_after_a_partial_result_never_links_a_landed_line_twice(h, rig):
    h.vendor.refuse_json_next("PUT", EDIT, "refused", after=2)
    first = h.run(OP, params(two_rows(rig), max_lines_per_put=2), key="d-part")
    assert [x["result"] for x in first.batch["lines"]] == ["linked", "linked", "failed", "failed"]
    again = h.run(OP, params(two_rows(rig), max_lines_per_put=2), key="d-part-2")  # the CRM resends everything
    assert [(x["result"], x["code"]) for x in again.batch["lines"]] == [
        ("skipped", "ALREADY_LINKED"), ("skipped", "ALREADY_LINKED"), ("linked", None), ("linked", None)]
    on_so = [r for r in h.vendor.rows("PO", 7001) if r.get("FromSODtlKey") in (rig.s5[0], rig.s5[1])]
    assert len(on_so) == 2  # still one PO row per SO row


def test_the_guard_reads_stop_at_the_deadline_and_nothing_is_sent(h, rig, monkeypatch):
    from modules.autocount.write_back import operations

    svc = h.ops()
    real = operations.OperationService._line_skip

    def slow(self, *a, **kw):
        self._op_deadline = 0.0  # the clock ran past the operation deadline during the guard reads
        return real(self, *a, **kw)

    monkeypatch.setattr(operations.OperationService, "_line_skip", slow)
    res = h.run(OP, params(two_rows(rig)), key="d-deadline", svc=svc)
    assert res.outcome in ("pending_verification", "refused", "recovered"), (res.outcome, res.error_code)
    assert h.vendor.writes() == []
