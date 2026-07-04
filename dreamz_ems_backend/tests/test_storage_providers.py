"""Storage providers + S3-compatible adapter (plan sprint-2/06 D2/D3).

The boto3 client is stubbed at the adapter seam — no network, no moto. The
CDN probe fetch is patched at the urlopen seam.
"""
from typing import Any, Dict, Optional

import pytest

from app.integrations import get_provider
from app.integrations.s3_provider import (
    R2Provider,
    S3CompatibleAdapter,
    S3Provider,
    derive_endpoint,
)


class StubS3Client:
    """Minimal in-memory stand-in for boto3's S3 client."""

    def __init__(self, fail_head: bool = False):
        self.objects: Dict[str, bytes] = {}
        self.fail_head = fail_head
        self.presigned: list = []

    def head_bucket(self, Bucket):  # noqa: N803 — boto3 casing
        if self.fail_head:
            raise RuntimeError("403 Forbidden (head_bucket)")

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):  # noqa: N803
        import io

        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)

    def generate_presigned_url(self, op, Params, ExpiresIn):  # noqa: N803
        self.presigned.append(Params["Key"])
        return f"https://signed.example/{Params['Key']}?sig=abc"


def adapter(
    *,
    cdn: str = "",
    client: Optional[StubS3Client] = None,
) -> S3CompatibleAdapter:
    return S3CompatibleAdapter(
        bucket="assets",
        endpoint_url="https://endpoint.example",
        region="auto",
        access_key_id="ak",
        secret_access_key="sk",
        cdn_base_url=cdn,
        client=client or StubS3Client(),
    )


# ── endpoint derivation ────────────────────────────────────────────────────

def test_r2_endpoint_derived_from_account_id():
    assert (
        derive_endpoint("r2", {"accountId": "23f8c4ed"})
        == "https://23f8c4ed.r2.cloudflarestorage.com"
    )


def test_s3_endpoint_blank_means_aws_default():
    assert derive_endpoint("s3", {"endpointUrl": ""}) is None
    assert derive_endpoint("s3", {"endpointUrl": "https://minio.local"}) == "https://minio.local"


# ── adapter mechanics ──────────────────────────────────────────────────────

def test_save_stores_and_returns_key():
    client = StubS3Client()
    a = adapter(client=client)
    key = a.save("avatars/user-1", b"BYTES", "image/webp")
    assert key.startswith("avatars/user-1-")
    assert key.endswith(".webp")
    assert client.objects[key] == b"BYTES"


def test_resolve_uses_cdn_url_when_configured():
    a = adapter(cdn="https://cdn.acme.com/")
    kind, url = a.resolve("avatars/x.webp")
    assert kind == "url"
    assert url == "https://cdn.acme.com/avatars/x.webp"


def test_resolve_presigns_without_cdn():
    client = StubS3Client()
    a = adapter(client=client)
    kind, url = a.resolve("avatars/x.webp")
    # Presigned URLs EXPIRE — the distinct kind tells serving routes to skip
    # the immutable cache header (review fix).
    assert kind == "presigned"
    assert url.startswith("https://signed.example/avatars/x.webp")
    assert client.presigned == ["avatars/x.webp"]


def test_delete_removes_object():
    client = StubS3Client()
    a = adapter(client=client)
    key = a.save("k", b"x", "image/png")
    a.delete(key)
    assert key not in client.objects


def test_put_returns_public_url():
    a = adapter(cdn="https://cdn.acme.com")
    url = a.put("media/img", b"x", "image/png")
    assert url.startswith("https://cdn.acme.com/media/img-")


# ── provider catalog shape (plan 06 D2) ────────────────────────────────────

def test_storage_providers_registered():
    s3 = get_provider("s3")
    r2 = get_provider("r2")
    assert s3 is not None and s3.type == "storage"
    assert r2 is not None and r2.type == "storage"


def test_r2_fields_use_account_id_not_region():
    keys = [f["key"] for f in R2Provider().fields()]
    assert "accountId" in keys
    assert "region" not in keys
    assert "endpointUrl" not in keys
    assert "cdnBaseUrl" in keys


def test_s3_fields_have_optional_endpoint_and_cdn():
    fields = {f["key"]: f for f in S3Provider().fields()}
    assert fields["region"]["required"] is True
    assert fields["endpointUrl"]["required"] is False
    assert fields["cdnBaseUrl"]["required"] is False
    assert fields["secretAccessKey"]["secret"] is True


# ── provider.test() — probe round-trip (plan 06 D3) ────────────────────────

def _patch_adapter_client(monkeypatch, client: StubS3Client):
    monkeypatch.setattr(
        S3CompatibleAdapter, "_build_client", lambda self: client
    )


CONFIG: Dict[str, Any] = {"bucket": "assets", "region": "auto", "cdnBaseUrl": ""}
CREDS = {"accessKeyId": "ak", "secretAccessKey": "sk"}


def test_provider_test_probe_roundtrip_ok(monkeypatch):
    _patch_adapter_client(monkeypatch, StubS3Client())
    result = S3Provider().test(CONFIG, CREDS)
    assert result.ok
    assert "verified" in result.message.lower()


def test_provider_test_fails_on_head_bucket(monkeypatch):
    _patch_adapter_client(monkeypatch, StubS3Client(fail_head=True))
    result = S3Provider().test(CONFIG, CREDS)
    assert not result.ok
    assert "403" in result.message


def test_provider_test_fetches_probe_via_cdn(monkeypatch):
    client = StubS3Client()
    _patch_adapter_client(monkeypatch, client)
    fetched: list = []

    def fake_fetch(url: str, timeout: float) -> bytes:
        fetched.append(url)
        # Serve the probe object as the CDN would.
        key = url.split("https://cdn.acme.com/", 1)[1]
        return client.objects[key]

    import app.integrations.s3_provider as mod

    monkeypatch.setattr(mod, "_http_get", fake_fetch)
    result = S3Provider().test({**CONFIG, "cdnBaseUrl": "https://cdn.acme.com"}, CREDS)
    assert result.ok, result.message
    assert fetched and fetched[0].startswith("https://cdn.acme.com/")
    assert "cdn.acme.com" in result.message


def test_provider_test_cdn_mismatch_fails(monkeypatch):
    client = StubS3Client()
    _patch_adapter_client(monkeypatch, client)

    import app.integrations.s3_provider as mod

    monkeypatch.setattr(mod, "_http_get", lambda url, timeout: b"WRONG BYTES")
    result = S3Provider().test({**CONFIG, "cdnBaseUrl": "https://cdn.acme.com"}, CREDS)
    assert not result.ok
    assert "cdn" in result.message.lower()


def test_probe_object_cleaned_up(monkeypatch):
    client = StubS3Client()
    _patch_adapter_client(monkeypatch, client)
    result = S3Provider().test(CONFIG, CREDS)
    assert result.ok
    assert client.objects == {}  # probe deleted


def test_r2_provider_test_derives_endpoint(monkeypatch):
    captured: Dict[str, Any] = {}

    original_init = S3CompatibleAdapter.__init__

    def spy_init(self, **kwargs):
        captured.update(kwargs)
        kwargs["client"] = StubS3Client()
        original_init(self, **kwargs)

    monkeypatch.setattr(S3CompatibleAdapter, "__init__", spy_init)
    result = R2Provider().test(
        {"accountId": "abc123", "bucket": "assets", "cdnBaseUrl": ""},
        CREDS,
    )
    assert result.ok, result.message
    assert captured["endpoint_url"] == "https://abc123.r2.cloudflarestorage.com"
    assert captured["region"] == "auto"
