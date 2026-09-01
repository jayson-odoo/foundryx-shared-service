"""Module platform v2 (sprint-3/10, F9) - inter-module deps + capability
registry + soft references + the one ``active_modules`` filter.

Extends the App Store (sprint-1/08) from isolated leaf modules to a real
ecosystem: declared dependencies (hard ``requires`` / soft ``optional``), a
sanctioned cross-module call seam (capabilities, runtime-resolved + tenant-
active-gated), cross-module data refs without FKs (soft refs through a provider
``resolve`` capability), and one filter applied at every catalog consumption
point so a tenant only sees the modules active for it.

Hard governance line preserved: a module NEVER FKs across schemas into another
module's tables and NEVER imports another module's Python internals - coupling
goes through the capability registry (this package).
"""
from app.module_platform.active import active_modules, is_visible
from app.module_platform.capabilities import (
    CapabilityDef,
    DuplicateCapability,
    register_capability,
    reset_capabilities,
    resolve_capability,
)
from app.module_platform.dependencies import (
    DependencyError,
    check_dependents,
    check_requires,
    resolve_install_order,
)
from app.module_platform.reference_guards import (
    is_referenced,
    reference_counts,
    register_reference_guard,
)
from app.module_platform.soft_refs import SoftRef, resolve_soft_ref, validate_soft_ref

__all__ = [
    "is_referenced",
    "reference_counts",
    "register_reference_guard",
    "active_modules",
    "is_visible",
    "CapabilityDef",
    "DuplicateCapability",
    "register_capability",
    "reset_capabilities",
    "resolve_capability",
    "DependencyError",
    "check_dependents",
    "check_requires",
    "resolve_install_order",
    "SoftRef",
    "resolve_soft_ref",
    "validate_soft_ref",
]
