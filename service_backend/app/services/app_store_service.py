"""App Store business logic (plan 08) — ONE service behind both entry points
(tenant-side ``/app-store/*`` and operator ``/platform/tenants/{id}/modules/*``).

Lifecycle semantics (§5):
- install     → tenant_modules ACTIVE @ current code version → module
                ``install_tenant`` seed → grant the module's permission rows to
                the tenant's Admin role (other roles: admin assigns manually).
- deactivate  → INACTIVE: routes 403 (require_module), data kept, grants
                kept-but-inert. reactivate → ACTIVE, instant.
- update      → module ``update_tenant(tenant_id, from_version)`` → re-grant
                NEW module perms to Admin → bump installed_version.
- uninstall   → typed-confirmation → module ``uninstall_tenant`` wipes the
                tenant's rows from every module table → revoke module perm
                grants from ALL the tenant's roles → delete the row. The module
                schema + other tenants' data are never touched.
"""
import importlib
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.module import (
    MODULE_STATUS_ACTIVE,
    MODULE_STATUS_INACTIVE,
    Module,
    TenantModule,
    parse_version,
)
from app.models.permission import Permission
from app.models.role import Role
from app.models.tenant import Tenant
from app.repositories.module_repository import ModuleRepository


class AppStoreError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class ModuleNotFound(AppStoreError):
    pass


class AlreadyInstalled(AppStoreError):
    pass


class NotInstalled(AppStoreError):
    pass


class InvalidState(AppStoreError):
    pass


class ConfirmMismatch(AppStoreError):
    pass


class PlatformTenantProtected(AppStoreError):
    pass


class RequiresUnmet(AppStoreError):
    """A hard ``requires`` dep is missing/inactive/version-short (plan 10 D4).
    Carries the resolution plan so the router can offer cascade-with-consent."""

    def __init__(self, message: str, detail: dict):
        super().__init__(message)
        self.detail = detail


class DependentsActive(AppStoreError):
    """Reverse-dep guard (plan 10 D4): a dependent is ACTIVE — block removal."""

    def __init__(self, message: str, dependents: list):
        super().__init__(message)
        self.dependents = dependents


def module_hooks(name: str):
    """The module's bootstrap contract (plan 08 §4) — absent hooks are no-ops."""
    try:
        return importlib.import_module(f"modules.{name}.bootstrap")
    except ModuleNotFoundError:
        return None


class AppStoreService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ModuleRepository(db)

    # ---- reads ----

    def list_for_tenant(self, tenant_id: str) -> List[Tuple[Module, Optional[TenantModule]]]:
        return self.repo.list_with_state(tenant_id)

    def installed(self, tenant_id: str) -> List[TenantModule]:
        return self.repo.states_for_tenant(tenant_id)

    # ---- lifecycle ----

    def _manifest(self, name: str) -> dict:
        from app.module_loader import discover_manifests

        for m in discover_manifests():
            if m["module_name"] == name:
                return m
        return {"module_name": name}

    def install(
        self, tenant_id: str, name: str, *, cascade: bool = False
    ) -> Tuple[Module, TenantModule]:
        from app.module_platform.dependencies import check_requires

        module = self._listed_module(name)
        self._guard_platform(tenant_id)
        if self.repo.get_state(tenant_id, module.id) is not None:
            raise AlreadyInstalled(f"{module.title} is already installed.")

        # Hard-requires guard (D4): block on missing/inactive deps; cascade only
        # with explicit consent (install the chain in dep-first order).
        req = check_requires(self.db, tenant_id, self._manifest(name))
        if not req["ok"]:
            if req["inactive"]:
                raise RequiresUnmet(
                    f"Activate {', '.join(req['inactive'])} first.", req
                )
            if req["missing"] and not cascade:
                names = ", ".join(m["name"] for m in req["missing"])
                raise RequiresUnmet(f"Requires: {names}.", req)
            for dep in req["cascade"]:  # cascade=True: install deps first
                if self.repo.get_state(tenant_id, self._listed_module(dep).id) is None:
                    self.install(tenant_id, dep, cascade=True)

        state = TenantModule(
            tenant_id=tenant_id,
            module_id=module.id,
            status=MODULE_STATUS_ACTIVE,
            installed_version=module.version,
        )
        self.db.add(state)
        self.db.flush()

        hooks = module_hooks(name)
        if hooks and hasattr(hooks, "install_tenant"):
            hooks.install_tenant(self.db, tenant_id)

        self._grant_admin(tenant_id, name)
        self.db.commit()
        return module, state

    def deactivate(self, tenant_id: str, name: str) -> Tuple[Module, TenantModule]:
        module, state = self._installed_state(tenant_id, name)
        if state.status != MODULE_STATUS_ACTIVE:
            raise InvalidState("Only an active module can be deactivated.")
        self._guard_dependents(tenant_id, name, "deactivated")
        state.status = MODULE_STATUS_INACTIVE
        self.db.commit()
        return module, state

    def reactivate(self, tenant_id: str, name: str) -> Tuple[Module, TenantModule]:
        module, state = self._installed_state(tenant_id, name)
        if state.status != MODULE_STATUS_INACTIVE:
            raise InvalidState("Only an inactive module can be reactivated.")
        state.status = MODULE_STATUS_ACTIVE
        self.db.commit()
        return module, state

    def update(self, tenant_id: str, name: str) -> Tuple[Module, TenantModule]:
        module, state = self._installed_state(tenant_id, name)
        if parse_version(module.version) <= parse_version(state.installed_version):
            raise InvalidState(f"{module.title} is already up to date.")

        hooks = module_hooks(name)
        if hooks and hasattr(hooks, "update_tenant"):
            hooks.update_tenant(self.db, tenant_id, state.installed_version)

        # New versions may declare new permission rows — Admin picks them up.
        self._grant_admin(tenant_id, name)
        state.installed_version = module.version
        self.db.commit()
        return module, state

    def uninstall(self, tenant_id: str, name: str, confirm_name: str) -> None:
        module, state = self._installed_state(tenant_id, name)
        if confirm_name != module.name:
            raise ConfirmMismatch("Confirmation name does not match the module name.")
        self._guard_dependents(tenant_id, name, "uninstalled")

        hooks = module_hooks(name)
        if hooks and hasattr(hooks, "uninstall_tenant"):
            hooks.uninstall_tenant(self.db, tenant_id)

        # Revoke the module's permission grants from EVERY role of this tenant
        # (catalog rows stay — they're global, owned by the module's CSV).
        for role in self.db.query(Role).filter(Role.tenant_id == tenant_id).all():
            kept = [p for p in role.permissions if p.module != name]
            if len(kept) != len(role.permissions):
                role.permissions = kept

        self.db.delete(state)
        self.db.commit()

    def remove_all_tenant_modules(self, tenant_id: str) -> None:
        """Tenant-purge teardown (BL-035): run every module's
        ``uninstall_tenant`` hook (ACTIVE and INACTIVE alike — deactivated
        modules keep their rows and must be wiped too) and drop the state
        rows. NO commit — rides the caller's transaction; NO grant revoke —
        the purge deletes the tenant's roles outright."""
        for name in self.repo.installed_module_names(tenant_id):
            hooks = module_hooks(name)
            if hooks and hasattr(hooks, "uninstall_tenant"):
                hooks.uninstall_tenant(self.db, tenant_id)
        self.db.query(TenantModule).filter(
            TenantModule.tenant_id == tenant_id
        ).delete(synchronize_session=False)

    # ---- internals ----

    def _listed_module(self, name: str) -> Module:
        module = self.repo.get_by_name(name)
        if module is None or not module.is_listed:
            raise ModuleNotFound("Module not found.")
        return module

    def _installed_state(self, tenant_id: str, name: str) -> Tuple[Module, TenantModule]:
        module = self._listed_module(name)
        state = self.repo.get_state(tenant_id, module.id)
        if state is None:
            raise NotInstalled(f"{module.title} is not installed.")
        return module, state

    def _guard_dependents(self, tenant_id: str, name: str, verb: str) -> None:
        """Reverse-dep guard (D4): a required provider can't be removed/
        deactivated while an ACTIVE dependent needs it."""
        from app.module_platform.dependencies import check_dependents

        dependents = check_dependents(self.db, tenant_id, name)
        if dependents:
            raise DependentsActive(
                f"{', '.join(dependents)} require this module and must be "
                f"removed before it can be {verb}.",
                dependents,
            )

    def _guard_platform(self, tenant_id: str) -> None:
        """The platform tenant hosts the operator team only (plan 07 §5)."""
        tenant = self.db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if tenant is not None and tenant.is_platform:
            raise PlatformTenantProtected("The platform tenant cannot install modules.")

    def _grant_admin(self, tenant_id: str, module_name: str) -> None:
        """Grant the module's catalog rows to the tenant's Admin role (idempotent)."""
        admin = (
            self.db.query(Role)
            .filter(Role.tenant_id == tenant_id, Role.name == "Admin")
            .first()
        )
        if admin is None:
            return
        held = {p.id for p in admin.permissions}
        for perm in self.db.query(Permission).filter(Permission.module == module_name).all():
            if perm.id not in held:
                admin.permissions.append(perm)
        self.db.flush()
