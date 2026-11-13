"""Plan 62 review round 5 (RED): neutral regression tests.

(1) the plan 55 link path takes the per-SO-row lock; (2) a pending split link counts against the guard;
(3) a create row stored before the lookup existed keeps its unknown outcome locked; (4) the lock engine's
connections are named; (5) the "may have reached AutoCount" notice has a truthful subject.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, List

import pytest

from app.main import app  # noqa: F401
from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import AcWriteOperation
from modules.autocount.write_back.link_lock import SoRowBusy
from modules.autocount.write_back.service import WriteBackService
from tests.test_autocount_write_back_create_lookup import URL, body, first_attempt_landed, posts
from tests.test_autocount_write_back_gateway_qtso import Gw
from tests.test_autocount_write_back_link_batch import Rig
from tests.test_autocount_write_back_operations import OpHarness, World, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import _line
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401


# ============================== (1) the plan 55 link path takes the lock ========================

def _patch_lock(monkeypatch, factory):
    import modules.autocount.write_back.link_lock as link_lock
    import modules.autocount.write_back.service as service

    monkeypatch.setattr(link_lock, "so_row_locks", factory)
    monkeypatch.setattr(service, "so_row_locks", factory, raising=False)


def _plan55_link(h, w, qty=2):
    return WriteBackService(h.db, **h.factories()).link(
        tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, po_doc_key=7001, po_dtl_key=w.p_free,
        so_doc_key=7002, so_dtl_key=w.so_b, qty=Decimal(qty))


def test_r5_1_the_plan_55_link_holds_the_so_row_lock_from_before_the_guard_to_after_the_put(h, monkeypatch):
    w = World(h)
    events: List[Any] = []

    @contextmanager
    def spy(db, company_id, so_dtl_keys):
        events.append(("enter", company_id, sorted(so_dtl_keys), len(h.vendor.writes())))
        yield
        events.append(("exit", len(h.vendor.writes())))

    _patch_lock(monkeypatch, spy)
    res = _plan55_link(h, w)
    assert res.outcome == "done", (res.outcome, res.error_code)
    assert events and events[0] == ("enter", h.company.id, [w.so_b], 0), events  # taken before anything is written
    assert events[-1] == ("exit", 1), events  # released only after the PUT


def test_r5_1_a_busy_so_row_refuses_the_plan_55_link_with_no_put(h, monkeypatch):
    w = World(h)

    @contextmanager
    def busy(db, company_id, so_dtl_keys):
        raise SoRowBusy()
        yield  # pragma: no cover

    _patch_lock(monkeypatch, busy)
    res = _plan55_link(h, w)
    assert res.outcome == "refused" and res.error_code == "DOC_BUSY", (res.outcome, res.error_code)
    assert h.vendor.writes() == []


# ============================== (2) a pending split link counts =================================

def test_r5_2_a_pending_split_link_counts_against_the_next_link_on_the_same_so_row(h):
    h.delete_on()
    so = h.seed_doc("SO", 7010, [_line("ITEM-A", 3, 5.0, "HQ")])
    s = so["Details"][0]["DtlKey"]
    a = h.seed_doc("PO", 7011, [_line("ITEM-A", 4, 5.0, "BR1")])["Details"][0]["DtlKey"]
    b = h.seed_doc("PO", 7012, [_line("ITEM-A", 1, 5.0, "BR1")])["Details"][0]["DtlKey"]
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    first = h.run("split_link", dict(po_doc_key=7011, po_dtl_key=a, so_doc_key=7010, so_dtl_key=s, qty=3), key="sp-1")
    assert first.outcome == "pending_verification", (first.outcome, first.error_code)
    second = h.run("link_row", dict(doc_key=7012, dtl_key=b, so_doc_key=7010, so_dtl_key=s), key="sp-2")
    assert second.outcome == "refused" and second.error_code == "QTY_ABOVE_OUTSTANDING", (
        second.outcome, second.error_code)


# ============================== (3) a create row from before the lookup ========================

@pytest.fixture
def gw(h, db):
    h.vendor.stamp_created = True
    h.delete_on()
    return Gw(h, db)


def _old_create_row(client, h, gw, db, key, status, code, outcome):
    h.vendor.fail_next("POST", "NewPurchaseOrder")
    client.post(URL, json=body(), headers=gw.hdr(key))
    row = db.query(AcWriteOperation).filter(AcWriteOperation.op == "create_doc:PO").one()
    row.status, row.error_code, row.snapshot_json = status, code, None  # as written before the lookup existed
    row.result_json = {"operationId": None, "outcome": outcome, "errorCode": code, "message": "", "warnings": [],
                       "docKey": None, "docNo": None, "replacedLines": [], "document": None}
    db.commit()


def test_r5_3_an_old_create_row_with_a_vendor_refusal_keeps_its_unknown_outcome_locked(client, h, gw, db):
    _old_create_row(client, h, gw, db, "oc-1", "vendor_error", "VENDOR_REFUSED", "vendor_error")
    before = len(posts(h))
    r = client.post(URL, json=body(), headers=gw.hdr("oc-1"))
    assert r.json()["outcome"] == "vendor_error" and r.json()["errorCode"] == "VENDOR_REFUSED", r.text
    assert len(posts(h)) == before  # replayed, nothing sent


def test_r5_3_control_an_old_create_row_that_SS_itself_refused_is_released(client, h, gw, db):
    _old_create_row(client, h, gw, db, "oc-2", "refused", "FIELD_REQUIRED", "refused")
    before = len(posts(h))
    r = client.post(URL, json=body(), headers=gw.hdr("oc-2"))
    assert r.status_code == 200 and r.json()["outcome"] == "done", r.text
    assert len(posts(h)) == before + 1


# ============================== (4) the lock engine's connections are named =====================

def test_r5_4_the_lock_engine_connects_with_an_application_name(monkeypatch):
    import psycopg2
    from sqlalchemy.engine import make_url

    from app.database import app_connect_args
    from modules.autocount.write_back import link_lock

    url = make_url("postgresql://u:p@localhost:5432/db_round5")
    seen: List[dict] = []

    def fake_connect(*args, **kwargs):
        seen.append(dict(kwargs))
        raise psycopg2.OperationalError("stop before any network")

    monkeypatch.setattr(psycopg2, "connect", fake_connect)
    monkeypatch.setattr(link_lock, "_engines", {})
    engine = link_lock._lock_engine(SimpleNamespace(url=url))
    with pytest.raises(Exception):
        engine.connect()
    assert seen, "the lock engine never tried to connect"
    wanted = app_connect_args(str(url))["application_name"]
    assert wanted in str(seen[0].get("application_name", "")), seen[0]


# ============================== (5) the notice subject is truthful ==============================

def _mail_rig(h):
    from tests.test_s33_integration_alerts import MANAGE, _only_recipients, _user

    _only_recipients(h.db)
    _user(h.db, "mgr@example.com", perms=[MANAGE])


def _subjects(h):
    from app.models.email_outbox import EmailOutbox

    h.db.expire_all()
    return [m.subject for m in h.db.query(EmailOutbox).all()]


def test_r5_5_a_batch_reconcile_notice_does_not_say_needs_re_keying(h):
    _mail_rig(h)
    rig = Rig(h)
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    assert h.run("link_batch", rig.params(rig.three()), key="sj-1", notifier="default").outcome == "pending_verification"
    next(r for r in h.vendor.rows("PO", 7001) if r["DtlKey"] == rig.w.p_free)["Qty"] = 3
    res = h.run("link_batch", rig.params(rig.three()), key="sj-1", notifier="default")
    assert res.outcome == "needs_attention"
    subjects = _subjects(h)
    assert len(subjects) == 1, subjects
    assert "re-key" not in subjects[0].lower(), subjects


def test_r5_5_a_merge_reconcile_notice_does_not_say_needs_re_keying(h):
    _mail_rig(h)
    h.delete_on()
    w = World(h)
    h.vendor.find("PO", 7001)["Details"][1]["UnitPrice"] = 5.0
    h.vendor.timeout_next("PUT", "EditPurchaseOrderbydockey")
    assert h.run("unlink_row", w.params["unlink_row"], key="sj-2", notifier="default").outcome == "pending_verification"
    po = h.vendor.find("PO", 7001)
    po["Details"] = [r for r in po["Details"] if r["DtlKey"] != w.p_linked]
    res = h.run("unlink_row", w.params["unlink_row"], key="sj-2", notifier="default")
    assert res.outcome == "needs_attention"
    subjects = _subjects(h)
    assert len(subjects) == 1, subjects
    assert "re-key" not in subjects[0].lower(), subjects
