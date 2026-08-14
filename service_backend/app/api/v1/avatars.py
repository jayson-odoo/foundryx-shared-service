"""Public avatar serving (plan sprint-2/06 D4).

Avatars render in plain ``<img>`` tags, which can't carry the Bearer header -
so this route is PUBLIC, like /public/branding/* (the user id is an
unguessable UUID; URLs carry ?v= for immutable caching). The stored KEY is
resolved per request: local file → stream, connection-backed → redirect to
the CDN/presigned URL.
"""
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.avatar_service import AvatarService

public_router = APIRouter()

_SECURITY_HEADERS = {
    # Uploaded bytes are sniff-gated to raster formats, but sandbox anyway -
    # this route is directly navigable on the API origin (branding lesson).
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "X-Content-Type-Options": "nosniff",
}
# Stable content (?v= busts on change) - cache hard.
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable", **_SECURITY_HEADERS}
# Presigned target URLs EXPIRE (1h TTL) - an immutable-cached redirect would
# keep replaying the dead signature for a year (review finding). Cache well
# under the presign TTL instead.
_SHORT_LIVED = {"Cache-Control": "private, max-age=300", **_SECURITY_HEADERS}


@public_router.get("/{user_id}")
def public_avatar(user_id: str, db: Session = Depends(get_db)):
    # Unscoped on purpose: public cross-tenant route, UUID = capability -
    # but lifecycle still applies: trashed users and archived tenants are
    # logically gone, their avatars must not stay publicly fetchable
    # (review finding).
    user = (
        db.query(User)
        .filter(User.id == user_id, User.is_trashed.is_(False))
        .first()
    )
    if user is not None and user.tenant is not None:
        tenant_status = user.tenant.status
        if tenant_status is not None and tenant_status.is_archived:
            user = None
    found = AvatarService(db).resolve(user) if user else None
    if found is None:
        raise HTTPException(status_code=404, detail="Not found")
    location, value = found
    if location == "url":
        return RedirectResponse(value, headers=_IMMUTABLE)
    if location == "presigned":
        return RedirectResponse(value, headers=_SHORT_LIVED)
    # Local file - a blob deleted out-of-band must 404, not let FileResponse
    # raise at send time (500 on a public route; review finding).
    if not os.path.isfile(value):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(value, headers=_IMMUTABLE)
