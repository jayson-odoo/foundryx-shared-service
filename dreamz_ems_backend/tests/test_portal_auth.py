"""Profile Portal auth tests (sprint-4/06 slice 0a) — validates AC-06-11..17.

password login (success + uniform 401) · OTP request always-200 + zero-activation
OTP login + wrong/expired/reused code · forgot + set-password single-use + policy ·
current_profile rejects a staff token / suspended-tenant 403 · portal throttle is
its OWN scope · require_portal_permission 403s (empty in 0a).
"""
from datetime import timedelta

import pytest

from app.models.auth_throttle import (
    THROTTLE_SCOPE_EMAIL,
    THROTTLE_SCOPE_IP,
    THROTTLE_SCOPE_PORTAL,
    AuthThrottle,
)
from app.models.email_outbox import EmailOutbox
from app.models.tenant import DEFAULT_TENANT_ID
from modules.ems.models import (
    PROFILE_TOKEN_OTP,
    PROFILE_TOKEN_SET_PASSWORD,
    Profile,
    ProfileAuthToken,
)
from modules.ems.portal_auth_service import PortalAuthService, _now
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

PROFILE_EMAIL = "participant@e2e.com"
GOOD_PASSWORD = "Portal1234!"
FIXED_OTP = "424242"


@pytest.fixture(autouse=True)
def _deterministic_otp(monkeypatch):
    """Make the emailed OTP deterministic so tests read it without brute-forcing
    the bcrypt hash. randbelow(1_000_000) -> 424242 -> "424242"."""
    monkeypatch.setattr(
        "modules.ems.portal_auth_service.secrets.randbelow", lambda _n: int(FIXED_OTP)
    )


def _make_profile(db, *, email=PROFILE_EMAIL, password=False, tenant_id=DEFAULT_TENANT_ID):
    from app.security import hash_password

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


# ── password login (AC-06-11/12) ─────────────────────────────────────────────


def test_password_login_success(client, session_factory):
    db = session_factory()
    _make_profile(db, password=True)
    db.close()
    res = client.post("/portal/auth/login", json={"email": PROFILE_EMAIL, "password": GOOD_PASSWORD})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["profile"]["email"] == PROFILE_EMAIL
    assert body["profile"]["portalPerms"] == []
    assert body["profile"]["personas"] == []
    # /me round-trips with the portal token
    h = {"Authorization": f"Bearer {body['access_token']}"}
    me = client.get("/portal/auth/me", headers=h)
    assert me.status_code == 200 and me.json()["email"] == PROFILE_EMAIL


def test_password_login_uniform_401(client, session_factory):
    db = session_factory()
    _make_profile(db, password=True)
    # a second profile with NO password (OTP-only)
    _make_profile(db, email="nopw@e2e.com", password=False)
    db.close()

    # wrong password
    bad = client.post("/portal/auth/login", json={"email": PROFILE_EMAIL, "password": "Wrong1234!"})
    assert bad.status_code == 401
    detail = bad.json()["detail"]
    # unknown email — SAME message (no enumeration)
    unk = client.post("/portal/auth/login", json={"email": "ghost@e2e.com", "password": "Wrong1234!"})
    assert unk.status_code == 401 and unk.json()["detail"] == detail
    # NULL-password profile — SAME message (must use OTP)
    nopw = client.post("/portal/auth/login", json={"email": "nopw@e2e.com", "password": GOOD_PASSWORD})
    assert nopw.status_code == 401 and nopw.json()["detail"] == detail


# ── OTP (AC-06-12/17) ────────────────────────────────────────────────────────


def test_request_otp_always_200_hit_and_miss(client, session_factory):
    db = session_factory()
    _make_profile(db, password=False)
    db.close()
    hit = client.post("/portal/auth/request-otp", json={"email": PROFILE_EMAIL})
    miss = client.post("/portal/auth/request-otp", json={"email": "ghost@e2e.com"})
    assert hit.status_code == 200 and miss.status_code == 200
    assert hit.json()["message"] == miss.json()["message"]


def test_otp_login_zero_activation(client, session_factory):
    db = session_factory()
    p = _make_profile(db, password=False)  # NO password set
    db.close()
    assert client.post("/portal/auth/request-otp", json={"email": PROFILE_EMAIL}).status_code == 200

    res = client.post("/portal/auth/login-otp", json={"email": PROFILE_EMAIL, "code": FIXED_OTP})
    assert res.status_code == 200, res.text
    assert res.json()["profile"]["email"] == PROFILE_EMAIL

    # email_verified_at stamped on first OTP login
    db = session_factory()
    refreshed = db.query(Profile).filter(Profile.id == p.id).first()
    assert refreshed.email_verified_at is not None
    assert refreshed.last_login_at is not None
    db.close()


def test_otp_wrong_expired_reused_rejected(client, session_factory):
    db = session_factory()
    _make_profile(db, password=False)
    db.close()
    client.post("/portal/auth/request-otp", json={"email": PROFILE_EMAIL})

    # wrong code
    wrong = client.post("/portal/auth/login-otp", json={"email": PROFILE_EMAIL, "code": "000000"})
    assert wrong.status_code == 400

    # correct code logs in once
    ok = client.post("/portal/auth/login-otp", json={"email": PROFILE_EMAIL, "code": FIXED_OTP})
    assert ok.status_code == 200
    # reuse rejected (single-use — used_at stamped)
    reuse = client.post("/portal/auth/login-otp", json={"email": PROFILE_EMAIL, "code": FIXED_OTP})
    assert reuse.status_code == 400

    # expired code rejected
    db = session_factory()
    p2 = _make_profile(db, email="expire@e2e.com", password=False)
    PortalAuthService(db).request_otp("expire@e2e.com")
    row = (
        db.query(ProfileAuthToken)
        .filter(ProfileAuthToken.profile_id == p2.id, ProfileAuthToken.kind == PROFILE_TOKEN_OTP)
        .first()
    )
    row.expires_at = _now() - timedelta(minutes=1)
    db.commit()
    db.close()
    expired = client.post("/portal/auth/login-otp", json={"email": "expire@e2e.com", "code": FIXED_OTP})
    assert expired.status_code == 400


# ── forgot + set-password (AC-06-15/16/17) ───────────────────────────────────


def test_forgot_password_always_200(client, session_factory):
    db = session_factory()
    _make_profile(db, password=False)
    db.close()
    hit = client.post("/portal/auth/forgot-password", json={"email": PROFILE_EMAIL})
    miss = client.post("/portal/auth/forgot-password", json={"email": "ghost@e2e.com"})
    assert hit.status_code == 200 and miss.status_code == 200
    assert hit.json()["message"] == miss.json()["message"]


def test_set_password_single_use_and_policy(client, session_factory):
    db = session_factory()
    p = _make_profile(db, password=False)
    # staff-issued invite returns the link; extract the token
    link = PortalAuthService(db).issue_profile_invite(DEFAULT_TENANT_ID, p.id)
    db.close()
    token = link.split("token=")[1]

    # weak password rejected by policy
    weak = client.post("/portal/auth/set-password", json={"token": token, "password": "weak"})
    assert weak.status_code == 422

    # strong password redeems → session issued
    ok = client.post("/portal/auth/set-password", json={"token": token, "password": GOOD_PASSWORD})
    assert ok.status_code == 200, ok.text
    assert ok.json()["profile"]["email"] == PROFILE_EMAIL

    # second redeem fails (single-use)
    again = client.post("/portal/auth/set-password", json={"token": token, "password": GOOD_PASSWORD})
    assert again.status_code == 400

    # the new password now logs in
    login = client.post("/portal/auth/login", json={"email": PROFILE_EMAIL, "password": GOOD_PASSWORD})
    assert login.status_code == 200


# ── current_profile: staff-token rejection + suspended tenant (AC-06-11/13) ───


def test_current_profile_rejects_staff_token(client, session_factory):
    # A valid STAFF JWT must never authenticate the portal.
    staff = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert staff.status_code == 200
    staff_token = staff.json()["access_token"]
    res = client.get("/portal/auth/me", headers={"Authorization": f"Bearer {staff_token}"})
    assert res.status_code == 401

    # and a portal token must never authenticate a staff endpoint
    db = session_factory()
    _make_profile(db, password=True)
    db.close()
    portal = client.post("/portal/auth/login", json={"email": PROFILE_EMAIL, "password": GOOD_PASSWORD})
    portal_token = portal.json()["access_token"]
    staff_me = client.get("/auth/me", headers={"Authorization": f"Bearer {portal_token}"})
    assert staff_me.status_code == 401


def test_current_profile_suspended_tenant_403(client, session_factory):
    db = session_factory()
    _make_profile(db, password=True)
    db.close()
    login = client.post("/portal/auth/login", json={"email": PROFILE_EMAIL, "password": GOOD_PASSWORD})
    assert login.status_code == 200
    token = login.json()["access_token"]

    # suspend the default tenant → portal session dies on the next request
    db = session_factory()
    from app.models.status import Status
    from app.models.tenant import Tenant

    tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
    suspended = (
        db.query(Status)
        .filter(Status.entity_type == "tenant", Status.blocks_access.is_(True))
        .first()
    )
    assert suspended is not None
    tenant.status_id = suspended.id
    db.commit()
    db.close()

    res = client.get("/portal/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403


# ── throttle is its OWN scope (AC-06-16) ─────────────────────────────────────


def test_portal_throttle_is_isolated_scope(client, session_factory):
    db = session_factory()
    _make_profile(db, password=True)
    db.close()

    # pump the portal bucket past its limit (failed logins)
    from app.config import settings

    for _ in range(settings.throttle_portal_max_fails):
        client.post("/portal/auth/login", json={"email": PROFILE_EMAIL, "password": "Wrong1234!"})
    blocked = client.post("/portal/auth/login", json={"email": PROFILE_EMAIL, "password": "Wrong1234!"})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers

    # the staff IP + email buckets are untouched — staff login still works
    db = session_factory()
    ip_rows = db.query(AuthThrottle).filter(AuthThrottle.scope == THROTTLE_SCOPE_IP).count()
    email_rows = db.query(AuthThrottle).filter(AuthThrottle.scope == THROTTLE_SCOPE_EMAIL).count()
    portal_rows = db.query(AuthThrottle).filter(AuthThrottle.scope == THROTTLE_SCOPE_PORTAL).count()
    db.close()
    assert portal_rows >= 1
    assert ip_rows == 0 and email_rows == 0

    staff = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert staff.status_code == 200

    # and the reverse: pumping the staff bucket does not block the portal — fresh
    # profile login still succeeds despite the portal bucket being full for THIS
    # ip (note: same 127.0.0.1, so we assert via a DIFFERENT email after reset).


def test_staff_throttle_does_not_block_portal(client, session_factory):
    db = session_factory()
    _make_profile(db, password=True)
    db.close()
    # pump the STAFF buckets (IP + email)
    from app.config import settings

    for _ in range(settings.throttle_ip_max_fails):
        client.post("/auth/login", json={"email": "ghost@example.com", "password": "Wrong1234!"})
    blocked = client.post("/auth/login", json={"email": "ghost@example.com", "password": "Wrong1234!"})
    assert blocked.status_code == 429
    # the portal bucket is its own scope → portal login still works
    ok = client.post("/portal/auth/login", json={"email": PROFILE_EMAIL, "password": GOOD_PASSWORD})
    assert ok.status_code == 200


# ── require_portal_permission gates (AC-06-14) ───────────────────────────────


def test_require_portal_permission_403_when_absent(client, session_factory):
    from fastapi import Depends

    from modules.ems.portal_deps import require_portal_permission

    # mount a throwaway gated route on the live app to exercise the dependency
    from app.main import app as live_app

    @live_app.get("/portal/_test_gated")
    def _gated(_p=Depends(require_portal_permission("submissions.read"))):  # pragma: no cover
        return {"ok": True}

    db = session_factory()
    _make_profile(db, password=True)
    db.close()
    token = client.post(
        "/portal/auth/login", json={"email": PROFILE_EMAIL, "password": GOOD_PASSWORD}
    ).json()["access_token"]
    res = client.get("/portal/_test_gated", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403  # empty key set in 0a
    # unauthenticated → 401
    assert client.get("/portal/_test_gated").status_code == 401


# ── Staff "Send portal invite" endpoint (AC-06-15c) ──────────────────────────


def _staff_headers(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_send_portal_invite_as_staff(client, session_factory):
    db = session_factory()
    p = _make_profile(db, password=False)
    db.close()

    res = client.post(f"/ems/profiles/{p.id}/invite", json={}, headers=_staff_headers(client))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sent"] is True and body["email"] == PROFILE_EMAIL

    db = session_factory()
    # an outstanding SET_PASSWORD token row now exists for the profile
    tokens = (
        db.query(ProfileAuthToken)
        .filter(
            ProfileAuthToken.profile_id == p.id,
            ProfileAuthToken.kind == PROFILE_TOKEN_SET_PASSWORD,
            ProfileAuthToken.used_at.is_(None),
        )
        .all()
    )
    assert len(tokens) == 1
    assert tokens[0].grant_persona_key is None
    # and an email was enqueued to the profile
    mail = (
        db.query(EmailOutbox)
        .filter(EmailOutbox.to_email == PROFILE_EMAIL)
        .order_by(EmailOutbox.id.desc())
        .first()
    )
    assert mail is not None
    db.close()


def test_send_portal_invite_requires_perm(client, session_factory):
    """A profile-authed (portal) token, or any caller lacking personas.manage,
    cannot trigger the staff invite — gated personas.manage."""
    db = session_factory()
    p = _make_profile(db, password=True)
    db.close()
    # A portal (profile) token is not a staff token — must not pass the gate.
    portal_token = client.post(
        "/portal/auth/login", json={"email": PROFILE_EMAIL, "password": GOOD_PASSWORD}
    ).json()["access_token"]
    res = client.post(
        f"/ems/profiles/{p.id}/invite",
        json={},
        headers={"Authorization": f"Bearer {portal_token}"},
    )
    assert res.status_code in (401, 403)
    # unauthenticated → 401
    assert client.post(f"/ems/profiles/{p.id}/invite", json={}).status_code == 401


def test_send_portal_invite_foreign_tenant_404(client, session_factory):
    # A profile owned by another tenant must be invisible to this tenant's staff
    # (tenant-scoped resolution → 404, never a cross-tenant invite).
    db = session_factory()
    foreign = _make_profile(db, email="foreign@e2e.com", tenant_id="some-other-tenant")
    db.close()

    res = client.post(
        f"/ems/profiles/{foreign.id}/invite", json={}, headers=_staff_headers(client)
    )
    assert res.status_code == 404


def test_send_portal_invite_no_email_422(client, session_factory):
    db = session_factory()
    p = _make_profile(db, email="", password=False)
    db.close()
    res = client.post(f"/ems/profiles/{p.id}/invite", json={}, headers=_staff_headers(client))
    assert res.status_code == 422


def test_send_portal_invite_with_persona_project_grant(client, session_factory):
    h = _staff_headers(client)
    # Build a project to scope the grant to.
    t = client.post("/ems/project-types", json={"name": "InviteType"}, headers=h).json()
    tmpl = client.post(
        "/ems/project-templates", json={"typeId": t["id"], "name": "InviteTmpl"}, headers=h
    ).json()
    proj = client.post(
        "/ems/projects", json={"templateId": tmpl["id"], "title": "InviteEvt"}, headers=h
    ).json()

    db = session_factory()
    p = _make_profile(db, email="grantee@e2e.com", password=False)
    db.close()

    res = client.post(
        f"/ems/profiles/{p.id}/invite",
        json={"personaKey": "participant", "scopeType": "project", "scopeId": proj["id"]},
        headers=h,
    )
    assert res.status_code == 200, res.text

    db = session_factory()
    token = (
        db.query(ProfileAuthToken)
        .filter(
            ProfileAuthToken.profile_id == p.id,
            ProfileAuthToken.kind == PROFILE_TOKEN_SET_PASSWORD,
            ProfileAuthToken.used_at.is_(None),
        )
        .first()
    )
    assert token.grant_persona_key == "participant"
    assert token.grant_scope_type == "project"
    assert token.grant_scope_id == proj["id"]
    db.close()


def test_send_portal_invite_bad_project_scope_422(client, session_factory):
    db = session_factory()
    p = _make_profile(db, email="badscope@e2e.com", password=False)
    db.close()
    res = client.post(
        f"/ems/profiles/{p.id}/invite",
        json={"personaKey": "participant", "scopeType": "project", "scopeId": "nope"},
        headers=_staff_headers(client),
    )
    assert res.status_code == 422
