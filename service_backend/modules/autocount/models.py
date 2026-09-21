"""AutoCount module tables (plan §7) - schema ``app_autocount``.

**Every table carries ``tenant_id`` AND ``company_id``, and every query filters
BOTH (AC-13-41).** Cross-tenant *or* cross-company leakage is a critical defect:
one tenant may run several AutoCount companies, so tenant-scoping alone would
let company A's staged purchase documents surface under company B.
(``ac_company`` is the one exception in form only - its own ``id`` IS the
company id.)

House rules honoured here:
  * ``UTCDateTime`` columns only - never a plain ``DateTime``.
  * ``JSON(none_as_null=True)`` - the default stores Python ``None`` as JSON
    ``null``, which passes ``IS NOT NULL`` and ghosts as a present value.
  * Cross-schema references to core (``connections.id``, ``background_jobs.id``)
    are plain INDEXED String columns, never DB-level FKs (BL-030).

Slice-1 scope. ``ac_quarantine`` (masters, slice 3) and ``ac_write_queue``
(writes, slice 4) are deliberately absent - an unused table invites code that
half-implements it.
"""
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from sqlalchemy.types import JSON as GenericJSON

from app.models.utc_datetime import UTCDateTime

from .db import AutocountBase
from .envelopes import ENVELOPE_STATUS_DICT
from .sources import INITIAL_LOAD_WINDOWED

_JSON = GenericJSON(none_as_null=True)


def _uuid() -> str:
    return str(uuid.uuid4())


# ── sync modes (D10) ──────────────────────────────────────────────────────────
# MANUAL           operator triggers; result waits in needs_review
# SCHEDULED_REVIEW scheduled; result waits in needs_review
# AUTO             pushes straight through (masters/stock, slice 3)
SYNC_MODE_MANUAL = "MANUAL"
SYNC_MODE_SCHEDULED_REVIEW = "SCHEDULED_REVIEW"
SYNC_MODE_AUTO = "AUTO"
SYNC_MODES = (SYNC_MODE_MANUAL, SYNC_MODE_SCHEDULED_REVIEW, SYNC_MODE_AUTO)
# Modes that stop at the approval gate. AUTO is declared but NOT reachable in
# slice 1 - it is validated against this set, so selecting it is a clean 422
# rather than a silent straight-through push nobody reviewed.
GATED_SYNC_MODES = (SYNC_MODE_MANUAL, SYNC_MODE_SCHEDULED_REVIEW)

# ── push-target sink impls (hop 2, plan 14) ───────────────────────────────────
# The name of the consumer sink a company delivers to. Kept as a literal here
# (matching ``sinks.SINK_LOGGING`` / ``sinks_sorento.SINK_SORENTO``) so the model
# layer never imports the sink layer - ``models`` is loaded first at bootstrap.
SINK_IMPL_LOGGING = "logging"
SINK_IMPL_SORENTO = "sorento"

# ── staged-record lifecycle ───────────────────────────────────────────────────
STAGED = "STAGED"  # mapped cleanly, awaiting approval
STAGED_FAILED = "FAILED"  # mapping failed; NEVER pushable (D13)
STAGED_PUSHED = "PUSHED"  # handed to the sink; the idempotency marker
STAGED_DISCARDED = "DISCARDED"  # operator declined
STAGED_STATUSES = (STAGED, STAGED_FAILED, STAGED_PUSHED, STAGED_DISCARDED)

# ── sync-run outcomes ─────────────────────────────────────────────────────────
RUN_SUCCESS = "SUCCESS"
RUN_FAILED = "FAILED"
RUN_ABORTED = "ABORTED"
RUN_OUTCOMES = (RUN_SUCCESS, RUN_FAILED, RUN_ABORTED)

# ── delivery mode (sprint-5/10 §2.1, D1/D2, AC-10-10) ─────────────────────────
# ``push`` = today's behaviour (an ACTIVE task delivers to the company's sink
# on its schedule); ``pull`` = the task never auto-pushes and never runs on
# the sweep - a consumer/operator request builds a snapshot on demand
# instead. Every task that existed before this plan reads ``push``.
DELIVERY_MODE_PUSH = "push"
DELIVERY_MODE_PULL = "pull"
DELIVERY_MODES = (DELIVERY_MODE_PUSH, DELIVERY_MODE_PULL)

# ── pull snapshot lifecycle (sprint-5/10 §2.4, AC-10-19) ──────────────────────
# Expiry is DERIVED from ``expires_at`` - never a stored fourth status a clock
# skew could disagree with.
PULL_SNAPSHOT_STATUS_BUILDING = "building"
PULL_SNAPSHOT_STATUS_READY = "ready"
PULL_SNAPSHOT_STATUS_FAILED = "failed"
PULL_SNAPSHOT_STATUSES = (
    PULL_SNAPSHOT_STATUS_BUILDING,
    PULL_SNAPSHOT_STATUS_READY,
    PULL_SNAPSHOT_STATUS_FAILED,
)

# ── direct-DB ETL (plan 22 §2.4/2.5/2.7) ──────────────────────────────────────
# Source implementations behind the ``EntitySource`` seam.
SOURCE_IMPL_AUTOCOUNT_READ = "autocount_read"  # HTTP wrapper (plans 13-16)
SOURCE_IMPL_SQL_DB = "sql_db"  # direct read-only SQL source (plan 22)
# The open (no-auth) REST wrapper page-walk source (sprint-5/08).
SOURCE_IMPL_AUTOCOUNT_HTTP = "autocount_http"
# Task lifecycle of a DB extraction (AC-22-18/19): configured but never
# activated → activate-once gate passed, scheduled runs push → held.
ETL_STATUS_DRAFT = "draft"
ETL_STATUS_ACTIVE = "active"
ETL_STATUS_PAUSED = "paused"
ETL_STATUSES = (ETL_STATUS_DRAFT, ETL_STATUS_ACTIVE, ETL_STATUS_PAUSED)
# What a staged record asks the sink to do (AC-22-21). ``delete`` rows are
# reconcile's delete intents; everything before plan 22 was an upsert.
STAGED_OP_UPSERT = "upsert"
STAGED_OP_DELETE = "delete"
STAGED_OPS = (STAGED_OP_UPSERT, STAGED_OP_DELETE)
# How a run was started (AC-22-17). Every pre-plan-22 run was ``manual``.
RUN_MODE_MANUAL = "manual"
RUN_MODE_INCREMENTAL = "incremental"
RUN_MODE_RECONCILE = "reconcile"
RUN_MODE_SKIPPED = "skipped"
# sprint-5/10 (AC-10-21) - a pull snapshot build. Writes NO staged record, NO
# row hash and advances NO watermark; it still records ONE ``AcSyncRun`` so
# the Runs tab shows a pull build exactly as it shows a push run.
RUN_MODE_SNAPSHOT = "snapshot"
RUN_MODES = (
    RUN_MODE_MANUAL,
    RUN_MODE_INCREMENTAL,
    RUN_MODE_RECONCILE,
    RUN_MODE_SKIPPED,
    RUN_MODE_SNAPSHOT,
)


class AcCompany(AutocountBase):
    """One AutoCount company database.

    Identity is ``database_name`` (``DatabaseName`` from the login response),
    **discovered, never typed by an operator**. The UNIQUE below is the real
    company-identity guard: core's ``uq_connection_tenant_provider`` was
    deliberately carved out for ``erp`` (every company is
    ``provider='autocount'``), so core holds ZERO AutoCount knowledge and this
    owns it.
    """

    __tablename__ = "ac_company"
    __table_args__ = (
        UniqueConstraint("tenant_id", "database_name", name="uq_ac_company_tenant_db"),
        Index("ix_ac_company_tenant", "tenant_id"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    # Core ``connections.id`` - plain indexed column, not an FK (BL-030).
    connection_id = Column(String, nullable=False, index=True)

    database_name = Column(String, nullable=False)  # discovered (AC-13-01)
    company_name = Column(String, nullable=False, default="")  # discovered
    name = Column(String, nullable=False, default="")  # operator's own label
    is_active = Column(Boolean, nullable=False, default=True)

    # ── push target (hop 2, plan 14) ─────────────────────────────────────────
    # Which consumer sink this company delivers ALL its entities to. Default
    # ``'logging'`` keeps the slice-1 no-op - a company that has not configured
    # a target changes nothing. ``'sorento'`` + a ``sink_connection_id`` selects
    # the real Sorento sink. A ``server_default`` is REQUIRED (not just the
    # Python ``default``): on a create_all-first host the ADD carries it to
    # existing rows, and on a stamped host the migration's ADD does - either way
    # no ``ac_company`` row is ever left NULL against this NOT NULL column.
    sink_impl = Column(
        String, nullable=False, default=SINK_IMPL_LOGGING, server_default="logging"
    )
    # Core ``connections.id`` of the ``consumer`` connection to push to - plain
    # indexed column, not an FK (BL-030). NULL when ``sink_impl='logging'``.
    sink_connection_id = Column(String, nullable=True, index=True)
    # The Sorento ``companies.code`` this company is anchored to (plan 22
    # Appendix A6 - every ingest/read/delete call is company-anchored).
    # Required when ``sink_impl='sorento'`` (validated at activation, S2);
    # NULL for the logging sink and for every pre-plan-22 row.
    sorento_company_code = Column(String, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())


class AcEntityConfig(AutocountBase):
    """Per (company, entity): sync mode, source implementation, record cap.

    ``source_impl`` is the D6 pluggability axis - which fetch strategy this
    entity uses. Uncertainty lives in HOW data is fetched, not in endpoint
    topology (which is a fixed uniform grammar), so that is where the seam is.
    """

    __tablename__ = "ac_entity_config"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "company_id", "entity_type", name="uq_ac_entity_config"
        ),
        Index("ix_ac_entity_config_scope", "tenant_id", "company_id"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    company_id = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)  # canonical key

    sync_mode = Column(String, nullable=False, default=SYNC_MODE_MANUAL)
    source_impl = Column(String, nullable=False, default="autocount_read")
    # The OUTER response shape this entity returns (AC-14-03). GRN is a dict
    # carrying ``Status``; masters are a bare ARRAY whose rows carry their own.
    # Neither is derivable from the other, and reading a master response through
    # the GRN unwrap fails every row - so it is configured, never guessed.
    envelope = Column(String, nullable=False, default=ENVELOPE_STATUS_DICT)
    # Whether the FIRST sync (no watermark yet) is unbounded or lookback-windowed
    # (AC-14-25). A document stream is naturally time-bounded; a master list is a
    # standing set that must be mirrored whole. Getting this wrong on masters
    # imports ~1% of the data and reports success.
    initial_load = Column(String, nullable=False, default=INITIAL_LOAD_WINDOWED)
    # The vendor's ``RecordCount`` cap. Hitting it is the ONLY truncation signal
    # available (the response's "N of TOTAL" marker is computed POST-cap and is
    # not a total) - and hitting it is logged and fails loudly (AC-13-46).
    record_cap = Column(Integer, nullable=False, default=200)
    # How far back the FIRST sync reaches when no watermark exists yet.
    # **Applies to ``initial_load='windowed'`` entities ONLY** - a ``full``
    # entity ignores it entirely.
    initial_lookback_days = Column(Integer, nullable=False, default=30)
    enabled = Column(Boolean, nullable=False, default=True)
    # sprint-5/10 (AC-10-10) - ``push`` (today's behaviour) or ``pull`` (never
    # auto-pushes, never runs on the sweep - a consumer/operator request
    # builds a snapshot on demand). A ``server_default`` is REQUIRED (not
    # just the Python ``default``) - same reasoning as ``sink_impl`` above:
    # on a create_all-first host the ADD carries it to existing rows, and on
    # a stamped host the migration's (0020) ADD does - either way no
    # ``ac_entity_config`` row is ever left NULL against this NOT NULL
    # column. ``backfill_delivery_mode_defaults`` is the belt-and-braces
    # sweep, same contract as ``backfill_sink_impl_defaults``.
    delivery_mode = Column(
        String, nullable=False, default=DELIVERY_MODE_PUSH, server_default=DELIVERY_MODE_PUSH
    )

    # ── direct-DB ETL task (plan 22 §2.4) - the per-(company, entity) task IS
    # this row (decision Q13: no free-form task entity). ───────────────────
    # For ``source_impl='sql_db'``: ``{connectionId, query, lineQuery?,
    # keyColumns[], watermarkColumn?, comparedColumns[], fromDate?,
    # incrementalMinutes, reconcileMode, reconcileHours?, reconcileAt?}``.
    # camelCase keys (the wire shape is stored as-is); NULL = never configured.
    source_config = Column(_JSON, nullable=True)
    # ``draft`` until the activate-once gate passes (AC-22-18). A
    # ``server_default`` so existing rows land on ``draft`` on the ADD.
    etl_status = Column(
        String, nullable=False, default=ETL_STATUS_DRAFT, server_default="draft"
    )
    activated_at = Column(UTCDateTime(), nullable=True)
    # The sweep's due-selection keys (AC-22-13) - INDEXED, one query per tick.
    next_incremental_at = Column(UTCDateTime(), nullable=True, index=True)
    next_reconcile_at = Column(UTCDateTime(), nullable=True, index=True)
    # The last run's failure, surfaced on the task (AC-22-19) - never silent.
    last_run_error = Column(Text, nullable=True)
    # The last run's TASK-LEVEL error code (plan 22 Appendix A6/A7): a Sorento
    # company-anchor 422 lands HERE (COMPANY_ANCHOR_REQUIRED | UNKNOWN_COMPANY |
    # COMPANY_BINDING_INVALID | COMPANY_ANCHOR_AMBIGUOUS), never per record.
    last_run_error_code = Column(String, nullable=True)
    # Result column names of the SAVED query, from the validation preview each
    # PUT runs (AC-22-11) - the Mapping tab's source picker reads them without
    # re-running the query (AC-22-09). NULL = no query saved yet.
    result_columns = Column(_JSON, nullable=True)
    # The SAVED lineQuery's result column names, from the line preview a
    # document task's PUT also runs (sprint-5/02, AC-02-06) - the Mapping
    # tab's Line-fields source picker reads them, and a line row whose
    # `source_path` is absent here is rejected at save time. NULL = the line
    # query has never previewed clean yet ("Test the line query first").
    line_result_columns = Column(_JSON, nullable=True)
    # When the last SUCCESSFUL dry-run preview completed (AC-22-18). CLEARED by
    # every config save - a preview of a superseded query must never unlock
    # Activate. NULL = Activate withheld.
    last_preview_at = Column(UTCDateTime(), nullable=True)
    # The last preview's genuinely-``failed`` prediction count (S5 review
    # SHOULD-FIX 4b) - a preview that COMPLETES but reports failed rows still
    # stamps ``last_preview_at`` (the dry run itself worked), so that alone is
    # not proof the task is safe to activate. ``retryable`` rows are NOT
    # counted here - a legitimate dependency-order carry-over (AC-22-23) must
    # stay activatable. NULL alongside a NULL ``last_preview_at`` = never
    # previewed; CLEARED (like ``last_preview_at``) by every config save.
    last_preview_failed_count = Column(Integer, nullable=True)
    # When the last run finished, whatever its outcome (AC-22-17).
    last_run_at = Column(UTCDateTime(), nullable=True)
    # sprint-5/11 (AC-11-23, D10) - the in-flight ``autocount_source_preview``
    # job claimed by THIS task, one preview per task. Set atomically
    # (``UPDATE ... WHERE preview_job_id IS NULL``) by
    # ``PreviewJobService.start`` and released on every terminal path -
    # done, failed, cancelled, and the orphan sweep's ``on_job_orphaned``
    # hook (mirrors ``AcPullSnapshot``'s own ``job_id`` claim pattern). A
    # module column, never a core ``background_jobs`` index (a module may
    # not add one) - NULL = no preview in flight, lets a remounted editor
    # re-attach instead of starting a second walk.
    preview_job_id = Column(String, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())


class AcRowHash(AutocountBase):
    """Reconcile state (plan 22 §2.4/2.5, AC-22-16): ONE row per source
    record ever seen by a DB task, holding only the hash of its compared
    columns - never a copy of the row.

    The diff on a reconcile run is hash-vs-hash: a new ``source_ref`` stages an
    add, a changed hash an update, an equal hash nothing, and a ref absent from
    the extract becomes a delete intent. A confirmed delete removes the row so
    a later re-appearance at source stages as an add again (AC-22-21).
    """

    __tablename__ = "ac_row_hash"
    __table_args__ = (
        Index("ix_ac_row_hash_scope", "tenant_id", "company_id", "entity_type"),
    )

    tenant_id = Column(String, primary_key=True)
    company_id = Column(String, primary_key=True)
    entity_type = Column(String, primary_key=True)
    source_ref = Column(String, primary_key=True)
    row_hash = Column(String, nullable=False)
    last_seen_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)


class AcDocFingerprint(AutocountBase):
    """feat/line-fingerprint-sweep - ONE row per document header ever seen by
    an incremental sweep, holding the sha256 of its own fingerprint query's
    ordered aggregate values (``sql_source.hashing.document_fingerprint``) -
    never a copy of the row, mirroring ``AcRowHash``'s own shape and reason.

    Distinct from ``AcRowHash``: the row hash covers the HEADER's own result
    columns and only ever refreshes when a header is actually re-fetched; this
    fingerprint is a cheap ``GROUP BY`` over the LINE table, computed on every
    sweep tick REGARDLESS of whether the header changed, so it can flag a
    line-only edit AutoCount never bumps the header's ``LastModified`` for
    (prod finding SO419208 - ``SODTL.TransferedQty`` rising with no
    ``SO.LastModified`` change).
    """

    __tablename__ = "ac_doc_fingerprint"
    __table_args__ = (
        Index("ix_ac_doc_fingerprint_scope", "tenant_id", "company_id", "entity_type"),
    )

    tenant_id = Column(String, primary_key=True)
    company_id = Column(String, primary_key=True)
    entity_type = Column(String, primary_key=True)
    source_ref = Column(String, primary_key=True)
    fingerprint = Column(String, nullable=False)
    seen_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)


class AcWatermark(AutocountBase):
    """Per (company, entity) delta high-water mark.

    Advances **only on batch success**, to the max ``LastModified`` observed
    (AC-13-05). A failed document holds it for that entity (D18) - re-reading a
    window is cheap and idempotent; skipping a window loses data silently.
    """

    __tablename__ = "ac_watermark"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "company_id", "entity_type", name="uq_ac_watermark"
        ),
        Index("ix_ac_watermark_scope", "tenant_id", "company_id"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    company_id = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)

    last_modified_at = Column(UTCDateTime(), nullable=True)
    cursor_json = Column(_JSON, nullable=True)  # slice-2 window-split resume
    last_success_at = Column(UTCDateTime(), nullable=True)
    last_attempt_at = Column(UTCDateTime(), nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    # feat/line-fingerprint-sweep - when the fingerprint sweep last ran
    # SUCCESSFULLY for this (company, entity). NULL/missing = due (a task
    # that has never swept, or whose last sweep errored, sweeps on its very
    # next incremental run). Advances only on a clean sweep - a fingerprint
    # query error leaves it untouched (the module docstring's "fails only
    # the sweep" rule) so the next tick retries rather than waiting out a
    # full interval on a query that is still broken.
    last_fingerprint_sweep_at = Column(UTCDateTime(), nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())


class AcFieldMapping(AutocountBase):
    """ONE mapping instruction (D5, AC-13-08) - the row an operator adds or
    removes to change behaviour with no code change.

    Per (company, entity) because per-customer UDF arrays are exactly what
    forces mapping to be data in the first place.
    """

    __tablename__ = "ac_field_mapping"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "company_id",
            "entity_type",
            "scope",
            "canonical_field",
            name="uq_ac_field_mapping",
        ),
        Index("ix_ac_field_mapping_scope", "tenant_id", "company_id", "entity_type"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    company_id = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)

    scope = Column(String, nullable=False, default="header")  # header | line
    source_path = Column(String, nullable=False)  # LITERAL vendor casing
    canonical_field = Column(String, nullable=False)
    transform = Column(String, nullable=False, default="string")
    # Optional safe transform FORMULA (slice 16, AC-16-01). NULL ⇒ the named
    # ``transform`` above is authoritative (today's behaviour, back-compat).
    # Set ⇒ the formula produces the field's value (evaluated by ``formula.py``)
    # and the ``transform`` is retained only as the display preset. A ``Text``
    # column (never migrated to a JSON/None-sensitive type) so a NULL is a true
    # SQL NULL, distinct from an empty-string formula.
    formula = Column(Text, nullable=True)
    is_required = Column(Boolean, nullable=False, default=False)
    is_enabled = Column(Boolean, nullable=False, default=True)
    # Per-field ownership (D8) - consumed by slice 3's masters merge. Carried
    # now so a mapping row never needs a migration to gain it later.
    is_source_owned = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())


class AcStagedRecord(AutocountBase):
    """A canonical record awaiting approval, plus its RAW source payload.

    ``raw_json`` is retained deliberately (AC-13-07): a field discovered later
    can be mapped retroactively without re-fetching history - and once a window
    has passed, re-fetching history is exactly what the vendor API makes hard.
    """

    __tablename__ = "ac_staged_record"
    __table_args__ = (
        Index("ix_ac_staged_scope", "tenant_id", "company_id", "entity_type"),
        Index("ix_ac_staged_job", "tenant_id", "job_id"),
        Index("ix_ac_staged_ref", "tenant_id", "company_id", "source_ref"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    company_id = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)
    # Core ``background_jobs.id`` - plain indexed column, not an FK (BL-030).
    job_id = Column(String, nullable=False, index=True)

    source_ref = Column(String, nullable=False)  # DocKey - stable correlation
    doc_no = Column(String, nullable=True)  # display only; MUTABLE at source
    source_last_modified = Column(UTCDateTime(), nullable=True)

    raw_json = Column(_JSON, nullable=True)  # AC-13-07
    canonical_json = Column(_JSON, nullable=True)  # None when FAILED (D13)
    diff_json = Column(_JSON, nullable=True)  # changed fields only (AC-13-12)
    errors_json = Column(_JSON, nullable=True)  # named per-field errors

    status = Column(String, nullable=False, default=STAGED)
    error = Column(Text, nullable=True)
    # ``upsert`` (every pre-plan-22 row) or ``delete`` (a reconcile delete
    # intent, AC-22-21). Push routes on this - a delete carries no canonical.
    op = Column(String, nullable=False, default=STAGED_OP_UPSERT, server_default="upsert")

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    pushed_at = Column(UTCDateTime(), nullable=True)
    # Stamped every time ``list_pending_for_entity`` hands this row to a push
    # (fix/push-marks-per-chunk, prod finding 2026-09-07: a permanently
    # ``retryable`` head of the oldest-first queue must not starve fresh rows
    # forever). ``NULLS FIRST`` in that query's ordering, so a never-offered
    # row always sorts ahead of one already given a chance and answered
    # retryable again.
    last_offered_at = Column(UTCDateTime(), nullable=True)


class AcSyncRun(AutocountBase):
    """Per-run audit: the window asked for, the counts, the outcome.

    Separate from ``background_jobs`` on purpose: the job row is generic
    machinery (claim / progress / abort), this is the integration-domain record
    an operator reads - which window, how many, why it stopped.
    """

    __tablename__ = "ac_sync_run"
    __table_args__ = (
        Index("ix_ac_sync_run_scope", "tenant_id", "company_id", "entity_type"),
        Index("ix_ac_sync_run_job", "tenant_id", "job_id"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    company_id = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)
    # NULLABLE since plan 22 S2: a ``skipped`` overlap tick (AC-22-14) records
    # a run row without ever enqueuing a job.
    job_id = Column(String, nullable=True, index=True)

    window_from = Column(UTCDateTime(), nullable=True)
    window_to = Column(UTCDateTime(), nullable=True)

    fetched_count = Column(Integer, nullable=False, default=0)
    staged_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    pushed_count = Column(Integer, nullable=False, default=0)
    # ── run-history cost columns (plan 22 §2.7, AC-22-17) ───────────────────
    # How the run started (``manual`` for every pre-plan-22 row); how many
    # source rows were scanned (volume × frequency = cost); adds/updates
    # staged by the hash-diff classification; delete intents; why a skipped
    # tick never ran.
    mode = Column(String, nullable=False, default=RUN_MODE_MANUAL, server_default="manual")
    rows_scanned = Column(Integer, nullable=False, default=0, server_default="0")
    added_count = Column(Integer, nullable=False, default=0, server_default="0")
    updated_count = Column(Integer, nullable=False, default=0, server_default="0")
    deleted_count = Column(Integer, nullable=False, default=0, server_default="0")
    skip_reason = Column(Text, nullable=True)

    outcome = Column(String, nullable=True)  # one of RUN_OUTCOMES
    error = Column(Text, nullable=True)
    # ── push request accounting (fix/push-marks-per-chunk, prod 2026-09-07) ──
    # A chunk-level push fault used to be invisible on the run row (the
    # summary carried it, ``ac_sync_run.error`` did not) - an operator saw
    # ``pushed_count 0`` with ``error NULL`` and no way to tell why. ``requests``
    # / ``requests_failed`` count chunk POSTs this run made; ``first_failure``
    # is the first one's ``{status, message}`` (status + a bounded snippet,
    # ``describe_consumer_failure`` style) - never the request/URL.
    requests = Column(Integer, nullable=True)
    requests_failed = Column(Integer, nullable=True)
    first_failure = Column(_JSON, nullable=True)
    # True when the record cap was hit - a truncated sync must NEVER read as a
    # complete one (AC-13-46).
    truncated = Column(Boolean, nullable=False, default=False)
    watermark_advanced_to = Column(UTCDateTime(), nullable=True)

    started_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    finished_at = Column(UTCDateTime(), nullable=True)
    duration_ms = Column(Integer, nullable=True)


class AcPullSnapshot(AutocountBase):
    """One IMMUTABLE extraction of ONE (company, entity) at one instant
    (sprint-5/10 §2.4, AC-10-18/19).

    ``company_code`` is COPIED here at build time (never re-read from
    ``ac_company.sorento_company_code``) so a later edit of the company's
    consumer code cannot retarget an extraction already out for review.
    Immutability once ``ready`` is STRUCTURAL: the repository exposes
    insert-row and terminal-stamp methods only, and ``SnapshotService``
    raises on any write against a snapshot whose status is not
    ``building`` (AC-10-19) - never a convention an operator could bypass.
    """

    __tablename__ = "ac_pull_snapshot"
    __table_args__ = (
        Index(
            "ix_ac_pull_snapshot_triple", "tenant_id", "company_id", "entity_type"
        ),
        Index("ix_ac_pull_snapshot_status", "tenant_id", "status"),
        # sprint-5/10 review round 1 SHOULD-FIX 3 - EXPLICIT, named indexes
        # (matching migration 0020's own ``add_index`` names exactly) for
        # ``job_id``/``expires_at``, so ``create_all`` (this suite's SQLite
        # rig, and any create_all-first Postgres host) and the migration
        # agree on ONE index per column - a column-level ``index=True`` here
        # PLUS the migration's explicit ``CREATE INDEX`` minted TWO indexes
        # on the same column on the lane Postgres (confirmed:
        # ``ix_ac_pull_snapshot_expires_at`` beside the auto-named
        # ``ix_app_autocount_ac_pull_snapshot_expires_at``, same for
        # ``job_id``).
        Index("ix_ac_pull_snapshot_expires_at", "expires_at"),
        Index("ix_ac_pull_snapshot_job", "job_id"),
        # sprint-5/10 review round 1 SHOULD-FIX 4 (AC-10-26) - AT MOST ONE
        # ``building`` snapshot per (tenant, company, entity) triple, enforced
        # by the DATABASE, not just ``PullService.request_build``'s
        # read-then-write check (two concurrent Build clicks would otherwise
        # both pass that check and start two extractions). A ``ready``/
        # ``failed`` row never collides with this - the predicate is
        # ``status = 'building'`` only.
        Index(
            "uq_ac_pull_snapshot_one_building",
            "tenant_id", "company_id", "entity_type",
            unique=True,
            postgresql_where=Column("status") == PULL_SNAPSHOT_STATUS_BUILDING,
            sqlite_where=Column("status") == PULL_SNAPSHOT_STATUS_BUILDING,
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    company_id = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)
    # Copied from ``ac_company.sorento_company_code`` at build time (see the
    # class docstring) - NULL only for a pull-only company on the logging
    # sink, whose gateway header reports it as such.
    company_code = Column(String, nullable=True)
    status = Column(String, nullable=False, default=PULL_SNAPSHOT_STATUS_BUILDING)
    # Core ``background_jobs.id`` of the build job - plain indexed column,
    # never an FK (BL-030). Indexed by ``ix_ac_pull_snapshot_job`` above
    # (review round 1 SHOULD-FIX 3) - no ``index=True`` here too, or
    # ``create_all`` mints a SECOND, auto-named index on the same column.
    job_id = Column(String, nullable=True)
    record_count = Column(Integer, nullable=False, default=0)
    complete = Column(Boolean, nullable=False, default=False)
    content_hash = Column(String, nullable=True)
    # ``excludedRows``/``excludedCount`` (every entity) plus the per-entity
    # counters (AC-10-63/66/81) - the ONE place they live; the gateway header
    # is a thin projection of this column plus the row's own base fields.
    metadata_json = Column(_JSON, nullable=True)
    error = Column(Text, nullable=True)
    # One of the pinned gateway codes (AC-10-64/88,
    # ``sync.PULL_SNAPSHOT_FAILED_CODES``): SOURCE_PAGE_FAILED |
    # ENRICH_FAILED | ROW_LIMIT | EMPTY_EXTRACT | BUILD_ABANDONED.
    error_code = Column(String, nullable=True)
    requested_via = Column(String, nullable=False, default="operator")
    requested_by = Column(String, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    # The BUILD END (never its start) - a 25-minute build still leaves a full
    # TTL window of review time (plan §2.4).
    extracted_at = Column(UTCDateTime(), nullable=True)
    # Indexed by ``ix_ac_pull_snapshot_expires_at`` above (review round 1
    # SHOULD-FIX 3) - see that index's own comment.
    expires_at = Column(UTCDateTime(), nullable=True)


class AcPullApiKey(AutocountBase):
    """One issued pull gateway key (sprint-5/10 S4, AC-10-27/28).

    Mirrors ``modules.omnichannel.models.WorkspaceApiKey`` in spirit -
    scheme-prefixed plaintext returned ONCE, only a sha256 hash + an 8-char
    indexed lookup prefix stored - but is a deliberate, acknowledged
    duplication (D9/BL-SS-210): cross-module table reads are forbidden, so
    this module cannot reuse omnichannel's table.

    ``company_ids`` is the explicit SET of ``ac_company.id`` this key may
    act on - validated to belong to ``tenant_id`` at issue time
    (``PullKeyService.issue``) and re-checked at every gateway call (the
    polymorphic-stored-id rule: save-time validation AND tenant-scoped
    resolution at use time).
    """

    __tablename__ = "ac_pull_api_key"
    __table_args__ = (
        Index("ix_ac_pull_api_key_tenant", "tenant_id"),
        # The O(1) lookup ``PullKeyService.resolve`` needs BEFORE it knows
        # the tenant - deliberately NOT combined with tenant_id above.
        Index("ix_ac_pull_api_key_prefix", "key_prefix"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    name = Column(String, nullable=False, default="")
    key_prefix = Column(String, nullable=False)
    key_hash = Column(String, nullable=False)
    company_ids = Column(_JSON, nullable=False, default=list)
    created_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    last_used_at = Column(UTCDateTime(), nullable=True)
    revoked_at = Column(UTCDateTime(), nullable=True)


class AcPullAudit(AutocountBase):
    """One row per public gateway CALL (sprint-5/10 S4, AC-10-27/34) - who
    (key), when, what (company/entity/snapshot/action/page), and the outcome
    (``status_code``). Deliberately carries NO payload field and NO
    plaintext key - the module's own "no PII/no payload in audit" rule.

    A request whose key never resolved at all (missing/malformed/unknown/
    revoked) writes NO row here (this file's own choice, stated once): there
    is no tenant to attribute it to, and ``tenant_id`` is NOT NULL like
    every other table in this module.
    """

    __tablename__ = "ac_pull_audit"
    __table_args__ = (
        Index("ix_ac_pull_audit_tenant", "tenant_id"),
        Index("ix_ac_pull_audit_snapshot", "snapshot_id"),
        Index("ix_ac_pull_audit_key", "key_id"),
        # review round 2 (item 5) - the 90-day prune
        # (``pull_service.prune_pull_snapshots``/``PullAuditRepository.
        # delete_older_than``) full-scans this table without it; migration
        # 0021 (unreleased) is amended IN PLACE to add the matching index,
        # never a follow-up migration.
        Index("ix_ac_pull_audit_created_at", "created_at"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False)
    company_id = Column(String, nullable=True)
    entity_type = Column(String, nullable=True)
    key_id = Column(String, nullable=True)
    snapshot_id = Column(String, nullable=True)
    action = Column(String, nullable=False)
    page = Column(Integer, nullable=True)
    record_count = Column(Integer, nullable=True)
    status_code = Column(Integer, nullable=False)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)


class AcPullSnapshotRow(AutocountBase):
    """One delivered row of a snapshot, served exactly as stored - no
    re-projection at read time (AC-10-18, AC-10-33).

    The composite primary key IS the "no update-row method" guarantee
    (AC-10-19): there is no legal way to overwrite a row short of deleting
    the whole snapshot and rebuilding it, which is a different operation.
    """

    __tablename__ = "ac_pull_snapshot_row"
    __table_args__ = (
        Index("ix_ac_pull_snapshot_row_snapshot", "tenant_id", "snapshot_id"),
        # sprint-5/10 review round 1 SHOULD-FIX 3 - explicit, named (matches
        # migration 0020's ``ix_ac_pull_snapshot_row_company``); no
        # ``index=True`` on the column below too, or ``create_all`` mints a
        # second, auto-named duplicate on the same column (see the sibling
        # comment on ``AcPullSnapshot.expires_at`` above).
        Index("ix_ac_pull_snapshot_row_company", "company_id"),
    )

    tenant_id = Column(String, primary_key=True)
    snapshot_id = Column(String, primary_key=True)
    row_index = Column(Integer, primary_key=True)
    company_id = Column(String, nullable=False)
    source_ref = Column(String, nullable=False)
    # Exactly ``CanonicalRecord.sink_payload()`` - the same shape a push
    # delivers (AC-10-23's content-hash formula depends on this being the
    # EXACT stored dict, never a re-projection).
    payload_json = Column(_JSON, nullable=False)
