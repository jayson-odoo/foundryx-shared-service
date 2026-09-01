"""Core StorageKeyLocation registrations (sprint-4/10 D9).

Every core ``conn:<id>:`` storage-key location - scalar ``*_key`` columns +
JSON-embedded keys (form answers, template block-docs, workflow definitions).
Modules register their own at install (omnichannel ``conversation_messages.
media_key`` in its boot hook). Guarded by ``lazy_once`` (the house one-shot
registration pattern).
"""
import logging

from app.lazy_registry import lazy_once
from app.storage_migration.registry import (
    StorageKeyLoc,
    register_storage_key_location,
)

logger = logging.getLogger("foundryx.storage_migration")


def _register_core_locations() -> None:
    from app.models.document import DownloadJob, FileVersion
    from app.models.form import FormSubmission
    from app.models.import_job import ImportJob
    from app.models.notification_spec import NotificationSpec
    from app.models.template import Template
    from app.models.tenant_branding import TenantBranding
    from app.models.user import User
    from app.models.workflow import Workflow, WorkflowVersion

    # ── scalar *_key columns ─────────────────────────────────────────────────
    scalar = [
        StorageKeyLoc(model=User, column="avatar_key", tenant_column="tenant_id"),
        StorageKeyLoc(model=TenantBranding, column="logo_key", tenant_column="tenant_id"),
        StorageKeyLoc(model=TenantBranding, column="favicon_key", tenant_column="tenant_id"),
        StorageKeyLoc(model=TenantBranding, column="illustration_key", tenant_column="tenant_id"),
        StorageKeyLoc(model=ImportJob, column="file_storage_key", tenant_column="tenant_id"),
        StorageKeyLoc(model=ImportJob, column="error_report_key", tenant_column="tenant_id"),
        # file_versions has no direct tenant_id (via file_id → files.tenant_id);
        # enumerate/rewrite are connection-scoped, so tenant_column is optional.
        StorageKeyLoc(model=FileVersion, column="storage_key", tenant_column=None),
        StorageKeyLoc(model=DownloadJob, column="zip_storage_key", tenant_column="tenant_id"),
    ]
    for loc in scalar:
        register_storage_key_location(loc)

    # ── JSON-embedded keys (generic recursive walk/rewrite) ──────────────────
    json_locs = [
        StorageKeyLoc(model=FormSubmission, json_column="answers_json", tenant_column="tenant_id"),
        StorageKeyLoc(model=Template, json_column="doc_json", tenant_column="tenant_id"),
        StorageKeyLoc(model=NotificationSpec, json_column="doc_json", tenant_column="tenant_id"),
        # Workflow email.send config.doc lives inside the definition graphs
        # (mutable draft + immutable version snapshots) - both carry image-block
        # storageKeys, covered by the generic recursive rewriter.
        StorageKeyLoc(model=Workflow, json_column="draft_definition_json", tenant_column="tenant_id"),
        StorageKeyLoc(model=WorkflowVersion, json_column="definition_json", tenant_column="tenant_id"),
    ]
    for loc in json_locs:
        register_storage_key_location(loc)


ensure_core_locations = lazy_once(_register_core_locations)


def register_module_declared_locations(manifest: dict) -> int:
    """Register a module's manifest-declared storage-key locations, importing
    ONLY its ``models`` package (deliberately lighter + more import-safe than the
    full ``bootstrap`` chain). Returns how many specs were registered.

    Declaration lives in ``manifest.json`` under ``"storage_locations"``::

        {"model": "ConversationMessage", "column": "media_key",
         "tenantColumn": "tenant_id"}          # scalar
        {"model": "Foo", "jsonColumn": "doc_json", "tenantColumn": "tenant_id"}

    A module that declares locations is thereby PROTECTED by the completeness
    gate below - a migration refuses to cut over if these did not register.
    """
    import importlib

    specs = manifest.get("storage_locations") or []
    if not specs:
        return 0
    models_mod = importlib.import_module(f"modules.{manifest['_dir']}.models")
    for spec in specs:
        model = getattr(models_mod, spec["model"])
        register_storage_key_location(
            StorageKeyLoc(
                model=model,
                column=spec.get("column"),
                json_column=spec.get("jsonColumn"),
                tenant_column=spec.get("tenantColumn"),
                module=manifest["module_name"],
            )
        )
    return len(specs)


def ensure_all_storage_locations() -> list:
    """Register EVERY storage-key location - core + all on-disk modules' - into
    ``_LOCATIONS``. Idempotent. Returns a list of ``(module, error)`` for any
    module whose registration RAISED (surfaced into the job log - never silent).

    **Why this exists (the worker no-op bug, sprint-4/12).** Location
    registration was originally a side effect of FastAPI app boot only
    (``ensure_core_locations`` in ``main.py`` lifespan + each module's
    ``register_engine_entities`` via ``load_modules``). A ``storage_migration``
    job runs in the **Celery worker**, which boots neither - so ``_LOCATIONS``
    was empty and the migration copied/rewrote NOTHING.

    **Why it's now declarative (sprint-4/12 round 3).** The earlier fix called
    each module's ``register_engine_entities`` via ``module_hooks``, but
    ``module_hooks`` SWALLOWS ``ModuleNotFoundError`` - so when importing the
    module's heavy ``bootstrap`` chain failed in the worker process, it returned
    ``None`` and the module's locations were silently skipped (the prod
    "Registered 13 not 15" bug: omnichannel media never enumerated, then A was
    retired and the media stranded). We now:

    1. Register from the module's **manifest declaration**, importing only its
       ``models`` package - no capabilities, no bootstrap side effects.
    2. NEVER swallow an import error: a raise is recorded as a ``(module, err)``
       failure with its type + message, logged with a traceback.

    The real safety, though, is the **completeness gate** (``missing_declared_
    location_modules``): the migration HOLDS instead of cutting over whenever a
    declaring module's locations are not all registered - so an undercount can
    never silently strand + retire.
    """
    ensure_core_locations()
    # Deferred import - avoids a module_loader ↔ storage_migration import cycle.
    from app.module_loader import discover_manifests

    failures: list = []
    for manifest in discover_manifests():
        name = manifest["module_name"]
        try:
            register_module_declared_locations(manifest)
        except Exception as exc:  # noqa: BLE001 - a broken module must not abort a migration
            logger.exception(
                "module '%s' storage-location registration failed during migration", name
            )
            failures.append((name, f"{type(exc).__name__}: {exc}"))
    return failures


def missing_declared_location_modules() -> list:
    """Modules that DECLARE storage locations in their manifest but have fewer
    registered than declared - the completeness gate. A migration must HOLD (not
    cut over) while this is non-empty: an undercount means some of that module's
    blobs would be missed, then stranded when the source connection is retired.

    Counts by the ``module`` tag on registered locations (no model import needed
    - so it still catches the case where the models import itself failed).
    """
    from app.module_loader import discover_manifests
    from app.storage_migration.registry import list_locations

    registered_by_module: dict = {}
    for loc in list_locations():
        registered_by_module[loc.module] = registered_by_module.get(loc.module, 0) + 1

    missing: list = []
    for manifest in discover_manifests():
        want = len(manifest.get("storage_locations") or [])
        if want and registered_by_module.get(manifest["module_name"], 0) < want:
            missing.append(manifest["module_name"])
    return missing
