"""Ideation - idea clustering (Phase B-i slice 4, AC-BI-30/31, Bi-D14).

Two layers:

- **Service-level** (a same-thread factory session): the trigram all-pairs
  retrieval + LLM grouping via the scripted stub (AC-BI-30), and the
  degrade-to-ungrouped path when the model call fails (AC-BI-30 - clustering
  degrades, never blocks the board). Same-thread so the stub's thread-local
  fixture queue is visible.
- **Route-level** (``ideation_client``): the endpoint + its
  ``ideation.clusters.manage`` gate; suggestions only, never auto-promote
  (AC-BI-31).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.sql import func

from app.ai.stub import StubResponse, stub_fixtures
from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from app.security import hash_password
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


def _seed_llm_connection(factory):
    db = factory()
    try:
        db.add(
            Connection(
                tenant_id=DEFAULT_TENANT_ID,
                provider="gemini",
                type="llm",
                name="gemini key",
                config_json={},
                credentials_json=encrypt_secret({"apiKey": "x", "dev": True}),
            )
        )
        db.commit()
    finally:
        db.close()


# Near-identical problems → difflib ratio well above the fallback threshold, so
# they form trigram candidate pairs on SQLite. The unrelated idea does not.
_SLOW_1 = "Checkout is slow and takes forever to load the page"
_SLOW_2 = "Checkout is slow and takes ages to load the page"
_SLOW_3 = "Checkout is slow and takes forever loading the page"
_UNRELATED = "Add dark mode support to the analytics dashboard"


# ── retrieval + degrade (no LLM grouping available) ───────────────────────────


def test_all_pairs_trigram_candidates_degrade_ungrouped(
    ideation_client, ideation_session_factory
):
    """AC-BI-30: the trigram all-pairs step groups near-duplicate ideas; with no
    usable model output (offline stub, no scripted clusters) it DEGRADES to the
    ungrouped connected components - the unrelated idea is excluded."""
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    id1 = _idea(ideation_client, h, pid, _SLOW_1)
    id2 = _idea(ideation_client, h, pid, _SLOW_2)
    id3 = _idea(ideation_client, h, pid, _SLOW_3)
    _idea(ideation_client, h, pid, _UNRELATED)

    db = ideation_session_factory()
    try:
        out = ClusteringService(db).suggest(DEFAULT_TENANT_ID, product_id=pid)
    finally:
        db.close()

    assert out.degraded is True  # no LLM grouping ran
    assert len(out.clusters) == 1
    cluster = out.clusters[0]
    assert set(cluster.ideaIds) == {id1, id2, id3}
    assert cluster.productId == pid
    assert len(cluster.ideas) == 3


def test_llm_grouping_via_scripted_stub(ideation_client, ideation_session_factory):
    """AC-BI-30: ONE LLM call groups + NAMES the trigram candidates. A scripted
    stub returns two labelled clusters over the candidate set."""
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    id1 = _idea(ideation_client, h, pid, _SLOW_1)
    id2 = _idea(ideation_client, h, pid, _SLOW_2)
    id3 = _idea(ideation_client, h, pid, _SLOW_3)
    _seed_llm_connection(ideation_session_factory)

    db = ideation_session_factory()
    try:
        with stub_fixtures(
            StubResponse(
                structured={
                    "clusters": [
                        {"label": "Slow checkout", "ideaIds": [id1, id2, id3]},
                    ]
                }
            )
        ):
            out = ClusteringService(db).suggest(DEFAULT_TENANT_ID, product_id=pid)
    finally:
        db.close()

    assert out.degraded is False
    assert len(out.clusters) == 1
    assert out.clusters[0].label == "Slow checkout"
    assert set(out.clusters[0].ideaIds) == {id1, id2, id3}


def test_degrade_on_llm_error_returns_ungrouped(
    ideation_client, ideation_session_factory
):
    """AC-BI-30: a model failure NEVER blocks the board - the trigram candidates
    are still returned ungrouped, and an ``error`` trace is persisted."""
    from app.models.ai import TRACE_STATUS_ERROR, AiTrace

    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    id1 = _idea(ideation_client, h, pid, _SLOW_1)
    id2 = _idea(ideation_client, h, pid, _SLOW_2)
    _seed_llm_connection(ideation_session_factory)

    db = ideation_session_factory()
    try:
        with stub_fixtures(StubResponse(error="provider exploded")):
            out = ClusteringService(db).suggest(DEFAULT_TENANT_ID, product_id=pid)
    finally:
        db.close()

    assert out.degraded is True
    assert len(out.clusters) == 1
    assert set(out.clusters[0].ideaIds) == {id1, id2}

    # The failed grouping still left an error trace (AC-BI-09 / decision 1).
    db = ideation_session_factory()
    try:
        assert (
            db.query(AiTrace)
            .filter(AiTrace.status == TRACE_STATUS_ERROR)
            .count()
            >= 1
        )
    finally:
        db.close()


def test_degrade_on_non_llm_error_never_500s(
    ideation_client, ideation_session_factory, monkeypatch
):
    """AC-BI-30 robustness: a grouping failure NOT wrapped as LLMError (a
    transport/JSON error the adapter missed) still DEGRADES to ungrouped
    components - it must NEVER propagate and 500 the board."""
    import modules.ideation.services.clustering as clustering_mod

    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    id1 = _idea(ideation_client, h, pid, _SLOW_1)
    id2 = _idea(ideation_client, h, pid, _SLOW_2)
    _seed_llm_connection(ideation_session_factory)

    def boom(self, **kwargs):
        raise RuntimeError("unexpected transport error")

    monkeypatch.setattr(clustering_mod.AiClient, "complete", boom)

    db = ideation_session_factory()
    try:
        out = ClusteringService(db).suggest(DEFAULT_TENANT_ID, product_id=pid)
    finally:
        db.close()

    assert out.degraded is True
    assert set(out.clusters[0].ideaIds) == {id1, id2}


def test_no_candidates_returns_empty(ideation_client, ideation_session_factory):
    """Unrelated ideas produce no candidate pairs → no clusters (not degraded)."""
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    _idea(ideation_client, h, pid, "Add SSO login support")
    _idea(ideation_client, h, pid, "Export invoices to PDF")

    db = ideation_session_factory()
    try:
        out = ClusteringService(db).suggest(DEFAULT_TENANT_ID, product_id=pid)
    finally:
        db.close()

    assert out.clusters == []
    assert out.degraded is False


# ── route + permission gate (AC-BI-31) ────────────────────────────────────────


def test_clusters_endpoint_requires_clusters_manage(
    ideation_client, ideation_session_factory
):
    """The endpoint is gated ``ideation.clusters.manage`` - a user without it is
    refused 403; the seeded Admin holds it."""
    from app.models import Role, User, UserStatus
    from app.models.permission import Permission

    # Admin (holds clusters.manage) - 200.
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    res = ideation_client.get(
        f"/ideation/ideas/clusters?productId={pid}", headers=h
    )
    assert res.status_code == 200, res.text
    assert "clusters" in res.json()

    # A user with only ideas.view - 403.
    db = ideation_session_factory()
    try:
        perms = (
            db.query(Permission)
            .filter(Permission.key.in_(["ideation.ideas.view"]))
            .all()
        )
        role = Role(
            tenant_id=DEFAULT_TENANT_ID,
            name="ViewerOnly",
            description="viewer",
            is_system=False,
        )
        role.permissions = perms
        db.add(role)
        db.flush()
        user = User(
            tenant_id=DEFAULT_TENANT_ID,
            email="clusterviewer@example.com",
            password=hash_password("Viewer123!"),
            name="Viewer",
            status=UserStatus.ACTIVE.value,
            email_verified_at=func.now(),
        )
        user.roles = [role]
        db.add(user)
        db.commit()
    finally:
        db.close()

    h2 = _auth(ideation_client, email="clusterviewer@example.com", password="Viewer123!")
    res2 = ideation_client.get(
        f"/ideation/ideas/clusters?productId={pid}", headers=h2
    )
    assert res2.status_code == 403, res2.text
