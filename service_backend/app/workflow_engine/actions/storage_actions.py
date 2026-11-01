"""Storage actions (plan sprint-2/09 D8) - push / resolve / delete a file via
``storage_for_tenant``. ``storage.get`` resolves a key to a URL + metadata ONLY
(never loads bytes into the run context - the binary-in-JSON trap). The run owns
the transaction; these touch the storage backend, not the DB.
"""
import mimetypes
import os
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.models.tenant import PLATFORM_TENANT_ID
from app.repositories.connection_repository import ConnectionRepository
from app.services.storage import _KEY_PREFIX, storage_for_tenant
from app.workflow_engine.context import render_field


class ActionError(Exception):
    """A node failed - halts the run (D14)."""


def _resolve_key(config: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    """Render + validate a tenant-authored storage key. Reject path traversal -
    the key is merge-rendered from tenant config and lands in LocalDiskStorage
    (the default/fallback backend), which joins it onto the media root without
    sanitizing; `../` would escape the root (read/delete arbitrary files)."""
    key = render_field(config.get("key"), ctx).strip()
    if not key:
        raise ActionError("Storage key is empty after merging.")
    normalized = key.replace("\\", "/")
    if (
        normalized.startswith("/")
        or normalized.startswith("~")
        or "\x00" in normalized
        or any(part == ".." for part in normalized.split("/"))
    ):
        raise ActionError("Storage key must be a relative path without '..'.")
    return key


def _tenant_prefix(tenant_id: str) -> str:
    return f"workflows/{tenant_id}/"


def _check_key_reach(db: Session, tenant_id: str, key: str) -> None:
    """Workflow storage nodes reach only the tenant's own connection keys or
    keys under `workflows/<tenant_id>/` (also on the platform connection)."""
    refused = ActionError("Storage key is not reachable from this workflow.")
    prefix = _tenant_prefix(tenant_id)
    if key.startswith(_KEY_PREFIX):
        parts = key.split(":", 2)
        if len(parts) != 3 or not all(parts):
            raise refused
        connection = ConnectionRepository(db).get_by_id(parts[1])
        if connection is None:
            raise refused
        if connection.tenant_id == tenant_id:
            return
        if connection.tenant_id == PLATFORM_TENANT_ID and parts[2].startswith(prefix) and len(parts[2]) > len(prefix):
            return
        raise refused
    if not (key.startswith(prefix) and len(key) > len(prefix)):
        raise refused


def _mime_for(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


def _url_and_meta(storage, key: str) -> Dict[str, Any]:
    """resolve() → a URL + best-effort size/mime (local paths get a stat)."""
    kind, value = storage.resolve(key)
    size = None
    if kind == "path":
        try:
            size = os.path.getsize(value)
        except OSError:
            size = None
    return {"url": value, "size": size, "mime": _mime_for(key)}


def storage_put(db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    key = _tenant_prefix(tenant_id) + _resolve_key(config, ctx)
    content = render_field(config.get("content"), ctx).encode("utf-8")
    mime = _mime_for(key)
    storage = storage_for_tenant(db, tenant_id)
    stored_key = storage.save(key, content, mime)
    kind, value = storage.resolve(stored_key)
    return {"url": value, "key": stored_key, "size": len(content), "mime": mime}


def storage_get(db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    key = _resolve_key(config, ctx)
    _check_key_reach(db, tenant_id, key)
    return _url_and_meta(storage_for_tenant(db, tenant_id), key)


def storage_delete(db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    key = _resolve_key(config, ctx)
    _check_key_reach(db, tenant_id, key)
    storage_for_tenant(db, tenant_id).delete(key)
    return {"deleted": True}
