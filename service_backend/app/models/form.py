"""Form engine models (plan sprint-3/01) - core ``public`` tables.

A ``Form`` carries a mutable ``draft_definition_json`` (the builder's working
block doc, D6). Publishing runs the validate gate, snapshots the draft into an
immutable ``FormVersion`` and points ``current_version_id`` at it (D9) - fill
surfaces serve ONLY the published version; preview renders the draft.

``FormSubmission`` is the one generic capture store (D2): pinned
``version_id`` (faithful re-render forever), camelCase ``answers_json``,
``status_id`` into the form's OWN scoped status machine (D4), nullable
``user_id`` (NULL = anonymous, slice 2) and the optional inbound polymorphic
subject ("this form is *about* record X" - validated against the author's
tenant at save, tenant-scoped at resolve).
"""
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.utc_datetime import UTCDateTime

# Definition lifecycle (D5) - a plain enum, NOT the status engine (the
# configurable-graph value targets submissions, not definitions).
FORM_DRAFT = "draft"
FORM_PUBLISHED = "published"
FORM_ARCHIVED = "archived"
FORM_STATUSES = (FORM_DRAFT, FORM_PUBLISHED, FORM_ARCHIVED)

# Access model (D11) - `portal` reserved for Cluster D.
ACCESS_INTERNAL = "internal"
ACCESS_PUBLIC = "public"
FORM_ACCESS_VALUES = (ACCESS_INTERNAL, ACCESS_PUBLIC)

# The scoped status-engine entity (D4) - scope_id = the owning form's id.
FORM_SUBMISSION_ENTITY = "form_submission"

# Honeypot input name injected on the public fill page (plan sprint-3/02 D12) -
# a real respondent never fills it; a naive bot does → the submission is dropped.
FORM_HONEYPOT_FIELD = "_hp_company"

# Public serving states (D10/D11). `open` carries the definition; `closed`/`full`
# render a friendly message. Unknown/non-public/unpublished = a uniform 404.
PUBLIC_STATE_OPEN = "open"
PUBLIC_STATE_CLOSED = "closed"
PUBLIC_STATE_FULL = "full"


def _uuid() -> str:
    return str(uuid.uuid4())


class Form(Base):
    __tablename__ = "forms"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_forms_tenant_slug"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    # Tenant-born, never two-tier (D16).
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String, nullable=False, default=FORM_DRAFT, index=True)
    access = Column(String, nullable=False, default=ACCESS_INTERNAL)

    # The builder's working copy (forever-contract doc, D6).
    draft_definition_json = Column(JSON, nullable=False, default=dict)
    # The published version fill surfaces serve (NULL = never published).
    current_version_id = Column(String, nullable=True)

    # Submission window + caps (D10) - on the form, not the version.
    opens_at = Column(UTCDateTime(), nullable=True)
    closes_at = Column(UTCDateTime(), nullable=True)
    max_submissions = Column(Integer, nullable=True)
    # Enforceable only with an authenticated identity - public/anonymous
    # forms ignore it (foolproof-UI greys it out).
    submission_limit_per_user = Column(Integer, nullable=True)

    # Author-pinned answer keys shown as Submissions-list columns (D18).
    pinned_columns_json = Column(JSON(none_as_null=True), nullable=True)
    # Wizard steps vs one scrolling page (D18 Settings).
    display_mode = Column(String, nullable=False, default="paged")
    # Authors may revise a frozen submission into a new immutable snapshot
    # (plan sprint-4/04 R2). Off by default - opt-in per form.
    allow_revisions = Column(Boolean, nullable=False, default=False, server_default="false")

    created_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    versions = relationship(
        "FormVersion",
        back_populates="form",
        cascade="all, delete-orphan",
        order_by="FormVersion.version_number",
    )


class FormVersion(Base):
    __tablename__ = "form_versions"
    __table_args__ = (
        UniqueConstraint("form_id", "version_number", name="uq_form_versions_number"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    form_id = Column(
        String, ForeignKey("forms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number = Column(Integer, nullable=False)
    # Immutable snapshot - submissions pin it forever (D9).
    definition_json = Column(JSON, nullable=False)
    published_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)

    form = relationship("Form", back_populates="versions")


class FormSubmission(Base):
    __tablename__ = "form_submissions"
    __table_args__ = (
        # Exactly ONE current revision per group (plan sprint-4/04 R1) - partial
        # unique. Mirrors migration e6f7a8b9c0d1 so SQLite tests enforce it too.
        Index(
            "ix_form_submissions_group_current",
            "submission_group_id",
            unique=True,
            sqlite_where=text("is_current"),
            postgresql_where=text("is_current"),
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    form_id = Column(
        String, ForeignKey("forms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Stable identity across revisions (plan sprint-4/04 R1) - external refs
    # point here and resolve to the ``is_current`` row. Equals ``id`` for
    # originals (backfilled). ``revision_number`` increments per revision;
    # ``is_current`` flags the live one (lists default to it, R3).
    submission_group_id = Column(String, nullable=False, default=_uuid, index=True)
    revision_number = Column(Integer, nullable=False, default=1, server_default="1")
    is_current = Column(Boolean, nullable=False, default=True, server_default="true", index=True)
    # Pinned at submit - the reviewer sees the form as it was (D9).
    version_id = Column(String, ForeignKey("form_versions.id"), nullable=False)
    # The form's scoped machine (D4) - every move goes through transition().
    status_id = Column(String, nullable=False, index=True)
    # NULL = anonymous (public surface, slice 2).
    user_id = Column(String, nullable=True, index=True)
    # Inbound polymorphic subject (D2) - "about record X"; same guard class
    # as notification target_id (validate at save, scope at resolve).
    subject_type = Column(String, nullable=True)
    subject_id = Column(String, nullable=True)

    answers_json = Column(JSON, nullable=False, default=dict)
    submitted_at = Column(UTCDateTime(), nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
