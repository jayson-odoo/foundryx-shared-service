"""Product-kind registry - extensible, metadata-only (sprint-4/08 grill Q1/Q2).

A product ``kind`` is a label/filter facet, NEVER a behavior branch in core
(cluster-b only used it as a validation tuple + an export lambda). Core seeds
generic ``good``/``service``; modules register domain kinds at install (EMS adds
``admission``/``add_on``/``merchandise``). On module uninstall its kinds are
hidden (``active_kinds`` applies ``is_visible``), so pickers fall back to core
kinds; existing rows keep their raw value, rendered via ``kind_label`` humanized
fallback. Mirrors the status/terminology registry shape.
"""
from dataclasses import dataclass

from app.module_platform.active import active_modules, is_visible


@dataclass(frozen=True)
class ProductKind:
    key: str            # stored on Product.kind (snake/lowercase, immutable contract)
    label: str          # display
    module: str         # 'core' (always visible) or the owning module
    sort: int = 100


_REGISTRY: dict[str, ProductKind] = {}


def register_product_kind(kind: ProductKind) -> None:
    """Idempotent - last registration for a key wins (boot re-runs are safe)."""
    _REGISTRY[kind.key] = kind


def _ensure_core() -> None:
    if "good" in _REGISTRY:
        return
    register_product_kind(ProductKind("good", "Good", "core", 1))
    register_product_kind(ProductKind("service", "Service", "core", 2))


def all_kinds() -> list[ProductKind]:
    _ensure_core()
    return sorted(_REGISTRY.values(), key=lambda k: (k.sort, k.label))


def active_kinds(db, tenant_id: str) -> list[ProductKind]:
    """Core kinds + kinds from modules ACTIVE for the tenant (foolproof picker)."""
    _ensure_core()
    active = active_modules(db, tenant_id)
    return [k for k in all_kinds() if is_visible(k.module, active)]


def is_valid_kind(db, tenant_id: str, key: str) -> bool:
    return any(k.key == key for k in active_kinds(db, tenant_id))


def kind_label(key: str | None) -> str:
    """Humanized fallback for an orphaned/hidden kind (module uninstalled) -
    never blank (terminology-engine house style)."""
    if not key:
        return ""
    _ensure_core()
    k = _REGISTRY.get(key)
    if k is not None:
        return k.label
    return key.replace("_", " ").strip().title()
