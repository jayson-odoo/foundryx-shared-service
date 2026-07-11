"""Core StorageKeyLocation registrations (sprint-4/10 D9).

Every core ``conn:<id>:`` storage-key location — scalar ``*_key`` columns +
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
        # (mutable draft + immutable version snapshots) — both carry image-block
        # storageKeys, covered by the generic recursive rewriter.
        StorageKeyLoc(model=Workflow, json_column="draft_definition_json", tenant_column="tenant_id"),
        StorageKeyLoc(model=WorkflowVersion, json_column="definition_json", tenant_column="tenant_id"),
    ]
    for loc in json_locs:
        register_storage_key_location(loc)


ensure_core_locations = lazy_once(_register_core_locations)


def ensure_all_storage_locations() -> list:
    """Register EVERY storage-key location — core + all on-disk modules' — into
    ``_LOCATIONS``. Idempotent. Returns a list of ``(module, error)`` for any
    module whose registration failed (surfaced into the job log — never silent).

    **The fix for the worker no-op bug (sprint-4/12).** Location registration
    was previously a side effect of the FastAPI app boot only:
    ``ensure_core_locations()`` runs in ``main.py`` lifespan, and each module's
    ``register_engine_entities()`` runs via ``load_modules`` at app startup. A
    ``storage_migration`` job, however, executes in the **Celery worker**
    process, which runs neither — so ``_LOCATIONS`` was empty, ``enumerate_keys``
    returned 0 keys, and the migration finished "done" having copied/rewritten
    NOTHING. Calling this at the top of the job handler makes enumeration correct
    regardless of which process runs it.

    We call each module's ``register_engine_entities`` **directly** rather than
    ``register_module_boot`` — the latter runs ``register_capabilities`` FIRST,
    and a capability-registration failure there would skip engine-entity (hence
    storage-location) registration entirely (the prod "Registered 13 not 15" bug:
    omnichannel's ``conversation_messages.media_key`` was silently unregistered,
    so its media never enumerated). Storage migration needs zero capabilities.
    """
    ensure_core_locations()
    # Deferred import — avoids a module_loader ↔ storage_migration import cycle.
    from app.module_loader import discover_manifests
    from app.services.app_store_service import module_hooks

    failures: list = []
    for manifest in discover_manifests():
        name = manifest["module_name"]
        try:
            hooks = module_hooks(name)
            register = getattr(hooks, "register_engine_entities", None) if hooks else None
            if register is not None:
                register()  # registers the module's StorageKeyLocations
        except Exception as exc:  # noqa: BLE001 — a broken module must not abort a migration
            logger.exception(
                "module '%s' storage-location registration failed during migration", name
            )
            failures.append((name, f"{type(exc).__name__}: {exc}"))
    return failures
