"""Permission catalog business logic — grouped catalog + module sync (plan 03 §4).

`sync_permissions(module, rows)` is the App-Store mechanism, reused by core at
bootstrap (module = 'core'). The catalog endpoint returns resources grouped with
their actions, which the role Permissions tab renders as per-resource dropdowns.
"""
import csv
from pathlib import Path
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.repositories.permission_repository import PermissionRepository
from app.schemas.permission import PermissionActionOut, PermissionResourceOut

CORE_MODULE = "core"
# Platform-operator permissions (plan 07 §5) — never grantable/visible to
# tenant role editors; enforced by require_platform_permission + catalog filter.
PLATFORM_MODULE = "platform"
# app/services/permission_service.py -> app/permissions/*.csv
CORE_CSV = Path(__file__).resolve().parent.parent / "permissions" / "permissions.csv"
PLATFORM_CSV = Path(__file__).resolve().parent.parent / "permissions" / "platform_permissions.csv"


def load_csv(path: Path) -> List[dict]:
    """Read a module permissions CSV into row dicts (resource/action/labels/desc)."""
    with open(path, newline="", encoding="utf-8") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


class PermissionService:
    def __init__(self, db: Session):
        self.repo = PermissionRepository(db)

    def catalog(
        self,
        include_platform: bool = False,
        installed_modules: Optional[Set[str]] = None,
    ) -> List[PermissionResourceOut]:
        """All permissions grouped by resource (module preserved for UI grouping).

        Platform-module rows are hidden unless the caller is in the platform
        tenant (plan 07 §5) — tenant role editors never see or grant them.
        When ``installed_modules`` is given (tenant callers, plan 08 §6),
        App-Store module rows are limited to modules installed for that tenant
        — uninstalled modules' perms aren't visible or grantable.
        """
        grouped: Dict[str, PermissionResourceOut] = {}
        order: List[str] = []
        for perm in self.repo.list_all():
            if perm.module == PLATFORM_MODULE and not include_platform:
                continue
            if (
                installed_modules is not None
                and perm.module not in (CORE_MODULE, PLATFORM_MODULE)
                and perm.module not in installed_modules
            ):
                continue
            res = grouped.get(perm.resource)
            if res is None:
                res = PermissionResourceOut(
                    resource=perm.resource,
                    resourceLabel=perm.resource_label,
                    module=perm.module,
                    actions=[],
                )
                grouped[perm.resource] = res
                order.append(perm.resource)
            res.actions.append(PermissionActionOut.model_validate(perm))
        return [grouped[r] for r in order]

    def all_keys(self) -> List[str]:
        return self.repo.all_keys()

    def sync_permissions(self, module: str, rows: List[dict]) -> None:
        """Upsert a module's declared permissions; delete its undeclared ones."""
        self.repo.sync(module, rows)

    def sync_core(self) -> None:
        """Sync the core catalog from the bundled CSV (core = 'module zero')."""
        self.sync_permissions(CORE_MODULE, load_csv(CORE_CSV))

    def sync_platform(self) -> None:
        """Sync the platform-operator catalog (plan 07 §5)."""
        self.sync_permissions(PLATFORM_MODULE, load_csv(PLATFORM_CSV))
