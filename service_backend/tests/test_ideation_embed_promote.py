"""Ideation embed promote-to-BR (plan 15 B2, AC-15-20..23).

The embed token's ``email`` claim resolves to a shared-service user in the
token's tenant; that user must hold ``ideation.business_requirements.manage``
(the operator rule, no widening). Idea ids are scope-checked before any BR row.
"""
import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.database import get_db
from app.main import app
from tests.test_ideation_br import _make_user, _product
from tests.test_ideation_embed_writes import (
    AUD,
    CONNECTION_ID,
    SIGNING_SECRET,
    _auth,
    _bearer,
    _insert_idea,
    _mint,
    _seed_connection,
)

EMBED_EMAIL = "a@sorento.my"
MANAGE = "ideation.business_requirements.manage"


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


@pytest.fixture
def ctx(ideation_client):
    c = ideation_client
    h = _auth(c)
    pid = _product(c, h, name="Product A")
    other = _product(c, h, name="Product B")
    _seed_connection(c._factory, product_id=pid)
    ideas = [
        _insert_idea(c._factory, pid, problem="one"),
        _insert_idea(c._factory, pid, problem="two"),
    ]
    foreign = _insert_idea(c._factory, other, problem="foreign")
    return {"c": c, "h": h, "pid": pid, "ideas": ideas, "foreign": foreign}


def _br_count(factory):
    from modules.ideation.models import BusinessRequirement

    db = factory()
    try:
        return db.query(BusinessRequirement).count()
    finally:
        db.close()


def _token_without_email(c):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    assertion = jwt.encode(
        {
            "typ": "assertion",
            "aud": AUD,
            "iss": "sorento",
            "sub": "user-noemail",
            "name": "NoEmail",
            "connection_id": CONNECTION_ID,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=120)).timestamp()),
        },
        SIGNING_SECRET,
        algorithm=settings.jwt_algorithm,
    )
    res = c.post("/embed/session", json={"connection_id": CONNECTION_ID, "assertion": assertion})
    assert res.status_code == 200, res.text
    return res.json()["token"]


def test_promote_with_permission_creates_linked_br(ctx):
    c = ctx["c"]
    _make_user(c._factory, EMBED_EMAIL, "pw123456", [MANAGE])
    res = c.post(
        "/embed/ideas/promote",
        headers=_bearer(_mint(c)),
        json={"ideaIds": ctx["ideas"], "title": "Bulk promote"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["id"]
    assert body["title"] == "Bulk promote"
    linked = c.get(f"/ideation/business-requirements/{body['id']}/ideas", headers=ctx["h"])
    assert linked.status_code == 200, linked.text
    assert {i["id"] for i in linked.json()} == set(ctx["ideas"])


def test_promote_without_permission_is_403_forbidden(ctx):
    c = ctx["c"]
    _make_user(c._factory, EMBED_EMAIL, "pw123456", ["ideation.ideas.view"])
    before = _br_count(c._factory)
    res = c.post("/embed/ideas/promote", headers=_bearer(_mint(c)), json={"ideaIds": ctx["ideas"]})
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "forbidden"
    assert _br_count(c._factory) == before


def test_promote_no_matching_user_is_403(ctx):
    c = ctx["c"]
    res = c.post("/embed/ideas/promote", headers=_bearer(_mint(c)), json={"ideaIds": ctx["ideas"]})
    assert res.status_code == 403, res.text


def test_promote_assertion_without_email_is_403(ctx):
    c = ctx["c"]
    _make_user(c._factory, EMBED_EMAIL, "pw123456", [MANAGE])
    res = c.post(
        "/embed/ideas/promote",
        headers=_bearer(_token_without_email(c)),
        json={"ideaIds": ctx["ideas"]},
    )
    assert res.status_code == 403, res.text


def test_promote_out_of_scope_idea_is_404_and_creates_nothing(ctx):
    c = ctx["c"]
    _make_user(c._factory, EMBED_EMAIL, "pw123456", [MANAGE])
    before = _br_count(c._factory)
    res = c.post(
        "/embed/ideas/promote",
        headers=_bearer(_mint(c)),
        json={"ideaIds": [ctx["ideas"][0], ctx["foreign"]]},
    )
    assert res.status_code == 404, res.text
    assert _br_count(c._factory) == before


def test_operator_route_with_embed_token_is_401(ctx):
    c = ctx["c"]
    res = c.post(
        "/ideation/business-requirements",
        headers=_bearer(_mint(c)),
        json={"productId": ctx["pid"], "title": "x", "answers": {}},
    )
    assert res.status_code == 401, res.text


def test_operator_route_unchanged(ctx):
    res = ctx["c"].post(
        "/ideation/business-requirements",
        headers=ctx["h"],
        json={"productId": ctx["pid"], "title": "Op BR", "answers": {}},
    )
    assert res.status_code == 201, res.text


def test_promote_blocked_user_is_403(ctx):
    from app.models import User, UserStatus

    c = ctx["c"]
    _make_user(c._factory, EMBED_EMAIL, "pw123456", [MANAGE])
    db = c._factory()
    try:
        db.query(User).filter(User.email == EMBED_EMAIL).update({"status": UserStatus.BLOCKED.value})
        db.commit()
    finally:
        db.close()
    before = _br_count(c._factory)
    res = c.post("/embed/ideas/promote", headers=_bearer(_mint(c)), json={"ideaIds": ctx["ideas"]})
    assert res.status_code == 403, res.text
    assert _br_count(c._factory) == before


def test_promote_inactive_user_is_403(ctx):
    from app.models import User, UserStatus

    c = ctx["c"]
    _make_user(c._factory, EMBED_EMAIL, "pw123456", [MANAGE])
    # Control: the active user may promote (proves the 403 below is the status).
    ok = c.post("/embed/ideas/promote", headers=_bearer(_mint(c)), json={"ideaIds": ctx["ideas"][:1]})
    assert ok.status_code == 201, ok.text
    db = c._factory()
    try:
        db.query(User).filter(User.email == EMBED_EMAIL).update({"status": UserStatus.INACTIVE.value})
        db.commit()
    finally:
        db.close()
    before = _br_count(c._factory)
    res = c.post("/embed/ideas/promote", headers=_bearer(_mint(c)), json={"ideaIds": ctx["ideas"][1:]})
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "forbidden"
    assert _br_count(c._factory) == before


def test_promote_suspended_tenant_is_403(ctx):
    from app.models import DEFAULT_TENANT_ID, Tenant

    c = ctx["c"]
    _make_user(c._factory, EMBED_EMAIL, "pw123456", [MANAGE])
    token = _mint(c)
    db = c._factory()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).one()
        assert tenant.signin_allowed
        tenant.status.blocks_access = True
        db.commit()
    finally:
        db.close()
    before = _br_count(c._factory)
    res = c.post("/embed/ideas/promote", headers=_bearer(token), json={"ideaIds": ctx["ideas"]})
    assert res.status_code == 403, res.text
    assert _br_count(c._factory) == before


def test_promote_empty_idea_list_is_422_and_creates_nothing(ctx):
    c = ctx["c"]
    _make_user(c._factory, EMBED_EMAIL, "pw123456", [MANAGE])
    before = _br_count(c._factory)
    res = c.post("/embed/ideas/promote", headers=_bearer(_mint(c)), json={"ideaIds": []})
    assert res.status_code == 422, res.text
    assert _br_count(c._factory) == before
