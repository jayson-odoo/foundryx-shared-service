"""Issue #90 W2 - the BR template seed survives a late migration.

Reproduces the issue #89 failure SHAPE (a database that reached
``bootstrap_modules`` -> ``install`` -> ``seed_br_template`` flushed-then-
rolled-back once, then got migrated to head separately) as a set of STATES a
sqlite ``create_all`` test engine CAN replay - the actual Alembic-lock-timeout
ordering bug is #89's own lane (``fix/deploy-abort-on-module-migration-
failure``); this file never imports ``app.module_loader.bootstrap_modules``,
so that reorder/abort fix cannot change these results either way.

``seed_br_template`` is made "ensure" semantics (AC-90-201..204): it must
repair a half-seeded state on every future bootstrap, idempotently, and NEVER
move a valid operator-set active pointer. AC-90-205 covers the new
``GET /ideation/business-requirements/template-status`` read.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
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


def _delete_platform_template(db) -> None:
    """Remove the platform-tier BR template + its versions (models-level,
    committed) - simulates the state AFTER #89's rollback discarded the seed
    (the tables exist, empty)."""
    from modules.ideation.models import IdeationArtifactTemplate, IdeationArtifactTemplateVersion
    from modules.ideation.services.br_templates import BR_TEMPLATE_KEY

    existing = (
        db.query(IdeationArtifactTemplate)
        .filter(
            IdeationArtifactTemplate.template_key == BR_TEMPLATE_KEY,
            IdeationArtifactTemplate.tenant_id.is_(None),
        )
        .first()
    )
    if existing is not None:
        db.query(IdeationArtifactTemplateVersion).filter(
            IdeationArtifactTemplateVersion.template_id == existing.id
        ).delete()
        db.delete(existing)
        db.commit()


# ── AC-90-201 - the #89 rollback sequence leaves no platform template ────────


def test_seed_lost_to_rollback_then_migrated_leaves_no_template(ideation_client):
    """AC-90-201 (characterization of the failing sequence, partly green): a
    session that seeds via ``install()`` and then rolls back (modelling the
    lock-timeout -> ``db.rollback()`` step of the #89 sequence, review round
    2) leaves NO platform template row - the flushed insert never survives.
    From that state, BR create must answer the NEW ``br_template_unavailable``
    code (RED - the code does not exist yet) and the new template-status read
    must report inactive (RED - the route does not exist yet)."""
    factory = ideation_client._factory
    db = factory()
    try:
        _delete_platform_template(db)
        engine = db.get_bind()
        from modules.ideation.bootstrap import install

        install(engine, db)  # re-seeds via flush only (bootstrap commits, this test doesn't)
        db.rollback()

        from modules.ideation.models import IdeationArtifactTemplate
        from modules.ideation.services.br_templates import BR_TEMPLATE_KEY

        remaining = (
            db.query(IdeationArtifactTemplate)
            .filter(
                IdeationArtifactTemplate.template_key == BR_TEMPLATE_KEY,
                IdeationArtifactTemplate.tenant_id.is_(None),
            )
            .first()
        )
        assert remaining is None, "the flushed-then-rolled-back seed must not survive"
    finally:
        db.close()

    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    res = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "answers": _FULL_ANSWERS},
    )
    assert res.status_code == 422, res.text
    assert res.json()["detail"]["code"] == "br_template_unavailable"

    status_res = ideation_client.get(
        "/ideation/business-requirements/template-status", headers=h
    )
    assert status_res.status_code == 200, status_res.text
    assert status_res.json() == {"active": False}


# ── AC-90-202 - the next bootstrap seeds and activates it ────────────────────


def test_next_bootstrap_seeds_and_activates(ideation_client):
    """AC-90-202: from the emptied state, a plain ``install()`` + commit (the
    owner's actual workaround, #90 comment 1) seeds + activates the template -
    template-status reports active and a BR create stamps version 1."""
    factory = ideation_client._factory
    db = factory()
    try:
        _delete_platform_template(db)
        engine = db.get_bind()
        from modules.ideation.bootstrap import install

        install(engine, db)
        db.commit()
    finally:
        db.close()

    h = _auth(ideation_client)
    status_res = ideation_client.get(
        "/ideation/business-requirements/template-status", headers=h
    )
    assert status_res.status_code == 200, status_res.text
    assert status_res.json() == {"active": True}

    pid = _product(ideation_client, h)
    res = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "answers": _FULL_ANSWERS},
    )
    assert res.status_code == 201, res.text
    assert res.json()["templateVersion"] == 1


# ── AC-90-203 - the seed repairs a half state (never just insert-if-missing) ─


def _build_half_state(db, kind: str) -> None:
    """Build a broken platform template row directly via the ORM (models
    step, committed) - the residual defect this AC targets: the OLD seed
    guard keys on the template ROW only, so any of these is permanent today."""
    from modules.ideation.models import IdeationArtifactTemplate, IdeationArtifactTemplateVersion
    from modules.ideation.services.br_templates import (
        BR_TEMPLATE_KEY,
        BR_TEMPLATE_NAME,
        br_target_schema,
    )

    _delete_platform_template(db)
    template = IdeationArtifactTemplate(
        tenant_id=None,
        template_key=BR_TEMPLATE_KEY,
        name=BR_TEMPLATE_NAME,
        description="The default Business Requirement capture template.",
        is_system=True,
    )
    db.add(template)
    db.flush()

    if kind != "no_versions":
        doc = br_target_schema()
        version = IdeationArtifactTemplateVersion(
            template_id=template.id,
            tenant_id=None,
            version=1,
            doc_json=doc.model_dump(mode="json"),
            created_by=None,
        )
        db.add(version)
        db.flush()
        if kind == "null_pointer":
            template.active_version_id = None
        elif kind == "dangling_pointer":
            template.active_version_id = "does-not-exist-90"
        else:
            raise AssertionError(f"unknown half-state kind: {kind}")
    else:
        template.active_version_id = None
    db.commit()


@pytest.mark.parametrize("kind", ["null_pointer", "dangling_pointer", "no_versions"])
def test_seed_repairs_half_state(ideation_client, kind):
    """AC-90-203 (RED): the residual defect - the old guard keys on the
    template ROW only, so a template with a NULL/dangling pointer, or zero
    version rows, is broken FOREVER (every future bootstrap early-returns).
    The new ``seed_br_template`` must repair each of these, idempotently."""
    factory = ideation_client._factory
    db = factory()
    try:
        _build_half_state(db, kind)

        from modules.ideation.services.br_templates import (
            active_version_number,
            resolve_active_template,
            seed_br_template,
        )
        from modules.ideation.models import IdeationArtifactTemplateVersion

        seed_br_template(db)
        db.commit()

        template = resolve_active_template(db, None)
        assert template is not None
        version_rows = (
            db.query(IdeationArtifactTemplateVersion)
            .filter(IdeationArtifactTemplateVersion.template_id == template.id)
            .all()
        )
        assert version_rows, "the seed must create v1 when no version rows exist"
        assert active_version_number(template, db) == max(v.version for v in version_rows)
    finally:
        db.close()

    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    res = ideation_client.post(
        "/ideation/business-requirements",
        headers=h,
        json={"productId": pid, "answers": _FULL_ANSWERS},
    )
    assert res.status_code == 201, res.text


# ── AC-90-204 - idempotent, never moves a VALID operator pointer ────────────


def test_seed_is_idempotent_and_keeps_operator_active_version(ideation_session_factory):
    """AC-90-204: an operator who added v2 and activated it keeps v2 active
    across any number of reseeds - a VALID pointer is never moved back, and
    v1's ``doc_json`` is never rewritten. A future regression that makes the
    seed "helpfully" re-point to the highest version unconditionally should
    fail this test (kill-test)."""
    db = ideation_session_factory()
    try:
        from modules.ideation.models import IdeationArtifactTemplate, IdeationArtifactTemplateVersion
        from modules.ideation.services.br_templates import (
            BR_TEMPLATE_KEY,
            active_version_number,
            br_target_schema,
            resolve_active_template,
            seed_br_template,
        )

        template = resolve_active_template(db, None)
        assert template is not None, "base install must have already seeded v1"
        doc = br_target_schema()
        v2 = IdeationArtifactTemplateVersion(
            template_id=template.id,
            tenant_id=None,
            version=2,
            doc_json=doc.model_dump(mode="json"),
            created_by=None,
        )
        db.add(v2)
        db.flush()
        template.active_version_id = v2.id
        db.commit()

        v1_before = (
            db.query(IdeationArtifactTemplateVersion)
            .filter(
                IdeationArtifactTemplateVersion.template_id == template.id,
                IdeationArtifactTemplateVersion.version == 1,
            )
            .first()
        )
        v1_doc_before = v1_before.doc_json

        seed_br_template(db)
        db.commit()
        seed_br_template(db)
        db.commit()

        templates = (
            db.query(IdeationArtifactTemplate)
            .filter(
                IdeationArtifactTemplate.template_key == BR_TEMPLATE_KEY,
                IdeationArtifactTemplate.tenant_id.is_(None),
            )
            .all()
        )
        assert len(templates) == 1
        template = templates[0]
        versions = (
            db.query(IdeationArtifactTemplateVersion)
            .filter(IdeationArtifactTemplateVersion.template_id == template.id)
            .all()
        )
        assert {v.version for v in versions} == {1, 2}
        assert template.active_version_id == v2.id
        assert active_version_number(template, db) == 2

        v1_after = (
            db.query(IdeationArtifactTemplateVersion)
            .filter(
                IdeationArtifactTemplateVersion.template_id == template.id,
                IdeationArtifactTemplateVersion.version == 1,
            )
            .first()
        )
        assert v1_after.doc_json == v1_doc_before
    finally:
        db.close()


# ── AC-90-205 - the template-status read is permission-gated ────────────────


def _make_user(factory, email, password, perm_keys):
    from sqlalchemy.sql import func

    from app.models import Role, User, UserStatus
    from app.models.permission import Permission
    from app.security import hash_password

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


def test_template_status_requires_read_permission(ideation_client):
    """AC-90-205: no token -> 401; a token with no
    ``ideation.business_requirements.read`` -> 403."""
    res = ideation_client.get("/ideation/business-requirements/template-status")
    assert res.status_code == 401, res.text

    _make_user(
        ideation_client._factory,
        "no-br-perm-90@example.com",
        "NoPerm123!",
        set(),
    )
    h = _auth(ideation_client, email="no-br-perm-90@example.com", password="NoPerm123!")
    res = ideation_client.get("/ideation/business-requirements/template-status", headers=h)
    assert res.status_code == 403, res.text
