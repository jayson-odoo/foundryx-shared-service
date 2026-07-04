"""Review SURFACE tests (plan sprint-4/06 slice 2) — My Submissions / My Reviews
/ Decisions for BOTH portal (profile) + staff (user) actors + the revisions loop.

Build targets: AC-06-03/05/06/07/08/09/10/43-48/52/53 (backend boundary).

Eager workflows (conftest sets celery_task_always_eager=True) — the seeded
allocate workflow fires inline when a submission moves Draft→review-start.

Setup builds forms through the REAL FormService so each form materializes its own
scoped status graph (Draft→Submitted), then extends the SUBMISSION form's graph
with the review lifecycle (review-start / accepted / rejected / revisions). Portal
+ staff endpoints are exercised over the HTTP client (the real boundary).
"""
import uuid

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.form import FORM_SUBMISSION_ENTITY
from app.models.review import (
    ASSIGNMENT_COMPLETED,
    ASSIGNMENT_PENDING,
    ReviewAssignment,
    ReviewDecision,
)
from app.review_engine.service import ReviewConfigService
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _uniq(prefix):
    return f"{prefix} {uuid.uuid4().hex[:8]}"


# ---- form factories (real FormService → scoped graph materialized) ----


def _demo_user(db, tenant_id=DEFAULT_TENANT_ID):
    from app.models.user import User

    return (
        db.query(User)
        .filter(User.tenant_id == tenant_id, User.email == ACTIVE_EMAIL)
        .first()
    )


def _published_form(db, tenant_id, *, fields, user=None):
    """Create a form via FormService (materializes its scope), set a doc, publish."""
    from app.services.form_service import FormService

    user = user or _demo_user(db, tenant_id)
    svc = FormService(db)
    form = svc.create(tenant_id, user, name=_uniq("Form"))
    doc = {
        "schemaVersion": 1,
        "pages": [{"id": "p1", "title": "P", "sections": [{"id": "s1", "fields": fields}]}],
    }
    svc.update(tenant_id, form.id, fields_set={"draftDefinition"}, draftDefinition=doc)
    svc.publish(tenant_id, form.id, user)
    db.refresh(form)
    return form


def _num_field(key, label="Score"):
    return {"id": f"f_{key}", "type": "number", "key": key, "label": label}


def _text_field(key, label="Title"):
    return {"id": f"f_{key}", "type": "text", "key": key, "label": label}


def _extend_submission_scope(db, tenant_id, form_id):
    """Add the review lifecycle statuses/edges to a submission form's scope (it
    already has Draft + Submitted from FormService.create). Insert the extra
    statuses + edges directly (materialize_scope refuses a second seed). Returns
    {key: Status}."""
    from app.repositories.status_repository import StatusRepository
    from app.models.status import Status
    from app.models.status_transition import StatusTransition

    status_repo = StatusRepository(db)
    existing = {
        s.key: s
        for s in status_repo.list_for_entity(FORM_SUBMISSION_ENTITY, tenant_id, scope_id=form_id)
    }

    def _status(key, label, color, sort, flags):
        row = Status(entity_type=FORM_SUBMISSION_ENTITY, tenant_id=tenant_id, scope_id=form_id,
                     key=key, category=key.upper(), label=label, color=color, sort_order=sort,
                     **flags)
        db.add(row)
        db.flush()
        return row

    extra = {
        "in_review": _status("in_review", "In Review", "blue", 3, {}),
        "accepted": _status("accepted", "Accepted", "green", 4, {"is_terminal": True}),
        "rejected": _status("rejected", "Rejected", "red", 5, {"is_terminal": True}),
        # Frozen (is_active False) so FormService.revise clones it into a NEW
        # Draft revision (the plan's revisions loop, AC-06-09) — an active status
        # would mean "edit this same row" instead.
        "revisions": _status("revisions", "Revisions", "amber", 6, {"is_active": False}),
    }
    by_key = {**existing, **extra}
    # Edges: submitted→in_review, in_review→accepted/rejected/revisions, revisions→submitted.
    def _edge(frm, to, label):
        db.add(StatusTransition(
            tenant_id=tenant_id, entity_type=FORM_SUBMISSION_ENTITY,
            from_status_id=by_key[frm].id, to_status_id=by_key[to].id, label=label,
        ))
    _edge("submitted", "in_review", "Send to review")
    _edge("in_review", "accepted", "Accept")
    _edge("in_review", "rejected", "Reject")
    _edge("in_review", "revisions", "Request revisions")
    _edge("revisions", "submitted", "Resubmit")
    db.flush()
    return by_key


def _config(db, tenant_id, sub_form, rev_form, *, roles, score="score", required=1,
            review_start=None, accepted=None, rejected=None, revisions=None, window_end=None,
            window_start=None):
    return ReviewConfigService(db).create_config(
        tenant_id,
        name=_uniq("Process"),
        form_id=sub_form.id,
        review_form_id=rev_form.id,
        score_field_key=score,
        required_review_count=required,
        review_start_status_id=review_start,
        accepted_status_id=accepted,
        rejected_status_id=rejected,
        revisions_status_id=revisions,
        window_start=window_start,
        window_end=window_end,
        roles=roles,
    )


# ---- profile / persona helpers ----


def _profile(db, tenant_id=DEFAULT_TENANT_ID, *, email=None, status_id=None):
    from modules.ems.models import Profile

    p = Profile(tenant_id=tenant_id, email=email or f"{uuid.uuid4().hex[:8]}@e.com",
                full_name="P", status_id=status_id)
    db.add(p)
    db.flush()
    return p


def _grant(db, tenant_id, profile_id, persona_key, scope_id=None):
    from modules.ems.models import (
        PERSONA_GRANT_STAFF, PERSONA_SCOPE_PROJECT, PERSONA_SCOPE_TENANT,
    )
    from modules.ems.persona_service import grant_persona

    scope_type = PERSONA_SCOPE_PROJECT if scope_id else PERSONA_SCOPE_TENANT
    grant_persona(db, tenant_id, profile_id, persona_key, scope_type, scope_id,
                  PERSONA_GRANT_STAFF, commit=False)


def _portal_token(db, profile):
    from modules.ems.portal_auth_service import PortalAuthService

    return PortalAuthService(db).issue_token(profile)


def _ph(token):
    return {"Authorization": f"Bearer {token}"}


def _staff_login(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return _ph(res.json()["access_token"])


# Persona-bound config role-set: author=participant (can_submit), reviewer=reviewer
# (can_review), decider=decision_maker (can_decide) — all PERSONA / profile kind.
def _persona_roles(db):
    from modules.ems.persona_repository import PersonaRepository

    repo = PersonaRepository(db)
    part = repo.get_persona_by_key(DEFAULT_TENANT_ID, "participant")
    rev = repo.get_persona_by_key(DEFAULT_TENANT_ID, "reviewer")
    dec = repo.get_persona_by_key(DEFAULT_TENANT_ID, "decision_maker")
    return [
        {"key": "author", "label": "Author", "can_submit": True, "actor_source": "PERSONA",
         "actor_identity_kind": "profile", "bound_persona_id": part.id, "sort_order": 0},
        {"key": "reviewer", "label": "Reviewer", "can_review": True, "actor_source": "PERSONA",
         "actor_identity_kind": "profile", "bound_persona_id": rev.id, "sort_order": 1},
        {"key": "decider", "label": "Chair", "can_decide": True, "actor_source": "PERSONA",
         "actor_identity_kind": "profile", "bound_persona_id": dec.id, "sort_order": 2},
    ]



# =====================================================================
# Portal submit (AC-06-03/31/41/51/52)
# =====================================================================


def _full_setup(db, *, required=1, window_end=None, window_start=None):
    """A submission form (title) + review form (score) + extended scope + a
    persona-bound config with the allocate workflow seeded. Returns a dict of the
    ids the tests need (avoids DetachedInstanceError after the session closes)."""
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    by_key = _extend_submission_scope(db, DEFAULT_TENANT_ID, sub_form.id)
    config = _config(
        db, DEFAULT_TENANT_ID, sub_form, rev_form, roles=_persona_roles(db),
        required=required,
        review_start=by_key["in_review"].id,
        accepted=by_key["accepted"].id,
        rejected=by_key["rejected"].id,
        revisions=by_key["revisions"].id,
        window_end=window_end, window_start=window_start,
    )
    db.flush()
    return {
        "sub_form_id": sub_form.id,
        "rev_form_id": rev_form.id,
        "config_id": config.id,
        "in_review_id": by_key["in_review"].id,
        "accepted_id": by_key["accepted"].id,
        "rejected_id": by_key["rejected"].id,
        "revisions_id": by_key["revisions"].id,
    }


def _config_obj(db, config_id):
    return ReviewConfigService(db).repo.get_config(DEFAULT_TENANT_ID, config_id)


def _drive_to_review(db, group_id, in_review_id):
    """Move a group's current submission Submitted→In Review (fires allocate)."""
    from app.models.form import FormSubmission
    from app.services import status_machine

    sub = (
        db.query(FormSubmission)
        .filter_by(submission_group_id=group_id, is_current=True)
        .first()
    )
    status_machine.transition(db, FORM_SUBMISSION_ENTITY, sub, in_review_id,
                              tenant_id=DEFAULT_TENANT_ID)
    db.commit()


def test_portal_submit_captures_profile_author_and_allocates(client, session_factory):
    db = session_factory()
    s = _full_setup(db, required=2)
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    r1 = _profile(db); _grant(db, DEFAULT_TENANT_ID, r1.id, "reviewer")
    r2 = _profile(db); _grant(db, DEFAULT_TENANT_ID, r2.id, "reviewer")
    db.commit()
    author_id, r1_id, r2_id = author.id, r1.id, r2.id
    token = _portal_token(db, author)
    db.close()

    res = client.post(
        f"/portal/review-configs/{s['config_id']}/submissions",
        json={"answers": {"title": "My paper"}}, headers=_ph(token),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["statusLabel"] == "Submitted"  # Draft→Submitted fired
    group_id = body["groupId"]

    from app.models.form import FormSubmission
    db = session_factory()
    sub = db.query(FormSubmission).filter_by(submission_group_id=group_id).first()
    assert sub.subject_type == "profile" and sub.subject_id == author_id
    _drive_to_review(db, group_id, s["in_review_id"])
    rows = db.query(ReviewAssignment).filter_by(reviewed_submission_group_id=group_id).all()
    assert {(a.actor_kind, a.actor_id) for a in rows} == {("profile", r1_id), ("profile", r2_id)}
    db.close()


def test_portal_submit_rejects_non_submitter(client, session_factory):
    from modules.ems.models import PERSONA_GRANT_STAFF, PERSONA_SCOPE_TENANT
    from modules.ems.persona_service import PersonaService, grant_persona

    db = session_factory()
    s = _full_setup(db)
    # A profile WITHOUT the participant persona but holding forms.submit (so it
    # reaches the endpoint), yet may_submit=False.
    psvc = PersonaService(db)
    persona = psvc.create(DEFAULT_TENANT_ID,
                          {"key": _uniq("p").replace(" ", "_"), "label": "Bystander"})
    db.flush()
    psvc.set_permissions(DEFAULT_TENANT_ID, persona.id, ["forms.submit"])
    nope = _profile(db)
    grant_persona(db, DEFAULT_TENANT_ID, nope.id, persona.key, PERSONA_SCOPE_TENANT, None,
                  PERSONA_GRANT_STAFF, commit=False)
    db.commit()
    token = _portal_token(db, nope)
    db.close()

    res = client.post(f"/portal/review-configs/{s['config_id']}/submissions",
                      json={"answers": {"title": "x"}}, headers=_ph(token))
    assert res.status_code == 403, res.text


def test_portal_submit_window_closed_409(client, session_factory):
    from datetime import datetime, timedelta, timezone

    db = session_factory()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    s = _full_setup(db, window_end=past)
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    db.commit()
    token = _portal_token(db, author)
    db.close()

    res = client.post(f"/portal/review-configs/{s['config_id']}/submissions",
                      json={"answers": {"title": "x"}}, headers=_ph(token))
    assert res.status_code == 409, res.text


def test_portal_submit_blocked_profile_refused(client, session_factory):
    """AC-06-51 — a blocks_access tier-1 profile status refuses submit."""
    from app.models.status import Status

    db = session_factory()
    s = _full_setup(db)
    blocked = Status(entity_type="profile", key="blk", category="BLK", label="Blocked",
                     color="red", tenant_id=DEFAULT_TENANT_ID, blocks_access=True, sort_order=9)
    db.add(blocked); db.flush()
    author = _profile(db, status_id=blocked.id)
    _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    db.commit()
    token = _portal_token(db, author)
    db.close()

    res = client.post(f"/portal/review-configs/{s['config_id']}/submissions",
                      json={"answers": {"title": "x"}}, headers=_ph(token))
    assert res.status_code == 403, res.text


def test_portal_my_submissions_hides_reviews_shows_decision(client, session_factory):
    """AC-06-08/43/52 — My Submissions shows status + decision + feedback, NEVER
    raw reviews/scores; multiple groups per author each listed."""
    from app.services.form_service import FormService

    db = session_factory()
    s = _full_setup(db, required=1)
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    db.commit()
    token = _portal_token(db, author)
    author_id = author.id

    s1 = FormService(db).submit(DEFAULT_TENANT_ID, s["sub_form_id"], None, {"title": "A"},
                                subject_type="profile", subject_id=author_id)
    s2 = FormService(db).submit(DEFAULT_TENANT_ID, s["sub_form_id"], None, {"title": "B"},
                                subject_type="profile", subject_id=author_id)
    g1, g2 = s1.submission_group_id, s2.submission_group_id
    _drive_to_review(db, g1, s["in_review_id"])
    ReviewConfigService(db).decide_and_transition(
        DEFAULT_TENANT_ID, _config_obj(db, s["config_id"]), g1, 1, "profile", "decider1",
        "ACCEPTED", "Nice work")
    db.commit()
    db.close()

    res = client.get("/portal/submissions", headers=_ph(token))
    assert res.status_code == 200, res.text
    items = {i["groupId"]: i for i in res.json()}
    assert g1 in items and g2 in items  # AC-06-52
    decided = items[g1]
    assert decided["decision"] == "ACCEPTED"
    assert decided["feedbackText"] == "Nice work"
    # No raw reviews/scores in the author payload (AC-06-08).
    assert "reviews" not in decided and "averageScore" not in decided


# =====================================================================
# Submit-options discovery (AC-06-03) — eligible configs with ZERO submissions
# =====================================================================


def test_submit_options_lists_eligible_config_with_no_submissions(client, session_factory):
    """AC-06-03 — a participant with a can_submit persona role + an open window
    sees the config in submit-options BEFORE submitting anything."""
    db = session_factory()
    s = _full_setup(db)
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    db.commit()
    token = _portal_token(db, author)
    config_id = s["config_id"]
    db.close()

    res = client.get("/portal/submit-options", headers=_ph(token))
    assert res.status_code == 200, res.text
    items = res.json()
    entry = next(i for i in items if i["config_id"] == config_id)
    assert entry["window_state"] == "open"
    assert entry["can_submit_now"] is True
    assert entry["submission_form_id"] == s["sub_form_id"]
    assert entry["name"]


def test_submit_options_excludes_non_submitter(client, session_factory):
    """A reviewer-only profile (no can_submit role) sees no submit option for the
    config — even though it holds my_reviews and could reach the endpoint via a
    forms.submit grant on another persona."""
    from modules.ems.models import PERSONA_GRANT_STAFF, PERSONA_SCOPE_TENANT
    from modules.ems.persona_service import PersonaService, grant_persona

    db = session_factory()
    s = _full_setup(db)
    # A persona holding forms.submit (reaches the endpoint) but NOT a can_submit
    # role on the config → excluded.
    psvc = PersonaService(db)
    persona = psvc.create(DEFAULT_TENANT_ID,
                          {"key": _uniq("p").replace(" ", "_"), "label": "Bystander"})
    db.flush()
    psvc.set_permissions(DEFAULT_TENANT_ID, persona.id, ["forms.submit"])
    nope = _profile(db)
    grant_persona(db, DEFAULT_TENANT_ID, nope.id, persona.key, PERSONA_SCOPE_TENANT, None,
                  PERSONA_GRANT_STAFF, commit=False)
    db.commit()
    token = _portal_token(db, nope)
    config_id = s["config_id"]
    db.close()

    res = client.get("/portal/submit-options", headers=_ph(token))
    assert res.status_code == 200, res.text
    assert all(i["config_id"] != config_id for i in res.json())


def test_submit_options_window_states(client, session_factory):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    # Closed window.
    db = session_factory()
    s_closed = _full_setup(db, window_end=now - timedelta(hours=1))
    a1 = _profile(db); _grant(db, DEFAULT_TENANT_ID, a1.id, "participant")
    db.commit()
    t1 = _portal_token(db, a1)
    closed_id = s_closed["config_id"]
    db.close()
    entry = next(i for i in client.get("/portal/submit-options", headers=_ph(t1)).json()
                 if i["config_id"] == closed_id)
    assert entry["window_state"] == "closed" and entry["can_submit_now"] is False

    # Not-yet-open window.
    db = session_factory()
    s_future = _full_setup(db, window_start=now + timedelta(hours=1))
    a2 = _profile(db); _grant(db, DEFAULT_TENANT_ID, a2.id, "participant")
    db.commit()
    t2 = _portal_token(db, a2)
    future_id = s_future["config_id"]
    db.close()
    entry = next(i for i in client.get("/portal/submit-options", headers=_ph(t2)).json()
                 if i["config_id"] == future_id)
    assert entry["window_state"] == "not_yet_open" and entry["can_submit_now"] is False


def test_submit_options_blocked_profile_excluded_from_persona_pool(client, session_factory):
    """AC-06-51 — a blocks_access tier-1 profile is not a valid PERSONA-pool
    submitter, so the config never appears in submit-options (the pool resolver
    excludes blocked profiles; can_submit_now would be False even if it did)."""
    from app.models.status import Status

    db = session_factory()
    s = _full_setup(db)
    blocked = Status(entity_type="profile", key="blk2", category="BLK", label="Blocked",
                     color="red", tenant_id=DEFAULT_TENANT_ID, blocks_access=True, sort_order=9)
    db.add(blocked); db.flush()
    author = _profile(db, status_id=blocked.id)
    _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    db.commit()
    token = _portal_token(db, author)
    config_id = s["config_id"]
    db.close()

    items = client.get("/portal/submit-options", headers=_ph(token)).json()
    assert all(i["config_id"] != config_id for i in items)


# =====================================================================
# Submission detail (AC-06-09) — author-only, carries answers for revise
# =====================================================================


def test_submission_detail_returns_answers_for_author(client, session_factory):
    from app.services.form_service import FormService

    db = session_factory()
    s = _full_setup(db)
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    db.commit()
    token = _portal_token(db, author)
    sub = FormService(db).submit(DEFAULT_TENANT_ID, s["sub_form_id"], None, {"title": "Keep me"},
                                 subject_type="profile", subject_id=author.id)
    db.commit()
    gid = sub.submission_group_id
    db.close()

    res = client.get(f"/portal/submissions/{gid}", headers=_ph(token))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["answers"]["title"] == "Keep me"
    assert body["group_id"] == gid
    assert body["form_id"] == s["sub_form_id"]
    # Author-visible: status present, no raw reviews/scores leaked (AC-06-08).
    assert "status_label" in body
    assert "reviews" not in body and "average_score" not in body


def test_submission_detail_404_for_non_author(client, session_factory):
    from app.services.form_service import FormService

    db = session_factory()
    s = _full_setup(db)
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    stranger = _profile(db); _grant(db, DEFAULT_TENANT_ID, stranger.id, "participant")
    db.commit()
    sub = FormService(db).submit(DEFAULT_TENANT_ID, s["sub_form_id"], None, {"title": "Secret"},
                                 subject_type="profile", subject_id=author.id)
    db.commit()
    gid = sub.submission_group_id
    stranger_token = _portal_token(db, stranger)
    db.close()

    res = client.get(f"/portal/submissions/{gid}", headers=_ph(stranger_token))
    assert res.status_code == 404, res.text


def test_submission_detail_404_cross_tenant(client, session_factory):
    from app.models.status import Status
    from app.models.tenant import Tenant
    from app.services.form_service import FormService
    from modules.ems.bootstrap import _seed_personas

    db = session_factory()
    s = _full_setup(db)
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    db.commit()
    sub = FormService(db).submit(DEFAULT_TENANT_ID, s["sub_form_id"], None, {"title": "x"},
                                 subject_type="profile", subject_id=author.id)
    db.commit()
    gid = sub.submission_group_id

    active = db.query(Status).filter_by(
        entity_type="tenant", tenant_id=None, key="active").first()
    other = Tenant(slug=_uniq("t").replace(" ", "-")[:30], name="Other",
                   status_id=active.id if active else None)
    db.add(other); db.flush()
    _seed_personas(db, other.id)
    other_profile = _profile(db, tenant_id=other.id)
    _grant(db, other.id, other_profile.id, "participant")
    db.commit()
    pt = _portal_token(db, other_profile)
    db.close()

    assert client.get(f"/portal/submissions/{gid}", headers=_ph(pt)).status_code == 404


# =====================================================================
# My Reviews — two-pane, isolation, draft, submit, live average
# (AC-06-05/06/44/48)
# =====================================================================


def _submit_and_allocate(db, sub_form_id, in_review_id, author_id, *, title="Paper"):
    """Author submits → move to in_review → allocate fires → return group_id."""
    from app.services.form_service import FormService

    sub = FormService(db).submit(DEFAULT_TENANT_ID, sub_form_id, None, {"title": title},
                                 subject_type="profile", subject_id=author_id)
    gid = sub.submission_group_id
    _drive_to_review(db, gid, in_review_id)
    return gid


def test_my_reviews_two_pane_isolated_draft_submit_average(client, session_factory):
    db = session_factory()
    s = _full_setup(db, required=2)
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    r1 = _profile(db); _grant(db, DEFAULT_TENANT_ID, r1.id, "reviewer")
    r2 = _profile(db); _grant(db, DEFAULT_TENANT_ID, r2.id, "reviewer")
    db.commit()
    group_id = _submit_and_allocate(db, s["sub_form_id"], s["in_review_id"], author.id)
    t1, t2 = _portal_token(db, r1), _portal_token(db, r2)
    config_id = s["config_id"]
    db.close()

    q1 = client.get("/portal/reviews", headers=_ph(t1)).json()
    assert len(q1) == 1
    a1_id = q1[0]["assignmentId"]
    assert q1[0]["status"] == ASSIGNMENT_PENDING

    tp = client.get(f"/portal/reviews/{a1_id}", headers=_ph(t1))
    assert tp.status_code == 200, tp.text
    pane = tp.json()
    assert pane["submission"]["answers"]["title"] == "Paper"
    assert pane["reviewForm"] is not None
    assert pane["reviewDraft"] is None

    # r2 cannot open r1's assignment (reviewer isolation / identity → 404).
    assert client.get(f"/portal/reviews/{a1_id}", headers=_ph(t2)).status_code == 404

    d = client.post(f"/portal/reviews/{a1_id}/draft", json={"answers": {"score": 7}}, headers=_ph(t1))
    assert d.status_code == 200, d.text
    resumed = client.get(f"/portal/reviews/{a1_id}", headers=_ph(t1)).json()
    assert resumed["reviewDraft"]["answers"]["score"] == 7

    sub = client.post(f"/portal/reviews/{a1_id}/submit", json={"answers": {"score": 8}}, headers=_ph(t1))
    assert sub.status_code == 200, sub.text
    assert sub.json()["status"] == ASSIGNMENT_COMPLETED

    # Average updates live (AC-06-06): only r1 done → avg == 8.
    db = session_factory()
    assert ReviewConfigService(db).average_score(
        DEFAULT_TENANT_ID, _config_obj(db, config_id), group_id, 1) == 8.0
    db.close()
    # r2 grades 6 → avg == 7.
    q2 = client.get("/portal/reviews", headers=_ph(t2)).json()
    a2_id = q2[0]["assignmentId"]
    client.post(f"/portal/reviews/{a2_id}/submit", json={"answers": {"score": 6}}, headers=_ph(t2))
    db = session_factory()
    assert ReviewConfigService(db).average_score(
        DEFAULT_TENANT_ID, _config_obj(db, config_id), group_id, 1) == 7.0
    db.close()


# =====================================================================
# Decisions — partial average, ready flag, early decide, first-wins
# (AC-06-07/34/45)
# =====================================================================


def test_decisions_live_average_ready_and_first_wins(client, session_factory):
    db = session_factory()
    s = _full_setup(db, required=2)
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    r1 = _profile(db); _grant(db, DEFAULT_TENANT_ID, r1.id, "reviewer")
    r2 = _profile(db); _grant(db, DEFAULT_TENANT_ID, r2.id, "reviewer")
    d1 = _profile(db); _grant(db, DEFAULT_TENANT_ID, d1.id, "decision_maker")
    d2 = _profile(db); _grant(db, DEFAULT_TENANT_ID, d2.id, "decision_maker")
    db.commit()
    group_id = _submit_and_allocate(db, s["sub_form_id"], s["in_review_id"], author.id)
    t1 = _portal_token(db, r1)
    td1, td2 = _portal_token(db, d1), _portal_token(db, d2)
    accepted_id = s["accepted_id"]
    db.close()

    # One review completed → partial average, NOT ready (required=2).
    a1 = client.get("/portal/reviews", headers=_ph(t1)).json()[0]["assignmentId"]
    client.post(f"/portal/reviews/{a1}/submit", json={"answers": {"score": 9}}, headers=_ph(t1))

    dec = client.get("/portal/decisions", headers=_ph(td1))
    assert dec.status_code == 200, dec.text
    item = next(i for i in dec.json() if i["groupId"] == group_id)
    assert item["averageScore"] == 9.0
    assert item["completedCount"] == 1 and item["ready"] is False
    assert len(item["reviews"]) == 1 and item["reviews"][0]["score"] == 9.0  # AC-06-07

    # Early decision allowed (before ready) — first decider wins.
    win = client.post(f"/portal/decisions/{group_id}/decide",
                      json={"decision": "ACCEPTED", "feedback": "ok"}, headers=_ph(td1))
    assert win.status_code == 200, win.text
    assert win.json()["decision"] == "ACCEPTED"

    # Second concurrent decider = 409, no double transition.
    lose = client.post(f"/portal/decisions/{group_id}/decide",
                       json={"decision": "REJECTED"}, headers=_ph(td2))
    assert lose.status_code == 409, lose.text

    db = session_factory()
    from app.models.form import FormSubmission
    sub = db.query(FormSubmission).filter_by(submission_group_id=group_id, is_current=True).first()
    assert sub.status_id == accepted_id
    assert db.query(ReviewDecision).filter_by(reviewed_submission_group_id=group_id).count() == 1
    db.close()


# =====================================================================
# Revisions loop (AC-06-09)
# =====================================================================


def test_revisions_loop_reallocates_prior_reviewers(client, session_factory):
    from app.services.form_service import FormService

    db = session_factory()
    s = _full_setup(db, required=2)
    FormService(db).update(DEFAULT_TENANT_ID, s["sub_form_id"],
                           fields_set={"allowRevisions"}, allowRevisions=True)
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    r1 = _profile(db); _grant(db, DEFAULT_TENANT_ID, r1.id, "reviewer")
    r2 = _profile(db); _grant(db, DEFAULT_TENANT_ID, r2.id, "reviewer")
    d1 = _profile(db); _grant(db, DEFAULT_TENANT_ID, d1.id, "decision_maker")
    db.commit()
    group_id = _submit_and_allocate(db, s["sub_form_id"], s["in_review_id"], author.id)
    t_author = _portal_token(db, author)
    td1 = _portal_token(db, d1)
    r1_id, r2_id, in_review_id = r1.id, r2.id, s["in_review_id"]
    db.close()

    # Decision-maker requests revisions → submission lands on revisions_status.
    win = client.post(f"/portal/decisions/{group_id}/decide",
                      json={"decision": "REVISIONS", "feedback": "fix section 2"}, headers=_ph(td1))
    assert win.status_code == 200, win.text

    sub_item = next(i for i in client.get("/portal/submissions", headers=_ph(t_author)).json()
                    if i["groupId"] == group_id)
    assert sub_item["canRevise"] is True
    rev = client.post(f"/portal/submissions/{group_id}/revise", headers=_ph(t_author))
    assert rev.status_code == 200, rev.text
    new_sub_id = rev.json()["submission_id"]
    assert rev.json()["revision_number"] == 2

    rs = client.post(f"/portal/submissions/{new_sub_id}/resubmit",
                     json={"answers": {"title": "Paper v2"}}, headers=_ph(t_author))
    assert rs.status_code == 200, rs.text
    # Drive the resubmitted revision into review-start → re-allocate.
    db = session_factory()
    _drive_to_review(db, group_id, in_review_id)
    rows = db.query(ReviewAssignment).filter_by(
        reviewed_submission_group_id=group_id, revision_number=2).all()
    assert {(a.actor_kind, a.actor_id) for a in rows} == {("profile", r1_id), ("profile", r2_id)}
    db.close()


def test_revise_blocked_when_not_at_revisions(client, session_factory):
    from app.services.form_service import FormService

    db = session_factory()
    s = _full_setup(db)
    FormService(db).update(DEFAULT_TENANT_ID, s["sub_form_id"],
                           fields_set={"allowRevisions"}, allowRevisions=True)
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    db.commit()
    t_author = _portal_token(db, author)
    sub = FormService(db).submit(DEFAULT_TENANT_ID, s["sub_form_id"], None, {"title": "x"},
                                 subject_type="profile", subject_id=author.id)
    db.commit()
    gid = sub.submission_group_id
    db.close()

    res = client.post(f"/portal/submissions/{gid}/revise", headers=_ph(t_author))
    assert res.status_code == 409, res.text


# =====================================================================
# Identity routing (AC-06-10/47) — staff surfaces + cross-world 404
# =====================================================================


def test_identity_routing_user_assignment_staff_only(client, session_factory):
    """A STAFF_ROLE-sourced can_review role yields user assignments: reachable on
    the staff surface, 404 on the portal (and a profile vice-versa)."""
    from app.models.role import Role
    from app.models.user import User, UserStatus
    from app.security import hash_password

    db = session_factory()
    s = _full_setup(db, required=1)
    staff_role = Role(tenant_id=DEFAULT_TENANT_ID, name=_uniq("Judges"), is_system=False)
    staff_role.permissions = []
    db.add(staff_role); db.flush()
    admin = db.query(Role).filter_by(tenant_id=DEFAULT_TENANT_ID, name="Admin").first()
    judge = User(tenant_id=DEFAULT_TENANT_ID, email=f"judge-{uuid.uuid4().hex[:5]}@e.com",
                 password=hash_password("Passw0rd!"), name="Judge",
                 status=UserStatus.ACTIVE.value)
    # The judge holds BOTH the bound staff role (→ assignment) and Admin (→ the
    # reviews.grade perm to reach the staff surface).
    judge.roles = [staff_role, admin]
    db.add(judge); db.flush()
    ReviewConfigService(db).update_config(
        DEFAULT_TENANT_ID, s["config_id"], fields_set={"roles"},
        roles=_persona_roles(db) + [
            {"key": "staffrev", "label": "Staff Reviewer", "can_review": True,
             "actor_source": "STAFF_ROLE", "actor_identity_kind": "user",
             "bound_staff_role_id": staff_role.id, "sort_order": 9},
        ],
    )
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    db.commit()
    group_id = _submit_and_allocate(db, s["sub_form_id"], s["in_review_id"], author.id)
    rows = db.query(ReviewAssignment).filter_by(
        reviewed_submission_group_id=group_id, actor_kind="user").all()
    assert len(rows) == 1 and rows[0].actor_id == judge.id
    assignment_id = rows[0].id
    judge_email = judge.email
    db.close()

    # Staff login as the judge → staff My Reviews lists it; portal 404s it.
    res = client.post("/auth/login", json={"email": judge_email, "password": "Passw0rd!"})
    assert res.status_code == 200, res.text
    sh = _ph(res.json()["access_token"])
    staff_q = client.get("/reviews/my-reviews", headers=sh).json()
    assert any(r["assignmentId"] == assignment_id for r in staff_q)
    assert client.get(f"/reviews/assignments/{assignment_id}", headers=sh).status_code == 200

    # A PROFILE actor cannot reach a user-kind assignment on the portal (404).
    db = session_factory()
    stranger = _profile(db); _grant(db, DEFAULT_TENANT_ID, stranger.id, "reviewer")
    db.commit()
    pt = _portal_token(db, stranger)
    db.close()
    assert client.get(f"/portal/reviews/{assignment_id}", headers=_ph(pt)).status_code == 404


# =====================================================================
# Tenant isolation (AC-06-57)
# =====================================================================


def test_tenant_isolation_cross_tenant_assignment_404(client, session_factory):
    """A profile of tenant A can't read tenant B's assignment (404)."""
    from app.models.status import Status
    from app.models.tenant import Tenant

    db = session_factory()
    s = _full_setup(db, required=1)
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    r1 = _profile(db); _grant(db, DEFAULT_TENANT_ID, r1.id, "reviewer")
    db.commit()
    group_id = _submit_and_allocate(db, s["sub_form_id"], s["in_review_id"], author.id)
    a = db.query(ReviewAssignment).filter_by(reviewed_submission_group_id=group_id).first()
    assignment_id = a.id

    # A profile in ANOTHER tenant (tenant needs an active status_id). Seed that
    # tenant's personas so the profile DOES hold my_reviews.read — then the 404
    # proves the assignment itself is invisible cross-tenant (not merely a perm
    # block).
    from modules.ems.bootstrap import _seed_personas

    active = db.query(Status).filter_by(
        entity_type="tenant", tenant_id=None, key="active").first()
    other = Tenant(slug=_uniq("t").replace(" ", "-")[:30], name="Other",
                   status_id=active.id if active else None)
    db.add(other); db.flush()
    _seed_personas(db, other.id)
    other_profile = _profile(db, tenant_id=other.id)
    _grant(db, other.id, other_profile.id, "reviewer")
    db.commit()
    pt = _portal_token(db, other_profile)
    db.close()

    assert client.get(f"/portal/reviews/{assignment_id}", headers=_ph(pt)).status_code == 404


# =====================================================================
# Global event/context filter (AC-06-25) — contextId narrows every surface
# =====================================================================


def _full_setup_in_context(db, *, context_id, required=1):
    """A full review setup whose config is bound to ``context_id`` (an event/
    project scope). Mirrors ``_full_setup`` but stamps context_type/context_id so
    the surfaces' contextId filter has something to match (AC-06-25)."""
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    by_key = _extend_submission_scope(db, DEFAULT_TENANT_ID, sub_form.id)
    config = ReviewConfigService(db).create_config(
        DEFAULT_TENANT_ID,
        name=_uniq("Process"),
        form_id=sub_form.id,
        review_form_id=rev_form.id,
        score_field_key="score",
        required_review_count=required,
        context_type="project",
        context_id=context_id,
        review_start_status_id=by_key["in_review"].id,
        accepted_status_id=by_key["accepted"].id,
        rejected_status_id=by_key["rejected"].id,
        revisions_status_id=by_key["revisions"].id,
        roles=_persona_roles(db),
    )
    db.flush()
    return {
        "sub_form_id": sub_form.id,
        "config_id": config.id,
        "in_review_id": by_key["in_review"].id,
    }


def test_context_id_narrows_all_surfaces_and_unfiltered_shows_both(client, session_factory):
    """AC-06-25/52 — a profile with submissions/assignments/decisions across TWO
    event contexts: each list filtered by ``contextId`` returns only that event's
    items; unfiltered returns BOTH (two groups across contexts listed)."""
    db = session_factory()
    sA = _full_setup_in_context(db, context_id="proj-A", required=1)
    sB = _full_setup_in_context(db, context_id="proj-B", required=1)

    # The AUTHOR participates in both contexts (drives My Submissions + submit-
    # options). A separate ACTOR reviews + decides in both contexts (the author is
    # always excluded from reviewing its own submission, so the reviewer/decider
    # must be a different profile).
    author = _profile(db)
    _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    actor = _profile(db)
    _grant(db, DEFAULT_TENANT_ID, actor.id, "reviewer")
    _grant(db, DEFAULT_TENANT_ID, actor.id, "decision_maker")
    db.commit()
    author_id = author.id
    author_token = _portal_token(db, author)
    actor_token = _portal_token(db, actor)

    gA = _submit_and_allocate(db, sA["sub_form_id"], sA["in_review_id"], author_id, title="Paper A")
    gB = _submit_and_allocate(db, sB["sub_form_id"], sB["in_review_id"], author_id, title="Paper B")
    db.commit()
    db.close()

    # --- My Submissions (author) ---
    all_subs = client.get("/portal/submissions", headers=_ph(author_token)).json()
    sub_groups = {i["groupId"] for i in all_subs}
    assert gA in sub_groups and gB in sub_groups  # AC-06-52 — both groups unfiltered
    # Each row carries its config's contextId so the FE can label the context
    # per row when unfiltered (AC-06-25).
    row_ctx = {i["groupId"]: i["contextId"] for i in all_subs}
    assert row_ctx[gA] == "proj-A" and row_ctx[gB] == "proj-B"

    a_only = client.get("/portal/submissions?contextId=proj-A", headers=_ph(author_token)).json()
    assert {i["groupId"] for i in a_only} == {gA}
    b_only = client.get("/portal/submissions?contextId=proj-B", headers=_ph(author_token)).json()
    assert {i["groupId"] for i in b_only} == {gB}

    # --- My Reviews (actor) ---
    all_rev = client.get("/portal/reviews", headers=_ph(actor_token)).json()
    rev_groups = {i["groupId"] for i in all_rev}
    assert gA in rev_groups and gB in rev_groups
    a_rev = client.get("/portal/reviews?contextId=proj-A", headers=_ph(actor_token)).json()
    assert {i["groupId"] for i in a_rev} == {gA}

    # --- Decisions (actor) ---
    all_dec = client.get("/portal/decisions", headers=_ph(actor_token)).json()
    dec_groups = {i["groupId"] for i in all_dec}
    assert gA in dec_groups and gB in dec_groups
    b_dec = client.get("/portal/decisions?contextId=proj-B", headers=_ph(actor_token)).json()
    assert {i["groupId"] for i in b_dec} == {gB}

    # --- submit-options (author) ---
    all_opt = client.get("/portal/submit-options", headers=_ph(author_token)).json()
    opt_ctx = {i["config_id"]: i.get("context_id") for i in all_opt}
    assert sA["config_id"] in opt_ctx and sB["config_id"] in opt_ctx
    a_opt = client.get("/portal/submit-options?contextId=proj-A", headers=_ph(author_token)).json()
    assert {i["config_id"] for i in a_opt} == {sA["config_id"]}


def test_create_event_review_config_persists_context(session_factory):
    """The EMS event-review config helper stamps context_type='project' +
    context_id=<project_id> (AC-06-25/49)."""
    from modules.ems.services import EventReviewConfigService

    db = session_factory()
    # A minimal published project + forms.
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    project = _make_project(db)
    db.commit()

    config = EventReviewConfigService(db).create_event_review_config(
        DEFAULT_TENANT_ID,
        project_id=project.id,
        submission_form_id=sub_form.id,
        review_form_id=rev_form.id,
        score_field_key="score",
    )
    assert config.context_type == "project"
    assert config.context_id == project.id
    db.close()


def _make_project(db, tenant_id=DEFAULT_TENANT_ID):
    """A minimal EMS project (type→template→project) for context tests."""
    from modules.ems.models import Project, ProjectTemplate, ProjectType

    ptype = ProjectType(tenant_id=tenant_id, name=_uniq("Type"))
    db.add(ptype); db.flush()
    tmpl = ProjectTemplate(tenant_id=tenant_id, type_id=ptype.id, name=_uniq("Tmpl"))
    db.add(tmpl); db.flush()
    project = Project(tenant_id=tenant_id, template_id=tmpl.id, type_id=ptype.id,
                      title=_uniq("Event"))
    db.add(project); db.flush()
    return project


# =====================================================================
# Cluster-G referenceability (AC-06-53)
# =====================================================================


def test_accepted_submission_resolvable_by_group(client, session_factory):
    from app.review_engine.surfaces import ReviewSurfaceService
    from app.services.form_service import FormService

    db = session_factory()
    s = _full_setup(db, required=1)
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    db.commit()
    author_id = author.id
    sub = FormService(db).submit(DEFAULT_TENANT_ID, s["sub_form_id"], None, {"title": "Final"},
                                 subject_type="profile", subject_id=author_id)
    gid = sub.submission_group_id
    _drive_to_review(db, gid, s["in_review_id"])
    # Not accepted yet → None.
    assert ReviewSurfaceService(db).resolve_accepted_submission(DEFAULT_TENANT_ID, gid) is None
    ReviewConfigService(db).decide_and_transition(
        DEFAULT_TENANT_ID, _config_obj(db, s["config_id"]), gid, 1, "profile", "decider1", "ACCEPTED")
    db.commit()
    ref = ReviewSurfaceService(db).resolve_accepted_submission(DEFAULT_TENANT_ID, gid)
    assert ref is not None
    assert ref["author_kind"] == "profile" and ref["author_id"] == author_id
    assert ref["group_id"] == gid
    db.close()


# =====================================================================
# AC-06-22 sub-path — a PROFILE actor BOUND to a review role (EXPLICIT) auto-
# acquires the matching system persona → the portal surface key, so an EXPLICIT/
# RULE/STAFF_ROLE-sourced reviewer/decider/submitter can SEE their own work.
# =====================================================================


def _explicit_roles(*, reviewer_id=None, decider_id=None, submitter_id=None):
    """A config role-set with EXPLICIT profile actors per capability (named, not
    persona-pooled). Each role names one profile actor."""
    roles = []
    if submitter_id:
        roles.append({"key": "author", "label": "Author", "can_submit": True,
                      "actor_source": "EXPLICIT", "actor_identity_kind": "profile",
                      "sort_order": 0, "actors": [{"actor_kind": "profile", "actor_id": submitter_id}]})
    if reviewer_id:
        roles.append({"key": "reviewer", "label": "Reviewer", "can_review": True,
                      "actor_source": "EXPLICIT", "actor_identity_kind": "profile",
                      "sort_order": 1, "actors": [{"actor_kind": "profile", "actor_id": reviewer_id}]})
    if decider_id:
        roles.append({"key": "decider", "label": "Chair", "can_decide": True,
                      "actor_source": "EXPLICIT", "actor_identity_kind": "profile",
                      "sort_order": 2, "actors": [{"actor_kind": "profile", "actor_id": decider_id}]})
    return roles


def _explicit_setup(db, *, roles, required=1):
    """A submission + review form + extended scope + a config with EXPLICIT roles
    (no allocate-workflow dependence on personas). Returns the id dict."""
    sub_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_text_field("title")])
    rev_form = _published_form(db, DEFAULT_TENANT_ID, fields=[_num_field("score")])
    by_key = _extend_submission_scope(db, DEFAULT_TENANT_ID, sub_form.id)
    config = _config(
        db, DEFAULT_TENANT_ID, sub_form, rev_form, roles=roles, required=required,
        review_start=by_key["in_review"].id, accepted=by_key["accepted"].id,
        rejected=by_key["rejected"].id, revisions=by_key["revisions"].id,
    )
    db.flush()
    return {"sub_form_id": sub_form.id, "config_id": config.id,
            "in_review_id": by_key["in_review"].id}


def _portal_keys(db, profile_id, tenant_id=DEFAULT_TENANT_ID):
    from modules.ems.models import Profile
    from modules.ems.portal_deps import effective_portal_keys

    prof = db.query(Profile).filter_by(id=profile_id, tenant_id=tenant_id).first()
    return effective_portal_keys(db, prof)


def _rule_reviewer_role(reviewer_id):
    """A RULE-sourced can_review role naming one profile actor, with an always-true
    (empty) group condition. RULE actors are NOT surface-granted at config save
    (only EXPLICIT are) — so this isolates the ALLOCATE grant path."""
    return [{"key": "reviewer", "label": "Reviewer", "can_review": True,
             "actor_source": "RULE", "actor_identity_kind": "profile", "sort_order": 1,
             "conditions_json": {"kind": "group", "combinator": "and", "rules": []},
             "actors": [{"actor_kind": "profile", "actor_id": reviewer_id}]}]


def test_explicit_reviewer_gets_my_reviews_on_allocate(session_factory):
    """A profile reviewer BOUND to a (RULE) can_review role holds my_reviews.read
    AFTER allocate creates their assignment (the auto-grant fired), not before.
    RULE is used so config-save does NOT pre-grant — isolating the allocate path."""
    db = session_factory()
    reviewer = _profile(db); db.flush()
    s = _explicit_setup(db, roles=_rule_reviewer_role(reviewer.id))
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    db.commit()
    reviewer_id, author_id = reviewer.id, author.id

    # Before allocate: a RULE reviewer holds NO portal key (config save skips RULE).
    assert "my_reviews.read" not in _portal_keys(db, reviewer_id)

    # Submit + drive into review → allocate creates the assignment + auto-grants.
    gid = _submit_and_allocate(db, s["sub_form_id"], s["in_review_id"], author_id)
    db.commit()

    assert "my_reviews.read" in _portal_keys(db, reviewer_id)
    # The assignment was actually created (allocate ran).
    rows = db.query(ReviewAssignment).filter_by(reviewed_submission_group_id=gid).all()
    assert any(a.actor_kind == "profile" and a.actor_id == reviewer_id for a in rows)
    db.close()


def test_explicit_decider_gets_decisions_on_config_save(session_factory):
    """An EXPLICIT can_decide PROFILE actor holds decisions.read right after config
    save — deciders have no assignment row, so the config-save grant is the only
    path to their surface."""
    db = session_factory()
    decider = _profile(db); db.flush()
    decider_id = decider.id
    # Before any config: no decisions key.
    assert "decisions.read" not in _portal_keys(db, decider_id)
    _explicit_setup(db, roles=_explicit_roles(decider_id=decider_id))
    db.commit()
    assert "decisions.read" in _portal_keys(db, decider_id)
    db.close()


def test_explicit_submitter_gets_submit_surface_on_config_save(session_factory):
    """An EXPLICIT can_submit PROFILE actor holds my_submissions.read + forms.submit
    right after config save (submitters also have no assignment row)."""
    db = session_factory()
    submitter = _profile(db); db.flush()
    submitter_id = submitter.id
    assert "my_submissions.read" not in _portal_keys(db, submitter_id)
    _explicit_setup(db, roles=_explicit_roles(submitter_id=submitter_id))
    db.commit()
    keys = _portal_keys(db, submitter_id)
    assert "my_submissions.read" in keys and "forms.submit" in keys
    db.close()


def test_user_kind_actor_never_persona_granted(session_factory):
    """A user-kind (STAFF_ROLE) reviewer is NEVER persona-granted — no EMS persona
    membership is created for a user actor (it uses the staff surface)."""
    from app.models.role import Role
    from app.models.user import User, UserStatus
    from app.security import hash_password
    from modules.ems.models import PersonaMembership

    db = session_factory()
    s = _full_setup(db, required=1)
    staff_role = Role(tenant_id=DEFAULT_TENANT_ID, name=_uniq("Judges"), is_system=False)
    staff_role.permissions = []
    db.add(staff_role); db.flush()
    judge = User(tenant_id=DEFAULT_TENANT_ID, email=f"j-{uuid.uuid4().hex[:5]}@e.com",
                 password=hash_password("Passw0rd!"), name="Judge",
                 status=UserStatus.ACTIVE.value)
    judge.roles = [staff_role]
    db.add(judge); db.flush()
    judge_id = judge.id
    ReviewConfigService(db).update_config(
        DEFAULT_TENANT_ID, s["config_id"], fields_set={"roles"},
        roles=_persona_roles(db) + [
            {"key": "staffrev", "label": "Staff Reviewer", "can_review": True,
             "actor_source": "STAFF_ROLE", "actor_identity_kind": "user",
             "bound_staff_role_id": staff_role.id, "sort_order": 9}],
    )
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    db.commit()
    _submit_and_allocate(db, s["sub_form_id"], s["in_review_id"], author.id)
    db.commit()
    # A user-kind assignment was created, but NO persona membership uses the
    # user id as a profile_id (users are never persona-granted).
    membership_profile_ids = {
        m.profile_id for m in db.query(PersonaMembership).filter_by(
            tenant_id=DEFAULT_TENANT_ID).all()
    }
    assert judge_id not in membership_profile_ids
    db.close()


def test_surface_grant_failure_isolated_does_not_break_config_save(session_factory):
    """A granter that RAISES never breaks config save (the assignment/role still
    persists) — grant_actor_surface swallows the exception."""
    from app.review_engine import resolvers

    db = session_factory()
    submitter = _profile(db); db.flush()
    submitter_id = submitter.id

    original = resolvers._SURFACE_GRANTER

    def _boom(*args, **kwargs):
        raise RuntimeError("granter blew up")

    resolvers.register_surface_granter(_boom)
    try:
        s = _explicit_setup(db, roles=_explicit_roles(submitter_id=submitter_id))
        db.commit()
        # Config + role persisted despite the granter raising.
        config = ReviewConfigService(db).repo.get_config(DEFAULT_TENANT_ID, s["config_id"])
        assert config is not None
        roles = ReviewConfigService(db).repo.list_roles(DEFAULT_TENANT_ID, s["config_id"])
        assert any(r.can_submit for r in roles)
    finally:
        resolvers.register_surface_granter(original)
    db.close()


def test_allocate_survives_raising_granter(session_factory):
    """A granter that RAISES never breaks allocate (the assignment still persists)."""
    from app.review_engine import resolvers

    db = session_factory()
    reviewer = _profile(db); db.flush()
    s = _explicit_setup(db, roles=_explicit_roles(reviewer_id=reviewer.id))
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    db.commit()
    reviewer_id, author_id = reviewer.id, author.id

    original = resolvers._SURFACE_GRANTER

    def _boom(*args, **kwargs):
        raise RuntimeError("granter blew up")

    resolvers.register_surface_granter(_boom)
    try:
        _submit_and_allocate(db, s["sub_form_id"], s["in_review_id"], author_id)
        db.commit()
        rows = db.query(ReviewAssignment).filter_by(
            actor_kind="profile", actor_id=reviewer_id).all()
        assert len(rows) == 1  # assignment created despite the granter raising
    finally:
        resolvers.register_surface_granter(original)
    db.close()


# =====================================================================
# Portal terminology (Cluster E portal-signout fix) — a Profile-authed
# read so the portal review surfaces never call the staff GET /terminology
# (which 401s a Profile JWT → signs the portal session out).
# =====================================================================


def test_portal_terminology_profile_authed_returns_merged_map(client, session_factory):
    db = session_factory()
    p = _profile(db)
    db.commit()
    token = _portal_token(db, p)
    db.close()

    res = client.get("/portal/terminology", headers=_ph(token))
    assert res.status_code == 200, res.text
    body = res.json()
    # Merged map shape: {key: {singular, plural}} with the EMS-registered nouns.
    assert isinstance(body, dict)
    assert "submission" in body and "review" in body
    assert set(body["submission"].keys()) == {"singular", "plural"}


def test_portal_terminology_rejects_staff_token(client):
    """A staff JWT must NEVER authenticate the portal endpoint (AC-06-11) — the
    `kind` guard returns 401, never a leaked 200."""
    staff = _staff_login(client)  # {"Authorization": "Bearer <staff jwt>"}
    res = client.get("/portal/terminology", headers=staff)
    assert res.status_code == 401, res.text


def test_portal_terminology_requires_auth(client):
    res = client.get("/portal/terminology")
    assert res.status_code == 401


# =====================================================================
# Admin Submissions overview (AC §10 deferred) — the staff god-view:
# every submission → its reviews/scores → decision.
# =====================================================================


def test_admin_submissions_lists_reviews_and_decision(client, session_factory):
    """GET /reviews/configurations/{id}/submissions returns the submission group
    with BOTH reviews (the completed one carrying its score, the pending one not),
    the correct average, and the decision block."""
    db = session_factory()
    s = _full_setup(db, required=2)
    author = _profile(db); _grant(db, DEFAULT_TENANT_ID, author.id, "participant")
    r1 = _profile(db, email="rev1@e.com"); _grant(db, DEFAULT_TENANT_ID, r1.id, "reviewer")
    r2 = _profile(db, email="rev2@e.com"); _grant(db, DEFAULT_TENANT_ID, r2.id, "reviewer")
    d1 = _profile(db, email="chair@e.com"); _grant(db, DEFAULT_TENANT_ID, d1.id, "decision_maker")
    db.commit()
    group_id = _submit_and_allocate(db, s["sub_form_id"], s["in_review_id"], author.id)
    t1 = _portal_token(db, r1)
    config_id = s["config_id"]
    author_id = author.id
    d1_id = d1.id
    db.close()

    # r1 completes a review with a score; r2 stays pending.
    a1 = client.get("/portal/reviews", headers=_ph(t1)).json()[0]["assignmentId"]
    client.post(f"/portal/reviews/{a1}/submit", json={"answers": {"score": 8}}, headers=_ph(t1))

    # A decision is recorded.
    db = session_factory()
    ReviewConfigService(db).decide_and_transition(
        DEFAULT_TENANT_ID, _config_obj(db, config_id), group_id, 1, "profile", d1_id,
        "ACCEPTED", "Strong submission")
    db.commit()
    db.close()

    staff = _staff_login(client)
    res = client.get(f"/reviews/configurations/{config_id}/submissions", headers=staff)
    assert res.status_code == 200, res.text
    items = res.json()
    item = next(i for i in items if i["groupId"] == group_id)

    # Status + author.
    assert item["statusLabel"]
    assert item["author"]["kind"] == "profile" and item["author"]["id"] == author_id

    # Both reviews present; the completed one carries the score, the pending one not.
    reviews = {r["assignmentId"]: r for r in item["reviews"]}
    assert len(reviews) == 2
    completed = [r for r in reviews.values() if r["status"] == ASSIGNMENT_COMPLETED]
    pending = [r for r in reviews.values() if r["status"] == ASSIGNMENT_PENDING]
    assert len(completed) == 1 and completed[0]["score"] == 8.0
    assert len(pending) == 1 and pending[0]["score"] is None

    # Average over the single completed review = 8.
    assert item["averageScore"] == 8.0
    assert item["completedCount"] == 1 and item["requiredReviewCount"] == 2

    # Decision block.
    assert item["decision"]["decision"] == "ACCEPTED"
    assert item["decision"]["feedbackText"] == "Strong submission"
    assert item["decision"]["decidedAt"]


def test_admin_submissions_tenant_isolated(client, session_factory):
    """A config belongs to its tenant only — the admin overview resolves the
    config tenant-scoped (the polymorphic-target_id rule). A demo (tenant-A)
    staff request for a config id that lives in tenant B 404s, and the service
    returns no rows for the foreign tenant."""
    from app.review_engine.surfaces import ReviewSurfaceService, SurfaceNotFound
    from app.models.status import Status
    from app.models.tenant import Tenant
    from modules.ems.bootstrap import _seed_personas

    db = session_factory()
    s = _full_setup(db)  # a tenant-A (default) config
    config_id = s["config_id"]
    # A second tenant that does NOT own the config.
    active = db.query(Status).filter_by(
        entity_type="tenant", tenant_id=None, key="active").first()
    other = Tenant(slug=_uniq("t").replace(" ", "-")[:30], name="Other",
                   status_id=active.id if active else None)
    db.add(other); db.flush()
    _seed_personas(db, other.id)
    other_id = other.id
    db.commit()

    # The tenant-A config is invisible to tenant B → SurfaceNotFound.
    with pytest.raises(SurfaceNotFound):
        ReviewSurfaceService(db).admin_submissions(other_id, config_id)
    # And visible (tenant-scoped) to tenant A.
    rows = ReviewSurfaceService(db).admin_submissions(DEFAULT_TENANT_ID, config_id)
    assert isinstance(rows, list)
    db.close()

    # Over HTTP, the demo (tenant-A) staff reads its own config fine.
    staff = _staff_login(client)
    ok = client.get(f"/reviews/configurations/{config_id}/submissions", headers=staff)
    assert ok.status_code == 200, ok.text
    # A bogus config id 404s.
    miss = client.get("/reviews/configurations/nope/submissions", headers=staff)
    assert miss.status_code == 404, miss.text


def test_admin_submissions_requires_reviews_read(client, session_factory):
    """A user WITHOUT reviews.read is 403 on the admin overview."""
    from app.models.role import Role
    from app.models.user import User, UserStatus
    from app.security import hash_password

    db = session_factory()
    s = _full_setup(db)
    config_id = s["config_id"]
    # A bare user holding NO reviews perms.
    bare_role = Role(tenant_id=DEFAULT_TENANT_ID, name=_uniq("Bare"), is_system=False)
    bare_role.permissions = []
    db.add(bare_role); db.flush()
    user = User(tenant_id=DEFAULT_TENANT_ID, email=f"bare-{uuid.uuid4().hex[:5]}@e.com",
                password=hash_password("Passw0rd!"), name="Bare",
                status=UserStatus.ACTIVE.value)
    user.roles = [bare_role]
    db.add(user); db.flush()
    email = user.email
    db.commit()
    db.close()

    res = client.post("/auth/login", json={"email": email, "password": "Passw0rd!"})
    assert res.status_code == 200, res.text
    h = _ph(res.json()["access_token"])
    out = client.get(f"/reviews/configurations/{config_id}/submissions", headers=h)
    assert out.status_code == 403, out.text


def test_portal_terminology_reflects_tenant_override(client, session_factory):
    from app.services.terminology_service import TerminologyService

    db = session_factory()
    p = _profile(db)
    db.commit()
    token = _portal_token(db, p)
    # Tenant override on a registered key — the profile-authed map must follow it.
    TerminologyService(db).set_term(
        DEFAULT_TENANT_ID, "submission", "Paper", "Papers", _demo_user(db).id
    )
    db.close()

    res = client.get("/portal/terminology", headers=_ph(token))
    assert res.status_code == 200, res.text
    assert res.json()["submission"] == {"singular": "Paper", "plural": "Papers"}
