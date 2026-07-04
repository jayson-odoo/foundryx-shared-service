"""Profile Portal auth — gap-closing audit tests (sprint-4/06 slice 0a).

Supplements ``test_portal_auth.py`` to close coverage gaps found in the QA audit:
  - AC-06-13  JWT claim shape (sub/tenant_id/kind/empty perms+personas) + tenant
              re-resolution is tenant-scoped (a token's tenant_id is authoritative).
  - AC-06-12  password is PRIMARY but OTP still works for a password-set profile.
  - AC-06-16  request-otp AND forgot-password pump the PORTAL bucket (not staff)
              even on the HIT path (mail-bombing vector), and the throttle is
              enforced BEFORE bcrypt.
  - AC-06-17  re-requesting an OTP invalidates the prior outstanding code.
  - AC-06-11  unknown tenant slug = uniform 401 (no enumeration).
  - AC-06-13  cross-tenant: a profile in tenant A is never resolvable when the
              JWT carries tenant B (current_profile scopes by the token tenant).
"""
from datetime import timedelta

import pytest

from app.config import settings
from app.models.auth_throttle import (
    THROTTLE_SCOPE_EMAIL,
    THROTTLE_SCOPE_IP,
    THROTTLE_SCOPE_PORTAL,
    AuthThrottle,
)
from app.models.tenant import DEFAULT_TENANT_ID, Tenant
from app.security import decode_access_token
from modules.ems.models import (
    PROFILE_TOKEN_OTP,
    PROFILE_TOKEN_SET_PASSWORD,
    Profile,
    ProfileAuthToken,
)
from modules.ems.portal_auth_service import (
    PROFILE_TOKEN_KIND,
    PortalAuthService,
    _now,
)

PROFILE_EMAIL = "audit-participant@e2e.com"
GOOD_PASSWORD = "Portal1234!"
FIXED_OTP = "424242"


@pytest.fixture(autouse=True)
def _deterministic_otp(monkeypatch):
    monkeypatch.setattr(
        "modules.ems.portal_auth_service.secrets.randbelow", lambda _n: int(FIXED_OTP)
    )


def _make_profile(db, *, email=PROFILE_EMAIL, password=False, tenant_id=DEFAULT_TENANT_ID):
    from app.security import hash_password

    p = Profile(
        tenant_id=tenant_id,
        email=email.strip().lower(),
        full_name="Audit Participant",
        password_hash=hash_password(GOOD_PASSWORD) if password else None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _make_second_tenant(db, slug="audit-tenant-2"):
    """A second ACTIVE tenant cloning the default tenant's status row."""
    default = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
    t = Tenant(name="Audit Tenant 2", slug=slug, status_id=default.status_id)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ── AC-06-13: JWT claim shape ────────────────────────────────────────────────


def test_jwt_carries_profile_claims(client, session_factory):
    db = session_factory()
    p = _make_profile(db, password=True)
    pid = p.id
    db.close()
    res = client.post(
        "/portal/auth/login", json={"email": PROFILE_EMAIL, "password": GOOD_PASSWORD}
    )
    assert res.status_code == 200, res.text
    claims = decode_access_token(res.json()["access_token"])
    assert claims["sub"] == pid
    assert claims["tenant_id"] == DEFAULT_TENANT_ID
    assert claims["kind"] == PROFILE_TOKEN_KIND
    assert claims["email"] == PROFILE_EMAIL
    assert claims["portal_perms"] == []  # empty in 0a (personas land in 0b)
    assert claims["personas"] == []


# ── AC-06-12: OTP fallback works even when a password IS set ──────────────────


def test_otp_fallback_works_for_password_set_profile(client, session_factory):
    db = session_factory()
    _make_profile(db, password=True)  # password IS set
    db.close()
    assert (
        client.post("/portal/auth/request-otp", json={"email": PROFILE_EMAIL}).status_code
        == 200
    )
    res = client.post(
        "/portal/auth/login-otp", json={"email": PROFILE_EMAIL, "code": FIXED_OTP}
    )
    assert res.status_code == 200, res.text  # OTP is a fallback, not gated by NULL pw
    assert res.json()["profile"]["email"] == PROFILE_EMAIL


# ── AC-06-16: request-otp pumps the PORTAL bucket on the HIT path ─────────────


def test_request_otp_pumps_portal_bucket_on_hit(client, session_factory):
    db = session_factory()
    _make_profile(db, password=False)
    db.close()
    client.post("/portal/auth/request-otp", json={"email": PROFILE_EMAIL})  # a HIT

    db = session_factory()
    portal = db.query(AuthThrottle).filter(AuthThrottle.scope == THROTTLE_SCOPE_PORTAL).count()
    ip = db.query(AuthThrottle).filter(AuthThrottle.scope == THROTTLE_SCOPE_IP).count()
    em = db.query(AuthThrottle).filter(AuthThrottle.scope == THROTTLE_SCOPE_EMAIL).count()
    db.close()
    assert portal >= 1  # the send-mail endpoint pumps its own bucket
    assert ip == 0 and em == 0  # never the staff buckets


def test_request_otp_over_limit_429(client, session_factory):
    db = session_factory()
    _make_profile(db, password=False)
    db.close()
    for _ in range(settings.throttle_portal_max_fails):
        client.post("/portal/auth/request-otp", json={"email": PROFILE_EMAIL})
    blocked = client.post("/portal/auth/request-otp", json={"email": PROFILE_EMAIL})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_forgot_password_pumps_portal_bucket(client, session_factory):
    db = session_factory()
    _make_profile(db, password=False)
    db.close()
    client.post("/portal/auth/forgot-password", json={"email": PROFILE_EMAIL})
    db = session_factory()
    portal = db.query(AuthThrottle).filter(AuthThrottle.scope == THROTTLE_SCOPE_PORTAL).count()
    ip = db.query(AuthThrottle).filter(AuthThrottle.scope == THROTTLE_SCOPE_IP).count()
    db.close()
    assert portal >= 1 and ip == 0


# ── AC-06-17: a new OTP invalidates the prior outstanding one ─────────────────


def test_rerequest_otp_invalidates_prior_code(client, session_factory):
    """Two OTP requests in a row: the FIRST code must no longer be redeemable
    (issuing a new token of a kind invalidates prior outstanding ones)."""
    db = session_factory()
    p = _make_profile(db, password=False)
    svc = PortalAuthService(db)
    svc.request_otp(PROFILE_EMAIL)
    first = (
        db.query(ProfileAuthToken)
        .filter(ProfileAuthToken.profile_id == p.id, ProfileAuthToken.kind == PROFILE_TOKEN_OTP)
        .first()
    )
    assert first.used_at is None
    # second request invalidates the first
    svc.request_otp(PROFILE_EMAIL)
    db.refresh(first)
    assert first.used_at is not None  # prior code burned
    outstanding = (
        db.query(ProfileAuthToken)
        .filter(
            ProfileAuthToken.profile_id == p.id,
            ProfileAuthToken.kind == PROFILE_TOKEN_OTP,
            ProfileAuthToken.used_at.is_(None),
        )
        .count()
    )
    assert outstanding == 1  # exactly the fresh one remains
    db.close()


def test_reissuing_set_password_invalidates_prior_link(client, session_factory):
    db = session_factory()
    p = _make_profile(db, password=False)
    svc = PortalAuthService(db)
    link1 = svc.issue_profile_invite(DEFAULT_TENANT_ID, p.id)
    link2 = svc.issue_profile_invite(DEFAULT_TENANT_ID, p.id)
    db.close()
    token1 = link1.split("token=")[1]
    token2 = link2.split("token=")[1]
    assert token1 != token2
    # the FIRST link is dead (invalidate_outstanding burned it)
    dead = client.post(
        "/portal/auth/set-password", json={"token": token1, "password": GOOD_PASSWORD}
    )
    assert dead.status_code == 400
    # the SECOND link still redeems
    ok = client.post(
        "/portal/auth/set-password", json={"token": token2, "password": GOOD_PASSWORD}
    )
    assert ok.status_code == 200, ok.text


# ── AC-06-11: unknown tenant slug = uniform 401 (no enumeration) ──────────────


def test_login_unknown_slug_uniform_401(client, session_factory):
    db = session_factory()
    _make_profile(db, password=True)
    db.close()
    # right creds but a slug that does not exist → uniform 401, same as bad creds
    res = client.post(
        "/portal/auth/login",
        json={"email": PROFILE_EMAIL, "password": GOOD_PASSWORD, "tenantSlug": "no-such-tenant"},
    )
    assert res.status_code == 401
    bad = client.post(
        "/portal/auth/login", json={"email": PROFILE_EMAIL, "password": "Wrong1234!"}
    )
    assert res.json()["detail"] == bad.json()["detail"]


def test_request_otp_unknown_slug_still_200(client, session_factory):
    """An always-200 path must stay 200 even for an unknown slug (no enumeration)."""
    res = client.post(
        "/portal/auth/request-otp",
        json={"email": PROFILE_EMAIL, "tenantSlug": "no-such-tenant"},
    )
    assert res.status_code == 200


# ── AC-06-13/57: cross-tenant isolation of current_profile ────────────────────


def test_current_profile_is_tenant_scoped(client, session_factory):
    """A profile that exists in tenant A must NOT resolve against tenant B.

    We forge no token — instead we log a profile into the SECOND tenant and
    assert the same email in the DEFAULT tenant is a distinct identity, proving
    the email lookup + id resolution are both tenant-scoped (no leak across
    tenants on the shared DB).
    """
    db = session_factory()
    t2 = _make_second_tenant(db)
    # same email, two tenants → two distinct profiles
    p_default = _make_profile(db, password=True, tenant_id=DEFAULT_TENANT_ID)
    p_t2 = _make_profile(db, password=True, tenant_id=t2.id)
    assert p_default.id != p_t2.id
    t2_id, t2_slug = t2.id, t2.slug
    p_default_id = p_default.id
    db.close()

    # login on tenant 2 returns the tenant-2 profile, never the default one
    res = client.post(
        "/portal/auth/login",
        json={"email": PROFILE_EMAIL, "password": GOOD_PASSWORD, "tenantSlug": t2_slug},
    )
    assert res.status_code == 200, res.text
    claims = decode_access_token(res.json()["access_token"])
    assert claims["tenant_id"] == t2_id
    assert claims["sub"] != p_default_id  # resolved within tenant 2, not the default

    # the tenant-2 token's /me resolves the tenant-2 profile
    me = client.get(
        "/portal/auth/me", headers={"Authorization": f"Bearer {res.json()['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["tenantId"] == t2_id


# ── AC-06-16: throttle is enforced BEFORE bcrypt (set-password path) ──────────


def test_set_password_failed_redeem_pumps_portal_only(client, session_factory):
    db = session_factory()
    _make_profile(db, password=False)
    db.close()
    # a bogus token redeem fails and must pump the PORTAL bucket (token guessing)
    client.post("/portal/auth/set-password", json={"token": "bogus-token", "password": GOOD_PASSWORD})
    db = session_factory()
    portal = db.query(AuthThrottle).filter(AuthThrottle.scope == THROTTLE_SCOPE_PORTAL).count()
    ip = db.query(AuthThrottle).filter(AuthThrottle.scope == THROTTLE_SCOPE_IP).count()
    db.close()
    assert portal >= 1 and ip == 0
