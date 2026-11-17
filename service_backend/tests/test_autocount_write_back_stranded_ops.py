"""Lane AUTOCOUNT-STRANDED-OPS: an operation stranded ``in_progress`` heals itself.

Prod case: an unlink's request died between the PO read and the snapshot commit (the worker was
killed), so ``_guarded``'s finally never ran and the op stayed ``in_progress`` with no snapshot. Every
resend under the same key answered ``OPERATION_IN_PROGRESS`` for ever.

- C.a: a same-key resend of a STALE in_progress op reconciles it (expired before the key is settled).
- C.b: a pending op with NO snapshot ends ``recovered`` / ``OPERATION_NOT_APPLIED`` (no write can come
  before the snapshot commit): the key is freed and the resend runs fresh.
- C.c: an API-start sweep flips every stale in_progress op to pending.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcWriteAction, AcWriteOperation
from tests.test_autocount_write_back_operations import (  # noqa: F401
    KEY_ID,
    OpHarness,
    World,
    db,
    h,
    w,
)
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


class _WorkerKilled(BaseException):
    """Stands in for gunicorn's SIGKILL / an OOM kill: nothing below ``_guarded`` gets to run."""


def _kill_before_snapshot(h, monkeypatch, op="unlink_row", params=None, key="idem-strand"):
    """Run ``op`` and kill the worker after the PO read, before the snapshot commit."""
    from modules.autocount.write_back.operations import OperationService

    def killed(self, *a, **kw):
        raise _WorkerKilled()

    with monkeypatch.context() as patch:  # scoped: the fixtures' own patches (host pin) stay
        patch.setattr(OperationService, "_guards", killed)
        with pytest.raises(_WorkerKilled):
            h.ops().run(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id=KEY_ID,
                        idempotency_key=key, op=op, params=params)
    # a killed worker never ran its finally: drop whatever the dead session still held
    h.db.rollback()
    h.db.expire_all()
    row = (h.db.query(AcWriteOperation)
           .filter(AcWriteOperation.idempotency_key == key, AcWriteOperation.tenant_id == DEFAULT_TENANT_ID)
           .one())
    assert row.status == "in_progress" and row.snapshot_json is None
    return row


def _age(h, row, seconds):
    old = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    row.created_at = old
    row.updated_at = old
    h.db.commit()


def _window():
    from modules.autocount.write_back.frame import BUSY_WINDOW_SECONDS

    return BUSY_WINDOW_SECONDS


# ---- C.a + C.b: the same press (same key, same body) self-heals ---------------------------------------------------

def test_stale_same_key_resend_of_a_no_snapshot_op_runs_fresh_and_is_done(h, w, monkeypatch):
    stranded = _kill_before_snapshot(h, monkeypatch, params=w.params["unlink_row"])
    assert h.vendor.writes() == []  # died before any write
    _age(h, stranded, _window() + 60)
    res = h.run("unlink_row", w.params["unlink_row"], key="idem-strand")
    assert (res.outcome, res.error_code) == ("done", None)
    assert res.operation_id != stranded.id  # a fresh run under the freed key
    h.db.expire_all()
    old = h.db.get(AcWriteOperation, stranded.id)
    assert (old.status, old.error_code) == ("recovered", "OPERATION_NOT_APPLIED")
    assert old.idempotency_key != "idem-strand"  # kept for history, re-keyed


def test_young_same_key_resend_still_answers_in_progress(h, w, monkeypatch):
    stranded = _kill_before_snapshot(h, monkeypatch, params=w.params["unlink_row"])
    _age(h, stranded, 5)
    res = h.run("unlink_row", w.params["unlink_row"], key="idem-strand")
    assert (res.outcome, res.error_code) == ("refused", "OPERATION_IN_PROGRESS")
    assert h.vendor.writes() == []


def test_stale_same_key_resend_with_another_body_is_still_a_conflict(h, w, monkeypatch):
    stranded = _kill_before_snapshot(h, monkeypatch, params=w.params["unlink_row"])
    _age(h, stranded, _window() + 60)
    res = h.run("link_row", w.params["link_row"], key="idem-strand")
    assert (res.outcome, res.error_code) == ("refused", "IDEMPOTENCY_CONFLICT")
    assert h.vendor.writes() == []


# ---- C.b: settle / resume a pending op with no snapshot -----------------------------------------------------------

def test_resume_of_a_pending_op_with_no_snapshot_is_recovered_not_applied(h, w, monkeypatch):
    stranded = _kill_before_snapshot(h, monkeypatch, params=w.params["unlink_row"])
    stranded.status = "pending_verification"
    h.db.commit()
    out = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=stranded.id)
    assert (out.outcome, out.error_code) == ("recovered", "OPERATION_NOT_APPLIED")
    assert h.vendor.writes() == []
    h.db.expire_all()
    assert h.db.get(AcWriteOperation, stranded.id).status == "recovered"


def test_internal_error_before_the_snapshot_frees_the_key_on_resend(h, w, monkeypatch):
    """An exception before the snapshot commit ends pending/INTERNAL_ERROR with no snapshot: the
    resend under the same key reconciles and runs fresh instead of replaying the pending answer."""
    from modules.autocount.write_back.operations import OperationService

    def boom(self, *a, **kw):
        raise RuntimeError("guard blew up")

    with monkeypatch.context() as patch:
        patch.setattr(OperationService, "_guards", boom)
        first = h.run("unlink_row", w.params["unlink_row"], key="idem-err")
    assert (first.outcome, first.error_code) == ("pending_verification", "INTERNAL_ERROR")
    again = h.run("unlink_row", w.params["unlink_row"], key="idem-err")
    assert (again.outcome, again.error_code) == ("done", None)
    assert again.operation_id != first.operation_id


def test_a_no_snapshot_op_with_a_recorded_write_is_not_settled_as_not_applied(h, w, monkeypatch):
    """Defence in depth: a write action recorded under the op means something may have reached
    AutoCount, so the no-snapshot shortcut never applies."""
    stranded = _kill_before_snapshot(h, monkeypatch, params=w.params["unlink_row"])
    stranded.status = "pending_verification"
    h.db.add(AcWriteAction(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, action="edit_doc",
                           doc_type="PO", doc_key=7001, outcome="pending_verification", request_json={},
                           operation_id=stranded.id))
    h.db.commit()
    out = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=stranded.id)
    assert out.outcome == "pending_verification"
    h.db.expire_all()
    assert h.db.get(AcWriteOperation, stranded.id).status == "pending_verification"


def test_a_pending_op_with_a_snapshot_still_resumes_the_normal_way(h, w):
    h.vendor.timeout_next("PUT", "editpurchaseorderbydockey")
    first = h.run("link_row", w.params["link_row"], key="idem-snap")
    assert first.outcome == "pending_verification"
    out = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=first.operation_id)
    assert out.outcome not in ("needs_attention", "pending_verification")


# ---- C.c: crash sweep at API start --------------------------------------------------------------------------------

def test_startup_sweep_flips_only_stale_in_progress_ops(h, w, monkeypatch):
    from modules.autocount.write_back.operations import sweep_stranded_operations

    stale = _kill_before_snapshot(h, monkeypatch, params=w.params["unlink_row"], key="k-stale")
    _age(h, stale, _window() + 60)
    young = _kill_before_snapshot(h, monkeypatch, op="spo_unlink_row", params=w.params["spo_unlink_row"],
                                   key="k-young")  # another document: a run on the PO would expire the stale op itself
    _age(h, young, 5)
    assert sweep_stranded_operations(h.db) == 1
    h.db.expire_all()
    assert h.db.get(AcWriteOperation, stale.id).status == "pending_verification"
    assert h.db.get(AcWriteOperation, young.id).status == "in_progress"
    # updated_at kept: the flip must not make the row look young
    assert h.db.get(AcWriteOperation, stale.id).updated_at < datetime.now(timezone.utc) - timedelta(seconds=_window())
    # then C.b: the next same-key press runs fresh
    res = h.run("unlink_row", w.params["unlink_row"], key="k-stale")
    assert (res.outcome, res.error_code) == ("done", None)


def test_startup_sweep_is_wired_into_the_module_boot():
    from modules.autocount import bootstrap

    assert hasattr(bootstrap, "sweep_stranded_write_operations")
