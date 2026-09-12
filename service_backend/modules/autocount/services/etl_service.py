"""Direct-DB ETL service (plan 22 S1): SQL connections, schema browse, query
preview and the per-(company, entity) task config (AC-22-05/06/11/29/30).

Business logic only - HTTP lives in ``routers/sql.py`` + ``routers/companies.py``,
SQL against OUR database in the repositories, SQL against the SOURCE database
in ``sql_source/``.

Two security invariants every method honours:

* **A ``connectionId`` is a stored polymorphic id.** It is resolved
  tenant- AND provider-scoped on EVERY use (list, schema, preview, task save)
  via ``ConnectionRepository.get_for_provider`` - never a bare get-by-id.
* **Credentials never leave the backend.** Decrypted in memory for the engine
  only; every error that could carry them passes ``sanitize_error``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
import sqlalchemy as sa
from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.jobs.service import JobService
from app.models.connection import Connection
from app.secrets import decrypt_secret

from ..activity import (
    ACTIVITY_ERROR,
    ACTIVITY_SUCCESS,
    OPERATION_REPUSH_TASK,
    record_activity,
)
from ..canonical.documents import (
    DOCUMENT_ENTITY_TYPES,
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
    LINE_QUERY_DOC_KEY_PARAM,
    is_document_entity,
)
from ..canonical.grn import ENTITY_GOODS_RECEIVED_NOTE
from ..formula import FormulaError, known_filter_variables, parse_formula
from ..canonical.masters import (
    ENTITY_BRAND,
    ENTITY_CUSTOMER,
    ENTITY_PRODUCT,
    ENTITY_PRODUCT_CATEGORY,
    ENTITY_SALES_AGENT,
    ENTITY_SUPPLIER,
    ENTITY_UNIT_OF_MEASURE,
    ENTITY_WAREHOUSE,
)
from ..models import (
    ETL_STATUS_ACTIVE,
    ETL_STATUS_DRAFT,
    ETL_STATUS_PAUSED,
    RUN_MODE_MANUAL,
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    SOURCE_IMPL_SQL_DB,
    SYNC_MODE_SCHEDULED_REVIEW,
    AcEntityConfig,
)
from ..repositories import (
    ConnectionRepository,
    EntityConfigRepository,
    RowHashRepository,
    SyncJobRepository,
    SyncRunRepository,
    WatermarkRepository,
)
from ..sources import INITIAL_LOAD_FULL
from ..sql_provider import SQL_DATABASE_PROVIDER_KEY
from ..sql_source.errors import SqlGuardError, SqlSourceError
from ..sql_source.guard import assert_select_only, normalize_statement, query_binds_param
from ..sql_source.introspect import (
    SCHEMA_CACHE,
    SchemaCache,
    SqlSchemaTree,
    introspect_schema,
)
from ..sql_source.preview import PreviewResult, is_orderable_type, run_preview, wrap_preview
from ..sql_source.runtime import (
    RUNTIME,
    QUERY_TIMEOUT_SECONDS,
    SqlSourceRuntime,
    open_readonly,
    sanitize_error,
    secrets_of,
)
from ..sql_source.source import (
    CURSOR_MARK,
    build_document_header_wrap,
    build_incremental_wrap,
)
from .company_service import (
    HTTP_CAPABLE_ENTITY_TYPES,
    SOURCE_KIND_DB,
    AutocountServiceError,
    CompanyService,
    ConnectionNotFound,
    EntityConfigNotFound,
)
from ..presets import seed_document_mapping, seed_http_preset_mapping
from ..mapping import SCOPE_HEADER, SCOPE_LINE
from ..http_source.preview import HttpPreviewError, run_http_preview, validate_http_path
from ..provider import AUTH_NONE, PROVIDER_KEY, auth_mode
from ..sql_source.hashing import compared_columns_for

logger = logging.getLogger("foundryx.autocount")

# ── entity catalogue (plan 22 Scope) ─────────────────────────────────────────
# Canonical keys a DB task may be configured for. Code constants, never a
# tenant-editable key. Documents carry a from-date + a line query (Q20).
# ``ENTITY_SALES_AGENT``/``ENTITY_PRODUCT``/``ENTITY_WAREHOUSE``/
# ``ENTITY_PRODUCT_CATEGORY``/``ENTITY_UNIT_OF_MEASURE``/``ENTITY_SALES_ORDER``/
# ``ENTITY_PURCHASE_ORDER`` are imported (not redefined here, NIT S2 review,
# extended S4/S5) - ``mapping.py``/``mapping_catalog.py``/``sinks_sorento.py``
# need the SAME strings and share this import to avoid a second literal
# drifting from this one.
ETL_ENTITY_TYPES = (
    ENTITY_SUPPLIER,
    ENTITY_CUSTOMER,
    ENTITY_PRODUCT,
    ENTITY_WAREHOUSE,
    ENTITY_PRODUCT_CATEGORY,
    ENTITY_UNIT_OF_MEASURE,
    ENTITY_SALES_AGENT,
    ENTITY_SALES_ORDER,
    ENTITY_PURCHASE_ORDER,
    ENTITY_SHIPPING_ORDER,
    ENTITY_GOODS_RECEIVED_NOTE,
    # sprint-5/08 (AC-08-31) - a DB task may feed `brand` too (the open REST
    # API is not the only source), so it joins the DB-extractable catalogue.
    ENTITY_BRAND,
)

# ── schedule floors (AC-22-12, Q17) ──────────────────────────────────────────
MIN_INCREMENTAL_MINUTES = 1
MIN_INCREMENTAL_MINUTES_NO_WATERMARK = 15
MIN_RECONCILE_HOURS = 1
RECONCILE_MODE_INTERVAL = "interval"
RECONCILE_MODE_DAILY_AT = "dailyAt"
RECONCILE_MODES = (RECONCILE_MODE_INTERVAL, RECONCILE_MODE_DAILY_AT)
DEFAULT_INCREMENTAL_MINUTES = 15
DEFAULT_RECONCILE_AT = "02:00"

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_QUERY_HEAD = 120


class EtlValidationError(AutocountServiceError):
    """A task save rejected per field (AC-22-11) - the HTTP layer renders
    ``422 {fieldErrors}``."""

    def __init__(self, field_errors: Dict[str, str]):
        super().__init__("The task could not be saved. Fix the highlighted fields.")
        self.field_errors = field_errors


@dataclass(frozen=True)
class SqlConnectionView:
    """Flat + snake-free on purpose: the wire names ARE these names."""

    id: str
    name: str
    dialect: str
    database: str


@dataclass(frozen=True)
class SqlSchemaView:
    connection_id: str
    dialect: str
    database: str
    tree: SqlSchemaTree


class EtlStateError(AutocountServiceError):
    """The task is not in a state where this action makes sense (409).

    Deliberately NOT a 422: the request is well-formed, the TASK is simply
    somewhere else (already active, never previewed, a run still in flight).
    ``running_run_id`` is set on the in-flight case so the surface can link
    straight to the run rather than telling the operator to go hunt for it.
    """

    def __init__(self, message: str, *, running_run_id: Optional[str] = None):
        super().__init__(message)
        self.running_run_id = running_run_id


class PreviewUnavailable(AutocountServiceError):
    """The dry run itself failed (a transport / contract fault talking to the
    consumer). The gate must SHOW this and refuse to offer Activate - nobody
    activates blind. Nothing was written either way.

    ``message`` is what the operator reads (the router's 502 ``detail``): the
    generic sentence PLUS what the consumer said (``Consumer said: HTTP <n>
    <snippet>``) or why it could not be reached (``Consumer unreachable:
    <ExcClass>: <text>``). ``status_code`` / ``consumer_detail`` keep the
    parts separately for logs and tests. Prod 2026-09-06: the fixed sentence
    alone left the operator no way to tell a 504 from an unknown SO failure.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        consumer_detail: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.consumer_detail = consumer_detail


class EtlAnchorError(AutocountServiceError):
    """Sorento could not resolve the company anchor (Appendix A6/A7).

    A TASK-level configuration fault carrying its code, never a per-record
    failure - the records are fine, the company wiring is not.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class EtlTaskView:
    company_id: str
    entity_type: str
    etl_status: str
    activated_at: Optional[datetime]
    source_config: Dict[str, Any] = field(default_factory=dict)
    # sprint-5/08 (AC-08-30) - which fetch implementation this task saves as
    # (``sql_db`` | ``autocount_http``). Defaults to ``sql_db`` for a
    # never-configured entity (the editor's own create-time default).
    source_impl: str = SOURCE_IMPL_SQL_DB
    # ── read-only task state (plan 22 S2, all stamped server-side) ───────────
    # The SAVED query's result column names, from the validation preview every
    # PUT runs - so the Mapping tab offers them without re-running the query.
    result_columns: List[str] = field(default_factory=list)
    # The SAVED lineQuery's result columns (sprint-5/02, AC-02-06) - the
    # Mapping tab's Line-fields source picker + save-time gate. Empty until
    # the line query has previewed clean at least once.
    line_result_columns: List[str] = field(default_factory=list)
    # The activate-once gate (AC-22-18). CLEARED by every config save: a
    # preview of a superseded query must never unlock Activate.
    last_preview_at: Optional[datetime] = None
    # The last preview's genuinely-``failed`` count (S5 review SHOULD-FIX 4b) -
    # NOT ``retryable`` (a legitimate dependency-order carry-over stays fine).
    # ``activate_task`` refuses while this is truthy.
    last_preview_failed_count: Optional[int] = None
    last_run_at: Optional[datetime] = None
    last_run_error: Optional[str] = None
    last_run_error_code: Optional[str] = None
    # ── schedule (plan 22 S3, AC-22-12/13) ───────────────────────────────────
    next_incremental_at: Optional[datetime] = None
    next_reconcile_at: Optional[datetime] = None
    # ── continuation (plan sprint-5/03 S1/S4, AC-03-03/21) ───────────────────
    initial_load: Optional[Dict[str, Any]] = None
    # sprint-5/08 (AC-08-33/AC-08-20 S5) - non-null ONLY for a `brand` task on
    # a Sorento-sink company whose consumer does not yet accept brands:
    # ``{"version": <float|None>, "requiredVersion": 2.3}``. Drives the
    # Review & Activate banner ("Consumer contract 2.2 - brands land when 2.3
    # is deployed") without the operator having to run Preview first.
    brand_contract_gate: Optional[Dict[str, Any]] = None


@dataclass
class EtlRepushView:
    """``repush_task``'s result (plan sprint-5/07, AC-07-13..19) - deliberately
    NOT an `EtlTaskView`: the route clears change tracking only, it does not
    return the whole task."""

    cleared_count: int
    next_reconcile_at: Optional[datetime]
    status: str


def default_source_config(entity_type: str, *, today: Optional[date] = None) -> Dict[str, Any]:
    """The draft a never-configured entity starts from (the editor is the
    create surface). Documents get today's from-date + a line-query slot +
    the S5 line/ref column slots (all null until the operator picks them)."""
    document = is_document_entity(entity_type)
    return {
        "connectionId": None,
        "query": "",
        "lineQuery": "" if document else None,
        "keyColumns": [],
        "watermarkColumn": None,
        "comparedColumns": [],
        "fromDate": (today or date.today()).isoformat() if document else None,
        "docDateColumn": None,
        # sprint-5/02 (AC-02-11) - a document task's optional header filter,
        # authored ONLY via the AutocountFormulaBuilder (never a free-text
        # field). The three line/ref column pickers this slot used to sit
        # beside (`lineKeyColumn`/`lineProductColumn`/`lineWarehouseColumn`)
        # are GONE - a document's line fields are persisted `ac_field_mapping`
        # rows now (AC-02-01), not source_config picks.
        "filterFormula": None,
        "incrementalMinutes": DEFAULT_INCREMENTAL_MINUTES,
        "reconcileMode": RECONCILE_MODE_DAILY_AT,
        "reconcileHours": None,
        "reconcileAt": DEFAULT_RECONCILE_AT,
    }


def default_http_source_config() -> Dict[str, Any]:
    """The draft an ``autocount_http`` task starts from - the OWN shape
    (sprint-5/08, AC-08-30): never merged onto ``default_source_config``'s
    SQL keys, so a never-saved SQL key (``query``/``keyColumns``/...) never
    round-trips onto an HTTP task's wire config."""
    return {
        "connectionId": None,
        "path": "",
        "keyFields": [],
        "watermarkField": None,
        "comparedFields": [],
        "distinctOf": None,
        "incrementalMinutes": DEFAULT_INCREMENTAL_MINUTES,
        "reconcileMode": RECONCILE_MODE_DAILY_AT,
        "reconcileHours": None,
        "reconcileAt": DEFAULT_RECONCILE_AT,
    }


def _clean_list(value: Any) -> List[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: List[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _clean_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


# A document task's row-hash population (`ac_row_hash`) is a diff baseline
# for the *exact* set of headers `query`+`fromDate`+`filterFormula` can ever
# return. Narrowing any of these (or `keyColumns`, which changes what a hash
# row's own identity even means) makes a header that merely fell OUT of the
# new, narrower scope look identical - to the next reconcile's `known -
# current_refs` diff - to one AutoCount genuinely deleted (F1, sprint-5/02
# review round). Schedule-only fields (interval/reconcile timing) never
# change what the task's population IS, so they are deliberately excluded -
# clearing hashes on every save would defeat the whole point of reconcile
# (every save would re-add everything as a fresh "ADD", masking real edits).
POPULATION_DEFINING_KEYS = frozenset(
    {"fromDate", "query", "lineQuery", "keyColumns", "filterFormula"}
)


def validate_source_config(
    entity_type: str,
    raw: Dict[str, Any],
    columns: Optional[Dict[str, str]],
    *,
    line_columns: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Normalise + validate a task's ``source_config`` (AC-22-11/12).

    ``columns`` = ``{name: type}`` from a FRESH preview of ``query`` (None when
    no preview exists - blank query / no connection). Column picks are checked
    against it; a pick with no preview to check against is an error on the
    query, not a silent accept.

    ``line_columns`` (plan 22 S5, documents only) - the SAME shape from a
    FRESH preview of ``lineQuery`` (a sample ``:doc_key`` bound). Accepted for
    call-site compatibility with ``EtlService.update_task`` (which still
    stores it on the task as ``line_result_columns``, AC-02-06); no longer
    used to validate the removed line/ref column pickers (sprint-5/02,
    AC-02-05 - a document's line fields are persisted ``ac_field_mapping``
    rows now, validated by ``CompanyService.replace_mapping``, not here).

    Returns ``(clean, field_errors)``. Pure - no DB, no source. The caller
    (``EtlService.update_task``) resolves the connection, runs both previews
    and guards both queries itself, then merges its own errors in.
    """
    errors: Dict[str, str] = {}
    document = is_document_entity(entity_type)

    connection_id = str(raw.get("connectionId") or "").strip() or None
    query = normalize_statement(str(raw.get("query") or ""))
    line_query_raw = raw.get("lineQuery")
    line_query = normalize_statement(str(line_query_raw or "")) if document else None
    key_columns = _clean_list(raw.get("keyColumns"))
    watermark = str(raw.get("watermarkColumn") or "").strip() or None
    compared = _clean_list(raw.get("comparedColumns"))

    #     !!  BL-SS-087 - THE WATERMARK COLUMN CAN NEVER DOUBLE AS A KEY
    #         COLUMN.  !!
    # A value that is GUARANTEED to change on every update (that is the
    # entire point of a watermark) can never also be part of what makes a
    # row the "same" row - a task saved with keyColumns=["AutoKey",
    # "LastModified"] mints a "new" ref on every reconcile for the same
    # real-world record (the ac_sim ref-drift finding). Checked unconditional
    # of whether the query has ever previewed - this is a pure config-shape
    # defect, not a column-existence question.
    if watermark is not None and watermark in key_columns:
        errors["keyColumns"] = (
            "The watermark column cannot be part of the key - refs would "
            "change on every update."
        )

    # ── columns vs the fresh preview ─────────────────────────────────────────
    picked = bool(key_columns or watermark or compared)
    if picked and columns is None:
        errors["query"] = "Test a query first - the picked columns are checked against its result."
    elif columns is not None:
        missing = [c for c in key_columns if c not in columns]
        if missing:
            errors["keyColumns"] = f"Not in the query result: {', '.join(missing)}."
        if watermark is not None:
            if watermark not in columns:
                errors["watermarkColumn"] = f"'{watermark}' is not in the query result."
            elif not is_orderable_type(columns[watermark]):
                errors["watermarkColumn"] = (
                    f"'{watermark}' is {columns[watermark]} - the watermark must be a "
                    f"date/time or numeric column."
                )
        missing = [c for c in compared if c not in columns]
        if missing:
            errors["comparedColumns"] = f"Not in the query result: {', '.join(missing)}."
    # Compared columns never include a key (a key change is a new record).
    compared = [c for c in compared if c not in key_columns]

    # ── documents: line query + from-date + filter formula (S5, sprint-5/02) ─
    from_date: Optional[str] = None
    doc_date_column: Optional[str] = None
    fingerprint_query: Optional[str] = None
    # Never blank-required (a document with no filter simply stages every
    # header, today's behaviour).
    filter_formula = str(raw.get("filterFormula") or "").strip() or None
    if document and filter_formula:
        #     !!  A FILTER FORMULA MUST PARSE AGAINST WHAT IT WILL RUN OVER.  !!
        # (F2/B3, sprint-5/02 review round - the security review's SHOULD-FIX
        # F2 and the code review's B3.) `evaluate_row_filter` used to fail
        # OPEN silently on any parse error, citing THIS check as the reason
        # it was safe to - except this check never existed, so an
        # unparseable or unknown-variable filter saved clean and silently
        # kept every header, forever, with no visible sign the PO/SPO split
        # (or any other filter) was disabled. Parsed here with the SAME
        # fold-matched known-variable set `evaluate_row_filter` resolves at
        # run time (`known_filter_variables`), so a save-time PASS here is a
        # genuine guarantee the run-time filter can resolve every name it
        # references.
        if columns is None:
            errors["filterFormula"] = (
                "Test a query first - the filter is checked against its result."
            )
        else:
            try:
                parse_formula(filter_formula, known_filter_variables(filter_formula, columns))
            except FormulaError as exc:
                errors["filterFormula"] = str(exc)
    if document:
        raw_from = str(raw.get("fromDate") or "").strip()
        if not raw_from:
            errors["fromDate"] = "A from-date is required for documents."
        else:
            try:
                from_date = date.fromisoformat(raw_from).isoformat()
            except ValueError:
                errors["fromDate"] = "Enter the from-date as YYYY-MM-DD."

        #     !!  A DOCUMENT TASK REQUIRES A HEADER WATERMARK COLUMN.  !!
        # This is the S5 line-change-detection decision: AutoCount stamps a
        # SO/PO header's `LastModified` on ANY line edit (add/change/remove a
        # detail row), so "the header changed" IS "a line may have changed" -
        # reconcile can diff HEADER hashes only and never re-fetch every
        # document's lines to notice a line-only edit. Without a watermark
        # column there is no honest way to detect a line-only change short of
        # re-fetching every document's lines on every run, which defeats the
        # whole point of the per-header line query. Validated here (save-time
        # 422), not discovered at run-time.
        if not watermark:
            errors["watermarkColumn"] = (
                "A watermark column is required for documents - AutoCount "
                "updates a header's LastModified whenever a line changes, "
                "which is how a line-only edit is detected."
            )

        if not line_query:
            errors["lineQuery"] = "A line query is required for documents."
        else:
            try:
                assert_select_only(line_query)
            except SqlGuardError as exc:
                errors["lineQuery"] = exc.message
            else:
                #     !!  THE LINE QUERY MUST FILTER ON :doc_key.  !!
                # (S5 review BLOCKER 1.) It runs once PER header, bound to
                # that header's key - a query with no such WHERE clause
                # previews and saves clean (SQLAlchemy silently ignores an
                # unused param), then attaches the WHOLE line table to EVERY
                # header at run time. Checked via the same compiler
                # ``sa.text()`` uses at execution, never a substring search.
                if not query_binds_param(line_query, LINE_QUERY_DOC_KEY_PARAM):
                    errors["lineQuery"] = (
                        "The line query must filter on the header's key via "
                        f"WHERE ... = :{LINE_QUERY_DOC_KEY_PARAM} - it runs once "
                        "per header, bound to that header's key, never the "
                        "whole table."
                    )

        # feat/line-fingerprint-sweep - the fingerprint query, same
        # stored-verbatim contract as `query`/`lineQuery` (normalised,
        # SELECT-only guarded). Optional: a document task with no
        # fingerprint query simply never sweeps (the plain watermark path is
        # unaffected) - never required to activate.
        raw_fingerprint = normalize_statement(str(raw.get("fingerprintQuery") or ""))
        if raw_fingerprint:
            try:
                assert_select_only(raw_fingerprint)
            except SqlGuardError as exc:
                errors["fingerprintQuery"] = exc.message
            else:
                fingerprint_query = raw_fingerprint

        # The from-date floor applies to the document's OWN date column -
        # deliberately separate from `watermarkColumn` (LastModified drives
        # change detection, not how far back the sync looks).
        doc_date_column = str(raw.get("docDateColumn") or "").strip() or None
        if doc_date_column is None:
            errors.setdefault("docDateColumn", "Choose the document's date column.")
        elif columns is not None and doc_date_column not in columns:
            errors.setdefault(
                "docDateColumn", f"'{doc_date_column}' is not in the query result."
            )

    # ── schedule floors (AC-22-12) ───────────────────────────────────────────
    minutes = _clean_int(raw.get("incrementalMinutes"))
    floor = MIN_INCREMENTAL_MINUTES if watermark else MIN_INCREMENTAL_MINUTES_NO_WATERMARK
    if minutes is None:
        errors["incrementalMinutes"] = "Enter the incremental interval in minutes."
        minutes = DEFAULT_INCREMENTAL_MINUTES
    elif minutes < floor:
        errors["incrementalMinutes"] = (
            f"At least {floor} minute{'s' if floor != 1 else ''}"
            + (" without a watermark column." if not watermark else ".")
        )

    mode = str(raw.get("reconcileMode") or "").strip()
    hours: Optional[int] = None
    at: Optional[str] = None
    if mode not in RECONCILE_MODES:
        errors["reconcileMode"] = "Choose how to reconcile: every N hours or daily at a time."
        mode = RECONCILE_MODE_DAILY_AT
    elif mode == RECONCILE_MODE_INTERVAL:
        hours = _clean_int(raw.get("reconcileHours"))
        if hours is None:
            errors["reconcileHours"] = "Enter the reconcile interval in hours."
        elif hours < MIN_RECONCILE_HOURS:
            errors["reconcileHours"] = f"At least {MIN_RECONCILE_HOURS} hour."
    else:
        at = str(raw.get("reconcileAt") or "").strip() or None
        if at is None or not _TIME_RE.match(at):
            errors["reconcileAt"] = "Enter the daily reconcile time as HH:MM."

    clean = {
        "connectionId": connection_id,
        "query": query,
        "lineQuery": line_query if document else None,
        "keyColumns": key_columns,
        "watermarkColumn": watermark,
        "comparedColumns": compared,
        "fromDate": from_date if document else None,
        "docDateColumn": doc_date_column if document else None,
        "filterFormula": filter_formula if document else None,
        "fingerprintQuery": fingerprint_query if document else None,
        "incrementalMinutes": minutes,
        "reconcileMode": mode,
        "reconcileHours": hours,
        "reconcileAt": at,
    }
    return clean, errors


_PREVIEW_FAILED = (
    "The dry run against the consumer failed, so no prediction is available "
    "and this task cannot be activated yet. Nothing was written - resolve the "
    "consumer error first."
)


def _preview_unavailable(
    exc: BaseException, *, sink: Any, company_id: str, entity_type: str
) -> PreviewUnavailable:
    """Build the operator-facing ``PreviewUnavailable`` for a failed dry run
    and log it (WARNING, one line, with the parts a follow-up needs). The
    wording of the consumer line is ``sinks_sorento.describe_consumer_failure``
    - shared with the approve gate (``SyncService``) so both say the same
    thing. Imported lazily like every other ``sinks_sorento`` use in this
    module."""
    from ..sinks_sorento import describe_consumer_failure

    line, status, detail = describe_consumer_failure(exc, sink=sink)
    logger.warning(
        "autocount preview dry run failed: company_id=%s entity_type=%s status=%s detail=%s",
        company_id, entity_type, status, detail,
    )
    return PreviewUnavailable(
        f"{_PREVIEW_FAILED} {line}", status_code=status, consumer_detail=detail
    )


class EtlService:
    def __init__(
        self,
        db: Session,
        *,
        runtime: SqlSourceRuntime = RUNTIME,
        cache: SchemaCache = SCHEMA_CACHE,
    ):
        self.db = db
        self.runtime = runtime
        self.cache = cache
        self.connections = ConnectionRepository(db)
        self.configs = EntityConfigRepository(db)
        self.companies = CompanyService(db)

    # ── connections ──────────────────────────────────────────────────────────

    def list_connections(self, tenant_id: str) -> List[SqlConnectionView]:
        return [
            self._connection_view(conn)
            for conn in self.connections.list_for_provider(tenant_id, SQL_DATABASE_PROVIDER_KEY)
        ]

    def _connection(self, tenant_id: str, connection_id: str) -> Connection:
        """Tenant- AND provider-scoped. A stored/posted connection id resolved
        unscoped is the polymorphic-target_id leak class (AC-22-29)."""
        conn = self.connections.get_for_provider(
            tenant_id, connection_id, SQL_DATABASE_PROVIDER_KEY
        )
        if conn is None:
            raise ConnectionNotFound("That SQL connection was not found.")
        return conn

    @staticmethod
    def _connection_view(conn: Connection) -> SqlConnectionView:
        config = conn.config_json or {}
        return SqlConnectionView(
            id=conn.id,
            name=conn.name,
            dialect=str(config.get("dbType", "")),
            database=str(config.get("database", "")),
        )

    @staticmethod
    def _credentials(conn: Connection) -> Dict[str, Any]:
        if not conn.credentials_json:
            return {}
        try:
            return decrypt_secret(conn.credentials_json)
        except InvalidToken as exc:
            raise AutocountServiceError(
                "This connection's stored credentials can no longer be decrypted. "
                "Re-enter the database password."
            ) from exc

    def _engine(self, conn: Connection):
        config = conn.config_json or {}
        credentials = self._credentials(conn)
        return self.runtime.engine_for(conn.id, config, credentials), secrets_of(config, credentials)

    # ── schema (AC-22-05) ────────────────────────────────────────────────────

    def schema(self, tenant_id: str, connection_id: str, *, refresh: bool = False) -> SqlSchemaView:
        conn = self._connection(tenant_id, connection_id)
        engine, secrets = self._engine(conn)
        config = conn.config_json or {}
        database = str(config.get("database", ""))

        def load() -> SqlSchemaTree:
            return introspect_schema(engine, database=database, secrets=secrets)

        # Cache key = the connection id; a rebuilt engine (edited config) is a
        # different fingerprint in the runtime but the same key here - an edit
        # that matters is followed by the editor's Refresh, never per keystroke.
        tree = self.cache.get(f"{tenant_id}:{conn.id}", load, refresh=refresh)
        return SqlSchemaView(
            connection_id=conn.id,
            dialect=str(config.get("dbType", "")),
            database=database,
            tree=tree,
        )

    # ── preview (AC-22-06) ───────────────────────────────────────────────────

    def preview(
        self,
        tenant_id: str,
        connection_id: str,
        query: str,
        *,
        bind_doc_key: bool = False,
        doc_key: Optional[str] = None,
    ) -> PreviewResult:
        """Run a candidate SELECT capped at 100 rows (AC-22-06).

        ``bind_doc_key`` (plan 22 S5) - a document's ``lineQuery`` carries a
        ``:doc_key`` bound param; ``True`` binds ``doc_key`` (even a blank
        sample - never real filtered data at picker-config time - is enough
        to let the query EXECUTE at all so its result COLUMNS can populate
        the line-column pickers). ``False`` runs the query driver-native
        exactly as before - a SEPARATE flag from the value itself, because an
        ordinary header-query preview also carries no ``doc_key`` and must
        NOT be treated as parameterized (a bare `None` would be ambiguous
        between the two).
        """
        conn = self._connection(tenant_id, connection_id)
        # Guard BEFORE anything touches the source (AC-22-03) - and before the
        # engine is even built.
        assert_select_only(query)
        engine, secrets = self._engine(conn)
        params = {"doc_key": doc_key} if bind_doc_key else None
        try:
            result = run_preview(engine, query, secrets=secrets, params=params)
        except SqlSourceError as exc:
            self._record_preview(tenant_id, conn, query, status=ACTIVITY_ERROR, error=exc.message)
            raise
        self._record_preview(
            tenant_id,
            conn,
            query,
            status=ACTIVITY_SUCCESS,
            latency_ms=result.duration_ms,
            response={"rowCount": result.row_count, "truncated": result.truncated},
        )
        return result

    def _record_preview(
        self,
        tenant_id: str,
        conn: Connection,
        query: str,
        *,
        status: str,
        error: Optional[str] = None,
        latency_ms: Optional[int] = None,
        response: Optional[Dict[str, Any]] = None,
    ) -> None:
        """One Developer-Logs row per preview: dialect, a SANITISED head of the
        SQL (tenant data - never the whole text), outcome. Never raises, and
        sits at a transaction boundary (no pending writes during a preview)."""
        head = normalize_statement(query)[:_QUERY_HEAD]
        record_activity(
            self.db,
            tenant_id=tenant_id,
            operation="sql preview",
            status=status,
            external_ref=conn.id,
            latency_ms=latency_ms,
            error_message=error,
            request={"dialect": str((conn.config_json or {}).get("dbType", "")), "sql": head},
            response=response,
        )

    # ── open REST API (sprint-5/08, AC-08-14/15) ─────────────────────────────

    def list_http_connections(self, tenant_id: str) -> List[Connection]:
        """Every tenant ``autocount`` connection, BOTH auths (AC-08-15) - the
        Source tab's API picker badges each option from this. Tenant-scoped;
        the router projects the wire shape (auth is derived, not a column)."""
        return self.connections.list_for_provider(tenant_id, PROVIDER_KEY)

    def preview_http(
        self,
        tenant_id: str,
        connection_id: str,
        path: str,
        *,
        distinct_of: Optional[List[str]] = None,
        company_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        transport: Any = None,
    ):
        """One page-1 sample against an OPEN connection (AC-08-14).

        ``connectionId`` is tenant- AND provider-scoped and must be a no-auth
        connection - a vendor/SQL id is a 422 naming ``connectionId``, never a
        404 (the id may be perfectly real, just not usable here). When both
        ``company_id``/``entity_type`` are given, a clean result also stamps
        ``result_columns``/``last_preview_at`` on the task, tenant-scoped.

        ``transport``, when given, is a FULL ``httpx.Client`` used AS-IS
        (house convention - see ``probe_open_connection``) - production
        never passes one (a real network call); the router injects a stub
        ONLY via the ``get_http_transport`` dependency override, so a test
        exercising the real ``POST /autocount/http/preview`` route never
        reaches ``hapi.sorento.cc.cd`` (sprint-5/08 review round 1, B4).
        """
        conn = self.connections.get_for_provider(tenant_id, connection_id, PROVIDER_KEY)
        if conn is None or auth_mode(conn.config_json or {}) != AUTH_NONE:
            raise EtlValidationError(
                {"connectionId": "Choose an open (no-auth) AutoCount API connection."}
            )
        base_url = str((conn.config_json or {}).get("baseUrl") or "").strip()
        path_error = validate_http_path(path)
        if path_error:
            raise EtlValidationError({"path": path_error})
        try:
            result = run_http_preview(
                base_url, path, distinct_of=distinct_of, transport=transport
            )
        except HttpPreviewError as exc:
            raise EtlValidationError({exc.field: exc.message}) from exc

        if company_id and entity_type:
            self.companies.get(tenant_id, company_id)  # tenant-scope guard
            config = self.configs.get(tenant_id, company_id, entity_type)
            if config is not None:
                config.result_columns = list(result.columns)
                config.last_preview_at = datetime.now(timezone.utc)
                self.db.commit()
        return result

    # ── task (AC-22-11) ──────────────────────────────────────────────────────

    def _require_task_entity(self, tenant_id: str, company_id: str, entity_type: str):
        company = self.companies.get(tenant_id, company_id)  # CompanyNotFound
        if entity_type not in ETL_ENTITY_TYPES:
            raise EntityConfigNotFound(
                f"'{entity_type}' is not an entity a database task can extract."
            )
        return company

    def get_task(self, tenant_id: str, company_id: str, entity_type: str) -> EtlTaskView:
        self._require_task_entity(tenant_id, company_id, entity_type)
        config = self.configs.get(tenant_id, company_id, entity_type)
        return self._task_view(company_id, entity_type, config, tenant_id=tenant_id)

    def _task_view(
        self,
        company_id: str,
        entity_type: str,
        config: Optional[AcEntityConfig],
        *,
        tenant_id: Optional[str] = None,
    ) -> EtlTaskView:
        source_impl = (
            (config.source_impl if config is not None else None) or SOURCE_IMPL_SQL_DB
        )
        # Stored keys win; new keys fall back to the draft defaults so an
        # older document always round-trips whole. An HTTP task starts from
        # its OWN defaults (AC-08-30) - never the SQL shape's keys, so a
        # stray SQL key never round-trips onto an HTTP task's wire config.
        merged = (
            default_http_source_config()
            if source_impl == SOURCE_IMPL_AUTOCOUNT_HTTP
            else default_source_config(entity_type)
        )
        if config is not None and isinstance(config.source_config, dict):
            merged.update(config.source_config)
        return EtlTaskView(
            company_id=company_id,
            entity_type=entity_type,
            etl_status=(config.etl_status if config is not None else None) or ETL_STATUS_DRAFT,
            activated_at=config.activated_at if config is not None else None,
            source_config=merged,
            source_impl=source_impl,
            result_columns=[
                str(c) for c in ((config.result_columns if config is not None else None) or [])
            ],
            line_result_columns=[
                str(c)
                for c in ((config.line_result_columns if config is not None else None) or [])
            ],
            last_preview_at=config.last_preview_at if config is not None else None,
            last_preview_failed_count=(
                config.last_preview_failed_count if config is not None else None
            ),
            last_run_at=config.last_run_at if config is not None else None,
            last_run_error=config.last_run_error if config is not None else None,
            last_run_error_code=(
                config.last_run_error_code if config is not None else None
            ),
            next_incremental_at=(
                config.next_incremental_at if config is not None else None
            ),
            next_reconcile_at=(
                config.next_reconcile_at if config is not None else None
            ),
            initial_load=self._initial_load(company_id, entity_type, config),
            brand_contract_gate=self._brand_contract_gate(tenant_id, company_id, entity_type),
        )

    def _brand_contract_gate(
        self, tenant_id: Optional[str], company_id: str, entity_type: str
    ) -> Optional[Dict[str, Any]]:
        """AC-08-33/AC-08-20 S5 - gated to `brand` only, so the overwhelming
        majority of task-view reads (every other entity) never touch the
        network here. `tenant_id` absent (no call site should ever omit it,
        but the keyword stays optional so an unrelated future caller of
        `_task_view` cannot be forced to thread one through) reads as "not
        provable", same as an unreachable consumer."""
        if entity_type != ENTITY_BRAND or tenant_id is None:
            return None
        try:
            company = self.companies.get(tenant_id, company_id)
        except Exception:  # noqa: BLE001 - advisory only, never blocks the read
            return None
        return self.companies.brand_contract_gate(tenant_id, company)

    def _initial_load(
        self, company_id: str, entity_type: str, config: Optional[AcEntityConfig]
    ) -> Optional[Dict[str, Any]]:
        """The paged pass in progress, if any (plan sprint-5/03, AC-03-21) -
        derived straight from ``AcWatermark.cursor_json["pass"]``, never a
        second source of truth. A task never configured (or a company whose
        watermark row was never created because it has never run) has none.
        """
        if config is None:
            return None
        watermark = WatermarkRepository(self.db).get(config.tenant_id, company_id, entity_type)
        if watermark is None:
            return None
        cursor = watermark.cursor_json if isinstance(watermark.cursor_json, dict) else {}
        pass_state = cursor.get("pass")
        # ``None`` once no pass is OPEN (AC-03-21) - never configured, a
        # guard failure cleared it, or the last one simply completed. The
        # underlying ``cursor_json.pass.complete`` flag is left ``true``
        # rather than removed (``sync.py``'s run loop) so a later run of the
        # SAME mode is provably starting a FRESH pass, not resuming a
        # finished one - this is just the second reader of that one flag.
        if not isinstance(pass_state, dict) or pass_state.get("complete"):
            return None
        return {
            "complete": bool(pass_state.get("complete")),
            "pagesDone": int(pass_state.get("pagesDone") or 0),
            # Scoped to the pass itself, not the shared top-level cursor
            # mark (``sync.py``'s run loop writes both) - a stale mark left
            # by a DIFFERENT, already-finished pass kind must never read as
            # this pass's progress.
            "lastMark": pass_state.get("mark"),
            "kind": pass_state.get("kind"),
        }

    def _probe_incremental_wrap(
        self, engine, secrets: List[str], query: str, watermark_column: str
    ) -> None:
        """Execute the ACTUAL runtime statement shape once, capped, read-only
        (S2 review BLOCKER 2).

        ``SqlDbSource`` always runs an incremental (or mark-less initial)
        fetch as a derived-table wrap (``build_incremental_wrap`` - the SAME
        function, so this probes exactly what a real run would send). The
        ORDER-BY-stripping fix closes the one KNOWN-bad shape; this probe is
        the safety net for whatever it does not cover (an unaliased
        ``COUNT(*)`` or a duplicate column name - MSSQL error 8155, a query
        paired with ``OFFSET``/``FETCH`` we deliberately leave un-stripped) -
        so a wrap-incompatible query is a 422 on SAVE, never a run-time
        surprise the first time the task actually fires. Capped to 1 row via
        the SAME per-dialect rewriter the query preview uses (``wrap_preview``)
        so validating a huge table costs a bounded fetch, not a full extract.
        A dedicated method (not inlined) so a test can stub it without a real
        MSSQL/MySQL driver.
        """
        quoted = engine.dialect.identifier_preparer.quote(watermark_column)
        probe_sql = wrap_preview(
            build_incremental_wrap(query, quoted, None), engine.dialect.name, 1
        )
        with open_readonly(engine, timeout_s=QUERY_TIMEOUT_SECONDS, secrets=secrets) as conn:
            conn.execute(sa.text(probe_sql)).close()

    def _probe_document_wrap(
        self,
        engine,
        secrets: List[str],
        query: str,
        watermark_column: str,
        doc_date_column: str,
    ) -> None:
        """Document counterpart of ``_probe_incremental_wrap`` (S6 review
        SHOULD-FIX 3).

        A document task's real run NEVER executes ``build_incremental_wrap``
        - ``SqlDbSource._statement`` always builds ``build_document_header_wrap``
        for a document entity (the SAME derived-table wrap PLUS the always-on
        ``fromDate`` floor on ``docDateColumn``, plan 22 S5). Probing the
        plain shape at save time proves nothing about the shape that will
        actually run - a header query whose SELECT list survives the simple
        wrap can still be rejected once the date predicate/column joins it
        (an ambiguous/duplicate column the date comparison now touches, for
        instance). So a document entity is probed with THIS exact shape,
        mark-less (matching an initial load), with a harmless SAMPLE
        ``:from_date`` (today - never real data) bound the same way the real
        run binds it. Capped to 1 row via the SAME per-dialect
        ``wrap_preview`` rewriter the plain probe and the query preview use.
        """
        quoted_watermark = engine.dialect.identifier_preparer.quote(watermark_column)
        quoted_date = engine.dialect.identifier_preparer.quote(doc_date_column)
        probe_sql = wrap_preview(
            build_document_header_wrap(query, quoted_watermark, quoted_date, None),
            engine.dialect.name,
            1,
        )
        with open_readonly(engine, timeout_s=QUERY_TIMEOUT_SECONDS, secrets=secrets) as conn:
            conn.execute(sa.text(probe_sql), {"from_date": date.today()}).close()

    # ── HTTP task (sprint-5/08, AC-08-12/13/16/28/30) ─────────────────────────

    def _validate_http_config(
        self,
        tenant_id: str,
        raw: Dict[str, Any],
        *,
        existing_result_columns: Optional[List[str]],
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        """Normalise + validate an ``autocount_http`` task's ``source_config``
        (AC-08-13). ONE envelope with the SQL shape - a stray SQL key on the
        raw payload is simply not copied into ``clean`` (dropped, never a
        422). ``existing_result_columns`` is the task's CURRENT stored
        ``result_columns`` (from the last ``/autocount/http/preview`` call
        that named this task) - ``None`` when it has never been previewed,
        in which case key/watermark picks are accepted un-checked (nothing
        to check against yet) rather than refused.
        """
        errors: Dict[str, str] = {}

        connection_id = str(raw.get("connectionId") or "").strip() or None
        if connection_id:
            conn = self.connections.get_for_provider(tenant_id, connection_id, PROVIDER_KEY)
            if conn is None or auth_mode(conn.config_json or {}) != AUTH_NONE:
                errors["connectionId"] = (
                    "Choose an open (no-auth) AutoCount API connection of this tenant."
                )
                connection_id = None
        else:
            errors["connectionId"] = "Choose an open (no-auth) AutoCount API connection."

        path = str(raw.get("path") or "").strip()
        if not path:
            errors["path"] = "Enter the endpoint path."
        else:
            # S4 (sprint-5/08 review round 1) - the SAME rule set the
            # preview route now applies (``validate_http_path``), so a path
            # can never pass save-time validation and then fail differently
            # (or not at all) against the preview endpoint.
            path_error = validate_http_path(path)
            if path_error:
                errors["path"] = path_error

        key_fields = _clean_list(raw.get("keyFields"))
        distinct_of = _clean_list(raw.get("distinctOf")) or None
        if not key_fields:
            errors["keyFields"] = "Choose at least one key field."
        elif distinct_of and key_fields != ["value"]:
            errors["keyFields"] = (
                "A distinct-values field can only key on 'value'."
            )
        elif existing_result_columns is not None:
            missing = [c for c in key_fields if c not in existing_result_columns]
            if missing:
                errors["keyFields"] = (
                    f"Not in the last preview: {', '.join(missing)}. Test the "
                    f"endpoint first."
                )

        watermark_field = str(raw.get("watermarkField") or "").strip() or None
        if (
            watermark_field
            and existing_result_columns is not None
            and watermark_field not in existing_result_columns
        ):
            errors["watermarkField"] = f"'{watermark_field}' is not in the last preview."

        configured_compared = _clean_list(raw.get("comparedFields"))
        compared_fields = compared_columns_for(
            configured=configured_compared,
            result_columns=existing_result_columns or configured_compared,
            key_columns=key_fields,
        )

        # ── schedule floors (AC-22-12, reused verbatim) ──────────────────────
        minutes = _clean_int(raw.get("incrementalMinutes"))
        floor = (
            MIN_INCREMENTAL_MINUTES if watermark_field else MIN_INCREMENTAL_MINUTES_NO_WATERMARK
        )
        if minutes is None:
            errors["incrementalMinutes"] = "Enter the incremental interval in minutes."
            minutes = DEFAULT_INCREMENTAL_MINUTES
        elif minutes < floor:
            errors["incrementalMinutes"] = (
                f"At least {floor} minute{'s' if floor != 1 else ''}"
                + (" without a watermark field." if not watermark_field else ".")
            )

        mode = str(raw.get("reconcileMode") or "").strip()
        hours: Optional[int] = None
        at: Optional[str] = None
        if mode not in RECONCILE_MODES:
            errors["reconcileMode"] = "Choose how to reconcile: every N hours or daily at a time."
            mode = RECONCILE_MODE_DAILY_AT
        elif mode == RECONCILE_MODE_INTERVAL:
            hours = _clean_int(raw.get("reconcileHours"))
            if hours is None:
                errors["reconcileHours"] = "Enter the reconcile interval in hours."
            elif hours < MIN_RECONCILE_HOURS:
                errors["reconcileHours"] = f"At least {MIN_RECONCILE_HOURS} hour."
        else:
            at = str(raw.get("reconcileAt") or "").strip() or None
            if at is None or not _TIME_RE.match(at):
                errors["reconcileAt"] = "Enter the daily reconcile time as HH:MM."

        clean = {
            "connectionId": connection_id,
            "path": path,
            "keyFields": key_fields,
            "watermarkField": watermark_field,
            "comparedFields": compared_fields,
            "distinctOf": distinct_of,
            "incrementalMinutes": minutes,
            "reconcileMode": mode,
            "reconcileHours": hours,
            "reconcileAt": at,
        }
        return clean, errors

    def _update_http_task(
        self, tenant_id: str, company_id: str, entity_type: str, raw: Dict[str, Any]
    ) -> EtlTaskView:
        """Draft-save an ``autocount_http`` task (AC-08-13/16/28/30).

        Deliberately NO network call here - the SQL path's "fresh preview on
        every save" discipline would mean a live GET to a customer's server
        on every keystroke-driven save; the open API's Test button
        (``/autocount/http/preview``) is the one place that talks to the
        source, and it is what stamps ``result_columns``/``last_preview_at``
        (AC-08-14). A save therefore only validates the STATIC shape, keeps
        (or seeds) the mapping and demotes an active task whose identity
        changed (AC-08-28) - never an SQL engine, never an HTTP request.
        """
        self._require_task_entity(tenant_id, company_id, entity_type)
        if entity_type not in HTTP_CAPABLE_ENTITY_TYPES:
            raise EtlValidationError(
                {"path": f"'{entity_type}' has no open REST API route."}
            )

        config = self.configs.get(tenant_id, company_id, entity_type)
        existing_result_columns = (
            list(config.result_columns)
            if config is not None and config.result_columns
            else None
        )
        clean, errors = self._validate_http_config(
            tenant_id, raw, existing_result_columns=existing_result_columns
        )
        if errors:
            raise EtlValidationError(errors)

        previous_source_config: Optional[Dict[str, Any]] = (
            dict(config.source_config)
            if config is not None and isinstance(config.source_config, dict)
            else None
        )
        previous_source_impl = config.source_impl if config is not None else None

        if config is None:
            config = self.configs.add(
                AcEntityConfig(
                    tenant_id=tenant_id,
                    company_id=company_id,
                    entity_type=entity_type,
                    sync_mode=SYNC_MODE_SCHEDULED_REVIEW,
                    source_impl=SOURCE_IMPL_AUTOCOUNT_HTTP,
                    initial_load=INITIAL_LOAD_FULL,
                    enabled=True,
                    etl_status=ETL_STATUS_DRAFT,
                )
            )

        #     !!  AC-08-28: sourceImpl/connectionId/path change on an ACTIVE
        #         task demotes it to draft - hashes are KEPT.  !!
        demote = False
        if previous_source_impl is not None and previous_source_impl != SOURCE_IMPL_AUTOCOUNT_HTTP:
            demote = True
        elif previous_source_config is not None and (
            previous_source_config.get("connectionId") != clean.get("connectionId")
            or previous_source_config.get("path") != clean.get("path")
        ):
            demote = True

        config.source_impl = SOURCE_IMPL_AUTOCOUNT_HTTP
        config.source_config = clean
        if demote and config.etl_status == ETL_STATUS_ACTIVE:
            config.etl_status = ETL_STATUS_DRAFT

        # Every save invalidates the activation gate (AC-22-18 parity) - the
        # operator must Test again before Activate/re-activate.
        config.last_preview_at = None
        config.last_preview_failed_count = None
        if config.etl_status == ETL_STATUS_ACTIVE:
            # ``next_run_times`` reads the SQL key name - translated so an
            # active HTTP task's schedule floor still reflects whether it
            # carries a watermark.
            config.next_incremental_at, config.next_reconcile_at = self.next_run_times(
                {**clean, "watermarkColumn": clean.get("watermarkField")},
                now=datetime.now(timezone.utc),
            )

        #     !!  FIRST CLEAN SAVE SEEDS THE HTTP PRESET (AC-08-16).  !!
        # Only when the entity's mapping is still completely empty (an
        # operator who already started mapping, or a second save, is never
        # re-seeded) - the same seed-if-absent contract every other preset
        # in this module follows. ``columns=None`` (no live preview here)
        # seeds every row ENABLED, matching "nothing proven wrong yet".
        if self.companies.mappings.count(tenant_id, company_id, entity_type) == 0:
            seed_http_preset_mapping(
                self.db, tenant_id, company_id, entity_type, columns=None
            )

        self.db.commit()
        self.db.refresh(config)
        return self._task_view(company_id, entity_type, config, tenant_id=tenant_id)

    def update_task(
        self, tenant_id: str, company_id: str, entity_type: str, raw: Dict[str, Any]
    ) -> EtlTaskView:
        """Draft-save the task's ``source_config`` (AC-22-11).

        Order matters: (1) tenant-scope the company + entity; (2) resolve the
        connection tenant+provider scoped; (2b) refuse a connection whose OWN
        database does not match the company's (S2 review SHOULD-FIX 6); (3)
        static-guard the query; (4) run a FRESH preview so column picks are
        checked against what the query actually returns (and the query
        itself is proven to execute); (5) normalise + validate the rest; (6)
        with a watermark column and no errors so far, PROBE the exact
        incremental statement shape the real run will execute (BLOCKER 2) -
        every failure names its field.

        sprint-5/08 (AC-08-13/30): ``raw.sourceImpl == 'autocount_http'``
        dispatches to ``_update_http_task`` FIRST, before a single line of
        the SQL machinery below runs - no SQL engine is ever built for an
        HTTP task (asserted with a spy in
        ``tests/test_autocount_http_lifecycle.py``).
        """
        if str(raw.get("sourceImpl") or "") == SOURCE_IMPL_AUTOCOUNT_HTTP:
            return self._update_http_task(tenant_id, company_id, entity_type, raw)

        company = self._require_task_entity(tenant_id, company_id, entity_type)
        errors: Dict[str, str] = {}

        connection_id = str(raw.get("connectionId") or "").strip() or None
        if self.companies.source_kind_for(tenant_id, company) == SOURCE_KIND_DB:
            #     !!  A DB COMPANY READS ONLY FROM ITS OWN CONNECTION.  !!
            # (Plan sprint-5/01 AC-01-09/10.) Its identity IS that
            # connection's database, so the editor never offers a picker: an
            # omitted id is FILLED with the company connection, a different
            # one is a per-field 422 (no confirm-and-proceed). And GRN has no
            # Sorento path and an API-only envelope - not addable here.
            if entity_type == ENTITY_GOODS_RECEIVED_NOTE:
                raise AutocountServiceError(
                    f"'{entity_type}' is not available on a database company."
                )
            if connection_id is None:
                connection_id = company.connection_id
                raw = {**raw, "connectionId": connection_id}
            elif connection_id != company.connection_id:
                errors["connectionId"] = (
                    "A database company reads only from its own connection."
                )
                connection_id = None
        conn: Optional[Connection] = None
        if connection_id:
            try:
                conn = self._connection(tenant_id, connection_id)
            except ConnectionNotFound as exc:
                errors["connectionId"] = exc.message
            else:
                #     !!  NO SILENT CROSS-COMPANY OVERWRITE PATH.  !!
                # A DB task writes canonical rows keyed by THIS company's
                # ``database_name`` (AC-14-10's company-qualified source_ref)
                # - a connection pointed at a DIFFERENT database would extract
                # someone else's data under this company's identity. Always a
                # 422 (foolproof-UI: no confirm-and-proceed escape hatch) -
                # the operator fixes the company's database name or picks the
                # right connection.
                conn_database = str((conn.config_json or {}).get("database") or "").strip()
                company_database = str(company.database_name or "").strip()
                if company_database and conn_database and conn_database != company_database:
                    errors["connectionId"] = (
                        f"This connection reads '{conn_database}', but the company is "
                        f"'{company_database}'. Choose the connection for "
                        f"'{company_database}', or fix the company's database name."
                    )
                    conn = None

        query = normalize_statement(str(raw.get("query") or ""))
        columns: Optional[Dict[str, str]] = None
        engine = None
        secrets: List[str] = []
        if query:
            if conn is None and "connectionId" not in errors:
                errors["connectionId"] = "Choose the connection this query runs on."
            try:
                assert_select_only(query)
            except SqlGuardError as exc:
                errors["query"] = exc.message
            else:
                if conn is not None:
                    try:
                        engine, secrets = self._engine(conn)
                        columns = run_preview(engine, query, secrets=secrets).column_types
                    except (SqlSourceError, AutocountServiceError) as exc:
                        errors["query"] = exc.message
                        engine = None

        # ── documents: line-query preview, so the line/ref column pickers
        # (S5) are checked against what the lineQuery actually returns - the
        # SAME "test then pick" discipline the header query already applies.
        # A harmless SAMPLE ``:doc_key`` (never real data) is bound purely to
        # let the query execute at all; the picked columns are what matters.
        line_columns: Optional[Dict[str, str]] = None
        if is_document_entity(entity_type):
            line_query = normalize_statement(str(raw.get("lineQuery") or ""))
            if line_query and conn is not None:
                try:
                    assert_select_only(line_query)
                    if engine is None:
                        engine, secrets = self._engine(conn)
                    line_columns = run_preview(
                        engine, line_query, secrets=secrets, params={"doc_key": None}
                    ).column_types
                except (SqlSourceError, AutocountServiceError) as exc:
                    errors.setdefault("lineQuery", exc.message)

        clean, more = validate_source_config(
            entity_type, raw, columns, line_columns=line_columns
        )
        for key, message in more.items():
            errors.setdefault(key, message)

        watermark = clean.get("watermarkColumn")
        if not errors and watermark and engine is not None:
            document = is_document_entity(entity_type)
            try:
                if document:
                    # A document task's real run wraps the header query WITH
                    # the always-on ``fromDate`` predicate - probe THAT
                    # shape, not the plain incremental one (SHOULD-FIX 3).
                    self._probe_document_wrap(
                        engine, secrets, query, watermark, clean["docDateColumn"]
                    )
                else:
                    self._probe_incremental_wrap(engine, secrets, query, watermark)
            except Exception as exc:  # noqa: BLE001 - every driver raises its own class
                # Documents name the failure on ``query`` - it is the header
                # statement that does not survive being wrapped with the
                # extra date predicate/column, not the watermark column
                # itself (already proven present + orderable above).
                field = "query" if document else "watermarkColumn"
                errors[field] = (
                    "This query cannot be run incrementally on this database: "
                    + sanitize_error(exc, secrets=secrets)
                )

        if errors:
            raise EtlValidationError(errors)

        config = self.configs.get(tenant_id, company_id, entity_type)
        # Captured BEFORE `config.source_config` is overwritten below - the F1
        # re-baseline check needs the OLD population-defining values to
        # compare against the new ones. `None` for a brand-new task (nothing
        # to compare, no hashes could possibly exist yet either).
        previous_source_config: Optional[Dict[str, Any]] = (
            dict(config.source_config)
            if config is not None and isinstance(config.source_config, dict)
            else None
        )
        # sprint-5/08 review round 1 (B2) - captured BEFORE the branch below
        # may create a fresh row (whose ``source_impl`` starts at
        # ``sql_db`` and has nothing to demote from).
        previous_source_impl = config.source_impl if config is not None else None
        if config is None:
            # A row that exists ONLY for the DB path is born on the DB source.
            # Existing rows (API-path entities) keep their source_impl - the
            # activation step (S2) is where the source switches.
            config = self.configs.add(
                AcEntityConfig(
                    tenant_id=tenant_id,
                    company_id=company_id,
                    entity_type=entity_type,
                    sync_mode=SYNC_MODE_SCHEDULED_REVIEW,
                    source_impl=SOURCE_IMPL_SQL_DB,
                    initial_load=INITIAL_LOAD_FULL,
                    enabled=True,
                    etl_status=ETL_STATUS_DRAFT,
                )
            )
        config.source_config = clean
        #     !!  AC-08-28: sourceImpl CHANGE ON AN ACTIVE TASK DEMOTES IT TO
        #         DRAFT - EVERY DIRECTION, NOT JUST HTTP -> SQL (B2, review
        #         round 1: this branch used to never write ``source_impl`` at
        #         all, so an HTTP task saved through the SQL editor kept
        #         reporting ``autocount_http`` while carrying a SQL-shaped
        #         ``source_config`` - and an ACTIVE HTTP task saved this way
        #         never demoted).  !!
        # Hashes are KEPT (mirrors ``_update_http_task``) - the first
        # reconcile after a switch reports updates for changed hashes, never
        # a phantom mass-delete, as long as the key shape is unchanged.
        if (
            previous_source_impl is not None
            and previous_source_impl != SOURCE_IMPL_SQL_DB
            and config.etl_status == ETL_STATUS_ACTIVE
        ):
            config.etl_status = ETL_STATUS_DRAFT
        config.source_impl = SOURCE_IMPL_SQL_DB
        #     !!  A NARROWED POPULATION MUST RE-BASELINE, NEVER DELETE.  !!
        # (F1, sprint-5/02 review round - BLOCKER.) A document task's
        # `ac_row_hash` rows are a diff baseline for the set `query` +
        # `fromDate` + `filterFormula` + `keyColumns` can return. Changing any
        # of THOSE (never a schedule-only field) means every existing hash is
        # a baseline for a population that no longer exists - clearing them
        # here forces the next fetch to `upsert_many` a FRESH baseline (every
        # in-scope header stages as an ADD, never a phantom DELETE for one
        # that merely fell outside the new scope).
        if is_document_entity(entity_type) and previous_source_config is not None:
            narrowed = any(
                previous_source_config.get(key) != clean.get(key)
                for key in POPULATION_DEFINING_KEYS
            )
            if narrowed:
                RowHashRepository(self.db).clear_all(tenant_id, company_id, entity_type)
        #     !!  A keyColumns CHANGE IS AN IDENTITY CHANGE, EVERY ENTITY -
        #         NOT JUST A DOCUMENT'S NARROWED POPULATION (S2, review
        #         round 5).  !!
        # `source_ref`'s own scheme is BUILT FROM `keyColumns` - changing it
        # (grown, shrunk, or a same-count rename) makes every EXISTING
        # `ac_row_hash` ref read as "not seen this pass" under the NEW
        # scheme on the very next reconcile, which would stage a PHANTOM
        # DELETE for every one of them (the rows are all still genuinely
        # there; only their COMPUTED ref changed). A master has no
        # `fromDate`/`filterFormula` scope to narrow, so the document-only
        # block above never covered it at all - this one is entity-
        # agnostic and fires independently (a document whose `keyColumns`
        # changes trips BOTH; `clear_all` is idempotent, so that costs
        # nothing extra).
        key_columns_changed = (
            previous_source_config is not None
            and previous_source_config.get("keyColumns") != clean.get("keyColumns")
        )
        if key_columns_changed:
            RowHashRepository(self.db).clear_all(tenant_id, company_id, entity_type)
        #     !!  A MID-PASS WATERMARK-COLUMN OR POPULATION EDIT MUST CLEAR
        #         ANY OPEN PAGED PASS (F4, review round 2) - EVERY ENTITY,
        #         NOT JUST DOCUMENTS.  !!
        # A paged pass's own resume position (``cursor_json["pass"]["mark"]``)
        # is a value under the OLD comparison - a new watermark column (or a
        # narrower/wider population, which changes what the SAME column even
        # means) makes that stored position meaningless to reuse.
        # ``PageCursor.from_watermark_row`` already refuses to resume a pass
        # whose stored column no longer matches (F4's other half, the RUN-time
        # backstop); this is the SAVE-time half, so a mismatched pass never
        # even sits there looking resumable in the meantime. Any ``sql_db``
        # entity can be paged (a watermark column, not documents alone), so
        # this check is deliberately NOT gated on ``is_document_entity``.
        if previous_source_config is not None:
            key_or_watermark_changed = (
                key_columns_changed
                or previous_source_config.get("watermarkColumn") != clean.get("watermarkColumn")
            )
            population_changed = any(
                previous_source_config.get(key) != clean.get(key)
                for key in POPULATION_DEFINING_KEYS
            ) or key_or_watermark_changed
            if population_changed:
                watermark_row = WatermarkRepository(self.db).get(
                    tenant_id, company_id, entity_type
                )
                if (
                    watermark_row is not None
                    and isinstance(watermark_row.cursor_json, dict)
                    and (
                        watermark_row.cursor_json.get("pass") is not None
                        or key_or_watermark_changed
                    )
                ):
                    #     !!  A keyColumns/watermarkColumn CHANGE ALSO
                    #         CLEARS THE TOP-LEVEL sqlWatermark/lastKey (S2,
                    #         review round 5) - NOT JUST `pass`.  !!
                    # The top-level pair is the PUBLIC, monotonic position a
                    # fresh incremental/manual pass resumes from
                    # (`PageCursor.from_watermark_row`'s fresh-pass branch)
                    # - it is just as stale as `pass`'s own position once
                    # the column it was recorded against, or the KEY SHAPE
                    # it was seeked with, no longer applies. A schedule-only
                    # or narrower-scope-only edit (no key/watermark change)
                    # still clears `pass` (an open resume position is stale
                    # either way) but leaves the top-level pair alone - a
                    # merely narrower population does not change what the
                    # SAME column/key means. Fresh dict (SQLAlchemy misses
                    # in-place JSON mutation).
                    updates = {**watermark_row.cursor_json, "pass": None}
                    if key_or_watermark_changed:
                        updates[CURSOR_MARK] = None
                        updates["lastKey"] = None
                    watermark_row.cursor_json = updates
        # The validation preview already proved what this query returns, so its
        # column names are stored (AC-22-09/11) - the Mapping tab's source
        # picker reads them instead of re-running the query per keystroke.
        # ``None`` (no query / no connection) clears them rather than leaving a
        # stale list pointing at a query that no longer exists.
        config.result_columns = list(columns) if columns is not None else None
        # The SAME "test then pick" discipline as `result_columns`, for the
        # LINE query (sprint-5/02, AC-02-06) - the Mapping tab's Line-fields
        # source picker + save-time gate read this.
        config.line_result_columns = list(line_columns) if line_columns is not None else None
        #     !!  EVERY SAVE INVALIDATES THE ACTIVATION GATE (AC-22-18).  !!
        # A dry run proves what a SPECIFIC query would deliver. Editing the
        # query, the keys or the compared columns and keeping the old stamp
        # would let an operator activate a configuration nobody ever previewed.
        config.last_preview_at = None
        config.last_preview_failed_count = None
        # A save on an ALREADY-ACTIVE task re-arms its schedule (plan 22 S3,
        # AC-22-12) - the interval/reconcile fields just changed, so the next
        # fire time must reflect them rather than the one computed under the
        # old config. A draft/paused task has no schedule to arm (NULL until
        # activate/resume).
        if config.etl_status == ETL_STATUS_ACTIVE:
            config.next_incremental_at, config.next_reconcile_at = self.next_run_times(
                clean, now=datetime.now(timezone.utc)
            )
        #     !!  A DOCUMENT'S FIRST CLEAN SAVE SEEDS ITS PRESET MAPPING.  !!
        # (sprint-5/02, AC-02-16.) Only when the header query previewed
        # successfully (`columns is not None` - never seed rows referencing a
        # query that has not even proven it runs) AND the entity's mapping is
        # still completely empty (an operator who already started mapping,
        # or a second save, is never re-seeded - the DB stays the one source
        # of truth, same rule `seed_company_defaults` already follows for
        # masters). A row whose source column the query does not (yet) return
        # is seeded `is_enabled=False` rather than omitted.
        if is_document_entity(entity_type) and columns is not None:
            mappings = self.companies.mappings
            header_empty = (
                mappings.count(tenant_id, company_id, entity_type, scope=SCOPE_HEADER) == 0
            )
            line_empty = (
                mappings.count(tenant_id, company_id, entity_type, scope=SCOPE_LINE) == 0
            )
            # Per SCOPE, not "whole mapping empty" (hotfix after the live proof):
            # migration 0010 backfilled line rows onto existing document tasks,
            # which left their never-mapped HEADER un-seedable forever.
            if header_empty or line_empty:
                seed_document_mapping(
                    self.db, tenant_id, company_id, entity_type,
                    header_columns=columns,
                    line_columns=line_columns,
                    seed_header=header_empty,
                    seed_line=line_empty,
                )
        self.db.commit()
        self.db.refresh(config)
        return self._task_view(company_id, entity_type, config, tenant_id=tenant_id)

    # ── task lifecycle (plan 22 §2.6, AC-22-18/19/20) ────────────────────────
    #
    # Every method here is suffixed ``_task``: this service ALSO owns the raw
    # SQL-surface methods (``preview``/``schema`` take a CONNECTION id, not a
    # company), and an unsuffixed ``preview`` silently shadowed the query
    # preview - the SQL route then answered 'company not found'.

    def _task_config(self, tenant_id: str, company_id: str, entity_type: str):
        """The company + its entity config, both tenant-scoped. A never-saved
        task is a 409 rather than a 404: the entity exists, its task does not
        yet, and "save a query first" is the actionable message."""
        company = self._require_task_entity(tenant_id, company_id, entity_type)
        config = self.configs.get(tenant_id, company_id, entity_type)
        if config is None or not isinstance(config.source_config, dict):
            raise EtlStateError(
                "Save this task's query and key columns before using it."
            )
        return company, config

    @staticmethod
    def _require_runnable(config) -> None:
        source = config.source_config or {}
        if config.source_impl == SOURCE_IMPL_AUTOCOUNT_HTTP:
            if not str(source.get("path") or "").strip():
                raise EtlStateError("Save the endpoint path for this task first.")
            if not [c for c in (source.get("keyFields") or []) if str(c).strip()]:
                raise EtlStateError(
                    "Choose the key fields that identify a row before running this task."
                )
            return
        if not str(source.get("query") or "").strip():
            raise EtlStateError("Save a query for this task first.")
        if not [c for c in (source.get("keyColumns") or []) if str(c).strip()]:
            raise EtlStateError(
                "Choose the key columns that identify a row before running this task."
            )

    @staticmethod
    def _schedule_source_config(config: AcEntityConfig) -> Dict[str, Any]:
        """``config.source_config`` translated for ``next_run_times`` (which
        reads the SQL key name ``watermarkColumn`` for its floor/cadence
        decision) - an ``autocount_http`` task's watermark lives under
        ``watermarkField`` instead (sprint-5/08)."""
        source = dict(config.source_config or {})
        if config.source_impl == SOURCE_IMPL_AUTOCOUNT_HTTP:
            source["watermarkColumn"] = source.get("watermarkField")
        return source

    @staticmethod
    def next_run_times(
        source_config: Dict[str, Any], *, now: Optional[datetime] = None
    ) -> Tuple[datetime, datetime]:
        """``(next_incremental_at, next_reconcile_at)`` in UTC.

        Armed at activation so the sweep (S3) has a due time to select on from
        the first tick. The daily-at time is treated as UTC, full stop - there
        is no tenant-level timezone setting to re-resolve against (only a
        per-user preference, which has no natural owner for an unattended
        scheduled task; see ``scheduler.py``'s own note). BL-SS-034 tracks
        adding one. This stays a pure function of ``now`` either way.
        """
        now = now or datetime.now(timezone.utc)
        minutes = _clean_int(source_config.get("incrementalMinutes")) or (
            DEFAULT_INCREMENTAL_MINUTES
        )
        floor = (
            MIN_INCREMENTAL_MINUTES
            if source_config.get("watermarkColumn")
            else MIN_INCREMENTAL_MINUTES_NO_WATERMARK
        )
        incremental = now + timedelta(minutes=max(minutes, floor))

        if str(source_config.get("reconcileMode")) == RECONCILE_MODE_INTERVAL:
            hours = _clean_int(source_config.get("reconcileHours")) or MIN_RECONCILE_HOURS
            return incremental, now + timedelta(hours=max(hours, MIN_RECONCILE_HOURS))

        at = str(source_config.get("reconcileAt") or DEFAULT_RECONCILE_AT)
        if not _TIME_RE.match(at):
            at = DEFAULT_RECONCILE_AT
        hour, minute = (int(part) for part in at.split(":"))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return incremental, target

    def preview_task(
        self, tenant_id: str, company_id: str, entity_type: str
    ) -> Tuple[EtlTaskView, Dict[str, Any]]:
        """The initial-load dry run against the consumer - writes NOTHING.

        Extract the saved query, map it through the REAL mapping engine, and
        ask the sink what a push WOULD do (``?dry_run=true``, Sorento's own
        resolution rolled back - never a local reconstruction, AC-14-21).
        Nothing is staged and no row hash is written: a preview must be safe to
        run repeatedly, and stamping hashes here would make the FIRST real run
        report zero adds.

        On success ``last_preview_at`` is stamped, which is the ONLY thing that
        unlocks Activate (AC-22-18).

        The returned dict may carry a ``warnings`` key (sprint-5/02, AC-02-12/14)
        - non-blocking, omitted entirely when there is nothing to report:
        ``overlappingDocuments`` (this run's own headers also known to a
        SIBLING document task on the same company - e.g. a PO/SPO split gone
        wrong) and ``contractVersionMismatch`` (Sorento's own advertised
        ``/contract`` version is HIGHER than this connection's configured
        one - advisory only, never auto-applied).
        """
        from ..sinks_sorento import SinkAnchorError, SorentoSinkError

        company, config = self._task_config(tenant_id, company_id, entity_type)
        self._require_runnable(config)

        sink = self.companies.sink_for_company(tenant_id, company, entity_type)
        previewable = hasattr(sink, "dry_run")
        records: List[Any] = []
        current_refs: List[str] = []
        page_complete: Optional[bool] = None
        # AC-02-12 - the overlap warning needs THIS run's own fetched refs,
        # which requires actually reading the source; that is worth doing
        # even for a document with no consumer wired up yet (an operator
        # commonly builds the sibling PO/SPO tasks before pointing either at
        # Sorento), so this extraction is NOT gated on ``previewable``.
        if previewable or is_document_entity(entity_type):
            records, current_refs, page_complete = self._extract_and_map(
                tenant_id, company, config, entity_type
            )

        if not previewable:
            # A logging-sink company has no consumer to ask. Reported honestly
            # rather than as a failure - and deliberately NOT stamped, so the
            # activation gate stays shut (a DB task auto-pushes; activating one
            # with nowhere to push would be a task that runs and delivers
            # nothing, forever).
            payload: Dict[str, Any] = {
                "previewable": False,
                "sink": sink.name,
                "reason": (
                    "No consumer is configured for this company, so there is "
                    "nothing to dry-run. Point the company at Sorento first."
                ),
            }
            warnings = self._preview_warnings(
                tenant_id, company_id, entity_type, current_refs, sink, config
            )
            # AC-03-14 (F1, review round 2) - a watermarked task's preview
            # covers only its FIRST page; when more of the population
            # remains beyond it, the caller must be told this is a partial
            # look, not the whole thing.
            if page_complete is False:
                warnings["pagedPreview"] = True
            if warnings:
                payload["warnings"] = warnings
            return self._task_view(company_id, entity_type, config, tenant_id=tenant_id), payload

        try:
            result = sink.dry_run([r for r in records if r is not None])
        except SinkAnchorError as exc:
            raise EtlAnchorError(exc.code, exc.sorento_message) from exc
        except (SorentoSinkError, httpx.HTTPError) as exc:
            # The operator must be able to tell WHAT the consumer said (a 504
            # from its proxy, a 500 with a body, a refused connection) - the
            # generic sentence alone was useless twice on prod, 2026-09-06.
            # ``httpx.HTTPError`` is caught here as well because the sink does
            # NOT wrap transport faults; before this they escaped as a bare
            # 500 instead of a 502 that names the fault.
            raise _preview_unavailable(
                exc, sink=sink, company_id=company_id, entity_type=entity_type
            ) from exc

        config.last_preview_at = datetime.now(timezone.utc)
        # S5 review SHOULD-FIX 4b: the genuinely-``failed`` count, NOT
        # ``retryable`` - ``activate_task`` reads this to refuse an
        # activation whose own preview already showed rows that will never
        # resolve on their own (a dependency-order carry-over is retryable,
        # not failed, and must stay activatable, AC-22-23).
        config.last_preview_failed_count = int(result.summary.get("failed") or 0)
        self.db.commit()
        self.db.refresh(config)

        warnings = self._preview_warnings(
            tenant_id, company_id, entity_type, current_refs, sink, config
        )
        if page_complete is False:
            warnings["pagedPreview"] = True

        payload = {
            "previewable": True,
            "sink": sink.name,
            "summary": result.summary,
            "predictions": [
                {
                    "sourceRef": p.source_ref,
                    "outcome": p.outcome,
                    "entityId": p.entity_id,
                    "diff": p.diff,
                    "errors": p.errors,
                    "changesLiveData": p.changes_live_data,
                }
                for p in result.predictions
            ],
        }
        if warnings:
            payload["warnings"] = warnings
        return self._task_view(company_id, entity_type, config, tenant_id=tenant_id), payload

    def _preview_warnings(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        current_refs: List[str],
        sink: Any,
        config: Any = None,
    ) -> Dict[str, Any]:
        """The activation preview's non-blocking warnings (sprint-5/02,
        AC-02-12/14; SF2 review round) - computed the same way whether or not
        the company has a real consumer wired up yet (see the two call sites
        in ``preview_task``)."""
        from ..sinks_sorento import SorentoSink

        warnings: Dict[str, Any] = {}
        # SF2 (final reviewer pass) - `validate_source_config` blocks a NEW
        # watermark-inside-keyColumns save going forward, but an EXISTING
        # task saved before that guard existed can carry the bad shape in
        # the DB right now (the live Sorento product-master task did). The
        # activation preview surfaces it as a non-blocking warning naming
        # the offending column, so the operator notices and fixes it.
        raw_source_config = getattr(config, "source_config", None) or {}
        watermark_column = raw_source_config.get("watermarkColumn")
        key_columns = raw_source_config.get("keyColumns") or []
        if watermark_column and watermark_column in key_columns:
            warnings["watermarkInKey"] = watermark_column
        if is_document_entity(entity_type) and current_refs:
            overlaps = self._overlapping_documents(
                tenant_id, company_id, entity_type, current_refs
            )
            if overlaps:
                warnings["overlappingDocuments"] = overlaps
        if isinstance(sink, SorentoSink):
            advertised = sink.fetch_contract()
            if advertised is not None and advertised > sink.contract_version:
                warnings["contractVersionMismatch"] = {
                    "configured": sink.contract_version,
                    "advertised": advertised,
                }
        return warnings

    def _overlapping_documents(
        self, tenant_id: str, company_id: str, entity_type: str, current_refs: List[str],
    ) -> List[Dict[str, Any]]:
        """AC-02-12: which of THIS run's own headers are also known to a
        SIBLING document task on the same company (a PO/SPO filter-formula
        split that lets a DocKey through to both sides, most likely) -
        non-blocking, purely informational."""
        from ..repositories import RowHashRepository

        refs = set(current_refs)
        if not refs:
            return []
        hashes = RowHashRepository(self.db)
        overlaps: List[Dict[str, Any]] = []
        for other in DOCUMENT_ENTITY_TYPES:
            if other == entity_type:
                continue
            other_refs = set(hashes.all_hashes(tenant_id, company_id, other))
            shared = sorted(refs & other_refs)
            if shared:
                overlaps.append({"entityType": other, "sourceRefs": shared})
        return overlaps

    def _extract_and_map(self, tenant_id: str, company, config, entity_type: str):
        """Run the saved query and map every row - NO staging, NO hash writes.

        Deferred import: the DB source imports the mapping + repository layers,
        and importing it at module level here would make this service part of
        that cycle for no benefit.

        Returns ``(mapped_records, current_refs, page_complete)`` -
        ``page_complete`` is ``None`` for a non-watermarked (unpaged) task,
        and a bool for a watermarked one (see below).

        !!  A WATERMARKED TASK'S PREVIEW READS AT MOST ONE PAGE (F1, review
            round 2 BLOCKER).  !!
        The OLD code always called the UNPAGED ``fetch_changes`` here, which
        for a document task means "read the WHOLE from-date window, then run
        one ``lineQuery`` per header, in ONE HTTP request" - a task with
        148k headers issues 148k statements inside a single preview call.
        Reusing the SAME paging primitive a real run uses (``fetch_page``,
        one call, a fresh ``PageCursor``) caps a preview to exactly what a
        real run's FIRST page would read - correct, since the preview's own
        purpose (AC-22-18's activation gate) is to prove the shape of what
        will be pushed, not to enumerate the whole population.
        """
        from ..mapping import (
            MappingEngine,
            UnknownEntityProfile,
            build_mapping_rows_for_run,
            flat_profile,
        )
        from ..sources import SourceContext, Watermark
        from ..sql_source.source import PageCursor, SqlDbSource

        #     !!  B3 (sprint-5/08 review round 1): DISPATCH ON source_impl -
        #         NEVER HARDCODE SqlDbSource.  !!
        # Before this fix, Review & Activate's consumer dry-run always built
        # a ``SqlDbSource`` regardless of the task's actual implementation,
        # so an ``autocount_http`` task's "Preview" either crashed (no
        # ``query``/``keyColumns``) or silently mapped nothing - and
        # ``activate_task`` had to carve out a special bypass of the
        # "run a preview first" gate for HTTP tasks as a result (removed
        # below, now that this dry-run genuinely covers them too).
        is_http = config.source_impl == SOURCE_IMPL_AUTOCOUNT_HTTP
        if is_http:
            from ..http_source.source import HttpApiSource

            source = HttpApiSource(
                SourceContext(
                    db=self.db,
                    tenant_id=tenant_id,
                    company=company,
                    entity_config=config,
                    company_service=self.companies,
                ),
                entity_type=entity_type,
                mode=RUN_MODE_MANUAL,
                # A dry run must leave no trace (same contract as the SQL
                # branch below): the FIRST real run has to report its rows
                # as adds, which it cannot do if the preview already
                # recorded their hashes.
                persist_hashes=False,
            )
        else:
            source = SqlDbSource(
                SourceContext(
                    db=self.db,
                    tenant_id=tenant_id,
                    company=company,
                    entity_config=config,
                    company_service=self.companies,
                ),
                entity_type=entity_type,
                # A dry run must leave no trace: the FIRST real run has to report
                # its rows as adds, which it cannot do if the preview already
                # recorded their hashes.
                persist_hashes=False,
            )
        page_complete: Optional[bool] = None
        try:
            if not is_http and source.watermark_column:
                page = source.fetch_page(PageCursor())
                #     !!  PREVIEW MAPS EVERY CANDIDATE, NOT JUST CHANGED ONES
                #         (R2-S1, review round 3).  !!
                # ``page.records`` is CHANGE-ONLY by design (D2) - a preview
                # run right after a real run has already hashed the page, so
                # every row reads as unchanged and ``page.records`` is
                # empty, reporting "total: 0" for a task that plainly has
                # rows. ``page.preview_records`` carries every candidate on
                # the page regardless of changed/unchanged status; the RUN
                # loop (``sync.py``) keeps using ``page.records`` unchanged.
                raw_records = page.preview_records
                current_refs = list(page.hashes)
                page_complete = page.complete
            else:
                # ``Watermark()`` = no mark, so this is the INITIAL LOAD -
                # exactly what the activation gate is meant to show
                # (AC-22-18). For SQL this is only reachable for a task with
                # no watermark column at all; an HTTP task ALWAYS takes this
                # branch - it has no page-limited preview concept, it walks
                # the whole population every run by design (plan §2.4), so
                # its dry run does too. ``page_complete`` stays ``None`` for
                # it (not a partial look - a genuine full walk).
                result = source.fetch_changes(Watermark())
                raw_records = result.records
                current_refs = list(result.current_refs)
        finally:
            source.close()

        try:
            key_columns = (
                (config.source_config or {}).get("keyFields")
                if is_http
                else (config.source_config or {}).get("keyColumns")
            ) or []
            profile = flat_profile(entity_type, key_columns)
        except UnknownEntityProfile as exc:
            # NIT (S2 review): ``ETL_ENTITY_TYPES`` (a task CAN be saved for
            # this entity) is wider than ``mapping.ENTITY_PROFILES`` (mapping
            # actually knows how to SHAPE it). A clean, named 409 - never an
            # unhandled crash - for an entity this build cannot extract yet.
            raise EtlStateError(
                f"'{entity_type}' is not yet extractable via a database task - "
                "its AutoCount mapping is not implemented yet."
            ) from exc
        # ``mapping_rows`` returns BOTH scopes (header AND line, sprint-5/02) -
        # a document's line fields are real, persisted, operator-editable
        # ``ac_field_mapping`` rows now, not a code-generated fixed-column
        # convention. ``build_mapping_rows_for_run`` is the ONE gate here (S5
        # review NIT - shared with ``sync.py``'s real-run path so the two can
        # never drift). This method now runs against EITHER a freshly-built
        # ``SqlDbSource`` OR (sprint-5/08 B3) an ``HttpApiSource`` above -
        # ``is_sql_db_source`` is currently unused by the function itself
        # (see its docstring) but kept honest for a future reader/caller.
        rows = build_mapping_rows_for_run(
            entity_type,
            self.companies.mapping_rows(tenant_id, company.id, entity_type),
            is_sql_db_source=not is_http,
            source_config=config.source_config,
        )
        engine = MappingEngine(
            rows,
            entity_type=entity_type,
            profile=profile,
            database_name=company.database_name,
        )
        mapped = [engine.map_document(record.raw) for record in raw_records]
        # ``current_refs`` (sprint-5/02, AC-02-12) is returned alongside the
        # mapped records so ``preview_task`` can cross-check this run's own
        # fetched headers against a SIBLING document task's known refs
        # (the overlap warning) without re-reading the source a second time.
        # ``page_complete`` (F1, review round 2) lets ``preview_task`` warn
        # when this preview covers only PART of the population.
        return [m.record for m in mapped if m.ok], current_refs, page_complete

    def activate_task(self, tenant_id: str, company_id: str, entity_type: str) -> EtlTaskView:
        """draft|paused → active (AC-22-18).

        Server-side gate, not just a disabled button: the API is the real
        boundary, and after activation runs push with no further approval.
        """
        company, config = self._task_config(tenant_id, company_id, entity_type)
        self._require_runnable(config)
        if config.etl_status == ETL_STATUS_ACTIVE:
            raise EtlStateError("This task is already active.")
        #     !!  ACTIVATE-ONCE GATE - NOW UNIFORM ACROSS BOTH source_impl
        #         VALUES (sprint-5/08 review round 1, B3).  !!
        # ``_extract_and_map`` (``preview_task``'s dry-run) dispatches on
        # ``source_impl`` and builds a real ``HttpApiSource`` for an HTTP
        # task exactly as it builds a ``SqlDbSource`` for a SQL one, so this
        # gate no longer needs (or gets) a bypass for HTTP: ``last_preview_at``
        # is stamped by EITHER a successful ``preview_task`` run OR the
        # Source tab's own Test button (``/autocount/http/preview`` with
        # ``companyId``/``entityType`` set, AC-08-14) - foolproof-UI: the
        # operator only ever has to click Test once, never a second
        # ceremony.
        if config.last_preview_at is None:
            raise EtlStateError(
                "Run a successful preview of the initial load before activating."
            )
        #     !!  A PREVIEW THAT COMPLETED IS NOT THE SAME AS ONE THAT PASSED.  !!
        # (S5 review SHOULD-FIX 4b.) The dry run itself succeeding only proves
        # the CONSUMER was reachable - a row can still come back genuinely
        # ``failed`` (a required field the mapping never covers, a value
        # Sorento rejects outright). ``retryable`` stays allowed on purpose:
        # a dependency-order carry-over (AC-22-23) resolves itself on a later
        # run and must not block activation.
        if config.last_preview_failed_count:
            raise EtlStateError(
                f"The last preview reported {config.last_preview_failed_count} "
                f"failed row(s) - re-run preview after fixing the mapping "
                f"before activating."
            )
        if not (company.sorento_company_code or "").strip():
            raise EtlStateError(
                "Set the Sorento company code on this company before activating - "
                "every push is anchored to it."
            )
        now = datetime.now(timezone.utc)
        config.etl_status = ETL_STATUS_ACTIVE
        config.activated_at = now
        # Activation IS the switch to the DB path: an active task that still
        # read from the vendor API would auto-push records the operator
        # previewed from a different source entirely. sprint-5/08: an
        # ``autocount_http`` task is left AS-IS - it is not the legacy
        # vendor-API default this switch exists to escape.
        if config.source_impl not in (SOURCE_IMPL_SQL_DB, SOURCE_IMPL_AUTOCOUNT_HTTP):
            config.source_impl = SOURCE_IMPL_SQL_DB
        _, config.next_reconcile_at = self.next_run_times(
            self._schedule_source_config(config), now=now
        )
        # plan sprint-5/03 §2.4 - the initial (paged) pass starts on the
        # FIRST tick after activation, not after a full ``incrementalMinutes``
        # wait: 148k SO headers finish in hours unattended only if the sweep
        # fires immediately.
        config.next_incremental_at = now
        self.db.commit()
        self.db.refresh(config)
        return self._task_view(company_id, entity_type, config, tenant_id=tenant_id)

    def pause_task(self, tenant_id: str, company_id: str, entity_type: str) -> EtlTaskView:
        """active → paused. The sweep stops dispatching; an in-flight run
        finishes (nothing here touches a running job)."""
        _company, config = self._task_config(tenant_id, company_id, entity_type)
        if config.etl_status != ETL_STATUS_ACTIVE:
            raise EtlStateError("Only an active task can be paused.")
        config.etl_status = ETL_STATUS_PAUSED
        config.next_incremental_at = None
        config.next_reconcile_at = None
        self.db.commit()
        self.db.refresh(config)
        return self._task_view(company_id, entity_type, config, tenant_id=tenant_id)

    def resume_task(self, tenant_id: str, company_id: str, entity_type: str) -> EtlTaskView:
        """paused → active, with NO re-preview ceremony (AC-22-19). Pausing is
        an operational lever, not an invalidation of the gate - the config that
        was previewed has not changed (any save would have cleared the stamp)."""
        _company, config = self._task_config(tenant_id, company_id, entity_type)
        if config.etl_status != ETL_STATUS_PAUSED:
            raise EtlStateError("Only a paused task can be resumed.")
        now = datetime.now(timezone.utc)
        config.etl_status = ETL_STATUS_ACTIVE
        config.next_incremental_at, config.next_reconcile_at = self.next_run_times(
            self._schedule_source_config(config), now=now
        )
        self.db.commit()
        self.db.refresh(config)
        return self._task_view(company_id, entity_type, config, tenant_id=tenant_id)

    def run_task_now(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        *,
        actor_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Enqueue ONE manual run - the SAME job the sweep enqueues (AC-22-13).

        Refused unless the task is active (a draft has not passed the gate and
        would auto-push nothing) and unless no run is already in flight - two
        workers on one (company, entity) would double-push the same staged rows.
        """
        from ..sync import AUTOCOUNT_SYNC

        _company, config = self._task_config(tenant_id, company_id, entity_type)
        self._require_runnable(config)
        if config.etl_status != ETL_STATUS_ACTIVE:
            raise EtlStateError("Activate this task before running it.")

        in_flight = SyncJobRepository(self.db).first_unfinished(
            tenant_id, AUTOCOUNT_SYNC, company_id, entity_type
        )
        if in_flight is not None:
            run = SyncRunRepository(self.db).get_for_job(
                tenant_id, company_id, in_flight.id
            )
            raise EtlStateError(
                "A run for this task is still going. Wait for it to finish.",
                running_run_id=(run.id if run is not None else None),
            )

        job = JobService(self.db).create_and_enqueue(
            type=AUTOCOUNT_SYNC,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            # ``manual`` is the run MODE (plan 22 §2.7) - the sweep enqueues the
            # same job with ``incremental``/``reconcile``. One pipeline, one
            # payload shape, one place that reads it.
            payload={
                "companyId": company_id,
                "entityType": entity_type,
                "mode": RUN_MODE_MANUAL,
            },
        )
        # Eager dev/test ran the handler INLINE, so the run row already exists;
        # under a real worker it does not yet, and ``runId`` is empty until it
        # does (the surface polls the run history either way).
        run = SyncRunRepository(self.db).get_for_job(tenant_id, company_id, job.id)
        self.db.refresh(config)
        return {
            "run_id": run.id if run is not None else "",
            "job_id": job.id,
            "status": job.status,
            "task": self._task_view(company_id, entity_type, config, tenant_id=tenant_id),
        }

    def _in_flight_guard(
        self, tenant_id: str, company_id: str, entity_type: str
    ) -> None:
        """Raise the SAME `EtlStateError` `run_task_now` raises when a run for
        this (company, entity) is still executing - ``run.id if run is not
        None else None`` (AC-07-16: "same shape `run_task_now` uses" - no
        background-job-id fallback). Called TWICE by `repush_task`: once as
        the up-front guard, once again after `clear_all` but before the
        commit (the race `first_unfinished`/`clear_all` leaves open - a run
        can be enqueued in between)."""
        from ..sync import AUTOCOUNT_SYNC

        in_flight = SyncJobRepository(self.db).first_unfinished(
            tenant_id, AUTOCOUNT_SYNC, company_id, entity_type
        )
        if in_flight is None:
            return
        run = SyncRunRepository(self.db).get_for_job(tenant_id, company_id, in_flight.id)
        raise EtlStateError(
            "A run for this task is still going. Wait for it to finish.",
            running_run_id=(run.id if run is not None else None),
        )

    def repush_task(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        *,
        actor_user_id: Optional[str] = None,
    ) -> EtlRepushView:
        """Clear this task's change-tracking rows so the next reconcile
        classifies every fetched row as an add and re-pushes it (plan
        sprint-5/07, AC-07-13..19) - the operator's answer to "the mapping
        changed, re-send everything" with no SQL by hand.

        Guards mirror ``run_task_now``'s (a run in flight refuses the SAME
        way, with the same ``running_run_id`` link) plus two of its own: a
        task whose source is not a database task, and a draft (nothing has
        ever run for it to re-push). All three refuse BEFORE anything is
        deleted - ``EtlStateError`` -> 409, nothing committed.

        ``ac_doc_fingerprint``/the watermark are left alone (D5, plan
        section 2.3): the reconcile that follows is a FULL extract either
        way, so neither gates what it pushes - the fingerprint sweep
        re-baselines itself on its next pass, and resetting the watermark
        would re-read every page incrementally for nothing.

            !!  COMMIT ORDER - read before touching this method.  !!

        ``record_activity``/``ActivityLogService.record`` COMMITS the
        session it is handed on success, and on ITS OWN failure calls
        ``self.db.rollback()`` INSIDE its own swallow-all try/except (never
        re-raises - ``activity.py``'s own module docstring, AC-13-43). Call
        it before this method's own commit and a dropped activity row
        SILENTLY discards the `clear_all` deletion too (same session, same
        uncommitted transaction) while this method carries on as if nothing
        happened - a 200 reporting a `clearedCount` that was never actually
        persisted. So the ONLY correct order is: mutate -> re-check the
        in-flight race -> `self.db.commit()` (the ACTUAL atomicity boundary
        for the deletion + `next_reconcile_at`) -> THEN `record_activity`
        (same pattern as `preview_task`'s `_record_preview` call, ~:715) -
        an activity-write failure past this point can never touch the
        already-committed deletion.
        """
        _company, config = self._task_config(tenant_id, company_id, entity_type)
        if config.source_impl not in (SOURCE_IMPL_SQL_DB, SOURCE_IMPL_AUTOCOUNT_HTTP):
            raise EtlStateError(
                "Re-push applies to a database task or an open-API task only."
            )
        if config.etl_status == ETL_STATUS_DRAFT:
            raise EtlStateError(
                "Activate the task first - a draft has nothing to re-push."
            )
        self._in_flight_guard(tenant_id, company_id, entity_type)

        # `clear_all` only FLUSHES (never commits - its own docstring).
        cleared = RowHashRepository(self.db).clear_all(
            tenant_id, company_id, entity_type
        )
        if config.etl_status == ETL_STATUS_ACTIVE:
            # The very next scheduler sweep claims a `reconcile` (existing
            # claim path, no new mode) - the incremental schedule is
            # untouched. A `paused` task leaves this `None`: resuming later
            # re-arms it as today, same as any other resume.
            config.next_reconcile_at = datetime.now(timezone.utc)

        # Re-check the race `first_unfinished` + `clear_all` leaves open: a
        # manual/scheduled run can be enqueued between the up-front guard
        # above and this commit, and would otherwise push a population whose
        # tracked rows this call just wiped out from under it. Caught here
        # means the deletion is rolled back with everything else - nothing
        # commits at all for this request.
        try:
            self._in_flight_guard(tenant_id, company_id, entity_type)
        except EtlStateError:
            self.db.rollback()
            raise

        self.db.commit()
        self.db.refresh(config)

        logger.info(
            "autocount repush: tenant=%s company=%s entity=%s actor=%s cleared=%d",
            tenant_id, company_id, entity_type, actor_user_id, cleared,
        )
        record_activity(
            self.db,
            tenant_id=tenant_id,
            operation=OPERATION_REPUSH_TASK,
            status=ACTIVITY_SUCCESS,
            external_ref=company_id,
            response={
                "clearedCount": cleared,
                "entityType": entity_type,
                "actorUserId": actor_user_id,
            },
        )
        return EtlRepushView(
            cleared_count=cleared,
            next_reconcile_at=config.next_reconcile_at,
            status=config.etl_status,
        )

    def list_task_runs(
        self,
        tenant_id: str,
        company_id: str,
        entity_type: str,
        *,
        page: int = 0,
        page_size: int = 25,
    ):
        """This entity's run history, newest first. Tenant- AND company-scoped
        through ``_require_task_entity`` before a single row is read."""
        self._require_task_entity(tenant_id, company_id, entity_type)
        return SyncRunRepository(self.db).list(
            tenant_id,
            company_id,
            entity_type=entity_type,
            page=page,
            page_size=page_size,
        )
