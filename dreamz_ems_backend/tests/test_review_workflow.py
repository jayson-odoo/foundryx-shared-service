"""Review/Approval engine PART B tests (plan sprint-4/06) —
``review.allocate`` / ``review.escalate`` ActionDefs, the seeded allocate
workflow, decision→transition firing, EMS persona/contact resolvers, and the
EMS event review-config helper.

Build targets: AC-06-32, 33, 34 (transition), 40, 49, 50, 51 (+ AC-06-04/09/10).

Eager workflows (conftest sets celery_task_always_eager=True) — the seeded
allocate workflow fires inline on a real status transition.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.form import FORM_SUBMISSION_ENTITY, Form, FormSubmission, FormVersion
from app.models.review import (
    ASSIGNMENT_ESCALATED,
    ASSIGNMENT_PENDING,
    ReviewAssignment,
    ReviewConfiguration,
    ReviewDecision,
    ReviewRole,
    ReviewRoleActor,
)
from app.models.role import Role
from app.models.user import User, UserStatus
from app.review_engine.actions import review_allocate, review_escalate
from app.review_engine.resolvers import resolve_actor_contact
from app.review_engine.service import (
    ReviewConfigService,
    ReviewDecisionConflict,
    ReviewTransitionUnavailable,
)
from app.security import hash_password
from app.status_engine.scoped import (
    ScopeSeedEdge,
    ScopeSeedStatus,
    materialize_scope,
)


def _uniq(prefix):
    return f"{prefix} {uuid.uuid4().hex[:8]}"


# ---- factories ----


def _published_form(db, tenant_id, *, fields, name=None):
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


def _submission(db, tenant_id, form, *, answers=None, user_id=None, subject_type=None,
                subject_id=None, status_id="st", group_id=None, revision=1, is_current=True):
    sub_id = str(uuid.uuid4())
    sub = FormSubmission(
        id=sub_id,
        tenant_id=tenant_id,
        form_id=form.id,
        submission_group_id=group_id or sub_id,
        revision_number=revision,
        is_current=is_current,
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


def _config(db, tenant_id, form, review_form, *, score_field_key=None, required=1,
            window_end=None, review_start_status_id=None, accepted_status_id=None,
            rejected_status_id=None, revisions_status_id=None):
    config = ReviewConfiguration(
        tenant_id=tenant_id,
        name=_uniq("Process"),
        form_id=form.id,
        review_form_id=review_form.id,
        required_review_count=required,
        score_field_key=score_field_key,
        window_end=window_end,
        review_start_status_id=review_start_status_id,
        accepted_status_id=accepted_status_id,
        rejected_status_id=rejected_status_id,
        revisions_status_id=revisions_status_id,
    )
    db.add(config)
    db.flush()
    return config


def _explicit_review_role(db, tenant_id, config, profile_ids):
    role = ReviewRole(
        tenant_id=tenant_id, review_configuration_id=config.id, key="rev",
        label="Reviewer", can_review=True, actor_source="EXPLICIT",
        actor_identity_kind="profile", sort_order=0,
    )
    db.add(role)
    db.flush()
    for i, pid in enumerate(profile_ids):
        db.add(ReviewRoleActor(tenant_id=tenant_id, role_id=role.id,
                               actor_kind="profile", actor_id=pid, sort_order=i))
    db.flush()
    return role


def _staff_role_with_users(db, tenant_id, n=2):
    staff_role = Role(tenant_id=tenant_id, name=_uniq("Judges"), is_system=False)
    staff_role.permissions = []
    db.add(staff_role)
    db.flush()
    users = []
    for i in range(n):
        u = User(tenant_id=tenant_id, email=f"judge{i}-{uuid.uuid4().hex[:5]}@e.com",
                 password=hash_password("Passw0rd!"), name=f"Judge {i}",
                 status=UserStatus.ACTIVE.value)
        u.roles = [staff_role]
        db.add(u)
        users.append(u)
    db.flush()
    return staff_role, users


def _assignments(db, config_id, group_id, revision=1):
    return (
        db.query(ReviewAssignment)
        .filter(
            ReviewAssignment.review_configuration_id == config_id,
            ReviewAssignment.reviewed_submission_group_id == group_id,
            ReviewAssignment.revision_number == revision,
        )
        .order_by(ReviewAssignment.assigned_at.asc())
        .all()
    )


# =====================================================================
# review.allocate executor (AC-06-32)
# =====================================================================


def test_allocate_first_n_excludes_author_idempotent(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score", required=2)
    # 4 candidate reviewers; author is pB.
    _explicit_review_role(db, DEFAULT_TENANT_ID, config, ["pA", "pB", "pC", "pD"])
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile", subject_id="pB")
    db.commit()
    gid = sub.submission_group_id
    ctx = {"trigger.record.id": sub.id}

    out = review_allocate(db, DEFAULT_TENANT_ID, {"reviewConfigurationId": config.id}, ctx)
    db.commit()
    assert out["assigned"] == 2
    rows = _assignments(db, config.id, gid)
    assert [r.actor_id for r in rows] == ["pA", "pC"]  # first-2, author pB skipped
    assert all(r.status == ASSIGNMENT_PENDING for r in rows)

    # Re-run = idempotent (count met → no new assignments).
    out2 = review_allocate(db, DEFAULT_TENANT_ID, {"reviewConfigurationId": config.id}, ctx)
    db.commit()
    assert out2["assigned"] == 0
    assert len(_assignments(db, config.id, gid)) == 2
    db.close()


def test_allocate_notifies_each_assignee(client, session_factory, monkeypatch):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score", required=2)
    # STAFF_ROLE source so the core "user" contact resolver resolves real emails.
    staff_role, users = _staff_role_with_users(db, DEFAULT_TENANT_ID, n=3)
    role = ReviewRole(
        tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id, key="rev",
        label="Reviewer", can_review=True, actor_source="STAFF_ROLE",
        actor_identity_kind="user", bound_staff_role_id=staff_role.id, sort_order=0,
    )
    db.add(role)
    db.flush()
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, user_id=users[0].id)  # author
    db.commit()

    calls = []
    import app.services.email_service as es

    def _spy(self, db_, tenant_id, to_email, *a, **k):
        calls.append(to_email)

    monkeypatch.setattr(es.OutboxEmailService, "enqueue_raw", _spy)

    out = review_allocate(db, DEFAULT_TENANT_ID, {"reviewConfigurationId": config.id},
                          {"trigger.record.id": sub.id})
    db.commit()
    assert out["assigned"] == 2
    # author users[0] excluded; users[1], users[2] notified.
    assert set(calls) == {users[1].email, users[2].email}
    db.close()


def test_allocate_revision_prefers_prior_reviewers(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score", required=2)
    # Pool ordered pA, pB, pC, pD.
    _explicit_review_role(db, DEFAULT_TENANT_ID, config, ["pA", "pB", "pC", "pD"])
    group_id = str(uuid.uuid4())
    # Revision 1 was reviewed by pC + pD (NOT the first-N) — simulate prior round.
    db.add(ReviewAssignment(tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id,
                            reviewed_submission_group_id=group_id, revision_number=1, role_id="role",
                            actor_kind="profile", actor_id="pC"))
    db.add(ReviewAssignment(tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id,
                            reviewed_submission_group_id=group_id, revision_number=1, role_id="role",
                            actor_kind="profile", actor_id="pD"))
    # Revision-2 submission (same group).
    sub2 = _submission(db, DEFAULT_TENANT_ID, sub_form, group_id=group_id, revision=2)
    db.commit()

    out = review_allocate(db, DEFAULT_TENANT_ID, {"reviewConfigurationId": config.id},
                          {"trigger.record.id": sub2.id})
    db.commit()
    assert out["assigned"] == 2
    rows = _assignments(db, config.id, group_id, revision=2)
    # Prior reviewers pC, pD preferred over the first-N pA, pB.
    assert {r.actor_id for r in rows} == {"pC", "pD"}
    db.close()


def test_allocate_revision_tops_up_when_prior_short(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score", required=2)
    _explicit_review_role(db, DEFAULT_TENANT_ID, config, ["pA", "pB", "pC"])
    group_id = str(uuid.uuid4())
    # Prior round had only pC.
    db.add(ReviewAssignment(tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id,
                            reviewed_submission_group_id=group_id, revision_number=1, role_id="role",
                            actor_kind="profile", actor_id="pC"))
    sub2 = _submission(db, DEFAULT_TENANT_ID, sub_form, group_id=group_id, revision=2)
    db.commit()

    review_allocate(db, DEFAULT_TENANT_ID, {"reviewConfigurationId": config.id},
                    {"trigger.record.id": sub2.id})
    db.commit()
    rows = _assignments(db, config.id, group_id, revision=2)
    # pC preferred + topped up to 2 via candidate order (pA).
    assert rows[0].actor_id == "pC"
    assert {r.actor_id for r in rows} == {"pC", "pA"}
    db.close()


# =====================================================================
# review.escalate executor (AC-06-33)
# =====================================================================


def test_escalate_marks_overdue_and_reallocates(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score",
                     required=2, window_end=past)
    _explicit_review_role(db, DEFAULT_TENANT_ID, config, ["pA", "pB", "pC", "pD"])
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile", subject_id="pZ")
    db.commit()
    gid = sub.submission_group_id
    ctx = {"trigger.record.id": sub.id}

    # First allocate → pA, pB pending.
    review_allocate(db, DEFAULT_TENANT_ID, {"reviewConfigurationId": config.id}, ctx)
    db.commit()
    assert {r.actor_id for r in _assignments(db, config.id, gid)} == {"pA", "pB"}

    # Escalate: window_end is past, both PENDING → ESCALATED + re-allocate excl. them.
    out = review_escalate(db, DEFAULT_TENANT_ID, {"reviewConfigurationId": config.id}, ctx)
    db.commit()
    assert out["escalated"] == 2
    assert out["assigned"] == 2
    rows = _assignments(db, config.id, gid)
    escalated = {r.actor_id for r in rows if r.status == ASSIGNMENT_ESCALATED}
    pending = {r.actor_id for r in rows if r.status == ASSIGNMENT_PENDING}
    assert escalated == {"pA", "pB"}
    # Re-allocated to the next candidates, never the escalated non-responders.
    assert pending == {"pC", "pD"}
    db.close()


def test_escalate_noop_before_window_end(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score",
                     required=1, window_end=future)
    _explicit_review_role(db, DEFAULT_TENANT_ID, config, ["pA", "pB"])
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form)
    db.commit()
    ctx = {"trigger.record.id": sub.id}
    review_allocate(db, DEFAULT_TENANT_ID, {"reviewConfigurationId": config.id}, ctx)
    db.commit()
    out = review_escalate(db, DEFAULT_TENANT_ID, {"reviewConfigurationId": config.id}, ctx)
    assert out == {"escalated": 0, "assigned": 0}
    db.close()


# =====================================================================
# Seeded allocate workflow fires on the real transition (AC-06-04/32)
# =====================================================================


def _seed_submission_scope(db, tenant_id, form_id):
    """Materialize a form_submission scope graph: Draft → InReview (the
    review_start), plus the lifecycle targets accepted/rejected/revisions."""
    by_key = materialize_scope(
        db, FORM_SUBMISSION_ENTITY, tenant_id, form_id,
        statuses=[
            ScopeSeedStatus("draft", "Draft", "gray", 1, {"is_initial": True, "is_active": True}),
            ScopeSeedStatus("in_review", "In Review", "blue", 2, {}),
            ScopeSeedStatus("accepted", "Accepted", "green", 3, {"is_terminal": True}),
            ScopeSeedStatus("rejected", "Rejected", "red", 4, {"is_terminal": True}),
            ScopeSeedStatus("revisions", "Revisions", "amber", 5, {"is_active": True}),
        ],
        edges=[
            ScopeSeedEdge("draft", "in_review", "Submit", 1),
            ScopeSeedEdge("in_review", "accepted", "Accept", 2),
            ScopeSeedEdge("in_review", "rejected", "Reject", 3),
            ScopeSeedEdge("in_review", "revisions", "Request revisions", 4),
            ScopeSeedEdge("revisions", "in_review", "Resubmit", 5),
        ],
    )
    return by_key


def test_seeded_workflow_fires_allocate_on_transition(client, session_factory):
    """Canonical-flow proof (AC-06-04): create a config with review_start_status_id
    → the allocate workflow is seeded + published → driving a real submission
    transition INTO that status fires the workflow → assignments appear."""
    from app.services import status_machine

    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    by_key = _seed_submission_scope(db, DEFAULT_TENANT_ID, sub_form.id)
    in_review = by_key["in_review"].id
    db.commit()

    # Create the config via the service so the allocate workflow seeds + publishes.
    config = ReviewConfigService(db).create_config(
        DEFAULT_TENANT_ID,
        name=_uniq("Event reviews"),
        form_id=sub_form.id,
        review_form_id=rev_form.id,
        score_field_key="score",
        required_review_count=2,
        review_start_status_id=in_review,
        roles=[{
            "key": "rev", "label": "Reviewer", "can_review": True,
            "actor_source": "EXPLICIT", "actor_identity_kind": "profile",
            "actors": [
                {"actor_kind": "profile", "actor_id": "pA", "sort_order": 0},
                {"actor_kind": "profile", "actor_id": "pB", "sort_order": 1},
                {"actor_kind": "profile", "actor_id": "pC", "sort_order": 2},
            ],
        }],
    )

    # A submission in Draft authored by pC.
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile",
                      subject_id="pC", status_id=by_key["draft"].id)
    db.commit()
    gid = sub.submission_group_id

    # Drive the REAL transition Draft → In Review (eager workflows fire inline).
    status_machine.transition(db, FORM_SUBMISSION_ENTITY, sub, in_review, tenant_id=DEFAULT_TENANT_ID)
    db.commit()

    rows = _assignments(db, config.id, gid)
    # Author pC excluded; first-2 pA, pB assigned by the FIRED workflow.
    assert {r.actor_id for r in rows} == {"pA", "pB"}
    db.close()


# =====================================================================
# decide_and_transition (AC-06-34)
# =====================================================================


def test_decide_and_transition_fires_mapped_status(client, session_factory):
    from app.repositories.status_repository import StatusRepository

    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    by_key = _seed_submission_scope(db, DEFAULT_TENANT_ID, sub_form.id)
    in_review = by_key["in_review"].id
    accepted = by_key["accepted"].id
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score",
                     review_start_status_id=in_review, accepted_status_id=accepted)
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile",
                      subject_id="pA", status_id=in_review)
    db.commit()
    gid = sub.submission_group_id

    svc = ReviewConfigService(db)
    row = svc.decide_and_transition(DEFAULT_TENANT_ID, config, gid, 1, "profile",
                                    "decider1", "ACCEPTED", "great")
    db.commit()
    assert row.decision == "ACCEPTED"
    db.refresh(sub)
    assert sub.status_id == accepted  # mapped transition fired
    db.close()


def test_decide_and_transition_second_is_noop(client, session_factory):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    by_key = _seed_submission_scope(db, DEFAULT_TENANT_ID, sub_form.id)
    in_review = by_key["in_review"].id
    accepted = by_key["accepted"].id
    rejected = by_key["rejected"].id
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score",
                     review_start_status_id=in_review, accepted_status_id=accepted,
                     rejected_status_id=rejected)
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile",
                      subject_id="pA", status_id=in_review)
    db.commit()
    gid = sub.submission_group_id

    svc = ReviewConfigService(db)
    svc.decide_and_transition(DEFAULT_TENANT_ID, config, gid, 1, "profile",
                              "decider1", "ACCEPTED")
    db.commit()
    # Second concurrent decide = no-op/409, no double transition.
    with pytest.raises(ReviewDecisionConflict):
        svc.decide_and_transition(DEFAULT_TENANT_ID, config, gid, 1, "profile",
                                  "decider2", "REJECTED")
    db.rollback()
    db.refresh(sub)
    assert sub.status_id == accepted  # still Accepted, never moved to Rejected
    assert db.query(ReviewDecision).filter(
        ReviewDecision.reviewed_submission_group_id == gid).count() == 1
    db.close()


def test_decide_and_transition_no_edge_raises_no_orphan(client, session_factory):
    """Misconfigured status mapping: the mapped target has NO edge from the
    submission's CURRENT status → ReviewTransitionUnavailable, and the decision
    row is NEVER written (no orphan decided-but-not-moved row)."""
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    by_key = _seed_submission_scope(db, DEFAULT_TENANT_ID, sub_form.id)
    in_review = by_key["in_review"].id
    draft = by_key["draft"].id  # NO edge in_review -> draft exists in the seed graph
    # Map REVISIONS -> draft (the misconfig): from in_review there is no such edge.
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score",
                     review_start_status_id=in_review, revisions_status_id=draft)
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile",
                      subject_id="pA", status_id=in_review)
    db.commit()
    gid = sub.submission_group_id

    svc = ReviewConfigService(db)
    with pytest.raises(ReviewTransitionUnavailable):
        svc.decide_and_transition(DEFAULT_TENANT_ID, config, gid, 1, "profile",
                                  "decider1", "REVISIONS", "please revise")
    db.rollback()
    # No orphan decision row, and the submission never moved.
    assert db.query(ReviewDecision).filter(
        ReviewDecision.reviewed_submission_group_id == gid).count() == 0
    db.refresh(sub)
    assert sub.status_id == in_review
    db.close()


def test_decide_and_transition_valid_revisions_edge_fires(client, session_factory):
    """Happy path: a mapped target WITH an edge from the current status →
    decision written + transition fired (the revise loop re-arms)."""
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    by_key = _seed_submission_scope(db, DEFAULT_TENANT_ID, sub_form.id)
    in_review = by_key["in_review"].id
    revisions = by_key["revisions"].id  # in_review -> revisions edge exists
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score",
                     review_start_status_id=in_review, revisions_status_id=revisions)
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile",
                      subject_id="pA", status_id=in_review)
    db.commit()
    gid = sub.submission_group_id

    svc = ReviewConfigService(db)
    row = svc.decide_and_transition(DEFAULT_TENANT_ID, config, gid, 1, "profile",
                                    "decider1", "REVISIONS", "please revise")
    db.commit()
    assert row.decision == "REVISIONS"
    db.refresh(sub)
    assert sub.status_id == revisions
    assert db.query(ReviewDecision).filter(
        ReviewDecision.reviewed_submission_group_id == gid).count() == 1
    db.close()


# =====================================================================
# EMS PERSONA resolver + identity routing (AC-06-10/49/50/51)
# =====================================================================


def _profile(db, tenant_id, *, email=None, status_id=None):
    from modules.ems.models import Profile

    p = Profile(tenant_id=tenant_id, email=email or f"{uuid.uuid4().hex[:8]}@e.com",
                full_name="P", status_id=status_id)
    db.add(p)
    db.flush()
    return p


def _grant_persona(db, tenant_id, profile_id, persona_key, scope_id=None):
    from modules.ems.models import PERSONA_GRANT_STAFF, PERSONA_SCOPE_PROJECT, PERSONA_SCOPE_TENANT
    from modules.ems.persona_service import grant_persona

    scope_type = PERSONA_SCOPE_PROJECT if scope_id else PERSONA_SCOPE_TENANT
    return grant_persona(db, tenant_id, profile_id, persona_key, scope_type, scope_id,
                         PERSONA_GRANT_STAFF, commit=False)


def test_ems_persona_resolver_excludes_blocked(client, session_factory):
    """PERSONA pool = profiles holding the bound persona, EXCLUDING blocks_access
    tier-1 statuses (AC-06-51). Identity = profile."""
    from app.models.status import Status
    from modules.ems.persona_repository import PersonaRepository

    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score")

    # A blocks_access status + an active one.
    blocked = Status(entity_type="profile", key="blk", category="BLK", label="Blocked",
                     color="red", tenant_id=DEFAULT_TENANT_ID, blocks_access=True, sort_order=9)
    db.add(blocked)
    db.flush()

    reviewer_persona = PersonaRepository(db).get_persona_by_key(DEFAULT_TENANT_ID, "reviewer")
    assert reviewer_persona is not None  # seeded by EMS install (conftest)

    p_ok = _profile(db, DEFAULT_TENANT_ID)
    p_blocked = _profile(db, DEFAULT_TENANT_ID, status_id=blocked.id)
    _grant_persona(db, DEFAULT_TENANT_ID, p_ok.id, "reviewer")
    _grant_persona(db, DEFAULT_TENANT_ID, p_blocked.id, "reviewer")

    role = ReviewRole(
        tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id, key="rev",
        label="Reviewer", can_review=True, actor_source="PERSONA",
        actor_identity_kind="profile", bound_persona_id=reviewer_persona.id, sort_order=0,
    )
    db.add(role)
    db.flush()
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile", subject_id="pAuthor")
    db.commit()

    cands = ReviewConfigService(db).resolve_role_candidates(DEFAULT_TENANT_ID, config, role, sub, 1)
    # Only the non-blocked profile; identity is "profile".
    assert cands == [("profile", p_ok.id)]
    db.close()


def test_staff_role_produces_user_assignments(client, session_factory):
    """AC-06-10 backend half: a STAFF_ROLE-sourced can_review role produces
    actor_kind=user assignments."""
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score", required=2)
    staff_role, users = _staff_role_with_users(db, DEFAULT_TENANT_ID, n=2)
    role = ReviewRole(
        tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id, key="rev",
        label="Reviewer", can_review=True, actor_source="STAFF_ROLE",
        actor_identity_kind="user", bound_staff_role_id=staff_role.id, sort_order=0,
    )
    db.add(role)
    db.flush()
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, subject_type="profile", subject_id="pX")
    db.commit()
    gid = sub.submission_group_id
    review_allocate(db, DEFAULT_TENANT_ID, {"reviewConfigurationId": config.id},
                    {"trigger.record.id": sub.id})
    db.commit()
    rows = _assignments(db, config.id, gid)
    assert {r.actor_kind for r in rows} == {"user"}
    assert {r.actor_id for r in rows} == {users[0].id, users[1].id}
    db.close()


def test_profile_contact_resolver(client, session_factory):
    db = session_factory()
    p = _profile(db, DEFAULT_TENANT_ID, email="rev@e.com")
    db.commit()
    contact = resolve_actor_contact(db, DEFAULT_TENANT_ID, "profile", p.id)
    assert contact is not None
    assert contact[0] == "rev@e.com"
    db.close()


# =====================================================================
# EMS event review config helper + may_submit (AC-06-49/50)
# =====================================================================


def test_event_review_config_persona_bound_and_may_submit(client, session_factory):
    from modules.ems.persona_repository import PersonaRepository
    from modules.ems.services import EventReviewConfigService, ProjectService

    db = session_factory()
    # Build a minimal event (project) via a template.
    from modules.ems.services import ProjectTemplateService, ProjectTypeService

    ptype = ProjectTypeService(db).create(DEFAULT_TENANT_ID, {"name": _uniq("Conf")})
    template = ProjectTemplateService(db).create(
        DEFAULT_TENANT_ID, {"name": _uniq("Tmpl"), "typeId": ptype.id}
    )
    project = ProjectService(db).create(
        DEFAULT_TENANT_ID, {"title": _uniq("Event"), "templateId": template.id}
    )
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    db.commit()

    config = EventReviewConfigService(db).create_event_review_config(
        DEFAULT_TENANT_ID,
        project_id=project.id,
        submission_form_id=sub_form.id,
        review_form_id=rev_form.id,
        score_field_key="score",
        required_review_count=2,
    )
    db.commit()

    svc = ReviewConfigService(db)
    roles = svc.repo.list_roles(DEFAULT_TENANT_ID, config.id)
    by_key = {r.key: r for r in roles}
    assert by_key["author"].can_submit and by_key["author"].actor_source == "PERSONA"
    assert by_key["reviewer"].can_review and by_key["reviewer"].actor_source == "PERSONA"
    assert by_key["decision_maker"].can_decide

    # A participant (holds the participant persona) MAY submit; a blocked one not.
    participant_persona = PersonaRepository(db).get_persona_by_key(DEFAULT_TENANT_ID, "participant")
    assert by_key["author"].bound_persona_id == participant_persona.id

    p_ok = _profile(db, DEFAULT_TENANT_ID)
    _grant_persona(db, DEFAULT_TENANT_ID, p_ok.id, "participant")
    db.commit()
    assert svc.may_submit(DEFAULT_TENANT_ID, config, "profile", p_ok.id) is True

    # A profile NOT holding the participant persona cannot submit.
    p_no = _profile(db, DEFAULT_TENANT_ID)
    db.commit()
    assert svc.may_submit(DEFAULT_TENANT_ID, config, "profile", p_no.id) is False
    db.close()


def test_blocked_profile_cannot_submit_via_persona_pool(client, session_factory):
    """AC-06-51: a blocked profile holding the participant persona is excluded
    from the can_submit pool (the PERSONA resolver drops blocks_access)."""
    from app.models.status import Status

    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score")
    from modules.ems.persona_repository import PersonaRepository

    participant_persona = PersonaRepository(db).get_persona_by_key(DEFAULT_TENANT_ID, "participant")
    role = ReviewRole(
        tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id, key="author",
        label="Author", can_submit=True, actor_source="PERSONA",
        actor_identity_kind="profile", bound_persona_id=participant_persona.id, sort_order=0,
    )
    db.add(role)
    db.flush()
    blocked = Status(entity_type="profile", key="blk2", category="BLK", label="Blocked",
                     color="red", tenant_id=DEFAULT_TENANT_ID, blocks_access=True, sort_order=9)
    db.add(blocked)
    db.flush()
    p_blocked = _profile(db, DEFAULT_TENANT_ID, status_id=blocked.id)
    _grant_persona(db, DEFAULT_TENANT_ID, p_blocked.id, "participant")
    db.commit()

    assert ReviewConfigService(db).may_submit(DEFAULT_TENANT_ID, config, "profile", p_blocked.id) is False
    db.close()


# =====================================================================
# Failure isolation (AC-06-40)
# =====================================================================


def test_broken_notify_does_not_break_allocation(client, session_factory, monkeypatch):
    db = session_factory()
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    config = _config(db, DEFAULT_TENANT_ID, sub_form, rev_form, score_field_key="score", required=2)
    staff_role, users = _staff_role_with_users(db, DEFAULT_TENANT_ID, n=3)
    role = ReviewRole(
        tenant_id=DEFAULT_TENANT_ID, review_configuration_id=config.id, key="rev",
        label="Reviewer", can_review=True, actor_source="STAFF_ROLE",
        actor_identity_kind="user", bound_staff_role_id=staff_role.id, sort_order=0,
    )
    db.add(role)
    db.flush()
    sub = _submission(db, DEFAULT_TENANT_ID, sub_form, user_id=users[0].id)
    db.commit()
    gid = sub.submission_group_id

    import app.services.email_service as es

    def _boom(self, *a, **k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(es.OutboxEmailService, "enqueue_raw", _boom)

    # Allocation still completes despite the notify blowing up per-assignee.
    out = review_allocate(db, DEFAULT_TENANT_ID, {"reviewConfigurationId": config.id},
                          {"trigger.record.id": sub.id})
    db.commit()
    assert out["assigned"] == 2
    assert len(_assignments(db, config.id, gid)) == 2
    db.close()
