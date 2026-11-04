"""A storage read that cannot reach the bucket answers a clean retry.

Provider: an error raised by get_object itself is split in two. A transport
failure or an S3 5xx raises StorageUnavailable (cause preserved); a missing or
forbidden object stays FileNotFoundError. Route: GET /omnichannel/media/{id}
answers 503 + Retry-After: 5 for the first and 404 for the second, for staff
JWT and workspace API-key callers. Storage migration treats an unreachable
destination as a recorded failure and never as "copy it over".
Companion to tests/test_storage_fetch_body_error.py (body-read path).
"""
import pytest

from tests.test_omnichannel_rich_messages import (  # noqa: F401 - fixtures + helpers
    _auth,
    _memory_idempotency,
    _mint_key,
    _tmp_media,
)
from tests.test_storage_fetch_body_error import (  # noqa: F401 - helpers
    PLAIN,
    _patch_fetch,
    _seed_message,
)
from tests.test_storage_migration import (  # noqa: F401 - fixtures + helpers
    FakeAdapter,
    _point_avatar,
    _storage_conn,
    db,
    fakes,
    only_avatar_location,
    stub_probe,
)
from tests.test_storage_providers import StubS3Client, adapter


def _client_error(code, status):
    from botocore.exceptions import ClientError

    return ClientError(
        {
            "Error": {"Code": code, "Message": "x"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "GetObject",
    )


def _transport_errors():
    from botocore.exceptions import (
        ConnectionClosedError,
        ConnectTimeoutError,
        EndpointConnectionError,
        ProxyConnectionError,
        ReadTimeoutError,
    )
    from urllib3.exceptions import ProtocolError

    url = "https://endpoint.example"
    return [
        EndpointConnectionError(endpoint_url=url),
        ConnectTimeoutError(endpoint_url=url),
        ProxyConnectionError(proxy_url=url),
        ReadTimeoutError(endpoint_url=url),
        ConnectionClosedError(endpoint_url=url),
        ProtocolError("Connection reset by peer"),
        ConnectionResetError("reset"),
        _client_error("InternalError", 500),
        _client_error("SlowDown", 503),
        _client_error("ServiceUnavailable", 503),
    ]


def _missing_errors():
    return [
        _client_error("NoSuchKey", 404),
        _client_error("NotFound", 404),
        _client_error("AccessDenied", 403),
        _client_error("BadRequest", 400),
    ]


class _RaisingClient(StubS3Client):
    def __init__(self, exc):
        super().__init__()
        self.exc = exc

    def get_object(self, Bucket, Key):  # noqa: N803
        raise self.exc


@pytest.mark.parametrize("idx", range(10))
def test_fetch_get_object_transport_failure_raises_storage_unavailable(idx):
    from app.services.storage import StorageUnavailable

    exc = _transport_errors()[idx]
    with pytest.raises(StorageUnavailable) as ei:
        adapter(client=_RaisingClient(exc)).fetch("k.png")
    assert isinstance(ei.value, OSError)
    assert not isinstance(ei.value, FileNotFoundError)
    assert ei.value.__cause__ is exc


@pytest.mark.parametrize("idx", range(4))
def test_fetch_get_object_missing_or_forbidden_stays_file_not_found(idx):
    from app.services.storage import StorageUnavailable

    exc = _missing_errors()[idx]
    with pytest.raises(FileNotFoundError) as ei:
        adapter(client=_RaisingClient(exc)).fetch("k.png")
    assert type(ei.value) is FileNotFoundError
    assert not isinstance(ei.value, StorageUnavailable)


def _connect_timeout():
    from botocore.exceptions import ConnectTimeoutError

    return ConnectTimeoutError(endpoint_url="https://endpoint.example")


def _patch_client(monkeypatch, exc):
    from modules.omnichannel.routers import media as media_router

    store = adapter(client=_RaisingClient(exc))
    monkeypatch.setattr(media_router, "storage_for_tenant", lambda db, tid: store)


def test_media_route_unreachable_bucket_503_for_staff(client, session_factory, monkeypatch):
    _, msg_id = _seed_message(client, session_factory)
    _patch_client(monkeypatch, _connect_timeout())
    r = client.get(f"/omnichannel/media/{msg_id}", headers=_auth(client))
    assert r.status_code == 503
    assert r.headers["retry-after"] == "5"
    assert r.json() == {"detail": PLAIN}


def test_media_route_unreachable_bucket_503_for_api_key(client, session_factory, monkeypatch):
    ws, msg_id = _seed_message(client, session_factory)
    key = _mint_key(client, ws)
    _patch_client(monkeypatch, _connect_timeout())
    r = client.get(
        f"/omnichannel/media/{msg_id}", headers={"Authorization": f"Bearer {key}"}
    )
    assert r.status_code == 503
    assert r.headers["retry-after"] == "5"
    assert r.json() == {"detail": PLAIN}


@pytest.mark.parametrize("idx", [0, 2])
def test_media_route_missing_or_forbidden_object_still_404(
    client, session_factory, monkeypatch, idx
):
    _, msg_id = _seed_message(client, session_factory)
    _patch_client(monkeypatch, _missing_errors()[idx])
    r = client.get(f"/omnichannel/media/{msg_id}", headers=_auth(client))
    assert r.status_code == 404
    assert r.json() == {"detail": "Not found"}
    assert "retry-after" not in r.headers


# ── storage migration: the destination (B) idempotent-skip read ──────────────
def _run_with_real_b(db, fakes, monkeypatch, b_exc):
    """A = in-memory fake holding raw1; B = real S3 adapter whose get_object
    raises b_exc. Returns (a_fake, b_client, job)."""
    from app.models.background_job import JOB_RUNNING, BackgroundJob
    from app.models.tenant import DEFAULT_TENANT_ID
    from app.repositories.connection_repository import ConnectionRepository
    from app.services import storage as storage_module
    from app.storage_migration.service import STORAGE_MIGRATION, run_storage_migration

    a = _storage_conn(db)
    a_fake = fakes.setdefault(a.id, FakeAdapter())
    a_fake.store["raw1"] = (b"one", "image/png")
    _point_avatar(db, DEFAULT_TENANT_ID, [f"conn:{a.id}:raw1"])
    b = _storage_conn(db, name="B", active=False)
    b_client = _RaisingClient(b_exc)
    b_adapter = adapter(client=b_client)

    def fake_adapter_for(connection):
        if connection.id == b.id:
            return b_adapter
        return fakes.setdefault(connection.id, FakeAdapter())

    monkeypatch.setattr(storage_module, "_adapter_for", fake_adapter_for)
    ConnectionRepository(db).mark_active(a.id, False)
    ConnectionRepository(db).mark_active(b.id, True)
    db.commit()
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=STORAGE_MIGRATION, status=JOB_RUNNING,
        payload_json={"fromConnectionId": a.id, "toConnectionId": b.id},
    )
    db.add(job)
    db.commit()
    run_storage_migration(db, job)
    db.refresh(job)
    return a_fake, b_client, job, a.id


def test_migration_unreachable_destination_records_failure_without_copy(
    db, only_avatar_location, fakes, stub_probe, monkeypatch
):
    from app.models.background_job import JOB_NEEDS_REVIEW

    a_fake, b_client, job, a_id = _run_with_real_b(
        db, fakes, monkeypatch, _connect_timeout()
    )
    assert job.status == JOB_NEEDS_REVIEW
    assert job.result_json["failed"] == 1
    assert job.result_json["failures"][0]["key"] == f"conn:{a_id}:raw1"
    assert a_fake.fetched == []  # never read the source
    assert b_client.objects == {}  # never wrote the destination


def test_migration_destination_no_such_key_still_copies_from_source(
    db, only_avatar_location, fakes, stub_probe, monkeypatch
):
    from app.models.background_job import JOB_DONE

    a_fake, b_client, job, _ = _run_with_real_b(
        db, fakes, monkeypatch, _client_error("NoSuchKey", 404)
    )
    assert job.status == JOB_DONE
    assert a_fake.fetched == ["raw1"]
    assert b_client.objects == {"raw1": b"one"}
