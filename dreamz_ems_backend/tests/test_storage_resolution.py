"""Connection-driven StorageService resolution (plan sprint-2/06 D1/D7/D10).

Chain: tenant's storage connection → platform's → local disk. Keys written
through a connection carry `conn:<id>:` so reads resolve through the
connection that WROTE them; legacy unprefixed keys stay on local disk.
"""
import pytest

from app.models.connection import (
    CONNECTION_STATUS_ERROR,
    CONNECTION_STATUS_UNVERIFIED,
    Connection,
)
from app.models.tenant import DEFAULT_TENANT_ID, PLATFORM_TENANT_ID
from app.secrets import encrypt_secret
from app.integrations.s3_provider import S3CompatibleAdapter
from app.services import storage as storage_module
from app.services.storage import UnresolvableKey, storage_for_tenant

from tests.test_storage_providers import StubS3Client


@pytest.fixture
def stub_client(monkeypatch):
    client = StubS3Client()
    monkeypatch.setattr(S3CompatibleAdapter, "_build_client", lambda self: client)
    storage_module.clear_adapter_cache()
    return client


@pytest.fixture
def local_media(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    return tmp_path


def _storage_connection(
    db,
    tenant_id: str = DEFAULT_TENANT_ID,
    *,
    status: str = CONNECTION_STATUS_UNVERIFIED,
    cdn: str = "https://cdn.acme.com",
    provider: str = "s3",
) -> Connection:
    row = Connection(
        tenant_id=tenant_id,
        provider=provider,
        type="storage",
        name="Bucket",
        config_json={"bucket": "assets", "region": "auto", "cdnBaseUrl": cdn},
        credentials_json=encrypt_secret({"accessKeyId": "ak", "secretAccessKey": "sk"}),
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ── resolution chain ───────────────────────────────────────────────────────

def test_no_connection_falls_back_to_local_disk(session_factory, local_media):
    db = session_factory()
    storage = storage_for_tenant(db, DEFAULT_TENANT_ID)
    key = storage.save("avatars/u1", b"BYTES", "image/png")
    assert not key.startswith("conn:")
    kind, value = storage.resolve(key)
    assert kind == "path"
    assert open(value, "rb").read() == b"BYTES"
    db.close()


def test_tenant_connection_wins_and_prefixes_keys(session_factory, stub_client, local_media):
    db = session_factory()
    conn = _storage_connection(db)
    storage = storage_for_tenant(db, DEFAULT_TENANT_ID)
    key = storage.save("avatars/u1", b"BYTES", "image/webp")
    assert key.startswith(f"conn:{conn.id}:")
    # The blob landed in the bucket, not on disk.
    raw = key.split(":", 2)[2]
    assert stub_client.objects[raw] == b"BYTES"
    kind, url = storage.resolve(key)
    assert kind == "url"
    assert url == f"https://cdn.acme.com/{raw}"
    db.close()


def test_platform_connection_is_the_fallback(session_factory, stub_client, local_media):
    db = session_factory()
    conn = _storage_connection(db, PLATFORM_TENANT_ID)
    storage = storage_for_tenant(db, DEFAULT_TENANT_ID)
    key = storage.save("avatars/u1", b"X", "image/png")
    assert key.startswith(f"conn:{conn.id}:")
    db.close()


def test_error_connection_is_skipped(session_factory, stub_client, local_media):
    db = session_factory()
    _storage_connection(db, status=CONNECTION_STATUS_ERROR)
    storage = storage_for_tenant(db, DEFAULT_TENANT_ID)
    key = storage.save("avatars/u1", b"X", "image/png")
    assert not key.startswith("conn:")  # fell through to local
    db.close()


def test_old_keys_resolve_through_their_writing_connection(
    session_factory, stub_client, local_media
):
    """Switching backends must not strand existing assets (D1): the key names
    the WRITING connection; resolve loads THAT row even after a different
    connection becomes the write target. Real-world shape: blobs written via
    the PLATFORM default, then the tenant connects its OWN bucket (the
    same-tenant variant can't exist — UNIQUE(tenant_id, type))."""
    db = session_factory()
    platform = _storage_connection(db, PLATFORM_TENANT_ID, cdn="https://platform-cdn.acme.com")
    storage = storage_for_tenant(db, DEFAULT_TENANT_ID)
    key = storage.save("avatars/u1", b"X", "image/png")
    assert key.startswith(f"conn:{platform.id}:")

    # The tenant brings its own bucket — NEW writes go there…
    own = _storage_connection(db, cdn="https://own-cdn.acme.com")
    storage_module.clear_adapter_cache()
    fresh = storage_for_tenant(db, DEFAULT_TENANT_ID)
    new_key = fresh.save("avatars/u2", b"Y", "image/png")
    assert new_key.startswith(f"conn:{own.id}:")

    # …while OLD keys keep resolving through the platform row that wrote them.
    kind, url = fresh.resolve(key)
    assert url.startswith("https://platform-cdn.acme.com/")
    db.close()


def test_foreign_tenant_connection_id_is_unresolvable(session_factory, stub_client, local_media):
    """Defense-in-depth (polymorphic target_id rule): a key naming another
    tenant's connection must not resolve through it."""
    db = session_factory()
    from app.models.tenant import Tenant
    from app.models.status import Status

    status_id = db.query(Status.id).filter(Status.entity_type == "tenant").first()[0]
    other = Tenant(name="Other", slug="other-co", status_id=status_id)
    db.add(other)
    db.commit()
    foreign = _storage_connection(db, other.id)
    storage = storage_for_tenant(db, DEFAULT_TENANT_ID)
    with pytest.raises(UnresolvableKey):
        storage.resolve(f"conn:{foreign.id}:avatars/x.png")
    db.close()


def test_missing_connection_id_is_unresolvable(session_factory, local_media):
    db = session_factory()
    storage = storage_for_tenant(db, DEFAULT_TENANT_ID)
    with pytest.raises(UnresolvableKey):
        storage.resolve("conn:does-not-exist:avatars/x.png")
    db.close()


def test_delete_routes_by_prefix(session_factory, stub_client, local_media):
    db = session_factory()
    _storage_connection(db)
    storage = storage_for_tenant(db, DEFAULT_TENANT_ID)
    key = storage.save("avatars/u1", b"X", "image/png")
    raw = key.split(":", 2)[2]
    assert raw in stub_client.objects
    storage.delete(key)
    assert raw not in stub_client.objects
    db.close()


# ── one ACTIVE connection per type (D7) ────────────────────────────────────

def _login(client, email, password):
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


S3_PAYLOAD = {
    "provider": "s3",
    "name": "Bucket",
    "config": {"bucket": "assets", "region": "auto"},
    "credentials": {"accessKeyId": "ak", "secretAccessKey": "sk"},
}
R2_PAYLOAD = {
    "provider": "r2",
    "name": "R2 Bucket",
    "config": {"accountId": "abc", "bucket": "assets"},
    "credentials": {"accessKeyId": "ak", "secretAccessKey": "sk"},
}


def test_second_storage_connection_conflicts(client):
    from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

    h = _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)
    assert client.post("/integrations/connections", json=S3_PAYLOAD, headers=h).status_code == 201
    res = client.post("/integrations/connections", json=R2_PAYLOAD, headers=h)
    assert res.status_code == 409
    assert "disconnect" in res.json()["detail"].lower()


def test_storage_next_to_email_is_fine(client):
    from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

    h = _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)
    smtp = {
        "provider": "smtp",
        "name": "Mail",
        "config": {"host": "smtp.acme.com", "port": "587", "security": "starttls",
                   "fromEmail": "a@acme.com"},
        "credentials": {},
    }
    assert client.post("/integrations/connections", json=smtp, headers=h).status_code == 201
    assert client.post("/integrations/connections", json=S3_PAYLOAD, headers=h).status_code == 201


def test_reconnect_after_disconnect(client):
    from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

    h = _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)
    created = client.post("/integrations/connections", json=S3_PAYLOAD, headers=h).json()
    assert client.delete(f"/integrations/connections/{created['id']}", headers=h).status_code == 204
    assert client.post("/integrations/connections", json=R2_PAYLOAD, headers=h).status_code == 201


# ── platform seeding (D10) ─────────────────────────────────────────────────

def test_platform_storage_seed_from_env(session_factory, monkeypatch):
    from app.config import settings
    from app.seed import seed_platform_storage_connection

    db = session_factory()
    monkeypatch.setattr(settings, "platform_storage_provider", "r2")
    monkeypatch.setattr(settings, "platform_storage_account_id", "acct1")
    monkeypatch.setattr(settings, "platform_storage_bucket", "platform-assets")
    monkeypatch.setattr(settings, "platform_storage_access_key_id", "ak")
    monkeypatch.setattr(settings, "platform_storage_secret_access_key", "sk")
    monkeypatch.setattr(settings, "platform_storage_cdn_base_url", "https://cdn.dreamz.app")
    from cryptography.fernet import Fernet

    monkeypatch.setattr(settings, "fernet_key", Fernet.generate_key().decode())

    seed_platform_storage_connection(db)
    db.commit()
    row = (
        db.query(Connection)
        .filter(Connection.tenant_id == PLATFORM_TENANT_ID, Connection.type == "storage")
        .one()
    )
    assert row.provider == "r2"
    assert row.config_json["bucket"] == "platform-assets"
    assert row.config_json["cdnBaseUrl"] == "https://cdn.dreamz.app"
    db.close()


def test_platform_storage_seed_refuses_without_fernet_key(session_factory, monkeypatch, capsys):
    from app.config import settings
    from app.seed import seed_platform_storage_connection

    db = session_factory()
    monkeypatch.setattr(settings, "platform_storage_provider", "s3")
    monkeypatch.setattr(settings, "platform_storage_bucket", "b")
    monkeypatch.setattr(settings, "fernet_key", "")

    seed_platform_storage_connection(db)
    db.commit()
    assert (
        db.query(Connection)
        .filter(Connection.tenant_id == PLATFORM_TENANT_ID, Connection.type == "storage")
        .first()
        is None
    )
    assert "FERNET_KEY" in capsys.readouterr().out
    db.close()
