"""Generic Review/Approval engine tests (plan sprint-4/06 Part A - slice-1
schema/sources/guard portion, AC-06-27..42).

Covers (this slice): config CRUD + score-field guard (422 non-numeric / 200
numeric) · form-publish blocked when it would drop/retype a referenced score
field · role validation (identity-kind uniform, PERSONA needs persona, RULE
conditions validated, EXPLICIT/RULE candidate kind must match role kind) ·
resolve_role_candidates (RULE gate pass/fail + first-N ordering + author
excluded, EXPLICIT, STAFF_ROLE core resolver, PERSONA [] when no resolver) ·
author-actor capture · may_submit · decide() first-wins · average_score
(partial + None + pinned-version answers) · UNIQUE(review_assignments) ·
tenant isolation.

Part B (workflow allocate/escalate ActionDefs, seeded workflow, the firing of
the decision's status transition, EMS persona resolver) is NOT exercised here.
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.form import Form, FormSubmission, FormVersion
from app.models.review import (
    ASSIGNMENT_COMPLETED,
    ASSIGNMENT_PENDING,
    ReviewAssignment,
    ReviewConfiguration,
    ReviewDecision,
    ReviewRole,
    ReviewRoleActor,
)
from app.models.role import Role, user_roles
from app.models.user import User, UserStatus
from app.models import DEFAULT_TENANT_ID
from app.review_engine.resolvers import (
    get_actor_pool_resolver,
    register_actor_pool_resolver,
)
from app.review_engine.service import (
    ReviewConfigService,
    ReviewDecisionConflict,
    ReviewValidationError,
)
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


OTHER_TENANT = "tenant-other"


# ---- HTTP helpers ----


def _login(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD):
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _uniq(prefix):
    return f"{prefix} {uuid.uuid4().hex[:8]}"


# ---- ORM form-with-published-version factory (faster than the full API path) ----


def _published_form(db, tenant_id, *, fields, name=None):
    """Create a Form + a published FormVersion whose doc carries ``fields``
    (FormField dicts). Returns the Form."""
    form = Form(
        tenant_id=tenant_id,
        name=name or _uniq("Form"),
        slug=_uniq("slug").replace(" ", "-"),
        status="published",
        access="internal",
        draft_definition_json={"schemaVersion": 1, "pages": []},
    )
    db.add(form)
    db.flush()
    doc = {
        "schemaVersion": 1,
        "pages": [{"id": "p1", "sections": [{"id": "s1", "fields": fields}]}],
    }
    version = FormVersion(form_id=form.id, version_number=1, definition_json=doc)
    db.add(version)
    db.flush()
    form.current_version_id = version.id
    db.flush()
    return form


def _num_field(key, label="Score"):
    return {"id": f"f_{key}", "type": "number", "key": key, "label": label}


def _text_field(key, label="Field"):
    return {"id": f"f_{key}", "type": "text", "key": key, "label": label}


def _submission(db, tenant_id, form, *, answers=None, user_id=None, subject_type=None, subject_id=None, status_id="st", group_id=None):
    sub_id = str(uuid.uuid4())
    sub = FormSubmission(
        id=sub_id,
        tenant_id=tenant_id,
        form_id=form.id,
        submission_group_id=group_id or sub_id,
        revision_number=1,
        is_current=True,
        version_id=form.current_version_id,
        status_id=status_id,
        user_id=user_id,
        subject_type=subject_type,
        subject_id=subject_id,
        answers_json=answers or {},
    )
    db.add(sub)
    db.flush()
    return sub


def _config(db, tenant_id, form, review_form, *, score_field_key=None, required=1):
    config = ReviewConfiguration(
        tenant_id=tenant_id,
        name=_uniq("Process"),
        form_id=form.id,
        review_form_id=review_form.id,
        required_review_count=required,
        score_field_key=score_field_key,
    )
    db.add(config)
    db.flush()
    return config


def _rule_group(*conditions):
    return {"kind": "group", "combinator": "and", "rules": list(conditions)}


def _cond(fact, operator, value):
    return {"kind": "condition", "fact": fact, "operator": operator, "value": value}


# =====================================================================
# Config CRUD + score-field guard (AC-06-27/36)
# =====================================================================


def test_create_config_with_numeric_score_field(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    db.commit()
    sub_id, rev_id = sub_form.id, rev_form.id
    db.close()

    headers = _login(client)
    res = client.post(
        "/reviews/configurations",
        json={
            "name": _uniq("P"),
            "formId": sub_id,
            "reviewFormId": rev_id,
            "scoreFieldKey": "score",
            "requiredReviewCount": 2,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["scoreFieldKey"] == "score"
    assert body["requiredReviewCount"] == 2

    # Round-trips on list + get.
    assert client.get("/reviews/configurations", headers=headers).json()["total"] >= 1
    got = client.get(f"/reviews/configurations/{body['id']}", headers=headers)
    assert got.status_code == 200
    assert got.json()["formId"] == sub_id


def test_create_config_rejects_non_numeric_score_field(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("comments")])
    db.commit()
    sub_id, rev_id = sub_form.id, rev_form.id
    db.close()

    headers = _login(client)
    res = client.post(
        "/reviews/configurations",
        json={
            "name": _uniq("P"),
            "formId": sub_id,
            "reviewFormId": rev_id,
            "scoreFieldKey": "comments",  # text, not numeric
        },
        headers=headers,
    )
    assert res.status_code == 422, res.text
    assert "numeric" in res.json()["detail"].lower()


def test_create_config_rejects_missing_score_field(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    db.commit()
    sub_id, rev_id = sub_form.id, rev_form.id
    db.close()

    headers = _login(client)
    res = client.post(
        "/reviews/configurations",
        json={
            "name": _uniq("P"),
            "formId": sub_id,
            "reviewFormId": rev_id,
            "scoreFieldKey": "nonexistent",
        },
        headers=headers,
    )
    assert res.status_code == 422, res.text


def test_update_config_score_field_guard(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score"), _text_field("notes")])
    db.commit()
    sub_id, rev_id = sub_form.id, rev_form.id
    db.close()

    headers = _login(client)
    created = client.post(
        "/reviews/configurations",
        json={"name": _uniq("P"), "formId": sub_id, "reviewFormId": rev_id},
        headers=headers,
    ).json()
    # PATCH to a numeric key OK; to a text key 422.
    ok = client.patch(
        f"/reviews/configurations/{created['id']}",
        json={"scoreFieldKey": "score"},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    bad = client.patch(
        f"/reviews/configurations/{created['id']}",
        json={"scoreFieldKey": "notes"},
        headers=headers,
    )
    assert bad.status_code == 422


def test_delete_config(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    db.commit()
    sub_id, rev_id = sub_form.id, rev_form.id
    db.close()

    headers = _login(client)
    created = client.post(
        "/reviews/configurations",
        json={"name": _uniq("P"), "formId": sub_id, "reviewFormId": rev_id, "scoreFieldKey": "score"},
        headers=headers,
    ).json()
    assert client.delete(f"/reviews/configurations/{created['id']}", headers=headers).status_code == 204
    assert client.get(f"/reviews/configurations/{created['id']}", headers=headers).status_code == 404


def test_form_meta_offers_only_valid_pickers(client, session_factory):
    """The admin pickers' only-valid-option universes (AC-06-55): the review
    form's numeric fields (not its text fields) + the submission form's answer
    facts (text → string fact, non-conditionable types dropped)."""
    db = session_factory()
    sub_form = _published_form(
        db,
        DEFAULT_TENANT_ID,
        fields=[_text_field("title"), _num_field("budget", label="Budget")],
    )
    rev_form = _published_form(
        db,
        DEFAULT_TENANT_ID,
        fields=[_num_field("score", label="Overall"), _text_field("comments")],
    )
    db.commit()
    sub_id, rev_id = sub_form.id, rev_form.id
    db.close()

    headers = _login(client)
    res = client.get(
        f"/reviews/configurations/form-meta?submissionFormId={sub_id}&reviewFormId={rev_id}",
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    # Score field = ONLY numeric fields of the review form (text excluded).
    numeric_keys = {f["key"] for f in body["numericFields"]}
    assert "score" in numeric_keys
    assert "comments" not in numeric_keys

    # Submission facts = answer facts of the submission form (namespaced).
    fact_keys = {f["key"] for f in body["submissionFacts"]}
    assert "answers.title" in fact_keys
    assert "answers.budget" in fact_keys


def test_config_requires_permission(client, session_factory):
    # A user with no reviews.* perm is 403.
    db = session_factory()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name=_uniq("Empty"), is_system=False)
    role.permissions = []
    db.add(role)
    db.flush()
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=f"noperm-{uuid.uuid4().hex[:6]}@example.com",
        password=__import__("app.security", fromlist=["hash_password"]).hash_password("Passw0rd!"),
        name="No Perm",
        status=UserStatus.ACTIVE.value,
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    email = user.email
    db.close()

    headers = _login(client, email=email, password="Passw0rd!")
    assert client.get("/reviews/configurations", headers=headers).status_code == 403


# =====================================================================
# Form-publish guard (AC-06-36 second half)
# =====================================================================


def test_publish_blocked_when_dropping_referenced_score_field(client, session_factory):
    """A review form referenced by a config's score_field_key cannot be
    republished with that field removed/retyped."""
    headers = _login(client)
    # Build a review form via the API so publish() runs the real guard.
    rev = client.post("/forms", json={"name": _uniq("Rubric")}, headers=headers).json()
    doc = {
        "schemaVersion": 1,
        "pages": [{"id": "p1", "sections": [{"id": "s1", "fields": [_num_field("score")]}]}],
    }
    client.patch(f"/forms/{rev['id']}", json={"draftDefinition": doc}, headers=headers)
    assert client.post(f"/forms/{rev['id']}/publish", headers=headers).status_code == 200

    sub = client.post("/forms", json={"name": _uniq("Sub")}, headers=headers).json()
    sub_doc = {
        "schemaVersion": 1,
        "pages": [{"id": "p1", "sections": [{"id": "s1", "fields": [_text_field("title")]}]}],
    }
    client.patch(f"/forms/{sub['id']}", json={"draftDefinition": sub_doc}, headers=headers)
    client.post(f"/forms/{sub['id']}/publish", headers=headers)

    # Configure the review process referencing score.
    cfg = client.post(
        "/reviews/configurations",
        json={"name": _uniq("P"), "formId": sub["id"], "reviewFormId": rev["id"], "scoreFieldKey": "score"},
        headers=headers,
    )
    assert cfg.status_code == 201, cfg.text

    # Now retype score → text and try to republish the review form: blocked.
    retyped = {
        "schemaVersion": 1,
        "pages": [{"id": "p1", "sections": [{"id": "s1", "fields": [_text_field("score")]}]}],
    }
    client.patch(f"/forms/{rev['id']}", json={"draftDefinition": retyped}, headers=headers)
    res = client.post(f"/forms/{rev['id']}/publish", headers=headers)
    assert res.status_code == 422, res.text
    assert "problems" in res.json()["detail"]
    assert any("numeric" in p.lower() for p in res.json()["detail"]["problems"])

    # Keeping it numeric republishes fine.
    keep = {
        "schemaVersion": 1,
        "pages": [{"id": "p1", "sections": [{"id": "s1", "fields": [_num_field("score"), _num_field("clarity")]}]}],
    }
    client.patch(f"/forms/{rev['id']}", json={"draftDefinition": keep}, headers=headers)
    assert client.post(f"/forms/{rev['id']}/publish", headers=headers).status_code == 200


# =====================================================================
# Role validation (AC-06-29/30)
# =====================================================================


def _service(db):
    return ReviewConfigService(db)


def test_role_persona_requires_bound_persona(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    db.commit()
    with pytest.raises(ReviewValidationError):
        _service(db).create_config(
            DEFAULT_TENANT_ID,
            name=_uniq("P"),
            form_id=sub_form.id,
            review_form_id=rev_form.id,
            score_field_key="score",
            roles=[{
                "key": "rev", "label": "Reviewer", "can_review": True,
                "actor_source": "PERSONA", "actor_identity_kind": "profile",
            }],
        )
    db.close()


def test_role_explicit_candidate_kind_must_match(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    db.commit()
    with pytest.raises(ReviewValidationError):
        _service(db).create_config(
            DEFAULT_TENANT_ID,
            name=_uniq("P"),
            form_id=sub_form.id,
            review_form_id=rev_form.id,
            score_field_key="score",
            roles=[{
                "key": "dec", "label": "Decider", "can_decide": True,
                "actor_source": "EXPLICIT", "actor_identity_kind": "profile",
                # a USER candidate in a PROFILE role → 422
                "actors": [{"actor_kind": "user", "actor_id": "u1"}],
            }],
        )
    db.close()


def test_role_rule_conditions_validated(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("track")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    db.commit()
    # A condition referencing a non-existent submission field → 422.
    with pytest.raises(ReviewValidationError):
        _service(db).create_config(
            DEFAULT_TENANT_ID,
            name=_uniq("P"),
            form_id=sub_form.id,
            review_form_id=rev_form.id,
            score_field_key="score",
            roles=[{
                "key": "rev", "label": "Reviewer", "can_review": True,
                "actor_source": "RULE", "actor_identity_kind": "profile",
                "conditions_json": _rule_group(_cond("answers.nope", "eq", "x")),
            }],
        )
    # A valid condition (references a real field) saves.
    config = _service(db).create_config(
        DEFAULT_TENANT_ID,
        name=_uniq("P"),
        form_id=sub_form.id,
        review_form_id=rev_form.id,
        score_field_key="score",
        roles=[{
            "key": "rev", "label": "Reviewer", "can_review": True,
            "actor_source": "RULE", "actor_identity_kind": "profile",
            "conditions_json": _rule_group(_cond("answers.track", "eq", 1)),
            "actors": [{"actor_kind": "profile", "actor_id": "p1"}],
        }],
    )
    roles = ReviewConfigService(db).repo.list_roles(DEFAULT_TENANT_ID, config.id)
    assert roles[0].conditions_json is not None
    db.close()


# =====================================================================
# resolve_role_candidates (AC-06-30/32/42)
# =====================================================================


def test_resolve_explicit_excludes_author(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score")
    role = ReviewRole(
        tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id, key="rev",
        label="Reviewer", can_review=True, actor_source="EXPLICIT",
        actor_identity_kind="profile", sort_order=0,
    )
    db.add(role); db.flush()
    for i, pid in enumerate(["pA", "pB", "pC"]):
        db.add(ReviewRoleActor(tenant_id=DEFAULT_TENANT_ID, role_id=role.id, actor_kind="profile", actor_id=pid, sort_order=i))
    db.flush()
    # Author is pB (a profile-subject submission).
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile", subject_id="pB")
    db.commit()

    cands = ReviewConfigService(db).resolve_role_candidates(DEFAULT_TENANT_ID, config, role, sub, 1)
    assert cands == [("profile", "pA"), ("profile", "pC")]  # ordered, author pB dropped
    db.close()


def test_resolve_rule_gate_fail_returns_empty(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("track")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score")
    role = ReviewRole(
        tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id, key="rev",
        label="Reviewer", can_review=True, actor_source="RULE",
        actor_identity_kind="profile", sort_order=0,
        conditions_json=_rule_group(_cond("answers.track", "eq", 2)),
    )
    db.add(role); db.flush()
    db.add(ReviewRoleActor(tenant_id=DEFAULT_TENANT_ID, role_id=role.id, actor_kind="profile", actor_id="pA", sort_order=0))
    db.flush()
    # track=1 → gate False → no candidates.
    sub_fail = _submission(db, DEFAULT_TENANT_ID, sub_form, answers={"track": 1})
    # track=2 → gate passes → pA.
    sub_pass = _submission(db, DEFAULT_TENANT_ID, sub_form, answers={"track": 2})
    db.commit()

    svc = ReviewConfigService(db)
    assert svc.resolve_role_candidates(DEFAULT_TENANT_ID, config, role, sub_fail, 1) == []
    assert svc.resolve_role_candidates(DEFAULT_TENANT_ID, config, role, sub_pass, 1) == [("profile", "pA")]
    db.close()


def test_resolve_rule_first_n_ordering_and_per_candidate_gate(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("track")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score", required=2)
    role = ReviewRole(
        tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id, key="rev",
        label="Reviewer", can_review=True, actor_source="RULE",
        actor_identity_kind="profile", sort_order=0, conditions_json=None,
    )
    db.add(role); db.flush()
    # pA always; pB only when track=9; pC always.
    db.add(ReviewRoleActor(tenant_id=DEFAULT_TENANT_ID, role_id=role.id, actor_kind="profile", actor_id="pA", sort_order=0))
    db.add(ReviewRoleActor(tenant_id=DEFAULT_TENANT_ID, role_id=role.id, actor_kind="profile", actor_id="pB", sort_order=1, conditions_json=_rule_group(_cond("answers.track", "eq", 9))))
    db.add(ReviewRoleActor(tenant_id=DEFAULT_TENANT_ID, role_id=role.id, actor_kind="profile", actor_id="pC", sort_order=2))
    db.flush()
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, answers={"track": 1})
    db.commit()

    cands = ReviewConfigService(db).resolve_role_candidates(DEFAULT_TENANT_ID, config, role, sub, 1)
    # pB gated out; order preserved. Caller trims to first-N (we return all eligible).
    assert cands == [("profile", "pA"), ("profile", "pC")]
    db.close()


def test_resolve_staff_role_core_resolver(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score")
    # A staff role with two users assigned.
    staff_role = Role(tenant_id=DEFAULT_TENANT_ID, name=_uniq("Judges"), is_system=False)
    staff_role.permissions = []
    db.add(staff_role); db.flush()
    from app.security import hash_password
    users = []
    for i in range(2):
        u = User(tenant_id=DEFAULT_TENANT_ID, email=f"judge{i}-{uuid.uuid4().hex[:5]}@e.com",
                 password=hash_password("Passw0rd!"), name=f"Judge {i}", status=UserStatus.ACTIVE.value)
        u.roles = [staff_role]
        db.add(u); users.append(u)
    db.flush()
    role = ReviewRole(
        tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id, key="rev",
        label="Reviewer", can_review=True, actor_source="STAFF_ROLE",
        actor_identity_kind="user", bound_staff_role_id=staff_role.id, sort_order=0,
    )
    db.add(role); db.flush()
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, user_id=users[0].id)  # author = users[0]
    db.commit()

    cands = ReviewConfigService(db).resolve_role_candidates(DEFAULT_TENANT_ID, config, role, sub, 1)
    # Author users[0] excluded; only users[1] remains.
    assert cands == [("user", users[1].id)]
    db.close()


def test_resolve_persona_empty_without_resolver(client, session_factory):
    # PERSONA with no registered resolver → [] (fail-closed, no crash).
    # Ensure no PERSONA resolver is registered for this test.
    saved = get_actor_pool_resolver("PERSONA")
    if saved is not None:
        # remove it for the duration of the test
        from app.review_engine import resolvers as R
        R._RESOLVERS.pop("PERSONA", None)
    try:
        db = session_factory()
        sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
        rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
        config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score")
        role = ReviewRole(
            tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id, key="rev",
            label="Reviewer", can_review=True, actor_source="PERSONA",
            actor_identity_kind="profile", bound_persona_id="persona-x", sort_order=0,
        )
        db.add(role); db.flush()
        sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile", subject_id="pZ")
        db.commit()
        assert ReviewConfigService(db).resolve_role_candidates(DEFAULT_TENANT_ID, config, role, sub, 1) == []
        db.close()
    finally:
        if saved is not None:
            register_actor_pool_resolver("PERSONA", saved)


# =====================================================================
# Author-actor capture (AC-06-41/42)
# =====================================================================


def test_author_actor_capture_profile_and_user(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    profile_sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile", subject_id="pX")
    user_sub = _submission(db, DEFAULT_TENANT_ID, sub_form, user_id="uX")
    anon_sub = _submission(db, DEFAULT_TENANT_ID, sub_form)
    db.commit()
    svc = ReviewConfigService(db)
    assert svc.submission_author_actor(profile_sub) == ("profile", "pX")
    assert svc.submission_author_actor(user_sub) == ("user", "uX")
    assert svc.submission_author_actor(anon_sub) is None
    db.close()


# =====================================================================
# may_submit (AC-06-31)
# =====================================================================


def test_may_submit_explicit(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score")
    role = ReviewRole(
        tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id, key="auth",
        label="Author", can_submit=True, actor_source="EXPLICIT",
        actor_identity_kind="profile", sort_order=0,
    )
    db.add(role); db.flush()
    db.add(ReviewRoleActor(tenant_id=DEFAULT_TENANT_ID, role_id=role.id, actor_kind="profile", actor_id="pA", sort_order=0))
    db.commit()
    svc = ReviewConfigService(db)
    assert svc.may_submit(DEFAULT_TENANT_ID, config, "profile", "pA") is True
    assert svc.may_submit(DEFAULT_TENANT_ID, config, "profile", "pZ") is False
    assert svc.may_submit(DEFAULT_TENANT_ID, config, "user", "pA") is False  # wrong kind
    db.close()


# =====================================================================
# decide() first-wins (AC-06-34)
# =====================================================================


def test_decide_first_wins(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score")
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile", subject_id="pA")
    db.commit()
    gid = sub.submission_group_id
    svc = ReviewConfigService(db)
    first = svc.decide(DEFAULT_TENANT_ID, config, gid, 1, "profile", "decider1", "ACCEPTED", "great")
    assert first.decision == "ACCEPTED"
    # Second attempt = no-op/409, NOT a double write.
    with pytest.raises(ReviewDecisionConflict):
        svc.decide(DEFAULT_TENANT_ID, config, gid, 1, "profile", "decider2", "REJECTED")
    rows = db.query(ReviewDecision).filter(
        ReviewDecision.reviewed_submission_group_id == gid,
        ReviewDecision.revision_number == 1,
    ).all()
    assert len(rows) == 1
    assert rows[0].decider_id == "decider1"
    db.close()


# =====================================================================
# average_score (AC-06-35)
# =====================================================================


def test_average_score_partial_and_none(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score", required=3)
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile", subject_id="pA")
    gid = sub.submission_group_id

    # Three reviews of the rubric form: two completed (8, 6), one pending.
    r1 = _submission(db, DEFAULT_TENANT_ID, rev_form, answers={"score": 8})
    r2 = _submission(db, DEFAULT_TENANT_ID, rev_form, answers={"score": 6})
    db.add(ReviewAssignment(tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id,
                            reviewed_submission_group_id=gid, revision_number=1, role_id="role",
                            actor_kind="profile", actor_id="rA", review_submission_id=r1.id, status=ASSIGNMENT_COMPLETED))
    db.add(ReviewAssignment(tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id,
                            reviewed_submission_group_id=gid, revision_number=1, role_id="role",
                            actor_kind="profile", actor_id="rB", review_submission_id=r2.id, status=ASSIGNMENT_COMPLETED))
    db.add(ReviewAssignment(tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id,
                            reviewed_submission_group_id=gid, revision_number=1, role_id="role",
                            actor_kind="profile", actor_id="rC", review_submission_id=None, status=ASSIGNMENT_PENDING))
    db.commit()

    svc = ReviewConfigService(db)
    assert svc.average_score(DEFAULT_TENANT_ID, config, gid, 1) == pytest.approx(7.0)

    # A group with zero completed reviews → None.
    other = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile", subject_id="pB")
    db.commit()
    assert svc.average_score(DEFAULT_TENANT_ID, config, other.submission_group_id, 1) is None
    db.close()


# =====================================================================
# UNIQUE(review_assignments) (AC-06-37)
# =====================================================================


def test_assignment_unique_per_actor_revision(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score")
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile", subject_id="pA")
    gid = sub.submission_group_id
    db.add(ReviewAssignment(tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id,
                            reviewed_submission_group_id=gid, revision_number=1, role_id="role",
                            actor_kind="profile", actor_id="rA"))
    db.commit()
    db.add(ReviewAssignment(tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id,
                            reviewed_submission_group_id=gid, revision_number=1, role_id="role",
                            actor_kind="profile", actor_id="rA"))  # duplicate
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    # A different revision for the SAME actor is allowed (per-revision history).
    db.add(ReviewAssignment(tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id,
                            reviewed_submission_group_id=gid, revision_number=2, role_id="role",
                            actor_kind="profile", actor_id="rA"))
    db.commit()
    db.close()


# =====================================================================
# Audit additions (QA gap closure) - AC-06-29/30/34/57
# =====================================================================


def test_role_rule_candidate_kind_must_match(client, session_factory):
    """AC-06-29/30: a RULE role's named candidate kind must match the role's
    identity kind (the EXPLICIT path is tested above; RULE shares the loop)."""
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("track")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    db.commit()
    with pytest.raises(ReviewValidationError):
        _service(db).create_config(
            DEFAULT_TENANT_ID,
            name=_uniq("P"),
            form_id=sub_form.id,
            review_form_id=rev_form.id,
            score_field_key="score",
            roles=[{
                "key": "rev", "label": "Reviewer", "can_review": True,
                "actor_source": "RULE", "actor_identity_kind": "profile",
                "conditions_json": _rule_group(_cond("answers.track", "eq", 1)),
                # a USER candidate inside a PROFILE rule role → 422
                "actors": [{"actor_kind": "user", "actor_id": "u1"}],
            }],
        )
    db.close()


def test_role_staff_role_requires_binding(client, session_factory):
    """AC-06-30: a STAFF_ROLE role with no bound staff role is rejected."""
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    db.commit()
    with pytest.raises(ReviewValidationError):
        _service(db).create_config(
            DEFAULT_TENANT_ID,
            name=_uniq("P"),
            form_id=sub_form.id,
            review_form_id=rev_form.id,
            score_field_key="score",
            roles=[{
                "key": "rev", "label": "Reviewer", "can_review": True,
                "actor_source": "STAFF_ROLE", "actor_identity_kind": "user",
            }],
        )
    db.close()


def test_staff_role_resolver_tenant_scoped(client, session_factory):
    """AC-06-57: a STAFF_ROLE bound to ANOTHER tenant's role resolves to an empty
    pool - the resolver scopes both Role.tenant_id and User.tenant_id, so a
    foreign/planted staff-role id never leaks that tenant's users."""
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score")
    # A staff role + a user owned by OTHER_TENANT.
    from app.security import hash_password
    other_role = Role(tenant_id=OTHER_TENANT, name=_uniq("Foreign"), is_system=False)
    other_role.permissions = []
    db.add(other_role); db.flush()
    ou = User(tenant_id=OTHER_TENANT, email=f"foreign-{uuid.uuid4().hex[:5]}@e.com",
              password=hash_password("Passw0rd!"), name="Foreign", status=UserStatus.ACTIVE.value)
    ou.roles = [other_role]
    db.add(ou); db.flush()
    # DEFAULT-tenant config role binds the FOREIGN staff role id.
    role = ReviewRole(
        tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id, key="rev",
        label="Reviewer", can_review=True, actor_source="STAFF_ROLE",
        actor_identity_kind="user", bound_staff_role_id=other_role.id, sort_order=0,
    )
    db.add(role); db.flush()
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile", subject_id="pX")
    db.commit()
    cands = ReviewConfigService(db).resolve_role_candidates(DEFAULT_TENANT_ID, config, role, sub, 1)
    assert cands == []  # foreign tenant's user never leaks
    db.close()


def test_decision_durable_when_target_status_unset(client, session_factory):
    """AC-06-34: decide_and_transition writes the first-wins decision durably even
    when no target status is mapped for the outcome (the transition is skipped, the
    decision still commits - first-wins is honored)."""
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    # No accepted_status_id mapped.
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score")
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile", subject_id="pA")
    db.commit()
    gid = sub.submission_group_id
    row = ReviewConfigService(db).decide_and_transition(
        DEFAULT_TENANT_ID, config, gid, 1, "profile", "decider1", "ACCEPTED"
    )
    db.commit()
    assert row.decision == "ACCEPTED"
    stored = db.query(ReviewDecision).filter(
        ReviewDecision.reviewed_submission_group_id == gid).all()
    assert len(stored) == 1  # durable despite no transition
    db.close()


def test_average_ignores_non_numeric_and_non_completed(client, session_factory):
    """AC-06-35: only COMPLETED assignments with a numeric score contribute; a
    completed review carrying a non-numeric value is skipped, not crashed."""
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score", required=3)
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile", subject_id="pA")
    gid = sub.submission_group_id
    r1 = _submission(db, DEFAULT_TENANT_ID, rev_form, answers={"score": 10})
    r2 = _submission(db, DEFAULT_TENANT_ID, rev_form, answers={"score": "not a number"})
    db.add(ReviewAssignment(tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id,
                            reviewed_submission_group_id=gid, revision_number=1, role_id="role",
                            actor_kind="profile", actor_id="rA", review_submission_id=r1.id,
                            status=ASSIGNMENT_COMPLETED))
    db.add(ReviewAssignment(tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id,
                            reviewed_submission_group_id=gid, revision_number=1, role_id="role",
                            actor_kind="profile", actor_id="rB", review_submission_id=r2.id,
                            status=ASSIGNMENT_COMPLETED))
    db.commit()
    # Only the numeric 10 counts → average 10.0 (the junk value is ignored).
    assert ReviewConfigService(db).average_score(DEFAULT_TENANT_ID, config, gid, 1) == pytest.approx(10.0)
    db.close()


# =====================================================================
# Tenant isolation (AC-06-57)
# =====================================================================


def test_config_tenant_isolation(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, OTHER_TENANT, fields=[_text_field("title")])
    rev_form = _published_form(db, OTHER_TENANT, fields=[_num_field("score")])
    config = _config(db, OTHER_TENANT, sub_form, rev_form, score_field_key="score")
    db.commit()
    other_id = config.id
    db.close()

    headers = _login(client)  # default-tenant admin
    # The other tenant's config is invisible.
    assert client.get(f"/reviews/configurations/{other_id}", headers=headers).status_code == 404
    ids = {c["id"] for c in client.get("/reviews/configurations", headers=headers).json()["data"]}
    assert other_id not in ids
    db.close()
