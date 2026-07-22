"""Ideation — Business Requirement entity (Phase B-i slice 2, AC-BI-15..19).

Covers: BR create stamps the active template version + validates answers against
the STAMPED version (AC-BI-16); a template edit never reshapes an existing BR
(historical BRs render against their stamp); Idea↔BR many-many cardinality +
cross-tenant / cross-product refusal (AC-BI-17); lifecycle edges via the status
engine (AC-BI-15); permission gating incl. the separate ``.promote`` (AC-BI-19);
tenant scoping.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.sql import func

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from app.security import hash_password
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


def _make_user(factory, email, password, perm_keys):
    from app.models import Role, User, UserStatus
    from app.models.permission import Permission

    db = factory()
    try:
        perms = db.query(Permission).filter(Permission.key.in_(list(perm_keys))).all()
        role = Role(
            tenant_id=DEFAULT_TENANT_ID,
            name=f"Role-{email}",
            description="Test role",
            is_system=False,
        )
        role.permissions = perms
        db.add(role)
        db.flush()
        user = User(
            tenant_id=DEFAULT_TENANT_ID,
            email=email,
            password=hash_password(password),
            name="Test User",
            status=UserStatus.ACTIVE.value,
            email_verified_at=func.now(),
        )
        user.roles = [role]
        db.add(user)
        db.commit()
    finally:
        db.close()


# ── create + stamping (AC-BI-15/16) ──────────────────────────────────────────


def test_create_br_stamps_active_template_and_starts_draft(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    res = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "title": "Order export", "answers": _FULL_ANSWERS},
    )
    assert res.status_code == 201, res.text
    br = res.json()
    assert br["status"] == "draft"
    assert br["templateKey"] == "business_requirement"
    assert br["templateVersion"] == 1
    assert br["answers"]["problem_statement"] == "CS cannot export orders."
    # The detail carries the stamped template doc for the renderer.
    assert br["templateDoc"]["pages"], br
    assert br["productName"] == "Sorento CRM"


def test_create_br_validates_answers_against_stamped_version(ideation_client):
    """A missing required field (success_metric) 422s per-field, not 500."""
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    res = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={
            "productId": pid,
            "answers": {"problem_statement": "x", "business_goal": "y"},
        },
    )
    assert res.status_code == 422, res.text
    assert "success_metric" in res.json()["detail"]["fieldErrors"]


def test_historical_br_renders_against_its_stamped_version(
    ideation_client, ideation_session_factory
):
    """A template edit mints v2 + moves the active label, but a BR stamped at v1
    still renders against v1 (AC-BI-16)."""
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "answers": _FULL_ANSWERS},
    ).json()["id"]

    # Edit the platform template body → v2 with an EXTRA required field.
    db = ideation_session_factory()
    try:
        from modules.ideation.models import (
            IdeationArtifactTemplate,
            IdeationArtifactTemplateVersion,
        )
        from modules.ideation.services.br_templates import (
            BR_TEMPLATE_KEY,
            br_target_schema,
        )

        template = (
            db.query(IdeationArtifactTemplate)
            .filter(
                IdeationArtifactTemplate.template_key == BR_TEMPLATE_KEY,
                IdeationArtifactTemplate.tenant_id.is_(None),
            )
            .first()
        )
        doc = br_target_schema().model_dump(mode="json")
        doc["pages"][0]["sections"][0]["fields"].append(
            {
                "id": "f-extra",
                "type": "textarea",
                "key": "extra",
                "label": "Extra",
                "required": True,
            }
        )
        v2 = IdeationArtifactTemplateVersion(
            template_id=template.id, tenant_id=None, version=2, doc_json=doc
        )
        db.add(v2)
        db.flush()
        template.active_version_id = v2.id
        db.commit()
    finally:
        db.close()

    # The existing BR still stamps v1 and its doc has NO `extra` field.
    got = ideation_client.get(
        f"/ideation/business-requirements/{br_id}", headers=h
    ).json()
    assert got["templateVersion"] == 1
    keys = {
        f["key"]
        for f in got["templateDoc"]["pages"][0]["sections"][0]["fields"]
    }
    assert "extra" not in keys

    # A NEW BR stamps v2 (the active version).
    fresh = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={
            "productId": pid,
            "answers": {**_FULL_ANSWERS, "extra": "needed"},
        },
    ).json()
    assert fresh["templateVersion"] == 2


# ── Idea ↔ BR many-many (AC-BI-17) ────────────────────────────────────────────


def test_link_ideas_many_many_and_lineage(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    idea_a = _idea(ideation_client, h, pid, "idea A")
    idea_b = _idea(ideation_client, h, pid, "idea B")
    br1 = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "answers": _FULL_ANSWERS, "ideaIds": [idea_a]},
    ).json()
    br2 = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "answers": _FULL_ANSWERS},
    ).json()

    # A BR absorbs many ideas.
    res = ideation_client.post(
        f"/ideation/business-requirements/{br1['id']}/ideas",
        headers=h,
        json={"ideaIds": [idea_b]},
    )
    assert res.status_code == 200, res.text
    assert {i["id"] for i in res.json()} == {idea_a, idea_b}

    # An idea feeds several BRs.
    ideation_client.post(
        f"/ideation/business-requirements/{br2['id']}/ideas",
        headers=h,
        json={"ideaIds": [idea_a]},
    )
    lineage2 = ideation_client.get(
        f"/ideation/business-requirements/{br2['id']}/ideas", headers=h
    ).json()
    assert [i["id"] for i in lineage2] == [idea_a]

    # ideaCount surfaces on the list.
    rows = ideation_client.get(
        "/ideation/business-requirements", headers=h
    ).json()
    counts = {r["id"]: r["ideaCount"] for r in rows}
    assert counts[br1["id"]] == 2


def test_link_cross_product_idea_refused(ideation_client):
    h = _auth(ideation_client)
    pid1 = _product(ideation_client, h, "Product One")
    pid2 = _product(ideation_client, h, "Product Two")
    other_idea = _idea(ideation_client, h, pid2, "other product idea")
    br = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid1, "answers": _FULL_ANSWERS},
    ).json()
    res = ideation_client.post(
        f"/ideation/business-requirements/{br['id']}/ideas",
        headers=h,
        json={"ideaIds": [other_idea]},
    )
    assert res.status_code == 422, res.text


def test_link_unknown_idea_refused(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "answers": _FULL_ANSWERS},
    ).json()
    res = ideation_client.post(
        f"/ideation/business-requirements/{br['id']}/ideas",
        headers=h,
        json={"ideaIds": ["does-not-exist"]},
    )
    assert res.status_code == 422, res.text


# ── lifecycle via the status engine (AC-BI-15) ────────────────────────────────


def test_status_engine_lifecycle_edges(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "answers": _FULL_ANSWERS},
    ).json()
    bid = br["id"]

    # draft → grilling (defined edge).
    res = ideation_client.post(
        f"/ideation/business-requirements/{bid}/status",
        headers=h,
        json={"status": "grilling"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "grilling"

    # grilling → delivered is NOT a defined edge → 409.
    bad = ideation_client.post(
        f"/ideation/business-requirements/{bid}/status",
        headers=h,
        json={"status": "delivered"},
    )
    assert bad.status_code == 409, bad.text

    # An unknown status key → 422.
    unknown = ideation_client.post(
        f"/ideation/business-requirements/{bid}/status",
        headers=h,
        json={"status": "nope"},
    )
    assert unknown.status_code == 422, unknown.text


def test_promote_edge_seam_exists(ideation_client, ideation_session_factory):
    """The draft → ready promote edge (S4 gate seam) is seeded (AC-BI-19)."""
    db = ideation_session_factory()
    try:
        from app.models.status_transition import StatusTransition
        from modules.ideation.services.statuses import BR_ENTITY

        edge = (
            db.query(StatusTransition)
            .filter(
                StatusTransition.entity_type == BR_ENTITY,
                StatusTransition.id == "br-tr-promote",
            )
            .first()
        )
        assert edge is not None
        assert edge.from_status_id == "br-status-draft"
        assert edge.to_status_id == "br-status-ready"
    finally:
        db.close()


# ── versions tab (AC-BI-16) ───────────────────────────────────────────────────


def test_versions_tab_flags_stamped(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "answers": _FULL_ANSWERS},
    ).json()
    res = ideation_client.get(
        f"/ideation/business-requirements/{br['id']}/versions", headers=h
    )
    assert res.status_code == 200, res.text
    versions = res.json()
    assert any(v["version"] == 1 and v["isStamped"] for v in versions)


# ── permission gating (AC-BI-19) ──────────────────────────────────────────────


def test_read_only_user_cannot_manage(ideation_client, ideation_session_factory):
    """A user with .read but not .manage/.promote can read but not create."""
    _make_user(
        ideation_session_factory,
        "brreader@example.com",
        "Reader123!",
        {"ideation.business_requirements.read"},
    )
    h_admin = _auth(ideation_client)
    pid = _product(ideation_client, h_admin)

    h = _auth(ideation_client, email="brreader@example.com", password="Reader123!")
    # read OK
    assert (
        ideation_client.get("/ideation/business-requirements", headers=h).status_code
        == 200
    )
    # create refused (no .manage)
    res = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "answers": _FULL_ANSWERS},
    )
    assert res.status_code == 403, res.text


def test_manage_grants_imply_read(ideation_client):
    """The seeded Admin holds .read/.manage/.promote (grant reaches it)."""
    h = _auth(ideation_client)
    res = ideation_client.get("/auth/me", headers=h)
    perms = set(res.json()["permissions"])
    assert "ideation.business_requirements.read" in perms
    assert "ideation.business_requirements.manage" in perms
    assert "ideation.business_requirements.promote" in perms


# ── tenant scoping ────────────────────────────────────────────────────────────


def test_get_unknown_br_404(ideation_client):
    h = _auth(ideation_client)
    res = ideation_client.get(
        "/ideation/business-requirements/nope", headers=h
    )
    assert res.status_code == 404, res.text
