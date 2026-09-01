"""Branding routes (plan sprint-2/03). Thin: validate, delegate to
BrandingService, shape HTTP.

Two routers:
- ``router``        - the caller's OWN tenant, gated branding.read / branding.manage.
- ``public_router`` - pre-auth consumption (sign-in page, tab metadata, theme
  CSS, asset streaming). Unknown slug = uniform defaults, NEVER 404 - tenant
  existence is not enumerable here.
"""
import os

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from app.schemas.branding import (
    BrandingResponse,
    BrandingUpdateRequest,
    PublicBrandingResponse,
)
from app.services.branding_service import (
    BrandingError,
    BrandingService,
    PlatformTenantBrandingRejected,
    TenantNotFound,
)

router = APIRouter()
public_router = APIRouter()


def raise_branding_http(e: Exception):
    """ONE service-exception → HTTP translator for BOTH branding routers
    (review finding: two diverging copies = divergent error contracts)."""
    if isinstance(e, BrandingError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="; ".join(e.errors),
        )
    if isinstance(e, PlatformTenantBrandingRejected):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The platform tenant keeps stock branding.",
        )
    if isinstance(e, TenantNotFound):
        raise HTTPException(status_code=404, detail="Tenant not found")
    raise e


_raise = raise_branding_http


# ---- own tenant ----


@router.get("", response_model=BrandingResponse)
def get_branding(
    user: User = Depends(require_permission("branding.read")),
    db: Session = Depends(get_db),
):
    return BrandingService(db).get(user.tenant_id)


@router.get("/template")
def get_template(
    user: User = Depends(require_permission("branding.read")),
    db: Session = Depends(get_db),
):
    return BrandingService(db).template(user.tenant_id)


@router.put("", response_model=BrandingResponse)
def update_branding(
    payload: BrandingUpdateRequest,
    user: User = Depends(require_permission("branding.manage")),
    db: Session = Depends(get_db),
):
    try:
        return BrandingService(db).update(
            user.tenant_id, payload.slogan, payload.tokens, payload.socials, payload.footer,
            app_name=payload.appName,
        )
    except Exception as e:  # noqa: BLE001 - translated to HTTP below
        _raise(e)


@router.post("/assets/{kind}", response_model=BrandingResponse)
async def upload_asset(
    kind: str,
    file: UploadFile = File(...),
    user: User = Depends(require_permission("branding.manage")),
    db: Session = Depends(get_db),
):
    content = await file.read()
    try:
        return BrandingService(db).upload_asset(
            user.tenant_id, kind, content, file.content_type or "", file.filename or ""
        )
    except Exception as e:  # noqa: BLE001
        _raise(e)


@router.delete("/assets/{kind}", response_model=BrandingResponse)
def remove_asset(
    kind: str,
    user: User = Depends(require_permission("branding.manage")),
    db: Session = Depends(get_db),
):
    try:
        return BrandingService(db).remove_asset(user.tenant_id, kind)
    except Exception as e:  # noqa: BLE001
        _raise(e)


# ---- public (pre-auth) ----


@public_router.get("/{slug}", response_model=PublicBrandingResponse)
def public_branding(slug: str, db: Session = Depends(get_db)):
    return BrandingService(db).public(slug)


@public_router.get("/{slug}/theme.css")
def public_theme_css(slug: str, db: Session = Depends(get_db)):
    css, version = BrandingService(db).theme_css(slug)
    return Response(
        content=css,
        media_type="text/css",
        headers={
            # URLs carry ?v={version} - safe to cache aggressively.
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"branding-{slug}-{version}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@public_router.get("/{slug}/asset/{kind}")
def public_asset(slug: str, kind: str, db: Session = Depends(get_db)):
    # Resolution lives in the service since plan 06 D1 - the key's backend is
    # the owning tenant's connection chain, not a global storage singleton.
    found = BrandingService(db).resolve_asset(slug, kind)
    if found is None:
        raise HTTPException(status_code=404, detail="Not found")
    location, value, mime, disposition = found
    headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "Content-Disposition": disposition,
        # Uploaded SVGs can embed <script>; <img> keeps them inert but this
        # route is directly navigable on the API origin - sandbox the document
        # so scripts NEVER execute, whatever the format (stored-XSS guard;
        # full SVG sanitization remains BL-067 defense-in-depth).
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        "X-Content-Type-Options": "nosniff",
    }
    if location == "presigned":
        # The target URL expires (1h presign TTL) - an immutable-cached
        # redirect would replay the dead signature for a year (review
        # finding, shared with /public/avatars).
        headers["Cache-Control"] = "private, max-age=300"
        return RedirectResponse(value, headers=headers)
    if location == "url":
        return RedirectResponse(value, headers=headers)
    # A DB row can outlive its local blob (media/ is gitignored - a reseed keeps
    # the branding row, the file is gone). FileResponse on a missing path raises
    # → a 500; serve a clean 404 so the <img> just falls back (caught live).
    if not os.path.exists(value):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(value, media_type=mime, headers=headers)
