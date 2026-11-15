"""Lane AUTOCOUNT-SS-POLOCK (RED first): the per-PO-document write lock.

Acceptance criteria: ``documentation/plans/sprint-5/ss-autocount-po-lock.md`` (POL-01..06). The same PO row
linked to two DIFFERENT SO rows at overlapping times is serialised per PO document (the per-SO-row lock alone
never sees the two callers meet). SQLite takes no advisory lock, so the operation-level tests drive a spy /
an in-process lock; the real Postgres lock is exercised at the bottom when ``TEST_POSTGRES_URL`` is set.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List

import pytest

from app.main import app  # noqa: F401
from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcWriteAction, AcWriteOperation
from modules.autocount.write_back.link_lock import SoRowBusy
from modules.autocount.write_back.service import WriteBackService
from tests.test_autocount_write_back_link_batch import Rig, puts
from tests.test_autocount_write_back_operations import KEY_ID, OpHarness, World, db, h  # noqa: F401
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

OP = "link_batch"


@pytest.fixture
def rig(h):
    return Rig(h)


def _stored(h, key: str) -> int:
    h.db.expire_all()
    return h.db.query(AcWriteOperation).filter(AcWriteOperation.idempotency_key == key).count()


def _during_first_po_get(h, fn) -> List[Any]:
    """Run ``fn`` once, while the first caller's fresh PO read is on the wire (overlapping callers)."""
    original = h.vendor._route
    out: List[Any] = []

    def route(method, leaf, call):
        if method == "GET" and "purchaseorder" in leaf and not out:
            out.append(None)
            out[0] = fn()
        return original(method, leaf, call)

    h.monkeypatch.setattr(h.vendor, "_route", route)
    return out


def _second(h, rig, so_dtl_key: int, key: str) -> Any:
    other = h.session_factory()
    try:
        return h.run(OP, rig.params([(7006, so_dtl_key, 1)]), key=key, svc=h.ops(db=other))
    finally:
        other.close()


# ============================== POL-01 two overlapping batches, one PO row ========================

def test_pol_01_two_overlapping_batches_on_one_po_row_onto_different_so_rows_make_exactly_one_put(h, rig):
    second = _during_first_po_get(h, lambda: _second(h, rig, rig.s6[1], "pl-b"))
    first = h.run(OP, rig.params([(7006, rig.s6[0], 1)]), key="pl-a")
    assert first.outcome == "done", (first.outcome, first.error_code)
    assert second and second[0].outcome == "refused" and second[0].error_code == "DOC_BUSY", second
    assert second[0].operation_id is None
    batch_puts = [c for c in puts(h) if any(r.get("DtlKey") == 0 for r in c.body["Details"])]
    assert len(batch_puts) == 1, [c.body for c in puts(h)]  # exactly one link PUT reached AutoCount
    assert _stored(h, "pl-b") == 0  # DOC_BUSY is never stored under the key
    again = h.run(OP, rig.params([(7006, rig.s6[1], 1)]), key="pl-b")  # the same key runs fresh
    assert again.error_code != "DOC_BUSY", (again.outcome, again.error_code)


def test_pol_04_a_plan_55_link_of_the_same_po_row_while_a_batch_runs_is_busy_with_no_put(h, rig):
    """POL-04: the standalone (plan 55) path counts the in_progress operation on the same PO."""

    def plan55():
        other = h.session_factory()
        try:
            return WriteBackService(other, **h.factories()).link(
                tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=7001, po_dtl_key=rig.w.p_free,
                so_doc_key=7006, so_dtl_key=rig.s6[1], qty=Decimal(1))
        finally:
            other.close()

    second = _during_first_po_get(h, plan55)
    first = h.run(OP, rig.params([(7006, rig.s6[0], 1)]), key="pl-c")
    assert first.outcome == "done", (first.outcome, first.error_code)
    assert second and second[0].outcome == "refused" and second[0].error_code == "DOC_BUSY", second
    batch_puts = [c for c in puts(h) if any(r.get("DtlKey") == 0 for r in c.body["Details"])]
    assert len(batch_puts) == 1, [c.body for c in puts(h)]


def test_pol_04_the_split_link_operation_is_not_busy_on_its_own_row(h):
    """Control: the plan 55 flow that an operation runs (split_link) excludes its own in_progress row."""
    w = World(h)
    h.delete_on()
    res = h.run("split_link", dict(po_doc_key=7001, po_dtl_key=w.p_free, so_doc_key=7002, so_dtl_key=w.so_b,
                                   qty=1), key="pl-d")
    assert res.outcome == "done", (res.outcome, res.error_code)


# ============================== POL-02 / 03 which locks, order, release ===========================

class _Recorder:
    """A spy for ``link_locks`` / ``so_row_locks`` that records (enter/exit, tokens, PUTs so far)."""

    def __init__(self, h, busy: Iterable[str] = ()) -> None:
        self.h = h
        self.events: List[Any] = []
        self.busy = set(busy)
        self.open = 0

    def tokens(self, po, so) -> List[str]:
        return [f"po:{k}" for k in sorted(set(po))] + [f"so:{k}" for k in sorted(set(so))]

    def link_locks(self, db, company_id, *, po_doc_keys=(), so_dtl_keys=()):
        return self._cm(self.tokens(list(po_doc_keys), list(so_dtl_keys)))

    def so_row_locks(self, db, company_id, so_dtl_keys):
        return self._cm(self.tokens([], list(so_dtl_keys)))

    @contextmanager
    def _cm(self, tokens):
        if self.busy & set(tokens):
            self.events.append(("busy", tokens))
            raise SoRowBusy()
        self.open += 1
        self.events.append(("enter", tokens, len(puts(self.h))))
        try:
            yield
        finally:
            self.open -= 1
            self.events.append(("exit", tokens, len(puts(self.h))))

    def install(self) -> "_Recorder":
        import modules.autocount.write_back.operations as operations
        import modules.autocount.write_back.service as service

        for mod in (operations, service):
            self.h.monkeypatch.setattr(mod, "link_locks", self.link_locks)
            self.h.monkeypatch.setattr(mod, "so_row_locks", self.so_row_locks)
        return self

    def entered(self) -> List[List[str]]:
        return [e[1] for e in self.events if e[0] == "enter"]


def test_pol_02_the_batch_takes_the_po_lock_first_then_the_so_rows_and_holds_the_po_lock_past_every_put(h, rig):
    rec = _Recorder(h).install()
    res = h.run(OP, rig.params(rig.three()), key="pl-e")
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert rec.entered()[0] == ["po:7001"], rec.events  # PO document first
    assert rec.entered()[1] == [f"so:{k}" for k in sorted(rig.s5)], rec.events  # then the SO rows
    po_exit = [e for e in rec.events if e[0] == "exit" and e[1] == ["po:7001"]]
    assert po_exit and po_exit[-1][2] == len(puts(h)) == 2, rec.events  # held past PUT 1 AND the restore PUT
    assert rec.events[-1][1] == ["po:7001"] and rec.open == 0  # released last, nothing left open


@pytest.mark.parametrize("op", ["link_row", "unlink_row", "relink_row"])
def test_pol_02_every_po_row_operation_takes_the_po_lock(h, op):
    h.delete_on()
    w = World(h)
    rec = _Recorder(h).install()
    res = h.run(op, w.params[op], key=f"pl-{op}")
    assert res.outcome in ("done", "recovered", "refused"), (res.outcome, res.error_code)
    assert rec.entered() and rec.entered()[0][0] == "po:7001", rec.events
    assert rec.open == 0


def test_pol_02_spo_operations_take_no_po_lock(h):
    h.delete_on()
    w = World(h)
    rec = _Recorder(h).install()
    h.run("spo_unlink_row", w.params["spo_unlink_row"], key="pl-spo")
    assert not any(t.startswith("po:") for tokens in rec.entered() for t in tokens), rec.events


def test_pol_02_the_plan_55_relocate_and_unlink_take_the_po_lock(h):
    h.delete_on()
    w = World(h)
    rec = _Recorder(h).install()
    svc = WriteBackService(h.db, **h.factories())
    svc.relocate(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=7001, po_dtl_key=w.p_linked)
    svc.unlink(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=7001, po_dtl_key=w.p_linked)
    assert [t for t in rec.entered() if t == ["po:7001"]] and len(rec.entered()) >= 2, rec.events
    assert rec.open == 0


def test_pol_02_a_busy_po_document_is_doc_busy_with_no_http_and_the_key_stays_usable(h, rig):
    rec = _Recorder(h, busy=["po:7001"]).install()
    res = h.run(OP, rig.params(rig.three()), key="pl-f")
    assert res.outcome == "refused" and res.error_code == "DOC_BUSY", (res.outcome, res.error_code)
    assert h.vendor.writes() == [] and h.vendor.gets() == []  # nothing read, nothing sent
    assert _stored(h, "pl-f") == 0
    rec.busy.clear()
    again = h.run(OP, rig.params(rig.three()), key="pl-f")
    assert again.outcome == "done", (again.outcome, again.error_code)


def test_pol_02_a_busy_po_document_refuses_the_plan_55_link_with_no_put(h):
    w = World(h)
    _Recorder(h, busy=["po:7001"]).install()
    res = WriteBackService(h.db, **h.factories()).link(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=7001, po_dtl_key=w.p_free,
        so_doc_key=7002, so_dtl_key=w.so_b, qty=Decimal(2))
    assert res.outcome == "refused" and res.error_code == "DOC_BUSY", (res.outcome, res.error_code)
    assert h.vendor.writes() == []
    h.db.expire_all()
    assert h.db.query(AcWriteAction).filter(AcWriteAction.outcome == "in_flight").count() == 0


def test_pol_03_the_po_lock_is_released_when_the_body_raises(h, rig, monkeypatch):
    import modules.autocount.write_back.operations as operations

    rec = _Recorder(h).install()

    def boom(*a, **k):
        raise RuntimeError("injected")

    monkeypatch.setattr(operations.OperationService, "_batch_locked", boom)
    res = h.run(OP, rig.params(rig.three()), key="pl-g")
    assert res.error_code == "INTERNAL_ERROR", (res.outcome, res.error_code)
    assert rec.open == 0 and rec.events[-1][0] == "exit", rec.events


def test_pol_02_resume_takes_the_po_lock_and_a_busy_lock_leaves_the_row_resumable(h, rig):
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    first = h.run(OP, rig.params(rig.three()), key="pl-h")
    assert first.outcome == "pending_verification", (first.outcome, first.error_code)
    rec = _Recorder(h, busy=["po:7001"]).install()
    busy = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=first.operation_id)
    assert busy.outcome == "refused" and busy.error_code == "DOC_BUSY", (busy.outcome, busy.error_code)
    assert h.operation(first).status == "pending_verification"  # untouched: still resumable
    rec.busy.clear()
    res = h.ops().resume(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, operation_id=first.operation_id)
    assert rec.entered() and rec.entered()[0] == ["po:7001"], rec.events
    assert res.outcome in ("recovered", "done"), (res.outcome, res.error_code)
    assert rec.open == 0


# ============================== POL-05 PO-side pending qty ========================================

def _age(h, res) -> None:
    row = h.operation(res)
    row.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)  # past the busy window
    h.db.commit()


def test_pol_05_a_pending_batch_that_did_not_land_counts_against_the_po_row_free_qty(h, rig):
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")  # PUT 1 never reached AutoCount: outcome unknown
    first = h.run(OP, rig.params(rig.three()), key="pl-i")  # 3 of the row's 4
    assert first.outcome == "pending_verification", (first.outcome, first.error_code)
    _age(h, first)
    before = len(puts(h))
    second = h.run(OP, rig.params([(7006, rig.s6[0], 2)]), key="pl-j")  # 2 > the 1 left free
    assert second.outcome == "refused" and second.error_code == "ALL_LINKS_SKIPPED", (
        second.outcome, second.error_code)
    assert [s["code"] for s in second.batch["skipped"]] == ["QTY_ABOVE_FREE"], second.batch
    assert len(puts(h)) == before


def test_pol_05_a_pending_batch_that_landed_is_not_counted_twice(h, rig):
    h.vendor.apply_then_500_next("PUT", "EditPurchaseOrderbydockey")  # PUT 1 landed, answered 500
    first = h.run(OP, rig.params(rig.three()), key="pl-k")
    assert first.outcome == "pending_verification", (first.outcome, first.error_code)
    _age(h, first)
    second = h.run(OP, rig.params([(7006, rig.s6[0], 1)]), key="pl-l")  # the 1 the landed PUT left free
    assert second.outcome == "done", (second.outcome, second.error_code, second.batch)


# ============================== POL-06 refusals release, DOC_BUSY never replayed ==================

def test_pol_06_a_definite_refusal_releases_its_key_and_the_resend_runs_fresh(h, rig):
    first = h.run(OP, rig.params([(7006, rig.s6[0], 99)]), key="pl-m")  # above outstanding: every line skipped
    assert first.outcome == "refused" and first.error_code == "ALL_LINKS_SKIPPED", (first.outcome, first.error_code)
    again = h.run(OP, rig.params([(7006, rig.s6[0], 1)]), key="pl-m")  # fixed, same key
    assert again.outcome == "done", (again.outcome, again.error_code)


# ============================== the real Postgres lock ============================================

PG_URL = os.environ.get("TEST_POSTGRES_URL")
pg = pytest.mark.skipif(not PG_URL, reason="TEST_POSTGRES_URL unset (CI has no Postgres)")


class _PgSession:
    """The bit of a Session ``link_locks`` reads: ``get_bind()``."""

    def __init__(self, engine) -> None:
        self.engine = engine

    def get_bind(self):
        return self.engine


@pytest.fixture
def pg_db(monkeypatch):
    from sqlalchemy import create_engine

    from modules.autocount.write_back import link_lock

    monkeypatch.setattr(link_lock, "WAIT_SECONDS", 0.5)
    monkeypatch.setattr(link_lock, "_engines", {})
    engine = create_engine(PG_URL)
    yield _PgSession(engine)
    for e in link_lock._engines.values():
        e.dispose()
    engine.dispose()


def _held_tokens(engine) -> int:
    from sqlalchemy import text

    with engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")).scalar()


def _in_thread(fn) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    def run():
        try:
            out["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            out["error"] = exc

    t = threading.Thread(target=run)
    t.start()
    t.join(10)
    return out


@pg
def test_pol_pg_a_held_po_lock_makes_a_second_caller_busy_after_the_wait_whatever_its_so_row(pg_db):
    from modules.autocount.write_back.link_lock import link_locks

    with link_locks(pg_db, "c1", po_doc_keys=[7001], so_dtl_keys=[11]):
        def other():
            with link_locks(pg_db, "c1", po_doc_keys=[7001], so_dtl_keys=[22]):  # a DIFFERENT SO row
                return "got"

        out = _in_thread(other)
        assert isinstance(out.get("error"), SoRowBusy), out
        other_doc = _in_thread(lambda: _enter(link_locks(pg_db, "c1", po_doc_keys=[7002])))
        assert other_doc.get("value") == "got", other_doc  # another PO document is not blocked
    assert _held_tokens(pg_db.engine) == 0


def _enter(cm) -> str:
    with cm:
        return "got"


@pytest.mark.skipif(not PG_URL, reason="TEST_POSTGRES_URL unset (CI has no Postgres)")
def test_pol_pg_the_lock_is_released_on_an_exception_and_after_a_timed_out_wait(pg_db):
    from modules.autocount.write_back.link_lock import link_locks

    with pytest.raises(RuntimeError):
        with link_locks(pg_db, "c1", po_doc_keys=[7001], so_dtl_keys=[11]):
            raise RuntimeError("boom")
    assert _held_tokens(pg_db.engine) == 0
    with link_locks(pg_db, "c1", so_dtl_keys=[22]):  # hold the SO row so the next take times out half-way
        out = _in_thread(lambda: _enter(link_locks(pg_db, "c1", po_doc_keys=[7001], so_dtl_keys=[22])))
        assert isinstance(out.get("error"), SoRowBusy), out
        free = _in_thread(lambda: _enter(link_locks(pg_db, "c1", po_doc_keys=[7001])))
        assert free.get("value") == "got", free  # the PO lock won before the timeout was given back
    assert _held_tokens(pg_db.engine) == 0


@pg
def test_pol_pg_a_nested_take_reuses_the_held_connection_and_releases_only_its_own_locks(pg_db):
    from modules.autocount.write_back.link_lock import link_locks, so_row_locks

    with link_locks(pg_db, "c1", po_doc_keys=[7001], so_dtl_keys=[11]):
        with link_locks(pg_db, "c1", po_doc_keys=[7001], so_dtl_keys=[11]):  # the plan 55 split link inside
            pass  # re-entrant: no wait, no busy
        with so_row_locks(pg_db, "c1", [33]):
            pass
        held = _in_thread(lambda: _enter(link_locks(pg_db, "c1", po_doc_keys=[7001])))
        assert isinstance(held.get("error"), SoRowBusy), held  # the outer level still holds the PO
        freed = _in_thread(lambda: _enter(so_row_locks(pg_db, "c1", [33])))
        assert freed.get("value") == "got", freed  # the nested level gave its own lock back
    assert _held_tokens(pg_db.engine) == 0


# ============================== review round 1 ====================================================

def _pending_op(h, key: str, op: str, dtl_key: int, snapshot: Dict[str, Any], status="pending_verification"):
    row = AcWriteOperation(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id=KEY_ID, idempotency_key=key, request_hash="x",
        op=op, doc_type="PO", doc_key=7001, dtl_key=dtl_key, status=status, snapshot_json=snapshot,
        updated_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    h.db.add(row)
    h.db.commit()
    return row


def test_pol_05_a_pending_part_row_link_row_counts_against_the_free_qty(h, rig):
    """A link_row below the row qty runs as the split: its snapshot is a split snapshot."""
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    first = h.run("link_row", dict(doc_key=7001, dtl_key=rig.w.p_free, so_doc_key=7005, so_dtl_key=rig.s5[0], qty=3),
                  key="pl-n")
    assert first.outcome == "pending_verification", (first.outcome, first.error_code)
    _age(h, first)
    second = h.run(OP, rig.params([(7006, rig.s6[0], 2)]), key="pl-o")  # 2 > the 1 left free
    assert second.error_code == "ALL_LINKS_SKIPPED", (second.outcome, second.error_code)
    assert [s["code"] for s in second.batch["skipped"]] == ["QTY_ABOVE_FREE"], second.batch


def test_pol_05_a_needs_attention_batch_counts_against_the_free_qty(h, rig):
    _pending_op(h, "pl-p", OP, rig.w.p_free, {"mode": "batch", "knownKeys": [],
                "links": [{"soDtlKey": rig.s5[0], "qty": "3"}]}, status="needs_attention")
    second = h.run(OP, rig.params([(7006, rig.s6[0], 2)]), key="pl-q")
    assert [s["code"] for s in second.batch["skipped"]] == ["QTY_ABOVE_FREE"], (second.error_code, second.batch)


def test_pol_05_one_landed_row_answers_for_one_pending_link_only(h, rig):
    """World's p_linked row (qty 4 on so_a) is the one landed split; the second identical split did not land."""
    for key in ("pl-r", "pl-s"):
        _pending_op(h, key, "split_link", rig.w.p_free, {"mode": "split", "links": [{"soDtlKey": rig.w.so_a, "qty": "4"}]})
    second = h.run(OP, rig.params([(7006, rig.s6[0], 1)]), key="pl-t")
    assert [s["code"] for s in second.batch["skipped"]] == ["QTY_ABOVE_FREE"], (second.error_code, second.batch)


def test_pol_03_a_lock_connection_that_breaks_before_the_body_is_busy_and_not_stored(h, rig, monkeypatch):
    import sys
    from types import SimpleNamespace

    from sqlalchemy.exc import OperationalError

    orig = h.db.get_bind

    class Conn:
        def execute(self, *a, **k):
            raise OperationalError("SELECT", {}, Exception("server closed the connection unexpectedly"))

        def close(self):
            pass

        def invalidate(self):
            pass

    class Engine:
        dialect = SimpleNamespace(name="postgresql")

        @property
        def engine(self):
            return self

        def connect(self):
            return Conn()

    def get_bind(*a, **k):
        if sys._getframe(1).f_globals.get("__name__") == "modules.autocount.write_back.link_lock":
            return Engine()
        return orig(*a, **k)

    monkeypatch.setattr(h.db, "get_bind", get_bind)
    res = h.run(OP, rig.params(rig.three()), key="pl-u")
    assert res.outcome == "refused" and res.error_code == "DOC_BUSY", (res.outcome, res.error_code)
    assert h.vendor.writes() == [] and _stored(h, "pl-u") == 0


def test_pol_05_a_needs_attention_whole_row_link_whose_row_still_stands_reserves_nothing(h, rig):
    _pending_op(h, "pl-v", "link_row", rig.w.p_free, {"mode": "delete", "row": {"Qty": 4}, "received": None,
                "newLink": {"FromDocDtlKey": rig.s5[0]}}, status="needs_attention")
    res = h.run(OP, rig.params([(7006, rig.s6[0], 1)]), key="pl-w")
    assert res.outcome == "done", (res.outcome, res.error_code, res.batch)


def test_pol_05_a_pending_whole_row_link_whose_row_still_stands_reserves_the_row(h, rig):
    _pending_op(h, "pl-x", "link_row", rig.w.p_free, {"mode": "delete", "row": {"Qty": 4}, "received": None,
                "newLink": {"FromDocDtlKey": rig.s5[0]}})
    res = h.run(OP, rig.params([(7006, rig.s6[0], 1)]), key="pl-y")
    assert [s["code"] for s in res.batch["skipped"]] == ["QTY_ABOVE_FREE"], (res.error_code, res.batch)
