"""Core StorageService (sprint-2/03 - lifted from modules/omnichannel;
connection-driven since plan sprint-2/06 D1).

Media blobs behind one interface. Backend selection is DATA, not env: the
tenant's storage connection → the platform tenant's → local disk (zero-config
dev). The retired ``STORAGE_BACKEND`` env is gone; ``media_root`` stays (the
local adapter needs it).

Keys carry their writing backend: a blob stored through a connection gets a
``conn:<connection_id>:<raw>`` key, so reads resolve through the connection
that WROTE them - switching connections never breaks existing assets (they
stay resolvable while the old row exists; re-upload migration = BL-077).
Legacy unprefixed keys (and dev writes) resolve via local disk, unchanged.

Two usage styles:
- ``put``  - omnichannel's original contract: store + return the PUBLIC URL
  (local URLs ride the omnichannel media router; the module owns that mount).
- ``save`` / ``resolve`` / ``delete`` - key-based storage for core features
  that serve assets through their own routes (e.g. ``/public/branding/...``):
  ``save`` returns an opaque storage key persisted in the DB; ``resolve``
  turns it back into a local path or a remote URL to stream/redirect.
"""
import mimetypes
import uuid
from pathlib import Path
from typing import Dict, Optional, Protocol, Tuple
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.services.url_guard import (
    GuardedTransport,
    UrlGuardError,
    assert_deliverable,
    validate_public_https_url,
)


class StorageService(Protocol):
    def put(self, key_hint: str, content: bytes, mime_type: str) -> str:
        """Store a blob; returns the public URL the frontend can render."""
        ...

    def save(self, key_hint: str, content: bytes, mime_type: str) -> str:
        """Store a blob; returns an opaque storage key (persist it)."""
        ...

    def put_raw(self, raw: str, content: bytes, mime_type: str) -> None:
        """Write a blob at the EXACT ``raw`` key - NO uuid mint (plan sprint-4/10
        D2). ``save`` mints a fresh uuid, which is wrong for a path-preserving
        COPY (storage migration): a later ``fetch(raw)`` / ``resolve(raw)`` must
        return exactly these bytes at exactly this key."""
        ...

    def resolve(self, key: str) -> Tuple[str, str]:
        """Storage key → ('path', local file path), ('url', STABLE remote
        URL - safe to cache immutably) or ('presigned', EXPIRING URL - never
        let clients cache it past the presign TTL)."""
        ...

    def fetch(self, key: str) -> Tuple[bytes, Optional[str]]:
        """Storage key → (raw bytes, stored content-type | None). Reads the
        blob straight from the backend so a serving route can stream it
        SAME-ORIGIN - no redirect to a presigned remote URL (which a browser
        then CORS-blocks against the bucket). Raises FileNotFoundError when the
        blob is gone."""
        ...

    def delete(self, key: str) -> None:
        """Remove a stored blob (replace/remove flows). Missing = no-op."""
        ...


def _ext_for(mime_type: str) -> str:
    return mimetypes.guess_extension(mime_type or "") or ".bin"


def _safe(key_hint: str) -> str:
    return "".join(c if c.isalnum() or c in "-_/" else "-" for c in key_hint)


def _safe_read_path(root: Path, key: str) -> Path:
    """Resolve a client-supplied storage `key` under `root`, rejecting
    directory traversal (review round 1, finding B2a). `_safe()` above only
    ever guards a WRITE-time `key_hint` (it mints a fresh uuid-suffixed
    filename, so a hostile hint can only mangle its OWN prefix); every READ
    path (`fetch`/`resolve`) used to join a caller-supplied key straight onto
    `root` with NO guard at all - a `contactsCsvKey` of `"../../../../etc/
    hosts"` was a real arbitrary-file read (plan 33 review). Rejects `..`,
    an absolute path, a home-dir reference and an embedded NUL outright,
    then verifies the RESOLVED path still sits under `root` (belt-and-
    suspenders against a symlink or a platform-specific separator trick the
    substring checks alone might miss). Raises `FileNotFoundError` - the
    SAME exception a genuinely-missing key raises - so a caller (and an
    attacker probing the behaviour) can never distinguish "unsafe" from
    "missing".

    The `".."` check (review round 2 note) is a bare SUBSTRING match, not a
    path-segment match - it rejects the whole key the moment `".."` appears
    ANYWHERE in it, including inside an otherwise-innocent segment (a stored
    key of `"report..final.csv"` or `"v1..2/export.csv"` never validates,
    even though neither is a traversal attempt). This is deliberate
    over-blocking, not a bug: every key this module mints itself is `_safe()`-
    sanitized (`-`/`_`/`/`/alnum only, never a literal `.`), so a legitimate
    stored key can never contain `".."` in the first place - only a hostile
    or hand-typed key would, and refusing the whole key outright is strictly
    safer than trying to parse "is this occurrence actually a `..` path
    segment" case by case."""
    if not key or "\x00" in key or ".." in key or key.startswith("~") or Path(key).is_absolute():
        raise FileNotFoundError(key)
    resolved_root = root.resolve()
    candidate = (root / key).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise FileNotFoundError(key)
    return root / key


class LocalDiskStorage:
    """Dev adapter - writes under media_root."""

    def __init__(self, root: Optional[str] = None):
        self.root = Path(root or settings.media_root)

    def _write(self, key_hint: str, content: bytes, mime_type: str) -> str:
        rel = f"{_safe(key_hint)}-{uuid.uuid4().hex[:8]}{_ext_for(mime_type)}"
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return rel

    def put(self, key_hint: str, content: bytes, mime_type: str) -> str:
        # Omnichannel contract: local blobs are served by the module's media
        # router at /omnichannel/media/{rel}.
        rel = self._write(key_hint, content, mime_type)
        return f"{settings.public_base_url}/omnichannel/media/{rel}"

    def save(self, key_hint: str, content: bytes, mime_type: str) -> str:
        return self._write(key_hint, content, mime_type)

    def put_raw(self, raw: str, content: bytes, mime_type: str) -> None:
        # Path-preserving write (no uuid mint) - sprint-4/10 D2.
        path = self.root / raw
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def resolve(self, key: str) -> Tuple[str, str]:
        return ("path", str(_safe_read_path(self.root, key)))

    def fetch(self, key: str) -> Tuple[bytes, Optional[str]]:
        path = _safe_read_path(self.root, key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes(), mimetypes.guess_type(str(path))[0]

    def delete(self, key: str) -> None:
        try:
            _safe_read_path(self.root, key).unlink()
        except FileNotFoundError:
            pass


class UnresolvableKey(Exception):
    """A ``conn:``-prefixed key whose connection is gone or belongs to another
    tenant (defense-in-depth - the polymorphic target_id rule), or whose
    connection carries an endpoint that is not a public https address."""


class StorageReadError(Exception):
    """A stored object could not be read. The message is fixed and carries no
    address or content; the underlying cause is chained. ``status`` is the HTTP
    status when the server answered with a non-2xx one."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


_READ_FAILED = "The stored file could not be read."
_CHUNK = 64 * 1024


def storage_url_is_plain(value: str) -> bool:
    """False for a value that parsers read differently: a backslash, an ``@``,
    whitespace or control characters, or an address ``urlsplit`` cannot parse."""
    if any(c in "\\@" or c.isspace() or ord(c) < 32 for c in value):
        return False
    try:
        urlsplit(value).port  # noqa: B018 - raises ValueError for a bad port
    except ValueError:
        return False
    return True


def read_url(
    url: str,
    *,
    operator_owned: bool = False,
    timeout: float = 30,
    max_bytes: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
    subject: str = "Storage URL",
) -> bytes:
    """The one place a storage URL is opened.

    Storage URLs must be public https. The scheme is checked on the raw string
    before any network use; the connection goes only to checked public
    addresses; redirects are not followed; any non-2xx answer is a failed read;
    ``max_bytes`` stops the read. An operator-owned URL (the platform storage
    row) may use ``http`` and any address, nothing else.
    """
    allowed = ("http://", "https://") if operator_owned else ("https://",)
    try:
        if not storage_url_is_plain(url):
            raise StorageReadError(_READ_FAILED)
        if not url.startswith(allowed) or not urlsplit(url).hostname:
            raise StorageReadError(_READ_FAILED)
        if operator_owned:
            transport: Optional[httpx.BaseTransport] = None
        else:
            assert_deliverable(url, subject=subject)
            transport = GuardedTransport(subject=subject)
        chunks = []
        total = 0
        with httpx.Client(
            transport=transport, timeout=timeout, follow_redirects=False
        ) as client:
            request_headers = {**(headers or {}), "Accept-Encoding": "identity"}
            with client.stream("GET", url, headers=request_headers) as resp:
                if not 200 <= resp.status_code < 300:
                    raise StorageReadError(_READ_FAILED, status=resp.status_code)
                encoding = resp.headers.get("content-encoding", "").strip().lower()
                if encoding and encoding != "identity":
                    raise StorageReadError(_READ_FAILED)
                declared = resp.headers.get("content-length", "").strip()
                if (
                    max_bytes is not None
                    and declared.isascii()
                    and declared.isdigit()
                    and int(declared) > max_bytes
                ):
                    raise StorageReadError(_READ_FAILED)
                for chunk in resp.iter_raw(_CHUNK):
                    total += len(chunk)
                    if max_bytes is not None and total > max_bytes:
                        raise StorageReadError(_READ_FAILED)
                    chunks.append(chunk)
        return b"".join(chunks)
    except StorageReadError:
        raise
    except (UrlGuardError, httpx.HTTPError, httpx.InvalidURL, OSError, ValueError) as exc:
        raise StorageReadError(_READ_FAILED) from exc


def read_object(
    storage,
    key: str,
    *,
    timeout: float = 30,
    max_bytes: Optional[int] = None,
) -> bytes:
    """Bytes of a stored object, whatever the backend. Local files are read as
    before; a URL goes through ``read_url`` with the ownership of the
    connection that holds the key."""
    try:
        resolver = getattr(storage, "resolve_with_ownership", None)
        if resolver is not None:
            kind, value, operator_owned = resolver(key)
        else:
            kind, value = storage.resolve(key)
            operator_owned = False
    except UnresolvableKey as exc:
        raise StorageReadError(_READ_FAILED) from exc
    if kind == "path":
        with open(value, "rb") as fh:
            return fh.read()
    return read_url(
        value, operator_owned=operator_owned, timeout=timeout, max_bytes=max_bytes
    )


def endpoint_is_usable(provider: str, config: Dict[str, object]) -> bool:
    """True when a tenant-owned connection's endpoint is empty or a public https
    URL. boto3 resolves names itself, so this runs once when a client is built."""
    from app.integrations.s3_provider import derive_endpoint

    from app.integrations.s3_provider import R2_ACCOUNT_ID

    if provider == "r2":
        account_id = str(config.get("accountId", ""))
        if account_id and not R2_ACCOUNT_ID.match(account_id):
            return False
    endpoint = derive_endpoint(provider, config)
    if not endpoint:
        return True
    if not storage_url_is_plain(endpoint):
        return False
    try:
        validate_public_https_url(endpoint, strict_dns=False, subject="Endpoint URL")
    except (UrlGuardError, ValueError):
        return False
    return True


def usable_storage_connection(db: Session, tenant_id: str):
    """The storage connection a tenant writes to: its own, else the platform's.
    A tenant-owned connection whose endpoint is not usable is skipped like an
    ERROR row, so the platform connection (or local disk, None) serves."""
    from app.models.connection import CONNECTION_STATUS_ERROR
    from app.models.tenant import PLATFORM_TENANT_ID
    from app.repositories.connection_repository import ConnectionRepository

    repo = ConnectionRepository(db)
    connection = repo.resolve_for_type(tenant_id, "storage")
    if (
        connection is not None
        and connection.tenant_id != PLATFORM_TENANT_ID
        and not endpoint_is_usable(connection.provider, connection.config_json or {})
    ):
        platform = repo.get_by_type(PLATFORM_TENANT_ID, "storage")
        if platform is not None and platform.status != CONNECTION_STATUS_ERROR:
            return platform
        return None
    return connection


_KEY_PREFIX = "conn:"

# Adapter cache - presign needs decrypted credentials per resolve. Keyed by
# connection id; the stored updated_at stamp busts the entry when the
# connection is edited (REPLACING it, so the cache stays bounded by the
# number of live connections - review finding: a (id, updated_at) composite
# key accumulated a stale adapter per edit, forever).
_adapters: Dict[str, Tuple[str, object]] = {}


def clear_adapter_cache() -> None:
    """Test seam."""
    _adapters.clear()


def _adapter_for(connection) -> "StorageService":
    from app.integrations.s3_provider import S3CompatibleAdapter
    from app.secrets import decrypt_secret

    from app.models.tenant import PLATFORM_TENANT_ID

    stamp = str(connection.updated_at)
    cached = _adapters.get(connection.id)
    if cached is not None and cached[0] == stamp:
        return cached[1]  # type: ignore[return-value]
    operator_owned = connection.tenant_id == PLATFORM_TENANT_ID
    # The cache is keyed on updated_at, so an edited endpoint is checked again
    # here; a tenant-owned connection needs a public https endpoint.
    if not operator_owned and not endpoint_is_usable(
        connection.provider, connection.config_json or {}
    ):
        raise UnresolvableKey(connection.id)
    credentials = decrypt_secret(connection.credentials_json) if connection.credentials_json else {}
    adapter = S3CompatibleAdapter.from_connection(
        connection.provider, connection.config_json or {}, credentials
    )
    adapter.operator_owned = operator_owned
    _adapters[connection.id] = (stamp, adapter)
    return adapter


class TenantStorage:
    """Connection-aware StorageService (plan 06 D1).

    Writes go to the resolved connection (tenant → platform; ERROR rows
    skipped) and return ``conn:``-prefixed keys; no connection = local disk
    with raw keys. Reads route by the KEY's prefix - through the connection
    that wrote the blob - never by whatever connection is current.
    """

    def __init__(self, db: Session, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self._local = LocalDiskStorage()

    def _write_connection(self):
        return usable_storage_connection(self.db, self.tenant_id)

    def _connection_for_key(self, connection_id: str):
        from app.models.tenant import PLATFORM_TENANT_ID
        from app.repositories.connection_repository import ConnectionRepository

        connection = ConnectionRepository(self.db).get_by_id(connection_id)
        # Stored keys are server-written, but verify ownership anyway: only
        # the caller's tenant or the platform default may serve its blobs.
        if connection is None or connection.tenant_id not in (self.tenant_id, PLATFORM_TENANT_ID):
            raise UnresolvableKey(connection_id)
        return connection

    @staticmethod
    def _split(key: str) -> Optional[Tuple[str, str]]:
        if not key.startswith(_KEY_PREFIX):
            return None
        _, connection_id, raw = key.split(":", 2)
        return connection_id, raw

    # ── StorageService protocol ───────────────────────────────────────────

    def save(self, key_hint: str, content: bytes, mime_type: str) -> str:
        from app.database import release_read_transactions

        # Resolve the connection and adapter first (they read the database), copy
        # what the write needs, then end read-only transactions so none is held
        # across the write itself. Nothing below touches the session.
        connection = self._write_connection()
        if connection is None:
            release_read_transactions()
            return self._local.save(key_hint, content, mime_type)
        adapter = _adapter_for(connection)
        connection_id = connection.id
        release_read_transactions()
        raw = adapter.save(key_hint, content, mime_type)
        return f"{_KEY_PREFIX}{connection_id}:{raw}"

    def resolve(self, key: str) -> Tuple[str, str]:
        parts = self._split(key)
        if parts is None:
            return self._local.resolve(key)
        connection_id, raw = parts
        return _adapter_for(self._connection_for_key(connection_id)).resolve(raw)

    def resolve_with_ownership(self, key: str) -> Tuple[str, str, bool]:
        """``resolve`` plus whether the connection that holds the key belongs to
        the platform (operator-owned), decided from the connection row."""
        from app.models.tenant import PLATFORM_TENANT_ID

        parts = self._split(key)
        if parts is None:
            kind, value = self._local.resolve(key)
            return kind, value, False
        connection_id, raw = parts
        connection = self._connection_for_key(connection_id)
        kind, value = _adapter_for(connection).resolve(raw)
        return kind, value, connection.tenant_id == PLATFORM_TENANT_ID

    def fetch(self, key: str) -> Tuple[bytes, Optional[str]]:
        parts = self._split(key)
        if parts is None:
            return self._local.fetch(key)
        connection_id, raw = parts
        return _adapter_for(self._connection_for_key(connection_id)).fetch(raw)

    def delete(self, key: str) -> None:
        parts = self._split(key)
        if parts is None:
            return self._local.delete(key)
        connection_id, raw = parts
        try:
            _adapter_for(self._connection_for_key(connection_id)).delete(raw)
        except UnresolvableKey:
            pass  # connection gone - nothing left to delete through

    def put(self, key_hint: str, content: bytes, mime_type: str) -> str:
        """Omnichannel contract - public URL straight back (no key persisted,
        so no prefix involved).

        The returned URL gets PERSISTED by the caller, so it must be STABLE:
        a connection without a CDN can only mint presigned URLs (1h TTL -
        historical media would 403 forever after, review finding), so those
        fall back to local disk. Key-based media resolution that lifts this
        limit = BL-078.
        """
        connection = self._write_connection()
        if connection is not None:
            adapter = _adapter_for(connection)
            if getattr(adapter, "cdn_base_url", ""):
                return adapter.put(key_hint, content, mime_type)
        return self._local.put(key_hint, content, mime_type)


def storage_for_tenant(db: Session, tenant_id: str) -> StorageService:
    """The storage every consumer should use (plan 06 D1)."""
    override = _storage  # set_storage() test seam wins when set
    if override is not None:
        return override
    return TenantStorage(db, tenant_id)


_storage: Optional[StorageService] = None


def get_storage() -> StorageService:
    """Legacy accessor - LOCAL disk only (unprefixed keys). Kept for call
    sites without a db/tenant context; new code uses `storage_for_tenant`."""
    global _storage
    if _storage is None:
        _storage = LocalDiskStorage()
    return _storage


def set_storage(storage: Optional[StorageService]) -> None:
    """Test seam."""
    global _storage
    _storage = storage
