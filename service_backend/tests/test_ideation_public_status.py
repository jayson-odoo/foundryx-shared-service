"""Ideation intake redesign - public idea status page (S5), Group F of the UAC
(AC-1601..AC-1604) + the 0010 migration existence check. TEST-FIRST
(PRINCIPLES.md): written BEFORE the S5 implementation lands.

Most tests here work at the sink/router boundary directly (constructing an
already-``captured`` ``Idea`` row via the ORM with the target columns) so they
do not depend on the S1 turn-algorithm redesign (Group A) also being done -
the public status page is a separate, independently-testable surface per the
lane brief.
"""
import importlib.util
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

MODULE_ROOT = Path(__file__).resolve().parents[1] / "modules" / "ideation"
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"


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


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _create_software_product(client, h, name="Sorento CRM") -> str:
    res = client.post("/products", headers=h, json={"name": name, "kind": "software"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _set_delivery(client, h, product_id, base="https://fe-sorento.foundryx.my") -> None:
    res = client.put(
        f"/ideation/products/{product_id}/delivery",
        headers=h,
        json={"productDomainBase": base},
    )
    assert res.status_code == 200, res.text


@pytest.fixture
def setup(ideation_client):
    factory = ideation_client._factory
    h = _auth(ideation_client)
    product_id = _create_software_product(ideation_client, h)
    _set_delivery(ideation_client, h, product_id)
    return {
        "client": ideation_client,
        "factory": factory,
        "product_id": product_id,
        "h": h,
    }


UNIFORM_404 = {"error": {"code": "not_found", "message": "Not found."}}


def _make_captured_idea(
    factory,
    product_id,
    *,
    problem="Show promo price in red on price tags",
    title=None,
    idea_number="IDEA-0001",
    status_token=None,
    is_test=False,
):
    """Directly construct an already-``captured`` Idea row with the S5 columns
    (title/idea_number/status_token) - isolates the public-status tests from
    the Group A turn-algorithm redesign."""
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    db = factory()
    try:
        status_id = idea_status_id(db, "captured", DEFAULT_TENANT_ID)
        assert status_id is not None
        idea = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=product_id,
            status_id=status_id,
            problem=problem,
            title=title,
            idea_number=idea_number,
            status_token=status_token,
            is_test=is_test,
            captured_json={"problem": problem},
        )
        db.add(idea)
        db.commit()
        return idea.id
    finally:
        db.close()


def _idea_row(factory, idea_id):
    from modules.ideation.models import Idea

    db = factory()
    try:
        return db.query(Idea).filter(Idea.id == idea_id).first()
    finally:
        db.close()


# ── AC-1601 - public status returns only title/status/idea_number ────────────


def test_ac_1601_returns_only_title_status_idea_number(setup):
    """AC-1601: an unauthenticated GET on a captured idea's status_token
    returns exactly title, status, ideaNumber - nothing else."""
    s = setup
    token = "tok_" + "a" * 20
    _make_captured_idea(
        s["factory"],
        s["product_id"],
        title="Show promo price in red on price tags",
        idea_number="IDEA-0182",
        status_token=token,
    )
    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body.keys()) == {"title", "status", "ideaNumber"}
    assert body["title"] == "Show promo price in red on price tags"
    assert body["ideaNumber"] == "IDEA-0182"
    assert body["status"] == "New"


def test_ac_1601_no_auth_header_required(setup):
    """AC-1601: the route needs no Authorization header at all (public)."""
    s = setup
    token = "tok_" + "b" * 20
    _make_captured_idea(s["factory"], s["product_id"], status_token=token, idea_number="IDEA-0002")
    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text
    body = res.json()
    for forbidden_key in (
        "problem", "solution", "impact", "department", "submitter",
        "submitterName", "product", "productId", "id", "draftId",
    ):
        assert forbidden_key not in body


# ── AC-1602 - unknown/malformed/draft tokens -> uniform 404 ───────────────────


@pytest.mark.parametrize(
    "token",
    [
        "unknown-token-that-does-not-exist",
        "bad token!",
        "%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20%20",  # decodes whitespace-only
        "x" * 15,  # below the 16-char minimum
        "x" * 400,
        "IDEA-0001",  # an idea number must never resolve as a token
    ],
)
def test_ac_1602_unknown_and_malformed_tokens_uniform_404(setup, token):
    """Tokens here all reach ``/public/ideas/{token}`` as a SINGLE path
    segment. A literal or percent-encoded ``../`` (e.g. ``%2e%2e%2fetc``)
    decodes to a value containing ``/`` - starlette/FastAPI then routes it as
    MULTIPLE segments, missing the ``{token}`` route entirely and hitting the
    framework's generic ``{"detail": "Not Found"}`` 404 instead of ours; that
    is a routing-normalization artifact, not this endpoint's behavior, so it
    is excluded from this parametrization."""
    res = setup["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 404
    assert res.json() == UNIFORM_404


def test_ac_1602_identical_body_unknown_vs_malformed(setup):
    """AC-1602: an unknown token and a malformed token produce byte-identical
    bodies - no distinguishing "wrong token" from "not yours"."""
    s = setup
    res_unknown = s["client"].get("/public/ideas/unknown-xxxxxxxxxxxxxxxxxxxx")
    res_malformed = s["client"].get("/public/ideas/" + "y" * 400)
    assert res_unknown.status_code == res_malformed.status_code == 404
    assert res_unknown.json() == res_malformed.json() == UNIFORM_404


def test_ac_1602_draft_status_row_is_404_even_with_a_token(setup):
    """AC-1602: a draft-status idea's row must 404 even if it somehow carries a
    status_token (drafts never mint one in the real flow; this proves the
    lookup gates on status, not merely token match)."""
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import initial_idea_status_id

    s = setup
    token = "tok_" + "d" * 20
    db = s["factory"]()
    try:
        idea = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=s["product_id"],
            status_id=initial_idea_status_id(db, DEFAULT_TENANT_ID),
            problem="an open draft",
            status_token=token,
        )
        db.add(idea)
        db.commit()
    finally:
        db.close()

    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 404
    assert res.json() == UNIFORM_404


# ── AC-1603 - each token returns only its own idea; token shape ──────────────


def test_ac_1603_each_token_returns_only_its_own_idea(setup):
    s = setup
    token1 = "tok_" + "1" * 20
    token2 = "tok_" + "2" * 20
    _make_captured_idea(
        s["factory"], s["product_id"], title="Idea One", idea_number="IDEA-0001", status_token=token1
    )
    _make_captured_idea(
        s["factory"], s["product_id"], title="Idea Two", idea_number="IDEA-0002", status_token=token2
    )
    res1 = s["client"].get(f"/public/ideas/{token1}")
    res2 = s["client"].get(f"/public/ideas/{token2}")
    assert res1.status_code == res2.status_code == 200
    b1, b2 = res1.json(), res2.json()
    assert b1["title"] == "Idea One"
    assert b1["ideaNumber"] == "IDEA-0001"
    assert b2["title"] == "Idea Two"
    assert b2["ideaNumber"] == "IDEA-0002"
    assert b1 != b2


def test_ac_1603_token_minted_by_sink_matches_shape(setup):
    """AC-1603: the token minted by the completion sink is a signed/random
    per-idea value - never the row's UUID, never its sequential idea_number -
    and matches ``^[A-Za-z0-9_-]{16,64}$``."""
    from modules.ideation.models import Idea
    from modules.ideation.services.sinks import ideation_on_complete_sink
    from modules.ideation.services.statuses import initial_idea_status_id

    s = setup
    db = s["factory"]()
    try:
        idea = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=s["product_id"],
            status_id=initial_idea_status_id(db, DEFAULT_TENANT_ID),
            problem="an idea about to be captured",
            captured_json={"problem": "an idea about to be captured"},
        )
        db.add(idea)
        db.flush()
        ideation_on_complete_sink(db, idea, DEFAULT_TENANT_ID)
        db.commit()
        token = getattr(idea, "status_token", None)
        assert token is not None, "status_token was not minted by the sink"
        assert re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token)
        assert token != idea.id
        assert token != getattr(idea, "idea_number", None)
    finally:
        db.close()


def test_ac_1603_token_is_never_the_sequential_idea_number(setup):
    s = setup
    token = "tok_" + "9" * 20
    _make_captured_idea(
        s["factory"], s["product_id"], idea_number="IDEA-0099", status_token=token
    )
    res = s["client"].get(f"/public/ideas/IDEA-0099")
    assert res.status_code == 404
    assert res.json() == UNIFORM_404


# ── AC-1604 - is_test idea still gets a token + link ──────────────────────────


def test_ac_1604_is_test_idea_still_gets_token_and_link(setup):
    """AC-1604: a completed is_test idea still gets a status_token and a link,
    the same as any other idea."""
    from modules.ideation.models import Idea
    from modules.ideation.services.sinks import ideation_on_complete_sink, mint_idea_link
    from modules.ideation.services.statuses import initial_idea_status_id

    s = setup
    db = s["factory"]()
    try:
        idea = Idea(
            tenant_id=DEFAULT_TENANT_ID,
            product_id=s["product_id"],
            status_id=initial_idea_status_id(db, DEFAULT_TENANT_ID),
            problem="a console/--say test turn",
            captured_json={"problem": "a console/--say test turn"},
            is_test=True,
        )
        db.add(idea)
        db.flush()
        ideation_on_complete_sink(db, idea, DEFAULT_TENANT_ID)
        db.commit()
        token = getattr(idea, "status_token", None)
        assert token is not None
        link = mint_idea_link(db, idea)
        assert link is not None
        assert link == f"https://fe-sorento.foundryx.my/public/ideas/{token}"
    finally:
        db.close()

    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 200, res.text


# ── Review round 1, blocking #2 - layering + tenant signin_allowed ───────────


def test_router_never_queries_the_db_directly():
    """Review round 1 (blocking #2): the public_ideas ROUTER is HTTP/Pydantic
    only - the lookup lives in ``services/public_status.py``. A static check:
    the route HANDLER's own source (not the module docstring, which is free
    to describe the rule in prose) never mentions ``db.query``, and the
    resolve logic is reachable as ``PublicIdeaStatusService.resolve``."""
    import inspect

    from modules.ideation.routers.public_ideas import get_public_idea_status
    from modules.ideation.services.public_status import PublicIdeaStatusService

    source = inspect.getsource(get_public_idea_status)
    assert "db.query" not in source
    assert "PublicIdeaStatusService" in source
    assert hasattr(PublicIdeaStatusService, "resolve")


def test_suspended_tenant_never_serves_a_public_idea_status(setup):
    """Review round 1 (blocking #2 / nit 9): a tenant whose sign-in is
    blocked (status-engine ``blocks_access``, e.g. suspended) must never
    serve its idea's public status page - ``Tenant.signin_allowed`` is the
    single chokepoint core checks per request (``FormService._resolve_public``
    reuses the same predicate for its own public surface); this endpoint
    reuses it too. Uniform 404, same as an unknown token."""
    from app.models.status import TENANT_STATUS_IDS, TENANT_STATUS_SUSPENDED
    from app.models.tenant import Tenant
    from modules.ideation.models import Idea
    from modules.ideation.services.statuses import idea_status_id

    s = setup
    token = "tok_" + "z" * 20
    db = s["factory"]()
    try:
        suspended = Tenant(
            name="Suspended Co",
            slug="suspended-ideation",
            status_id=TENANT_STATUS_IDS[TENANT_STATUS_SUSPENDED],
        )
        db.add(suspended)
        db.flush()
        assert suspended.signin_allowed is False
        status_id = idea_status_id(db, "captured", suspended.id)
        idea = Idea(
            tenant_id=suspended.id,
            product_id=s["product_id"],
            status_id=status_id,
            problem="an idea under a suspended tenant",
            idea_number="IDEA-9001",
            status_token=token,
            captured_json={"problem": "an idea under a suspended tenant"},
        )
        db.add(idea)
        db.commit()
    finally:
        db.close()

    res = s["client"].get(f"/public/ideas/{token}")
    assert res.status_code == 404
    assert res.json() == UNIFORM_404


# ── Migration existence: 0010 chains onto 0009 ────────────────────────────────


def test_migration_0010_ideation_intake_contract_exists_and_chains():
    """The 0010 migration exists and revises 0009_ideation_is_test (current
    head) - imported by path per the codebase's own precedent
    (tests/test_autocount_so_ref.py::test_revision_0019_...)."""
    path = VERSIONS_DIR / "0010_ideation_intake_contract.py"
    assert path.exists(), f"missing migration file: {path}"
    spec = importlib.util.spec_from_file_location("_ideation_rev_0010", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0009_ideation_is_test"
    assert len(module.revision) <= 32
