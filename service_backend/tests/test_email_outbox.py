"""Email outbox + dispatcher tests (plan 09 §5) - enqueue-on-send, dev-log
fallback, dispatch success/retry/backoff, tenant→platform fallback, the
per-connection rate limit and retention pruning."""
from datetime import datetime, timedelta, timezone

import pytest

from app.integrations import get_provider
from app.models.connection import Connection, CONNECTION_STATUS_UNVERIFIED
from app.models.email_outbox import (
    EmailOutbox,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OUTBOX_SENDING,
    OUTBOX_SENT,
)
from app.models.tenant import DEFAULT_TENANT_ID, PLATFORM_TENANT_ID
from app.secrets import encrypt_secret
from app.services.email_dispatcher import dispatch_pending, prune_sent
from app.services.email_service import email_service
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _connection(db, tenant_id, host="smtp.acme.com", rate=30) -> Connection:
    row = Connection(
        tenant_id=tenant_id,
        provider="smtp",
        type="email",
        name=f"SMTP {tenant_id[:8]}",
        config_json={"host": host, "port": "587", "security": "starttls",
                     "username": "mailer@acme.com", "fromEmail": "no-reply@acme.com"},
        credentials_json=encrypt_secret({"password": "s3cret"}),
        status=CONNECTION_STATUS_UNVERIFIED,
        rate_limit_per_minute=rate,
    )
    db.add(row)
    db.commit()
    return row


def _due(db) -> None:
    """Time-travel: make every pending row due now."""
    for row in db.query(EmailOutbox).filter(EmailOutbox.status == OUTBOX_PENDING):
        row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()


@pytest.fixture
def db(session_factory):
    s = session_factory()
    yield s
    s.close()


# ---- enqueue ----

def test_enqueue_without_connection_devlogs_and_marks_sent(db, capsys):
    email_service.send_invite(db, "new@acme.com", "http://x/set-password?token=t", DEFAULT_TENANT_ID)
    db.commit()
    row = db.query(EmailOutbox).one()
    assert row.status == OUTBOX_SENT  # dev fallback - no mail infra needed
    assert row.template_key == "auth.invite"  # engine key (plan 07 D7)
    assert "set-password?token=t" in capsys.readouterr().out


def test_enqueue_with_connection_goes_pending(db):
    _connection(db, DEFAULT_TENANT_ID)
    email_service.send_password_reset(db, "u@acme.com", "http://x/reset", DEFAULT_TENANT_ID)
    db.commit()
    row = db.query(EmailOutbox).one()
    assert row.status == OUTBOX_PENDING
    assert "Reset password" in row.html_body  # engine-rendered (plan 07)
    assert "http://x/reset" in row.text_body


def test_platform_connection_is_the_fallback_resolver(db):
    # No DEFAULT-tenant connection, but a PLATFORM one → still queued (not devlog).
    _connection(db, PLATFORM_TENANT_ID)
    email_service.send_verification(db, "u@acme.com", "http://x/verify", DEFAULT_TENANT_ID)
    db.commit()
    assert db.query(EmailOutbox).one().status == OUTBOX_PENDING


# ---- dispatch ----

def test_dispatch_sends_and_marks_connection_active(db, monkeypatch):
    conn = _connection(db, DEFAULT_TENANT_ID)
    email_service.send_invite(db, "a@b.co", "http://x/i", DEFAULT_TENANT_ID)
    db.commit()

    sent_calls = []
    monkeypatch.setattr(
        get_provider("smtp"), "send",
        lambda config, creds, to, subject, html, text: sent_calls.append((to, subject)),
    )
    assert dispatch_pending(db) == 1

    row = db.query(EmailOutbox).one()
    assert row.status == OUTBOX_SENT
    assert row.sent_at is not None
    assert row.connection_id == conn.id
    assert sent_calls[0][0] == "a@b.co"
    db.refresh(conn)
    assert conn.status == "ACTIVE"


def test_dispatch_failure_retries_with_backoff(db, monkeypatch):
    conn = _connection(db, DEFAULT_TENANT_ID)
    email_service.send_invite(db, "a@b.co", "http://x/i", DEFAULT_TENANT_ID)
    db.commit()

    def boom(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(get_provider("smtp"), "send", boom)
    assert dispatch_pending(db) == 0

    row = db.query(EmailOutbox).one()
    assert row.status == OUTBOX_PENDING  # back in the queue
    assert row.attempts == 1
    assert row.next_attempt_at > datetime.now(timezone.utc)  # backoff applied
    assert "connection refused" in row.last_error
    db.refresh(conn)
    assert conn.status == "ERROR"


def test_exhausted_tenant_connection_falls_back_to_platform_then_fails(db, monkeypatch):
    tenant_conn = _connection(db, DEFAULT_TENANT_ID, host="smtp.tenant.com")
    platform_conn = _connection(db, PLATFORM_TENANT_ID, host="smtp.platform.com")
    email_service.send_invite(db, "a@b.co", "http://x/i", DEFAULT_TENANT_ID)
    db.commit()

    monkeypatch.setattr(
        get_provider("smtp"), "send",
        lambda *a, **k: (_ for _ in ()).throw(OSError("down")),
    )

    # Exhaust the tenant connection (3 attempts).
    for _ in range(3):
        _due(db)
        dispatch_pending(db)

    row = db.query(EmailOutbox).one()
    assert row.used_fallback is True
    assert row.connection_id == platform_conn.id
    assert row.attempts == 0  # reset for the fallback connection
    assert row.status == OUTBOX_PENDING

    # Exhaust the platform connection too → terminal failure.
    for _ in range(3):
        _due(db)
        dispatch_pending(db)
    db.refresh(row)
    assert row.status == OUTBOX_FAILED
    assert tenant_conn.id != row.connection_id


def test_rate_limit_defers_excess_sends(db, monkeypatch):
    _connection(db, DEFAULT_TENANT_ID, rate=1)
    email_service.send_invite(db, "one@b.co", "http://x/1", DEFAULT_TENANT_ID)
    email_service.send_invite(db, "two@b.co", "http://x/2", DEFAULT_TENANT_ID)
    db.commit()

    monkeypatch.setattr(get_provider("smtp"), "send", lambda *a, **k: None)
    assert dispatch_pending(db) == 1  # second send deferred by the 1/min limit

    statuses = sorted(r.status for r in db.query(EmailOutbox).all())
    assert statuses == [OUTBOX_PENDING, OUTBOX_SENT]
    deferred = db.query(EmailOutbox).filter(EmailOutbox.status == OUTBOX_PENDING).one()
    assert deferred.next_attempt_at > datetime.now(timezone.utc)


def test_prune_sent_respects_retention(db):
    _connection(db, DEFAULT_TENANT_ID)
    email_service.send_invite(db, "a@b.co", "http://x/i", DEFAULT_TENANT_ID)
    db.commit()
    row = db.query(EmailOutbox).one()
    row.status = OUTBOX_SENT
    row.sent_at = datetime.now(timezone.utc) - timedelta(days=365)
    db.commit()

    assert prune_sent(db) == 1
    assert db.query(EmailOutbox).count() == 0


def test_stale_sending_rows_are_reclaimed_after_lease_expiry(db, monkeypatch):
    """A worker that crashed mid-send leaves rows SENDING; once the claim lease
    expires they are re-claimed and delivered (no silent orphans)."""
    _connection(db, DEFAULT_TENANT_ID)
    email_service.send_invite(db, "a@b.co", "http://x/i", DEFAULT_TENANT_ID)
    db.commit()

    # Simulate a crash: row claimed (SENDING) with an EXPIRED lease.
    row = db.query(EmailOutbox).one()
    row.status = OUTBOX_SENDING
    row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    monkeypatch.setattr(get_provider("smtp"), "send", lambda *a, **k: None)
    assert dispatch_pending(db) == 1
    db.refresh(row)
    assert row.status == OUTBOX_SENT


def test_sending_rows_within_lease_are_not_reclaimed(db, monkeypatch):
    """A row another worker is ACTIVELY sending (lease not expired) is untouchable."""
    _connection(db, DEFAULT_TENANT_ID)
    email_service.send_invite(db, "a@b.co", "http://x/i", DEFAULT_TENANT_ID)
    db.commit()
    row = db.query(EmailOutbox).one()
    row.status = OUTBOX_SENDING
    row.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=300)  # live lease
    db.commit()

    monkeypatch.setattr(get_provider("smtp"), "send", lambda *a, **k: None)
    assert dispatch_pending(db) == 0
    db.refresh(row)
    assert row.status == OUTBOX_SENDING


def test_error_connection_is_skipped_at_resolution(db):
    """A known-bad (ERROR) tenant connection must not absorb sends - resolution
    falls through to the platform default (or dev-log when none)."""
    bad = _connection(db, DEFAULT_TENANT_ID, host="smtp.broken.com")
    bad.status = "ERROR"
    platform = _connection(db, PLATFORM_TENANT_ID, host="smtp.platform.com")
    db.commit()

    email_service.send_invite(db, "a@b.co", "http://x/i", DEFAULT_TENANT_ID)
    db.commit()
    row = db.query(EmailOutbox).one()
    assert row.status == OUTBOX_PENDING

    from app.repositories.connection_repository import ConnectionRepository

    resolved = ConnectionRepository(db).resolve_for_send(DEFAULT_TENANT_ID, "smtp")
    assert resolved is not None and resolved.id == platform.id


# ---- end-to-end through the API ----

def test_admin_reset_password_lands_in_outbox(client, session_factory):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}

    db = session_factory()
    try:
        _connection(db, DEFAULT_TENANT_ID)
        from app.models.user import User

        target = db.query(User).filter(User.email == ACTIVE_EMAIL).one()
        user_id = target.id
    finally:
        db.close()

    res = client.post(f"/users/{user_id}/reset-password", headers=headers)
    assert res.status_code in (200, 204), res.text

    db = session_factory()
    try:
        row = db.query(EmailOutbox).filter(EmailOutbox.template_key == "auth.password_reset").one()
        assert row.status == OUTBOX_PENDING
        assert row.tenant_id == DEFAULT_TENANT_ID
    finally:
        db.close()
