"""Embed-access config tests — plan 11H (tenant-level embed connection admin).

Covers: enable idempotency; rotate returns the secret exactly once + GET then
reports hasSecret without ever echoing it; origin validation (reject path /
trailing slash / query / non-localhost http, accept https + localhost); merge-
safe origin save; tenant scoping (A can't see/modify B); the workspaces.manage
perm gate; and the rotate/origins-before-enable guard.
"""
import uuid

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import decrypt_secret
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

EMBED_PROVIDER = "omnichannel_shared"


# ── helpers ──────────────────────────────────────────────────────────────────
def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _connection(session_factory, tenant_id):
    db = session_factory()
    conn = (
        db.query(Connection)
        .filter(Connection.tenant_id == tenant_id, Connection.provider == EMBED_PROVIDER)
        .first()
    )
    db.close()
    return conn


# ── enable ───────────────────────────────────────────────────────────────────
def test_get_config_before_enable_is_empty(client):
    res = client.get("/omnichannel/embed-config", headers=_bearer(_token(client)))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["connectionId"] is None
    assert body["allowedOrigins"] == []
    assert body["hasSecret"] is False
    assert body["host"]
    # The tenant's workspaces are offered for the snippet picker.
    assert isinstance(body["workspaces"], list)
    assert body["workspaces"] and all("id" in w and "name" in w for w in body["workspaces"])


def test_enable_is_idempotent(client, session_factory):
    token = _token(client)
    first = client.post("/omnichannel/embed-config/enable", headers=_bearer(token))
    assert first.status_code == 200, first.text
    cid = first.json()["connectionId"]
    assert cid
    assert first.json()["hasSecret"] is False
    # Enabling again returns the SAME connection (no duplicate row).
    second = client.post("/omnichannel/embed-config/enable", headers=_bearer(token))
    assert second.json()["connectionId"] == cid
    db = session_factory()
    count = (
        db.query(Connection)
        .filter(Connection.tenant_id == DEFAULT_TENANT_ID, Connection.provider == EMBED_PROVIDER)
        .count()
    )
    db.close()
    assert count == 1


# ── rotate secret (write-only) ───────────────────────────────────────────────
def test_rotate_returns_secret_once_then_hidden(client, session_factory):
    token = _token(client)
    client.post("/omnichannel/embed-config/enable", headers=_bearer(token))
    rot = client.post("/omnichannel/embed-config/rotate-secret", headers=_bearer(token))
    assert rot.status_code == 200, rot.text
    secret = rot.json()["embedSecret"]
    assert secret and len(secret) >= 32

    # GET never echoes the secret — only hasSecret flips true.
    cfg = client.get("/omnichannel/embed-config", headers=_bearer(token)).json()
    assert cfg["hasSecret"] is True
    assert "embedSecret" not in cfg

    # It is genuinely stored (encrypted) — decrypts back to the returned value.
    conn = _connection(session_factory, DEFAULT_TENANT_ID)
    assert decrypt_secret(conn.credentials_json)["embedSecret"] == secret


def test_rotate_generates_a_new_secret_each_time(client):
    token = _token(client)
    client.post("/omnichannel/embed-config/enable", headers=_bearer(token))
    a = client.post("/omnichannel/embed-config/rotate-secret", headers=_bearer(token)).json()
    b = client.post("/omnichannel/embed-config/rotate-secret", headers=_bearer(token)).json()
    assert a["embedSecret"] != b["embedSecret"]


def test_rotate_before_enable_is_409(client):
    res = client.post("/omnichannel/embed-config/rotate-secret", headers=_bearer(_token(client)))
    assert res.status_code == 409


# ── allowed origins ──────────────────────────────────────────────────────────
def test_set_origins_valid(client):
    token = _token(client)
    client.post("/omnichannel/embed-config/enable", headers=_bearer(token))
    res = client.put(
        "/omnichannel/embed-config/origins",
        json={"allowedOrigins": ["https://crm.acme.com", "http://localhost:3000", "https://crm.acme.com"]},
        headers=_bearer(token),
    )
    assert res.status_code == 200, res.text
    # Deduped, order preserved.
    assert res.json()["allowedOrigins"] == ["https://crm.acme.com", "http://localhost:3000"]


def test_set_origins_rejects_path(client):
    token = _token(client)
    client.post("/omnichannel/embed-config/enable", headers=_bearer(token))
    res = client.put(
        "/omnichannel/embed-config/origins",
        json={"allowedOrigins": ["https://crm.acme.com/leads"]},
        headers=_bearer(token),
    )
    assert res.status_code == 422


def test_set_origins_rejects_trailing_slash(client):
    token = _token(client)
    client.post("/omnichannel/embed-config/enable", headers=_bearer(token))
    res = client.put(
        "/omnichannel/embed-config/origins",
        json={"allowedOrigins": ["https://crm.acme.com/"]},
        headers=_bearer(token),
    )
    assert res.status_code == 422


def test_set_origins_rejects_query(client):
    token = _token(client)
    client.post("/omnichannel/embed-config/enable", headers=_bearer(token))
    res = client.put(
        "/omnichannel/embed-config/origins",
        json={"allowedOrigins": ["https://crm.acme.com?x=1"]},
        headers=_bearer(token),
    )
    assert res.status_code == 422


def test_set_origins_rejects_non_localhost_http(client):
    token = _token(client)
    client.post("/omnichannel/embed-config/enable", headers=_bearer(token))
    res = client.put(
        "/omnichannel/embed-config/origins",
        json={"allowedOrigins": ["http://crm.acme.com"]},
        headers=_bearer(token),
    )
    assert res.status_code == 422


def test_set_origins_merge_safe(client, session_factory):
    """A pre-existing unrelated config key survives an origins save."""
    token = _token(client)
    client.post("/omnichannel/embed-config/enable", headers=_bearer(token))
    # Plant an extra config key directly.
    db = session_factory()
    conn = (
        db.query(Connection)
        .filter(Connection.tenant_id == DEFAULT_TENANT_ID, Connection.provider == EMBED_PROVIDER)
        .first()
    )
    conn.config_json = {**(conn.config_json or {}), "keepMe": "yes"}
    db.commit()
    db.close()

    client.put(
        "/omnichannel/embed-config/origins",
        json={"allowedOrigins": ["https://crm.acme.com"]},
        headers=_bearer(token),
    )
    conn = _connection(session_factory, DEFAULT_TENANT_ID)
    assert conn.config_json.get("keepMe") == "yes"
    assert conn.config_json.get("allowedOrigins") == ["https://crm.acme.com"]


def test_set_origins_before_enable_is_409(client):
    res = client.put(
        "/omnichannel/embed-config/origins",
        json={"allowedOrigins": ["https://crm.acme.com"]},
        headers=_bearer(_token(client)),
    )
    assert res.status_code == 409


# ── tenant scoping ───────────────────────────────────────────────────────────
def test_tenant_scoping(client, session_factory):
    """Tenant B's embed connection is invisible to tenant A's GET, and A's
    enable never touches B's row. B = the seeded PLATFORM tenant (a real row)."""
    from app.models.tenant import PLATFORM_TENANT_ID

    token_a = _token(client)  # default tenant (A)
    b_conn_id = str(uuid.uuid4())
    db = session_factory()
    db.add(
        Connection(
            id=b_conn_id,
            tenant_id=PLATFORM_TENANT_ID,
            provider=EMBED_PROVIDER,
            type="omnichannel",
            name="Embed access",
            config_json={"allowedOrigins": ["https://b.example"]},
            credentials_json="",
            status="ACTIVE",
        )
    )
    db.commit()
    db.close()

    # A's GET sees NOTHING of B (its own connection is absent).
    a_cfg = client.get("/omnichannel/embed-config", headers=_bearer(token_a)).json()
    assert a_cfg["connectionId"] is None

    # A enables — a NEW row for A, B untouched.
    a_cid = client.post("/omnichannel/embed-config/enable", headers=_bearer(token_a)).json()[
        "connectionId"
    ]
    assert a_cid != b_conn_id
    db = session_factory()
    b_conn = db.query(Connection).filter(Connection.id == b_conn_id).first()
    assert b_conn.config_json["allowedOrigins"] == ["https://b.example"]  # untouched
    db.close()


# ── permission gate ──────────────────────────────────────────────────────────
def test_requires_workspaces_manage(client, session_factory):
    """A user WITHOUT workspaces.manage is refused (403). Reuses the existing
    perm — no new permission, no grant sweep."""
    from sqlalchemy.sql import func

    from app.models import Role, User, UserStatus
    from app.security import hash_password

    db = session_factory()
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="EmbedNoPerm", is_system=False)
    db.add(role)
    db.flush()
    email = "embed-noperm@example.com"
    password = "Passw0rd!x"
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=email,
        password=hash_password(password),
        name="No Perm",
        status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    db.close()

    token = _token(client, email=email, password=password)
    assert client.get("/omnichannel/embed-config", headers=_bearer(token)).status_code == 403
    assert (
        client.post("/omnichannel/embed-config/enable", headers=_bearer(token)).status_code == 403
    )
