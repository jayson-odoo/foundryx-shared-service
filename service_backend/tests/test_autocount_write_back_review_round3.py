"""Plan 62 review round 3 (RED): neutral regression tests.

(1) a create lookup only runs for a stored create row; (2) a lock connection failure is a busy refusal;
(3) the create lookup follows later edits and never adopts a document another create already owns;
(4) lookup GETs are logged under the stored operation; (5) pending link operations count against the
over-link guard; (6) resume of a create row is a clean refusal.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, List

import pytest
from sqlalchemy.exc import OperationalError

from app.main import app  # noqa: F401
from modules.autocount.models import AcApiCallLog, AcWriteOperation
from tests.test_autocount_write_back_create_lookup import (
    URL, MYT, body, first_attempt_landed, lookups, posts, shift,
)
from tests.test_autocount_write_back_gateway_qtso import PREFIX, Gw, code
from tests.test_autocount_write_back_link_batch import ROUTE, Rig
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


@pytest.fixture
def gw(h, db):
    h.vendor.stamp_created = True
    h.delete_on()
    return Gw(h, db)


def create_op(db, key=None):
    db.expire_all()
    q = db.query(AcWriteOperation).filter(AcWriteOperation.op == "create_doc:PO")
    return q.one() if key is None else q.filter(AcWriteOperation.idempotency_key == key).one()


# ============================== (1) the lookup is for stored create rows only ===================

def test_r3_1_a_key_first_used_on_the_batch_route_is_not_flipped_by_a_create_lookup(client, h, db):
    rig = Rig(h)
    g = Gw(h, db)
    h.vendor.stamp_created = True
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    r1 = client.post(ROUTE, json=rig.body(rig.three()), headers=g.hdr("sh-1"))
    assert r1.status_code == 202 and r1.json()["outcome"] == "pending_verification", r1.text
    op_id = r1.json()["operationId"]
    r2 = client.post(URL, json=body(), headers=g.hdr("sh-1"))  # the same key on another route
    assert r2.status_code != 500, r2.text
    assert r2.json().get("outcome") != "done", r2.text
    assert code(r2) == "IDEMPOTENCY_CONFLICT", r2.text
    db.expire_all()
    assert db.get(AcWriteOperation, op_id).status == "pending_verification"
    r3 = client.post(ROUTE, json=rig.body(rig.three()), headers=g.hdr("sh-1"))  # the batch still reconciles
    assert r3.status_code == 200 and r3.json()["outcome"] == "done", r3.text


@pytest.mark.parametrize("snapshot", [None, {}, {"kind": "PO"}], ids=["none", "empty", "no_start"])
def test_r3_1_a_stored_create_row_without_first_attempt_info_resends_without_a_500(client, h, gw, db, snapshot):
    h.vendor.fail_next("POST", "NewPurchaseOrder")
    r1 = client.post(URL, json=body(), headers=gw.hdr("sh-2"))
    assert r1.json()["outcome"] == "vendor_error"
    row = create_op(db)
    row.snapshot_json = snapshot  # a row written before the lookup existed
    db.commit()
    r2 = client.post(URL, json=body(), headers=gw.hdr("sh-2"))
    assert r2.status_code != 500, r2.text
    assert r2.json().get("errorCode") != "INTERNAL_ERROR", r2.text


# ============================== (2) lock connection failure =====================================

def test_r3_2_a_lock_connection_failure_is_a_busy_refusal_with_nothing_stored(h, monkeypatch):
    w = World(h)
    orig = h.db.get_bind
    broken = {"on": True}

    class Engine:
        dialect = SimpleNamespace(name="postgresql")

        @property
        def engine(self):
            return self

        def connect(self):
            raise OperationalError("connect", {}, Exception("QueuePool limit reached, connection timed out"))

    def get_bind(*a, **k):
        if broken["on"] and sys._getframe(1).f_globals.get("__name__") == "modules.autocount.write_back.link_lock":
            return Engine()  # force the Postgres branch for the lock only
        return orig(*a, **k)

    monkeypatch.setattr(h.db, "get_bind", get_bind)
    res = h.run("link_row", w.params["link_row"], key="lk-1")
    assert res.outcome == "refused" and res.error_code == "DOC_BUSY", (res.outcome, res.error_code)
    assert h.vendor.writes() == []
    h.db.expire_all()
    assert h.db.query(AcWriteOperation).filter_by(idempotency_key="lk-1").count() == 0  # the key stays usable
    broken["on"] = False  # the pool recovers
    again = h.run("link_row", w.params["link_row"], key="lk-1")
    assert again.outcome == "done", (again.outcome, again.error_code)


# ============================== (3) lookup reach and ownership ==================================

def test_r3_3_a_document_edited_on_a_later_day_is_still_found(client, h, gw, db):
    first_attempt_landed(client, h, gw, "lr-1", body())
    created = (datetime.now(MYT).replace(tzinfo=None) - timedelta(days=2)).isoformat(timespec="milliseconds")
    doc = h.vendor.docs["PO"][0]
    doc["CreatedTimeStamp"] = created                         # created two MYT days ago ...
    doc["LastModified"] = datetime.now(MYT).replace(tzinfo=None).isoformat(timespec="milliseconds")  # ... edited today
    op = create_op(db)
    start = datetime.fromisoformat(created).replace(tzinfo=MYT)
    op.snapshot_json = dict(op.snapshot_json, start=start.isoformat(), end=(start + timedelta(seconds=3)).isoformat())
    db.commit()
    r = client.post(URL, json=body(), headers=gw.hdr("lr-1"))
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert len(posts(h)) == 1


def test_r3_3_the_day_scan_is_capped(client, h, gw, db):
    first_attempt_landed(client, h, gw, "lr-2", body())
    old = datetime.now(MYT).replace(tzinfo=None) - timedelta(days=60)
    op = create_op(db)
    start = old.replace(tzinfo=MYT)
    op.snapshot_json = dict(op.snapshot_json, start=start.isoformat(), end=(start + timedelta(seconds=3)).isoformat())
    db.commit()
    client.post(URL, json=body(), headers=gw.hdr("lr-2"))
    assert 1 <= len(lookups(h)) <= 8  # at most 7 days back plus today, never 60


def test_r3_3_a_document_owned_by_another_done_create_is_never_adopted(client, h, gw):
    first_attempt_landed(client, h, gw, "own-1", body())
    d1 = h.vendor.docs["PO"][0]["DocNo"]
    r = client.post(URL, json=body(), headers=gw.hdr("own-1"))
    assert r.json()["outcome"] == "done" and r.json()["docNo"] == d1  # K1 adopts D1
    h.vendor.fail_next("POST", "NewPurchaseOrder")
    assert client.post(URL, json=body(), headers=gw.hdr("own-2")).json()["outcome"] == "vendor_error"
    r2 = client.post(URL, json=body(), headers=gw.hdr("own-2"))  # identical body, inside the same window
    assert r2.json()["docNo"] != d1, "adopted a document another create already owns"
    assert r2.json()["outcome"] == "done" and len(h.vendor.docs["PO"]) == 2
    assert len(posts(h)) == 3


# ============================== (4) lookup GETs are logged under the stored operation ===========

def test_r3_4_lookup_gets_carry_the_stored_operations_key_and_id(client, h, gw, db):
    first_attempt_landed(client, h, gw, "lg-1", body())
    op = create_op(db)
    client.post(URL, json=body(), headers=gw.hdr("lg-1"))
    db.expire_all()
    rows = [r for r in db.query(AcApiCallLog).filter(AcApiCallLog.method == "GET").all()
            if "byLastModified" in (r.path or "") or "bylastmodified" in (r.path or "").lower()]
    assert rows
    assert all(r.actor == gw.key.id and r.operation_id == op.id for r in rows), [(r.actor, r.operation_id) for r in rows]


# ============================== (5) pending link operations count ===============================

def test_r3_5_a_pending_link_counts_against_the_next_link_on_the_same_so_row(h):
    h.delete_on()
    so = h.seed_doc("SO", 7010, [_line("ITEM-A", 5, 5.0, "HQ")])
    s = so["Details"][0]["DtlKey"]
    a = h.seed_doc("PO", 7011, [_line("ITEM-A", 5, 5.0, "BR1")])["Details"][0]["DtlKey"]
    b = h.seed_doc("PO", 7012, [_line("ITEM-A", 1, 5.0, "BR1")])["Details"][0]["DtlKey"]
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    first = h.run("link_row", dict(doc_key=7011, dtl_key=a, so_doc_key=7010, so_dtl_key=s), key="pn-1")
    assert first.outcome == "pending_verification", (first.outcome, first.error_code)
    second = h.run("link_row", dict(doc_key=7012, dtl_key=b, so_doc_key=7010, so_dtl_key=s), key="pn-2")
    assert second.outcome == "refused" and second.error_code == "QTY_ABOVE_OUTSTANDING", (
        second.outcome, second.error_code)


# ============================== (6) resume of a create row ======================================

def _resume(client, gw, op_id, key):
    return client.post(f"{PREFIX}/write-operations/{op_id}/resume", headers=gw.hdr(key), json={"companyCode": "SRT"})


def test_r3_6_resume_of_a_pending_create_row_is_a_clean_refusal(client, h, gw, db):
    h.vendor.timeout_next("POST", "NewPurchaseOrder")
    r1 = client.post(URL, json=body(), headers=gw.hdr("rs-1"))
    assert r1.json()["outcome"] == "pending_verification"
    op = create_op(db)
    r = _resume(client, gw, op.id, "rs-1r")
    assert r.status_code < 500, r.text
    assert r.json().get("errorCode") != "INTERNAL_ERROR", r.text


def test_r3_6_resume_of_an_ambiguous_create_keeps_create_ambiguous(client, h, gw, db):
    import copy

    first_attempt_landed(client, h, gw, "rs-2", body())
    twin = copy.deepcopy(h.vendor.docs["PO"][0])
    twin.update(DocKey=twin["DocKey"] + 1000, DocNo="PO-TWIN")
    h.vendor.docs["PO"].append(twin)
    assert code(client.post(URL, json=body(), headers=gw.hdr("rs-2"))) == "CREATE_AMBIGUOUS"
    op = create_op(db)
    r = _resume(client, gw, op.id, "rs-2r")
    assert r.status_code < 500, r.text
    assert r.json().get("errorCode") != "INTERNAL_ERROR", r.text
    db.expire_all()
    row = db.get(AcWriteOperation, op.id)
    assert row.status == "needs_attention" and row.error_code == "CREATE_AMBIGUOUS"
