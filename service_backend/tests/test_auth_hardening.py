"""Auth hardening tests (plan 10): forgot-password (enumeration-safe),
token single-use/expiry/invalidation, rememberMe expiry, signup kill-switch,
and the Postgres-backed dual (email + IP) throttle.
"""
from datetime import timedelta

from app.config import settings
from app.models.email_outbox import EmailOutbox
from app.models.invite_token import InviteToken
from app.models.tenant import DEFAULT_TENANT_ID
from app.models.user import User
from app.security import decode_access_token

from .conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD, INACTIVE_EMAIL

UNIFORM_MESSAGE = "If an account exists for this email, a reset link has been sent."
STRONG_PASSWORD = "NewPass1!"


def _reset_tokens(db, email: str):
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        return []
    return (
        db.query(InviteToken)
        .filter(InviteToken.user_id == user.id)
        .order_by(InviteToken.created_at)
        .all()
    )


# ── Forgot-password: enumeration safety ──────────────────────────────────────


def test_forgot_password_known_email_enqueues_reset(client, session_factory):
    res = client.post("/auth/forgot-password", json={"email": ACTIVE_EMAIL})
    assert res.status_code == 200
    assert res.json() == {"message": UNIFORM_MESSAGE}

    db = session_factory()
    try:
        rows = (
            db.query(EmailOutbox)
            .filter(
                EmailOutbox.to_email == ACTIVE_EMAIL,
                EmailOutbox.template_key == "auth.password_reset",
            )
            .all()
        )
        assert len(rows) == 1
        # The redeem link points at the frontend change-password page.
        assert "/change-password?token=" in rows[0].html_body
        tokens = _reset_tokens(db, ACTIVE_EMAIL)
        assert len(tokens) == 1
    finally:
        db.close()


def test_forgot_password_unknown_email_same_response_no_email(client, session_factory):
    known = client.post("/auth/forgot-password", json={"email": ACTIVE_EMAIL})
    unknown = client.post(
        "/auth/forgot-password", json={"email": "ghost@example.com"}
    )
    # Identical status + body - no enumeration.
    assert unknown.status_code == known.status_code == 200
    assert unknown.json() == known.json()

    db = session_factory()
    try:
        assert (
            db.query(EmailOutbox)
            .filter(EmailOutbox.to_email == "ghost@example.com")
            .count()
            == 0
        )
    finally:
        db.close()


def test_forgot_password_inactive_user_sends_nothing(client, session_factory):
    res = client.post("/auth/forgot-password", json={"email": INACTIVE_EMAIL})
    assert res.status_code == 200
    assert res.json() == {"message": UNIFORM_MESSAGE}

    db = session_factory()
    try:
        assert (
            db.query(EmailOutbox)
            .filter(EmailOutbox.to_email == INACTIVE_EMAIL)
            .count()
            == 0
        )
    finally:
        db.close()


def test_forgot_password_unknown_tenant_sends_nothing(client, session_factory):
    res = client.post(
        "/auth/forgot-password",
        json={"email": ACTIVE_EMAIL, "tenantSlug": "no-such-tenant"},
    )
    assert res.status_code == 200
    assert res.json() == {"message": UNIFORM_MESSAGE}

    db = session_factory()
    try:
        assert db.query(EmailOutbox).count() == 0
    finally:
        db.close()


# ── Token lifecycle: redeem, single-use, expiry, invalidation ────────────────


def test_forgot_password_token_redeems_and_is_single_use(client, session_factory):
    client.post("/auth/forgot-password", json={"email": ACTIVE_EMAIL})
    db = session_factory()
    try:
        token = _reset_tokens(db, ACTIVE_EMAIL)[-1].token
    finally:
        db.close()

    res = client.post(
        "/auth/set-password", json={"token": token, "password": STRONG_PASSWORD}
    )
    assert res.status_code == 200

    # Old password rejected, new password works.
    old = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    assert old.status_code == 401
    new = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": STRONG_PASSWORD}
    )
    assert new.status_code == 200

    # Single-use: the same token cannot be redeemed twice.
    again = client.post(
        "/auth/set-password", json={"token": token, "password": "Another1!"}
    )
    assert again.status_code == 400


def test_expired_reset_token_is_rejected(client, session_factory):
    client.post("/auth/forgot-password", json={"email": ACTIVE_EMAIL})
    db = session_factory()
    try:
        row = _reset_tokens(db, ACTIVE_EMAIL)[-1]
        row.expires_at = row.expires_at - timedelta(days=365)
        token = row.token
        db.commit()
    finally:
        db.close()

    res = client.post(
        "/auth/set-password", json={"token": token, "password": STRONG_PASSWORD}
    )
    assert res.status_code == 400


def test_new_forgot_password_invalidates_prior_tokens(client, session_factory):
    client.post("/auth/forgot-password", json={"email": ACTIVE_EMAIL})
    client.post("/auth/forgot-password", json={"email": ACTIVE_EMAIL})

    db = session_factory()
    try:
        tokens = _reset_tokens(db, ACTIVE_EMAIL)
        assert len(tokens) == 2
        first, second = tokens[0].token, tokens[1].token
    finally:
        db.close()

    # The superseded token is dead; the fresh one redeems.
    res_old = client.post(
        "/auth/set-password", json={"token": first, "password": STRONG_PASSWORD}
    )
    assert res_old.status_code == 400
    res_new = client.post(
        "/auth/set-password", json={"token": second, "password": STRONG_PASSWORD}
    )
    assert res_new.status_code == 200


def test_reset_token_ttl_comes_from_settings(client, session_factory):
    client.post("/auth/forgot-password", json={"email": ACTIVE_EMAIL})
    db = session_factory()
    try:
        row = _reset_tokens(db, ACTIVE_EMAIL)[-1]
        ttl = row.expires_at - row.created_at
        assert abs(ttl.total_seconds() - settings.reset_token_ttl_minutes * 60) < 120
    finally:
        db.close()


# ── set-password: server-side password policy ────────────────────────────────


def test_set_password_enforces_policy(client, session_factory):
    client.post("/auth/forgot-password", json={"email": ACTIVE_EMAIL})
    db = session_factory()
    try:
        token = _reset_tokens(db, ACTIVE_EMAIL)[-1].token
    finally:
        db.close()

    for weak in ["short1!", "alllower1!", "ALLUPPER1!", "NoDigits!!", "NoSpecial11Aa"]:
        res = client.post(
            "/auth/set-password", json={"token": token, "password": weak}
        )
        assert res.status_code == 422, f"{weak!r} should violate the policy"


# ── rememberMe: JWT expiry boundary (plan 10 D4) ─────────────────────────────


def _login_exp_minutes(client, remember_me) -> float:
    payload = {"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    if remember_me is not None:
        payload["rememberMe"] = remember_me
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 200
    claims = decode_access_token(res.json()["access_token"])
    import time

    return (claims["exp"] - time.time()) / 60


def test_login_default_expiry_is_short(client):
    minutes = _login_exp_minutes(client, None)
    assert abs(minutes - settings.access_token_expire_minutes) < 5


def test_login_remember_me_expiry_is_long(client):
    minutes = _login_exp_minutes(client, True)
    assert abs(minutes - settings.remember_me_expire_minutes) < 5


def test_login_remember_me_false_stays_short(client):
    minutes = _login_exp_minutes(client, False)
    assert abs(minutes - settings.access_token_expire_minutes) < 5


# ── Signup kill-switch (plan 10 D3) ──────────────────────────────────────────


def test_signup_is_404_while_disabled(client):
    res = client.post(
        "/auth/signup",
        json={"email": "new@example.com", "password": STRONG_PASSWORD},
    )
    assert res.status_code == 404


def test_signup_works_when_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "signup_enabled", True)
    res = client.post(
        "/auth/signup",
        json={"email": "new@example.com", "password": STRONG_PASSWORD},
    )
    assert res.status_code == 201


# ── Throttle: email counter (5 fails / 15 min → 15 min lock) ─────────────────


def _fail_login(client, email, n=1):
    last = None
    for _ in range(n):
        last = client.post(
            "/auth/login", json={"email": email, "password": "definitely-wrong"}
        )
    return last


def test_email_throttle_locks_after_max_fails(client):
    last = _fail_login(client, ACTIVE_EMAIL, settings.throttle_email_max_fails)
    assert last.status_code == 401  # up to the limit: uniform 401

    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    assert res.status_code == 429
    assert "Retry-After" in res.headers
    assert int(res.headers["Retry-After"]) > 0


def test_email_throttle_lock_expires(client, session_factory):
    _fail_login(client, ACTIVE_EMAIL, settings.throttle_email_max_fails)

    # Rewind the lock + window as if the lock period elapsed.
    from app.models.auth_throttle import AuthThrottle

    db = session_factory()
    try:
        for row in db.query(AuthThrottle).all():
            row.window_start = row.window_start - timedelta(hours=2)
            if row.locked_until is not None:
                row.locked_until = row.locked_until - timedelta(hours=2)
        db.commit()
    finally:
        db.close()

    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    assert res.status_code == 200


def test_success_resets_email_counter(client):
    max_fails = settings.throttle_email_max_fails
    _fail_login(client, ACTIVE_EMAIL, max_fails - 1)
    ok = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    assert ok.status_code == 200

    # Counter was reset - another (max-1) fails still get the uniform 401.
    last = _fail_login(client, ACTIVE_EMAIL, max_fails - 1)
    assert last.status_code == 401


def test_throttled_response_does_not_leak_validity(client):
    """The 429 must not depend on whether the password would have been right."""
    _fail_login(client, ACTIVE_EMAIL, settings.throttle_email_max_fails)
    wrong = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": "definitely-wrong"}
    )
    right = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    assert wrong.status_code == right.status_code == 429


# ── Throttle: IP counter ─────────────────────────────────────────────────────


def test_ip_throttle_across_emails(client, monkeypatch):
    monkeypatch.setattr(settings, "throttle_ip_max_fails", 4)
    # 4 fails across DIFFERENT emails - none trips the email counter.
    for i in range(4):
        res = client.post(
            "/auth/login",
            json={"email": f"user{i}@example.com", "password": "definitely-wrong"},
        )
        assert res.status_code == 401
    res = client.post(
        "/auth/login",
        json={"email": "another@example.com", "password": "definitely-wrong"},
    )
    assert res.status_code == 429
    assert "Retry-After" in res.headers


def test_forgot_password_counts_toward_ip_throttle(client, monkeypatch):
    monkeypatch.setattr(settings, "throttle_ip_max_fails", 3)
    for _ in range(3):
        res = client.post(
            "/auth/forgot-password", json={"email": "ghost@example.com"}
        )
        assert res.status_code == 200
    res = client.post("/auth/forgot-password", json={"email": "ghost@example.com"})
    assert res.status_code == 429


def test_set_password_failures_count_toward_ip_throttle(client, monkeypatch):
    monkeypatch.setattr(settings, "throttle_ip_max_fails", 3)
    for _ in range(3):
        res = client.post(
            "/auth/set-password",
            json={"token": "bogus-token", "password": STRONG_PASSWORD},
        )
        assert res.status_code == 400
    res = client.post(
        "/auth/set-password",
        json={"token": "bogus-token", "password": STRONG_PASSWORD},
    )
    assert res.status_code == 429


# ── Client IP resolution (trust_proxy_headers) ───────────────────────────────


def test_forwarded_for_ignored_by_default(client, monkeypatch):
    monkeypatch.setattr(settings, "throttle_ip_max_fails", 2)
    # Spoofed XFF must NOT give the attacker fresh counters per header value.
    for i in range(2):
        client.post(
            "/auth/login",
            json={"email": f"u{i}@example.com", "password": "definitely-wrong"},
            headers={"X-Forwarded-For": f"10.0.0.{i}"},
        )
    res = client.post(
        "/auth/login",
        json={"email": "u9@example.com", "password": "definitely-wrong"},
        headers={"X-Forwarded-For": "10.0.0.99"},
    )
    assert res.status_code == 429


def test_forwarded_for_honored_behind_trusted_proxy(client, monkeypatch):
    monkeypatch.setattr(settings, "throttle_ip_max_fails", 2)
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    for i in range(2):
        client.post(
            "/auth/login",
            json={"email": f"u{i}@example.com", "password": "definitely-wrong"},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
    # Same client IP, different first-hop → separate counter.
    res = client.post(
        "/auth/login",
        json={"email": "u9@example.com", "password": "definitely-wrong"},
        headers={"X-Forwarded-For": "10.0.0.2"},
    )
    assert res.status_code == 401
