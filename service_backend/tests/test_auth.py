"""Auth endpoint + security tests."""
import time

from app.models.tenant import DEFAULT_TENANT_ID
from app.security import decode_access_token

from .conftest import (
    ACTIVE_EMAIL,
    ACTIVE_PASSWORD,
    INACTIVE_EMAIL,
    INACTIVE_PASSWORD,
)

GENERIC_ERROR = "Invalid email or password."


# ── Login: happy path ────────────────────────────────────────────────────────
def test_login_success_returns_token_and_user(client):
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == ACTIVE_EMAIL
    assert body["user"]["tenantId"] == DEFAULT_TENANT_ID


def test_login_token_carries_tenant_claim(client):
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    claims = decode_access_token(res.json()["access_token"])
    assert claims["tenant_id"] == DEFAULT_TENANT_ID
    assert claims["sub"]


# ── Login: failure modes ─────────────────────────────────────────────────────
def test_wrong_password_is_401_generic(client):
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": "wrongpass"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == GENERIC_ERROR


def test_unknown_email_is_401_not_404(client):
    res = client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "whatever1"}
    )
    assert res.status_code == 401  # NOT 404 - no enumeration
    assert res.json()["detail"] == GENERIC_ERROR


def test_no_user_enumeration_identical_responses(client):
    wrong_pw = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": "wrongpass"}
    )
    unknown = client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "wrongpass"}
    )
    assert wrong_pw.status_code == unknown.status_code
    assert wrong_pw.json() == unknown.json()


def test_inactive_account_is_403(client):
    res = client.post(
        "/auth/login",
        json={"email": INACTIVE_EMAIL, "password": INACTIVE_PASSWORD},
    )
    assert res.status_code == 403


def test_unknown_email_path_still_runs_bcrypt(client):
    """Timing parity: the not-found path must do a bcrypt compare, so it can't
    return near-instantly (which would leak that the email doesn't exist)."""
    start = time.perf_counter()
    client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "whatever1"}
    )
    elapsed = time.perf_counter() - start
    assert elapsed > 0.01  # bcrypt verify is ~tens of ms; a no-op would be <1ms


# ── Signup: password policy + duplicates ─────────────────────────────────────
def test_signup_rejects_short_password(client):
    res = client.post(
        "/auth/signup", json={"email": "new@example.com", "password": "short"}
    )
    assert res.status_code == 422  # Pydantic min_length


def test_signup_long_password_does_not_500(client):
    """Review #1: password over bcrypt's 72-byte limit must not crash the API."""
    res = client.post(
        "/auth/signup",
        json={"email": "long@example.com", "password": "a" * 200},
    )
    # rejected by policy (422), never a 500
    assert res.status_code == 422


def test_signup_reusing_trashed_email_is_409_not_500(client, session_factory, monkeypatch):
    """Review #2: a soft-deleted user's email reused on signup → 409, not a
    500 from the (tenant_id, email) unique constraint."""
    from app.config import settings
    from app.models import User, UserStatus
    from app.models.tenant import DEFAULT_TENANT_ID
    from app.security import hash_password

    monkeypatch.setattr(settings, "signup_enabled", True)  # parked by default (plan 10 D3)

    db = session_factory()
    db.add(
        User(
            tenant_id=DEFAULT_TENANT_ID,
            email="trashed@example.com",
            password=hash_password("whatever1"),
            status=UserStatus.ACTIVE.value,
            is_trashed=True,
        )
    )
    db.commit()
    db.close()

    res = client.post(
        "/auth/signup",
        json={"email": "trashed@example.com", "password": "LongEnough1!"},
    )
    assert res.status_code == 409


def test_me_rejects_token_from_another_tenant(client):
    """Review #3: get_current_user is tenant-scoped - a token whose tenant_id
    doesn't match the user's tenant must not authenticate."""
    from app.security import create_access_token

    user_id = (
        client.post(
            "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
        )
        .json()["user"]["id"]
    )
    forged = create_access_token({"sub": user_id, "tenant_id": "some-other-tenant"})
    res = client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert res.status_code == 401


def test_signup_success_then_duplicate_conflict(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "signup_enabled", True)  # parked by default (plan 10 D3)
    ok = client.post(
        "/auth/signup",
        json={"email": "new@example.com", "password": "LongEnough1!", "name": "New"},
    )
    assert ok.status_code == 201
    assert ok.json()["tenantId"] == DEFAULT_TENANT_ID

    dup = client.post(
        "/auth/signup",
        json={"email": "new@example.com", "password": "LongEnough1!"},
    )
    assert dup.status_code == 409


# ── /me protected endpoint ───────────────────────────────────────────────────
def test_me_requires_and_accepts_token(client):
    token = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    ).json()["access_token"]

    unauth = client.get("/auth/me")
    assert unauth.status_code == 401

    res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["email"] == ACTIVE_EMAIL
    assert res.json()["tenantId"] == DEFAULT_TENANT_ID
