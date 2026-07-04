"""Change-email ceremony (plan sprint-2/04) — dual confirmation.

Self-service: password re-entry → approve link to the OLD mailbox →
verify link to the NEW mailbox → email flips only on the new-side verify.
Admin path: instant change + notification to both addresses.
"""
import pytest

from app.config import settings
from app.models.email_change_request import (
    CHANGE_CANCELLED,
    CHANGE_COMPLETED,
    CHANGE_PENDING_NEW,
    CHANGE_PENDING_OLD,
    EmailChangeRequest,
)
from app.models.email_outbox import EmailOutbox
from app.models.user import User

from .conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD, INACTIVE_EMAIL

NEW_EMAIL = "fresh.address@example.com"


def _login(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _request_change(client, token, new_email=NEW_EMAIL, password=ACTIVE_PASSWORD):
    return client.post(
        "/me/change-email",
        json={"newEmail": new_email, "password": password},
        headers=_auth(token),
    )


def _row(db, user_email=ACTIVE_EMAIL) -> EmailChangeRequest:
    user = db.query(User).filter(User.email == user_email).first()
    return (
        db.query(EmailChangeRequest)
        .filter(EmailChangeRequest.user_id == user.id)
        .order_by(EmailChangeRequest.created_at.desc())
        .first()
    )


def _outbox(db, template_key: str):
    return (
        db.query(EmailOutbox)
        .filter(EmailOutbox.template_key == template_key)
        .order_by(EmailOutbox.created_at.desc())
        .all()
    )


# ---- Happy path ----


def test_full_ceremony_flips_email_only_after_verify(client, session_factory):
    token = _login(client)
    res = _request_change(client, token)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["newEmail"] == NEW_EMAIL
    assert body["status"] == CHANGE_PENDING_OLD

    db = session_factory()
    try:
        # Approve mail went to the OLD address with the approve link.
        approve_mails = _outbox(db, "account.email_change_approve")
        assert len(approve_mails) == 1
        assert approve_mails[0].to_email == ACTIVE_EMAIL
        assert "/approve-email-change?token=" in approve_mails[0].html_body

        row = _row(db)
        old_token = row.old_token
        assert row.new_token is None  # new-side token only exists after approve
    finally:
        db.close()

    # Old-side approve → PENDING_NEW + verify mail to the NEW address.
    res = client.post("/auth/approve-email-change", json={"token": old_token})
    assert res.status_code == 200, res.text

    db = session_factory()
    try:
        verify_mails = _outbox(db, "account.email_change_verify")
        assert len(verify_mails) == 1
        assert verify_mails[0].to_email == NEW_EMAIL
        assert "/verify-email-change?token=" in verify_mails[0].html_body
        row = _row(db)
        assert row.status == CHANGE_PENDING_NEW
        new_token = row.new_token
        # Email has NOT flipped yet.
        assert db.query(User).filter(User.email == ACTIVE_EMAIL).first() is not None
    finally:
        db.close()

    # New-side verify → the flip.
    res = client.post("/auth/verify-email-change", json={"token": new_token})
    assert res.status_code == 200, res.text

    db = session_factory()
    try:
        assert db.query(User).filter(User.email == NEW_EMAIL).first() is not None
        assert db.query(User).filter(User.email == ACTIVE_EMAIL).first() is None
        # Final notice goes to the PREVIOUS address.
        notices = _outbox(db, "account.email_change_notice")
        assert any(m.to_email == ACTIVE_EMAIL for m in notices)
        assert _row(db, NEW_EMAIL).status == CHANGE_COMPLETED
    finally:
        db.close()

    # Sign-in: NEW email works, OLD email is gone (uniform 401).
    assert (
        client.post(
            "/auth/login", json={"email": NEW_EMAIL, "password": ACTIVE_PASSWORD}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
        ).status_code
        == 401
    )


def test_pending_status_readable_and_cancellable(client, session_factory):
    token = _login(client)
    assert client.get("/me/change-email", headers=_auth(token)).json() is None

    _request_change(client, token)
    pending = client.get("/me/change-email", headers=_auth(token)).json()
    assert pending["newEmail"] == NEW_EMAIL
    assert pending["status"] == CHANGE_PENDING_OLD

    res = client.delete("/me/change-email", headers=_auth(token))
    assert res.status_code == 204
    assert client.get("/me/change-email", headers=_auth(token)).json() is None

    # The cancelled request's approve token is dead.
    db = session_factory()
    try:
        row = _row(db)
        assert row.status == CHANGE_CANCELLED
        old_token = row.old_token
    finally:
        db.close()
    res = client.post("/auth/approve-email-change", json={"token": old_token})
    assert res.status_code == 400


def test_re_request_invalidates_prior_request(client, session_factory):
    token = _login(client)
    _request_change(client, token, new_email="first.choice@example.com")
    db = session_factory()
    try:
        first_token = _row(db).old_token
    finally:
        db.close()

    _request_change(client, token, new_email="second.choice@example.com")
    # The superseded approve link no longer works…
    assert (
        client.post("/auth/approve-email-change", json={"token": first_token}).status_code
        == 400
    )
    # …and the outstanding request is the second one.
    pending = client.get("/me/change-email", headers=_auth(token)).json()
    assert pending["newEmail"] == "second.choice@example.com"


# ---- Failure paths: nothing ever flips ----


def test_wrong_password_rejected_and_throttle_counted(client):
    token = _login(client)
    # 400 (NOT 401 — the api-client treats 401-with-token as session death).
    for _ in range(settings.throttle_email_max_fails):
        res = _request_change(client, token, password="not-the-password")
        assert res.status_code == 400
    # Password failures count like login failures: the account bucket locks.
    res = _request_change(client, token, password="not-the-password")
    assert res.status_code == 429
    assert "Retry-After" in res.headers
    # No request row was ever created.
    assert client.get("/me/change-email", headers=_auth(token)).json() is None


def test_same_email_rejected(client):
    token = _login(client)
    res = _request_change(client, token, new_email=ACTIVE_EMAIL)
    assert res.status_code == 422


def test_bad_and_reused_tokens_4xx(client, session_factory):
    token = _login(client)
    _request_change(client, token)
    db = session_factory()
    try:
        old_token = _row(db).old_token
    finally:
        db.close()

    # Garbage tokens.
    assert client.post("/auth/approve-email-change", json={"token": "nope"}).status_code == 400
    assert client.post("/auth/verify-email-change", json={"token": "nope"}).status_code == 400
    # Approve token redeemed on the WRONG endpoint fails.
    assert client.post("/auth/verify-email-change", json={"token": old_token}).status_code == 400

    # Proper approve once → reuse dies.
    assert client.post("/auth/approve-email-change", json={"token": old_token}).status_code == 200
    assert client.post("/auth/approve-email-change", json={"token": old_token}).status_code == 400

    db = session_factory()
    try:
        new_token = _row(db).new_token
    finally:
        db.close()
    assert client.post("/auth/verify-email-change", json={"token": new_token}).status_code == 200
    assert client.post("/auth/verify-email-change", json={"token": new_token}).status_code == 400


def test_expired_request_redeems_nothing(client, session_factory):
    from datetime import datetime, timedelta, timezone

    token = _login(client)
    _request_change(client, token)
    db = session_factory()
    try:
        row = _row(db)
        old_token = row.old_token
        row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        db.add(row)
        db.commit()
    finally:
        db.close()

    assert client.post("/auth/approve-email-change", json={"token": old_token}).status_code == 400
    # An expired request no longer shows as pending.
    assert client.get("/me/change-email", headers=_auth(token)).json() is None


def test_typoed_new_email_never_flips_anything(client, session_factory):
    """The whole point of dual confirmation: an undeliverable new address
    leaves the account untouched — the verify link is simply never redeemed."""
    token = _login(client)
    _request_change(client, token, new_email="typo@nowhere-real.example.com")
    db = session_factory()
    try:
        old_token = _row(db).old_token
    finally:
        db.close()
    client.post("/auth/approve-email-change", json={"token": old_token})

    # Nobody ever clicks the verify link. The account email is unchanged.
    assert (
        client.post(
            "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
        ).status_code
        == 200
    )


def test_uniqueness_race_409_at_verify(client, session_factory):
    """Request is accepted uniformly (no enumeration), but the FLIP re-checks
    uniqueness transactionally — the race loses with a 409."""
    token = _login(client)
    res = _request_change(client, token, new_email=INACTIVE_EMAIL)
    assert res.status_code == 200  # uniform — never reveals the address is taken

    db = session_factory()
    try:
        old_token = _row(db).old_token
    finally:
        db.close()
    assert client.post("/auth/approve-email-change", json={"token": old_token}).status_code == 200

    db = session_factory()
    try:
        new_token = _row(db).new_token
    finally:
        db.close()
    res = client.post("/auth/verify-email-change", json={"token": new_token})
    assert res.status_code == 409

    # Nothing flipped.
    assert (
        client.post(
            "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
        ).status_code
        == 200
    )


# ---- Admin instant path ----


def _inactive_user_id(db) -> str:
    return db.query(User).filter(User.email == INACTIVE_EMAIL).first().id


def test_admin_changes_someone_elses_email_instantly(client, session_factory):
    token = _login(client)  # demo admin holds users.update
    db = session_factory()
    try:
        target_id = _inactive_user_id(db)
    finally:
        db.close()

    res = client.patch(
        f"/users/{target_id}",
        json={"email": "renamed.user@example.com"},
        headers=_auth(token),
    )
    assert res.status_code == 200, res.text
    assert res.json()["email"] == "renamed.user@example.com"

    db = session_factory()
    try:
        # Immediate flip + notice to BOTH addresses.
        assert db.query(User).filter(User.email == "renamed.user@example.com").first() is not None
        notices = _outbox(db, "account.email_change_notice")
        recipients = {m.to_email for m in notices}
        assert INACTIVE_EMAIL in recipients
        assert "renamed.user@example.com" in recipients
    finally:
        db.close()


def test_admin_cannot_bypass_own_ceremony(client, session_factory):
    token = _login(client)
    db = session_factory()
    try:
        own_id = db.query(User).filter(User.email == ACTIVE_EMAIL).first().id
    finally:
        db.close()

    res = client.patch(
        f"/users/{own_id}",
        json={"email": "sneaky@example.com"},
        headers=_auth(token),
    )
    assert res.status_code == 409
    db = session_factory()
    try:
        assert db.query(User).filter(User.email == ACTIVE_EMAIL).first() is not None
    finally:
        db.close()


def test_admin_duplicate_email_409(client, session_factory):
    token = _login(client)
    db = session_factory()
    try:
        target_id = _inactive_user_id(db)
    finally:
        db.close()
    res = client.patch(
        f"/users/{target_id}",
        json={"email": ACTIVE_EMAIL},
        headers=_auth(token),
    )
    assert res.status_code == 409


def test_verify_collision_with_trashed_user_is_409_not_500(client, session_factory):
    """uq_users_tenant_email covers trashed rows — the uniqueness guard must
    too, or the flip 500s where a clean 409 was intended (review fix)."""
    token = _login(client)
    db = session_factory()
    try:
        target = db.query(User).filter(User.email == INACTIVE_EMAIL).first()
        target.is_trashed = True
        db.add(target)
        db.commit()
    finally:
        db.close()

    _request_change(client, token, new_email=INACTIVE_EMAIL)
    db = session_factory()
    try:
        old_token = _row(db).old_token
    finally:
        db.close()
    assert client.post("/auth/approve-email-change", json={"token": old_token}).status_code == 200
    db = session_factory()
    try:
        new_token = _row(db).new_token
    finally:
        db.close()
    res = client.post("/auth/verify-email-change", json={"token": new_token})
    assert res.status_code == 409  # not a 500


def test_change_email_success_does_not_clear_login_throttle(client):
    """A correct password on /me/change-email must NOT reset the LOGIN
    lockout counter (review fix — session-holders can't wipe brute-force
    state)."""
    token = _login(client)
    # 4 login failures (one below the lock threshold of 5)…
    for _ in range(settings.throttle_email_max_fails - 1):
        res = client.post(
            "/auth/login", json={"email": ACTIVE_EMAIL, "password": "bad-pass-1!"}
        )
        assert res.status_code == 401
    # …a successful change-email request in between…
    assert _request_change(client, token).status_code == 200
    # …then the 5th failure still locks: the counter was NOT reset.
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": "bad-pass-1!"}
    )
    assert res.status_code == 401
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    assert res.status_code == 429


def test_admin_change_clears_verified_badge(client, session_factory):
    """The new mailbox never proved deliverability — email_verified_at must
    not carry over from the previous address (review fix)."""
    token = _login(client)
    db = session_factory()
    try:
        target = db.query(User).filter(User.email == INACTIVE_EMAIL).first()
        target.email_verified_at = target.created_at  # pretend it was verified
        db.add(target)
        db.commit()
        target_id = target.id
    finally:
        db.close()

    res = client.patch(
        f"/users/{target_id}",
        json={"email": "unproven@example.com"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    assert res.json()["emailVerifiedAt"] is None


def test_service_email_change_fails_closed_without_actor(client, session_factory):
    """An internal caller that can't name the actor must not get the instant
    path (review fix — an omitted Optional kwarg is not a bypass)."""
    from app.services.user_service import SelfEmailChange, UserService

    db = session_factory()
    try:
        target = db.query(User).filter(User.email == INACTIVE_EMAIL).first()
        with pytest.raises(SelfEmailChange):
            UserService(db).update(target.id, email="anything@example.com")
    finally:
        db.close()


def test_admin_patch_without_email_still_works(client, session_factory):
    """Email stays optional — a plain profile save must not be affected."""
    token = _login(client)
    db = session_factory()
    try:
        target_id = _inactive_user_id(db)
    finally:
        db.close()
    res = client.patch(
        f"/users/{target_id}",
        json={"name": "Renamed Person"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed Person"
    assert res.json()["email"] == INACTIVE_EMAIL
