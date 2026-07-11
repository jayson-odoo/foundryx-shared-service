"""Centralized background-jobs table (sprint-4/10, plan §3.1).

ONE generic, ``type``-dispatched job table + worker so every future async job
type rides shared machinery (a job row = source of truth, atomic status-claim =
exactly-once, ``cursor_json`` = resumability). Storage migration is the first
``type``; the existing typed job tables (``import_jobs``,
``document_download_jobs``, ``workflow_runs``, ``email_outbox``) are left
untouched (BL-125 folds them in). Core ``public``.
"""
import uuid

from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.sql import func
from sqlalchemy.types import JSON as GenericJSON

from app.database import Base
from app.models.utc_datetime import UTCDateTime

# Generic JSON (Postgres + SQLite tests). none_as_null so a cleared column is
# SQL NULL, not JSON 'null' (house gotcha, sprint-2/02 D1).
_JSON = GenericJSON(none_as_null=True)


def _uuid() -> str:
    return str(uuid.uuid4())


# Job lifecycle. ``needs_review`` = a job that finished with recoverable
# failures and HOLDS for an explicit user decision (storage-migration D5).
JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_NEEDS_REVIEW = "needs_review"
JOB_DONE = "done"
JOB_FAILED = "failed"
JOB_ABORTED = "aborted"

JOB_STATUSES = (
    JOB_PENDING,
    JOB_RUNNING,
    JOB_NEEDS_REVIEW,
    JOB_DONE,
    JOB_FAILED,
    JOB_ABORTED,
)
# Terminal statuses (retention pruning targets these; running/pending never
# pruned). ``needs_review`` is NOT terminal — it awaits an explicit decision.
JOB_TERMINAL_STATUSES = (JOB_DONE, JOB_FAILED, JOB_ABORTED)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    type = Column(String, nullable=False, index=True)  # the JobHandlerDef key
    status = Column(String, nullable=False, default=JOB_PENDING, index=True)
    actor_user_id = Column(String, nullable=True)

    payload_json = Column(_JSON, nullable=True)  # type input
    result_json = Column(_JSON, nullable=True)  # type output
    cursor_json = Column(_JSON, nullable=True)  # resume point
    # Human-readable milestone log for troubleshooting (sprint-4/12): a list of
    # ``{ts, level, message}`` appended via ``JobService.log`` and surfaced on the
    # job-detail page. Milestones only (never per-item) — cheap + reads well.
    logs_json = Column(_JSON, nullable=True)

    progress_total = Column(Integer, nullable=False, default=0)
    progress_done = Column(Integer, nullable=False, default=0)
    progress_failed = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    started_at = Column(UTCDateTime(), nullable=True)
    finished_at = Column(UTCDateTime(), nullable=True)
