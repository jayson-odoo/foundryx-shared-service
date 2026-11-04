"""A storage read that fails mid-body answers a clean retry, not a 500.

Provider: a failure while reading the object body raises StorageUnavailable
(an OSError, never FileNotFoundError). Route: GET /omnichannel/media/{id}
answers 503 + Retry-After: 5 for it; a missing object stays 404. The media
route serves staff JWT and workspace API-key callers through one handler with
plain HTTPException details (no gateway envelope), so both paths are covered.
"""
import io

import pytest

from tests.test_omnichannel_rich_messages import (  # noqa: F401 - fixtures + helpers
    PNG,
    _auth,
    _default_workspace_id,
    _memory_idempotency,
    _mint_key,
    _seed_channel,
    _seed_contact,
    _send_image,
    _tmp_media,
)
from tests.test_storage_providers import StubS3Client, adapter

PLAIN = "The file is temporarily unavailable. Please try again."


def _read_errors():
    from botocore.exceptions import (
        IncompleteReadError,
        ReadTimeoutError,
        ResponseStreamingError,
    )
    from urllib3.exceptions import ProtocolError

    return [
        ReadTimeoutError(endpoint_url="https://endpoint.example"),
        ProtocolError("Connection reset by peer"),
        IncompleteReadError(actual_bytes=1, expected_bytes=9),
        ResponseStreamingError(error=ProtocolError("broken")),
    ]


class _BadBody:
    def __init__(self, exc):
        self.exc = exc

    def read(self, *a, **kw):
        raise self.exc


class _BadBodyClient(StubS3Client):
    def __init__(self, exc):
        super().__init__()
        self.exc = exc

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": _BadBody(self.exc), "ContentType": "image/png"}


@pytest.mark.parametrize("idx", range(4))
def test_fetch_body_read_failure_raises_storage_unavailable(idx):
    from app.services.storage import StorageUnavailable

    store = adapter(client=_BadBodyClient(_read_errors()[idx]))
    with pytest.raises(StorageUnavailable) as ei:
        store.fetch("k.png")
    assert isinstance(ei.value, OSError)
    assert not isinstance(ei.value, FileNotFoundError)


def test_fetch_missing_object_still_file_not_found():
    with pytest.raises(FileNotFoundError):
        adapter().fetch("absent.png")


def test_fetch_good_body_returns_bytes_and_type():
    client = StubS3Client()
    client.get_object = lambda Bucket, Key: {  # noqa: N803
        "Body": io.BytesIO(b"abc"),
        "ContentType": "image/png",
    }
    assert adapter(client=client).fetch("k.png") == (b"abc", "image/png")


def _patch_fetch(monkeypatch, exc):
    from modules.omnichannel.routers import media as media_router

    class _Store:
        def fetch(self, key):
            raise exc

    monkeypatch.setattr(media_router, "storage_for_tenant", lambda db, tid: _Store())


def _seed_message(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _seed_channel(session_factory, ws)
    cid = _seed_contact(session_factory, ws)
    return ws, _send_image(client, cid).json()["id"]


def test_media_route_503_retry_after_for_staff(client, session_factory, monkeypatch):
    from app.services.storage import StorageUnavailable

    _, msg_id = _seed_message(client, session_factory)
    _patch_fetch(monkeypatch, StorageUnavailable("read failed"))
    r = client.get(f"/omnichannel/media/{msg_id}", headers=_auth(client))
    assert r.status_code == 503
    assert r.headers["retry-after"] == "5"
    assert r.json()["detail"] == PLAIN


def test_media_route_503_retry_after_for_api_key(client, session_factory, monkeypatch):
    from app.services.storage import StorageUnavailable

    ws, msg_id = _seed_message(client, session_factory)
    key = _mint_key(client, ws)
    _patch_fetch(monkeypatch, StorageUnavailable("read failed"))
    r = client.get(
        f"/omnichannel/media/{msg_id}", headers={"Authorization": f"Bearer {key}"}
    )
    assert r.status_code == 503
    assert r.headers["retry-after"] == "5"
    assert r.json()["detail"] == PLAIN


def test_media_route_missing_object_still_404(client, session_factory, monkeypatch):
    _, msg_id = _seed_message(client, session_factory)
    _patch_fetch(monkeypatch, FileNotFoundError("gone"))
    r = client.get(f"/omnichannel/media/{msg_id}", headers=_auth(client))
    assert r.status_code == 404
    assert "retry-after" not in r.headers


def test_storage_unavailable_is_transient_oserror_for_send_runner():
    from app.services.storage import StorageUnavailable

    assert issubclass(StorageUnavailable, OSError)
    assert not issubclass(StorageUnavailable, FileNotFoundError)
