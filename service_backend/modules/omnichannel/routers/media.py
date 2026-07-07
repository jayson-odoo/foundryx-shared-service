"""Omnichannel media serving.

Two routes on the ``/omnichannel/media`` mount (declared public in the manifest —
auth is enforced INSIDE):

- ``GET /omnichannel/media/{message_id}`` (plan 12 AC-12-05): the ONE blob-fetch
  endpoint for a message's stored media, authed by **either** a session JWT
  (agent browser via ``apiFetchBlob``) **or** a workspace API key (EMS). Tenant/
  workspace-scoped; ``Content-Security-Policy: sandbox`` + nosniff. A cross-tenant/
  workspace message id → 404; no auth → 401.
- ``GET /omnichannel/media/{path:path}`` (legacy): the local-disk StorageService
  adapter's public URL for pre-plan-12 inbound media. Multi-segment keys only.
"""
from pathlib import Path
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response
from jose import JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.tenant import DEFAULT_TENANT_ID
from app.repositories.user_repository import UserRepository
from app.security import decode_access_token
from app.services.storage import UnresolvableKey, storage_for_tenant

from ..api_auth import _parse_bearer
from ..repositories.contact_repository import ContactRepository
from ..services.api_key_service import ApiKeyService

router = APIRouter()

_MEDIA_HEADERS = {
    "Content-Security-Policy": "sandbox",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, max-age=300",
}


def _resolve_principal(
    authorization: Optional[str], db: Session
) -> Tuple[str, Optional[str]]:
    """Resolve either auth path → (tenant_id, workspace_id | None). API-key auth
    is workspace-scoped; session auth is tenant-scoped (workspace None). Raises
    401 on any miss (uniform — no enumeration)."""
    token = _parse_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing or invalid credentials.")
    # Workspace API key (EMS path).
    if token.startswith("fxw_"):
        row = ApiKeyService(db).resolve(token)
        if row is None:
            raise HTTPException(status_code=401, detail="Invalid API key.")
        return row.tenant_id, row.workspace_id
    # Session JWT (agent path).
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    tenant_id = payload.get("tenant_id") or DEFAULT_TENANT_ID
    user = UserRepository(db).get_by_id(user_id, tenant_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    return tenant_id, None


@router.get("/{message_id}")
def serve_message_media(
    message_id: str,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Response:
    tenant_id, workspace_id = _resolve_principal(authorization, db)
    # Defense-in-depth: resolve the message tenant-scoped (never unscoped).
    message = ContactRepository(db).get_message(message_id, tenant_id)
    if message is None or not message.media_key:
        raise HTTPException(status_code=404, detail="Not found")
    # API-key callers are additionally workspace-scoped (AC-12-27).
    if workspace_id is not None:
        contact = ContactRepository(db).get_by_id(message.contact_id, tenant_id)
        if contact is None or contact.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Not found")

    try:
        kind, value = storage_for_tenant(db, tenant_id).resolve(message.media_key)
    except (UnresolvableKey, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Not found")
    media_type = message.media_mime or "application/octet-stream"
    if kind == "path":
        path = Path(value)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(path, media_type=media_type, headers=_MEDIA_HEADERS)
    # 'url' | 'presigned' — redirect (presigned expires; never cache it hard).
    return RedirectResponse(value, headers=_MEDIA_HEADERS)


@router.get("/{path:path}")
def serve_local_media(path: str) -> FileResponse:
    root = Path(settings.media_root).resolve()
    target = (root / path).resolve()
    # Path-traversal guard: target must be INSIDE media_root.
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target)
