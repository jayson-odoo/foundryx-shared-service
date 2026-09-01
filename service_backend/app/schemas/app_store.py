"""App Store wire shapes (plan 08 §7) - camelCase out, matching types/app-store.ts."""
from datetime import datetime
from typing import List, Optional


from app.schemas.base import ApiModel

from app.models.module import Module, TenantModule, parse_version


class StoreModuleOut(ApiModel):
    name: str
    title: str
    description: str
    icon: Optional[str] = None
    version: str
    status: Optional[str] = None
    installedVersion: Optional[str] = None
    updateAvailable: bool = False
    installedAt: Optional[datetime] = None
    # Module platform v2 (plan sprint-3/10): declared deps + provided
    # capabilities + the errored/availability flags for dependency-aware UX.
    requires: List[dict] = []
    optional: List[dict] = []
    provides: List[dict] = []
    errored: bool = False
    errorMessage: Optional[str] = None
    # True when this module's hard requires are met for the tenant (else the
    # install button warns + offers cascade-with-consent).
    availabilityOk: bool = True


class InstalledModuleOut(ApiModel):
    module: str
    status: str
    version: str


class UninstallRequest(ApiModel):
    confirmName: str


def store_module_out(
    module: Module,
    state: Optional[TenantModule],
    *,
    manifest: Optional[dict] = None,
    errored: Optional[str] = None,
    availability_ok: bool = True,
) -> StoreModuleOut:
    update_available = bool(
        state and parse_version(module.version) > parse_version(state.installed_version)
    )
    manifest = manifest or {}
    return StoreModuleOut(
        name=module.name,
        title=module.title,
        description=module.description or "",
        icon=module.icon,
        version=module.version,
        status=state.status if state else None,
        installedVersion=state.installed_version if state else None,
        updateAvailable=update_available,
        installedAt=state.installed_at if state else None,
        requires=manifest.get("requires", []) or [],
        optional=manifest.get("optional", []) or [],
        provides=manifest.get("provides", []) or [],
        errored=errored is not None,
        errorMessage=errored,
        availabilityOk=availability_ok,
    )
