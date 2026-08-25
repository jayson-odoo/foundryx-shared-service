"""Operator surface of tenant branding (plan sprint-2/03) - the same
BrandingService behind the console's Branding tab. ALL routes operator-only:
``require_platform_permission("tenants.manage_branding")`` = permission key
AND platform-tenant membership (follows platform_tenant_modules)."""
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_platform_permission
from app.models.user import User
from app.api.v1.branding import raise_branding_http as _raise
from app.schemas.branding import BrandingResponse, BrandingUpdateRequest
from app.services.branding_service import BrandingService

router = APIRouter()

MANAGE = "tenants.manage_branding"


@router.get("/{tenant_id}/branding", response_model=BrandingResponse)
def get_branding(
    tenant_id: str,
    user: User = Depends(require_platform_permission(MANAGE)),
    db: Session = Depends(get_db),
):
    try:
        return BrandingService(db).get_checked(tenant_id)
    except Exception as e:  # noqa: BLE001 - translated to HTTP below
        _raise(e)


@router.get("/{tenant_id}/branding/template")
def get_template(
    tenant_id: str,
    user: User = Depends(require_platform_permission(MANAGE)),
    db: Session = Depends(get_db),
):
    try:
        return BrandingService(db).template_checked(tenant_id)
    except Exception as e:  # noqa: BLE001
        _raise(e)


@router.put("/{tenant_id}/branding", response_model=BrandingResponse)
def update_branding(
    tenant_id: str,
    payload: BrandingUpdateRequest,
    user: User = Depends(require_platform_permission(MANAGE)),
    db: Session = Depends(get_db),
):
    try:
        return BrandingService(db).update(
            tenant_id, payload.slogan, payload.tokens, payload.socials, payload.footer,
            app_name=payload.appName,
        )
    except Exception as e:  # noqa: BLE001
        _raise(e)


@router.post("/{tenant_id}/branding/assets/{kind}", response_model=BrandingResponse)
async def upload_asset(
    tenant_id: str,
    kind: str,
    file: UploadFile = File(...),
    user: User = Depends(require_platform_permission(MANAGE)),
    db: Session = Depends(get_db),
):
    content = await file.read()
    try:
        return BrandingService(db).upload_asset(
            tenant_id, kind, content, file.content_type or "", file.filename or ""
        )
    except Exception as e:  # noqa: BLE001
        _raise(e)


@router.delete("/{tenant_id}/branding/assets/{kind}", response_model=BrandingResponse)
def remove_asset(
    tenant_id: str,
    kind: str,
    user: User = Depends(require_platform_permission(MANAGE)),
    db: Session = Depends(get_db),
):
    try:
        return BrandingService(db).remove_asset(tenant_id, kind)
    except Exception as e:  # noqa: BLE001
        _raise(e)
