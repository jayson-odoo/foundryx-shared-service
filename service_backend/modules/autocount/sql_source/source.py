"""``SqlDbSource`` - the direct read-only SQL implementation of the
``EntitySource`` seam (plan 22 §2.2/2.5, AC-22-08/15/16).

Everything downstream of a source (mapping, staging, approval, push, retry,
observability) is identical to the API path; only HOW rows are read changes.

Two fetch shapes, chosen by whether a mark exists:

* **Initial load** - the saved query as written, streamed in server-side
  batches. A ``full`` first read is correct for a master list: a standing set
  must be mirrored whole (the same reasoning as ``INITIAL_LOAD_FULL`` on the
  API path).
* **Incremental** - ``SELECT * FROM (<query>) t WHERE t.<wm> > :mark ORDER BY
  t.<wm>``. The mark is a BOUND PARAMETER and the column name is quoted by the
  dialect's own identifier preparer after being checked against the columns the
  saved query actually returns - **nothing from a request is ever spliced into
  SQL** (AC-22-03/30).

Rules that are easy to get wrong and expensive to get wrong:

1. **The watermark advances to the max value SEEN, never to the clock.** With a
   watermark column configured the statement always carries ``ORDER BY t.<wm>``
   (initial load included), so the new mark is simply the LAST row's value -
   decided by the database's own ordering, never by a Python comparison across
   types the driver may have decoded differently. Zero rows = the mark HOLDS.
2. **The guard re-runs on the STORED query at execution time.** The save-time
   guard proves what was saved; this proves what is about to run (a row edited
   straight into the JSON column, or a guard that got stricter since, must not
   sail through).
3. **The connection id is re-resolved tenant- AND provider-scoped on every
   run** - it is a stored polymorphic id (AC-22-29).
4. **Hashes are written for every fetched row** so S3's reconcile has a
   baseline from day one; a run that raises writes none.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, time as dt_time, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

import sqlalchemy as sa
from cryptography.fernet import InvalidToken
from sqlalchemy.engine import Engine

from app.secrets import decrypt_secret

from ..client import CallRecord
from ..mapping import IdentityError, flat_source_ref
from ..models import (
    RUN_MODE_MANUAL,
    SOURCE_IMPL_SQL_DB,
    AcRowHash,  # noqa: F401 - documents what ``persist_hashes`` writes
)
from ..repositories import ConnectionRepository, RowHashRepository
from ..sources import (
    FetchResult,
    SourceContext,
    SourceRecord,
    Watermark,
    register_source,
)
from ..sql_provider import SQL_DATABASE_PROVIDER_KEY
from .errors import SqlSourceError
from .guard import assert_select_only, normalize_statement, top_level_words
from .hashing import compared_columns_for, row_hash
from .preview import json_safe
from .runtime import RUNTIME, QUERY_TIMEOUT_SECONDS, SqlSourceRuntime, open_readonly, secrets_of

logger = logging.getLogger("foundryx.autocount")

__all__ = [
    "SqlDbSource",
    "SqlTaskNotConfigured",
    "build_incremental_wrap",
    "register_sql_db_source",
]

# Rows are streamed from the server in blocks of this size; the extract is
# still materialised in memory for mapping, so a hard ceiling fails LOUDLY
# rather than taking the worker out with a MemoryError. Raising it is a
# deliberate act, not a silent degradation (the house line on the record cap).
STREAM_BATCH = 1000
MAX_EXTRACT_ROWS = 200_000

# The cursor key the DB source keeps its own mark under. It lives in
# ``ac_watermark.cursor_json`` rather than ``last_modified_at`` because the
# watermark column need not be a datetime (an ever-increasing id is a perfectly
# good mark) - ``last_modified_at`` is ALSO advanced when it is one, so the
# existing "watermark at" surface keeps working.
CURSOR_MARK = "sqlWatermark"
CURSOR_COLUMN = "sqlWatermarkColumn"

_QUERY_HEAD = 200


class SqlTaskNotConfigured(SqlSourceError):
    """The task cannot run as configured - a SETUP fault (no query, no key
    columns, a connection that is not this tenant's). Loud, never a silent
    empty fetch that would look like "nothing changed"."""


def _encode_mark(value: Any) -> Any:
    """A watermark value as it is stored in ``cursor_json`` (JSON-safe)."""
    if isinstance(value, datetime):
        stamp = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc).isoformat()
    if isinstance(value, (date, dt_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return value


def _decode_mark(value: Any) -> Any:
    """The stored mark back as the type the source column compares against.

    An ISO datetime string round-trips to an aware-UTC datetime so the driver
    binds a real timestamp; anything else (a number, a business code) is bound
    as-is.
    """
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return value


def _as_utc(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    return (
        value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    ).astimezone(timezone.utc)


# ── incremental-fetch statement building (S2 review BLOCKER 2) ──────────────
#
#     !!  MSSQL REJECTS ORDER BY (1033) AND UNNAMED COLUMNS (8155) INSIDE A
#         DERIVED TABLE - AUTOCOUNT IS MSSQL.  !!
# The preview cap (``preview.wrap_preview``) rewrites the user's OWN outermost
# statement rather than wrapping it in a derived table for exactly this
# reason. The incremental predicate is harder to rewrite that way in general
# (it must ADD a WHERE clause, AND-ed with whatever the query already has,
# not just inject a keyword after SELECT) - the derived-table wrap stays, but
# TWO changes close the two known-bad shapes:
#
# 1. A top-level TRAILING ``ORDER BY`` on the saved query is stripped before
#    wrapping - it is meaningless once wrapped (the OUTER statement re-orders
#    by the watermark column) and is exactly what triggers MSSQL error 1033.
#    Left untouched when paired with ``OFFSET``/``FETCH`` (stripping only the
#    ORDER BY there would break that syntax) - documented, not silently
#    "handled": that shape is caught by the save-time validation probe below
#    instead of surprising a live run.
# 2. ``EtlService.update_task`` EXECUTES this exact wrapped statement once at
#    save time (see there) - a query whose SELECT list still trips something
#    the strip does not cover (an unaliased ``COUNT(*)``, duplicate column
#    names) fails as a 422 on save, never a run-time surprise.
_ROW_CLAUSES_AFTER_ORDER = frozenset({"OFFSET", "FETCH"})


def _strip_trailing_order_by(statement: str) -> str:
    """Drop a top-level trailing ``ORDER BY`` - see the module note above."""
    words = top_level_words(statement)
    if {word for word, _, _ in words} & _ROW_CLAUSES_AFTER_ORDER:
        return statement
    order_at: Optional[int] = None
    for i in range(len(words) - 1):
        if words[i][0] == "ORDER" and words[i + 1][0] == "BY":
            order_at = i
    if order_at is None:
        return statement
    return statement[: words[order_at][1]].rstrip()


def build_incremental_wrap(query: str, quoted_column: str, mark: Any) -> str:
    """The exact statement text an incremental (``mark`` given) or mark-less
    initial (``mark is None``) DB-source fetch executes.

    ``mark`` only decides which of the two shapes to build - the actual bound
    value (when there is one) is never spliced into the text, it rides as the
    SQLAlchemy bind parameter ``:mark``. ONE function builds this shape for
    both the real run (``SqlDbSource._statement``) and the save-time
    validation probe (``EtlService.update_task``) - never two copies to drift
    apart.
    """
    inner = _strip_trailing_order_by(query).replace(":", r"\:")
    if mark is None:
        return f"SELECT * FROM ({inner}) AS t ORDER BY t.{quoted_column}"
    return (
        f"SELECT * FROM ({inner}) AS t "
        f"WHERE t.{quoted_column} > :mark ORDER BY t.{quoted_column}"
    )


class SqlDbSource:
    """One entity, one company, one saved query."""

    def __init__(
        self,
        ctx: SourceContext,
        *,
        entity_type: str,
        mode: str = RUN_MODE_MANUAL,
        persist_hashes: bool = True,
        runtime: SqlSourceRuntime = RUNTIME,
        row_limit: int = MAX_EXTRACT_ROWS,
        timeout_s: int = QUERY_TIMEOUT_SECONDS,
        **_extra: Any,
    ) -> None:
        self.entity_type = entity_type
        self.mode = mode
        self.persist_hashes = persist_hashes
        self.row_limit = row_limit
        self.timeout_s = timeout_s
        self._ctx = ctx
        self._runtime = runtime
        self._calls: List[CallRecord] = []

        config = getattr(ctx.entity_config, "source_config", None) or {}
        if not isinstance(config, dict):
            raise SqlTaskNotConfigured("This entity has no database task configured.")
        self.query = normalize_statement(str(config.get("query") or ""))
        if not self.query:
            raise SqlTaskNotConfigured(
                "This entity's database task has no query saved yet."
            )
        self.key_columns = [str(c) for c in (config.get("keyColumns") or []) if str(c).strip()]
        if not self.key_columns:
            raise SqlTaskNotConfigured(
                "This entity's database task has no key columns, so its rows "
                "cannot be correlated."
            )
        self.watermark_column = str(config.get("watermarkColumn") or "").strip() or None
        self.result_columns = [
            str(c) for c in (getattr(ctx.entity_config, "result_columns", None) or [])
        ]
        self.compared_columns = compared_columns_for(
            configured=[str(c) for c in (config.get("comparedColumns") or [])],
            # Before the first successful save-time preview there is nothing to
            # default FROM; falling back to the configured picks keeps the hash
            # meaningful instead of hashing an empty set (which would make every
            # row identical).
            result_columns=self.result_columns
            or [str(c) for c in (config.get("comparedColumns") or [])],
            key_columns=self.key_columns,
        )

        # A STORED connection id, re-resolved tenant- AND provider-scoped on
        # every run (AC-22-29) - never a bare get-by-id.
        connection_id = str(config.get("connectionId") or "").strip()
        if not connection_id:
            raise SqlTaskNotConfigured(
                "This entity's database task has no connection selected."
            )
        conn = ConnectionRepository(ctx.db).get_for_provider(
            ctx.tenant_id, connection_id, SQL_DATABASE_PROVIDER_KEY
        )
        if conn is None:
            raise SqlTaskNotConfigured(
                "The database connection this task reads from was not found."
            )
        self._connection = conn
        conn_config = conn.config_json or {}
        credentials: Dict[str, Any] = {}
        if conn.credentials_json:
            try:
                credentials = decrypt_secret(conn.credentials_json)
            except InvalidToken as exc:
                raise SqlTaskNotConfigured(
                    "This connection's stored credentials can no longer be "
                    "decrypted. Re-enter the database password."
                ) from exc
        self._secrets = secrets_of(conn_config, credentials)
        self.dialect_key = str(conn_config.get("dbType", ""))
        self._engine: Engine = runtime.engine_for(conn.id, conn_config, credentials)

        #     !!  DENY-FIRST, ON THE STORED TEXT, AT EXECUTION TIME.  !!
        # The save-time guard proved what was SAVED. This proves what is about
        # to RUN - a row edited straight into the JSON column, a restored
        # backup, or a guard that got stricter since must not sail through.
        assert_select_only(self.query)

    # ── statement building ───────────────────────────────────────────────────

    def _quoted_watermark(self) -> str:
        """The watermark column, checked against the columns the saved query
        actually returns and quoted by the DIALECT's own preparer.

        Both halves matter: the check is what makes the name non-arbitrary, the
        preparer is what makes it safe to place in SQL text.
        """
        column = self.watermark_column or ""
        if self.result_columns and column not in self.result_columns:
            raise SqlTaskNotConfigured(
                f"The watermark column '{column}' is not one this task's query "
                f"returns. Re-test the query and re-save the task."
            )
        return self._engine.dialect.identifier_preparer.quote(column)

    def _statement(self, mark: Any) -> Tuple[Any, Optional[Dict[str, Any]]]:
        """``(executable, params)`` for this run.

        No watermark column = the saved query verbatim (no params, run through
        ``exec_driver_sql`` exactly as the preview does, so the user's own text
        is never re-parsed).

        With one, the query becomes a derived table (``build_incremental_wrap``)
        so the bound comparison and the ordering apply to ITS result columns
        rather than being spliced into the user's own clauses. Colons in the
        inner text are backslash-escaped because SQLAlchemy's ``text()`` would
        otherwise read a Postgres ``::`` cast or a ``'12:30'`` literal as a
        bind parameter.
        """
        if not self.watermark_column:
            return self.query, None
        column = self._quoted_watermark()
        sql = build_incremental_wrap(self.query, column, mark)
        return sa.text(sql), ({} if mark is None else {"mark": mark})

    # ── fetch ────────────────────────────────────────────────────────────────

    def fetch_changes(self, since: Watermark) -> FetchResult:
        cursor = since.cursor if isinstance(since.cursor, dict) else {}
        stored_mark = cursor.get(CURSOR_MARK) if cursor.get(CURSOR_COLUMN) == self.watermark_column else None
        mark = _decode_mark(stored_mark) if stored_mark is not None else None
        incremental = bool(self.watermark_column) and mark is not None

        started = time.monotonic()
        window_to = datetime.now(timezone.utc)
        try:
            raw_rows = self._read(mark)
        except SqlSourceError as exc:
            self._record_call(started, rows=0, incremental=incremental, error=exc.message)
            raise
        self._record_call(started, rows=len(raw_rows), incremental=incremental)

        records: List[SourceRecord] = []
        hashes: Dict[str, str] = {}
        added = updated = 0
        max_seen: Optional[datetime] = None
        new_mark: Any = stored_mark

        prior = self._prior_hashes(raw_rows)
        for raw in raw_rows:
            stamp = None
            if self.watermark_column:
                value = raw.get(self.watermark_column)
                # ORDER BY means the LAST row carries the max - the DATABASE's
                # own ordering, never a Python comparison across types the
                # driver may have decoded inconsistently. A NULL is skipped
                # here (S2 review SHOULD-FIX 3): Postgres sorts NULLS LAST by
                # default, so a NULL trailing row would otherwise overwrite a
                # real mark with None and strand the cursor - the next run
                # would initial-load forever.
                if value is not None:
                    new_mark = _encode_mark(value)
                stamp = _as_utc(value)
                if stamp is not None and (max_seen is None or stamp > max_seen):
                    max_seen = stamp
            records.append(SourceRecord(raw=json_safe(raw), last_modified=stamp))

            ref = self._source_ref(raw)
            if ref is None:
                # A blank key is a per-RECORD fault: the mapping engine raises
                # the same named IdentityError and stages the row FAILED. It
                # must not take the whole run down, and it has no ref to key a
                # hash on either.
                continue
            value_hash = row_hash(raw, self.compared_columns)
            hashes[ref] = value_hash
            if ref not in prior:
                added += 1
            elif prior[ref] != value_hash:
                updated += 1

        if self.persist_hashes and hashes:
            RowHashRepository(self._ctx.db).upsert_many(
                self._ctx.tenant_id,
                self._ctx.company.id,
                self.entity_type,
                hashes,
                seen_at=window_to,
            )
            # The sync handler committed immediately before calling us and does
            # not write again until after ``record_client_calls`` (which commits
            # of its own accord), so this boundary is ours to own.
            self._ctx.db.commit()

        return FetchResult(
            records=records,
            max_last_modified=max_seen,
            window_from=_as_utc(mark) if incremental else None,
            window_to=window_to,
            reported_total=None,
            rows_scanned=len(raw_rows),
            added_count=added,
            updated_count=updated,
            cursor=(
                {CURSOR_COLUMN: self.watermark_column, CURSOR_MARK: new_mark}
                if self.watermark_column and new_mark is not None
                else None
            ),
        )

    def _read(self, mark: Any) -> List[Dict[str, Any]]:
        executable, params = self._statement(mark)
        rows: List[Dict[str, Any]] = []
        with open_readonly(
            self._engine, timeout_s=self.timeout_s, secrets=self._secrets
        ) as conn:
            streaming = conn.execution_options(
                stream_results=True, max_row_buffer=STREAM_BATCH
            )
            try:
                result = (
                    streaming.execute(executable, params)
                    if params is not None
                    else streaming.exec_driver_sql(executable)
                )
                for partition in result.partitions(STREAM_BATCH):
                    for row in partition:
                        rows.append(dict(row._mapping))
                    if len(rows) > self.row_limit:
                        raise SqlSourceError(
                            f"The extract passed {self.row_limit:,} rows without "
                            f"finishing, so it was stopped and nothing was "
                            f"accepted. Narrow the query or set a watermark "
                            f"column so runs stay incremental."
                        )
            except SqlSourceError:
                raise
            except Exception as exc:  # noqa: BLE001 - every driver has its own class
                from .runtime import sanitize_error

                raise SqlSourceError(sanitize_error(exc, secrets=self._secrets)) from exc
        return rows

    def _source_ref(self, raw: Dict[str, Any]) -> Optional[str]:
        try:
            return flat_source_ref(
                raw,
                database_name=getattr(self._ctx.company, "database_name", ""),
                key_columns=self.key_columns,
                entity_type=self.entity_type,
            )
        except IdentityError:
            return None

    def _prior_hashes(self, raw_rows: Sequence[Dict[str, Any]]) -> Dict[str, str]:
        refs = [ref for ref in (self._source_ref(raw) for raw in raw_rows) if ref]
        if not refs:
            return {}
        return RowHashRepository(self._ctx.db).hashes_for(
            self._ctx.tenant_id, self._ctx.company.id, self.entity_type, refs
        )

    # ── observability (the optional duck-typed seam, plan 22 §2.1) ───────────

    def _record_call(
        self,
        started: float,
        *,
        rows: int,
        incremental: bool,
        error: Optional[str] = None,
    ) -> None:
        """ONE ``CallRecord`` per executed query - dialect, rows, duration and a
        SANITISED head of the SQL. The query text is tenant data, so only a
        bounded head is ever stored (the same rule the preview logger follows).
        """
        self._calls.append(
            CallRecord(
                method="SELECT",
                path=f"sql:{self.dialect_key or self._engine.dialect.name}",
                status_code=None,
                latency_ms=int((time.monotonic() - started) * 1000),
                ok=error is None,
                request={
                    "dialect": self.dialect_key or self._engine.dialect.name,
                    "mode": "incremental" if incremental else "initial",
                    "sql": self.query[:_QUERY_HEAD],
                    "watermarkColumn": self.watermark_column,
                },
                response={"rows": rows},
                error_message=error,
            )
        )

    def drain_activity(self) -> List[CallRecord]:
        calls, self._calls = self._calls, []
        return calls

    def close(self) -> None:
        """The engine is POOLED per connection id and shared across runs, so it
        is deliberately NOT disposed here - closing it would throw away the pool
        every sync. ``SqlSourceRuntime.evict`` is the explicit teardown."""
        return None


# ── registry (D6) ─────────────────────────────────────────────────────────────


def _sql_db_factory(
    ctx: SourceContext,
    *,
    entity_type: str,
    mode: str = RUN_MODE_MANUAL,
    **_extra: Any,
):
    # Every API-path keyword (vendor_entity, record_cap, envelope, …) is
    # deliberately swallowed: a DB task has no vendor endpoint, no record cap
    # and no envelope. The factory contract is uniform; the implementations
    # read only what they use.
    return SqlDbSource(ctx, entity_type=entity_type, mode=mode)


def register_sql_db_source() -> None:
    """Idempotent - the registry is a keyed dict."""
    register_source(SOURCE_IMPL_SQL_DB, _sql_db_factory)
