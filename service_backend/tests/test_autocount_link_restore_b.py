"""Plan 65 part B (RED): AC-65-29..32.

* AC-65-29 / 30: ``unlink_row`` (merge and replace path) and ``relink_row`` delete the linked row; hapi cannot
  write FOCQty (probe P2), so a row carrying FOC is refused ``FOC_ON_ROW`` before any PUT (same check as the batch).
* AC-65-31 / 32: a request that died mid-way leaves an op ``in_progress``; Resume now expires a STALE one
  (older than the busy window) for that document first, keeping its ``updated_at``; a young one is still respected.

The fake vendor carries FOCQty on reads (``realistic_vendor`` only forbids WRITING it). Docstring "control" = passes
on 778e2ed8 by design. Helpers come from ``test_autocount_link_restore``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcWriteOperation
from modules.autocount.write_back.frame import BUSY_WINDOW_SECONDS
from tests.test_autocount_link_restore import (  # noqa: F401
    NOTE, NO_DATE, PO_DATE, PO_KEY, SO_KEY, Rig65, day, incident_state, landed_link, puts, resume, rtf,
)
from tests.test_autocount_write_back_operations import OpHarness, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


@pytest.fixture
def rig(h):
    return Rig65(h)


# ================================ AC-65-29 / 30 FOC_ON_ROW on unlink and relink =====================

def linked_with_foc(h, rig, foc: float, *, mergeable: bool = False) -> int:
    """A real whole-row link of the free row to the undated SO row, then the FOC set on the linked row as the
    read would carry it. ``mergeable``: a free row with the same item, unit, location, price and date exists
    (an unlink would merge into it); else the row sits at a location no free row has (an unlink replaces it)."""
    res = h.run("link_row", dict(doc_key=PO_KEY, dtl_key=rig.free_a, so_doc_key=SO_KEY, so_dtl_key=rig.so_undated),
                key="b-link")
    assert res.outcome == "done", (res.outcome, res.error_code)
    (row,) = rig.linked(rig.so_undated)
    row.update(FOCQty=foc, UnitPrice=2.5, Discount="")
    if mergeable:
        row.update(Location="HQ", DeliveryDate=PO_DATE)  # matches the free rows (HQ, 2.5, 2026-11-26)
    else:
        row.update(Location="BRW-AM", DeliveryDate=PO_DATE)
    return row["DtlKey"]


@pytest.mark.parametrize("mergeable", [True, False], ids=["merge-path", "replace-path"])
def test_ac_65_29_unlink_of_a_linked_row_carrying_foc_is_refused_foc_on_row_with_no_put(h, rig, mergeable):
    key = linked_with_foc(h, rig, 1.0, mergeable=mergeable)
    writes = len(h.vendor.writes())
    res = h.run("unlink_row", dict(doc_key=PO_KEY, dtl_key=key), key="b-unlink")
    assert res.outcome == "refused" and res.error_code == "FOC_ON_ROW", (res.outcome, res.error_code)
    assert len(h.vendor.writes()) == writes  # zero PUTs
    assert rig.row(key) is not None and rig.row(key)["FOCQty"] == 1.0  # the row and its FOC are untouched


@pytest.mark.parametrize("mergeable", [True, False], ids=["merge-path", "replace-path"])
def test_ac_65_29_control_unlink_of_a_linked_row_without_foc_runs_as_today(h, rig, mergeable):
    """control: FOCQty 0 unlinks as before, on the merge path and on the replace path."""
    key = linked_with_foc(h, rig, 0.0, mergeable=mergeable)
    res = h.run("unlink_row", dict(doc_key=PO_KEY, dtl_key=key), key="b-unlink-ok")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert rig.row(key) is None and not rig.linked(rig.so_undated)
    (_old, target), = res.replaced_lines
    assert (target in (rig.src, rig.free_b)) == mergeable, (mergeable, res.replaced_lines)  # the path under test


def test_ac_65_30_relink_of_a_row_carrying_foc_is_refused_foc_on_row_with_no_put(h, rig):
    key = linked_with_foc(h, rig, 1.0)
    writes = len(h.vendor.writes())
    res = h.run("relink_row", dict(doc_key=PO_KEY, dtl_key=key, so_doc_key=SO_KEY, so_dtl_key=rig.so_dated),
                key="b-relink")
    assert res.outcome == "refused" and res.error_code == "FOC_ON_ROW", (res.outcome, res.error_code)
    assert len(h.vendor.writes()) == writes
    assert rig.row(key) is not None and rig.linked(rig.so_undated)  # still linked to the old SO row


def test_ac_65_30_control_relink_of_a_row_without_foc_runs_as_today(h, rig):
    """control: FOCQty 0 relinks as before."""
    key = linked_with_foc(h, rig, 0.0)
    res = h.run("relink_row", dict(doc_key=PO_KEY, dtl_key=key, so_doc_key=SO_KEY, so_dtl_key=rig.so_dated),
                key="b-relink-ok")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(rig.linked(rig.so_dated)) == 1 and not rig.linked(rig.so_undated)


# ================================ AC-65-31 / 32 a stale in_progress op ==============================

def stuck_op(h, age_seconds: float, *, snapshot=None) -> str:
    """A request that died mid-way: another op of the same PO document left ``in_progress`` (tonight's stuck unlink:
    op ``unlink_row``, no snapshot), ``updated_at`` ``age_seconds`` ago."""
    stamp = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    row = AcWriteOperation(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id="key-1", idempotency_key="b-stuck",
        request_hash="h", op="unlink_row", doc_type="PO", doc_key=PO_KEY, dtl_key=None, status="in_progress",
        snapshot_json=snapshot, updated_at=stamp)
    h.db.add(row)
    h.db.commit()
    return row.id


def op_row(h, op_id: str) -> AcWriteOperation:
    h.db.expire_all()
    return h.db.query(AcWriteOperation).filter(AcWriteOperation.id == op_id).one()


STALE, YOUNG = BUSY_WINDOW_SECONDS + 3600, 60


def test_ac_65_31_resume_expires_a_stale_in_progress_op_of_the_po_and_runs_as_normal(h, rig):
    first = landed_link(h, rig)
    incident_state(h, rig, first)
    stuck = stuck_op(h, STALE)
    before = op_row(h, stuck).updated_at
    sent_before = len(puts(h))
    res = resume(h, first)
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert len(puts(h)) - sent_before == 1  # the one restore PUT
    after = op_row(h, stuck)
    assert after.status == "pending_verification"
    assert after.updated_at == before  # the age is kept (the busy window keeps meaning)


def test_ac_65_31_control_a_young_in_progress_op_still_holds_the_po_resume_is_doc_busy(h, rig):
    """control: inside the window the other op is respected: DOC_BUSY, nothing sent, both rows untouched."""
    first = landed_link(h, rig)
    incident_state(h, rig, first)
    young = stuck_op(h, YOUNG)
    before_young, before_link = op_row(h, young).updated_at, op_row(h, first.operation_id).updated_at
    writes, calls = len(h.vendor.writes()), len(h.vendor.calls)
    res = resume(h, first)
    assert res.outcome == "refused" and res.error_code == "DOC_BUSY", (res.outcome, res.error_code)
    assert len(h.vendor.writes()) == writes and len(h.vendor.calls) == calls
    assert op_row(h, young).status == "in_progress" and op_row(h, young).updated_at == before_young
    assert op_row(h, first.operation_id).status == "needs_attention"
    assert op_row(h, first.operation_id).updated_at == before_link


def test_ac_65_32_resume_of_the_stale_in_progress_op_itself_expires_it_and_answers_from_its_stored_state(h, rig):
    stuck = stuck_op(h, STALE)
    before = op_row(h, stuck).updated_at
    res = resume(h, SimpleNamespace(operation_id=stuck))
    assert res.error_code != "OPERATION_IN_PROGRESS", (res.outcome, res.error_code)
    # BL-SS-368 (lane AUTOCOUNT-STRANDED-OPS): no snapshot = no write could have happened, so the expired op
    # settles recovered / OPERATION_NOT_APPLIED (its key is then free), still with nothing sent
    assert (res.outcome, res.error_code) == ("recovered", "OPERATION_NOT_APPLIED"), (res.outcome, res.error_code)
    assert h.vendor.calls == []
    row = op_row(h, stuck)
    assert row.status == "recovered" and before is not None


def test_ac_65_32_control_a_young_in_progress_op_still_answers_operation_in_progress(h, rig):
    """control: inside the window the op is still running as far as anyone can tell."""
    young = stuck_op(h, YOUNG)
    before = op_row(h, young).updated_at
    res = resume(h, SimpleNamespace(operation_id=young))
    assert res.outcome == "refused" and res.error_code == "OPERATION_IN_PROGRESS", (res.outcome, res.error_code)
    assert h.vendor.calls == []
    row = op_row(h, young)
    assert row.status == "in_progress" and row.updated_at == before


# ================================ AC-65-34 a recovered answer always releases its key (B3) ==========

import hashlib  # noqa: E402
import json  # noqa: E402


def stored_op(h, rig, status: str, code, *, key: str = "b-same") -> "tuple[AcWriteOperation, dict]":
    """A stored ``unlink_row`` op (same key id, key and params as the resend) of a real linked row, settled as
    ``status`` / ``code``. The vendor is untouched, so a fresh run still has the row to unlink."""
    res = h.run("link_row", dict(doc_key=PO_KEY, dtl_key=rig.free_a, so_doc_key=SO_KEY, so_dtl_key=rig.so_undated),
                key="b-setup-link")
    assert res.outcome == "done", (res.outcome, res.error_code)
    (row,) = rig.linked(rig.so_undated)
    params = dict(doc_key=PO_KEY, dtl_key=row["DtlKey"])
    digest = hashlib.sha256(json.dumps({"op": "unlink_row", "params": params}, sort_keys=True,
                                       default=str).encode()).hexdigest()
    op = AcWriteOperation(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id="key-1", idempotency_key=key,
        request_hash=digest, op="unlink_row", doc_type="PO", doc_key=PO_KEY, dtl_key=row["DtlKey"], status=status,
        error_code=code, result_json={"outcome": status, "errorCode": code, "message": "", "warnings": []})
    h.db.add(op)
    h.db.commit()
    return op, params


@pytest.mark.parametrize("code", ["ROW_MISMATCH", "RESUMED", None, "NOT_APPLIED"],
                         ids=["row-mismatch", "resumed", "no-code", "constant-name"])
def test_ac_65_34_a_resend_of_a_recovered_unlink_with_any_stored_code_runs_fresh_and_releases_the_old_key(
        h, rig, code):
    old, params = stored_op(h, rig, "recovered", code)
    old_id, writes = old.id, len(h.vendor.writes())
    res = h.run("unlink_row", params, key="b-same")
    assert res.operation_id != old_id and res.outcome == "done", (res.operation_id == old_id, res.outcome,
                                                                  res.error_code)  # a NEW op ran
    assert len(h.vendor.writes()) > writes  # the vendor PUT(s) of the fresh run
    released = op_row(h, old_id)
    assert released.idempotency_key == f"b-same{chr(31)}released{chr(31)}{old_id}"


def test_ac_65_34_control_recovered_operation_not_applied_releases_as_today(h, rig):
    """control: the value the code really uses (``OPERATION_NOT_APPLIED``) already releases."""
    old, params = stored_op(h, rig, "recovered", "OPERATION_NOT_APPLIED")
    old_id = old.id
    res = h.run("unlink_row", params, key="b-same")
    assert res.operation_id != old_id and res.outcome == "done", (res.outcome, res.error_code)
    assert op_row(h, old_id).idempotency_key == f"b-same{chr(31)}released{chr(31)}{old_id}"


def test_ac_65_34_control_a_stored_done_replays_its_answer_with_zero_vendor_calls(h, rig):
    """control: a landed operation is never re-run."""
    old, params = stored_op(h, rig, "done", None)
    calls = len(h.vendor.calls)
    res = h.run("unlink_row", params, key="b-same")
    assert res.operation_id == old.id and res.outcome == "done", (res.operation_id, res.outcome, res.error_code)
    assert len(h.vendor.calls) == calls
    assert op_row(h, old.id).idempotency_key == "b-same"


def test_ac_65_34_control_a_stored_needs_attention_replays_and_starts_no_new_op(h, rig):
    """control: an open operation is a person's to resolve, never silently re-run under the same key."""
    old, params = stored_op(h, rig, "needs_attention", "COLLATERAL_CHANGE")
    calls = len(h.vendor.calls)
    res = h.run("unlink_row", params, key="b-same")
    assert res.operation_id == old.id and res.outcome == "needs_attention", (res.operation_id, res.outcome)
    assert len(h.vendor.calls) == calls
    assert op_row(h, old.id).idempotency_key == "b-same"
