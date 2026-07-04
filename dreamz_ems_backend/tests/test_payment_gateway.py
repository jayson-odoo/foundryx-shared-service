"""Cluster F slice 3 (sprint-4/07) — payment gateways + checkout + webhooks.

AC-07-24..36 + cross-cutting isolation/failure/exact-money. Gateway HTTP is
mocked at the adapter boundary (no live Stripe/Billplz). Celery is EAGER under
tests (conftest) so the webhook route runs the ingest inline.
"""
import hashlib
import hmac
import json
import time
from decimal import Decimal


from app.models.connection import Connection
from app.models.integration_log import IntegrationLog
from app.models.status import Status
from app.models.tenant import DEFAULT_TENANT_ID
from app.secrets import encrypt_secret
from modules.finance.models import INVOICE_ENTITY, PAYMENT_ENTITY, Invoice, Payment
from modules.finance.payment_service import PaymentService
from modules.finance.services import InvoiceService
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

TENANT = DEFAULT_TENANT_ID
WHSEC = "whsec_test_secret"


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


def _make_issued_invoice(db, total="100.00"):
    from app.module_platform import resolve_capability

    handler = resolve_capability(db, TENANT, "finance.create_invoice", 1)
    res = handler(db, TENANT, {"billToType": "Profile", "billToId": "p1", "currency": "USD",
                               "lines": [{"description": "Ticket", "qty": 1, "unitPrice": total}]})
    db.commit()
    iid = res["id"]
    InvoiceService(db).transition(TENANT, iid, _status_id(db, INVOICE_ENTITY, "issued"), None)
    return iid


def _stripe_connection(db, provider="stripe"):
    """Create a payment connection; return its id (the object detaches on close)."""
    c = Connection(
        tenant_id=TENANT, provider=provider, type="payment", name=provider.title(),
        config_json={}, credentials_json=encrypt_secret({"secretKey": "sk_test", "webhookSigningSecret": WHSEC}),
        status="ACTIVE",
    )
    db.add(c)
    db.commit()
    cid = c.id
    return cid


def _stripe_event(event_type, *, ext_ref, amount_minor=10000, event_id="evt_1", fee_minor=None, pi="pi_1"):
    obj = {"client_reference_id": ext_ref, "amount_total": amount_minor, "currency": "usd",
           "payment_intent": pi, "id": "cs_1"}
    if fee_minor is not None:
        obj["balance_transaction"] = {"fee": fee_minor}
    return {"id": event_id, "type": event_type, "data": {"object": obj}}


def _sign_stripe(body: bytes, ts=None):
    ts = ts or int(time.time())
    signed = f"{ts}.".encode() + body
    sig = hmac.new(WHSEC.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


# ── AC-07-24 — payment connections, one-per-type relaxed ─────────────────────

def test_two_different_payment_providers_allowed(client, session_factory):
    h = _admin(client)
    r1 = client.post("/integrations/connections", json={
        "provider": "stripe", "name": "Stripe", "config": {}, "credentials": {"secretKey": "sk", "webhookSigningSecret": "w"},
    }, headers=h)
    assert r1.status_code == 201, r1.text
    r2 = client.post("/integrations/connections", json={
        "provider": "billplz", "name": "Billplz", "config": {"collectionId": "c"},
        "credentials": {"apiKey": "k", "xSignatureKey": "x"},
    }, headers=h)
    assert r2.status_code == 201, r2.text  # different provider, same type → allowed


def test_same_payment_provider_duplicate_rejected(client, session_factory):
    h = _admin(client)
    client.post("/integrations/connections", json={
        "provider": "stripe", "name": "Stripe", "config": {}, "credentials": {"secretKey": "sk", "webhookSigningSecret": "w"},
    }, headers=h)
    dup = client.post("/integrations/connections", json={
        "provider": "stripe", "name": "Stripe 2", "config": {}, "credentials": {"secretKey": "sk2", "webhookSigningSecret": "w2"},
    }, headers=h)
    assert dup.status_code == 409, dup.text


def test_non_payment_type_still_one_per_type(client, session_factory):
    h = _admin(client)
    r1 = client.post("/integrations/connections", json={
        "provider": "smtp", "name": "Mail", "config": {"host": "h", "port": "587", "security": "starttls", "fromEmail": "a@b.c"},
        "credentials": {},
    }, headers=h)
    assert r1.status_code == 201, r1.text
    # smtp + s3 are different types; but a 2nd email-type would be blocked. Use s3 (a different type) → allowed,
    # then a duplicate email type is impossible (only one email provider 'smtp'); assert the 2nd smtp dup is blocked
    # via the (tenant, provider) unique anyway. Here assert a storage one-per-type:
    r2 = client.post("/integrations/connections", json={
        "provider": "s3", "name": "S3", "config": {"bucket": "b", "region": "r"},
        "credentials": {"accessKeyId": "a", "secretAccessKey": "s"},
    }, headers=h)
    assert r2.status_code == 201, r2.text
    dup = client.post("/integrations/connections", json={
        "provider": "r2", "name": "R2", "config": {"bucket": "b2", "accountId": "acc"},
        "credentials": {"accessKeyId": "a", "secretAccessKey": "s"},
    }, headers=h)
    assert dup.status_code == 409, dup.text  # second STORAGE type blocked (one-per-type)


# ── AC-07-26 — adapters registered ───────────────────────────────────────────

def test_payment_providers_registered():
    from app.integrations import get_provider

    for key in ("stripe", "billplz"):
        p = get_provider(key)
        assert p is not None and p.type == "payment"
        for op in ("create_checkout", "verify_webhook", "refund", "test"):
            assert callable(getattr(p, op))


# ── AC-07-27 — checkout creates Pending row + redirect ───────────────────────

def test_checkout_creates_pending_and_redirects(client, session_factory, monkeypatch):
    from app.integrations import CheckoutResult, StripeProvider

    monkeypatch.setattr(
        StripeProvider, "create_checkout",
        lambda *a, **k: CheckoutResult(redirect_url="https://stripe.test/cs_1", external_payment_id="pi_1"),
    )
    db = session_factory()
    _stripe_connection(db)
    iid = _make_issued_invoice(db)
    db.close()

    h = _admin(client)
    res = client.post(f"/finance/invoices/{iid}/checkout", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["redirectUrl"].startswith("https://stripe.test/")
    pay_id = body["paymentId"]

    db = session_factory()
    pay = db.query(Payment).filter(Payment.id == pay_id).first()
    assert pay is not None
    assert pay.method == "GATEWAY"
    assert pay.external_ref == pay.id
    assert pay.paid_at is None  # still Pending
    assert db.query(Status).filter(Status.id == pay.status_id).first().key == "pending"
    db.close()


# ── AC-07-25 — per-project connection resolution ─────────────────────────────

def test_per_project_connection_resolution(client, session_factory, monkeypatch):
    from app.integrations import CheckoutResult, StripeProvider

    captured = {}

    def fake_checkout(self, config, credentials, **kw):
        captured["secretKey"] = credentials.get("secretKey")
        return CheckoutResult(redirect_url="https://x.test", external_payment_id="pi")

    monkeypatch.setattr(StripeProvider, "create_checkout", fake_checkout)

    db = session_factory()
    # tenant default (Stripe)
    _stripe_connection(db)
    # a project-specific stripe… but provider unique blocks 2 stripe; use billplz override
    from app.integrations import BillplzProvider
    monkeypatch.setattr(
        BillplzProvider, "create_checkout",
        lambda *a, **k: CheckoutResult(redirect_url="https://billplz.test", external_payment_id="bill_1"),
    )
    override = Connection(
        tenant_id=TENANT, provider="billplz", type="payment", name="Billplz",
        config_json={"collectionId": "c"}, credentials_json=encrypt_secret({"apiKey": "k", "xSignatureKey": "x"}),
        status="ACTIVE",
    )
    db.add(override)
    db.flush()
    # a project pointing at the override
    from modules.ems.models import Project, ProjectTemplate, ProjectType
    pt = ProjectType(tenant_id=TENANT, name="T")
    db.add(pt)
    db.flush()
    tmpl = ProjectTemplate(tenant_id=TENANT, type_id=pt.id, name="Tmpl")
    db.add(tmpl)
    db.flush()
    proj = Project(tenant_id=TENANT, template_id=tmpl.id, title="Ev", payment_connection_id=override.id)
    db.add(proj)
    db.flush()
    # invoice on that project
    from app.module_platform import resolve_capability
    handler = resolve_capability(db, TENANT, "finance.create_invoice", 1)
    res = handler(db, TENANT, {"projectId": proj.id, "billToType": "Profile", "billToId": "p", "currency": "USD",
                               "lines": [{"description": "x", "qty": 1, "unitPrice": "50.00"}]})
    db.commit()
    iid = res["id"]
    InvoiceService(db).transition(TENANT, iid, _status_id(db, INVOICE_ENTITY, "issued"), None)
    db.close()

    h = _admin(client)
    r = client.post(f"/finance/invoices/{iid}/checkout", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["redirectUrl"] == "https://billplz.test"  # project override used


# ── AC-07-28/31 — webhook route, tenant from connection, flip Pending→Succeeded

def test_webhook_flips_pending_to_succeeded(client, session_factory, monkeypatch):
    from app.integrations import CheckoutResult, StripeProvider

    monkeypatch.setattr(
        StripeProvider, "create_checkout",
        lambda *a, **k: CheckoutResult(redirect_url="https://x.test", external_payment_id="pi_1"),
    )
    db = session_factory()
    conn_id = _stripe_connection(db)
    iid = _make_issued_invoice(db, total="100.00")
    db.close()

    h = _admin(client)
    pay_id = client.post(f"/finance/invoices/{iid}/checkout", headers=h).json()["paymentId"]

    body = json.dumps(_stripe_event("payment_intent.succeeded", ext_ref=pay_id, amount_minor=10000)).encode()
    res = client.post(
        f"/integrations/webhooks/stripe/{conn_id}",
        content=body, headers={"stripe-signature": _sign_stripe(body)},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "processed"

    db = session_factory()
    pay = db.query(Payment).filter(Payment.id == pay_id).first()
    assert db.query(Status).filter(Status.id == pay.status_id).first().key == "succeeded"
    assert pay.paid_at is not None
    inv = db.query(Invoice).filter(Invoice.id == iid).first()
    assert db.query(Status).filter(Status.id == inv.status_id).first().key == "paid"
    db.close()


# ── AC-07-29 — signature + timestamp tolerance ───────────────────────────────

def test_invalid_signature_rejected(client, session_factory):
    db = session_factory()
    conn_id = _stripe_connection(db)
    db.close()
    body = json.dumps(_stripe_event("payment_intent.succeeded", ext_ref="nope")).encode()
    res = client.post(
        f"/integrations/webhooks/stripe/{conn_id}",
        content=body, headers={"stripe-signature": "t=1,v1=deadbeef"},
    )
    assert res.json()["status"] == "rejected"


def test_stale_event_rejected(client, session_factory):
    db = session_factory()
    conn_id = _stripe_connection(db)
    db.close()
    body = json.dumps(_stripe_event("payment_intent.succeeded", ext_ref="nope")).encode()
    stale_ts = int(time.time()) - 99999
    res = client.post(
        f"/integrations/webhooks/stripe/{conn_id}",
        content=body, headers={"stripe-signature": _sign_stripe(body, ts=stale_ts)},
    )
    assert res.json()["status"] == "rejected"


# ── AC-07-30 — idempotent ingest + idempotent flip ───────────────────────────

def test_idempotent_ingest_and_flip(client, session_factory, monkeypatch):
    from app.integrations import CheckoutResult, StripeProvider

    monkeypatch.setattr(
        StripeProvider, "create_checkout",
        lambda *a, **k: CheckoutResult(redirect_url="https://x.test", external_payment_id="pi_1"),
    )
    db = session_factory()
    conn_id = _stripe_connection(db)
    iid = _make_issued_invoice(db, total="100.00")
    db.close()
    h = _admin(client)
    pay_id = client.post(f"/finance/invoices/{iid}/checkout", headers=h).json()["paymentId"]

    body = json.dumps(_stripe_event("payment_intent.succeeded", ext_ref=pay_id, event_id="evt_dup")).encode()
    sig = {"stripe-signature": _sign_stripe(body)}
    r1 = client.post(f"/integrations/webhooks/stripe/{conn_id}", content=body, headers=sig)
    assert r1.json()["status"] == "processed"
    # same event id → duplicate no-op
    r2 = client.post(f"/integrations/webhooks/stripe/{conn_id}", content=body, headers={"stripe-signature": _sign_stripe(body)})
    assert r2.json()["status"] == "duplicate"

    # a DIFFERENT event id but the payment is already Succeeded → flip is a no-op
    body2 = json.dumps(_stripe_event("payment_intent.succeeded", ext_ref=pay_id, event_id="evt_other")).encode()
    r3 = client.post(f"/integrations/webhooks/stripe/{conn_id}", content=body2, headers={"stripe-signature": _sign_stripe(body2)})
    assert r3.json()["result"]["applied"] is False  # not re-credited

    db = session_factory()
    # exactly one Succeeded payment, paid total == 100 (never doubled)
    paid = (
        db.query(Payment).filter(Payment.invoice_id == iid, Payment.paid_at.isnot(None)).all()
    )
    assert len(paid) == 1
    assert sum((p.amount for p in paid), Decimal(0)) == Decimal("100.0000")
    db.close()


# ── AC-07-32 — gateway_fee captured ──────────────────────────────────────────

def test_gateway_fee_captured(client, session_factory, monkeypatch):
    from app.integrations import CheckoutResult, StripeProvider

    monkeypatch.setattr(
        StripeProvider, "create_checkout",
        lambda *a, **k: CheckoutResult(redirect_url="https://x.test", external_payment_id="pi_1"),
    )
    db = session_factory()
    conn_id = _stripe_connection(db)
    iid = _make_issued_invoice(db, total="100.00")
    db.close()
    h = _admin(client)
    pay_id = client.post(f"/finance/invoices/{iid}/checkout", headers=h).json()["paymentId"]
    body = json.dumps(_stripe_event("charge.succeeded", ext_ref=pay_id, amount_minor=10000, fee_minor=320)).encode()
    client.post(f"/integrations/webhooks/stripe/{conn_id}", content=body, headers={"stripe-signature": _sign_stripe(body)})

    db = session_factory()
    pay = db.query(Payment).filter(Payment.id == pay_id).first()
    assert pay.gateway_fee == Decimal("3.2000")  # 320 cents
    db.close()


# ── AC-07-33 — abandoned Pending reaped → Expired ────────────────────────────

def test_reaper_expires_abandoned_pending(client, session_factory):
    from datetime import datetime, timedelta, timezone

    db = session_factory()
    iid = _make_issued_invoice(db, total="50.00")
    pending = _status_id(db, PAYMENT_ENTITY, "pending")
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    pay = Payment(tenant_id=TENANT, invoice_id=iid, amount=Decimal("50.0000"), method="GATEWAY",
                  status_id=pending, external_ref="x")
    db.add(pay)
    db.flush()
    pay.created_at = old
    db.commit()
    n = PaymentService(db).reap_abandoned(TENANT)
    assert n == 1
    db.refresh(pay)
    assert db.query(Status).filter(Status.id == pay.status_id).first().key == "expired"
    db.close()


# ── AC-07-34 — out-of-order webhook retried, not hard-failed ─────────────────

def test_out_of_order_webhook_retried(client, session_factory):
    db = session_factory()
    conn_id = _stripe_connection(db)
    db.close()
    # success event for a payment that was never created → RetryableWebhook → 'retry'
    body = json.dumps(_stripe_event("payment_intent.succeeded", ext_ref="does-not-exist", event_id="evt_oo")).encode()
    res = client.post(f"/integrations/webhooks/stripe/{conn_id}", content=body, headers={"stripe-signature": _sign_stripe(body)})
    assert res.status_code == 200
    assert res.json()["status"] == "retry"
    # the idempotency row must be REMOVED so the retry isn't swallowed as duplicate
    db = session_factory()
    assert db.query(IntegrationLog).filter(IntegrationLog.external_event_id == "evt_oo").first() is None
    db.close()


# ── AC-07-36 — dispute → Disputed ────────────────────────────────────────────

def test_dispute_flips_to_disputed(client, session_factory, monkeypatch):
    from app.integrations import CheckoutResult, StripeProvider

    monkeypatch.setattr(
        StripeProvider, "create_checkout",
        lambda *a, **k: CheckoutResult(redirect_url="https://x.test", external_payment_id="pi_1"),
    )
    db = session_factory()
    conn_id = _stripe_connection(db)
    iid = _make_issued_invoice(db, total="100.00")
    db.close()
    h = _admin(client)
    pay_id = client.post(f"/finance/invoices/{iid}/checkout", headers=h).json()["paymentId"]
    # succeed first
    b1 = json.dumps(_stripe_event("payment_intent.succeeded", ext_ref=pay_id, event_id="evt_s")).encode()
    client.post(f"/integrations/webhooks/stripe/{conn_id}", content=b1, headers={"stripe-signature": _sign_stripe(b1)})
    # dispute
    b2 = json.dumps(_stripe_event("charge.dispute.created", ext_ref=pay_id, event_id="evt_d")).encode()
    r = client.post(f"/integrations/webhooks/stripe/{conn_id}", content=b2, headers={"stripe-signature": _sign_stripe(b2)})
    assert r.json()["status"] == "processed"
    db = session_factory()
    pay = db.query(Payment).filter(Payment.id == pay_id).first()
    assert db.query(Status).filter(Status.id == pay.status_id).first().key == "disputed"
    db.close()


# ── AC-07-28 — masked log ────────────────────────────────────────────────────

def test_webhook_log_is_masked(client, session_factory, monkeypatch):
    db = session_factory()
    conn_id = _stripe_connection(db)
    db.close()
    # an unsigned (rejected) delivery still logs, masked
    body = json.dumps({"id": "evt_m", "type": "x", "data": {"object": {"secret": "supersecret", "card": "4242424242424242"}}}).encode()
    client.post(f"/integrations/webhooks/stripe/{conn_id}", content=body, headers={"stripe-signature": "bad"})
    db = session_factory()
    log = db.query(IntegrationLog).filter(IntegrationLog.provider == "stripe").first()
    assert log is not None
    blob = json.dumps(log.request_json)
    assert "supersecret" not in blob
    assert "4242424242424242" not in blob
    db.close()


# ── AC-07-49 — webhook tenant isolation (unknown connection rejected) ────────

def test_unknown_connection_rejected(client, session_factory):
    body = json.dumps(_stripe_event("payment_intent.succeeded", ext_ref="x")).encode()
    res = client.post("/integrations/webhooks/stripe/nonexistent", content=body, headers={"stripe-signature": _sign_stripe(body)})
    assert res.json()["status"] == "rejected"


# ── AC-07-35 — post-payment reaction: tickets Valid + participant Eligible ───

def test_post_payment_reaction(client, session_factory):
    """Invoice→Paid makes its admission tickets Valid + the owning participant
    Eligible, failure-isolated on the event bus (AC-07-35)."""
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import PARTICIPANT_ENTITY, Ticket, ProjectParticipant
    from tests.test_cluster_d import _admin as _ems_admin, _confirm_ticket, _ga_offering, _make_event

    h = _ems_admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "PayReact")
    tid = _confirm_ticket(client, session_factory, pid, o["id"], email="pay@x.com")

    db = session_factory()
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    inv_id = t.invoice_id
    pp_id = t.participant_id
    assert inv_id is not None
    # Issue the invoice, then record full payment → derives Paid → reaction fires.
    iss = _status_id(db, INVOICE_ENTITY, "issued")
    InvoiceService(db).transition(DEFAULT_TENANT_ID, inv_id, iss, None)
    inv = db.query(Invoice).filter(Invoice.id == inv_id).first()
    total = float(inv.total)
    db.close()

    res = client.post(
        f"/finance/invoices/{inv_id}/payments",
        json={"amount": total, "method": "CASH"}, headers=h,
    )
    assert res.status_code == 200, res.text

    db = session_factory()
    inv = db.query(Invoice).filter(Invoice.id == inv_id).first()
    assert db.query(Status).filter(Status.id == inv.status_id).first().key == "paid"
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    assert db.query(Status).filter(Status.id == t.status_id).first().key == "valid"
    pp = db.query(ProjectParticipant).filter(ProjectParticipant.id == pp_id).first()
    elig = (
        db.query(Status)
        .filter(Status.entity_type == PARTICIPANT_ENTITY, Status.scope_id == pid, Status.key == "eligible")
        .first()
    )
    assert pp.status_id == elig.id
    db.close()


# ── AC-07-10 — manual GATEWAY rejected (still holds) ─────────────────────────

def test_manual_gateway_payment_rejected(client, session_factory):
    db = session_factory()
    iid = _make_issued_invoice(db, total="50.00")
    db.close()
    h = _admin(client)
    res = client.post(f"/finance/invoices/{iid}/payments", json={"amount": 50, "method": "GATEWAY"}, headers=h)
    assert res.status_code == 422
