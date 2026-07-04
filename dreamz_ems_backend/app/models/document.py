"""Document management (the Drive) models — core ``public`` tables (plan
sprint-3/04).

A shared per-tenant Drive: nested ``Folder`` tree, ``File`` rows whose identity
+ name are STABLE across replacements, and append-only ``FileVersion`` history
(Replace/edit never destroys bytes, D5). ``AttachmentType`` is optional
categorisation (D7); ``DocumentSettings`` is the one-row-per-tenant policy
(quota + default cap + the slice-05 public-share ceiling, D12). ``DownloadJob``
backs the async bulk/folder ZIP (D8).

Tenant-born, tenant-scoped on every row (never two-tier). Name-collision and
folder-cycle are enforced in the service/repository (app-level) — a functional
``lower(name)`` unique index is Postgres-only and NULL-distinct on the nullable
``folder_id``, so the DB backstop is a follow-up, not the guard.
"""
import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base
from app.models.utc_datetime import UTCDateTime

# DownloadJob.status
DOWNLOAD_PENDING = "pending"
DOWNLOAD_PROCESSING = "processing"
DOWNLOAD_READY = "ready"
DOWNLOAD_FAILED = "failed"

# DocumentSettings.public_sharing (slice-05 ceiling; off by default).
SHARING_OFF = "off"
SHARING_VIEW = "view"
SHARING_EDIT = "edit"
SHARING_VALUES = (SHARING_OFF, SHARING_VIEW, SHARING_EDIT)

# Workflow triggerable entity_type (D13).
FILE_ENTITY = "file"

# ---- sharing (slice-05, Google-Drive model) ----
SHARE_TARGET_FILE = "file"
SHARE_TARGET_FOLDER = "folder"
SHARE_TARGET_KINDS = (SHARE_TARGET_FILE, SHARE_TARGET_FOLDER)

# General access = the "who, beyond named people" tier on the ONE stable link.
# Restricted = only named people; Workspace = any authenticated tenant member;
# Public = anyone with the link (anonymous). Named people in file_share_users are
# ALWAYS additive (they keep access even when general_access is restricted).
SHARE_ACCESS_RESTRICTED = "restricted"
SHARE_ACCESS_WORKSPACE = "workspace"
SHARE_ACCESS_PUBLIC = "public"
SHARE_ACCESS_LEVELS = (
    SHARE_ACCESS_RESTRICTED,
    SHARE_ACCESS_WORKSPACE,
    SHARE_ACCESS_PUBLIC,
)

SHARE_CAP_VIEW = "view"
SHARE_CAP_EDIT = "edit"
SHARE_CAPABILITIES = (SHARE_CAP_VIEW, SHARE_CAP_EDIT)

# Public-edit per-link guardrail defaults (D6) — caps abuse independent of quota.
SHARE_DEFAULT_MAX_UPLOADS = 50
SHARE_DEFAULT_MAX_TOTAL_MB = 200


def _uuid() -> str:
    return str(uuid.uuid4())


class Folder(Base):
    __tablename__ = "folders"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    parent_id = Column(String, ForeignKey("folders.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    is_deleted = Column(Boolean, nullable=False, default=False, index=True)
    deleted_at = Column(UTCDateTime(), nullable=True)
    deleted_by = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AttachmentType(Base):
    __tablename__ = "attachment_types"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    # Lowercase dot-less extensions (["pdf","docx"]); [] = any within the floor.
    allowed_exts_json = Column(JSON, nullable=False, default=list)
    # Per-type cap; NULL = fall back to the tenant default.
    max_mb = Column(Integer, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class File(Base):
    __tablename__ = "files"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    folder_id = Column(String, ForeignKey("folders.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    # The latest version (what previews/downloads serve). NULL only transiently
    # before the first version row is attached.
    current_version_id = Column(String, nullable=True)
    attachment_type_id = Column(
        String, ForeignKey("attachment_types.id"), nullable=True
    )
    is_deleted = Column(Boolean, nullable=False, default=False, index=True)
    deleted_at = Column(UTCDateTime(), nullable=True)
    deleted_by = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FileVersion(Base):
    __tablename__ = "file_versions"

    id = Column(String, primary_key=True, default=_uuid)
    file_id = Column(String, ForeignKey("files.id"), nullable=False, index=True)
    ordinal = Column(Integer, nullable=False)  # 1-based
    storage_key = Column(String, nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    # The magic-byte-SNIFFED mime (never the declared content-type).
    mime = Column(String, nullable=False)
    uploaded_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)


class DocumentSettings(Base):
    __tablename__ = "document_settings"

    tenant_id = Column(String, primary_key=True)
    public_sharing = Column(String, nullable=False, default=SHARING_OFF)
    default_max_file_mb = Column(Integer, nullable=False, default=50)
    storage_quota_mb = Column(Integer, nullable=True)  # NULL = unlimited
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FileShare(Base):
    """The ONE stable share link for a file or folder (Google-Drive model). A
    target has at most one share row — the ``token`` never changes; the owner
    edits ``general_access`` / ``general_capability`` / the people list in place,
    so flipping "Anyone with the link" → "Restricted" simply makes the same URL
    stop working for the public without re-minting. ``is_disabled`` is a hard
    kill-switch (oversight). Public access is clamped by
    ``document_settings.public_sharing`` server-side at every serve (D5)."""

    __tablename__ = "file_shares"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "target_kind", "target_id", name="uq_file_shares_target"
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    target_kind = Column(String, nullable=False)  # file | folder
    target_id = Column(String, nullable=False, index=True)
    token = Column(String, nullable=False, unique=True, index=True)
    # restricted | workspace | public — the tier BEYOND the named people list.
    general_access = Column(
        String, nullable=False, default=SHARE_ACCESS_RESTRICTED
    )
    # Role for the general-access tier (named people carry their own role).
    general_capability = Column(String, nullable=False, default=SHARE_CAP_VIEW)
    expires_at = Column(UTCDateTime(), nullable=True)
    password_hash = Column(String, nullable=True)
    # Public+edit per-link guardrails (NULL = fall back to the sane defaults).
    max_uploads = Column(Integer, nullable=True)
    max_total_mb = Column(Integer, nullable=True)
    uploads_count = Column(Integer, nullable=False, default=0)
    uploads_bytes = Column(BigInteger, nullable=False, default=0)
    is_disabled = Column(Boolean, nullable=False, default=False, index=True)
    created_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FileShareUser(Base):
    """A named person on a share (Google "People with access") — ALWAYS additive,
    each with their own ``capability``. ``user_id`` is validated to the share's
    tenant at save (422 otherwise) and tenant-scoped at resolve (the sprint-2/01
    cross-tenant-leak rule — never resolve a stored id unscoped)."""

    __tablename__ = "file_share_users"
    __table_args__ = (
        UniqueConstraint("share_id", "user_id", name="uq_file_share_users"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    share_id = Column(String, ForeignKey("file_shares.id"), nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    capability = Column(String, nullable=False, default=SHARE_CAP_VIEW)  # view | edit


class FileLink(Base):
    """The deferred polymorphic seam from slice 04 (D8). A Drive-side row that
    points OUT to a domain entity by STRING (no FK to domain modules, no import).
    Same polymorphic save-validate + tenant-scoped-resolve discipline as
    ``FileShareUser``. Untested against a real consumer until BL-101 (Cluster B)."""

    __tablename__ = "file_links"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)
    file_id = Column(String, ForeignKey("files.id"), nullable=False, index=True)
    created_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)


class DownloadJob(Base):
    __tablename__ = "document_download_jobs"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False, default="zip")
    status = Column(String, nullable=False, default=DOWNLOAD_PENDING)
    filename = Column(String, nullable=False)
    zip_storage_key = Column(String, nullable=True)
    file_count = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    ready_at = Column(UTCDateTime(), nullable=True)
