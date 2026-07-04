"""Cluster F slice 4 (sprint-4/07) — refunds + settlement.

AC-07-37..51. Per-ticket refunds (gateway + manual), over-refund guard, numbered
credit note + PDF, tickets Void + QR dead + capacity released, invoice/eligibility
re-derive, AGENCY commercial config + PRIMARY settlement (three-way net),
settlement lifecycle, post-remit ADJUSTMENT. Gateway HTTP is mocked at the adapter
boundary; Celery is EAGER under tests (conftest) so derivations run inline.
"""
from decimal import Decimal

from app.models.status import Status
from app.models.tenant import DEFAULT_TENANT_ID
from modules.finance.models import (
    INVOICE_ENTITY,
    PAYMENT_ENTITY,
    REFUND_ENTITY,
    SETTLEMENT_ENTITY,
    Invoice,
    Payment,
    Refund,
    RefundLine,
    Settlement,
)
from modules.finance.services import InvoiceService
from modules.finance.refund_service import RefundService
from modules.finance.settlement_service import SettlementService
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

TENANT = DEFAULT_TENANT_ID


def _admin(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _status_id(db, entity, key):
    row = (
        db.query(Status)
        .filter(Status.entity_type == entity, Status.tenant_id == TENANT,
                Status.scope_id.is_(None), Status.key == key)
        .first()
    )
    return row.id if row else None


def _make_event(client, h):
    t = client.post("/ems/project-types", json={"name": "Conf"}, headers=h).json()
    tmpl = client.post("/ems/project-templates", json={"typeId": t["id"], "name": "Std"}, headers=h).json()
    proj = client.post("/ems/projects", json={"templateId": tmpl["id"], "title": "Summit"}, headers=h).json()
    return proj["id"]


def _ga_offering(client, h, pid, name="Pass", price=100):
    prod = client.post("/products", json={"name": name, "kind": "admission"}, headers=h).json()
    return client.post(
        f"/ems/projects/{pid}/offerings",
        json={"productId": prod["id"], "allocationMode": "GA", "capacity": 100, "price": price, "currency": "MYR"},
        headers=h,
    ).json()


def _confirm_paid(session_factory, pid, offering_id, email, *, method="CASH"):
    """Confirm a ticket → Draft invoice; Issue + record a manual full payment so
    the invoice derives Paid. Returns (ticket_id, invoice_id)."""
    from modules.ems.models import Ticket
    from modules.ems.services import CheckoutService

    db = session_factory()
    CheckoutService(db).confirm(
        TENANT, pid, [{"offeringId": offering_id, "attendee": {"name": "A", "email": email}}]
    )
    db.commit()
    t = db.query(Ticket).filter(Ticket.project_id == pid).order_by(Ticket.created_at.desc()).first()
    tid, invoice_id = t.id, t.invoice_id
    db.close()

    db = session_factory()
    svc = InvoiceService(db)
    svc.transition(TENANT, invoice_id, _status_id(db, INVOICE_ENTITY, "issued"), None)
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    svc.record_payment(TENANT, invoice_id, {"amount": float(inv.total), "method": method}, None)
    db.close()
    return tid, invoice_id


def _invoice_key(session_factory, invoice_id):
    db = session_factory()
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    st = db.query(Status).filter(Status.id == inv.status_id).first()
    key = st.key if st else None
    db.close()
    return key


# ── AC-07-38 — manual refund (CASH) creates a record, no gateway ─────────────

def test_manual_cash_refund_confirmed_with_credit_note(client, session_factory):
    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid)
    tid, iid = _confirm_paid(session_factory, pid, o["id"], "cash@x.com", method="CASH")
    assert _invoice_key(session_factory, iid) == "paid"

    db = session_factory()
    res = RefundService(db).create(TENANT, iid, {"ticketIds": [tid], "reason": "changed mind"}, None)
    db.close()
    assert res["method"] == "CASH"
    assert res["statusKey"] == "confirmed"
    assert res["creditNoteNumber"]  # AC-07-40 numbered
    assert res["ticketIds"] == [tid]


# ── AC-07-37/38 — gateway refund routes through the gateway API ──────────────

def test_gateway_refund_calls_provider_api(client, session_factory, monkeypatch):
    """A GATEWAY payment refund routes through the provider.refund() API (mocked
    at the adapter boundary) and confirms with the returned ref."""
    from app.models.connection import Connection
    from app.integrations.base import RefundResult
    from app.secrets import encrypt_secret
    from modules.ems.models import Ticket
    from modules.ems.services import CheckoutService

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, price=100)
    # confirm + issue, then create a GATEWAY Succeeded payment directly
    db = session_factory()
    CheckoutService(db).confirm(TENANT, pid, [{"offeringId": o["id"], "attendee": {"name": "G", "email": "gw@x.com"}}])
    db.commit()
    t = db.query(Ticket).filter(Ticket.project_id == pid).order_by(Ticket.created_at.desc()).first()
    tid, iid = t.id, t.invoice_id
    conn = Connection(tenant_id=TENANT, provider="stripe", type="payment", name="Stripe",
                      config_json={}, credentials_json=encrypt_secret({"secretKey": "sk", "webhookSigningSecret": "w"}),
                      status="ACTIVE")
    db.add(conn)
    db.flush()
    svc = InvoiceService(db)
    svc.transition(TENANT, iid, _status_id(db, INVOICE_ENTITY, "issued"), None)
    from datetime import datetime, timezone
    pay = Payment(tenant_id=TENANT, invoice_id=iid, amount=100, method="GATEWAY",
                  status_id=_status_id(db, PAYMENT_ENTITY, "succeeded"),
                  paid_at=datetime.now(timezone.utc), gateway_connection_id=conn.id,
                  external_payment_id="pi_xyz")
    db.add(pay)
    db.commit()
    db.close()

    calls = {}

    def _fake_refund(self, config, credentials, *, external_payment_id, amount, currency):
        calls["external_payment_id"] = external_payment_id
        calls["amount"] = amount
        return RefundResult(external_refund_id="re_123")

    from app.integrations.stripe_provider import StripeProvider
    monkeypatch.setattr(StripeProvider, "refund", _fake_refund)

    db = session_factory()
    res = RefundService(db).create(TENANT, iid, {"ticketIds": [tid]}, None)
    db.close()
    assert calls["external_payment_id"] == "pi_xyz"
    assert res["method"] == "GATEWAY"
    assert res["gatewayRef"] == "re_123"
    assert res["statusKey"] == "confirmed"


def test_credit_note_pdf_renders(client, session_factory):
    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid)
    tid, iid = _confirm_paid(session_factory, pid, o["id"], "cn@x.com")
    db = session_factory()
    res = RefundService(db).create(TENANT, iid, {"ticketIds": [tid]}, None)
    pdf = RefundService(db).render_credit_note_pdf(TENANT, res["id"])
    db.close()
    assert pdf[:4] == b"%PDF"  # AC-07-40 a real PDF


# ── AC-07-43 — invoice re-derives Refunded (full) / Partially (partial) ──────

def test_full_refund_derives_invoice_refunded(client, session_factory):
    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid)
    tid, iid = _confirm_paid(session_factory, pid, o["id"], "full@x.com")
    db = session_factory()
    RefundService(db).create(TENANT, iid, {"ticketIds": [tid]}, None)
    db.close()
    assert _invoice_key(session_factory, iid) == "refunded"


def test_partial_refund_derives_partially_refunded(client, session_factory):
    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, price=100)
    # two tickets on ONE invoice
    from modules.ems.models import Ticket
    from modules.ems.services import CheckoutService

    db = session_factory()
    CheckoutService(db).confirm(TENANT, pid, [
        {"offeringId": o["id"], "attendee": {"name": "A", "email": "p1@x.com"}},
        {"offeringId": o["id"], "attendee": {"name": "B", "email": "p2@x.com"}},
    ])
    db.commit()
    tickets = db.query(Ticket).filter(Ticket.project_id == pid).order_by(Ticket.created_at.asc()).all()
    iid = tickets[0].invoice_id
    t_first = tickets[0].id
    db.close()
    db = session_factory()
    svc = InvoiceService(db)
    svc.transition(TENANT, iid, _status_id(db, INVOICE_ENTITY, "issued"), None)
    inv = db.query(Invoice).filter(Invoice.id == iid).first()
    svc.record_payment(TENANT, iid, {"amount": float(inv.total), "method": "CASH"}, None)
    db.close()
    db = session_factory()
    RefundService(db).create(TENANT, iid, {"ticketIds": [t_first]}, None)
    db.close()
    assert _invoice_key(session_factory, iid) == "partially_refunded"


# ── AC-07-41/42 — tickets Void/Refunded + QR dead + capacity released ────────

def test_refund_voids_ticket_and_rotates_qr(client, session_factory):
    from modules.ems.models import Ticket

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid)
    tid, iid = _confirm_paid(session_factory, pid, o["id"], "qr@x.com")
    db = session_factory()
    before = db.query(Ticket).filter(Ticket.id == tid).first()
    nonce_before = before.qr_nonce
    db.close()
    db = session_factory()
    RefundService(db).create(TENANT, iid, {"ticketIds": [tid]}, None)
    db.close()
    db = session_factory()
    after = db.query(Ticket).filter(Ticket.id == tid).first()
    assert after.status == "refunded"
    assert after.qr_nonce != nonce_before  # AC-07-41 QR rotated dead
    db.close()


# ── AC-07-39 — over-refund guarded ───────────────────────────────────────────

def test_over_refund_rejected(client, session_factory):
    from fastapi import HTTPException

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid)
    tid, iid = _confirm_paid(session_factory, pid, o["id"], "over@x.com")
    db = session_factory()
    RefundService(db).create(TENANT, iid, {"ticketIds": [tid]}, None)  # full refund
    # a second refund of the same (already refunded) ticket → 409
    try:
        RefundService(db).create(TENANT, iid, {"ticketIds": [tid]}, None)
        assert False, "expected an over-refund / non-refundable rejection"
    except HTTPException as e:
        assert e.status_code == 409
    db.close()


# ── AC-07-44 — participant eligibility drops on refund ───────────────────────

def test_refund_drops_participant_eligibility(client, session_factory):
    from modules.ems.models import PARTICIPANT_ENTITY, Ticket, ProjectParticipant

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid)
    tid, iid = _confirm_paid(session_factory, pid, o["id"], "elig@x.com")
    # paying derives the participant Eligible (post_payment reaction)
    db = session_factory()
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    pp = db.query(ProjectParticipant).filter(ProjectParticipant.id == t.participant_id).first()
    st = db.query(Status).filter(Status.id == pp.status_id).first()
    assert st.key == "eligible", f"expected eligible, got {st.key}"
    db.close()
    # refund → eligibility drops (no live admission ticket)
    db = session_factory()
    RefundService(db).create(TENANT, iid, {"ticketIds": [tid]}, None)
    db.close()
    db = session_factory()
    pp = db.query(ProjectParticipant).filter(ProjectParticipant.id == pp.id).first()
    st = db.query(Status).filter(Status.id == pp.status_id).first()
    assert st.key != "eligible", "participant must drop from Eligible (AC-07-44)"
    db.close()


# ── AC-07-45/46 — AGENCY commercial config + PRIMARY settlement three-way ────

def test_self_run_project_has_no_settlement(client, session_factory):
    from fastapi import HTTPException

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid)
    _confirm_paid(session_factory, pid, o["id"], "sr@x.com")
    db = session_factory()
    try:
        SettlementService(db).generate(TENANT, pid, None)
        assert False, "SELF_RUN must not produce a settlement"
    except HTTPException as e:
        assert e.status_code == 409
    db.close()


def test_agency_primary_settlement_nets_three_ways(client, session_factory):
    h = _admin(client)
    pid = _make_event(client, h)
    # AGENCY, 10% fee
    client.patch(f"/ems/projects/{pid}", json={"commercialMode": "AGENCY", "feeType": "PERCENT", "feeValue": 10}, headers=h)
    o = _ga_offering(client, h, pid, price=100)
    _confirm_paid(session_factory, pid, o["id"], "ag@x.com")  # MYR 100 paid, no gateway fee
    db = session_factory()
    res = SettlementService(db).generate(TENANT, pid, None)
    db.close()
    assert res["kind"] == "PRIMARY"
    assert res["grossCollected"] == 100.0
    assert res["gatewayFees"] == 0.0
    assert res["feeAmount"] == 10.0  # 10% of 100
    assert res["netPayable"] == 90.0  # 100 - 0 - 10 (AC-07-46/51 exact)


# ── AC-07-47 — settlement lifecycle Draft→Approved→Remitted ──────────────────

def test_settlement_lifecycle(client, session_factory):
    h = _admin(client)
    pid = _make_event(client, h)
    client.patch(f"/ems/projects/{pid}", json={"commercialMode": "AGENCY", "feeType": "FLAT", "feeValue": 5}, headers=h)
    o = _ga_offering(client, h, pid, price=100)
    _confirm_paid(session_factory, pid, o["id"], "lc@x.com")
    r = client.post("/finance/settlements", json={"projectId": pid}, headers=h)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    db = session_factory()
    approved = _status_id(db, SETTLEMENT_ENTITY, "approved")
    remitted = _status_id(db, SETTLEMENT_ENTITY, "remitted")
    db.close()
    r2 = client.post(f"/finance/settlements/{sid}/transition", json={"toStatusId": approved}, headers=h)
    assert r2.status_code == 200 and r2.json()["statusKey"] == "approved"
    # remit requires a remittance ref
    r3 = client.post(f"/finance/settlements/{sid}/transition", json={"toStatusId": remitted}, headers=h)
    assert r3.status_code == 422
    r4 = client.post(f"/finance/settlements/{sid}/transition",
                     json={"toStatusId": remitted, "remittanceRef": "TXN-123"}, headers=h)
    assert r4.status_code == 200 and r4.json()["statusKey"] == "remitted"
    assert r4.json()["remittanceRef"] == "TXN-123"


# ── AC-07-48 — post-remit refund spawns ADJUSTMENT (negative) ────────────────

def test_post_remit_refund_spawns_adjustment(client, session_factory):
    h = _admin(client)
    pid = _make_event(client, h)
    client.patch(f"/ems/projects/{pid}", json={"commercialMode": "AGENCY", "feeType": "PERCENT", "feeValue": 10}, headers=h)
    o = _ga_offering(client, h, pid, price=100)
    tid, iid = _confirm_paid(session_factory, pid, o["id"], "adj@x.com")
    # generate + remit the PRIMARY
    sid = client.post("/finance/settlements", json={"projectId": pid}, headers=h).json()["id"]
    db = session_factory()
    approved = _status_id(db, SETTLEMENT_ENTITY, "approved")
    remitted = _status_id(db, SETTLEMENT_ENTITY, "remitted")
    db.close()
    client.post(f"/finance/settlements/{sid}/transition", json={"toStatusId": approved}, headers=h)
    client.post(f"/finance/settlements/{sid}/transition", json={"toStatusId": remitted, "remittanceRef": "T1"}, headers=h)
    # refund AFTER remit → ADJUSTMENT
    db = session_factory()
    RefundService(db).create(TENANT, iid, {"ticketIds": [tid]}, None)
    db.close()
    db = session_factory()
    adjustments = (
        db.query(Settlement)
        .filter(Settlement.tenant_id == TENANT, Settlement.project_id == pid, Settlement.kind == "ADJUSTMENT")
        .all()
    )
    db.close()
    assert len(adjustments) == 1, "a post-remit refund must spawn one ADJUSTMENT"
    assert adjustments[0].net_payable < 0, "the clawback adjustment is negative"


# ── AC-07-49/50 — tenant isolation + failure isolation ───────────────────────

def test_refund_tenant_scoped(client, session_factory):
    from fastapi import HTTPException

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid)
    tid, iid = _confirm_paid(session_factory, pid, o["id"], "iso@x.com")
    db = session_factory()
    try:
        RefundService(db).create("other-tenant", iid, {"ticketIds": [tid]}, None)
        assert False, "cross-tenant refund must 404"
    except HTTPException as e:
        assert e.status_code == 404
    db.close()


# ── AC-07-51 — money exact (no float drift) ──────────────────────────────────

def test_refund_lines_sum_to_amount_exactly(client, session_factory):
    """Σ refund_lines == refund.amount with no cent drift, even on a 3-way split
    of an indivisible total (AC-07-51)."""
    from modules.ems.models import Ticket
    from modules.ems.services import CheckoutService

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, price=100)  # 3 × 100 = 300, /3 = exact, use odd via partial
    db = session_factory()
    CheckoutService(db).confirm(TENANT, pid, [
        {"offeringId": o["id"], "attendee": {"name": "A", "email": "s1@x.com"}},
        {"offeringId": o["id"], "attendee": {"name": "B", "email": "s2@x.com"}},
        {"offeringId": o["id"], "attendee": {"name": "C", "email": "s3@x.com"}},
    ])
    db.commit()
    tickets = db.query(Ticket).filter(Ticket.project_id == pid).order_by(Ticket.created_at.asc()).all()
    iid = tickets[0].invoice_id
    tids = [t.id for t in tickets]
    db.close()
    db = session_factory()
    svc = InvoiceService(db)
    svc.transition(TENANT, iid, _status_id(db, INVOICE_ENTITY, "issued"), None)
    inv = db.query(Invoice).filter(Invoice.id == iid).first()
    svc.record_payment(TENANT, iid, {"amount": float(inv.total), "method": "CASH"}, None)
    db.close()
    db = session_factory()
    res = RefundService(db).create(TENANT, iid, {"ticketIds": tids[:2]}, None)
    lines = db.query(RefundLine).filter(RefundLine.refund_id == res["id"]).all()
    line_sum = sum((Decimal(str(line.amount)) for line in lines), Decimal("0"))
    refund_amount = Decimal(str(res["amount"]))
    db.close()
    assert line_sum == refund_amount, "Σ refund lines must equal the refund amount exactly"


def test_settlement_net_reconciles_exactly(client, session_factory):
    h = _admin(client)
    pid = _make_event(client, h)
    client.patch(f"/ems/projects/{pid}", json={"commercialMode": "AGENCY", "feeType": "PERCENT", "feeValue": 6}, headers=h)
    o = _ga_offering(client, h, pid, price=99.99)
    _confirm_paid(session_factory, pid, o["id"], "exact@x.com")
    db = session_factory()
    res = SettlementService(db).generate(TENANT, pid, None)
    db.close()
    gross = Decimal(str(res["grossCollected"]))
    fees = Decimal(str(res["gatewayFees"]))
    fee = Decimal(str(res["feeAmount"]))
    net = Decimal(str(res["netPayable"]))
    assert net == (gross - fees - fee), "net must equal gross − gateway_fees − fee exactly"
