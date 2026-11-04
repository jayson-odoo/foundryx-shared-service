"""Tenant S3 storage client: bounded connect/read timeouts and retries."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.integrations.s3_provider import S3CompatibleAdapter


def _adapter() -> S3CompatibleAdapter:
    return S3CompatibleAdapter(
        bucket="b",
        endpoint_url="http://127.0.0.1:9",
        region="us-east-1",
        access_key_id="AKIADUMMY",
        secret_access_key="dummysecret",
        cdn_base_url="",
    )


def _cfg(adapter=None):
    return (adapter or _adapter())._build_client().meta.config


def test_client_config_matches_default_settings():
    cfg = _cfg()
    assert cfg.connect_timeout == settings.storage_s3_connect_timeout_seconds == 5
    assert cfg.read_timeout == settings.storage_s3_read_timeout_seconds == 60
    assert cfg.retries["max_attempts"] == settings.storage_s3_max_attempts == 3
    assert cfg.retries["mode"] == "standard"


def test_client_config_follows_changed_settings(monkeypatch):
    monkeypatch.setattr(settings, "storage_s3_connect_timeout_seconds", 2, raising=False)
    monkeypatch.setattr(settings, "storage_s3_read_timeout_seconds", 15, raising=False)
    monkeypatch.setattr(settings, "storage_s3_max_attempts", 7, raising=False)
    cfg = _cfg()
    assert cfg.connect_timeout == 2
    assert cfg.read_timeout == 15
    assert cfg.retries["max_attempts"] == 7


@pytest.mark.parametrize(
    "env,value",
    [
        ("STORAGE_S3_CONNECT_TIMEOUT_SECONDS", "0"),
        ("STORAGE_S3_READ_TIMEOUT_SECONDS", "4"),
        ("STORAGE_S3_MAX_ATTEMPTS", "0"),
        ("STORAGE_S3_MAX_ATTEMPTS", "11"),
    ],
)
def test_settings_below_floor_or_above_cap_refused(monkeypatch, env, value):
    monkeypatch.setenv(env, value)
    with pytest.raises(ValidationError) as exc:
        Settings()
    assert env.lower() in str(exc.value)


@pytest.mark.parametrize(
    "env,value,attr",
    [
        ("STORAGE_S3_CONNECT_TIMEOUT_SECONDS", "1", "storage_s3_connect_timeout_seconds"),
        ("STORAGE_S3_READ_TIMEOUT_SECONDS", "5", "storage_s3_read_timeout_seconds"),
        ("STORAGE_S3_MAX_ATTEMPTS", "1", "storage_s3_max_attempts"),
        ("STORAGE_S3_MAX_ATTEMPTS", "10", "storage_s3_max_attempts"),
    ],
)
def test_settings_at_bounds_load(monkeypatch, env, value, attr):
    monkeypatch.setenv(env, value)
    assert getattr(Settings(), attr) == int(value)


def test_control_endpoint_region_credentials_and_presign_still_work():
    client = _adapter()._build_client()
    assert client.meta.endpoint_url == "http://127.0.0.1:9"
    assert client.meta.region_name == "us-east-1"
    creds = client._request_signer._credentials
    assert creds.access_key == "AKIADUMMY"
    assert creds.secret_key == "dummysecret"
    url = client.generate_presigned_url(
        "get_object", Params={"Bucket": "b", "Key": "k"}, ExpiresIn=60
    )
    assert url.startswith("http://127.0.0.1:9/")
    assert "X-Amz-Signature" in url or "Signature" in url
