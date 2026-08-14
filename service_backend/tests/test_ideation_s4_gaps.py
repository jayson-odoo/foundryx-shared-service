"""Ideation Phase B-i slice 4 - QA gap-closing tests (added by the TESTER).

Two branches the primary S4 suites leave unexercised, keyed to the ACs:

- **AC-BI-30 (clustering degrades on a DB error):** the ``pg_trgm`` retrieval is
  the ONE place clustering touches Postgres-only SQL. When that statement raises
  (extension missing, etc.) the service must roll back the poisoned transaction
  and fall back to the in-Python ``difflib`` candidate pass - NOT 500 the board.
  The routine suite runs on SQLite, which never enters the pg branch, so this
  test forces it (``_is_postgres`` True + a raising ``_candidate_pairs_pg``) to
  prove the rollback + degrade path.
- **AC-BI-30/32 + AC-BI-17 (a cross-tenant idea can't be promoted):** the
  "Promote to BR" bulk action is ``POST /business-requirements`` with
  ``ideaIds[]``. A foreign-tenant idea id passed at CREATE is refused 422 (the
  polymorphic-target rule, tenant-scoped resolve on read) and no BR is left
  half-linked - the create-with-ideaIds sibling of the link-path cross-tenant
  test in ``test_ideation_br_coverage.py``.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from modules.ideation.services.clustering import ClusteringService
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


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


def _auth(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> dict:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _product(client, h, name="Sorento CRM") -> str:
    res = client.post("/products", headers=h, json={"name": name, "kind": "software"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _idea(client, h, product_id, problem) -> str:
    res = client.post(
        "/ideation/ideas",
        headers=h,
        json={"productId": product_id, "problem": problem, "rawText": problem},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


_SLOW_1 = "Checkout is slow and takes forever to load the page"
_SLOW_2 = "Checkout is slow and takes ages to load the page"

_FULL_ANSWERS = {
    "problem_statement": "CS cannot export orders.",
    "business_goal": "Reduce manual work.",
    "success_metric": "50% fewer support tickets.",
}


# ── AC-BI-30 - clustering degrades on a trigram DB error (difflib fallback) ────


def test_clustering_degrades_on_db_error_falls_back_to_difflib(
    ideation_client, ideation_session_factory, monkeypatch
):
    """A failing ``pg_trgm`` retrieval must NOT block the board - the service
    rolls back and falls back to the difflib candidate pass, still surfacing the
    near-duplicate pair (degraded=True, no LLM). Never a 502/500 (AC-BI-30)."""
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    id1 = _idea(ideation_client, h, pid, _SLOW_1)
    id2 = _idea(ideation_client, h, pid, _SLOW_2)

    db = ideation_session_factory()
    try:
        svc = ClusteringService(db)
        # Force the Postgres branch, then make the trigram statement raise - the
        # same class of failure a missing pg_trgm extension throws.
        monkeypatch.setattr(svc, "_is_postgres", lambda: True)

        def _boom(_tenant_id, _product_id):
            raise SQLAlchemyError("operator does not exist: text % text")

        monkeypatch.setattr(svc, "_candidate_pairs_pg", _boom)
        out = svc.suggest(DEFAULT_TENANT_ID, product_id=pid)
    finally:
        db.close()

    # Degraded to the difflib candidates → the near-dup pair still clusters.
    assert out.degraded is True
    assert len(out.clusters) == 1
    assert set(out.clusters[0].ideaIds) == {id1, id2}


# ── AC-BI-17/32 - a cross-tenant idea can't be promoted into a BR ─────────────


def test_promote_to_br_rejects_cross_tenant_idea(
    ideation_client, ideation_session_factory
):
    """"Promote to BR" = POST /business-requirements with ideaIds. A foreign-
    tenant idea id (even sharing the product) is refused 422 and no BR is left
    behind linked to it (tenant-scoped resolve on read; polymorphic-target)."""
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)

    # Plant a real Idea row under a DIFFERENT tenant, sharing the product id.
    db = ideation_session_factory()
    try:
        from modules.ideation.models import Idea
        from modules.ideation.services.statuses import initial_idea_status_id

        foreign = Idea(
            id="foreign-promote-idea",
            tenant_id="tenant-other",
            product_id=pid,
            status_id=initial_idea_status_id(db, "tenant-other")
            or "idea-status-draft",
            problem="planted cross-tenant idea",
            raw_text="x",
        )
        db.add(foreign)
        db.commit()
    finally:
        db.close()

    res = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={
            "productId": pid,
            "answers": _FULL_ANSWERS,
            "ideaIds": ["foreign-promote-idea"],
        },
    )
    assert res.status_code == 422, res.text
    # The whole create rolled back - no orphan BR linked to the foreign idea.
    rows = ideation_client.get(
        "/ideation/business-requirements", headers=h
    ).json()
    assert rows == []
