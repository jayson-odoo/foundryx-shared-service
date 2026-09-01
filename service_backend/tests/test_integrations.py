"""Integration core tests (plan 09) - provider catalog, connection CRUD,
write-only credentials (encryption at rest), inline test + status upkeep,
tenant scoping."""
from app.integrations import get_provider
from app.integrations.base import TestResult
from app.models.connection import Connection
from app.secrets import decrypt_secret
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD, PLATFORM_EMAIL, PLATFORM_PASSWORD


def _login(client, email, password, tenant_slug=None):
    payload = {"email": email, "password": password}
    if tenant_slug is not None:
        payload["tenantSlug"] = tenant_slug
    return client.post("/auth/login", json=payload)


def _headers(res) -> dict:
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _demo_headers(client):
    return _headers(_login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD))


def _platform_headers(client):
    return _headers(_login(client, PLATFORM_EMAIL, PLATFORM_PASSWORD, "platform"))


SMTP_PAYLOAD = {
    "provider": "smtp",
    "name": "Acme Mail",
    "config": {
        "host": "smtp.acme.com",
        "port": "587",
        "security": "starttls",
        "username": "mailer@acme.com",
        "fromEmail": "no-reply@acme.com",
        "fromName": "Acme",
    },
    "credentials": {"password": "s3cret"},
    "rateLimitPerMinute": 30,
}


def _create(client, headers, payload=None):
    res = client.post("/integrations/connections", json=payload or SMTP_PAYLOAD, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


# ---- catalog ----

def test_providers_lists_smtp_with_config_schema(client):
    res = client.get("/integrations/providers", headers=_demo_headers(client))
    assert res.status_code == 200, res.text
    smtp = next(p for p in res.json() if p["provider"] == "smtp")
    assert smtp["type"] == "email"
    keys = [f["key"] for f in smtp["fields"]]
    assert {"host", "port", "security", "username", "password", "fromEmail"} <= set(keys)
    password_field = next(f for f in smtp["fields"] if f["key"] == "password")
    assert password_field["secret"] is True
    assert smtp["testTarget"] is not None  # optional targeted test offered


def test_endpoints_require_auth(client):
    assert client.get("/integrations/providers").status_code == 401
    assert client.get("/integrations/connections").status_code == 401


# ---- CRUD + write-only credentials ----

def test_create_connection_encrypts_credentials_and_never_echoes(client, session_factory):
    h = _demo_headers(client)
    created = _create(client, h)
    assert created["status"] == "UNVERIFIED"
    assert created["config"]["host"] == "smtp.acme.com"
    assert "credentials" not in created
    assert "password" not in str(created)

    db = session_factory()
    try:
        row = db.get(Connection, created["id"])
        assert row.credentials_json != ""
        assert "s3cret" not in row.credentials_json  # encrypted at rest
        assert decrypt_secret(row.credentials_json) == {"password": "s3cret"}
    finally:
        db.close()


def test_embed_connection_hidden_from_integrations(client):
    """The embed ``omnichannel_shared`` row lives in core ``connections`` but is
    NOT part of the Integrations surface - it must never appear in the list
    (where Disconnect would destroy it + mint a new connection id, breaking every
    consumer's embed iframe) nor resolve on detail."""
    h = _demo_headers(client)
    # Enable the embed connection (creates the omnichannel_shared row).
    assert client.post("/omnichannel/embed-config/enable", headers=h).status_code == 200
    embed_id = client.get("/omnichannel/embed-config", headers=h).json()["connectionId"]
    assert embed_id
    # A normal SMTP connection for contrast - that one DOES show.
    smtp = _create(client, h)

    ids = [c["id"] for c in client.get("/integrations/connections", headers=h).json()["data"]]
    assert smtp["id"] in ids
    assert embed_id not in ids
    # Detail refuses it too (so test/disconnect can't reach it).
    assert client.get(f"/integrations/connections/{embed_id}", headers=h).status_code == 404


def test_duplicate_provider_conflicts(client):
    h = _demo_headers(client)
    _create(client, h)
    res = client.post("/integrations/connections", json=SMTP_PAYLOAD, headers=h)
    assert res.status_code == 409


SQL_DATABASE_PAYLOAD = {
    "provider": "sql_database",
    "name": "AED 2024",
    "config": {
        "dbType": "mssql",
        "host": "db.acme.com",
        "port": "1433",
        "database": "AED_2024",
        "username": "readonly_user",
    },
    "credentials": {"password": "s3cret"},
}


def test_erp_provider_allows_several_connections_per_tenant(client):
    """``uq_connection_tenant_provider`` carves ``type='erp'`` out of the
    one-per-provider rule (plan 22: one SQL connection per AutoCount company
    database) - the service's 409 must mirror the index, not pre-empt it."""
    h = _demo_headers(client)
    first = _create(client, h, SQL_DATABASE_PAYLOAD)
    second = _create(
        client,
        h,
        {
            **SQL_DATABASE_PAYLOAD,
            "name": "AED 2025",
            "config": {**SQL_DATABASE_PAYLOAD["config"], "database": "AED_2025"},
        },
    )
    assert first["id"] != second["id"]
    assert first["type"] == second["type"] == "erp"
    ids = [c["id"] for c in client.get("/integrations/connections", headers=h).json()["data"]]
    assert first["id"] in ids and second["id"] in ids
    # Update never changes provider/type, and names are not unique - renaming
    # the second onto the first's name is a plain 200.
    res = client.patch(
        f"/integrations/connections/{second['id']}", json={"name": "AED 2024"}, headers=h
    )
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "AED 2024"
    # Non-erp providers keep the one-per-provider rule untouched.
    _create(client, h)  # smtp
    assert client.post("/integrations/connections", json=SMTP_PAYLOAD, headers=h).status_code == 409


def test_unknown_provider_rejected(client):
    h = _demo_headers(client)
    res = client.post(
        "/integrations/connections",
        json={**SMTP_PAYLOAD, "provider": "carrier-pigeon"},
        headers=h,
    )
    assert res.status_code == 422


def test_update_blank_credentials_keep_stored_secret(client, session_factory):
    h = _demo_headers(client)
    created = _create(client, h)
    res = client.patch(
        f"/integrations/connections/{created['id']}",
        json={"name": "Acme Mail v2", "config": {**SMTP_PAYLOAD["config"], "host": "smtp2.acme.com"},
              "credentials": {}},
        headers=h,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "Acme Mail v2"
    assert body["config"]["host"] == "smtp2.acme.com"
    assert body["status"] == "UNVERIFIED"  # config change invalidates verification

    db = session_factory()
    try:
        row = db.get(Connection, created["id"])
        assert decrypt_secret(row.credentials_json) == {"password": "s3cret"}  # kept
    finally:
        db.close()


def test_update_partial_config_merges_not_wipes(client, session_factory):
    """A partial config PATCH must merge with stored keys (sibling credentials
    merge too) - never silently wipe omitted keys."""
    h = _demo_headers(client)
    created = _create(client, h)
    res = client.patch(
        f"/integrations/connections/{created['id']}",
        json={"config": {"host": "smtp2.acme.com"}},
        headers=h,
    )
    assert res.status_code == 200, res.text
    cfg = res.json()["config"]
    assert cfg["host"] == "smtp2.acme.com"
    assert cfg["port"] == "587"            # kept
    assert cfg["fromEmail"] == "no-reply@acme.com"  # kept


def test_undecryptable_credentials_fail_cleanly_not_500(client, session_factory):
    """Stored ciphertext from a rotated/lost key → clean test failure + update
    recovery path, never an unhandled 500."""
    h = _demo_headers(client)
    created = _create(client, h)
    db = session_factory()
    try:
        row = db.get(Connection, created["id"])
        row.credentials_json = "gAAAAAB-not-decryptable-garbage"
        db.commit()
    finally:
        db.close()

    res = client.post(f"/integrations/connections/{created['id']}/test", json={}, headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is False
    assert "decrypt" in body["message"].lower() or "key" in body["message"].lower()

    # Recovery: writing a fresh password replaces the dead blob.
    res = client.patch(
        f"/integrations/connections/{created['id']}",
        json={"credentials": {"password": "fresh"}},
        headers=h,
    )
    assert res.status_code == 200, res.text
    db = session_factory()
    try:
        assert decrypt_secret(db.get(Connection, created["id"]).credentials_json) == {"password": "fresh"}
    finally:
        db.close()


def test_update_with_new_password_rotates_secret(client, session_factory):
    h = _demo_headers(client)
    created = _create(client, h)
    res = client.patch(
        f"/integrations/connections/{created['id']}",
        json={"credentials": {"password": "n3w-secret"}},
        headers=h,
    )
    assert res.status_code == 200, res.text
    db = session_factory()
    try:
        row = db.get(Connection, created["id"])
        assert decrypt_secret(row.credentials_json) == {"password": "n3w-secret"}
    finally:
        db.close()


def test_delete_connection(client):
    h = _demo_headers(client)
    created = _create(client, h)
    assert client.delete(f"/integrations/connections/{created['id']}", headers=h).status_code == 204
    assert client.get("/integrations/connections", headers=h).json()["data"] == []


# ---- set active (storage write-target, sprint-4/12) ----

def _storage_row(db, name, *, active):
    from app.models.connection import CONNECTION_STATUS_ACTIVE, Connection
    from app.models.tenant import DEFAULT_TENANT_ID

    row = Connection(
        tenant_id=DEFAULT_TENANT_ID,
        provider="s3",
        type="storage",
        name=name,
        config_json={},
        credentials_json="",
        status=CONNECTION_STATUS_ACTIVE,
        is_active=active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def test_set_active_switches_storage_write_target(client, session_factory):
    db = session_factory()
    a_id = _storage_row(db, "Bucket A", active=True)
    b_id = _storage_row(db, "Bucket B", active=False)
    db.close()

    h = _demo_headers(client)
    res = client.post(f"/integrations/connections/{b_id}/activate", headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["isActive"] is True
    # A is now retired; only one storage row is active.
    assert client.get(f"/integrations/connections/{a_id}", headers=h).json()["isActive"] is False


def test_set_active_rejects_non_storage(client):
    h = _demo_headers(client)
    smtp = _create(client, h)  # email type
    res = client.post(f"/integrations/connections/{smtp['id']}/activate", headers=h)
    assert res.status_code == 409


# ---- tenant scoping ----

def test_connections_are_tenant_scoped(client):
    dh = _demo_headers(client)
    ph = _platform_headers(client)
    _create(client, dh)
    # Platform tenant sees ITS OWN (empty) list, not the default tenant's.
    assert client.get("/integrations/connections", headers=ph).json()["data"] == []
    # Cross-tenant access by id → 404.
    created = client.get("/integrations/connections", headers=dh).json()["data"][0]
    res = client.post(
        f"/integrations/connections/{created['id']}/test", json={}, headers=ph
    )
    assert res.status_code == 404


# ---- inline test + status upkeep ----

def test_test_endpoint_marks_active_on_success(client, monkeypatch):
    h = _demo_headers(client)
    created = _create(client, h)
    provider = get_provider("smtp")
    monkeypatch.setattr(
        provider, "test", lambda config, credentials, target=None: TestResult(True, "Connection verified.")
    )
    res = client.post(f"/integrations/connections/{created['id']}/test", json={}, headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True

    listed = client.get("/integrations/connections", headers=h).json()["data"][0]
    assert listed["status"] == "ACTIVE"
    assert listed["lastTestedAt"] is not None
    assert listed["lastError"] is None


def test_test_endpoint_marks_error_on_failure(client, monkeypatch):
    h = _demo_headers(client)
    created = _create(client, h)
    provider = get_provider("smtp")
    monkeypatch.setattr(
        provider,
        "test",
        lambda config, credentials, target=None: TestResult(False, "SMTP authentication failed (535)."),
    )
    res = client.post(
        f"/integrations/connections/{created['id']}/test",
        json={"target": "owner@acme.com"},
        headers=h,
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is False

    listed = client.get("/integrations/connections", headers=h).json()["data"][0]
    assert listed["status"] == "ERROR"
    assert "535" in listed["lastError"]
