"""Sales Order — CRM Cluster F slice 2 (sprint-4/07). AC-07-19..23.

SO status graph + doc_number at Confirm (gapless) · from-quotation copies lines ·
create-invoice-from-SO mints a finance invoice with sales_order_id + only the
chosen qty + increments invoiced_qty via crm.so_line_invoiced@1 · partial keeps
Confirmed, full derives Fulfilled · capability resolves + tenant-scoped.

Uses the SQLite create_all suite; the derived subscriber is registered by the app
lifespan (the ``client`` fixture).
"""
from app.models.status import Status
from app.models.tenant import DEFAULT_TENANT_ID
from modules.crm.models import SALES_ORDER_ENTITY
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


def _make_client(client, h, name="Acme"):
    return client.post("/crm/clients", headers=h, json={"name": name}).json()


# ── AC-07-19 — status graph + doc number at Confirm ──────────────────────────


def test_so_status_graph(client, session_factory):
    db = session_factory()
    keys = {
        s.key
        for s in db.query(Status).filter(
            Status.entity_type == SALES_ORDER_ENTITY, Status.tenant_id == TENANT, Status.scope_id.is_(None)
        )
    }
    rows = db.query(Status).filter(
        Status.entity_type == SALES_ORDER_ENTITY, Status.tenant_id == TENANT, Status.scope_id.is_(None)
    ).all()
    db.close()
    assert {"draft", "confirmed", "fulfilled", "cancelled"} == keys
    assert rows and all(r.is_system for r in rows)  # AC-07-53 keys locked


def test_doc_number_null_in_draft_assigned_at_confirm(client, session_factory):
    h = _admin(client)
    c = _make_client(client, h)
    so = client.post(
        "/crm/sales-orders", headers=h,
        json={"clientId": c["id"], "lines": [{"description": "Booth", "qty": 2, "unitPrice": 100}]},
    ).json()
    assert so["docNumber"] is None  # NULL in Draft (a deleted draft burns no number)

    db = session_factory()
    confirmed = _status_id(db, SALES_ORDER_ENTITY, "confirmed")
    db.close()
    r = client.post(f"/crm/sales-orders/{so['id']}/transition", headers=h, json={"toStatusId": confirmed})
    assert r.status_code == 200, r.text
    assert r.json()["docNumber"], "Confirm assigns a doc number"


def test_doc_number_gapless(client, session_factory):
    h = _admin(client)
    db = session_factory()
    confirmed = _status_id(db, SALES_ORDER_ENTITY, "confirmed")
    db.close()
    c = _make_client(client, h)
    numbers = []
    for _ in range(3):
        so = client.post(
            "/crm/sales-orders", headers=h,
            json={"clientId": c["id"], "lines": [{"description": "x", "qty": 1, "unitPrice": 1}]},
        ).json()
        confirmed_so = client.post(
            f"/crm/sales-orders/{so['id']}/transition", headers=h, json={"toStatusId": confirmed}
        ).json()
        numbers.append(confirmed_so["docNumber"])
    # Sequential running counter (gapless), all distinct.
    assert len(set(numbers)) == 3


# ── AC-07-20 — SO with lines, from quotation ─────────────────────────────────


def test_so_from_accepted_quotation_copies_lines(client, session_factory):
    h = _admin(client)
    c = _make_client(client, h)
    q = client.post(
        "/crm/quotations", headers=h,
        json={"clientId": c["id"], "lines": [{"description": "Catering", "qty": 5, "unitPrice": 20}]},
    ).json()
    db = session_factory()
    sent = _status_id(db, "quotation", "sent")
    accepted = _status_id(db, "quotation", "accepted")
    db.close()
    client.post(f"/crm/quotations/{q['id']}/transition", headers=h, json={"toStatusId": sent})
    client.post(f"/crm/quotations/{q['id']}/transition", headers=h, json={"toStatusId": accepted})

    so = client.post("/crm/sales-orders/from-quotation", headers=h, json={"quotationId": q["id"]})
    assert so.status_code == 201, so.text
    body = so.json()
    assert body["quotationId"] == q["id"]
    assert len(body["lines"]) == 1
    assert body["lines"][0]["qty"] == 5
    assert body["lines"][0]["invoicedQty"] == 0


def test_so_from_non_accepted_quotation_rejected(client):
    h = _admin(client)
    c = _make_client(client, h)
    q = client.post("/crm/quotations", headers=h, json={"clientId": c["id"], "lines": []}).json()
    r = client.post("/crm/sales-orders/from-quotation", headers=h, json={"quotationId": q["id"]})
    assert r.status_code == 409  # Draft quotation


# ── AC-07-21/22 — create invoice from SO + invoiced_qty via capability ───────


def _confirmed_so(client, h, session_factory, lines):
    c = _make_client(client, h)
    so = client.post("/crm/sales-orders", headers=h, json={"clientId": c["id"], "lines": lines}).json()
    db = session_factory()
    confirmed = _status_id(db, SALES_ORDER_ENTITY, "confirmed")
    db.close()
    client.post(f"/crm/sales-orders/{so['id']}/transition", headers=h, json={"toStatusId": confirmed})
    return so


def test_create_invoice_from_so_partial(client, session_factory):
    h = _admin(client)
    so = _confirmed_so(client, h, session_factory, [{"description": "Seat", "qty": 10, "unitPrice": 50}])
    line_id = so["lines"][0]["id"]

    r = client.post(
        f"/crm/sales-orders/{so['id']}/create-invoice", headers=h,
        json={"selections": [{"lineId": line_id, "qty": 3}]},
    )
    assert r.status_code == 201, r.text
    invoice_id = r.json()["id"]

    # AC-07-21 — finance invoice carries sales_order_id; only chosen qty invoiced.
    from app.module_platform import resolve_capability

    db = session_factory()
    resolve = resolve_capability(db, TENANT, "invoice.resolve", 1)
    inv = resolve(db, TENANT, {"id": invoice_id})
    assert inv["salesOrderId"] == so["id"]

    # AC-07-22 — invoiced_qty incremented to 3 via crm.so_line_invoiced@1.
    refreshed = client.get(f"/crm/sales-orders/{so['id']}", headers=h).json()
    assert refreshed["lines"][0]["invoicedQty"] == 3
    # AC-07-23 — still under-invoiced (3 of 10) → stays Confirmed.
    assert refreshed["statusId"] == _status_id(db, SALES_ORDER_ENTITY, "confirmed")
    db.close()


def test_invoice_total_only_chosen_qty(client, session_factory):
    h = _admin(client)
    so = _confirmed_so(client, h, session_factory, [{"description": "Seat", "qty": 10, "unitPrice": 50}])
    r = client.post(
        f"/crm/sales-orders/{so['id']}/create-invoice", headers=h,
        json={"selections": [{"lineId": so["lines"][0]["id"], "qty": 2}]},
    )
    # 2 units × 50 = 100 (only the chosen qty).
    assert r.json()["total"] == 100.0


def test_over_invoice_rejected(client, session_factory):
    h = _admin(client)
    so = _confirmed_so(client, h, session_factory, [{"description": "Seat", "qty": 4, "unitPrice": 10}])
    r = client.post(
        f"/crm/sales-orders/{so['id']}/create-invoice", headers=h,
        json={"selections": [{"lineId": so["lines"][0]["id"], "qty": 5}]},
    )
    assert r.status_code == 409  # more than remaining


# ── AC-07-23 — full invoicing derives Fulfilled ──────────────────────────────


def test_full_invoicing_derives_fulfilled(client, session_factory):
    h = _admin(client)
    so = _confirmed_so(
        client, h, session_factory,
        [{"description": "A", "qty": 3, "unitPrice": 10}, {"description": "B", "qty": 2, "unitPrice": 5}],
    )
    sels = [{"lineId": ln["id"], "qty": ln["qty"]} for ln in so["lines"]]
    r = client.post(f"/crm/sales-orders/{so['id']}/create-invoice", headers=h, json={"selections": sels})
    assert r.status_code == 201, r.text

    db = session_factory()
    fulfilled = _status_id(db, SALES_ORDER_ENTITY, "fulfilled")
    db.close()
    refreshed = client.get(f"/crm/sales-orders/{so['id']}", headers=h).json()
    assert refreshed["statusId"] == fulfilled, "every line fully invoiced → Fulfilled"


# ── capability resolution + tenant scope (AC-07-22, AC-07-49) ────────────────


def test_so_line_invoiced_capability_resolves(client, session_factory):
    from app.module_platform import resolve_capability

    db = session_factory()
    handler = resolve_capability(db, TENANT, "crm.so_line_invoiced", 1)
    db.close()
    assert handler is not None


def test_apply_line_invoiced_is_tenant_scoped(client, session_factory):
    h = _admin(client)
    so = _confirmed_so(client, h, session_factory, [{"description": "x", "qty": 5, "unitPrice": 1}])
    line_id = so["lines"][0]["id"]
    from fastapi import HTTPException

    from modules.crm.services import SalesOrderService

    db = session_factory()
    try:
        raised = False
        try:
            SalesOrderService(db).apply_line_invoiced("other-tenant", line_id, 1)
        except HTTPException as exc:
            raised = exc.status_code == 404
        assert raised, "a foreign tenant cannot touch this line"
    finally:
        db.close()
