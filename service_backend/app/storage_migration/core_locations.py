"""Core StorageKeyLocation registrations (sprint-4/10 D9).

Every core ``conn:<id>:`` storage-key location — scalar ``*_key`` columns +
JSON-embedded keys (form answers, template block-docs, workflow definitions).
Modules register their own at install (omnichannel ``conversation_messages.
media_key`` in its boot hook). Guarded by ``lazy_once`` (the house one-shot
registration pattern).
"""
from app.lazy_registry import lazy_once
from app.storage_migration.registry import (
    StorageKeyLoc,
    register_storage_key_location,
)


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
