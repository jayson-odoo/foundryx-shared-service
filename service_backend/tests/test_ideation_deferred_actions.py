"""Ideation's deferred (grace-window) action registrations (sprint-4/23, T5
fix round 1, item 15) - migrating ideation's own `confirm:`-gated destructive
actions onto the shared core grace-window engine (D2). Covers: registration,
park + lapse-commit end to end for each of the 6 keys, and a missing-target
404 at park.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.deferred_actions.registry import deferred_action_for
from app.main import app
from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

CONNECTION_ID = "embed-dla-1"
SIGNING_SECRET = "a-freshly-set-secret-value-1234567890"
ORIGIN = "https://host.example.com"


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


def _product(client, h, name="Sorento CRM") -> str:
    res = client.post("/products", headers=h, json={"name": name, "kind": "software"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _idea(client, h, product_id, problem="An idea") -> str:
    res = client.post(
        "/ideation/ideas",
        headers=h,
        json={"productId": product_id, "problem": problem, "rawText": "ctx"},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


_FULL_ANSWERS = {
    "problem_statement": "CS cannot export orders.",
    "business_goal": "Reduce manual work.",
    "success_metric": "50% fewer support tickets.",
}


def _br(client, h, product_id, idea_ids=None) -> str:
    body = {"productId": product_id, "answers": _FULL_ANSWERS}
    if idea_ids:
        body["ideaIds"] = idea_ids
    res = client.post("/ideation/business-requirements", headers=h, json=body)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lapse_and_get(client, action_id: str, headers: dict) -> dict:
    """Back-date `commit_at` on the FACTORY's own db, then let `current` lazily
    commit it (mirrors every other deferred-action test in this suite)."""
    db = client._factory()
    from app.models.pending_action import PendingAction

    pa = db.get(PendingAction, action_id)
    pa.commit_at = _now() - timedelta(seconds=1)
    db.commit()
    db.close()


def _park(client, headers, action_key, entity_type, entity_id, payload=None) -> dict:
    body = {"actionKey": action_key, "entityType": entity_type, "entityId": entity_id}
    if payload is not None:
        body["payload"] = payload
    res = client.post("/api/v1/pending-actions", headers=headers, json=body)
    assert res.status_code == 202, res.text
    return res.json()


def _current(client, headers, entity_type, entity_id) -> dict:
    res = client.get(
        "/api/v1/pending-actions/current",
        headers=headers,
        params={"entityType": entity_type, "entityId": entity_id},
    )
    assert res.status_code == 200, res.text
    return res.json()


# ── registration ─────────────────────────────────────────────────────────


def test_all_six_ideation_keys_registered(ideation_session_factory):
    for key in (
        "ideation_ideas.archive",
        "ideation_ideas.delete",
        "ideation_business_requirements.delete",
        "ideation_business_requirements.unlink_idea",
        "ideation_embed_connections.delete",
        "ideation_embed_connections.set_active",
    ):
        assert deferred_action_for(key).key == key


# ── ideas ────────────────────────────────────────────────────────────────


def test_ideas_archive_park_and_lapse_commits(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    idea_id = _idea(ideation_client, h, pid)

    row = _park(ideation_client, h, "ideation_ideas.archive", "ideation_idea", idea_id)
    _lapse_and_get(ideation_client, row["id"], h)
    cur = _current(ideation_client, h, "ideation_idea", idea_id)
    assert cur["lastOutcome"]["status"] == "committed"

    detail = ideation_client.get(f"/ideation/ideas/{idea_id}", headers=h)
    assert detail.json()["status"] == "archived"


def test_ideas_delete_park_and_lapse_commits(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    idea_id = _idea(ideation_client, h, pid)

    row = _park(ideation_client, h, "ideation_ideas.delete", "ideation_idea", idea_id)
    _lapse_and_get(ideation_client, row["id"], h)
    cur = _current(ideation_client, h, "ideation_idea", idea_id)
    assert cur["lastOutcome"]["status"] == "committed"

    detail = ideation_client.get(f"/ideation/ideas/{idea_id}", headers=h)
    assert detail.status_code == 404


def test_ideas_archive_missing_target_404_at_park(ideation_client):
    h = _auth(ideation_client)
    res = ideation_client.post(
        "/api/v1/pending-actions",
        headers=h,
        json={"actionKey": "ideation_ideas.archive", "entityType": "ideation_idea", "entityId": "no-such-idea"},
    )
    assert res.status_code == 404


# ── business requirements ────────────────────────────────────────────────


def test_br_delete_park_and_lapse_commits(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = _br(ideation_client, h, pid)

    row = _park(ideation_client, h, "ideation_business_requirements.delete", "ideation_business_requirement", br_id)
    _lapse_and_get(ideation_client, row["id"], h)
    cur = _current(ideation_client, h, "ideation_business_requirement", br_id)
    assert cur["lastOutcome"]["status"] == "committed"

    detail = ideation_client.get(f"/ideation/business-requirements/{br_id}", headers=h)
    assert detail.status_code == 404


def test_br_unlink_idea_park_and_lapse_commits(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    idea_id = _idea(ideation_client, h, pid)
    br_id = _br(ideation_client, h, pid, idea_ids=[idea_id])

    link_key = f"{br_id}:{idea_id}"
    row = _park(
        ideation_client, h, "ideation_business_requirements.unlink_idea", "ideation_br_idea_link", link_key
    )
    _lapse_and_get(ideation_client, row["id"], h)
    cur = _current(ideation_client, h, "ideation_br_idea_link", link_key)
    assert cur["lastOutcome"]["status"] == "committed"

    ideas = ideation_client.get(f"/ideation/business-requirements/{br_id}/ideas", headers=h)
    assert ideas.json() == []


# ── embed connections ────────────────────────────────────────────────────


def test_embed_connection_delete_park_and_lapse_commits(ideation_client):
    from modules.ideation.services.embed import upsert_connection

    db = ideation_client._factory()
    upsert_connection(
        db,
        connection_id=CONNECTION_ID,
        tenant_id=DEFAULT_TENANT_ID,
        signing_secret=SIGNING_SECRET,
        allowed_origins=[ORIGIN],
        is_active=True,
    )
    db.close()

    h = _auth(ideation_client)
    row = _park(
        ideation_client, h, "ideation_embed_connections.delete", "ideation_embed_connection", CONNECTION_ID
    )
    _lapse_and_get(ideation_client, row["id"], h)
    cur = _current(ideation_client, h, "ideation_embed_connection", CONNECTION_ID)
    assert cur["lastOutcome"]["status"] == "committed"

    db2 = ideation_client._factory()
    from modules.ideation.services.embed import get_connection

    assert get_connection(db2, connection_id=CONNECTION_ID, tenant_id=DEFAULT_TENANT_ID) is None
    db2.close()


def test_embed_connection_set_active_toggles_via_payload(ideation_client):
    from modules.ideation.services.embed import get_connection, upsert_connection

    db = ideation_client._factory()
    upsert_connection(
        db,
        connection_id=CONNECTION_ID,
        tenant_id=DEFAULT_TENANT_ID,
        signing_secret=SIGNING_SECRET,
        allowed_origins=[ORIGIN],
        is_active=True,
    )
    db.close()

    h = _auth(ideation_client)
    row = _park(
        ideation_client,
        h,
        "ideation_embed_connections.set_active",
        "ideation_embed_connection",
        CONNECTION_ID,
        payload={"isActive": False},
    )
    _lapse_and_get(ideation_client, row["id"], h)
    cur = _current(ideation_client, h, "ideation_embed_connection", CONNECTION_ID)
    assert cur["lastOutcome"]["status"] == "committed"

    db2 = ideation_client._factory()
    conn = get_connection(db2, connection_id=CONNECTION_ID, tenant_id=DEFAULT_TENANT_ID)
    assert conn.is_active is False
    db2.close()
