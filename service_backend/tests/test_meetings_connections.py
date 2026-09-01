"""Meetings connection kinds - AC-S0-4, AC-S0-5.

Both kinds are ordinary core ``connections`` rows behind the standard
``/integrations`` surface, so what is pinned here is the provider contract:
which fields exist, which of them are secret (encrypted at rest, never echoed
back), and what the Test button does - the Google error VERBATIM on failure, the
first five directory users on success.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

SERVICE_ACCOUNT_JSON = '{"type":"service_account","client_email":"svc@x.iam.gserviceaccount.com"}'


@pytest.fixture
def meetings_client(meetings_session_factory):
    def override_get_db():
        db = meetings_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._factory = meetings_session_factory
        yield c
    app.dependency_overrides.clear()


def _auth(client) -> dict:
    res = client.post(
        "/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD}
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _provider(client, key: str) -> dict:
    res = client.get("/integrations/providers", headers=_auth(client))
    assert res.status_code == 200, res.text
    for row in res.json():
        if row["provider"] == key:
            return row
    raise AssertionError(f"provider {key} not registered: {[r['provider'] for r in res.json()]}")


# ── AC-S0-4: google_dwd ──────────────────────────────────────────────────────


def test_google_dwd_is_offered_with_its_two_fields(meetings_client):
    """AC-S0-4: service-account JSON (secret) + the admin email to impersonate."""
    provider = _provider(meetings_client, "google_dwd")
    assert provider["type"] == "calendar"
    fields = {f["key"]: f for f in provider["fields"]}
    assert set(fields) == {"serviceAccountJson", "impersonateEmail"}
    assert fields["serviceAccountJson"]["secret"] is True
    assert not fields["impersonateEmail"].get("secret")
    assert provider["testLabel"]


def test_google_dwd_credentials_are_never_echoed_back(meetings_client):
    """AC-S0-4: the JSON key is encrypted at rest and write-only over the API."""
    from app.models.connection import Connection

    headers = _auth(meetings_client)
    created = meetings_client.post(
        "/integrations/connections",
        headers=headers,
        json={
            "provider": "google_dwd",
            "name": "Workspace calendar",
            "config": {"impersonateEmail": "admin@example.com"},
            "credentials": {"serviceAccountJson": SERVICE_ACCOUNT_JSON},
        },
    )
    assert created.status_code in (200, 201), created.text
    body = created.json()
    assert "credentials" not in body
    assert SERVICE_ACCOUNT_JSON not in created.text

    read = meetings_client.get(
        f"/integrations/connections/{body['id']}", headers=headers
    )
    assert SERVICE_ACCOUNT_JSON not in read.text

    db = meetings_client._factory()
    try:
        row = db.query(Connection).filter(Connection.id == body["id"]).one()
        assert SERVICE_ACCOUNT_JSON not in row.credentials_json  # Fernet ciphertext
        from app.secrets import decrypt_secret

        assert decrypt_secret(row.credentials_json)["serviceAccountJson"] == SERVICE_ACCOUNT_JSON
    finally:
        db.close()


def test_google_dwd_test_lists_the_first_five_directory_users(monkeypatch):
    """AC-S0-4: a passing test names the domain users it could actually see."""
    from modules.meetings import providers as providers_module

    monkeypatch.setattr(
        providers_module,
        "list_directory_users",
        lambda **kw: ["a@x.com", "b@x.com", "c@x.com", "d@x.com", "e@x.com"],
    )
    result = providers_module.GoogleDwdProvider().test(
        {"impersonateEmail": "admin@x.com"},
        {"serviceAccountJson": SERVICE_ACCOUNT_JSON},
    )
    assert result.ok is True
    assert "a@x.com" in result.message and "e@x.com" in result.message


def test_google_dwd_test_reports_the_google_error_verbatim(monkeypatch):
    """AC-S0-4: no "connection failed" catch-all - the operator needs the reason."""
    from modules.meetings import providers as providers_module
    from modules.meetings.calendar.base import CalendarSourceError

    def boom(**kw):
        raise CalendarSourceError(
            "Not Authorized to access this resource/api (client is unauthorized)"
        )

    monkeypatch.setattr(providers_module, "list_directory_users", boom)
    result = providers_module.GoogleDwdProvider().test(
        {"impersonateEmail": "admin@x.com"},
        {"serviceAccountJson": SERVICE_ACCOUNT_JSON},
    )
    assert result.ok is False
    assert "client is unauthorized" in result.message


def test_google_dwd_test_rejects_a_malformed_key_before_calling_google(monkeypatch):
    """A key that is not JSON is a local mistake, not a Google round trip."""
    from modules.meetings import providers as providers_module

    def never(**kw):  # pragma: no cover - must not be reached
        raise AssertionError("Google must not be called for a malformed key")

    monkeypatch.setattr(providers_module, "list_directory_users", never)
    result = providers_module.GoogleDwdProvider().test(
        {"impersonateEmail": "admin@x.com"}, {"serviceAccountJson": "not json"}
    )
    assert result.ok is False


# ── AC-S0-5: meet_bot ────────────────────────────────────────────────────────


def test_meet_bot_is_offered_with_a_secret_password(meetings_client):
    """AC-S0-5: notetaker email + password; the password is encrypted at rest."""
    provider = _provider(meetings_client, "meet_bot")
    assert provider["type"] == "meeting_bot"
    fields = {f["key"]: f for f in provider["fields"]}
    assert {"email", "password"} <= set(fields)
    assert fields["password"]["secret"] is True
    assert not fields["email"].get("secret")


def test_meet_bot_saves_without_a_live_test(meetings_client):
    """AC-S0-5: it is stored now; the bot is what verifies it, in S2."""
    from app.secrets import decrypt_secret
    from app.models.connection import Connection

    headers = _auth(meetings_client)
    created = meetings_client.post(
        "/integrations/connections",
        headers=headers,
        json={
            "provider": "meet_bot",
            "name": "Notetaker",
            "config": {"email": "notetaker@example.com"},
            "credentials": {"password": "s3cr3t-pass"},
        },
    )
    assert created.status_code in (200, 201), created.text
    assert "s3cr3t-pass" not in created.text

    db = meetings_client._factory()
    try:
        row = db.query(Connection).filter(Connection.id == created.json()["id"]).one()
        assert decrypt_secret(row.credentials_json)["password"] == "s3cr3t-pass"
    finally:
        db.close()


def test_meet_bot_offers_no_test_at_all(meetings_client):
    """AC-S0-5: there is no live test in S0, so the provider must not offer one.

    A regex check that answered ok would flip the connection to ACTIVE and show
    the operator "Connected" for an account nobody has ever signed into. The
    connection stays UNVERIFIED until the bot really signs in, in S2."""
    from app.models.connection import CONNECTION_STATUS_UNVERIFIED

    provider = _provider(meetings_client, "meet_bot")
    assert provider["testLabel"] == ""

    headers = _auth(meetings_client)
    created = meetings_client.post(
        "/integrations/connections",
        headers=headers,
        json={
            "provider": "meet_bot",
            "name": "Notetaker",
            "config": {"email": "notetaker@example.com"},
            "credentials": {"password": "s3cr3t-pass"},
        },
    )
    assert created.status_code in (200, 201), created.text
    assert created.json()["status"] == CONNECTION_STATUS_UNVERIFIED

    # And the API refuses to run one rather than inventing a verdict.
    res = meetings_client.post(
        f"/integrations/connections/{created.json()['id']}/test", headers=headers, json={}
    )
    assert res.status_code == 422, res.text

    read = meetings_client.get(
        f"/integrations/connections/{created.json()['id']}", headers=headers
    ).json()
    assert read["status"] == CONNECTION_STATUS_UNVERIFIED
    assert read["lastTestedAt"] is None


def test_a_tenant_can_hold_both_kinds_at_once(meetings_client):
    """The two kinds are separate connection TYPES, so one-active-per-type does
    not make the second one unsavable - the trap the payment/erp carve-outs
    exist for."""
    headers = _auth(meetings_client)
    first = meetings_client.post(
        "/integrations/connections",
        headers=headers,
        json={
            "provider": "google_dwd",
            "name": "Workspace calendar",
            "config": {"impersonateEmail": "admin@example.com"},
            "credentials": {"serviceAccountJson": SERVICE_ACCOUNT_JSON},
        },
    )
    assert first.status_code in (200, 201), first.text
    second = meetings_client.post(
        "/integrations/connections",
        headers=headers,
        json={
            "provider": "meet_bot",
            "name": "Notetaker",
            "config": {"email": "notetaker@example.com"},
            "credentials": {"password": "s3cr3t-pass"},
        },
    )
    assert second.status_code in (200, 201), second.text
