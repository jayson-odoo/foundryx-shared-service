"""Core StorageService (sprint-2/03 — lifted from modules/omnichannel;
connection-driven since plan sprint-2/06 D1).

Media blobs behind one interface. Backend selection is DATA, not env: the
tenant's storage connection → the platform tenant's → local disk (zero-config
dev). The retired ``STORAGE_BACKEND`` env is gone; ``media_root`` stays (the
local adapter needs it).

Keys carry their writing backend: a blob stored through a connection gets a
``conn:<connection_id>:<raw>`` key, so reads resolve through the connection
that WROTE them — switching connections never breaks existing assets (they
stay resolvable while the old row exists; re-upload migration = BL-077).
Legacy unprefixed keys (and dev writes) resolve via local disk, unchanged.

Two usage styles:
- ``put``  — omnichannel's original contract: store + return the PUBLIC URL
  (local URLs ride the omnichannel media router; the module owns that mount).
- ``save`` / ``resolve`` / ``delete`` — key-based storage for core features
  that serve assets through their own routes (e.g. ``/public/branding/...``):
  ``save`` returns an opaque storage key persisted in the DB; ``resolve``
  turns it back into a local path or a remote URL to stream/redirect.
"""
import mimetypes
import uuid
from pathlib import Path
from typing import Dict, Optional, Protocol, Tuple

from sqlalchemy.orm import Session

from app.config import settings


class StorageService(Protocol):
    def put(self, key_hint: str, content: bytes, mime_type: str) -> str:
        """Store a blob; returns the public URL the frontend can render."""
        ...

    def save(self, key_hint: str, content: bytes, mime_type: str) -> str:
        """Store a blob; returns an opaque storage key (persist it)."""
        ...

    def resolve(self, key: str) -> Tuple[str, str]:
        """Storage key → ('path', local file path), ('url', STABLE remote
        URL — safe to cache immutably) or ('presigned', EXPIRING URL — never
        let clients cache it past the presign TTL)."""
        ...

    def fetch(self, key: str) -> Tuple[bytes, Optional[str]]:
        """Storage key → (raw bytes, stored content-type | None). Reads the
        blob straight from the backend so a serving route can stream it
        SAME-ORIGIN — no redirect to a presigned remote URL (which a browser
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


class LocalDiskStorage:
    """Dev adapter — writes under media_root."""

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

    def resolve(self, key: str) -> Tuple[str, str]:
        return ("path", str(self.root / key))

    def fetch(self, key: str) -> Tuple[bytes, Optional[str]]:
        path = self.root / key
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes(), mimetypes.guess_type(str(path))[0]

    def delete(self, key: str) -> None:
        try:
            (self.root / key).unlink()
        except FileNotFoundError:
            pass


class UnresolvableKey(Exception):
    """A ``conn:``-prefixed key whose connection is gone or belongs to another
    tenant (defense-in-depth — the polymorphic target_id rule)."""


_KEY_PREFIX = "conn:"

# Adapter cache — presign needs decrypted credentials per resolve. Keyed by
# connection id; the stored updated_at stamp busts the entry when the
# connection is edited (REPLACING it, so the cache stays bounded by the
# number of live connections — review finding: a (id, updated_at) composite
# key accumulated a stale adapter per edit, forever).
_adapters: Dict[str, Tuple[str, object]] = {}


def clear_adapter_cache() -> None:
    """Test seam."""
    _adapters.clear()


def _adapter_for(connection) -> "StorageService":
    from app.integrations.s3_provider import S3CompatibleAdapter
    from app.secrets import decrypt_secret

    stamp = str(connection.updated_at)
    cached = _adapters.get(connection.id)
    if cached is not None and cached[0] == stamp:
        return cached[1]  # type: ignore[return-value]
    credentials = decrypt_secret(connection.credentials_json) if connection.credentials_json else {}
    adapter = S3CompatibleAdapter.from_connection(
        connection.provider, connection.config_json or {}, credentials
    )
    _adapters[connection.id] = (stamp, adapter)
    return adapter


class TenantStorage:
    """Connection-aware StorageService (plan 06 D1).

    Writes go to the resolved connection (tenant → platform; ERROR rows
    skipped) and return ``conn:``-prefixed keys; no connection = local disk
    with raw keys. Reads route by the KEY's prefix — through the connection
    that wrote the blob — never by whatever connection is current.
    """

    def __init__(self, db: Session, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self._local = LocalDiskStorage()

    def _write_connection(self):
        from app.repositories.connection_repository import ConnectionRepository

        return ConnectionRepository(self.db).resolve_for_type(self.tenant_id, "storage")

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
        connection = self._write_connection()
        if connection is None:
            return self._local.save(key_hint, content, mime_type)
        raw = _adapter_for(connection).save(key_hint, content, mime_type)
        return f"{_KEY_PREFIX}{connection.id}:{raw}"

    def resolve(self, key: str) -> Tuple[str, str]:
        parts = self._split(key)
        if parts is None:
            return self._local.resolve(key)
        connection_id, raw = parts
        return _adapter_for(self._connection_for_key(connection_id)).resolve(raw)

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
            pass  # connection gone — nothing left to delete through

    def put(self, key_hint: str, content: bytes, mime_type: str) -> str:
        """Omnichannel contract — public URL straight back (no key persisted,
        so no prefix involved).

        The returned URL gets PERSISTED by the caller, so it must be STABLE:
        a connection without a CDN can only mint presigned URLs (1h TTL —
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
    """Legacy accessor — LOCAL disk only (unprefixed keys). Kept for call
    sites without a db/tenant context; new code uses `storage_for_tenant`."""
    global _storage
    if _storage is None:
        _storage = LocalDiskStorage()
    return _storage


def set_storage(storage: Optional[StorageService]) -> None:
    """Test seam."""
    global _storage
    _storage = storage
