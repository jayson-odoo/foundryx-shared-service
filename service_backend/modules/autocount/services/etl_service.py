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
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.models.connection import Connection
from app.secrets import decrypt_secret

from ..activity import ACTIVITY_ERROR, ACTIVITY_SUCCESS, record_activity
from ..canonical.grn import ENTITY_GOODS_RECEIVED_NOTE
from ..canonical.masters import ENTITY_CUSTOMER, ENTITY_SUPPLIER
from ..models import (
    ETL_STATUS_DRAFT,
    SOURCE_IMPL_SQL_DB,
    SYNC_MODE_SCHEDULED_REVIEW,
    AcEntityConfig,
)
from ..repositories import ConnectionRepository, EntityConfigRepository
from ..sources import INITIAL_LOAD_FULL
from ..sql_provider import SQL_DATABASE_PROVIDER_KEY
from ..sql_source.errors import SqlGuardError, SqlSourceError
from ..sql_source.guard import assert_select_only, normalize_statement
from ..sql_source.introspect import (
    SCHEMA_CACHE,
    SchemaCache,
    SqlSchemaTree,
    introspect_schema,
)
from ..sql_source.preview import PreviewResult, is_orderable_type, run_preview
from ..sql_source.runtime import RUNTIME, SqlSourceRuntime, secrets_of
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
ENTITY_PRODUCT = "product"
ENTITY_WAREHOUSE = "warehouse"
ENTITY_PRODUCT_CATEGORY = "product_category"
ENTITY_UNIT_OF_MEASURE = "unit_of_measure"
ENTITY_SALES_AGENT = "sales_agent"
ENTITY_SALES_ORDER = "sales_order"
ENTITY_PURCHASE_ORDER = "purchase_order"

DOCUMENT_ENTITY_TYPES = (ENTITY_SALES_ORDER, ENTITY_PURCHASE_ORDER)
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


def is_document_entity(entity_type: str) -> bool:
    return entity_type in DOCUMENT_ENTITY_TYPES


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


@dataclass
class EtlTaskView:
    company_id: str
    entity_type: str
    etl_status: str
    activated_at: Optional[datetime]
    source_config: Dict[str, Any] = field(default_factory=dict)


def default_source_config(entity_type: str, *, today: Optional[date] = None) -> Dict[str, Any]:
    """The draft a never-configured entity starts from (the editor is the
    create surface). Documents get today's from-date + a line-query slot."""
    document = is_document_entity(entity_type)
    return {
        "connectionId": None,
        "query": "",
        "lineQuery": "" if document else None,
        "keyColumns": [],
        "watermarkColumn": None,
        "comparedColumns": [],
        "fromDate": (today or date.today()).isoformat() if document else None,
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
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Normalise + validate a task's ``source_config`` (AC-22-11/12).

    ``columns`` = ``{name: type}`` from a FRESH preview of ``query`` (None when
    no preview exists - blank query / no connection). Column picks are checked
    against it; a pick with no preview to check against is an error on the
    query, not a silent accept.

    Returns ``(clean, field_errors)``. Pure - no DB, no source. The caller
    (``EtlService.update_task``) resolves the connection, runs the preview and
    guards the query itself, then merges its own errors in.
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

    # ── documents: line query + from-date (Q20) ──────────────────────────────
    from_date: Optional[str] = None
    if document:
        raw_from = str(raw.get("fromDate") or "").strip()
        if not raw_from:
            errors["fromDate"] = "A from-date is required for documents."
        else:
            try:
                from_date = date.fromisoformat(raw_from).isoformat()
            except ValueError:
                errors["fromDate"] = "Enter the from-date as YYYY-MM-DD."
        if line_query:
            try:
                assert_select_only(line_query)
            except SqlGuardError as exc:
                errors["lineQuery"] = exc.message

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

    def preview(self, tenant_id: str, connection_id: str, query: str) -> PreviewResult:
        conn = self._connection(tenant_id, connection_id)
        # Guard BEFORE anything touches the source (AC-22-03) - and before the
        # engine is even built.
        assert_select_only(query)
        engine, secrets = self._engine(conn)
        try:
            result = run_preview(engine, query, secrets=secrets)
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
        )

    def update_task(
        self, tenant_id: str, company_id: str, entity_type: str, raw: Dict[str, Any]
    ) -> EtlTaskView:
        """Draft-save the task's ``source_config`` (AC-22-11).

        Order matters: (1) tenant-scope the company + entity; (2) resolve the
        connection tenant+provider scoped; (3) static-guard the query; (4) run
        a FRESH preview so column picks are checked against what the query
        actually returns (and the query itself is proven to execute); (5)
        normalise + validate the rest. Every failure names its field.
        """
        self._require_task_entity(tenant_id, company_id, entity_type)
        errors: Dict[str, str] = {}

        connection_id = str(raw.get("connectionId") or "").strip() or None
        conn: Optional[Connection] = None
        if connection_id:
            try:
                conn = self._connection(tenant_id, connection_id)
            except ConnectionNotFound as exc:
                errors["connectionId"] = exc.message

        query = normalize_statement(str(raw.get("query") or ""))
        columns: Optional[Dict[str, str]] = None
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

        clean, more = validate_source_config(entity_type, raw, columns)
        for key, message in more.items():
            errors.setdefault(key, message)
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
        self.db.commit()
        self.db.refresh(config)
        return self._task_view(company_id, entity_type, config)
