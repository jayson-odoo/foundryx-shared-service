"""Cluster D (sprint-4/05) slice-1 backend tests — venue master + offerings +
capacity minting. Validates AC-05-OFF-*, AC-05-FIN gating excluded (slice 2).

venue CRUD + soft-trash · zones + seat generator (auto labels + counts) · GA vs
RESERVED offerings · capacity minting from a venue's zones · re-mint keeps sales ·
project-scope guard · permission gating.
"""
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _login(client, email, pw):
    return client.post("/auth/login", json={"email": email, "password": pw})


def _h(res):
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _admin(client):
    return _h(_login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD))


def _make_event(client, h):
    t = client.post("/ems/project-types", json={"name": "Conference"}, headers=h).json()
    tmpl = client.post(
        "/ems/project-templates", json={"typeId": t["id"], "name": "Std"}, headers=h
    ).json()
    proj = client.post(
        "/ems/projects", json={"templateId": tmpl["id"], "title": "Tech Summit"}, headers=h
    ).json()
    return proj["id"]


def _make_product(client, h, name="VIP Pass"):
    return client.post(
        "/products", json={"name": name, "kind": "admission"}, headers=h
    ).json()


# ── venues ──


def test_venue_crud_and_soft_trash(client):
    h = _admin(client)
    res = client.post("/ems/venues", json={"name": "Expo Hall", "address": "1 Road", "capacity": 800}, headers=h)
    assert res.status_code == 201, res.text
    v = res.json()
    assert v["name"] == "Expo Hall"
    assert v["zoneCount"] == 0 and v["seatCount"] == 0
    assert v["isTrashed"] is False

    # list (active)
    lst = client.get("/ems/venues", headers=h).json()
    assert any(row["id"] == v["id"] for row in lst["items"])

    # patch
    upd = client.patch(f"/ems/venues/{v['id']}", json={"name": "Expo Hall A"}, headers=h)
    assert upd.status_code == 200
    assert upd.json()["name"] == "Expo Hall A"

    # soft-delete → leaves active list, shows in trashed
    assert client.delete(f"/ems/venues/{v['id']}", headers=h).status_code == 204
    active = client.get("/ems/venues", headers=h).json()
    assert all(row["id"] != v["id"] for row in active["items"])
    trashed = client.get("/ems/venues?trashed=true", headers=h).json()
    assert any(row["id"] == v["id"] for row in trashed["items"])


def test_zones_and_seat_generator(client):
    h = _admin(client)
    v = client.post("/ems/venues", json={"name": "Arena"}, headers=h).json()
    z = client.post(f"/ems/venues/{v['id']}/zones", json={"name": "Main", "kind": "hall"}, headers=h)
    assert z.status_code == 201, z.text
    zone = z.json()
    assert zone["seatCount"] == 0

    # generate 4 rows x 6 = 24 seats, alpha rows
    gen = client.post(
        "/ems/venues/seats/generate",
        json={"zoneId": zone["id"], "rows": 4, "perRow": 6, "rowLabels": "alpha", "startNumber": 1},
        headers=h,
    )
    assert gen.status_code == 201, gen.text
    seats = gen.json()
    assert len(seats) == 24
    labels = {s["label"] for s in seats}
    # labels are zone-prefixed for cross-zone uniqueness (e.g. "Main·A1")
    assert any(l.endswith("·A1") for l in labels) and any(l.endswith("·D6") for l in labels)

    # counts roll up onto zone + venue
    zones = client.get(f"/ems/venues/{v['id']}/zones", headers=h).json()
    assert zones[0]["seatCount"] == 24
    venue = client.get(f"/ems/venues/{v['id']}", headers=h).json()
    assert venue["zoneCount"] == 1 and venue["seatCount"] == 24

    # clear zone seats
    assert client.delete(f"/ems/venues/zones/{zone['id']}/seats", headers=h).status_code == 204
    assert client.get(f"/ems/venues/{v['id']}", headers=h).json()["seatCount"] == 0


# ── offerings ──


def test_ga_offering_has_no_units(client):
    h = _admin(client)
    pid = _make_event(client, h)
    prod = _make_product(client, h, "GA")
    res = client.post(
        f"/ems/projects/{pid}/offerings",
        json={"productId": prod["id"], "allocationMode": "GA", "capacity": 200, "currency": "SGD", "taxRate": 9},
        headers=h,
    )
    assert res.status_code == 201, res.text
    o = res.json()
    assert o["allocationMode"] == "GA"
    assert o["productName"] == "GA"
    assert o["capacity"] == 200
    assert o["unitCount"] == 0

    units = client.get(f"/ems/projects/{pid}/offerings/{o['id']}/units", headers=h).json()
    assert units == []


def test_reserved_offering_mints_zone_seats(client):
    h = _admin(client)
    pid = _make_event(client, h)
    prod = _make_product(client, h, "VIP")

    # venue with two zones, seats minted
    v = client.post("/ems/venues", json={"name": "Theatre"}, headers=h).json()
    z1 = client.post(f"/ems/venues/{v['id']}/zones", json={"name": "Stalls"}, headers=h).json()
    z2 = client.post(f"/ems/venues/{v['id']}/zones", json={"name": "Circle"}, headers=h).json()
    client.post("/ems/venues/seats/generate", json={"zoneId": z1["id"], "rows": 3, "perRow": 5}, headers=h)
    client.post("/ems/venues/seats/generate", json={"zoneId": z2["id"], "rows": 2, "perRow": 5}, headers=h)

    # RESERVED offering drawing ONLY from z1 (15 seats)
    o = client.post(
        f"/ems/projects/{pid}/offerings",
        json={
            "productId": prod["id"], "allocationMode": "RESERVED", "currency": "SGD",
            "taxRate": 9, "venueId": v["id"], "zoneIds": [z1["id"]],
        },
        headers=h,
    ).json()
    assert o["allocationMode"] == "RESERVED"
    assert o["zoneIds"] == [z1["id"]]

    minted = client.post(f"/ems/projects/{pid}/offerings/{o['id']}/mint", headers=h)
    assert minted.status_code == 200, minted.text
    units = minted.json()
    assert len(units) == 15  # only z1's seats
    assert all(u["status"] == "free" for u in units)
    assert all(u["zone"] == "Stalls" for u in units)

    # offering reflects the unit count
    refreshed = client.get(f"/ems/projects/{pid}/offerings/{o['id']}", headers=h).json()
    assert refreshed["unitCount"] == 15


def test_mint_requires_reserved_with_zones(client):
    h = _admin(client)
    pid = _make_event(client, h)
    prod = _make_product(client, h, "GA2")
    o = client.post(
        f"/ems/projects/{pid}/offerings",
        json={"productId": prod["id"], "allocationMode": "GA", "capacity": 50, "currency": "SGD"},
        headers=h,
    ).json()
    # GA can't mint
    assert client.post(f"/ems/projects/{pid}/offerings/{o['id']}/mint", headers=h).status_code == 422


def test_offering_update_and_delete(client):
    h = _admin(client)
    pid = _make_event(client, h)
    prod = _make_product(client, h, "Std")
    o = client.post(
        f"/ems/projects/{pid}/offerings",
        json={"productId": prod["id"], "allocationMode": "GA", "capacity": 100, "currency": "SGD", "maxTicketsPerAttendee": 4},
        headers=h,
    ).json()
    assert o["maxTicketsPerAttendee"] == 4

    upd = client.patch(
        f"/ems/projects/{pid}/offerings/{o['id']}",
        json={"price": 79.0, "maxTicketsPerAttendee": 2},
        headers=h,
    ).json()
    assert upd["price"] == 79.0 and upd["maxTicketsPerAttendee"] == 2

    assert client.delete(f"/ems/projects/{pid}/offerings/{o['id']}", headers=h).status_code == 204
    assert client.get(f"/ems/projects/{pid}/offerings", headers=h).json() == []


def test_offering_scope_guard(client):
    """An offering id from one event isn't reachable under another event."""
    h = _admin(client)
    pid_a = _make_event(client, h)
    pid_b = _make_event(client, h)
    prod = _make_product(client, h, "Scoped")
    o = client.post(
        f"/ems/projects/{pid_a}/offerings",
        json={"productId": prod["id"], "allocationMode": "GA", "capacity": 10, "currency": "SGD"},
        headers=h,
    ).json()
    # wrong project → 404
    assert client.get(f"/ems/projects/{pid_b}/offerings/{o['id']}", headers=h).status_code == 404


def test_venue_endpoints_require_auth(client):
    assert client.get("/ems/venues").status_code == 401
    assert client.post("/ems/venues", json={"name": "X"}).status_code == 401


# ── slice 2: checkout / confirm (atomic ems → finance) ──


def test_confirm_mints_participants_tickets_and_invoice(client, session_factory):
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import Ticket, ProjectParticipant
    from modules.ems.services import CheckoutService

    h = _admin(client)
    pid = _make_event(client, h)
    prod = _make_product(client, h, "ConfPass")
    o = client.post(
        f"/ems/projects/{pid}/offerings",
        json={"productId": prod["id"], "allocationMode": "GA", "capacity": 100, "currency": "MYR", "taxRate": 10},
        headers=h,
    ).json()
    # offering price is null (uses product default 0) → set a price for the invoice
    client.patch(f"/ems/projects/{pid}/offerings/{o['id']}", json={"price": 50}, headers=h)

    db = session_factory()
    order = CheckoutService(db).confirm(
        DEFAULT_TENANT_ID,
        pid,
        [
            {"offeringId": o["id"], "attendee": {"name": "Ann", "email": "ann@x.com"}},
            {"offeringId": o["id"], "attendee": {"name": "Bob", "email": "bob@x.com"}},
        ],
    )
    db.close()

    assert order["ticketCount"] == 2
    assert order["invoiceId"]
    assert order["total"] == 110.0  # 2*50 + 10% tax
    assert set(order["confirmationEmails"]) == {"ann@x.com", "bob@x.com"}

    db = session_factory()
    tks = db.query(Ticket).filter(Ticket.project_id == pid).all()
    assert len(tks) == 2
    assert all(t.qr_token and t.invoice_id == order["invoiceId"] for t in tks)
    parts = db.query(ProjectParticipant).filter(ProjectParticipant.project_id == pid).count()
    assert parts == 2  # one participant per attendee

    # the invoice is resolvable through the finance capability
    from app.module_platform import resolve_capability

    resolver = resolve_capability(db, DEFAULT_TENANT_ID, "invoice.resolve", 1)
    inv = resolver(db, DEFAULT_TENANT_ID, {"id": order["invoiceId"]})
    db.close()
    assert inv["total"] == 110.0 and inv["billToType"] == "Profile"


def test_confirm_comp_skips_invoice(client, session_factory):
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import Ticket
    from modules.ems.services import CheckoutService

    h = _admin(client)
    pid = _make_event(client, h)
    prod = _make_product(client, h, "CompPass")
    o = client.post(
        f"/ems/projects/{pid}/offerings",
        json={"productId": prod["id"], "allocationMode": "GA", "capacity": 10, "currency": "MYR"},
        headers=h,
    ).json()

    db = session_factory()
    order = CheckoutService(db).confirm(
        DEFAULT_TENANT_ID, pid, [{"offeringId": o["id"], "attendee": {"name": "VIP", "email": "vip@x.com"}}], comp=True
    )
    db.close()
    assert order["invoiceId"] is None

    db = session_factory()
    t = db.query(Ticket).filter(Ticket.project_id == pid).first()
    db.close()
    assert t is not None and t.invoice_id is None  # comp = no invoice


def test_public_cart_ga_confirm(client):
    """Anonymous: create cart → set GA qty → confirm → tickets + invoice."""
    h = _admin(client)
    pid = _make_event(client, h)
    prod = _make_product(client, h, "PubGA")
    o = client.post(
        f"/ems/projects/{pid}/offerings",
        json={"productId": prod["id"], "allocationMode": "GA", "capacity": 50, "price": 50, "currency": "MYR", "taxRate": 10},
        headers=h,
    ).json()

    # public — no auth, slug in path
    cart = client.post(f"/public/register/default/{pid}/cart").json()
    cid = cart["cartId"]
    c = client.post(f"/public/register/default/{pid}/cart/{cid}/ga", json={"offeringId": o["id"], "qty": 2}).json()
    assert c["total"] == 110.0  # 2*50 + 10%
    assert c["expiresAt"]  # hold countdown armed

    order = client.post(
        f"/public/register/default/{pid}/cart/{cid}/confirm",
        json={"attendees": [{"name": "P1", "email": "p1@x.com"}, {"name": "P2", "email": "p2@x.com"}]},
    )
    assert order.status_code == 200, order.text
    body = order.json()
    assert body["ticketCount"] == 2 and body["invoiceId"]

    # cart can't be confirmed twice
    again = client.post(
        f"/public/register/default/{pid}/cart/{cid}/confirm",
        json={"attendees": [{"name": "P1", "email": "p1@x.com"}]},
    )
    assert again.status_code == 409


def test_public_cart_reserved_seat_hold_confirm(client):
    h = _admin(client)
    pid = _make_event(client, h)
    prod = _make_product(client, h, "PubVIP")
    v = client.post("/ems/venues", json={"name": "PubArena"}, headers=h).json()
    z = client.post(f"/ems/venues/{v['id']}/zones", json={"name": "Z"}, headers=h).json()
    client.post("/ems/venues/seats/generate", json={"zoneId": z["id"], "rows": 2, "perRow": 3}, headers=h)
    o = client.post(
        f"/ems/projects/{pid}/offerings",
        json={"productId": prod["id"], "allocationMode": "RESERVED", "price": 100, "currency": "MYR", "taxRate": 0, "venueId": v["id"], "zoneIds": [z["id"]]},
        headers=h,
    ).json()
    client.post(f"/ems/projects/{pid}/offerings/{o['id']}/mint", headers=h)

    cart = client.post(f"/public/register/default/{pid}/cart").json()
    cid = cart["cartId"]
    rows = client.get(f"/public/register/default/{pid}/seatmap/{o['id']}?cart={cid}").json()
    seat_id = rows[0]["seats"][0]["id"]
    # hold the seat
    c = client.post(f"/public/register/default/{pid}/cart/{cid}/seat", json={"offeringId": o["id"], "seatId": seat_id}).json()
    assert c["lines"][0]["seatIds"] == [seat_id]
    # seatmap now shows it mine/held
    rows2 = client.get(f"/public/register/default/{pid}/seatmap/{o['id']}?cart={cid}").json()
    held = [s for r in rows2 for s in r["seats"] if s["id"] == seat_id][0]
    assert held["status"] == "held" and held["mine"] is True
    # confirm
    order = client.post(
        f"/public/register/default/{pid}/cart/{cid}/confirm",
        json={"attendees": [{"name": "Seated", "email": "seat@x.com"}]},
    ).json()
    assert order["ticketCount"] == 1
    # the unit is now sold
    rows3 = client.get(f"/public/register/default/{pid}/seatmap/{o['id']}?cart={cid}").json()
    sold = [s for r in rows3 for s in r["seats"] if s["id"] == seat_id][0]
    assert sold["status"] == "sold"


def test_public_ga_oversell_blocked(client):
    h = _admin(client)
    pid = _make_event(client, h)
    prod = _make_product(client, h, "PubCap")
    o = client.post(
        f"/ems/projects/{pid}/offerings",
        json={"productId": prod["id"], "allocationMode": "GA", "capacity": 2, "price": 10, "currency": "MYR"},
        headers=h,
    ).json()
    cart = client.post(f"/public/register/default/{pid}/cart").json()
    over = client.post(f"/public/register/default/{pid}/cart/{cart['cartId']}/ga", json={"offeringId": o["id"], "qty": 3})
    assert over.status_code == 409  # exceeds capacity


def test_public_unknown_tenant_404(client):
    assert client.post("/public/register/nope/x/cart").status_code == 404


def test_confirm_blocks_suspended_profile(client, session_factory):
    """A blocks_access profile can't be confirmed as an attendee."""
    from app.models.status import Status
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import Profile
    from modules.ems.services import CheckoutService

    h = _admin(client)
    pid = _make_event(client, h)
    prod = _make_product(client, h, "BlkPass")
    o = client.post(
        f"/ems/projects/{pid}/offerings",
        json={"productId": prod["id"], "allocationMode": "GA", "capacity": 10, "currency": "MYR"},
        headers=h,
    ).json()
    # pre-create a suspended profile
    pr = client.post("/ems/profiles", json={"email": "susp@x.com", "fullName": "Susp"}, headers=h).json()
    db = session_factory()
    blocked = (
        db.query(Status)
        .filter(Status.entity_type == "profile", Status.tenant_id == DEFAULT_TENANT_ID, Status.blocks_access.is_(True))
        .first()
    )
    prof = db.query(Profile).filter(Profile.id == pr["id"]).first()
    prof.status_id = blocked.id
    db.commit()
    try:
        import pytest

        with pytest.raises(Exception):
            CheckoutService(db).confirm(
                DEFAULT_TENANT_ID, pid, [{"offeringId": o["id"], "attendee": {"name": "Susp", "email": "susp@x.com"}}]
            )
    finally:
        db.close()


def test_offering_currency_defaults_to_tenant(client):
    """Omitting currency falls back to the tenant default (no hard-coded SGD)."""
    from app.models.tenant_settings import DEFAULT_CURRENCY

    h = _admin(client)
    pid = _make_event(client, h)
    prod = _make_product(client, h, "DefCur")
    o = client.post(
        f"/ems/projects/{pid}/offerings",
        json={"productId": prod["id"], "allocationMode": "GA", "capacity": 10},
        headers=h,
    ).json()
    assert o["currency"] == DEFAULT_CURRENCY


def test_public_registration_portal(client):
    h = _admin(client)
    pid = _make_event(client, h)
    prod = _make_product(client, h, "Pub")
    client.post(
        f"/ems/projects/{pid}/offerings",
        json={"productId": prod["id"], "allocationMode": "GA", "capacity": 30},
        headers=h,
    )
    # public, no auth — tenant slug in path
    res = client.get(f"/public/register/default/{pid}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["projectId"] == pid
    assert len(body["offerings"]) == 1
    assert body["offerings"][0]["remaining"] == 30

    # unknown tenant / event → uniform 404
    assert client.get(f"/public/register/nope/{pid}").status_code == 404
    assert client.get("/public/register/default/missing").status_code == 404


# ── slice 3: ticket status entity · nomination · scan · derived check-in ──


def _confirm_ticket(client, session_factory, pid, offering_id, email="att@x.com", name="Att"):
    """Confirm one paid ticket via CheckoutService; return the ticket id."""
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import Ticket
    from modules.ems.services import CheckoutService

    db = session_factory()
    CheckoutService(db).confirm(
        DEFAULT_TENANT_ID, pid, [{"offeringId": offering_id, "attendee": {"name": name, "email": email}}]
    )
    db.close()
    db = session_factory()
    t = db.query(Ticket).filter(Ticket.project_id == pid).order_by(Ticket.created_at.desc()).first()
    tid = t.id
    db.close()
    return tid


def _ga_offering(client, h, pid, name, price=50):
    prod = _make_product(client, h, name)
    return client.post(
        f"/ems/projects/{pid}/offerings",
        json={"productId": prod["id"], "allocationMode": "GA", "capacity": 100, "price": price, "currency": "MYR"},
        headers=h,
    ).json()


def test_ticket_status_entity_seeded(client):
    """The ticket status graph is registered + seeded (Issued→Valid→…)."""
    h = _admin(client)
    # status entity appears in the registry
    resp = client.get("/status-entities", headers=h).json()
    rows = resp["data"] if isinstance(resp, dict) else resp
    types = {t["entityType"]: t for t in rows}
    assert "ticket" in types
    # the seeded graph carries the Issued initial + terminal Void/Refunded
    graph = client.get("/statuses", params={"entityType": "ticket"}, headers=h).json()
    by_key = {s["key"]: s for s in graph["statuses"]}
    assert by_key["issued"]["isInitial"] is True
    assert by_key["void"]["isTerminal"] is True and by_key["refunded"]["isTerminal"] is True
    labels = {t["label"] for t in graph["transitions"]}
    assert {"Validate", "Check in", "Transfer", "Void", "Refund"} <= labels


def test_confirm_sets_ticket_status_id(client, session_factory):
    """A confirmed ticket carries status_id = Issued + a rotation nonce."""
    from modules.ems.models import Ticket

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "StatPass")
    tid = _confirm_ticket(client, session_factory, pid, o["id"])
    db = session_factory()
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    assert t.status == "issued" and t.status_id is not None
    assert t.qr_nonce and t.qr_token
    db.close()


def test_nominate_rotates_qr_and_blocks_re_transfer(client, session_factory):
    from modules.ems.models import Ticket

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "NomPass")
    tid = _confirm_ticket(client, session_factory, pid, o["id"], email="owner@x.com")

    db = session_factory()
    old_token = db.query(Ticket).filter(Ticket.id == tid).first().qr_token
    db.close()

    # nominate to a new profile
    nominee = client.post("/ems/profiles", json={"email": "nominee@x.com", "fullName": "Nina"}, headers=h).json()
    res = client.post(
        f"/ems/projects/{pid}/tickets/{tid}/nominate", json={"profileId": nominee["id"]}, headers=h
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "transferred" and body["qrRotated"] is True
    assert body["attendeeProfileId"] == nominee["id"]

    db = session_factory()
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    assert t.qr_token != old_token  # QR rotated
    assert t.attendee_profile_id == nominee["id"]
    db.close()

    # nominee can't re-transfer (already Transferred)
    other = client.post("/ems/profiles", json={"email": "third@x.com", "fullName": "Theo"}, headers=h).json()
    again = client.post(
        f"/ems/projects/{pid}/tickets/{tid}/nominate", json={"profileId": other["id"]}, headers=h
    )
    assert again.status_code == 409


# ── event-wide tickets list (BL-120) — admin Tickets tab ──────────────────────


def test_list_project_tickets_shape(client, session_factory):
    """GET /ems/projects/{id}/tickets returns the event's tickets with attendee,
    offering, seat, status, paid + invoice details (the real Tickets-tab feed)."""
    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "ListPass", price=50)
    _confirm_ticket(client, session_factory, pid, o["id"], email="ann@x.com", name="Ann Lee")

    res = client.get(f"/ems/projects/{pid}/tickets", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["attendeeName"] == "Ann Lee"
    assert row["attendeeEmail"] == "ann@x.com"
    assert row["offeringName"] == "ListPass"
    assert row["seatLabel"] is None  # GA = no seat
    assert row["ticketStatus"] == "Issued" and row["ticketStatusKey"] == "issued"
    assert row["invoiceId"] and row["invoiceTotal"] == 50.0  # 50, taxRate 0
    assert row["currency"]  # invoice currency (resolved cross-module)
    assert row["paid"] is False  # invoice is Draft (no Paid status this slice)
    assert row["registeredAt"]


def test_list_project_tickets_comp_is_paid(client, session_factory):
    """A comp ticket (no invoice) is treated as paid/NA = paid True."""
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.services import CheckoutService

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "CompList")
    db = session_factory()
    CheckoutService(db).confirm(
        DEFAULT_TENANT_ID, pid,
        [{"offeringId": o["id"], "attendee": {"name": "Vee", "email": "vee@x.com"}}],
        comp=True,
    )
    db.close()

    body = client.get(f"/ems/projects/{pid}/tickets", headers=h).json()
    row = body["items"][0]
    assert row["invoiceId"] is None
    assert row["invoiceTotal"] is None
    assert row["paid"] is True


def test_list_project_tickets_tenant_scoped(client, session_factory):
    """Tickets of one event never leak into another event's list (tenant +
    project scoped)."""
    h = _admin(client)
    pid_a = _make_event(client, h)
    pid_b = _make_event(client, h)
    o_a = _ga_offering(client, h, pid_a, "ScopeA")
    _confirm_ticket(client, session_factory, pid_a, o_a["id"], email="a@x.com")

    body_b = client.get(f"/ems/projects/{pid_b}/tickets", headers=h).json()
    assert body_b["total"] == 0 and body_b["items"] == []


def test_list_project_tickets_search_and_pagination(client, session_factory):
    """Search filters on attendee name/email; pagination caps the page."""
    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "SearchPass")
    _confirm_ticket(client, session_factory, pid, o["id"], email="alice@x.com", name="Alice")
    _confirm_ticket(client, session_factory, pid, o["id"], email="bob@x.com", name="Bob")

    # search by name
    res = client.get(f"/ems/projects/{pid}/tickets", params={"search": "alice"}, headers=h).json()
    assert res["total"] == 1 and res["items"][0]["attendeeEmail"] == "alice@x.com"

    # pagination: page_size 1 returns 1 of 2
    page0 = client.get(f"/ems/projects/{pid}/tickets", params={"page": 0, "page_size": 1}, headers=h).json()
    assert page0["total"] == 2 and len(page0["items"]) == 1


def test_scan_admits_then_double_scan_is_already_in(client, session_factory):
    from modules.ems.models import Ticket, CheckpointLog

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "ScanPass")
    tid = _confirm_ticket(client, session_factory, pid, o["id"])

    db = session_factory()
    qr = db.query(Ticket).filter(Ticket.id == tid).first().qr_token
    db.close()

    cp = client.post(
        f"/ems/projects/{pid}/checkpoints", json={"name": "Main Gate", "entryType": "single"}, headers=h
    )
    assert cp.status_code == 201, cp.text
    cpid = cp.json()["id"]

    # first scan = admitted + ticket → checked_in
    first = client.post(f"/ems/projects/{pid}/checkpoints/{cpid}/scan", json={"qrToken": qr}, headers=h).json()
    assert first["result"] == "admitted" and first["ticketId"] == tid

    db = session_factory()
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    assert t.status == "checked_in"  # status engine moved + mirror synced
    n_logs = db.query(CheckpointLog).filter(CheckpointLog.ticket_id == tid).count()
    db.close()
    assert n_logs == 1

    # second scan = already_in via the SINGLE dedup, never a 500
    second = client.post(f"/ems/projects/{pid}/checkpoints/{cpid}/scan", json={"qrToken": qr}, headers=h).json()
    assert second["result"] == "already_in"
    db = session_factory()
    assert db.query(CheckpointLog).filter(CheckpointLog.ticket_id == tid, CheckpointLog.result == "admitted").count() == 1
    db.close()


def test_scan_tampered_token_is_clean_rejection(client):
    h = _admin(client)
    pid = _make_event(client, h)
    cp = client.post(f"/ems/projects/{pid}/checkpoints", json={"name": "Gate"}, headers=h).json()
    res = client.post(
        f"/ems/projects/{pid}/checkpoints/{cp['id']}/scan",
        json={"qrToken": "this-is-not-a-valid-fernet-token"},
        headers=h,
    )
    assert res.status_code == 200  # not a 500
    assert res.json()["result"] == "denied"


def test_scan_rotated_qr_dies(client, session_factory):
    """After a transfer the OLD QR ciphertext is rejected (nonce mismatch)."""
    from modules.ems.models import Ticket

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "RotPass")
    tid = _confirm_ticket(client, session_factory, pid, o["id"], email="rot@x.com")

    db = session_factory()
    old_qr = db.query(Ticket).filter(Ticket.id == tid).first().qr_token
    db.close()

    nominee = client.post("/ems/profiles", json={"email": "rotn@x.com", "fullName": "Rn"}, headers=h).json()
    client.post(f"/ems/projects/{pid}/tickets/{tid}/nominate", json={"profileId": nominee["id"]}, headers=h)

    cp = client.post(f"/ems/projects/{pid}/checkpoints", json={"name": "RotGate"}, headers=h).json()
    # the OLD QR no longer scans
    res = client.post(f"/ems/projects/{pid}/checkpoints/{cp['id']}/scan", json={"qrToken": old_qr}, headers=h).json()
    assert res["result"] == "denied"
    # but a transferred ticket is terminal → even the new QR is denied as transferred
    db = session_factory()
    new_qr = db.query(Ticket).filter(Ticket.id == tid).first().qr_token
    db.close()
    res2 = client.post(f"/ems/projects/{pid}/checkpoints/{cp['id']}/scan", json={"qrToken": new_qr}, headers=h).json()
    assert res2["result"] == "denied"


def test_derived_participant_checked_in(client, session_factory):
    """R3-2 — the centerpiece. A participant auto-advances Eligible→Checked-in
    once all their admission tickets are checked in (derived-status consumer)."""
    from app.models.tenant import DEFAULT_TENANT_ID
    from app.services import status_machine
    from modules.ems.models import PARTICIPANT_ENTITY, Ticket, ProjectParticipant
    from modules.ems.services import TicketService

    h = _admin(client)
    pid = _make_event(client, h)
    o = _ga_offering(client, h, pid, "DerivPass")
    tid = _confirm_ticket(client, session_factory, pid, o["id"], email="dvip@x.com")

    db = session_factory()
    t = db.query(Ticket).filter(Ticket.id == tid).first()
    pp = db.query(ProjectParticipant).filter(ProjectParticipant.id == t.participant_id).first()
    # move the participant onto Eligible (so the auto Eligible→Checked-in edge is live)
    elig = _scope_status_id(db, PARTICIPANT_ENTITY, DEFAULT_TENANT_ID, pid, "eligible")
    status_machine.transition(db, PARTICIPANT_ENTITY, pp, elig, None, tenant_id=DEFAULT_TENANT_ID)
    db.commit()
    pp_id = pp.id
    db.close()

    # check the ticket in → fires the ticket event → re-derives the participant
    db = session_factory()
    ticket = db.query(Ticket).filter(Ticket.id == tid).first()
    TicketService(db)._move_to_key(DEFAULT_TENANT_ID, ticket, "checked_in", None)
    db.close()

    db = session_factory()
    pp = db.query(ProjectParticipant).filter(ProjectParticipant.id == pp_id).first()
    checked = _scope_status_id(db, PARTICIPANT_ENTITY, DEFAULT_TENANT_ID, pid, "checked_in")
    assert pp.status_id == checked  # auto-advanced via the derived consumer
    db.close()


def _scope_status_id(db, entity_type, tenant_id, scope_id, key):
    from app.models.status import Status

    row = (
        db.query(Status)
        .filter(
            Status.entity_type == entity_type,
            Status.tenant_id == tenant_id,
            Status.scope_id == scope_id,
            Status.key == key,
        )
        .first()
    )
    return row.id if row else None


def test_participant_checkin_edge_is_auto_on_copied_scope(client, session_factory):
    """The Eligible→Checked-in edge copied onto a project's scope is AUTO with
    conditions (AC-03-18 fork/copy carries trigger_mode — the regression guard)."""
    from app.models.status import Status
    from app.models.status_transition import StatusTransition
    from app.models.tenant import DEFAULT_TENANT_ID
    from modules.ems.models import PARTICIPANT_ENTITY

    h = _admin(client)
    pid = _make_event(client, h)
    db = session_factory()
    elig = _scope_status_id(db, PARTICIPANT_ENTITY, DEFAULT_TENANT_ID, pid, "eligible")
    checked = _scope_status_id(db, PARTICIPANT_ENTITY, DEFAULT_TENANT_ID, pid, "checked_in")
    edge = (
        db.query(StatusTransition)
        .filter(
            StatusTransition.from_status_id == elig,
            StatusTransition.to_status_id == checked,
        )
        .first()
    )
    assert edge is not None
    assert edge.trigger_mode == "auto"
    assert edge.conditions_json  # carried (not lost in copy_scope)
    db.close()
