"""S3-compatible storage providers (plan sprint-2/06 D2/D3).

TWO catalog cards - Amazon S3 (`s3`, optional endpoint covers MinIO/Wasabi)
and Cloudflare R2 (`r2`, endpoint DERIVED from the Account ID) - over ONE
adapter. CDN support = the optional `cdnBaseUrl` config: public URLs become
`{cdnBaseUrl}/{key}`; without it, reads fall back to presigned URLs.

`test()` = connection check (HEAD bucket) + a probe-object round-trip: upload,
fetch back (through the CDN when configured), byte-compare, delete. That
verifies credentials, write access AND the CDN wiring in one pass.
"""
import mimetypes
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.integrations.base import TestResult

PRESIGN_TTL_SECONDS = 3600  # resolved per request - never persisted (D4)
_PROBE_TIMEOUT_SECONDS = 10
_PROBE_MAX_BYTES = 1024 * 1024  # the probe object is tiny


def _ext_for(mime_type: str) -> str:
    return mimetypes.guess_extension(mime_type or "") or ".bin"


def _safe(key_hint: str) -> str:
    return "".join(c if c.isalnum() or c in "-_/" else "-" for c in key_hint)


def derive_endpoint(provider: str, config: Dict[str, Any]) -> Optional[str]:
    """Provider card → boto3 endpoint_url (None = AWS default)."""
    if provider == "r2":
        account_id = str(config.get("accountId", "")).strip()
        return f"https://{account_id}.r2.cloudflarestorage.com"
    endpoint = str(config.get("endpointUrl", "")).strip()
    return endpoint or None


def _http_get(url: str, timeout: float, operator_owned: bool = False) -> bytes:
    """Probe fetch seam (tests patch this).

    Sends a product User-Agent - Cloudflare's WAF (Bot Fight Mode) 403s the
    default `Python-urllib/X.Y` UA, which broke the CDN probe against R2
    custom domains even when the wiring was correct. The read itself is the
    shared storage URL read (public https only; platform storage excepted).
    """
    from app.services.storage import read_url

    return read_url(
        url,
        operator_owned=operator_owned,
        timeout=timeout,
        max_bytes=_PROBE_MAX_BYTES,
        headers={"User-Agent": "FoundryxEMS-StorageProbe/1.0"},
    )


class S3CompatibleAdapter:
    """One S3 code path for every S3-compatible service (AWS/R2/MinIO/…).

    Implements the StorageService protocol (save/resolve/delete/put) so the
    connection-aware storage factory can hand it straight to consumers.
    """

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: Optional[str],
        region: Optional[str],
        access_key_id: str,
        secret_access_key: str,
        cdn_base_url: str = "",
        client: Optional[Any] = None,
    ):
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.region = region or None
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.cdn_base_url = cdn_base_url.rstrip("/")
        self._client = client
        # True only for the platform's own storage row (set by the factory).
        self.operator_owned = False

    @classmethod
    def from_connection(
        cls, provider: str, config: Dict[str, Any], credentials: Dict[str, str]
    ) -> "S3CompatibleAdapter":
        return cls(
            bucket=str(config.get("bucket", "")),
            endpoint_url=derive_endpoint(provider, config),
            # R2 ignores region - boto3 still wants one ("auto").
            region=str(config.get("region", "")) or ("auto" if provider == "r2" else None),
            access_key_id=str(credentials.get("accessKeyId", "")),
            secret_access_key=str(credentials.get("secretAccessKey", "")),
            cdn_base_url=str(config.get("cdnBaseUrl", "")),
        )

    def _build_client(self) -> Any:
        import boto3  # noqa: PLC0415 - imported here so the stub seam works without it

        return boto3.client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key_id or None,
            aws_secret_access_key=self.secret_access_key or None,
        )

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    # ── StorageService protocol ────────────────────────────────────────────

    def save(self, key_hint: str, content: bytes, mime_type: str) -> str:
        key = f"{_safe(key_hint)}-{uuid.uuid4().hex[:8]}{_ext_for(mime_type)}"
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=content, ContentType=mime_type
        )
        return key

    def put_raw(self, raw: str, content: bytes, mime_type: str) -> None:
        """Path-preserving write at the EXACT key (no uuid mint) - sprint-4/10 D2."""
        self.client.put_object(
            Bucket=self.bucket, Key=raw, Body=content, ContentType=mime_type
        )

    def resolve(self, key: str) -> Tuple[str, str]:
        # CDN URLs are STABLE → "url" (immutable-cacheable). Without a CDN the
        # URL is PRESIGNED and expires in PRESIGN_TTL_SECONDS → "presigned",
        # so serving routes must NOT let clients cache it long (review
        # finding: an immutable-cached redirect to a 1h presign breaks assets
        # after the hour).
        if self.cdn_base_url:
            return ("url", self.public_url(key))
        return ("presigned", self.public_url(key))

    def fetch(self, key: str) -> Tuple[bytes, Optional[str]]:
        """Read the object bytes straight through boto3 so the serving route
        streams them SAME-ORIGIN (no presigned redirect → no bucket-CORS
        preflight, which browsers 403 against R2/S3). Missing object →
        FileNotFoundError."""
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:  # noqa: BLE001 - boto3 ClientError (NoSuchKey etc.)
            raise FileNotFoundError(key) from exc
        return obj["Body"].read(), obj.get("ContentType")

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def put(self, key_hint: str, content: bytes, mime_type: str) -> str:
        """Omnichannel contract - store + return the public URL."""
        return self.public_url(self.save(key_hint, content, mime_type))

    # ── URLs (plan 06 D3/D4) ──────────────────────────────────────────────

    def public_url(self, key: str) -> str:
        """CDN URL when configured (edge-cached), presigned otherwise.

        Presigned URLs EXPIRE - they are computed per request and must never
        be persisted; the DB stores keys only (D4).
        """
        if self.cdn_base_url:
            return f"{self.cdn_base_url}/{key}"
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=PRESIGN_TTL_SECONDS,
        )

    # ── connection test (probe round-trip) ─────────────────────────────────

    def run_probe(self) -> TestResult:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception as e:  # noqa: BLE001 - boto3 raises ClientError subclasses
            return TestResult(ok=False, message=f"Could not access bucket “{self.bucket}” ({e}).")

        probe_body = f"foundryx-probe-{uuid.uuid4().hex}".encode()
        key = ""
        try:
            key = self.save("foundryx-probe/probe", probe_body, "text/plain")
            if self.cdn_base_url:
                probe_url = f"{self.cdn_base_url}/{key}"
                if self.operator_owned:
                    fetched = _http_get(probe_url, _PROBE_TIMEOUT_SECONDS, operator_owned=True)
                else:
                    fetched = _http_get(probe_url, _PROBE_TIMEOUT_SECONDS)
                if fetched != probe_body:
                    return TestResult(
                        ok=False,
                        message=(
                            "Bucket writable, but the CDN returned different content "
                            f"for the probe object - check that {self.cdn_base_url} "
                            "serves this bucket."
                        ),
                    )
                return TestResult(
                    ok=True,
                    message=f"Bucket verified - probe object round-tripped via {self.cdn_base_url}.",
                )
            fetched = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            if fetched != probe_body:
                return TestResult(ok=False, message="Probe object read back different content.")
            return TestResult(
                ok=True,
                message="Bucket verified - probe object uploaded, fetched back and deleted.",
            )
        except Exception as e:  # noqa: BLE001
            return TestResult(ok=False, message=f"Probe round-trip failed ({e}).")
        finally:
            if key:
                try:
                    self.delete(key)
                except Exception:  # noqa: BLE001 - best-effort cleanup
                    pass


_CDN_FIELD = {
    "key": "cdnBaseUrl",
    "label": "CDN base URL",
    "type": "text",
    "required": False,
    "placeholder": "https://cdn.yourcompany.com",
    "advanced": True,
}
_KEY_FIELDS = [
    {"key": "accessKeyId", "label": "Access key ID", "type": "password",
     "required": True, "secret": True},
    {"key": "secretAccessKey", "label": "Secret access key", "type": "password",
     "required": True, "secret": True},
]


R2_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9-]+$")


def _storage_url_error(
    provider: str, config: Dict[str, Any], *, operator_owned: bool = False
) -> Optional[str]:
    """Message for the first storage URL that is not allowed, else None. Empty
    values are allowed. An operator-owned row may use http and any address."""
    from app.services.storage import storage_url_is_plain
    from app.services.url_guard import UrlGuardError, validate_public_https_url

    checks = [("cdnBaseUrl", "CDN base URL")]
    if provider == "r2":
        account_id = str(config.get("accountId", "")).strip()
        if account_id and not R2_ACCOUNT_ID.match(account_id):
            return "Account ID may contain only letters, digits and hyphens."
    else:
        checks.append(("endpointUrl", "Endpoint URL"))
    for key, label in checks:
        value = str(config.get(key, "") or "")
        if not value:
            continue
        if not storage_url_is_plain(value):
            return f"{label} must be a valid address."
        if key == "endpointUrl" and ("?" in value or "#" in value):
            return f"{label} must be a valid address."
        if operator_owned:
            if not value.startswith(("http://", "https://")):
                return f"{label} must start with http:// or https://."
            continue
        try:
            validate_public_https_url(value, strict_dns=False, subject=label)
        except UrlGuardError as exc:
            return str(exc)
        except ValueError:
            return f"{label} must be a valid address."
    return None


class _StorageProviderBase:
    type = "storage"
    test_label = "Verify storage"
    test_target = None  # probe round-trip needs no user input

    provider = ""  # subclasses
    # The test needs to know whether the platform owns the row (see test()).
    test_needs_context = True

    def validate_config(self, config: Dict[str, Any]) -> Optional[str]:
        """Save-time rule: storage URLs a tenant can edit must be public https."""
        return _storage_url_error(self.provider, config)

    def validate_platform_config(self, config: Dict[str, Any]) -> Optional[str]:
        """Operator-owned row: any address, http or https."""
        return _storage_url_error(self.provider, config, operator_owned=True)

    def test(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        target: Optional[str] = None,
        db: Any = None,
        tenant_id: Optional[str] = None,
    ) -> TestResult:
        from app.models.tenant import PLATFORM_TENANT_ID

        operator_owned = tenant_id == PLATFORM_TENANT_ID
        if not operator_owned and _storage_url_error(self.provider, config):
            return TestResult(ok=False, message="The storage URLs must be public https addresses.")
        adapter = S3CompatibleAdapter.from_connection(self.provider, config, credentials)
        adapter.operator_owned = operator_owned
        return adapter.run_probe()


class S3Provider(_StorageProviderBase):
    provider = "s3"
    title = "Amazon S3"
    description = (
        "Store uploads (avatars, branding, media) in your own S3 bucket. Any "
        "S3-compatible service works - AWS, MinIO, Wasabi - via the optional endpoint."
    )
    icon = "database"

    def fields(self) -> List[Dict[str, Any]]:
        return [
            {"key": "bucket", "label": "Bucket", "type": "text", "required": True,
             "placeholder": "my-company-assets"},
            {"key": "region", "label": "Region", "type": "text", "required": True,
             "placeholder": "ap-southeast-1"},
            *_KEY_FIELDS,
            _CDN_FIELD,
            {"key": "endpointUrl", "label": "Endpoint URL", "type": "text",
             "required": False, "advanced": True,
             "placeholder": "https://s3.amazonaws.com (leave blank for AWS)"},
        ]


class R2Provider(_StorageProviderBase):
    provider = "r2"
    title = "Cloudflare R2"
    description = (
        "Store uploads in Cloudflare R2 - S3-compatible, zero egress fees. The "
        "endpoint is derived from your Account ID; add a custom domain as the "
        "CDN base URL for fast public delivery."
    )
    icon = "cloud"

    def fields(self) -> List[Dict[str, Any]]:
        return [
            {"key": "accountId", "label": "Account ID", "type": "text", "required": True,
             "placeholder": "23f8c4ed…"},
            {"key": "bucket", "label": "Bucket", "type": "text", "required": True,
             "placeholder": "my-company-assets"},
            *_KEY_FIELDS,
            _CDN_FIELD,
        ]


# settings import kept for parity with sibling providers (timeouts later).
_ = settings
