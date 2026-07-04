"""Finance module tests (sprint-4/05, Cluster D / R3-1) — invoice status seed,
the create_invoice + resolve capabilities, and the tenant-facing invoice API.
"""
from app.models.tenant import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _admin(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_invoice_status_seeded(client, session_factory):
    """Installing finance seeds Draft→Issued→Cancelled for the tenant."""
    from app.models.status import Status
    from modules.finance.models import INVOICE_ENTITY

    db = session_factory()
    keys = {
        s.key
        for s in db.query(Status).filter(
            Status.entity_type == INVOICE_ENTITY,
            Status.tenant_id == DEFAULT_TENANT_ID,
            Status.scope_id.is_(None),
        )
    }
    db.close()
    assert {"draft", "issued", "cancelled"} <= keys


def test_create_invoice_capability(client, session_factory):
    from app.module_platform import resolve_capability

    db = session_factory()
    handler = resolve_capability(db, DEFAULT_TENANT_ID, "finance.create_invoice", 1)
    assert handler is not None, "finance.create_invoice@1 must be active for the tenant"
    res = handler(
        db,
        DEFAULT_TENANT_ID,
        {
            "projectId": "proj-x",
            "billToType": "Profile",
            "billToId": "prof-x",
            "currency": "MYR",
            "lines": [
                {"description": "VIP", "qty": 2, "unitPrice": 100, "taxRate": 9},
                {"description": "GA", "qty": 1, "unitPrice": 50, "taxRate": 9},
            ],
        },
    )
    db.commit()
    assert res["currency"] == "MYR"
    # subtotal 250, tax 22.5, total 272.5
    assert res["total"] == 272.5
    assert res["statusId"]  # Draft

    # resolve it back
    resolver = resolve_capability(db, DEFAULT_TENANT_ID, "invoice.resolve", 1)
    got = resolver(db, DEFAULT_TENANT_ID, {"id": res["id"]})
    assert got["total"] == 272.5 and got["billToType"] == "Profile"
    # cross-tenant / missing → None (orphan-safe)
    assert resolver(db, DEFAULT_TENANT_ID, {"id": "nope"}) is None
    db.close()


def test_invoice_currency_defaults_to_tenant(client, session_factory):
    from app.models.tenant_settings import DEFAULT_CURRENCY
    from app.module_platform import resolve_capability

    db = session_factory()
    handler = resolve_capability(db, DEFAULT_TENANT_ID, "finance.create_invoice", 1)
    res = handler(db, DEFAULT_TENANT_ID, {"billToType": "Profile", "billToId": "p", "lines": []})
    db.commit()
    db.close()
    assert res["currency"] == DEFAULT_CURRENCY


def test_invoice_api_list_and_transition(client, session_factory):
    from app.module_platform import resolve_capability

    # seed one invoice via the capability
    db = session_factory()
    handler = resolve_capability(db, DEFAULT_TENANT_ID, "finance.create_invoice", 1)
    inv = handler(db, DEFAULT_TENANT_ID, {"billToType": "Profile", "billToId": "p", "currency": "USD", "lines": [{"description": "x", "qty": 1, "unitPrice": 10}]})
    db.commit()
    db.close()

    h = _admin(client)
    lst = client.get("/finance/invoices", headers=h)
    assert lst.status_code == 200, lst.text
    rows = lst.json()["items"]
    assert any(r["id"] == inv["id"] for r in rows)

    # Draft → Issued via the issue edge
    detail = client.get(f"/finance/invoices/{inv['id']}", headers=h).json()
    # find the issued status id from the graph
    from app.models.status import Status

    db = session_factory()
    issued = (
        db.query(Status)
        .filter(Status.entity_type == "invoice", Status.tenant_id == DEFAULT_TENANT_ID, Status.key == "issued", Status.scope_id.is_(None))
        .first()
    )
    issued_id = issued.id
    db.close()
    mv = client.post(f"/finance/invoices/{inv['id']}/transition", json={"toStatusId": issued_id}, headers=h)
    assert mv.status_code == 200, mv.text
    assert mv.json()["statusId"] == issued_id
    assert detail["billToType"] == "Profile"


def test_invoices_require_auth(client):
    assert client.get("/finance/invoices").status_code == 401


def test_money_is_exact_decimal_numeric(client, session_factory):
    """AC-07-01/02 — money columns are Numeric(14,4), arithmetic is exact Decimal
    (no binary-float drift), and a stored 12.5 reads back as 12.5000."""
    from decimal import Decimal

    from sqlalchemy import Numeric

    from app.module_platform import resolve_capability
    from modules.finance.models import Invoice, InvoiceLine

    # The model columns are Numeric (not Float) — AC-07-01.
    assert isinstance(Invoice.__table__.c.total.type, Numeric)
    assert isinstance(InvoiceLine.__table__.c.amount.type, Numeric)

    db = session_factory()
    handler = resolve_capability(db, DEFAULT_TENANT_ID, "finance.create_invoice", 1)
    # 0.1 + 0.2 would drift in float; with Decimal the total is exact.
    res = handler(
        db,
        DEFAULT_TENANT_ID,
        {
            "billToType": "Profile",
            "billToId": "p",
            "currency": "USD",
            "lines": [
                {"description": "a", "qty": 1, "unitPrice": 0.1},
                {"description": "b", "qty": 1, "unitPrice": 0.2},
            ],
        },
    )
    db.commit()
    # Re-read the stored value — exact decimal, not 0.30000000000000004.
    inv = db.query(Invoice).filter(Invoice.id == res["id"]).first()
    assert inv.total == Decimal("0.3000")
    assert str(inv.total) == "0.3000"  # reads back at 4dp

    # A whole-number-ish total preserves 4dp (12.5 → 12.5000).
    res2 = handler(
        db, DEFAULT_TENANT_ID,
        {"billToType": "Profile", "billToId": "p", "currency": "USD",
         "lines": [{"description": "x", "qty": 1, "unitPrice": 12.5}]},
    )
    db.commit()
    inv2 = db.query(Invoice).filter(Invoice.id == res2["id"]).first()
    assert inv2.total == Decimal("12.5000")
    db.close()
