"""Module catalog + per-tenant install-state queries (plan 08). Pure SQLAlchemy."""
from typing import List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule


class ModuleRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- catalog ----

    def get_by_name(self, name: str) -> Optional[Module]:
        return self.db.query(Module).filter(Module.name == name).first()

    def list_listed(self) -> List[Module]:
        return (
            self.db.query(Module)
            .filter(Module.is_listed.is_(True))
            .order_by(Module.title)
            .all()
        )

    # ---- per-tenant state ----

    def get_state(self, tenant_id: str, module_id: str) -> Optional[TenantModule]:
        return (
            self.db.query(TenantModule)
            .filter(TenantModule.tenant_id == tenant_id, TenantModule.module_id == module_id)
            .first()
        )

    def states_for_tenant(self, tenant_id: str) -> List[TenantModule]:
        return self.db.query(TenantModule).filter(TenantModule.tenant_id == tenant_id).all()

    def list_with_state(self, tenant_id: str) -> List[Tuple[Module, Optional[TenantModule]]]:
        states = {tm.module_id: tm for tm in self.states_for_tenant(tenant_id)}
        return [(m, states.get(m.id)) for m in self.list_listed()]

    def active_module_names(self, tenant_id: str) -> Set[str]:
        rows = (
            self.db.query(Module.name)
            .join(TenantModule, TenantModule.module_id == Module.id)
            .filter(
                TenantModule.tenant_id == tenant_id,
                TenantModule.status == MODULE_STATUS_ACTIVE,
            )
            .all()
        )
        return {name for (name,) in rows}

    def installed_module_names(self, tenant_id: str) -> Set[str]:
        """ACTIVE + INACTIVE — installed at all (grants stay while deactivated)."""
        rows = (
            self.db.query(Module.name)
            .join(TenantModule, TenantModule.module_id == Module.id)
            .filter(TenantModule.tenant_id == tenant_id)
            .all()
        )
        return {name for (name,) in rows}

    def is_active(self, tenant_id: str, name: str) -> bool:
        return (
            self.db.query(TenantModule.id)
            .join(Module, TenantModule.module_id == Module.id)
            .filter(
                TenantModule.tenant_id == tenant_id,
                Module.name == name,
                TenantModule.status == MODULE_STATUS_ACTIVE,
            )
            .first()
            is not None
        )

    def installed_version(self, tenant_id: str, name: str) -> Optional[str]:
        row = (
            self.db.query(TenantModule.installed_version)
            .join(Module, TenantModule.module_id == Module.id)
            .filter(TenantModule.tenant_id == tenant_id, Module.name == name)
            .first()
        )
        return row[0] if row else None
