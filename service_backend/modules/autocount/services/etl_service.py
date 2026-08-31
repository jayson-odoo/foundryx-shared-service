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

import sqlalchemy as sa
from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.jobs.service import JobService
from app.models.connection import Connection
from app.secrets import decrypt_secret

from ..activity import ACTIVITY_ERROR, ACTIVITY_SUCCESS, record_activity
from ..canonical.documents import (
    DOCUMENT_ENTITY_TYPES,
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    LINE_QUERY_DOC_KEY_PARAM,
    is_document_entity,
)
from ..canonical.grn import ENTITY_GOODS_RECEIVED_NOTE
from ..canonical.masters import (
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
    SOURCE_IMPL_SQL_DB,
    SYNC_MODE_SCHEDULED_REVIEW,
    AcEntityConfig,
)
from ..repositories import (
    ConnectionRepository,
    EntityConfigRepository,
    SyncJobRepository,
    SyncRunRepository,
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
from ..sql_source.source import build_document_header_wrap, build_incremental_wrap
from .company_service import (
    AutocountServiceError,
    CompanyService,
    ConnectionNotFound,
    EntityConfigNotFound,
)

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
    ENTITY_GOODS_RECEIVED_NOTE,
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
    activates blind. Nothing was written either way."""


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
    # ── read-only task state (plan 22 S2, all stamped server-side) ───────────
    # The SAVED query's result column names, from the validation preview every
    # PUT runs - so the Mapping tab offers them without re-running the query.
    result_columns: List[str] = field(default_factory=list)
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
        "lineKeyColumn": None,
        "lineProductColumn": None,
        "lineWarehouseColumn": None,
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

    ``line_columns`` (plan 22 S5, documents only) = the SAME shape from a
    FRESH preview of ``lineQuery`` (a sample ``:doc_key`` bound) - the line-
    column pickers (``lineKeyColumn``/``lineProductColumn``/
    ``lineWarehouseColumn``) are checked against it exactly like the header
    pickers are checked against ``columns``.

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

    # ── documents: line query + from-date + line/ref columns (S5) ────────────
    from_date: Optional[str] = None
    doc_date_column: Optional[str] = None
    line_key_column: Optional[str] = None
    line_product_column: Optional[str] = None
    line_warehouse_column: Optional[str] = None
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

        line_key_column = str(raw.get("lineKeyColumn") or "").strip() or None
        line_product_column = str(raw.get("lineProductColumn") or "").strip() or None
        line_warehouse_column = str(raw.get("lineWarehouseColumn") or "").strip() or None
        if line_key_column is None:
            errors.setdefault("lineKeyColumn", "Choose the line query's key column.")
        if line_product_column is None:
            errors.setdefault("lineProductColumn", "Choose the line query's product column.")
        picked_line = bool(line_key_column or line_product_column or line_warehouse_column)
        if picked_line and line_query and "lineQuery" not in errors and line_columns is None:
            errors.setdefault(
                "lineQuery", "Test the line query first - the picked columns are checked against its result."
            )
        elif line_columns is not None:
            for field, value in (
                ("lineKeyColumn", line_key_column),
                ("lineProductColumn", line_product_column),
                ("lineWarehouseColumn", line_warehouse_column),
            ):
                if value is not None and value not in line_columns:
                    errors.setdefault(field, f"'{value}' is not in the line query result.")

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
        "lineKeyColumn": line_key_column if document else None,
        "lineProductColumn": line_product_column if document else None,
        "lineWarehouseColumn": line_warehouse_column if document else None,
        "incrementalMinutes": minutes,
        "reconcileMode": mode,
        "reconcileHours": hours,
        "reconcileAt": at,
    }
    return clean, errors


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
        return self._task_view(company_id, entity_type, config)

    def _task_view(
        self, company_id: str, entity_type: str, config: Optional[AcEntityConfig]
    ) -> EtlTaskView:
        # Stored keys win; new keys fall back to the draft defaults so an older
        # document always round-trips whole.
        merged = default_source_config(entity_type)
        if config is not None and isinstance(config.source_config, dict):
            merged.update(config.source_config)
        return EtlTaskView(
            company_id=company_id,
            entity_type=entity_type,
            etl_status=(config.etl_status if config is not None else None) or ETL_STATUS_DRAFT,
            activated_at=config.activated_at if config is not None else None,
            source_config=merged,
            result_columns=[
                str(c) for c in ((config.result_columns if config is not None else None) or [])
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
        )

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
        """
        company = self._require_task_entity(tenant_id, company_id, entity_type)
        errors: Dict[str, str] = {}

        connection_id = str(raw.get("connectionId") or "").strip() or None
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
        # The validation preview already proved what this query returns, so its
        # column names are stored (AC-22-09/11) - the Mapping tab's source
        # picker reads them instead of re-running the query per keystroke.
        # ``None`` (no query / no connection) clears them rather than leaving a
        # stale list pointing at a query that no longer exists.
        config.result_columns = list(columns) if columns is not None else None
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
        self.db.commit()
        self.db.refresh(config)
        return self._task_view(company_id, entity_type, config)

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
        if not str(source.get("query") or "").strip():
            raise EtlStateError("Save a query for this task first.")
        if not [c for c in (source.get("keyColumns") or []) if str(c).strip()]:
            raise EtlStateError(
                "Choose the key columns that identify a row before running this task."
            )

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
        """
        from ..sinks_sorento import SinkAnchorError, SorentoSinkError

        company, config = self._task_config(tenant_id, company_id, entity_type)
        self._require_runnable(config)

        sink = self.companies.sink_for_company(tenant_id, company, entity_type)
        if not hasattr(sink, "dry_run"):
            # A logging-sink company has no consumer to ask. Reported honestly
            # rather than as a failure - and deliberately NOT stamped, so the
            # activation gate stays shut (a DB task auto-pushes; activating one
            # with nowhere to push would be a task that runs and delivers
            # nothing, forever).
            return self._task_view(company_id, entity_type, config), {
                "previewable": False,
                "sink": sink.name,
                "reason": (
                    "No consumer is configured for this company, so there is "
                    "nothing to dry-run. Point the company at Sorento first."
                ),
            }

        records = self._extract_and_map(tenant_id, company, config, entity_type)
        try:
            result = sink.dry_run([r for r in records if r is not None])
        except SinkAnchorError as exc:
            raise EtlAnchorError(exc.code, exc.sorento_message) from exc
        except SorentoSinkError as exc:
            raise PreviewUnavailable(
                "The dry run against the consumer failed, so no prediction is "
                "available and this task cannot be activated yet. Nothing was "
                "written - resolve the consumer error first."
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
        return self._task_view(company_id, entity_type, config), {
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

    def _extract_and_map(self, tenant_id: str, company, config, entity_type: str):
        """Run the saved query and map every row - NO staging, NO hash writes.

        Deferred import: the DB source imports the mapping + repository layers,
        and importing it at module level here would make this service part of
        that cycle for no benefit.
        """
        from ..mapping import (
            MappingEngine,
            UnknownEntityProfile,
            build_mapping_rows_for_run,
            flat_profile,
        )
        from ..sources import SourceContext, Watermark
        from ..sql_source.source import SqlDbSource

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
        try:
            # ``Watermark()`` = no mark, so this is the INITIAL LOAD - which is
            # exactly what the activation gate is meant to show (AC-22-18).
            result = source.fetch_changes(Watermark())
        finally:
            source.close()

        try:
            profile = flat_profile(
                entity_type, (config.source_config or {}).get("keyColumns") or []
            )
        except UnknownEntityProfile as exc:
            # NIT (S2 review): ``ETL_ENTITY_TYPES`` (a task CAN be saved for
            # this entity) is wider than ``mapping.ENTITY_PROFILES`` (mapping
            # actually knows how to SHAPE it). A clean, named 409 - never an
            # unhandled crash - for an entity this build cannot extract yet.
            raise EtlStateError(
                f"'{entity_type}' is not yet extractable via a database task - "
                "its AutoCount mapping is not implemented yet."
            ) from exc
        # A document's LINE rows are code-generated from its source_config
        # (plan 22 S5's "FIXED column-name convention", ``mapping.
        # document_line_rows``), never read from ``ac_field_mapping`` -
        # ``mapping_rows`` stays HEADER-only, same as before this slice.
        # ``build_mapping_rows_for_run`` is the ONE gate for this (S5 review
        # NIT - shared with ``sync.py``'s real-run path so the two can never
        # drift). This method only ever runs against a freshly-built
        # ``SqlDbSource`` above - always the DB source, never the API path.
        rows = build_mapping_rows_for_run(
            entity_type,
            self.companies.mapping_rows(tenant_id, company.id, entity_type),
            is_sql_db_source=True,
            source_config=config.source_config,
        )
        engine = MappingEngine(
            rows,
            entity_type=entity_type,
            profile=profile,
            database_name=company.database_name,
        )
        mapped = [engine.map_document(record.raw) for record in result.records]
        return [m.record for m in mapped if m.ok]

    def activate_task(self, tenant_id: str, company_id: str, entity_type: str) -> EtlTaskView:
        """draft|paused → active (AC-22-18).

        Server-side gate, not just a disabled button: the API is the real
        boundary, and after activation runs push with no further approval.
        """
        company, config = self._task_config(tenant_id, company_id, entity_type)
        self._require_runnable(config)
        if config.etl_status == ETL_STATUS_ACTIVE:
            raise EtlStateError("This task is already active.")
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
        # previewed from a different source entirely.
        config.source_impl = SOURCE_IMPL_SQL_DB
        config.next_incremental_at, config.next_reconcile_at = self.next_run_times(
            config.source_config or {}, now=now
        )
        self.db.commit()
        self.db.refresh(config)
        return self._task_view(company_id, entity_type, config)

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
        return self._task_view(company_id, entity_type, config)

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
            config.source_config or {}, now=now
        )
        self.db.commit()
        self.db.refresh(config)
        return self._task_view(company_id, entity_type, config)

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
            "task": self._task_view(company_id, entity_type, config),
        }

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
