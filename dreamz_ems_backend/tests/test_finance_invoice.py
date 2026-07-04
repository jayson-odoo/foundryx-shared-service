"""Finance Cluster F slice 1 (sprint-4/07) — invoice depth: status graph + derived
Paid/Overdue, freeze-after-Issue, manual payments, tax, void, PDF.

AC-07-08..18. Uses the SQLite create_all suite (status_id backfill rides the live
Postgres migration; here every row is born with status_id).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.status import Status
from app.models.tenant import DEFAULT_TENANT_ID
from modules.finance.models import INVOICE_ENTITY, PAYMENT_ENTITY, Invoice, Payment
from modules.finance.services import InvoiceService
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

TENANT = DEFAULT_TENANT_ID


def _admin(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _status_id(db, entity, key):
    row = (
        db.query(Status)
        .filter(Status.entity_type == entity, Status.tenant_id == TENANT, Status.scope_id.is_(None), Status.key == key)
        .first()
    )
    return row.id if row else None


def _new_invoice(db, lines):
    from app.module_platform import resolve_capability

    handler = resolve_capability(db, TENANT, "finance.create_invoice", 1)
    res = handler(db, TENANT, {"billToType": "Profile", "billToId": "p", "currency": "USD", "lines": lines})
    db.commit()
    return res["id"]


def _issue(db, invoice_id):
    issued = _status_id(db, INVOICE_ENTITY, "issued")
    InvoiceService(db).transition(TENANT, invoice_id, issued, None)


# ── AC-07-08 graph extended + backfill ──────────────────────────────────────


def test_invoice_graph_extended(client, session_factory):
    db = session_factory()
    keys = {
        s.key
        for s in db.query(Status).filter(
            Status.entity_type == INVOICE_ENTITY, Status.tenant_id == TENANT, Status.scope_id.is_(None)
        )
    }
    db.close()
    assert {"draft", "issued", "cancelled", "void", "partially_paid", "paid", "overdue", "refunded"} <= keys


def test_invoice_statuses_are_system_locked(client, session_factory):
    """AC-07-53 — finance status keys are a code contract, locked from rename."""
    db = session_factory()
    rows = db.query(Status).filter(
        Status.entity_type == INVOICE_ENTITY, Status.tenant_id == TENANT, Status.scope_id.is_(None)
    ).all()
    db.close()
    assert rows and all(r.is_system for r in rows)


def test_backfill_repairs_partial_graph(client, session_factory):
    """AC-07-08 — a tenant with only Draft/Issued/Cancelled is backfilled with the
    new states + auto-edges (not seed-if-absent only)."""
    from app.models.status_transition import StatusTransition
    from modules.finance.bootstrap import (
        INVOICE_EDGE_SEED,
        INVOICE_STATUS_SEED,
        backfill_graph,
    )

    db = session_factory()
    # Simulate a legacy tenant: delete the F-era statuses + their edges.
    legacy_keys = {"void", "partially_paid", "paid", "overdue", "partially_refunded", "refunded"}
    legacy_ids = [
        s.id for s in db.query(Status).filter(
            Status.entity_type == INVOICE_ENTITY, Status.tenant_id == TENANT,
            Status.scope_id.is_(None), Status.key.in_(legacy_keys),
        )
    ]
    db.query(StatusTransition).filter(
        StatusTransition.entity_type == INVOICE_ENTITY,
        (StatusTransition.from_status_id.in_(legacy_ids)) | (StatusTransition.to_status_id.in_(legacy_ids)),
    ).delete(synchronize_session=False)
    db.query(Status).filter(Status.id.in_(legacy_ids)).delete(synchronize_session=False)
    db.commit()
    remaining = {s.key for s in db.query(Status).filter(
        Status.entity_type == INVOICE_ENTITY, Status.tenant_id == TENANT, Status.scope_id.is_(None))}
    assert "paid" not in remaining

    added = backfill_graph(db, INVOICE_ENTITY, TENANT, INVOICE_STATUS_SEED, INVOICE_EDGE_SEED)
    db.commit()
    assert added > 0
    repaired = {s.key for s in db.query(Status).filter(
        Status.entity_type == INVOICE_ENTITY, Status.tenant_id == TENANT, Status.scope_id.is_(None))}
    assert legacy_keys <= repaired
    # Re-running is a no-op (idempotent).
    assert backfill_graph(db, INVOICE_ENTITY, TENANT, INVOICE_STATUS_SEED, INVOICE_EDGE_SEED) == 0
    db.close()


# ── AC-07-06 number at Issue + AC-07-09 freeze ──────────────────────────────


def test_number_assigned_at_issue_and_frozen(client, session_factory):
    db = session_factory()
    iid = _new_invoice(db, [{"description": "x", "qty": 1, "unitPrice": 100, "taxRate": 6}])
    inv = db.query(Invoice).filter(Invoice.id == iid).first()
    assert inv.invoice_number is None  # AC-07-06 Draft has no number
    _issue(db, iid)
    inv = db.query(Invoice).filter(Invoice.id == iid).first()
    assert inv.invoice_number  # assigned at Issue
    assert inv.issued_at is not None and inv.due_date is not None
    db.close()


def test_freeze_after_issue(client, session_factory):
    """AC-07-09 — Draft editable; Issued financial fields 409; notes still editable."""
    h = _admin(client)
    db = session_factory()
    iid = _new_invoice(db, [{"description": "x", "qty": 1, "unitPrice": 100}])
    db.close()

    # Draft: line edit OK
    r = client.patch(f"/finance/invoices/{iid}", json={"lines": [{"description": "y", "qty": 2, "unitPrice": 50}]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 100.0

    # Issue it
    db = session_factory()
    _issue(db, iid)
    db.close()

    # Issued: financial PATCH → 409
    r = client.patch(f"/finance/invoices/{iid}", json={"lines": [{"description": "z", "qty": 1, "unitPrice": 999}]}, headers=h)
    assert r.status_code == 409, r.text
    r = client.patch(f"/finance/invoices/{iid}", json={"currency": "EUR"}, headers=h)
    assert r.status_code == 409
    # Notes stay editable post-Issue
    r = client.patch(f"/finance/invoices/{iid}", json={"notes": "paid in cash"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == "paid in cash"


# ── AC-07-10 manual payment method gate ─────────────────────────────────────


def test_manual_payment_method_gate(client, session_factory):
    h = _admin(client)
    db = session_factory()
    iid = _new_invoice(db, [{"description": "x", "qty": 1, "unitPrice": 100}])
    _issue(db, iid)
    db.close()

    ok = client.post(f"/finance/invoices/{iid}/payments", json={"amount": 40, "method": "CASH"}, headers=h)
    assert ok.status_code == 200, ok.text
    for bad in ("GATEWAY", "FPX"):
        r = client.post(f"/finance/invoices/{iid}/payments", json={"amount": 10, "method": bad}, headers=h)
        assert r.status_code == 422, (bad, r.text)


# ── AC-07-11 derived Partially Paid / Paid ──────────────────────────────────


def test_derived_partially_then_paid(client, session_factory):
    db = session_factory()
    iid = _new_invoice(db, [{"description": "x", "qty": 1, "unitPrice": 100}])  # total 100
    _issue(db, iid)
    db.close()
    h = _admin(client)

    r = client.post(f"/finance/invoices/{iid}/payments", json={"amount": 40, "method": "CASH"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["statusKey"] == "partially_paid", r.json()

    r = client.post(f"/finance/invoices/{iid}/payments", json={"amount": 60, "method": "BANK"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["statusKey"] == "paid", r.json()
    assert r.json()["paidTotal"] == 100.0


# ── AC-07-12 overpayment rejected ───────────────────────────────────────────


def test_overpayment_rejected(client, session_factory):
    db = session_factory()
    iid = _new_invoice(db, [{"description": "x", "qty": 1, "unitPrice": 100}])
    _issue(db, iid)
    # pre-pay 70
    InvoiceService(db).record_payment(TENANT, iid, {"amount": 70, "method": "CASH"}, None)
    db.close()
    h = _admin(client)
    # 50 would push Σ to 120 > 100 → 409
    r = client.post(f"/finance/invoices/{iid}/payments", json={"amount": 50, "method": "CARD"}, headers=h)
    assert r.status_code == 409, r.text
    # exact remaining 30 succeeds
    r = client.post(f"/finance/invoices/{iid}/payments", json={"amount": 30, "method": "CARD"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["statusKey"] == "paid"


# ── AC-07-13 Overdue time-derived ───────────────────────────────────────────


def test_overdue_time_derived(client, session_factory):
    from app.workflow_engine.scheduler import reevaluate_time_based

    db = session_factory()
    iid = _new_invoice(db, [{"description": "x", "qty": 1, "unitPrice": 100}])
    _issue(db, iid)
    # Force the due date into the past, unpaid.
    inv = db.query(Invoice).filter(Invoice.id == iid).first()
    inv.due_date = datetime.now(timezone.utc) - timedelta(days=5)
    db.commit()
    db.close()

    db = session_factory()
    reevaluate_time_based(db)
    db.close()

    db = session_factory()
    inv = db.query(Invoice).filter(Invoice.id == iid).first()
    overdue = _status_id(db, INVOICE_ENTITY, "overdue")
    assert inv.status_id == overdue, "should derive to Overdue"
    db.close()


def test_paid_invoice_not_overdue(client, session_factory):
    from app.workflow_engine.scheduler import reevaluate_time_based

    db = session_factory()
    iid = _new_invoice(db, [{"description": "x", "qty": 1, "unitPrice": 100}])
    _issue(db, iid)
    InvoiceService(db).record_payment(TENANT, iid, {"amount": 100, "method": "CASH"}, None)
    inv = db.query(Invoice).filter(Invoice.id == iid).first()
    assert inv.status_id == _status_id(db, INVOICE_ENTITY, "paid")
    inv.due_date = datetime.now(timezone.utc) - timedelta(days=5)
    db.commit()
    db.close()

    db = session_factory()
    reevaluate_time_based(db)
    db.close()
    db = session_factory()
    inv = db.query(Invoice).filter(Invoice.id == iid).first()
    assert inv.status_id == _status_id(db, INVOICE_ENTITY, "paid"), "Paid wins, never Overdue"
    db.close()


# ── AC-07-14 Void only from Issued + zero payments ──────────────────────────


def test_void_only_from_issued_zero_payments(client, session_factory):
    db = session_factory()
    iid = _new_invoice(db, [{"description": "x", "qty": 1, "unitPrice": 100}])
    _issue(db, iid)
    db.close()
    h = _admin(client)
    void = None
    db = session_factory()
    void = _status_id(db, INVOICE_ENTITY, "void")
    db.close()

    # zero payments → void OK
    r = client.post(f"/finance/invoices/{iid}/transition", json={"toStatusId": void}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["statusKey"] == "void"

    # an invoice with a payment cannot void
    db = session_factory()
    iid2 = _new_invoice(db, [{"description": "x", "qty": 1, "unitPrice": 100}])
    _issue(db, iid2)
    InvoiceService(db).record_payment(TENANT, iid2, {"amount": 10, "method": "CASH"}, None)
    db.close()
    r = client.post(f"/finance/invoices/{iid2}/transition", json={"toStatusId": void}, headers=h)
    assert r.status_code == 409, r.text


# ── AC-07-15 per-line tax round + summary ───────────────────────────────────


def test_tax_round_per_line_and_summary(client, session_factory):
    db = session_factory()
    # line A: 333 @ 6% → tax 19.98 ; line B: 250 @ 8% → tax 20.00
    iid = _new_invoice(db, [
        {"description": "A", "qty": 1, "unitPrice": 333, "taxRate": 6},
        {"description": "B", "qty": 1, "unitPrice": 250, "taxRate": 8},
    ])
    inv = InvoiceService(db).get(TENANT, iid)
    lines = {l.description: l for l in inv.lines}
    assert lines["A"].tax_amount == Decimal("19.9800")
    assert lines["B"].tax_amount == Decimal("20.0000")
    assert inv.tax == Decimal("39.9800")
    summary = {row["label"]: row for row in inv.taxSummary}
    assert summary["6%"]["tax"] == 19.98
    assert summary["8%"]["tax"] == 20.0
    db.close()


# ── AC-07-16 reserved e-invoice fields ──────────────────────────────────────


def test_einvoice_fields_settable_inert(client, session_factory):
    h = _admin(client)
    db = session_factory()
    iid = _new_invoice(db, [{"description": "x", "qty": 1, "unitPrice": 100}])
    db.close()
    r = client.patch(f"/finance/invoices/{iid}", json={
        "buyerTin": "C12345", "sstRegNo": "SST-9", "taxCode": "01", "einvoiceType": "01"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["buyerTin"] == "C12345" and body["taxCode"] == "01"


# ── AC-07-17/18 PDF + receipt ───────────────────────────────────────────────


def test_invoice_pdf_renders(client, session_factory):
    db = session_factory()
    iid = _new_invoice(db, [{"description": "Booth", "qty": 1, "unitPrice": 500, "taxRate": 6}])
    _issue(db, iid)
    pdf = InvoiceService(db).render_pdf(TENANT, iid)
    db.close()
    assert isinstance(pdf, bytes) and pdf[:4] == b"%PDF" and len(pdf) > 1000


def test_receipt_is_paid_invoice_pdf(client, session_factory):
    """AC-07-18 — a Paid invoice PDF shows the payments + Paid stamp = receipt."""
    from modules.finance.pdf import build_invoice_facts

    db = session_factory()
    iid = _new_invoice(db, [{"description": "Booth", "qty": 1, "unitPrice": 100}])
    _issue(db, iid)
    InvoiceService(db).record_payment(TENANT, iid, {"amount": 100, "method": "CASH"}, None)
    inv = db.query(Invoice).filter(Invoice.id == iid).first()
    facts = build_invoice_facts(db, TENANT, inv)
    assert facts["paidStamp"] == "PAID"
    assert len(facts["payments"]) == 1 and facts["payments"][0]["method"] == "CASH"
    pdf = InvoiceService(db).render_pdf(TENANT, iid)
    db.close()
    assert pdf[:4] == b"%PDF"


def test_pdf_download_endpoint(client, session_factory):
    h = _admin(client)
    db = session_factory()
    iid = _new_invoice(db, [{"description": "x", "qty": 1, "unitPrice": 100}])
    _issue(db, iid)
    db.close()
    r = client.get(f"/finance/invoices/{iid}/pdf", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"
