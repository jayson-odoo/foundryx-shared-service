"""Ideation - BR coverage hardening (added by TESTER QA of Phase B-i slice 2).

These tests close gaps the primary ``test_ideation_br.py`` left open, keyed to
AC-BI-15..19:

- **AC-BI-16 (validate against STAMPED, not active):** editing a template to a v2
  with a NEW required field must NOT retroactively invalidate a historical BR -
  the v1 BR still saves with its v1 answer set (no ``extra``).
- **AC-BI-17 (cross-TENANT refusal):** a valid Idea row owned by ANOTHER tenant
  can never be linked (tenant-scoped resolve on read = the polymorphic-target
  rule), even when it shares the product id.
- **AC-BI-19 (read vs manage boundary):** a ``.read``-only user is refused 403 on
  every mutating route (status move, link).
- **AC-BI-19 (promote-gate DEFERRAL, documented):** the ``.promote`` permission is
  declared + granted but NOT yet enforced - a ``.manage`` user can currently fire
  the ``draft → ready`` promote edge through ``POST /status``. This test PINS the
  current S2 behaviour so the S4 promote-gate work is provably the thing that
  closes it. See the QA report for the honest assessment.
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


def _bump_template_to_v2(factory) -> None:
    """Edit the platform BR template → v2 with an EXTRA required field, moving the
    active label. Mirrors the primary suite's helper."""
    db = factory()
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


# ── AC-BI-16 - UPDATE validates against the STAMPED version, not the active ────


def test_update_historical_br_validates_against_stamped_version(
    ideation_client, ideation_session_factory
):
    """A v1 BR is still editable WITHOUT the field v2 later made required - the
    write path resolves the STAMPED (v1) doc, never the active (v2) one."""
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br_id = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "answers": _FULL_ANSWERS},
    ).json()["id"]

    _bump_template_to_v2(ideation_session_factory)

    # Edit the v1 BR with only v1 fields - must SUCCEED (v1 has no `extra`), even
    # though the ACTIVE template (v2) would require `extra`.
    res = ideation_client.patch(
        f"/ideation/business-requirements/{br_id}",
        headers=h,
        json={
            "answers": {
                **_FULL_ANSWERS,
                "business_goal": "Reduce manual work even more.",
            }
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["templateVersion"] == 1
    assert body["answers"]["business_goal"] == "Reduce manual work even more."
    # The v1 field set has no `extra`, so it is never stored.
    assert "extra" not in body["answers"]


# ── AC-BI-17 - cross-TENANT idea link refused ────────────────────────────────


def test_link_cross_tenant_idea_refused(ideation_client, ideation_session_factory):
    """An Idea owned by another tenant - even with the SAME product id - is
    refused (tenant-scoped resolve on read; the polymorphic-target rule)."""
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "answers": _FULL_ANSWERS},
    ).json()

    # Plant an Idea directly under a DIFFERENT tenant, sharing the BR's product.
    db = ideation_session_factory()
    try:
        from modules.ideation.models import Idea
        from modules.ideation.services.statuses import initial_idea_status_id

        foreign = Idea(
            id="foreign-idea-1",
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
        f"/ideation/business-requirements/{br['id']}/ideas",
        headers=h,
        json={"ideaIds": ["foreign-idea-1"]},
    )
    assert res.status_code == 422, res.text
    # And nothing got linked.
    lineage = ideation_client.get(
        f"/ideation/business-requirements/{br['id']}/ideas", headers=h
    ).json()
    assert lineage == []


# ── AC-BI-19 - read-only user refused on every mutating route ─────────────────


def test_read_only_user_refused_on_status_and_link(
    ideation_client, ideation_session_factory
):
    h_admin = _auth(ideation_client)
    pid = _product(ideation_client, h_admin)
    br = ideation_client.post(
        "/ideation/business-requirements",
        headers=h_admin,
        json={"productId": pid, "answers": _FULL_ANSWERS},
    ).json()

    _make_user(
        ideation_session_factory,
        "brreader2@example.com",
        "Reader123!",
        {"ideation.business_requirements.read"},
    )
    h = _auth(ideation_client, email="brreader2@example.com", password="Reader123!")

    # status move → 403 (manage-gated)
    assert (
        ideation_client.post(
            f"/ideation/business-requirements/{br['id']}/status",
            headers=h,
            json={"status": "grilling"},
        ).status_code
        == 403
    )
    # link ideas → 403 (manage-gated)
    assert (
        ideation_client.post(
            f"/ideation/business-requirements/{br['id']}/ideas",
            headers=h,
            json={"ideaIds": []},
        ).status_code
        == 403
    )
    # patch → 403 (manage-gated)
    assert (
        ideation_client.patch(
            f"/ideation/business-requirements/{br['id']}",
            headers=h,
            json={"title": "nope"},
        ).status_code
        == 403
    )


# ── AC-BI-19 - promote gate ENFORCED (closed in S2) ──────────────────────────


def test_manage_without_promote_refused_on_promote_edge(
    ideation_client, ideation_session_factory
):
    """AC-BI-19/34: firing the ``br-tr-promote`` (draft → ready) edge requires the
    SEPARATE ``.promote`` permission. A ``.manage``-without-``.promote`` actor is
    refused 403 on that edge - but every OTHER BR edge stays gated by ``.manage``
    (draft → grilling succeeds for the same actor)."""
    h_admin = _auth(ideation_client)
    pid = _product(ideation_client, h_admin)

    # A user with read+manage but NOT promote.
    _make_user(
        ideation_session_factory,
        "brmanager@example.com",
        "Manager123!",
        {
            "ideation.business_requirements.read",
            "ideation.business_requirements.manage",
        },
    )
    h = _auth(ideation_client, email="brmanager@example.com", password="Manager123!")

    br = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "answers": _FULL_ANSWERS},
    ).json()

    # draft → ready (the promote edge) is REFUSED without .promote.
    denied = ideation_client.post(
        f"/ideation/business-requirements/{br['id']}/status",
        headers=h,
        json={"status": "ready"},
    )
    assert denied.status_code == 403, denied.text

    # draft → grilling (a non-promote edge) SUCCEEDS under .manage.
    ok = ideation_client.post(
        f"/ideation/business-requirements/{br['id']}/status",
        headers=h,
        json={"status": "grilling"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "grilling"


def test_promote_holder_can_fire_promote_edge(ideation_client):
    """A holder of ``.promote`` (the seeded Admin holds read+manage+promote)
    successfully fires draft → ready."""
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    br = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "answers": _FULL_ANSWERS},
    ).json()

    res = ideation_client.post(
        f"/ideation/business-requirements/{br['id']}/status",
        headers=h,
        json={"status": "ready"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ready"
