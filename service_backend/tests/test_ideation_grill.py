"""Ideation — generic grill engine (Phase B-i slice 3, AC-BI-20..29 + 20b/24b).

Two layers, both OFFLINE via the deterministic stub (AC-BI-12) — zero key, zero
network:

- **Engine-level** (a synthetic ``GrillDefinition``): the turn's ONE structured
  call → ``{replyText, coveredFields}`` (AC-BI-24b), partial emit is success
  (AC-BI-26), validation-failure → one retry → surfaced (AC-BI-25), and a failed
  completion STILL writes an ``error`` trace after the engine commits (decision 1
  / AC-BI-24b).
- **Route-level** (``ideation_client``): the turn/generate endpoints, extraction
  persists ``answers_json`` with the BR left DRAFT (never auto-promotes,
  AC-BI-27), tenant scoping, and the auto-seeded agent + skill (AC-BI-20b/28).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.sql import func

from app.ai import GrillContext, GrillDefinition, GrillEngine, GrillError
from app.ai.grill import (
    _REGISTRY,
    register_grill_definition,
    set_definition_target_type,
)
from app.ai.stub import StubResponse, stub_fixtures
from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from app.models.ai import (
    ROLE_ASSISTANT,
    ROLE_USER,
    SPAN_KIND_RETRY,
    SPAN_KIND_VALIDATE,
    TRACE_STATUS_ERROR,
    AiAgent,
    AiConversation,
    AiMessage,
    AiTrace,
)
from app.models.connection import Connection
from app.secrets import encrypt_secret
from app.security import hash_password
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


# ── shared fixtures / helpers ─────────────────────────────────────────────────


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


def _make_llm_connection(db, *, tenant_id=DEFAULT_TENANT_ID):
    """A dev-cred LLM connection: readiness passes (a connection exists) and the
    stub answers (AC-BI-12) — no key, no network."""
    conn = Connection(
        tenant_id=tenant_id,
        provider="gemini",
        type="llm",
        name="gemini key",
        config_json={},
        credentials_json=encrypt_secret({"apiKey": "x", "dev": True}),
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _grill_agent(db, tenant_id=DEFAULT_TENANT_ID):
    return (
        db.query(AiAgent)
        .filter(AiAgent.tenant_id == tenant_id, AiAgent.name == "Ideation grill")
        .first()
    )


# ── engine-level: a synthetic definition over a controllable doc ──────────────

_TEST_DEF_KEY = "test_grill"
_TEST_TARGET = "test_grill_target"

# A doc with a REQUIRED textarea + a SELECT with a fixed option set. The select
# lets us script a choice-membership failure (textareas never fail on format),
# so the retry path is deterministically exercised.
_TEST_DOC = {
    "schemaVersion": 1,
    "pages": [
        {
            "id": "p",
            "title": "P",
            "sections": [
                {
                    "id": "s",
                    "title": "S",
                    "fields": [
                        {
                            "id": "f1",
                            "type": "textarea",
                            "key": "summary",
                            "label": "Summary",
                            "required": True,
                        },
                        {
                            "id": "f2",
                            "type": "select",
                            "key": "priority",
                            "label": "Priority",
                            "required": False,
                            "options": {
                                "items": [
                                    {"value": "low", "label": "Low"},
                                    {"value": "high", "label": "High"},
                                ]
                            },
                        },
                    ],
                }
            ],
        }
    ],
}

_TEST_FIELDS = [
    {"key": "summary", "label": "Summary"},
    {"key": "priority", "label": "Priority"},
]


@pytest.fixture
def engine_fixture(ideation_session_factory):
    """A synthetic grill definition + the auto-seeded agent + a dev connection,
    with a captured ``persist`` sink. Returns (db, definition, sink)."""
    db = ideation_session_factory()
    _make_llm_connection(db)
    agent = _grill_agent(db)
    assert agent is not None, "install_tenant should auto-seed the Ideation grill agent"
    # Heal the connectionless seeded agent onto the dev connection (mirrors the
    # lazy heal in the real resolver).
    conn = db.query(Connection).filter(Connection.type == "llm").first()
    agent.connection_id = conn.id
    db.commit()

    sink: dict = {}

    def resolve(_db, tenant_id, target_id):
        return GrillContext(
            tenant_id=tenant_id,
            target_id=target_id,
            target_fields=list(_TEST_FIELDS),
            target_doc=_TEST_DOC,
            source_artifacts=["Problem: exports are slow"],
            source_type="idea",
            source_ids=["idea-1"],
            template_version=1,
            agent=agent,
            skill_body="Grill about {{ target_fields }} using {{ source_artifacts }}.",
            skill_key="grill-me-business",
            prompt_version=1,
        )

    def persist(_db, tenant_id, target_id, answers, actor):
        sink["answers"] = answers
        sink["target_id"] = target_id

    definition = GrillDefinition(
        key=_TEST_DEF_KEY,
        source_type="idea",
        skill_key="grill-me-business",
        resolve_context=resolve,
        persist_answers=persist,
    )
    set_definition_target_type(_TEST_DEF_KEY, _TEST_TARGET)
    register_grill_definition(definition)
    try:
        yield db, definition, sink
    finally:
        _REGISTRY.pop(_TEST_DEF_KEY, None)
        db.close()


def _demo_user(db):
    from app.models.user import User

    return db.query(User).filter(User.email == ACTIVE_EMAIL).first()


def test_turn_returns_reply_and_covered_fields(engine_fixture):
    """The turn is ONE structured call → {replyText, coveredFields} (AC-BI-24b);
    an invalid key in coveredFields is filtered to the valid set (AC-BI-22)."""
    db, definition, _ = engine_fixture
    actor = _demo_user(db)
    with stub_fixtures(
        StubResponse(structured={"replyText": "What is the success metric?", "coveredFields": ["summary", "bogus"]})
    ):
        result = GrillEngine(db).turn(definition, DEFAULT_TENANT_ID, "br-x", "It is about exports.", actor)
    assert result.reply_text == "What is the success metric?"
    assert result.covered_fields == ["summary"]  # 'bogus' filtered out

    # The transcript persisted BOTH turns (AC-BI-21) under one conversation.
    convo = (
        db.query(AiConversation)
        .filter(AiConversation.target_id == "br-x")
        .first()
    )
    assert convo is not None
    assert convo.prompt_version == 1 and convo.template_version == 1
    msgs = (
        db.query(AiMessage)
        .filter(AiMessage.conversation_id == convo.id)
        .order_by(AiMessage.created_at.asc())
        .all()
    )
    assert [m.role for m in msgs] == [ROLE_USER, ROLE_ASSISTANT]
    assert msgs[1].covered_fields_json == ["summary"]


def test_generate_persists_answers_via_the_definition(engine_fixture):
    """Generate extracts → validates → persists through the definition's sink."""
    db, definition, sink = engine_fixture
    actor = _demo_user(db)
    with stub_fixtures(
        StubResponse(structured={"summary": "Export orders faster.", "priority": "high"})
    ):
        result = GrillEngine(db).generate(definition, DEFAULT_TENANT_ID, "br-x", actor)
    assert result.ok is True
    assert sink["answers"] == {"summary": "Export orders faster.", "priority": "high"}


def test_partial_extraction_leaves_missing_required_blank_no_422(engine_fixture):
    """A partial extraction (summary REQUIRED but omitted) is SUCCESS — the field
    is left blank, nothing 422s (AC-BI-26/24b)."""
    db, definition, sink = engine_fixture
    actor = _demo_user(db)
    with stub_fixtures(StubResponse(structured={"priority": "low"})):
        result = GrillEngine(db).generate(definition, DEFAULT_TENANT_ID, "br-x", actor)
    assert result.ok is True
    assert result.field_errors == {}
    assert sink["answers"] == {"priority": "low"}
    assert "summary" not in sink["answers"]  # left blank, never invented


def test_validation_failure_triggers_one_retry_then_succeeds(engine_fixture):
    """An invalid choice fails validation → exactly one retry with the errors fed
    back → the valid retry persists; validate + retry land as spans (AC-BI-25)."""
    db, definition, sink = engine_fixture
    actor = _demo_user(db)
    with stub_fixtures(
        StubResponse(structured={"summary": "ok", "priority": "not-a-choice"}),
        StubResponse(structured={"summary": "ok", "priority": "high"}),
    ):
        result = GrillEngine(db).generate(definition, DEFAULT_TENANT_ID, "br-x", actor)
    assert result.ok is True
    assert sink["answers"]["priority"] == "high"

    from app.models.ai import AiSpan

    kinds = {s.span_kind for s in db.query(AiSpan).all()}
    assert SPAN_KIND_VALIDATE in kinds
    assert SPAN_KIND_RETRY in kinds


def test_validation_failure_twice_surfaces_field_errors(engine_fixture):
    """Both attempts invalid → surfaced to the human (never an infinite loop),
    the sink is never written (AC-BI-25)."""
    db, definition, sink = engine_fixture
    actor = _demo_user(db)
    with stub_fixtures(
        StubResponse(structured={"summary": "ok", "priority": "bad1"}),
        StubResponse(structured={"summary": "ok", "priority": "bad2"}),
    ):
        result = GrillEngine(db).generate(definition, DEFAULT_TENANT_ID, "br-x", actor)
    assert result.ok is False
    assert "priority" in result.field_errors
    assert "answers" not in sink  # nothing persisted


def test_failed_completion_still_writes_an_error_trace(engine_fixture):
    """Decision 1 / AC-BI-24b: an LLMError commits the flushed trace inside the
    except, then surfaces GrillError — the error trace MUST survive."""
    db, definition, _ = engine_fixture
    with stub_fixtures(StubResponse(error="provider exploded")):
        with pytest.raises(GrillError):
            GrillEngine(db).turn(definition, DEFAULT_TENANT_ID, "br-x", "hello", _demo_user(db))
    # The committed error trace survives the raised GrillError (decision 1).
    trace = db.query(AiTrace).filter(AiTrace.status == TRACE_STATUS_ERROR).first()
    assert trace is not None
    assert "provider exploded" in (trace.error or "")


# ── route-level: the real Idea→BR grill through the ideation API ──────────────


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


def _seed_connection(client):
    db = client._factory()
    try:
        _make_llm_connection(db)
    finally:
        db.close()


def test_grill_state_reports_ready_and_target_fields(ideation_client):
    _seed_connection(ideation_client)
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = _draft_br(ideation_client, h, pid)
    res = ideation_client.get(f"/ideation/business-requirements/{br_id}/grill", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ready"] is True
    keys = {f["key"] for f in body["fields"]}
    assert {"problem_statement", "business_goal", "success_metric"} <= keys
    assert body["messages"] == []


def test_grill_state_warns_when_no_connection(ideation_client):
    """No LLM connection anywhere → the prerequisite warning, grill unavailable
    (AC-BI-11)."""
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = _draft_br(ideation_client, h, pid)
    res = ideation_client.get(f"/ideation/business-requirements/{br_id}/grill", headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["ready"] is False
    assert res.json()["warning"]


# The stub queue is thread-local; Starlette's TestClient runs the endpoint on a
# DIFFERENT thread, so stub-scripted turns/extractions are driven against the
# REAL registered ``idea_to_br`` definition on a same-thread factory session
# (the route's HTTP wiring — readiness/scoping/perms — is covered above). This is
# the real ideation resolver + persist path, only the transport layer differs.


def _real_service(client):
    from modules.ideation.services.grill import IdeationGrillService

    return IdeationGrillService(client._factory())


def _real_definition():
    from modules.ideation.services.grill import GRILL_DEFINITION_KEY

    from app.ai import get_grill_definition

    definition = get_grill_definition(GRILL_DEFINITION_KEY)
    assert definition is not None, "idea_to_br grill definition should be boot-registered"
    return definition


def _demo(db):
    from app.models.user import User

    return db.query(User).filter(User.email == ACTIVE_EMAIL).first()


def test_turn_endpoint_persists_and_returns_coverage(ideation_client):
    _seed_connection(ideation_client)
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = _draft_br(ideation_client, h, pid)

    db = ideation_client._factory()
    try:
        engine = GrillEngine(db)
        with stub_fixtures(
            StubResponse(
                structured={
                    "replyText": "Who are the stakeholders?",
                    "coveredFields": ["problem_statement"],
                }
            )
        ):
            result = engine.turn(_real_definition(), DEFAULT_TENANT_ID, br_id, "CS cannot export.", _demo(db))
        assert result.reply_text == "Who are the stakeholders?"
        assert result.covered_fields == ["problem_statement"]
    finally:
        db.close()

    # It shows up on the transcript read through the real HTTP route.
    state = ideation_client.get(
        f"/ideation/business-requirements/{br_id}/grill", headers=h
    ).json()
    assert [m["role"] for m in state["messages"]] == ["user", "assistant"]
    assert state["coveredFields"] == ["problem_statement"]


def test_generate_persists_answers_and_br_stays_draft(ideation_client):
    """Generate writes answers_json but NEVER promotes — the BR stays draft
    (AC-BI-27). No non-human path reaches ready."""
    _seed_connection(ideation_client)
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = _draft_br(ideation_client, h, pid)

    db = ideation_client._factory()
    try:
        service = __import__(
            "modules.ideation.services.grill", fromlist=["IdeationGrillService"]
        ).IdeationGrillService(db)
        with stub_fixtures(
            StubResponse(
                structured={
                    "problem_statement": "CS cannot export orders.",
                    "business_goal": "Cut manual work.",
                    "success_metric": "50% fewer tickets.",
                }
            )
        ):
            out = service.generate(DEFAULT_TENANT_ID, br_id, actor=_demo(db))
        assert out.status == "ok"
        assert out.br.status == "draft"  # NEVER auto-promoted
        assert out.br.answers["problem_statement"] == "CS cannot export orders."
    finally:
        db.close()

    # Re-fetch through HTTP confirms persistence + still draft.
    got = ideation_client.get(
        f"/ideation/business-requirements/{br_id}", headers=h
    ).json()
    assert got["status"] == "draft"
    assert got["answers"]["business_goal"] == "Cut manual work."


def test_generate_partial_extraction_persists_and_stays_draft(ideation_client):
    """A partial extraction (missing success_metric) persists the grounded fields,
    leaves the rest blank, and succeeds — no 422 (AC-BI-26)."""
    _seed_connection(ideation_client)
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = _draft_br(ideation_client, h, pid)

    db = ideation_client._factory()
    try:
        service = __import__(
            "modules.ideation.services.grill", fromlist=["IdeationGrillService"]
        ).IdeationGrillService(db)
        with stub_fixtures(
            StubResponse(structured={"problem_statement": "Exports break.", "business_goal": "Fix it."})
        ):
            out = service.generate(DEFAULT_TENANT_ID, br_id, actor=_demo(db))
        assert out.status == "ok"
        assert out.br.answers.get("problem_statement") == "Exports break."
        assert "success_metric" not in out.br.answers  # left blank, never invented
        assert out.br.status == "draft"
    finally:
        db.close()


def test_turn_error_surfaces_502_and_writes_error_trace(ideation_client):
    """A provider failure → the service maps GrillError to 502; the error trace is
    committed first (decision 1)."""
    from fastapi import HTTPException

    _seed_connection(ideation_client)
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = _draft_br(ideation_client, h, pid)

    db = ideation_client._factory()
    try:
        service = __import__(
            "modules.ideation.services.grill", fromlist=["IdeationGrillService"]
        ).IdeationGrillService(db)
        with stub_fixtures(StubResponse(error="provider down")):
            with pytest.raises(HTTPException) as exc:
                service.turn(DEFAULT_TENANT_ID, br_id, "hi", actor=_demo(db))
        assert exc.value.status_code == 502
    finally:
        db.close()

    db2 = ideation_client._factory()
    try:
        trace = db2.query(AiTrace).filter(AiTrace.status == TRACE_STATUS_ERROR).first()
        assert trace is not None
        assert "provider down" in (trace.error or "")
    finally:
        db2.close()


def test_grill_is_tenant_scoped(ideation_client):
    """A BR from another tenant is invisible to the grill (404)."""
    _seed_connection(ideation_client)
    h = _auth(ideation_client)
    res = ideation_client.get(
        "/ideation/business-requirements/not-my-br/grill", headers=h
    )
    assert res.status_code == 404, res.text


def test_grill_agent_binds_by_key_not_name(ideation_client, ideation_session_factory):
    """AC-BI-20b / DoD #3: the grill resolves its agent by the STABLE key, so a
    tenant renaming the auto-seeded 'Ideation grill' agent does NOT degrade the
    Grill tab to the no-agent warning."""
    _seed_connection(ideation_client)
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = _draft_br(ideation_client, h, pid)

    # Rename the seeded agent (the display name is freely editable).
    db = ideation_session_factory()
    try:
        agent = _grill_agent(db)
        assert agent is not None
        assert agent.key == "ideation-grill" and agent.is_system is True
        agent.name = "My Custom Grill Bot"
        db.commit()
    finally:
        db.close()

    # The grill still resolves it by key → ready, not the no-agent warning.
    res = ideation_client.get(
        f"/ideation/business-requirements/{br_id}/grill", headers=h
    )
    assert res.status_code == 200, res.text
    assert res.json()["ready"] is True


def test_system_grill_agent_cannot_be_deleted(ideation_client, ideation_session_factory):
    """A system-seeded agent is delete-locked (mirrors AiSkill.is_system)."""
    from fastapi import HTTPException

    from app.services.ai_service import AgentService

    _seed_connection(ideation_client)
    _auth(ideation_client)  # ensures the tenant + agent are seeded

    db = ideation_session_factory()
    try:
        agent = _grill_agent(db)
        assert agent is not None and agent.is_system is True
        with pytest.raises(HTTPException) as exc:
            AgentService(db).delete(DEFAULT_TENANT_ID, agent.id)
        assert exc.value.status_code == 409
    finally:
        db.close()


def test_manage_permission_required_for_turn(ideation_client, ideation_session_factory):
    """A read-only user cannot run a turn (gated .manage, AC-BI-19)."""
    _seed_connection(ideation_client)
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = _draft_br(ideation_client, h, pid)

    # A user holding only .read.
    from app.models import Role, User, UserStatus
    from app.models.permission import Permission

    db = ideation_session_factory()
    try:
        perms = (
            db.query(Permission)
            .filter(Permission.key == "ideation.business_requirements.read")
            .all()
        )
        role = Role(tenant_id=DEFAULT_TENANT_ID, name="ReadOnly", description="", is_system=False)
        role.permissions = perms
        db.add(role)
        db.flush()
        user = User(
            tenant_id=DEFAULT_TENANT_ID,
            email="readonly-grill@example.com",
            password=hash_password("Passw0rd!23"),
            name="RO",
            status=UserStatus.ACTIVE.value,
            email_verified_at=func.now(),
        )
        user.roles = [role]
        db.add(user)
        db.commit()
    finally:
        db.close()

    h2 = _auth(ideation_client, email="readonly-grill@example.com", password="Passw0rd!23")
    res = ideation_client.post(
        f"/ideation/business-requirements/{br_id}/grill/turn",
        headers=h2,
        json={"message": "x"},
    )
    assert res.status_code == 403, res.text
