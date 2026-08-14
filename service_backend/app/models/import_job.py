"""Import engine job + settings tables (sprint-3/09, F8).

``import_jobs`` is the source of truth for a two-phase, job-backed, Celery-
decoupled import (mirrors ``document_download_jobs``). ``import_settings`` is the
per-tenant cap row (mirrors ``workflow_settings``). All core ``public``.
"""
import uuid

from sqlalchemy import Boolean, Column, Integer, String
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.sql import func
from sqlalchemy.types import JSON as GenericJSON

from app.database import Base
from app.models.utc_datetime import UTCDateTime

# Use generic JSON (Postgres + SQLite tests). none_as_null so a cleared column
# is SQL NULL, not JSON 'null' (house gotcha, sprint-2/02 D1).
_JSON = GenericJSON(none_as_null=True)


def _uuid() -> str:
    return str(uuid.uuid4())


# Modes (D5) - chosen in the modal, never guessed.
MODE_CREATE_ONLY = "create_only"
MODE_UPDATE_ONLY = "update_only"
MODE_UPSERT = "upsert"
IMPORT_MODES = (MODE_CREATE_ONLY, MODE_UPDATE_ONLY, MODE_UPSERT)

# Job lifecycle (D7).
STATUS_PENDING = "pending"
STATUS_VALIDATING = "validating"
STATUS_VALIDATED = "validated"
STATUS_IMPORTING = "importing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    actor_user_id = Column(String, nullable=True)

    entity_type = Column(String, nullable=False)  # the ImporterDef key
    mode = Column(String, nullable=False, default=MODE_CREATE_ONLY)
    abort_on_invalid = Column(Boolean, nullable=False, default=False)
    # Embedded-list parent scope, e.g. {"project_id": "..."} (D17).
    context_json = Column(_JSON, nullable=True)
    # Default OFF - a backfill must not fire 10k workflow events (D13).
    trigger_automations = Column(Boolean, nullable=False, default=False)
    # tz assumed for naive datetimes (D6 transparency).
    assumed_tz = Column(String, nullable=True)

    file_storage_key = Column(String, nullable=True)
    files_purged = Column(Boolean, nullable=False, default=False)  # D16
    sheet_name = Column(String, nullable=True)
    mapping_json = Column(_JSON, nullable=True)  # {fileHeader: columnKey | null}

    status = Column(String, nullable=False, default=STATUS_PENDING, index=True)
    total_rows = Column(Integer, nullable=False, default=0)
    valid_rows = Column(Integer, nullable=False, default=0)
    invalid_rows = Column(Integer, nullable=False, default=0)

    error_report_key = Column(String, nullable=True)
    errors_json = Column(_JSON, nullable=True)  # [{row, column, message}] capped ~1000
    created_ids = Column(_JSON, nullable=True)  # forensic trace (D12)
    updated_ids = Column(_JSON, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    validated_at = Column(UTCDateTime(), nullable=True)
    committed_at = Column(UTCDateTime(), nullable=True)
    finished_at = Column(UTCDateTime(), nullable=True)


class ImportSettings(Base):
    """Per-tenant caps (D11). NULL falls back to the global settings default."""

    __tablename__ = "import_settings"

    tenant_id = Column(String, primary_key=True)
    max_rows = Column(Integer, nullable=True)
    max_file_mb = Column(Integer, nullable=True)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=True
    )
