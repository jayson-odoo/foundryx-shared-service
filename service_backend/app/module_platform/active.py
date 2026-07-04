"""The ONE active-modules filter (sprint-3/10 D2).

Every registry item carries a ``module`` tag (``'core'`` always visible; else
the module name). ``active_modules(db, tenant_id)`` returns the set of module
names ACTIVE for a tenant; ``is_visible(item_module, active)`` is the uniform
predicate applied at EVERY catalog consumption point (workflow trigger/action
pickers + event-bus matching, rule facts, status entities, import button,
terminology, website blocks, menu, GET /permissions).

New-catalog checklist rule: any future catalog MUST tag ``module`` + apply this.
"""
from typing import Set

from sqlalchemy.orm import Session

CORE_MODULE = "core"


def active_modules(db: Session, tenant_id: str) -> Set[str]:
    """Module names ACTIVE for this tenant (``'core'`` is implicit-always)."""
    from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule

    rows = (
        db.query(Module.name)
        .join(TenantModule, TenantModule.module_id == Module.id)
        .filter(
            TenantModule.tenant_id == tenant_id,
            TenantModule.status == MODULE_STATUS_ACTIVE,
        )
        .all()
    )
    return {CORE_MODULE} | {name for (name,) in rows}


def is_visible(item_module: str, active: Set[str]) -> bool:
    """Core is always visible; a module's item only while it's active."""
    return item_module == CORE_MODULE or item_module in active
