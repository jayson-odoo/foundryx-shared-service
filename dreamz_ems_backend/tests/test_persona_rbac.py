"""Persona RBAC tests (sprint-4/06 slice 0b) — validates AC-06-19..23, 26, 62.

Persona membership scoping + UNIQUE · effective_portal_keys union (tenant-scoped,
no cross-tenant leak) · require_portal_permission resolves FRESH from DB (grant
passes, revoke denies on next request) · the 3 grant paths (AUTO/STAFF/INVITE) ·
system personas delete-blocked · the portal catalog is DISJOINT from core
permissions · GET /portal/surfaces gating · staff persona CRUD + grant endpoints ·
tenant isolation.
"""
import uuid

import pytest
from fastapi import Depends
from sqlalchemy.exc import IntegrityError

from app.models.permission import Permission
from app.models.tenant import DEFAULT_TENANT_ID
from app.security import hash_password
from modules.ems.models import (
    PERSONA_GRANT_STAFF,
    PERSONA_SCOPE_PROJECT,
    PERSONA_SCOPE_TENANT,
    Persona,
    PersonaMembership,
    PersonaPermission,
    Profile,
    ProfileAuthToken,
    PROFILE_TOKEN_SET_PASSWORD,
)
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

GOOD_PASSWORD = "Portal1234!"


# ── fixtures / helpers ───────────────────────────────────────────────────────


def _h(res):
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _staff_headers(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    return _h(res)


def _make_profile(db, *, email=None, password=False, tenant_id=DEFAULT_TENANT_ID):
    email = email or f"profile-{uuid.uuid4().hex[:8]}@e2e.com"
    p = Profile(
        tenant_id=tenant_id,
        email=email.strip().lower(),
        full_name="Test Participant",
        password_hash=hash_password(GOOD_PASSWORD) if password else None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _persona(db, key, *, tenant_id=DEFAULT_TENANT_ID, is_system=False, perms=()):
    persona = Persona(
        tenant_id=tenant_id, key=key, label=key.title(), is_system=is_system
    )
    db.add(persona)
    db.flush()
    for pk in perms:
        db.add(
            PersonaPermission(tenant_id=tenant_id, persona_id=persona.id, permission_key=pk)
        )
    db.commit()
    db.refresh(persona)
    return persona


# ── AC-06-20: membership is scoped + UNIQUE ──────────────────────────────────


def test_membership_scoped_different_personas_per_scope(session_factory):
    db = session_factory()
    prof = _make_profile(db)
    reviewer = _persona(db, "reviewer-x")
    participant = _persona(db, "participant-x")
    # Same profile, different personas in different project scopes.
    db.add(PersonaMembership(tenant_id=DEFAULT_TENANT_ID, profile_id=prof.id,
                             persona_id=reviewer.id, scope_type=PERSONA_SCOPE_PROJECT,
                             scope_id="proj-A", granted_via=PERSONA_GRANT_STAFF))
    db.add(PersonaMembership(tenant_id=DEFAULT_TENANT_ID, profile_id=prof.id,
                             persona_id=participant.id, scope_type=PERSONA_SCOPE_PROJECT,
                             scope_id="proj-B", granted_via=PERSONA_GRANT_STAFF))
    db.commit()
    rows = db.query(PersonaMembership).filter(PersonaMembership.profile_id == prof.id).all()
    assert len(rows) == 2
    db.close()


def test_membership_unique_rejects_duplicate(session_factory):
    db = session_factory()
    prof = _make_profile(db)
    persona = _persona(db, "dup-persona")
    db.add(PersonaMembership(tenant_id=DEFAULT_TENANT_ID, profile_id=prof.id,
                             persona_id=persona.id, scope_type=PERSONA_SCOPE_PROJECT,
                             scope_id="proj-A", granted_via=PERSONA_GRANT_STAFF))
    db.commit()
    db.add(PersonaMembership(tenant_id=DEFAULT_TENANT_ID, profile_id=prof.id,
                             persona_id=persona.id, scope_type=PERSONA_SCOPE_PROJECT,
                             scope_id="proj-A", granted_via=PERSONA_GRANT_STAFF))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()


# ── AC-06-14/21: effective_portal_keys union + no cross-tenant leak ───────────


def test_effective_portal_keys_unions_across_personas(session_factory):
    db = session_factory()
    from modules.ems.portal_deps import effective_portal_keys

    prof = _make_profile(db)
    p1 = _persona(db, "p1", perms=["my_submissions.read", "forms.submit"])
    p2 = _persona(db, "p2", perms=["my_reviews.read"])
    for persona in (p1, p2):
        db.add(PersonaMembership(tenant_id=DEFAULT_TENANT_ID, profile_id=prof.id,
                                 persona_id=persona.id, scope_type=PERSONA_SCOPE_TENANT,
                                 scope_id=None, granted_via=PERSONA_GRANT_STAFF))
    db.commit()
    keys = effective_portal_keys(db, prof)
    assert keys == {"my_submissions.read", "forms.submit", "my_reviews.read"}
    db.close()


def test_effective_portal_keys_no_cross_tenant_leak(session_factory):
    db = session_factory()
    from modules.ems.portal_deps import effective_portal_keys

    # Same profile id reused across tenants is impossible (uuid), but a persona +
    # membership belonging to ANOTHER tenant must never contribute keys.
    prof = _make_profile(db, tenant_id=DEFAULT_TENANT_ID)
    other_persona = _persona(db, "leaky", tenant_id="other-tenant", perms=["secret.read"])
    # plant a membership in the OTHER tenant referencing our persona id but our
    # profile — effective_portal_keys filters by the profile's OWN tenant_id.
    db.add(PersonaMembership(tenant_id="other-tenant", profile_id=prof.id,
                             persona_id=other_persona.id, scope_type=PERSONA_SCOPE_TENANT,
                             scope_id=None, granted_via=PERSONA_GRANT_STAFF))
    db.commit()
    assert effective_portal_keys(db, prof) == set()
    db.close()


# ── AC-06-14: require_portal_permission resolves FRESH (grant→pass, revoke→deny)


def test_require_portal_permission_grant_then_revoke(client, session_factory):
    from app.main import app as live_app
    from modules.ems.portal_deps import require_portal_permission

    @live_app.get("/portal/_test_persona_gate")
    def _gated(_p=Depends(require_portal_permission("my_submissions.read"))):
        return {"ok": True}

    db = session_factory()
    prof = _make_profile(db, password=True)
    persona = _persona(db, "gate-persona", perms=["my_submissions.read"])
    membership = PersonaMembership(
        tenant_id=DEFAULT_TENANT_ID, profile_id=prof.id, persona_id=persona.id,
        scope_type=PERSONA_SCOPE_TENANT, scope_id=None, granted_via=PERSONA_GRANT_STAFF,
    )
    db.add(membership)
    db.commit()
    membership_id = membership.id
    email = prof.email
    db.close()

    token = client.post(
        "/portal/auth/login", json={"email": email, "password": GOOD_PASSWORD}
    ).json()["access_token"]
    hdr = {"Authorization": f"Bearer {token}"}
    assert client.get("/portal/_test_persona_gate", headers=hdr).status_code == 200

    # Revoke the grant; the SAME token must now be denied (fresh DB resolution).
    db = session_factory()
    db.query(PersonaMembership).filter(PersonaMembership.id == membership_id).delete()
    db.commit()
    db.close()
    assert client.get("/portal/_test_persona_gate", headers=hdr).status_code == 403


# ── AC-06-22: three grant paths ──────────────────────────────────────────────


def test_grant_path_auto_participant_add(client, session_factory):
    """Adding a ProjectParticipant auto-derives the participant persona scoped to
    that project."""
    h = _staff_headers(client)
    t = client.post("/ems/project-types", json={"name": "Conf"}, headers=h).json()
    tmpl = client.post("/ems/project-templates",
                       json={"typeId": t["id"], "name": "Std"}, headers=h).json()
    proj = client.post("/ems/projects",
                       json={"templateId": tmpl["id"], "title": "AutoEvt"}, headers=h).json()
    prof = client.post("/ems/profiles", json={"email": "auto@e2e.com"}, headers=h).json()
    add = client.post(f"/ems/projects/{proj['id']}/participants",
                      json={"profileId": prof["id"]}, headers=h)
    assert add.status_code in (200, 201), add.text

    db = session_factory()
    persona = db.query(Persona).filter(
        Persona.tenant_id == DEFAULT_TENANT_ID, Persona.key == "participant"
    ).first()
    m = db.query(PersonaMembership).filter(
        PersonaMembership.profile_id == prof["id"],
        PersonaMembership.persona_id == persona.id,
    ).first()
    assert m is not None
    assert m.scope_type == PERSONA_SCOPE_PROJECT
    assert m.scope_id == proj["id"]
    assert m.granted_via == "AUTO"
    db.close()


def test_grant_path_staff_assign(client, session_factory):
    h = _staff_headers(client)
    # A real tenant project — the save-time scope guard (polymorphic-target_id
    # rule) now rejects a foreign/unknown project scope id.
    t = client.post("/ems/project-types", json={"name": "ConfSG"}, headers=h).json()
    tmpl = client.post("/ems/project-templates",
                       json={"typeId": t["id"], "name": "StdSG"}, headers=h).json()
    proj = client.post("/ems/projects",
                       json={"templateId": tmpl["id"], "title": "StaffGrantEvt"}, headers=h).json()
    proj_id = proj["id"]
    prof = client.post("/ems/profiles", json={"email": "staff-grant@e2e.com"}, headers=h).json()
    db = session_factory()
    reviewer = db.query(Persona).filter(
        Persona.tenant_id == DEFAULT_TENANT_ID, Persona.key == "reviewer"
    ).first()
    reviewer_id = reviewer.id
    db.close()
    res = client.post(
        f"/ems/profiles/{prof['id']}/personas",
        json={"personaId": reviewer_id, "scopeType": "project", "scopeId": proj_id},
        headers=h,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["grantedVia"] == "STAFF"
    assert body["scopeId"] == proj_id
    # idempotent — re-assign returns the same membership, no dup.
    again = client.post(
        f"/ems/profiles/{prof['id']}/personas",
        json={"personaId": reviewer_id, "scopeType": "project", "scopeId": proj_id},
        headers=h,
    )
    assert again.status_code == 201
    assert again.json()["id"] == body["id"]
    # Save-time guard: an unknown/foreign project scope id is rejected (422).
    bad = client.post(
        f"/ems/profiles/{prof['id']}/personas",
        json={"personaId": reviewer_id, "scopeType": "project", "scopeId": "proj-FOREIGN"},
        headers=h,
    )
    assert bad.status_code == 422, bad.text


def test_grant_path_invite_set_password_applies_persona(client, session_factory):
    db = session_factory()
    prof = _make_profile(db)
    tenant_id, profile_id = prof.tenant_id, prof.id
    db.close()

    # Staff issues an invite carrying a persona+context to grant on acceptance.
    db = session_factory()
    from modules.ems.portal_auth_service import PortalAuthService

    PortalAuthService(db).issue_profile_invite(
        tenant_id, profile_id,
        grant_persona_key="reviewer", grant_scope_type="project", grant_scope_id="proj-INV",
    )
    db.commit()
    row = db.query(ProfileAuthToken).filter(
        ProfileAuthToken.profile_id == profile_id,
        ProfileAuthToken.kind == PROFILE_TOKEN_SET_PASSWORD,
        ProfileAuthToken.used_at.is_(None),
    ).first()
    token = row.token
    assert row.grant_persona_key == "reviewer"
    db.close()

    # Redeem the invite — the persona is applied (granted_via=INVITE).
    res = client.post("/portal/auth/set-password", json={"token": token, "password": GOOD_PASSWORD})
    assert res.status_code == 200, res.text

    db = session_factory()
    reviewer = db.query(Persona).filter(
        Persona.tenant_id == DEFAULT_TENANT_ID, Persona.key == "reviewer"
    ).first()
    m = db.query(PersonaMembership).filter(
        PersonaMembership.profile_id == profile_id,
        PersonaMembership.persona_id == reviewer.id,
    ).first()
    assert m is not None
    assert m.granted_via == "INVITE"
    assert m.scope_id == "proj-INV"
    db.close()


# ── AC-06-19: system personas delete-blocked; custom deletable ───────────────


def test_system_persona_delete_blocked(client):
    h = _staff_headers(client)
    rows = client.get("/ems/personas", headers=h).json()
    system = next(p for p in rows if p["key"] == "participant")
    assert system["isSystem"] is True
    res = client.delete(f"/ems/personas/{system['id']}", headers=h)
    assert res.status_code == 409


def test_custom_persona_crud_and_delete(client):
    h = _staff_headers(client)
    created = client.post("/ems/personas", json={"key": "presenter", "label": "Presenter"}, headers=h)
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    assert created.json()["isSystem"] is False
    patched = client.patch(f"/ems/personas/{pid}", json={"label": "Speaker"}, headers=h)
    assert patched.json()["label"] == "Speaker"
    assert client.delete(f"/ems/personas/{pid}", headers=h).status_code == 204


def test_system_persona_key_locked_label_editable(client, session_factory):
    h = _staff_headers(client)
    rows = client.get("/ems/personas", headers=h).json()
    system = next(p for p in rows if p["key"] == "reviewer")
    # key change blocked
    blocked = client.patch(f"/ems/personas/{system['id']}", json={"key": "reviewer2"}, headers=h)
    assert blocked.status_code == 422
    # label editable
    ok = client.patch(f"/ems/personas/{system['id']}", json={"label": "Peer Reviewer"}, headers=h)
    assert ok.status_code == 200
    assert ok.json()["label"] == "Peer Reviewer"


# ── AC-06-21: portal catalog is DISJOINT from core permissions ───────────────


def test_portal_catalog_disjoint_from_core_permissions(client, session_factory):
    h = _staff_headers(client)
    catalog = client.get("/ems/personas/portal-permissions", headers=h)
    assert catalog.status_code == 200
    keys = {p["key"] for p in catalog.json()}
    assert "my_submissions.read" in keys
    # NONE of the portal keys exist in the core permissions table.
    db = session_factory()
    core_keys = {row.key for row in db.query(Permission).all()}
    db.close()
    assert keys.isdisjoint(core_keys)


# ── AC-06-23: GET /portal/surfaces gating ────────────────────────────────────


def test_portal_surfaces_gated_by_held_keys(client, session_factory):
    db = session_factory()
    prof = _make_profile(db, password=True)
    # grant ONLY the reviewer persona (my_reviews.read) at tenant scope.
    reviewer = db.query(Persona).filter(
        Persona.tenant_id == DEFAULT_TENANT_ID, Persona.key == "reviewer"
    ).first()
    db.add(PersonaMembership(tenant_id=DEFAULT_TENANT_ID, profile_id=prof.id,
                             persona_id=reviewer.id, scope_type=PERSONA_SCOPE_PROJECT,
                             scope_id="proj-S", granted_via=PERSONA_GRANT_STAFF))
    db.commit()
    email = prof.email
    db.close()

    token = client.post(
        "/portal/auth/login", json={"email": email, "password": GOOD_PASSWORD}
    ).json()["access_token"]
    res = client.get("/portal/surfaces", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    surfaces = {s["key"]: s for s in res.json()}
    assert set(surfaces) == {"my_reviews"}  # only the held surface
    # the surface carries the profile's scoped context for it. The label is None
    # here ("proj-S" is not a real project), resolved server-side for real events
    # (AC-06-25).
    ctxs = surfaces["my_reviews"]["contexts"]
    assert len(ctxs) == 1
    assert ctxs[0]["scopeType"] == "project" and ctxs[0]["scopeId"] == "proj-S"
    assert ctxs[0].get("label") is None


def test_portal_surfaces_context_label_is_real_event_name(client, session_factory):
    """AC-06-25 — a project-scope context resolves to the real event name (not an
    id prefix) in the surfaces payload, so the filter pill reads "{event title}"."""
    from modules.ems.models import Project, ProjectTemplate, ProjectType

    db = session_factory()
    ptype = ProjectType(tenant_id=DEFAULT_TENANT_ID, name="T")
    db.add(ptype); db.flush()
    tmpl = ProjectTemplate(tenant_id=DEFAULT_TENANT_ID, type_id=ptype.id, name="Tmpl")
    db.add(tmpl); db.flush()
    project = Project(tenant_id=DEFAULT_TENANT_ID, template_id=tmpl.id, type_id=ptype.id,
                      title="Annual Summit")
    db.add(project); db.flush()

    prof = _make_profile(db, password=True)
    reviewer = db.query(Persona).filter(
        Persona.tenant_id == DEFAULT_TENANT_ID, Persona.key == "reviewer"
    ).first()
    db.add(PersonaMembership(tenant_id=DEFAULT_TENANT_ID, profile_id=prof.id,
                             persona_id=reviewer.id, scope_type=PERSONA_SCOPE_PROJECT,
                             scope_id=project.id, granted_via=PERSONA_GRANT_STAFF))
    db.commit()
    email = prof.email
    db.close()

    token = client.post(
        "/portal/auth/login", json={"email": email, "password": GOOD_PASSWORD}
    ).json()["access_token"]
    res = client.get("/portal/surfaces", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    surfaces = {s["key"]: s for s in res.json()}
    ctx = surfaces["my_reviews"]["contexts"][0]
    assert ctx["label"] == "Annual Summit"


def test_portal_surfaces_empty_when_no_personas(client, session_factory):
    db = session_factory()
    prof = _make_profile(db, password=True)
    email = prof.email
    db.close()
    token = client.post(
        "/portal/auth/login", json={"email": email, "password": GOOD_PASSWORD}
    ).json()["access_token"]
    res = client.get("/portal/surfaces", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json() == []


# ── AC-06-26: staff persona-grant endpoints ──────────────────────────────────


def test_staff_set_persona_permissions(client, session_factory):
    h = _staff_headers(client)
    created = client.post("/ems/personas", json={"key": "judge", "label": "Judge"}, headers=h).json()
    pid = created["id"]
    res = client.put(
        f"/ems/personas/{pid}/permissions",
        json={"keys": ["decisions.read", "my_reviews.read"]},
        headers=h,
    )
    assert res.status_code == 200, res.text
    assert set(res.json()["keys"]) == {"decisions.read", "my_reviews.read"}
    # unknown key rejected (foolproof — catalog-validated).
    bad = client.put(f"/ems/personas/{pid}/permissions",
                     json={"keys": ["not.a.real.key"]}, headers=h)
    assert bad.status_code == 422


# ── AC-06-57: tenant isolation ───────────────────────────────────────────────


def test_tenant_isolation_personas(client, session_factory):
    """A staff user of tenant A cannot read/modify tenant B's personas."""
    db = session_factory()
    other = _persona(db, "other-tenant-persona", tenant_id="tenant-B")
    other_id = other.id
    db.close()
    h = _staff_headers(client)  # demo user is tenant = default
    assert client.get(f"/ems/personas/{other_id}", headers=h).status_code == 404
    assert client.patch(f"/ems/personas/{other_id}", json={"label": "x"}, headers=h).status_code == 404
    assert client.delete(f"/ems/personas/{other_id}", headers=h).status_code == 404


def test_assign_membership_rejects_cross_tenant_persona(client, session_factory):
    """AC-06-26/57: staff of tenant A assigning a tenant-B persona id to one of
    A's profiles is a tenant-scoped 404 — a foreign persona can never be bound."""
    db = session_factory()
    foreign = _persona(db, "foreign-persona", tenant_id="tenant-B")
    foreign_id = foreign.id
    db.close()
    h = _staff_headers(client)  # default tenant
    prof = client.post("/ems/profiles", json={"email": "xtenant@e2e.com"}, headers=h).json()
    res = client.post(
        f"/ems/profiles/{prof['id']}/personas",
        json={"personaId": foreign_id, "scopeType": "tenant"},
        headers=h,
    )
    assert res.status_code == 404, res.text
    # nothing was written
    db = session_factory()
    assert (
        db.query(PersonaMembership)
        .filter(PersonaMembership.profile_id == prof["id"])
        .count()
        == 0
    )
    db.close()


def test_otp_only_profile_holds_persona_and_resolves_keys(client, session_factory):
    """AC-06-12/22: a zero-activation Profile (NO password_hash, OTP-only) can hold
    a persona; effective_portal_keys resolves for it exactly like a password
    profile — persona RBAC is identity-of-auth-agnostic."""
    from modules.ems.portal_deps import effective_portal_keys

    db = session_factory()
    prof = _make_profile(db, password=False)  # OTP-only — no password set
    assert prof.password_hash is None
    persona = _persona(db, "otp-persona", perms=["my_submissions.read", "forms.submit"])
    db.add(
        PersonaMembership(
            tenant_id=DEFAULT_TENANT_ID, profile_id=prof.id, persona_id=persona.id,
            scope_type=PERSONA_SCOPE_TENANT, scope_id=None, granted_via=PERSONA_GRANT_STAFF,
        )
    )
    db.commit()
    assert effective_portal_keys(db, prof) == {"my_submissions.read", "forms.submit"}
    db.close()
