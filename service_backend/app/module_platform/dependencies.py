"""Module dependency resolution (sprint-3/10 D4).

``requires`` (hard): install blocked unless the dep is installed + ACTIVE +
version-satisfies; missing → block + offer a cascade plan (topological order).
Reverse-dependency guard on BOTH uninstall AND deactivate (a required provider
can't go away / go inactive while a dependent is ACTIVE). Cycle detection at
boot → loud failure.

``optional``/``enhances`` (soft): ZERO guards - the consumer discovers the
capability at runtime; an absent provider self-disables (foolproof warn).
"""
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session


class DependencyError(Exception):
    pass


def version_satisfies(installed: Optional[str], spec: Optional[str]) -> bool:
    """``spec`` = ``">=X.Y.Z"`` (or empty/None = any). False if not installed."""
    if not spec:
        return installed is not None
    from app.models.module import parse_version

    if installed is None:
        return False
    spec = spec.strip()
    minimum = spec[2:].strip() if spec.startswith(">=") else spec
    return parse_version(installed) >= parse_version(minimum)


def _requires(manifest: dict) -> List[dict]:
    return manifest.get("requires", []) or []


def _optional(manifest: dict) -> List[dict]:
    return manifest.get("optional", []) or []


def resolve_install_order(manifests: List[dict]) -> List[str]:
    """Topological order over hard ``requires`` edges; raises on a cycle.
    ``optional`` edges do NOT constrain order (they're runtime-discovered)."""
    names = {m["module_name"] for m in manifests}
    by_name = {m["module_name"]: m for m in manifests}
    # edges: dep → dependent (dep must come first)
    visited: Dict[str, int] = {}  # 0=visiting, 1=done
    order: List[str] = []

    def visit(name: str, stack: Tuple[str, ...]) -> None:
        state = visited.get(name)
        if state == 1:
            return
        if state == 0:
            cycle = " → ".join([*stack, name])
            raise DependencyError(f"Dependency cycle detected: {cycle}")
        visited[name] = 0
        for req in _requires(by_name.get(name, {})):
            dep = req["name"]
            if dep in by_name:  # core/unknown deps are not topo nodes
                visit(dep, (*stack, name))
        visited[name] = 1
        order.append(name)

    for name in sorted(names):
        visit(name, ())
    return order


def check_requires(db: Session, tenant_id: str, manifest: dict) -> dict:
    """Evaluate a module's hard deps for install. Returns
    ``{"ok": bool, "missing": [...], "inactive": [...], "cascade": [names]}``.

    - ``missing``: not installed (offer cascade-with-consent, topo order).
    - ``inactive``: installed but INACTIVE (block "activate X first" - no silent
      reactivation).
    - version mismatch counts as ``missing`` (needs install/update).
    """
    from app.models.module import (
        MODULE_STATUS_ACTIVE,
        Module,
        TenantModule,
    )

    reqs = _requires(manifest)
    missing: List[dict] = []
    inactive: List[str] = []
    for req in reqs:
        dep = req["name"]
        spec = req.get("version")
        row = (
            db.query(Module, TenantModule)
            .outerjoin(
                TenantModule,
                (TenantModule.module_id == Module.id)
                & (TenantModule.tenant_id == tenant_id),
            )
            .filter(Module.name == dep)
            .first()
        )
        module = row[0] if row else None
        state = row[1] if row else None
        if module is None:
            missing.append({"name": dep, "reason": "not available"})
            continue
        if state is None or not version_satisfies(state.installed_version, spec):
            missing.append({"name": dep, "version": spec})
            continue
        if state.status != MODULE_STATUS_ACTIVE:
            inactive.append(dep)
    ok = not missing and not inactive
    return {
        "ok": ok,
        "missing": missing,
        "inactive": inactive,
        # cascade = the missing deps to install first, dep order
        "cascade": [m["name"] for m in missing],
    }


def check_dependents(db: Session, tenant_id: str, module_name: str) -> List[str]:
    """Reverse-dependency guard (uninstall AND deactivate): names of modules
    ACTIVE for this tenant that hard-``require`` ``module_name``. Non-empty =
    block the removal/deactivation."""
    from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule
    from app.module_loader import discover_manifests

    active_dependents: List[str] = []
    active_names = {
        name
        for (name,) in db.query(Module.name)
        .join(TenantModule, TenantModule.module_id == Module.id)
        .filter(
            TenantModule.tenant_id == tenant_id,
            TenantModule.status == MODULE_STATUS_ACTIVE,
        )
        .all()
    }
    for manifest in discover_manifests():
        name = manifest["module_name"]
        if name not in active_names:
            continue
        if any(req["name"] == module_name for req in _requires(manifest)):
            active_dependents.append(name)
    return active_dependents
