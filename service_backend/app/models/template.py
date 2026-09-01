"""Template engine - templates table (plan sprint-2/07 D6).

Two-tier rows (status-engine D7 pattern): platform defaults carry
``tenant_id NULL``; a tenant's first edit of a system template FORKS a
tenant-owned copy resolved ahead of the platform row. ``doc_json`` holds the
editor-agnostic block document (schemaVersion inside - the forever-contract;
never store compiled HTML as source of truth).
"""

import uuid

from sqlalchemy import Boolean, Column, Index, JSON, String, func, text

from app.database import Base
from app.models.utc_datetime import UTCDateTime

TEMPLATE_TYPE_EMAIL = "email"
# F2 (plan sprint-3/03): document-surface templates render to PDF, not MJML.
TEMPLATE_TYPE_DOCUMENT = "document"
# F2 slice 2: fixed-canvas (badge/ticket/cert) - polymorphic canvas-doc, PDF.
TEMPLATE_TYPE_BADGE = "badge"


class Template(Base):
    __tablename__ = "templates"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # NULL = platform-tier default (visible to every tenant until forked).
    tenant_id = Column(String, nullable=True, index=True)
    type = Column(String, nullable=False, default=TEMPLATE_TYPE_EMAIL)
    # Addressable key - system templates resolve by key (e.g. auth.password_reset).
    key = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    # TemplateContext registry key - defines the merge-fact vocabulary (D11).
    context = Column(String, nullable=False)
    # Merge-enabled subject line.
    subject = Column(String, nullable=False, default="")
    # Block document (types/templates.ts mirror). none_as_null per house JSON rule.
    doc_json = Column(JSON(none_as_null=True), nullable=False)
    # System = seeded platform template: key/context/delete locked, fork-on-edit.
    is_system = Column(Boolean, nullable=False, default=False)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        # Tenant-tier uniqueness: one row per (tenant, key).
        Index(
            "uq_templates_tenant_key",
            "tenant_id",
            "key",
            unique=True,
            postgresql_where=text("tenant_id IS NOT NULL"),
            sqlite_where=text("tenant_id IS NOT NULL"),
        ),
        # Platform-tier uniqueness MUST be a partial index - NULLs are
        # distinct under a plain UNIQUE (BL-065 lesson: a duplicate
        # platform row slipped past the constraint and shadowed an edge).
        Index(
            "uq_templates_platform_key",
            "key",
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
            sqlite_where=text("tenant_id IS NULL"),
        ),
    )
