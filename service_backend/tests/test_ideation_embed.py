"""Ideation iframe-embed SSO tests (PLAN-ideation-embed-sso, AC-E-5..9, E-12).

Covers the shared-service half of the handshake: connection verify happy path,
tampered / expired / wrong-secret / wrong-issuer / wrong-audience rejection (no
token minted), the embed token's tenant scope, cross-tenant read denial, the
``/embed/validate`` gate, and that the omnichannel widget's ``/embed/session``
still works through the shared dispatcher.

The assertion helper mirrors sorento's ``mint_embed_assertion`` EXACTLY (the
cross-repo contract) so a drift on either side fails here.
"""
import time
import uuid
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
    factory, *, connection_id=CONNECTION_ID, secret=SIGNING_SECRET, tenant_id=DEFAULT_TENANT_ID, active=True
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
            is_active=active,
        )
    finally:
        db.close()


def _assertion(
    *,
    secret=SIGNING_SECRET,
    connection_id=CONNECTION_ID,
    sub="user-1",
    email="a@sorento.my",
    name="Alice",
    aud=AUD,
    iss="sorento",
    typ="assertion",
    iat=None,
    exp=None,
    alg=None,
):
    """Mirrors sorento ``mint_embed_assertion`` — the cross-repo contract."""
    now = datetime.now(timezone.utc)
    payload = {
        "typ": typ,
        "aud": aud,
        "iss": iss,
        "sub": sub,
        "email": email,
        "name": name,
        "connection_id": connection_id,
        "iat": iat if iat is not None else int(now.timestamp()),
        "exp": exp if exp is not None else int((now + timedelta(seconds=120)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=alg or settings.jwt_algorithm)


def _session(client, *, connection_id=CONNECTION_ID, assertion=None, idea_id=None):
    body = {"connection_id": connection_id, "assertion": assertion or _assertion()}
    if idea_id:
        body["idea_id"] = idea_id
    return client.post("/embed/session", json=body)


def _create_software_product(client, h, name="Sorento CRM") -> str:
    res = client.post("/products", headers=h, json={"name": name, "kind": "software"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _token(client, email="demo@example.com", password="demo1234") -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _insert_idea(factory, product_id, *, problem="Export orders to Excel", tenant_id=DEFAULT_TENANT_ID, status_key="captured") -> str:
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


# ── AC-E-5: verify happy path + mint ──────────────────────────────────────────
def test_valid_assertion_mints_embed_token(ideation_client):
    _seed_connection(ideation_client._factory)
    res = _session(ideation_client)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["token"]
    assert body["expires_at"]
    # No cookie is set.
    assert "set-cookie" not in {k.lower() for k in res.headers}
    # The minted token is an embed token scoped to the connection's tenant.
    from app.security import decode_access_token

    claims = decode_access_token(body["token"])
    assert claims["typ"] == "embed"
    assert claims["tenant_id"] == DEFAULT_TENANT_ID
    assert claims["connection_id"] == CONNECTION_ID


def test_idea_id_carried_into_token(ideation_client):
    _seed_connection(ideation_client._factory)
    res = _session(ideation_client, idea_id="idea-123")
    assert res.status_code == 200, res.text
    from app.security import decode_access_token

    assert decode_access_token(res.json()["token"])["idea_id"] == "idea-123"


# ── AC-E-6: rejection matrix (never mints) ────────────────────────────────────
def test_unknown_connection_rejected(ideation_client):
    _seed_connection(ideation_client._factory)
    res = _session(ideation_client, connection_id="does-not-exist")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_connection"


def test_wrong_secret_rejected(ideation_client):
    _seed_connection(ideation_client._factory)
    res = _session(ideation_client, assertion=_assertion(secret="the-wrong-secret-abcdefghij"))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_assertion"


def test_tampered_assertion_rejected(ideation_client):
    _seed_connection(ideation_client._factory)
    good = _assertion()
    tampered = good[:-3] + ("aaa" if good[-3:] != "aaa" else "bbb")
    res = _session(ideation_client, assertion=tampered)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_assertion"


def test_expired_assertion_rejected(ideation_client):
    _seed_connection(ideation_client._factory)
    now = int(time.time())
    res = _session(ideation_client, assertion=_assertion(iat=now - 600, exp=now - 300))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "expired"


def test_wrong_audience_rejected(ideation_client):
    _seed_connection(ideation_client._factory)
    res = _session(ideation_client, assertion=_assertion(aud="some-other-aud"))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_assertion"


def test_wrong_issuer_rejected(ideation_client):
    _seed_connection(ideation_client._factory)
    res = _session(ideation_client, assertion=_assertion(iss="attacker"))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_assertion"


def test_future_iat_rejected(ideation_client):
    _seed_connection(ideation_client._factory)
    now = int(time.time())
    res = _session(ideation_client, assertion=_assertion(iat=now + 3600, exp=now + 7200))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_assertion"


def test_inactive_connection_rejected(ideation_client):
    _seed_connection(ideation_client._factory, active=False)
    res = _session(ideation_client)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_connection"


def test_rotating_secret_invalidates_old_assertion(ideation_client):
    _seed_connection(ideation_client._factory, secret=SIGNING_SECRET)
    old = _assertion(secret=SIGNING_SECRET)
    # Rotate the connection's signing secret.
    _seed_connection(ideation_client._factory, secret="rotated-secret-9876543210xyz")
    res = _session(ideation_client, assertion=old)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_assertion"


# ── AC-E-7/8: embed token validate + tenant-scoped reads ──────────────────────
def test_validate_returns_tenant_scope(ideation_client):
    _seed_connection(ideation_client._factory)
    token = _session(ideation_client).json()["token"]
    res = ideation_client.post("/embed/validate", json={"token": token})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tenant_id"] == DEFAULT_TENANT_ID
    assert body["connection_id"] == CONNECTION_ID
    assert body["scope"] == "ideation"


def test_validate_rejects_bad_token(ideation_client):
    _seed_connection(ideation_client._factory)
    res = ideation_client.post("/embed/validate", json={"token": "not-a-jwt"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_token"


def test_embed_ideas_scoped_to_token_tenant(ideation_client):
    _seed_connection(ideation_client._factory)
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    _insert_idea(ideation_client._factory, pid, problem="mine A")
    _insert_idea(ideation_client._factory, pid, problem="mine B")
    token = _session(ideation_client).json()["token"]

    res = ideation_client.get("/embed/ideas", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    problems = {r["problem"] for r in res.json()}
    assert problems == {"mine A", "mine B"}


def test_embed_ideas_cross_tenant_denied(ideation_client):
    _seed_connection(ideation_client._factory)  # connection for DEFAULT tenant
    h = _auth(ideation_client)
    pid = _create_software_product(ideation_client, h)
    _insert_idea(ideation_client._factory, pid, problem="default tenant idea")
    other_idea = _insert_idea(
        ideation_client._factory, pid, problem="OTHER tenant idea", tenant_id="tenant-other"
    )
    token = _session(ideation_client).json()["token"]
    bearer = {"Authorization": f"Bearer {token}"}

    # List returns ONLY the default tenant's ideas (no cross-tenant leak).
    listed = ideation_client.get("/embed/ideas", headers=bearer).json()
    assert {r["problem"] for r in listed} == {"default tenant idea"}
    # Detail on the other tenant's idea → 404 (not visible to this token).
    detail = ideation_client.get(f"/embed/ideas/{other_idea}", headers=bearer)
    assert detail.status_code == 404


def test_embed_ideas_requires_token(ideation_client):
    _seed_connection(ideation_client._factory)
    res = ideation_client.get("/embed/ideas")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_token"


def test_embed_token_rejected_on_staff_endpoint(ideation_client):
    """Defense-in-depth: an embed token can't authenticate a staff route."""
    _seed_connection(ideation_client._factory)
    token = _session(ideation_client).json()["token"]
    res = ideation_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


# ── AC-E-5/12: admin registry ─────────────────────────────────────────────────
def test_admin_create_and_list_never_returns_secret(ideation_client):
    h = _auth(ideation_client)
    create = ideation_client.post(
        "/ideation/embed-connections",
        headers=h,
        json={
            "connection_id": "admin-made",
            "signing_secret": "a-freshly-set-secret-value",
            "allowed_origins": [ORIGIN],
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["connection_id"] == "admin-made"
    assert body["has_secret"] is True
    assert "signing_secret" not in body and "signing_secret_ciphertext" not in body

    listed = ideation_client.get("/ideation/embed-connections", headers=h)
    assert listed.status_code == 200
    assert any(r["connection_id"] == "admin-made" for r in listed.json())


# ── dispatcher: omnichannel widget embed still works ──────────────────────────
def test_omnichannel_embed_session_still_reachable(ideation_client):
    """A body WITHOUT connection_id is delegated to the omnichannel handler — an
    empty/omni request is NOT swallowed by the ideation path (regression guard)."""
    # No connection_id, no valid omni assertion → omnichannel rejects it (401),
    # proving the request reached the omnichannel handler (not ideation's 401).
    res = ideation_client.post("/embed/session", json={"assertion": "x", "parentOrigin": ORIGIN})
    assert res.status_code == 401
    # Omnichannel's typed code (its verifier), not ideation's invalid_connection.
    assert res.json()["error"]["code"] == "invalid_assertion"
