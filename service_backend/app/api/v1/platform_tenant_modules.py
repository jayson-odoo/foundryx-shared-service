"""Operator App Store routes (plan 08 §7) - manage ANY tenant's modules from the
Platform Console (support path). Same AppStoreService as the tenant-side
routes (error mapping shared via ``app_store.run_store_action``); gated by
``tenants.manage_modules`` (platform key + platform-tenant membership via
``require_platform_permission``).
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.app_store import run_store_action, store_error_http
from app.database import get_db
from app.dependencies import require_platform_permission
from app.models.user import User
from app.schemas.app_store import StoreModuleOut, UninstallRequest, store_module_out
from app.services.app_store_service import AppStoreError, AppStoreService
from app.services.tenant_service import TenantNotFound, TenantService

router = APIRouter()

MANAGE = "tenants.manage_modules"


def _tenant_or_404(db: Session, tenant_id: str) -> None:
    """Existence check via the service layer (no DB logic in routers)."""
    try:
        TenantService(db).get(tenant_id)
    except TenantNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")


@router.get("/{tenant_id}/modules", response_model=List[StoreModuleOut])
def tenant_modules(
    tenant_id: str,
    current_user: User = Depends(require_platform_permission(MANAGE)),
    db: Session = Depends(get_db),
) -> List[StoreModuleOut]:
    _tenant_or_404(db, tenant_id)
    return [
        store_module_out(module, state)
        for module, state in AppStoreService(db).list_for_tenant(tenant_id)
    ]


@router.post("/{tenant_id}/modules/{name}/install", response_model=StoreModuleOut)
def install(
    tenant_id: str,
    name: str,
    current_user: User = Depends(require_platform_permission(MANAGE)),
    db: Session = Depends(get_db),
) -> StoreModuleOut:
    _tenant_or_404(db, tenant_id)
    return run_store_action(AppStoreService(db).install, tenant_id, name)


@router.post("/{tenant_id}/modules/{name}/update", response_model=StoreModuleOut)
def update(
    tenant_id: str,
    name: str,
    current_user: User = Depends(require_platform_permission(MANAGE)),
    db: Session = Depends(get_db),
) -> StoreModuleOut:
    _tenant_or_404(db, tenant_id)
    return run_store_action(AppStoreService(db).update, tenant_id, name)


@router.post("/{tenant_id}/modules/{name}/deactivate", response_model=StoreModuleOut)
def deactivate(
    tenant_id: str,
    name: str,
    current_user: User = Depends(require_platform_permission(MANAGE)),
    db: Session = Depends(get_db),
) -> StoreModuleOut:
    _tenant_or_404(db, tenant_id)
    return run_store_action(AppStoreService(db).deactivate, tenant_id, name)


@router.post("/{tenant_id}/modules/{name}/reactivate", response_model=StoreModuleOut)
def reactivate(
    tenant_id: str,
    name: str,
    current_user: User = Depends(require_platform_permission(MANAGE)),
    db: Session = Depends(get_db),
) -> StoreModuleOut:
    _tenant_or_404(db, tenant_id)
    return run_store_action(AppStoreService(db).reactivate, tenant_id, name)


@router.post("/{tenant_id}/modules/{name}/uninstall")
def uninstall(
    tenant_id: str,
    name: str,
    payload: UninstallRequest,
    current_user: User = Depends(require_platform_permission(MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    _tenant_or_404(db, tenant_id)
    try:
        AppStoreService(db).uninstall(tenant_id, name, payload.confirmName)
    except AppStoreError as exc:
        raise store_error_http(exc)
    return {"ok": True}
