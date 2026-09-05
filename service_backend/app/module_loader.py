"""Module loader - the sanctioned hook for App-Store modules (plan 08 §4).

Manifest-driven: scans ``modules/*/manifest.json`` and wires each module in.
Modules never inject into core; core pulls them in here.

- ``load_modules(app)``: dynamic-import each manifest's routers and include
  them WITH the ``require_module(<name>)`` gate injected - module code stays
  untouched; deactivated/uninstalled tenants get 403 on every module route.
- ``bootstrap_modules()``: sync the global ``modules`` catalog from manifests,
  run every module's global ``install()`` (idempotent schema + tables + perms
  CSV - DDL stays ``create_all``, BL-029), then the transitional backfill:
  tenants that already hold module data from the pre-App-Store era get an
  ACTIVE ``tenant_modules`` row at the current version (platform excluded).

Module bootstrap contract (certification requirement, governance §plan 08):
    install(engine, db)                        # global, idempotent
    install_tenant(db, tenant_id)              # per-tenant seed
    update_tenant(db, tenant_id, from_version) # per-tenant data migration
    uninstall_tenant(db, tenant_id)            # wipe the tenant's module rows
    tenant_has_data(db, tenant_id) -> bool     # optional: backfill detection
"""
import importlib
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"

logger = logging.getLogger(__name__)

# Errored modules (plan sprint-3/10 D8) - a module that fails at boot (router
# import / registration) or migration is recorded here, skipped, and behaves
# like inactive. Surfaced via the catalog API; the app + siblings + core survive.
ERRORED_MODULES: Dict[str, str] = {}  # module_name → captured error message


def discover_manifests(modules_dir: Optional[Path] = None) -> List[dict]:
    """All on-disk module manifests, sorted by module_name (deterministic wiring)."""
    root = modules_dir or MODULES_DIR
    manifests = []
    if not root.is_dir():
        return manifests
    for manifest_path in sorted(root.glob("*/manifest.json")):
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        manifest["_dir"] = manifest_path.parent.name
        manifests.append(manifest)
    manifests.sort(key=lambda m: m["module_name"])
    return manifests


def load_modules(app: FastAPI) -> None:
    """Include every discovered module's routers, gated by require_module.

    A router spec may set ``"public": true`` to skip the gate - for endpoints
    that have no authenticated user to resolve a tenant from: provider
    webhooks (Meta-signature-verified), media serving, and WebSockets (which
    authenticate in-endpoint via a token query param, incl. the module-active
    check). Plan 05 §7.
    """
    from app.dependencies import require_module

    for manifest in discover_manifests():
        name = manifest["module_name"]
        # Per-module failure isolation (D8): a broken module is marked errored,
        # skipped, and logged - the app + all siblings + core continue.
        try:
            gate = Depends(require_module(name))
            for router_spec in manifest.get("routers", []):
                router_module = importlib.import_module(
                    f"modules.{manifest['_dir']}.routers.{router_spec['name']}"
                )
                app.include_router(
                    router_module.router,
                    prefix=router_spec["prefix"],
                    tags=[f"{name}:{router_spec['name']}"],
                    dependencies=[] if router_spec.get("public") else [gate],
                )
            register_module_boot(name)
        except Exception as exc:  # noqa: BLE001 - D8 isolation
            ERRORED_MODULES[name] = f"{type(exc).__name__}: {exc}"
            logger.error("Module '%s' failed to load: %s", name, exc, exc_info=True)


def register_module_boot(name: str) -> None:
    """Call a module's boot-time registration hooks if present: capabilities
    (D5) + engine entities (status/fact/terminology/importer, plan 11 D9). Both
    are idempotent - safe to call at every boot/bootstrap."""
    from app.services.app_store_service import module_hooks

    hooks = module_hooks(name)
    if hooks is None:
        return
    if hasattr(hooks, "register_capabilities"):
        hooks.register_capabilities()
    if hasattr(hooks, "register_engine_entities"):
        hooks.register_engine_entities()


def boot_module_hooks() -> None:
    """Run every discovered module's boot hooks (capabilities + engine
    entities) WITHOUT a FastAPI app - for worker processes.

    ``load_modules`` does this as a side effect of router inclusion, so the API
    process always has module-registered workflow triggers/actions. A Celery
    worker never calls ``load_modules``; without this the workflow worker only
    knows core nodes and a run touching ``omnichannel.send_message`` fails
    ``Unknown action`` in prod (invisible in eager dev, which runs inline in the
    API process). Same D8 isolation as ``load_modules``: a broken module is
    marked errored + skipped, siblings continue. Idempotent.
    """
    for manifest in discover_manifests():
        name = manifest["module_name"]
        try:
            register_module_boot(name)
        except Exception as exc:  # noqa: BLE001 - D8 isolation
            ERRORED_MODULES[name] = f"{type(exc).__name__}: {exc}"
            logger.error("Module '%s' boot hooks failed: %s", name, exc, exc_info=True)


def sync_module_catalog(db: Session, modules_dir: Optional[Path] = None) -> None:
    """Upsert the global ``modules`` catalog from manifests; delist removed dirs."""
    from app.models.module import Module

    manifests = {m["module_name"]: m for m in discover_manifests(modules_dir)}
    existing = {m.name: m for m in db.query(Module).all()}

    for name, manifest in manifests.items():
        row = existing.get(name)
        if row is None:
            row = Module(name=name)
            db.add(row)
        row.version = manifest["version"]
        row.title = manifest.get("title") or name.title()
        row.description = manifest.get("description") or ""
        row.icon = manifest.get("icon")
        row.is_listed = True

    # Removed from disk → delist (keep the row: tenant_modules FK history).
    for name, row in existing.items():
        if name not in manifests:
            row.is_listed = False

    db.flush()


def _backfill_tenant_modules(db: Session) -> None:
    """Pre-App-Store tenants already had module data seeded - mark them
    installed ACTIVE at the current code version (plan 08 §4). Detection is the
    module's optional ``tenant_has_data`` hook; without it nothing backfills.

    B4 (plan-25 round-3 codex triage): a normal ``AppStoreService.install``
    also runs the module's ``install_tenant`` seed hook + grants the module's
    permission keys to the tenant's Admin role (`_grant_admin`) - this backfill
    path used to skip BOTH, silently stamping the tenant ACTIVE at the
    CURRENT code version with no later ``update_tenant`` ever firing (install
    == current version, so the App Store never offers an update either).
    Generic fix, not an omnichannel special case: mirror the same two steps
    here for every module, isolated per-tenant so one tenant's failure never
    blocks the others or the rest of bootstrap. Each tenant's row + hook +
    grant runs inside its own SAVEPOINT (``db.begin_nested()``) so a failure
    rolls back exactly that tenant's work and leaves the session usable for
    the next tenant / the rest of bootstrap, instead of leaving it in
    ``PendingRollbackError`` (or committing a half-applied seed alongside the
    ACTIVE ``TenantModule`` row on a non-DB error).

    Unlike ``AppStoreService.install`` this path skips ``check_requires`` and
    unconditionally re-grants the module's permission keys to the tenant's
    Admin role - both are only reachable here for tenants that have no
    ``TenantModule`` row yet (the pre-App-Store backfill case), never for an
    already-installed tenant.
    """
    from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule
    from app.models.tenant import Tenant
    from app.services.app_store_service import AppStoreService, module_hooks

    tenants = db.query(Tenant).filter(Tenant.is_platform.is_(False)).all()
    for module in db.query(Module).filter(Module.is_listed.is_(True)).all():
        hooks = module_hooks(module.name)
        has_data = getattr(hooks, "tenant_has_data", None) if hooks else None
        if has_data is None:
            continue
        installed = {
            tm.tenant_id
            for tm in db.query(TenantModule).filter(TenantModule.module_id == module.id).all()
        }
        for tenant in tenants:
            if tenant.id in installed or not has_data(db, tenant.id):
                continue
            try:
                with db.begin_nested():
                    db.add(
                        TenantModule(
                            tenant_id=tenant.id,
                            module_id=module.id,
                            status=MODULE_STATUS_ACTIVE,
                            installed_version=module.version,
                        )
                    )
                    db.flush()
                    if hooks and hasattr(hooks, "install_tenant"):
                        hooks.install_tenant(db, tenant.id)
                    AppStoreService(db)._grant_admin(tenant.id, module.name)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Module '%s' backfill install_tenant failed for tenant %s: %s",
                    module.name, tenant.id, exc, exc_info=True,
                )
    db.flush()


def bootstrap_modules(engine=None, db: Optional[Session] = None) -> None:
    """Catalog sync + every module's global install + backfill. Idempotent.

    Called by scripts/bootstrap_db.py with the app defaults; tests pass their
    own engine/session.
    """
    from app.database import SessionLocal
    from app.database import engine as default_engine
    from app.services.app_store_service import module_hooks

    from app.module_platform.dependencies import resolve_install_order

    own_session = db is None
    engine = engine or default_engine
    db = db or SessionLocal()
    try:
        sync_module_catalog(db)
        manifests = {m["module_name"]: m for m in discover_manifests()}
        # Hard-requires topological order (D4) - a provider installs before a
        # dependent. Cycle detection raises loudly here (boot-time).
        order = resolve_install_order(list(manifests.values()))
        for name in order:
            manifest = manifests.get(name)
            if manifest is None:
                continue
            # Per-module isolation (D8): a failing module is marked errored,
            # skipped (install + migration + capabilities), siblings continue.
            try:
                _bootstrap_one_module(engine, db, name)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                ERRORED_MODULES[name] = f"{type(exc).__name__}: {exc}"
                logger.error("Module '%s' bootstrap failed: %s", name, exc, exc_info=True)
        _backfill_tenant_modules(db)
        db.commit()
    finally:
        if own_session:
            db.close()


def _bootstrap_one_module(engine, db: Session, name: str) -> None:
    """One module's global install + per-module Alembic + capabilities (D3/D5)."""
    from app.module_platform.migrations import run_module_migrations
    from app.services.app_store_service import module_hooks

    hooks = module_hooks(name)
    if hooks and hasattr(hooks, "install"):
        hooks.install(engine, db)
    # Per-module Alembic (D3, BL-029): stamp-if-legacy-else-upgrade. No-op on
    # SQLite test engines (module schema-isolation needs Postgres) and on
    # modules without an alembic/ dir (legacy create_all path).
    run_module_migrations(engine, name)
    register_module_boot(name)
