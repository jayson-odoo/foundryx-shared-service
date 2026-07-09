"""Omnichannel media serving.

ONE authed route on the ``/omnichannel/media`` mount (declared public in the
manifest — auth is enforced INSIDE):

``GET /omnichannel/media/{message_id}`` (plan 12 AC-12-05): blob-fetch a message's
stored media, authed by **either** a session JWT (agent browser via
``apiFetchBlob``) **or** a workspace API key (EMS). Both paths are tenant-scoped;
the API-key path is additionally workspace-scoped + re-checks the module is active
(mirrors ``api_auth.get_api_workspace``); the session path requires the
``conversations.read`` permission (the same gate that exposes the mediaUrl on
``/contacts/{id}/messages``). ``Content-Security-Policy: sandbox`` + nosniff.
No auth → 401; a message id the caller can't reach → 404.

NOTE: the legacy unauthenticated ``GET /{path:path}`` local-disk route was removed
(plan 12 review) — it co-served outbound blobs under ``media_root`` with no auth/
CSP. All blobs now flow through this authed endpoint only.
"""
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from jose import JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import effective_permission_keys
from app.models.tenant import DEFAULT_TENANT_ID
from app.repositories.module_repository import ModuleRepository
from app.repositories.user_repository import UserRepository
from app.security import decode_access_token
from app.services.storage import UnresolvableKey, storage_for_tenant

from ..api_auth import MODULE_NAME, _parse_bearer
from ..repositories.contact_repository import ContactRepository
from ..services.api_key_service import ApiKeyService

router = APIRouter()

_MEDIA_HEADERS = {
    "Content-Security-Policy": "sandbox",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, max-age=300",
}
_READ_PERMISSION = "conversations.read"


def _resolve_principal(
    authorization: Optional[str], db: Session
) -> Tuple[str, Optional[str]]:
    """Resolve either auth path → (tenant_id, workspace_id | None). API-key auth
    is workspace-scoped (+ module-active re-check); session auth is tenant-scoped
    (workspace None) and gated by ``conversations.read``. Raises 401 on any miss
    (uniform — no enumeration)."""
    token = _parse_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing or invalid credentials.")
    # Workspace API key (EMS path).
    if token.startswith("fxw_"):
        row = ApiKeyService(db).resolve(token)
        if row is None:
            raise HTTPException(status_code=401, detail="Invalid API key.")
        # Re-check the service is active for the key's tenant (mirror get_api_workspace).
        if not ModuleRepository(db).is_active(row.tenant_id, MODULE_NAME):
            raise HTTPException(status_code=403, detail="This service is not enabled.")
        return row.tenant_id, row.workspace_id
    # Session JWT (agent path).
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    user_id = payload.get("sub")
    if not user_id or payload.get("kind") == "profile":
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    tenant_id = payload.get("tenant_id") or DEFAULT_TENANT_ID
    user = UserRepository(db).get_by_id(user_id, tenant_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    # Permission gate: only a conversations reader may fetch media (the same gate
    # that exposes the mediaUrl on /contacts/{id}/messages). Read fresh, not from
    # the JWT (RBAC edits apply immediately).
    if _READ_PERMISSION not in effective_permission_keys(user):
        raise HTTPException(status_code=403, detail=f"Missing permission: {_READ_PERMISSION}")
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

    # Stream the bytes back SAME-ORIGIN (plan 12 review). A remote backend (R2/
    # S3) is read through the storage adapter and re-served from our origin —
    # never a 307 to a presigned bucket URL, which the browser then CORS-blocks
    # (the client sends x-tenant-slug/Authorization, so the redirected fetch
    # triggers an OPTIONS preflight the bucket 403s). Local disk still streams
    # from the media root.
    try:
        data, stored_mime = storage_for_tenant(db, tenant_id).fetch(message.media_key)
    except (UnresolvableKey, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Not found")
    media_type = message.media_mime or stored_mime or "application/octet-stream"
    return Response(content=data, media_type=media_type, headers=_MEDIA_HEADERS)
