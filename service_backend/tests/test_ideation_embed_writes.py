"""Ideation embed-authed write routes (WS-C / AC-CAP-9..13).

Full operator-grid parity inside the iframe (G1): create / update / vote /
status / reorder / hard-delete under the EMBED token, each scoped to the
connection's tenant AND product. Covers, per write: happy path under a valid
embed token, cross-tenant denied, cross-product denied (same tenant, different
product → 404), and expired/invalid token → 401. Plus product-scoped list/board.

The signing-secret / minted token are never asserted into logs; scope is the
token's, never the request's.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID

CONNECTION_ID = "sorento-ideation"
SIGNING_SECRET = "ideation-embed-shared-secret-0123456789"
ORIGIN = "https://fe-sorento.foundryx.my"
AUD = "ideation-embed"


# ── fixtures / helpers ────────────────────────────────────────────────────────
@pytest.fixture
def ideation_client(ideation_session_factory):
    def override_get_db():
        db = ideation_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._factory = ideation_session_factory
        yield c
    app.dependency_overrides.clear()


def _seed_connection(
    factory,
    *,
    connection_id=CONNECTION_ID,
    secret=SIGNING_SECRET,
    tenant_id=DEFAULT_TENANT_ID,
    product_id=None,
    active=True,
):
    from modules.ideation.services.embed import upsert_connection

    db = factory()
    try:
        upsert_connection(
            db,
            connection_id=connection_id,
            tenant_id=tenant_id,
            signing_secret=secret,
            allowed_origins=[ORIGIN],
            product_id=product_id,
            is_active=active,
        )
    finally:
        db.close()


def _assertion(*, secret=SIGNING_SECRET, connection_id=CONNECTION_ID, exp=None, iat=None, sub="user-1"):
    now = datetime.now(timezone.utc)
    payload = {
        "typ": "assertion",
        "aud": AUD,
        "iss": "sorento",
        "sub": sub,
        "email": "a@sorento.my",
        "name": "Alice",
        "connection_id": connection_id,
        "iat": iat if iat is not None else int(now.timestamp()),
        "exp": exp if exp is not None else int((now + timedelta(seconds=120)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def _mint(client, *, connection_id=CONNECTION_ID, secret=SIGNING_SECRET, sub="user-1"):
    res = client.post(
        "/embed/session",
        json={
            "connection_id": connection_id,
            "assertion": _assertion(connection_id=connection_id, secret=secret, sub=sub),
        },
    )
    assert res.status_code == 200, res.text
    return res.json()["token"]


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _token(client, email="demo@example.com", password="demo1234") -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _create_software_product(client, h, name="Sorento CRM") -> str:
    res = client.post("/products", headers=h, json={"name": name, "kind": "software"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _insert_idea(
    factory,
    product_id,
    *,
    problem="Export orders to Excel",
    tenant_id=DEFAULT_TENANT_ID,
    status_key="captured",
) -> str:
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    db = factory()
    try:
        idea = Idea(
            tenant_id=tenant_id,
            product_id=product_id,
            status_id=idea_status_id(db, status_key),
            intake_definition_key="ideation",
            problem=problem,
            raw_text=problem,
            source="whatsapp",
        )
        db.add(idea)
        db.commit()
        return idea.id
    finally:
        db.close()


@pytest.fixture
def scoped(ideation_client):
    """A product-scoped embed connection + a same-tenant OTHER product with its
    own idea (the cross-product foil). Returns the pieces the write tests share."""
    h = _auth(ideation_client)
    product_id = _create_software_product(ideation_client, h, name="Product A")
    other_product_id = _create_software_product(ideation_client, h, name="Product B")
    _seed_connection(ideation_client._factory, product_id=product_id)
    in_scope = _insert_idea(ideation_client._factory, product_id, problem="in scope")
    other_product = _insert_idea(
        ideation_client._factory, other_product_id, problem="other product"
    )
    other_tenant = _insert_idea(
        ideation_client._factory, product_id, problem="other tenant", tenant_id="tenant-x"
    )
    token = _mint(ideation_client)
    return {
        "client": ideation_client,
        "h": h,
        "product_id": product_id,
        "other_product_id": other_product_id,
        "in_scope": in_scope,
        "other_product": other_product,
        "other_tenant": other_tenant,
        "token": token,
        "bearer": _bearer(token),
    }


EXPIRED_BEARER = _bearer("not-a-real-embed-token")


# ── product-scoped list + board ───────────────────────────────────────────────
def test_embed_list_product_scoped(scoped):
    listed = scoped["client"].get("/embed/ideas", headers=scoped["bearer"])
    assert listed.status_code == 200, listed.text
    problems = {r["problem"] for r in listed.json()}
    assert problems == {"in scope"}  # not "other product", not "other tenant"


def test_embed_board_product_scoped(scoped):
    board = scoped["client"].get("/embed/board", headers=scoped["bearer"])
    assert board.status_code == 200, board.text
    all_problems = {
        i["problem"] for col in board.json()["columns"] for i in col["ideas"]
    }
    assert all_problems == {"in scope"}


def test_embed_list_tenant_only_when_unscoped(ideation_client):
    """A connection with no product_id keeps the tenant-only behaviour (today)."""
    h = _auth(ideation_client)
    pa = _create_software_product(ideation_client, h, name="Product A")
    pb = _create_software_product(ideation_client, h, name="Product B")
    _seed_connection(ideation_client._factory, product_id=None)
    _insert_idea(ideation_client._factory, pa, problem="a")
    _insert_idea(ideation_client._factory, pb, problem="b")
    token = _mint(ideation_client)
    listed = ideation_client.get("/embed/ideas", headers=_bearer(token))
    assert {r["problem"] for r in listed.json()} == {"a", "b"}


def test_validate_returns_product_id(scoped):
    res = scoped["client"].post("/embed/validate", json={"token": scoped["token"]})
    assert res.status_code == 200, res.text
    assert res.json()["product_id"] == scoped["product_id"]


def test_minted_token_carries_product_id(scoped):
    from app.security import decode_access_token

    assert decode_access_token(scoped["token"])["product_id"] == scoped["product_id"]


# ── create ────────────────────────────────────────────────────────────────────
def test_embed_create_happy(scoped):
    res = scoped["client"].post(
        "/embed/ideas",
        headers=scoped["bearer"],
        json={"problem": "new idea from iframe", "rawText": "note"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["problem"] == "new idea from iframe"
    # Product is FORCED to the connection's product (never chosen by the iframe).
    assert body["productId"] == scoped["product_id"]


def test_embed_create_rejected_without_product_scope(ideation_client):
    _seed_connection(ideation_client._factory, product_id=None)
    token = _mint(ideation_client)
    res = ideation_client.post(
        "/embed/ideas", headers=_bearer(token), json={"problem": "x"}
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "embed_scope_required"


def test_embed_create_requires_token(ideation_client):
    _seed_connection(ideation_client._factory, product_id="p")
    res = ideation_client.post("/embed/ideas", json={"problem": "x"})
    assert res.status_code == 401


# ── update ────────────────────────────────────────────────────────────────────
def test_embed_update_happy(scoped):
    res = scoped["client"].patch(
        f"/embed/ideas/{scoped['in_scope']}",
        headers=scoped["bearer"],
        json={"problem": "edited"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["problem"] == "edited"


def test_embed_update_cross_product_denied(scoped):
    res = scoped["client"].patch(
        f"/embed/ideas/{scoped['other_product']}",
        headers=scoped["bearer"],
        json={"problem": "hax"},
    )
    assert res.status_code == 404
    # And the target is untouched.
    got = scoped["client"].get(
        f"/embed/ideas/{scoped['in_scope']}", headers=scoped["bearer"]
    )
    assert got.status_code == 200


def test_embed_update_cross_tenant_denied(scoped):
    res = scoped["client"].patch(
        f"/embed/ideas/{scoped['other_tenant']}",
        headers=scoped["bearer"],
        json={"problem": "hax"},
    )
    assert res.status_code == 404


def test_embed_update_expired_token(scoped):
    res = scoped["client"].patch(
        f"/embed/ideas/{scoped['in_scope']}",
        headers=EXPIRED_BEARER,
        json={"problem": "x"},
    )
    assert res.status_code == 401


# ── vote ──────────────────────────────────────────────────────────────────────
def test_embed_vote_happy(scoped):
    res = scoped["client"].post(
        f"/embed/ideas/{scoped['in_scope']}/vote",
        headers=scoped["bearer"],
        json={"dir": "up"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["upvotes"] == 1


def test_embed_votes_are_per_sorento_user(scoped):
    """Votes are per HOST (sorento) user, taken from the assertion ``sub`` — NOT one
    shared vote per connection. One user upvotes, a DIFFERENT user downvotes the
    same idea → 1 up + 1 down (distinct entries)."""
    client = scoped["client"]
    idea = scoped["in_scope"]
    r1 = client.post(f"/embed/ideas/{idea}/vote", headers=scoped["bearer"], json={"dir": "up"})
    assert r1.status_code == 200, r1.text
    # A different sorento user (distinct assertion sub) votes the other way.
    other = _bearer(_mint(client, sub="user-2"))
    r2 = client.post(f"/embed/ideas/{idea}/vote", headers=other, json={"dir": "down"})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["upvotes"] == 1 and body["downvotes"] == 1


def test_embed_vote_cross_product_denied(scoped):
    res = scoped["client"].post(
        f"/embed/ideas/{scoped['other_product']}/vote",
        headers=scoped["bearer"],
        json={"dir": "up"},
    )
    assert res.status_code == 404


def test_embed_vote_cross_tenant_denied(scoped):
    res = scoped["client"].post(
        f"/embed/ideas/{scoped['other_tenant']}/vote",
        headers=scoped["bearer"],
        json={"dir": "up"},
    )
    assert res.status_code == 404


def test_embed_vote_expired_token(scoped):
    res = scoped["client"].post(
        f"/embed/ideas/{scoped['in_scope']}/vote",
        headers=EXPIRED_BEARER,
        json={"dir": "up"},
    )
    assert res.status_code == 401


# ── status ────────────────────────────────────────────────────────────────────
def test_embed_status_happy(scoped):
    res = scoped["client"].post(
        f"/embed/ideas/{scoped['in_scope']}/status",
        headers=scoped["bearer"],
        json={"status": "triaged"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "triaged"


def test_embed_status_cross_product_denied(scoped):
    res = scoped["client"].post(
        f"/embed/ideas/{scoped['other_product']}/status",
        headers=scoped["bearer"],
        json={"status": "triaged"},
    )
    assert res.status_code == 404


def test_embed_status_cross_tenant_denied(scoped):
    res = scoped["client"].post(
        f"/embed/ideas/{scoped['other_tenant']}/status",
        headers=scoped["bearer"],
        json={"status": "triaged"},
    )
    assert res.status_code == 404


def test_embed_status_expired_token(scoped):
    res = scoped["client"].post(
        f"/embed/ideas/{scoped['in_scope']}/status",
        headers=EXPIRED_BEARER,
        json={"status": "triaged"},
    )
    assert res.status_code == 401


# ── reorder ───────────────────────────────────────────────────────────────────
def test_embed_reorder_happy(scoped):
    second = _insert_idea(
        scoped["client"]._factory, scoped["product_id"], problem="second in scope"
    )
    res = scoped["client"].put(
        "/embed/ideas/reorder",
        headers=scoped["bearer"],
        json={"orderedIds": [second, scoped["in_scope"]]},
    )
    assert res.status_code == 200, res.text
    returned = res.json()
    # Only the connection's product appears (no cross-product leak).
    assert {r["problem"] for r in returned} == {"in scope", "second in scope"}
    assert returned[0]["id"] == second  # priority 0 = top


def test_embed_reorder_cross_product_denied(scoped):
    """Any id outside the tenant+product scope denies the whole reorder (404) —
    no cross-product priority mutation."""
    res = scoped["client"].put(
        "/embed/ideas/reorder",
        headers=scoped["bearer"],
        json={"orderedIds": [scoped["other_product"], scoped["in_scope"]]},
    )
    assert res.status_code == 404


def test_embed_reorder_cross_tenant_denied(scoped):
    res = scoped["client"].put(
        "/embed/ideas/reorder",
        headers=scoped["bearer"],
        json={"orderedIds": [scoped["other_tenant"]]},
    )
    assert res.status_code == 404


def test_embed_reorder_expired_token(scoped):
    res = scoped["client"].put(
        "/embed/ideas/reorder",
        headers=EXPIRED_BEARER,
        json={"orderedIds": [scoped["in_scope"]]},
    )
    assert res.status_code == 401


# ── delete ────────────────────────────────────────────────────────────────────
def test_embed_delete_happy(scoped):
    res = scoped["client"].delete(
        f"/embed/ideas/{scoped['in_scope']}", headers=scoped["bearer"]
    )
    assert res.status_code == 204, res.text
    gone = scoped["client"].get(
        f"/embed/ideas/{scoped['in_scope']}", headers=scoped["bearer"]
    )
    assert gone.status_code == 404


def test_embed_delete_cross_product_denied(scoped):
    res = scoped["client"].delete(
        f"/embed/ideas/{scoped['other_product']}", headers=scoped["bearer"]
    )
    assert res.status_code == 404
    # The cross-product idea still exists (verified via the operator API).
    got = scoped["client"].get(
        f"/ideation/ideas/{scoped['other_product']}", headers=scoped["h"]
    )
    assert got.status_code == 200


def test_embed_delete_cross_tenant_denied(scoped):
    res = scoped["client"].delete(
        f"/embed/ideas/{scoped['other_tenant']}", headers=scoped["bearer"]
    )
    assert res.status_code == 404


def test_embed_delete_expired_token(scoped):
    res = scoped["client"].delete(
        f"/embed/ideas/{scoped['in_scope']}", headers=EXPIRED_BEARER
    )
    assert res.status_code == 401
