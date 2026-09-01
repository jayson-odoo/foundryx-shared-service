"""Grill - FULL HTTP-path coverage (QA addition, Phase B-i slice 3).

The routine grill suite (``test_ideation_grill.py``) drives stub-scripted
turn/generate/error paths against the SERVICE on a same-thread factory session,
because the stub's fixture queue is thread-local and Starlette's ``TestClient``
runs the endpoint on a DIFFERENT thread. That leaves the REAL request lifecycle
- routing → ``require_permission`` → the service → ``get_db`` teardown - untested
for the scripted paths.

These tests close that gap by monkeypatching the PROCESS-GLOBAL ``stub_provider``
singleton (shared across threads, unlike the thread-local queue), so the full
HTTP stack runs end to end while the "model" output stays deterministic:

- **AC-BI-24b / decision 1** - a failed completion leaves an ``error`` trace even
  after ``get_db`` would roll the request back (the engine commits inside the
  ``except``). Only a real request exercises that teardown; the service-level test
  never does.
- **AC-BI-23** - a turn is synchronous: it creates NO ``background_jobs`` row.
- **AC-BI-26 / AC-BI-27** - a partial extraction persists the grounded fields
  through the real ``/generate`` endpoint and the BR stays ``draft``.
"""
import pytest
from fastapi.testclient import TestClient

from app.ai.stub import stub_provider
from app.database import get_db
from app.integrations.base import LLMError, LLMResult
from app.main import app
from app.models import DEFAULT_TENANT_ID
from app.models.ai import TRACE_STATUS_ERROR, AiTrace
from app.models.background_job import BackgroundJob
from app.models.connection import Connection
from app.secrets import encrypt_secret
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


def _seed_connection(client):
    db = client._factory()
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


def _product(client, h, name="Sorento CRM") -> str:
    res = client.post("/products", headers=h, json={"name": name, "kind": "software"})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _draft_br(client, h, pid) -> str:
    res = client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "title": "Order export"},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _patch_complete(monkeypatch, fn):
    """Replace the process-global stub's ``complete`` so the swap is visible on the
    TestClient's request thread (the thread-local fixture queue is not)."""
    monkeypatch.setattr(stub_provider, "complete", fn)


# ── AC-BI-24b / decision 1: error trace survives get_db teardown ──────────────


def test_http_turn_provider_error_writes_error_trace_and_502(ideation_client, monkeypatch):
    """A provider failure through the REAL request: the endpoint returns 502 and
    the committed ``error`` trace survives ``get_db``'s exception-teardown rollback
    (decision 1 / AC-BI-24b). This is the path the service-level test can't reach -
    it uses a direct session with no ``get_db`` teardown."""
    _seed_connection(ideation_client)
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = _draft_br(ideation_client, h, pid)

    def boom(*args, **kwargs):
        raise LLMError("http provider exploded")

    _patch_complete(monkeypatch, boom)
    res = ideation_client.post(
        f"/ideation/business-requirements/{br_id}/grill/turn",
        headers=h,
        json={"message": "CS cannot export orders."},
    )
    assert res.status_code == 502, res.text

    # The error trace was committed inside the engine's except and is NOT rolled
    # back by the request teardown.
    db = ideation_client._factory()
    try:
        trace = (
            db.query(AiTrace).filter(AiTrace.status == TRACE_STATUS_ERROR).first()
        )
        assert trace is not None, "a failed completion must leave an error trace (AC-BI-09)"
        assert "http provider exploded" in (trace.error or "")
    finally:
        db.close()


def test_http_turn_error_writes_no_transcript(ideation_client, monkeypatch):
    """A provider failure leaves NO half-written turn (AC-BI-23): the user message
    is not persisted without a reply."""
    _seed_connection(ideation_client)
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = _draft_br(ideation_client, h, pid)

    def boom(*args, **kwargs):
        raise LLMError("down")

    _patch_complete(monkeypatch, boom)
    ideation_client.post(
        f"/ideation/business-requirements/{br_id}/grill/turn",
        headers=h,
        json={"message": "orphan message"},
    )
    state = ideation_client.get(
        f"/ideation/business-requirements/{br_id}/grill", headers=h
    ).json()
    assert state["messages"] == [], "no half-written turn after a provider failure"


# ── AC-BI-23: a turn is synchronous - no background_jobs row ───────────────────


def test_http_turn_is_synchronous_no_background_job(ideation_client, monkeypatch):
    """A grill turn is request/response, never a batch job - it must not create a
    ``background_jobs`` row (AC-BI-23)."""
    _seed_connection(ideation_client)
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = _draft_br(ideation_client, h, pid)

    def reply(*args, **kwargs):
        return LLMResult(
            structured={"replyText": "Who are the stakeholders?", "coveredFields": ["problem_statement"]},
            tokens_in=5,
            tokens_out=3,
            model="stub-model-1",
            finish_reason="stop",
        )

    _patch_complete(monkeypatch, reply)

    db = ideation_client._factory()
    try:
        before = db.query(BackgroundJob).count()
    finally:
        db.close()

    res = ideation_client.post(
        f"/ideation/business-requirements/{br_id}/grill/turn",
        headers=h,
        json={"message": "CS cannot export orders."},
    )
    assert res.status_code == 200, res.text
    assert res.json()["replyText"] == "Who are the stakeholders?"
    assert res.json()["coveredFields"] == ["problem_statement"]

    db = ideation_client._factory()
    try:
        after = db.query(BackgroundJob).count()
    finally:
        db.close()
    assert after == before, "a synchronous turn must not enqueue a background job"


# ── AC-BI-26 / AC-BI-27: full-stack generate - partial persists, stays draft ──


def test_http_generate_partial_persists_and_br_stays_draft(ideation_client, monkeypatch):
    """The REAL ``/generate`` endpoint: a partial extraction (``success_metric``
    ungrounded) persists the grounded fields, leaves the rest blank (never
    invented, AC-BI-26), succeeds (no 422), and the BR stays ``draft`` - no
    non-human path promotes it (AC-BI-27)."""
    _seed_connection(ideation_client)
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = _draft_br(ideation_client, h, pid)

    def extract(*args, **kwargs):
        return LLMResult(
            structured={
                "problem_statement": "CS cannot export orders in bulk.",
                "business_goal": "Cut manual export effort.",
            },
            tokens_in=9,
            tokens_out=6,
            model="stub-model-1",
            finish_reason="stop",
        )

    _patch_complete(monkeypatch, extract)
    res = ideation_client.post(
        f"/ideation/business-requirements/{br_id}/grill/generate", headers=h
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ok"
    assert body["answers"]["problem_statement"] == "CS cannot export orders in bulk."
    assert "success_metric" not in body["answers"]  # left blank, never fabricated

    # Re-fetch through HTTP: answers persisted, BR still draft (never auto-promoted).
    got = ideation_client.get(
        f"/ideation/business-requirements/{br_id}", headers=h
    ).json()
    assert got["status"] == "draft"
    assert got["answers"]["business_goal"] == "Cut manual export effort."
    assert "success_metric" not in got["answers"]


def test_http_generate_warns_when_no_connection(ideation_client):
    """With no LLM connection anywhere, ``/generate`` is unavailable (409 with the
    prerequisite warning) - never a silent runtime failure (AC-BI-11)."""
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = _draft_br(ideation_client, h, pid)
    res = ideation_client.post(
        f"/ideation/business-requirements/{br_id}/grill/generate", headers=h
    )
    assert res.status_code == 409, res.text
