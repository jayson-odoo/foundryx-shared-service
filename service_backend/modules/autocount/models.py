"""AutoCount module tables (plan §7) — schema ``app_autocount``.

**Every table carries ``tenant_id`` AND ``company_id``, and every query filters
BOTH (AC-13-41).** Cross-tenant *or* cross-company leakage is a critical defect:
one tenant may run several AutoCount companies, so tenant-scoping alone would
let company A's staged purchase documents surface under company B.
(``ac_company`` is the one exception in form only — its own ``id`` IS the
company id.)

House rules honoured here:
  * ``UTCDateTime`` columns only — never a plain ``DateTime``.
  * ``JSON(none_as_null=True)`` — the default stores Python ``None`` as JSON
    ``null``, which passes ``IS NOT NULL`` and ghosts as a present value.
  * Cross-schema references to core (``connections.id``, ``background_jobs.id``)
    are plain INDEXED String columns, never DB-level FKs (BL-030).

Slice-1 scope. ``ac_quarantine`` (masters, slice 3) and ``ac_write_queue``
(writes, slice 4) are deliberately absent — an unused table invites code that
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
# slice 1 — it is validated against this set, so selecting it is a clean 422
# rather than a silent straight-through push nobody reviewed.
GATED_SYNC_MODES = (SYNC_MODE_MANUAL, SYNC_MODE_SCHEDULED_REVIEW)

# ── push-target sink impls (hop 2, plan 14) ───────────────────────────────────
# The name of the consumer sink a company delivers to. Kept as a literal here
# (matching ``sinks.SINK_LOGGING`` / ``sinks_sorento.SINK_SORENTO``) so the model
# layer never imports the sink layer — ``models`` is loaded first at bootstrap.
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
    # Core ``connections.id`` — plain indexed column, not an FK (BL-030).
    connection_id = Column(String, nullable=False, index=True)

    database_name = Column(String, nullable=False)  # discovered (AC-13-01)
    company_name = Column(String, nullable=False, default="")  # discovered
    name = Column(String, nullable=False, default="")  # operator's own label
    is_active = Column(Boolean, nullable=False, default=True)

    # ── push target (hop 2, plan 14) ─────────────────────────────────────────
    # Which consumer sink this company delivers ALL its entities to. Default
    # ``'logging'`` keeps the slice-1 no-op — a company that has not configured
    # a target changes nothing. ``'sorento'`` + a ``sink_connection_id`` selects
    # the real Sorento sink. A ``server_default`` is REQUIRED (not just the
    # Python ``default``): on a create_all-first host the ADD carries it to
    # existing rows, and on a stamped host the migration's ADD does — either way
    # no ``ac_company`` row is ever left NULL against this NOT NULL column.
    sink_impl = Column(
        String, nullable=False, default=SINK_IMPL_LOGGING, server_default="logging"
    )
    # Core ``connections.id`` of the ``consumer`` connection to push to — plain
    # indexed column, not an FK (BL-030). NULL when ``sink_impl='logging'``.
    sink_connection_id = Column(String, nullable=True, index=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())


class AcEntityConfig(AutocountBase):
    """Per (company, entity): sync mode, source implementation, record cap.

    ``source_impl`` is the D6 pluggability axis — which fetch strategy this
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
    # the GRN unwrap fails every row — so it is configured, never guessed.
    envelope = Column(String, nullable=False, default=ENVELOPE_STATUS_DICT)
    # Whether the FIRST sync (no watermark yet) is unbounded or lookback-windowed
    # (AC-14-25). A document stream is naturally time-bounded; a master list is a
    # standing set that must be mirrored whole. Getting this wrong on masters
    # imports ~1% of the data and reports success.
    initial_load = Column(String, nullable=False, default=INITIAL_LOAD_WINDOWED)
    # The vendor's ``RecordCount`` cap. Hitting it is the ONLY truncation signal
    # available (the response's "N of TOTAL" marker is computed POST-cap and is
    # not a total) — and hitting it is logged and fails loudly (AC-13-46).
    record_cap = Column(Integer, nullable=False, default=200)
    # How far back the FIRST sync reaches when no watermark exists yet.
    # **Applies to ``initial_load='windowed'`` entities ONLY** — a ``full``
    # entity ignores it entirely.
    initial_lookback_days = Column(Integer, nullable=False, default=30)
    enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())


class AcWatermark(AutocountBase):
    """Per (company, entity) delta high-water mark.

    Advances **only on batch success**, to the max ``LastModified`` observed
    (AC-13-05). A failed document holds it for that entity (D18) — re-reading a
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

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())


class AcFieldMapping(AutocountBase):
    """ONE mapping instruction (D5, AC-13-08) — the row an operator adds or
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
    is_required = Column(Boolean, nullable=False, default=False)
    is_enabled = Column(Boolean, nullable=False, default=True)
    # Per-field ownership (D8) — consumed by slice 3's masters merge. Carried
    # now so a mapping row never needs a migration to gain it later.
    is_source_owned = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())


class AcStagedRecord(AutocountBase):
    """A canonical record awaiting approval, plus its RAW source payload.

    ``raw_json`` is retained deliberately (AC-13-07): a field discovered later
    can be mapped retroactively without re-fetching history — and once a window
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
    # Core ``background_jobs.id`` — plain indexed column, not an FK (BL-030).
    job_id = Column(String, nullable=False, index=True)

    source_ref = Column(String, nullable=False)  # DocKey — stable correlation
    doc_no = Column(String, nullable=True)  # display only; MUTABLE at source
    source_last_modified = Column(UTCDateTime(), nullable=True)

    raw_json = Column(_JSON, nullable=True)  # AC-13-07
    canonical_json = Column(_JSON, nullable=True)  # None when FAILED (D13)
    diff_json = Column(_JSON, nullable=True)  # changed fields only (AC-13-12)
    errors_json = Column(_JSON, nullable=True)  # named per-field errors

    status = Column(String, nullable=False, default=STAGED)
    error = Column(Text, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    pushed_at = Column(UTCDateTime(), nullable=True)


class AcSyncRun(AutocountBase):
    """Per-run audit: the window asked for, the counts, the outcome.

    Separate from ``background_jobs`` on purpose: the job row is generic
    machinery (claim / progress / abort), this is the integration-domain record
    an operator reads — which window, how many, why it stopped.
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
    job_id = Column(String, nullable=False, index=True)

    window_from = Column(UTCDateTime(), nullable=True)
    window_to = Column(UTCDateTime(), nullable=True)

    fetched_count = Column(Integer, nullable=False, default=0)
    staged_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    pushed_count = Column(Integer, nullable=False, default=0)

    outcome = Column(String, nullable=True)  # one of RUN_OUTCOMES
    error = Column(Text, nullable=True)
    # True when the record cap was hit — a truncated sync must NEVER read as a
    # complete one (AC-13-46).
    truncated = Column(Boolean, nullable=False, default=False)
    watermark_advanced_to = Column(UTCDateTime(), nullable=True)

    started_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    finished_at = Column(UTCDateTime(), nullable=True)
    duration_ms = Column(Integer, nullable=True)
