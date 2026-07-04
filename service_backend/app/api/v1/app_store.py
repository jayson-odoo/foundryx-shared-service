"""Tenant-side App Store routes (plan 08 §7) — act on the CALLER's tenant only,
gated by the ``app_store.*`` core permissions. Thin: delegate to AppStoreService.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from app.schemas.app_store import (
    InstalledModuleOut,
    StoreModuleOut,
    UninstallRequest,
    store_module_out,
)
from app.services.app_store_service import (
    AppStoreError,
    AppStoreService,
    ConfirmMismatch,
    ModuleNotFound,
)

router = APIRouter()


def store_error_http(exc: AppStoreError) -> HTTPException:
    """Map AppStoreService errors to HTTP — shared with the operator routes
    (platform_tenant_modules) so both entry points fail identically."""
    if isinstance(exc, ModuleNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    if isinstance(exc, ConfirmMismatch):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.message)
    return HTTPException(status.HTTP_409_CONFLICT, exc.message)


def run_store_action(action, *args) -> StoreModuleOut:
    try:
        module, state = action(*args)
    except AppStoreError as exc:
        raise store_error_http(exc)
    return store_module_out(module, state)


@router.get("/modules", response_model=List[StoreModuleOut])
def catalog(
    current_user: User = Depends(require_permission("app_store.read")),
    db: Session = Depends(get_db),
) -> List[StoreModuleOut]:
    service = AppStoreService(db)
    from app.module_loader import ERRORED_MODULES, discover_manifests
    from app.module_platform.dependencies import check_requires

    manifests = {m["module_name"]: m for m in discover_manifests()}
    out = []
    for module, state in service.list_for_tenant(current_user.tenant_id):
        manifest = manifests.get(module.name, {})
        req = check_requires(db, current_user.tenant_id, manifest)
        out.append(
            store_module_out(
                module,
                state,
                manifest=manifest,
                errored=ERRORED_MODULES.get(module.name),
                availability_ok=req["ok"],
            )
        )
    return out


@router.get("/installed", response_model=List[InstalledModuleOut])
def installed(
    current_user: User = Depends(require_permission("app_store.read")),
    db: Session = Depends(get_db),
) -> List[InstalledModuleOut]:
    return [
        InstalledModuleOut(
            module=tm.module.name, status=tm.status, version=tm.installed_version
        )
        for tm in AppStoreService(db).installed(current_user.tenant_id)
    ]


@router.post("/modules/{name}/install", response_model=StoreModuleOut)
def install(
    name: str,
    current_user: User = Depends(require_permission("app_store.install")),
    db: Session = Depends(get_db),
) -> StoreModuleOut:
    return run_store_action(AppStoreService(db).install, current_user.tenant_id, name)


@router.post("/modules/{name}/update", response_model=StoreModuleOut)
def update(
    name: str,
    current_user: User = Depends(require_permission("app_store.install")),
    db: Session = Depends(get_db),
) -> StoreModuleOut:
    return run_store_action(AppStoreService(db).update, current_user.tenant_id, name)


@router.post("/modules/{name}/deactivate", response_model=StoreModuleOut)
def deactivate(
    name: str,
    current_user: User = Depends(require_permission("app_store.deactivate")),
    db: Session = Depends(get_db),
) -> StoreModuleOut:
    return run_store_action(AppStoreService(db).deactivate, current_user.tenant_id, name)


@router.post("/modules/{name}/reactivate", response_model=StoreModuleOut)
def reactivate(
    name: str,
    current_user: User = Depends(require_permission("app_store.deactivate")),
    db: Session = Depends(get_db),
) -> StoreModuleOut:
    return run_store_action(AppStoreService(db).reactivate, current_user.tenant_id, name)


@router.post("/modules/{name}/uninstall")
def uninstall(
    name: str,
    payload: UninstallRequest,
    current_user: User = Depends(require_permission("app_store.uninstall")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        AppStoreService(db).uninstall(current_user.tenant_id, name, payload.confirmName)
    except AppStoreError as exc:
        raise store_error_http(exc)
    return {"ok": True}
