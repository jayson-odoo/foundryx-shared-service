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

from ..canonical.documents import (
    LINE_QUERY_DOC_KEY_PARAM,
    SQL_DOC_LINES_KEY,
    is_document_entity,
)
from ..client import CallRecord
from ..mapping import IdentityError, flat_source_ref
from ..models import (
    RUN_MODE_MANUAL,
    RUN_MODE_RECONCILE,
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
from .errors import (
    SqlDeleteGuardExceeded,
    SqlDocumentCapExceeded,
    SqlQueryError,
    SqlSourceError,
)
from .guard import (
    assert_select_only,
    escape_incidental_binds,
    normalize_statement,
    query_binds_param,
    top_level_words,
)
from .hashing import compared_columns_for, row_hash
from .preview import json_safe
from .runtime import (
    RUNTIME,
    EXTRACT_TIMEOUT_SECONDS,
    SqlSourceRuntime,
    open_readonly,
    secrets_of,
)

logger = logging.getLogger("foundryx.autocount")

__all__ = [
    "SqlDbSource",
    "SqlTaskNotConfigured",
    "build_document_header_wrap",
    "build_incremental_wrap",
    "register_sql_db_source",
]

# Rows are streamed from the server in blocks of this size; the extract is
# still materialised in memory for mapping, so a hard ceiling fails LOUDLY
# rather than taking the worker out with a MemoryError. Raising it is a
# deliberate act, not a silent degradation (the house line on the record cap).
STREAM_BATCH = 1000
MAX_EXTRACT_ROWS = 200_000

# ── document line-fan-out caps (S5 review SHOULD-FIX 3) ──────────────────────
# A document task runs ONE bound ``lineQuery`` PER CHANGED HEADER, in the same
# read-only session - an N+1 by design (§2.8: the operator authors a scalar
# ``WHERE ... = :doc_key``, so rewriting it into a batched ``IN`` is fragile
# string surgery and was rejected; the batched-``IN`` approach is a backlog
# item instead). Two hard, NAMED caps stand in for it: too many changed
# headers in one pass, and one header carrying an unreasonable number of
# lines (a WHERE clause matching more than its own header, most likely). Both
# fail the WHOLE run - same fail-safe contract as the delete guard above:
# nothing is staged or pushed, and the run's error names which cap tripped.
MAX_DOCUMENT_HEADERS_PER_RUN = 2000
MAX_DOCUMENT_LINES_PER_HEADER = 5000

# ── delete guard (plan 22 §2.5, AC-22-22) ────────────────────────────────────
# A reconcile that would delete more than this fraction (or this many rows,
# whichever is larger) of the known population fails SAFE instead of pushing
# nothing-was-there. A broken query / a connection that returned early both
# look, structurally, exactly like "everything vanished" - the guard is the
# only thing standing between that and a mass unintended delete.
DELETE_GUARD_RATIO = 0.2
DELETE_GUARD_MIN_ABSOLUTE = 50

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


def build_document_header_wrap(
    query: str, quoted_watermark: str, quoted_date_column: str, mark: Any
) -> str:
    """A document header task's statement shape (plan 22 S5) - the SAME
    derived-table wrap as ``build_incremental_wrap``, plus an ALWAYS-ON
    ``fromDate`` floor on the document's own date column.

    ``fromDate`` is a permanent scope boundary ("only sync documents from this
    cutover date onward"), not a one-time first-run lookback - so it is ANDed
    into the predicate on EVERY read, mark-less initial load included. A
    document task always carries a watermark column (validated at save time -
    documents cannot activate without one, S5 decision), so - unlike
    ``build_incremental_wrap`` - there is no watermark-less shape to build
    here.
    """
    inner = _strip_trailing_order_by(query).replace(":", r"\:")
    date_predicate = f"t.{quoted_date_column} >= :from_date"
    if mark is None:
        return (
            f"SELECT * FROM ({inner}) AS t WHERE {date_predicate} "
            f"ORDER BY t.{quoted_watermark}"
        )
    return (
        f"SELECT * FROM ({inner}) AS t "
        f"WHERE t.{quoted_watermark} > :mark AND {date_predicate} "
        f"ORDER BY t.{quoted_watermark}"
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
        # A real extract (this class is NEVER used for the capped raw-query
        # preview - that path is ``preview.run_preview`` directly) must not
        # share the 30s preview budget (S2 review SHOULD-FIX 5) - both the
        # initial-load dry run (``EtlService.preview_task``) and every
        # scheduled/manual RUN read a real table end to end.
        timeout_s: int = EXTRACT_TIMEOUT_SECONDS,
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

        # ── documents only (plan 22 S5) ───────────────────────────────────────
        self.is_document = is_document_entity(entity_type)
        self.line_query: Optional[str] = None
        self.doc_date_column: Optional[str] = None
        self.from_date: Optional[date] = None
        self.line_key_column: Optional[str] = None
        self.line_product_column: Optional[str] = None
        self.line_warehouse_column: Optional[str] = None
        if self.is_document:
            #     !!  A DOCUMENT TASK REQUIRES A HEADER WATERMARK COLUMN.  !!
            # Save-time validation already refuses to persist a document task
            # without one (S5 decision - see `EtlService.validate_source_config`);
            # this is the execution-time backstop for a row edited straight
            # into the JSON column (the same "save-time proved what was
            # SAVED, this proves what is about to RUN" rule the guard re-check
            # above follows).
            if not self.watermark_column:
                raise SqlTaskNotConfigured(
                    "This document task has no watermark column - AutoCount "
                    "updates a header's LastModified whenever a line changes, "
                    "which is how a line-only edit is detected."
                )
            # A document's header key is exactly ONE column - it doubles as
            # the ``:doc_key`` bound value the line query runs with, so a
            # composite header key would be ambiguous about which part to
            # bind (documented design decision, plan 22 S5).
            if len(self.key_columns) != 1:
                raise SqlTaskNotConfigured(
                    "A document task's key must be exactly one column (the "
                    "header's DocKey-equivalent) - it is also what the line "
                    "query's :doc_key binds to."
                )
            self.line_query = normalize_statement(str(config.get("lineQuery") or ""))
            if not self.line_query:
                raise SqlTaskNotConfigured(
                    "This document task has no line query saved yet."
                )
            assert_select_only(self.line_query)
            #     !!  THE LINE QUERY MUST FILTER ON :doc_key.  !!
            # (S5 review BLOCKER 1.) Save-time validation already refuses a
            # lineQuery without the bind; this is the construction-time
            # backstop for a row edited straight into the JSON column.
            # SQLAlchemy silently ignores an UNUSED param passed to
            # ``execute`` - a query missing the bind would otherwise run
            # "successfully" and attach the WHOLE line table to every header.
            if not query_binds_param(self.line_query, LINE_QUERY_DOC_KEY_PARAM):
                raise SqlTaskNotConfigured(
                    "This document task's line query does not filter on the "
                    f"header's key (:{LINE_QUERY_DOC_KEY_PARAM}) - it would run "
                    "once per header against the whole line table instead of "
                    "just that header's own rows."
                )
            # Colons OTHER than the genuine ``:doc_key`` bind (a comment, a
            # literal note or time-of-day) are escaped ONCE here, exactly
            # like the header query's own inner text is escaped before being
            # wrapped (S5 review NIT) - SQLAlchemy's bind scanner is
            # comment/literal-blind, so an unescaped ``:word`` inside one
            # would otherwise demand an extra param the run never supplies.
            self._line_query_exec = escape_incidental_binds(
                self.line_query, LINE_QUERY_DOC_KEY_PARAM
            )
            self.doc_date_column = str(config.get("docDateColumn") or "").strip() or None
            if not self.doc_date_column:
                raise SqlTaskNotConfigured(
                    "This document task has no date column chosen for the "
                    "from-date floor."
                )
            raw_from_date = str(config.get("fromDate") or "").strip()
            if not raw_from_date:
                raise SqlTaskNotConfigured(
                    "This document task has no from-date saved yet."
                )
            try:
                # A real ``date`` object, not the ISO string - so the bind
                # carries the type the driver expects for a date comparison
                # (a bare string param is a MSSQL/pymssql footgun).
                self.from_date = date.fromisoformat(raw_from_date)
            except ValueError as exc:
                raise SqlTaskNotConfigured(
                    "This document task's from-date is not a valid date."
                ) from exc
            self.line_key_column = str(config.get("lineKeyColumn") or "").strip() or None
            self.line_product_column = str(config.get("lineProductColumn") or "").strip() or None
            self.line_warehouse_column = str(config.get("lineWarehouseColumn") or "").strip() or None
            if not self.line_key_column:
                raise SqlTaskNotConfigured(
                    "This document task has no line key column chosen."
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
        # The EXTRACT budget rides the engine's own connect_args (MSSQL's
        # per-query timeout can only be set at connect time) - never the
        # shorter preview default, even though this and a raw query preview
        # may share the same connection id.
        self._engine: Engine = runtime.engine_for(
            conn.id, conn_config, credentials, query_timeout=timeout_s
        )

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
        if not self.result_columns:
            # NIT (S2 review): the OLD ``if self.result_columns and ...``
            # SKIPPED this whole check when empty - a task never previewed
            # (or a corrupted row) ran with an UNCHECKED watermark column
            # instead of failing loudly.
            raise SqlTaskNotConfigured(
                "This task has no cached result columns to check the watermark "
                "column against. Re-test the query and re-save the task."
            )
        if column not in self.result_columns:
            raise SqlTaskNotConfigured(
                f"The watermark column '{column}' is not one this task's query "
                f"returns. Re-test the query and re-save the task."
            )
        return self._engine.dialect.identifier_preparer.quote(column)

    def _quoted_doc_date_column(self) -> str:
        """The document's date-floor column - same checked-then-quoted rule
        as ``_quoted_watermark`` (plan 22 S5)."""
        column = self.doc_date_column or ""
        if not self.result_columns:
            raise SqlTaskNotConfigured(
                "This task has no cached result columns to check the date "
                "column against. Re-test the query and re-save the task."
            )
        if column not in self.result_columns:
            raise SqlTaskNotConfigured(
                f"The date column '{column}' is not one this task's query "
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

        A DOCUMENT header task (plan 22 S5) always carries a watermark column
        (validated at construction) AND an always-on ``fromDate`` floor -
        ``build_document_header_wrap`` ANDs both into the ONE derived-table
        predicate.
        """
        if self.is_document:
            wm_column = self._quoted_watermark()
            date_column = self._quoted_doc_date_column()
            sql = build_document_header_wrap(self.query, wm_column, date_column, mark)
            params = {"from_date": self.from_date}
            if mark is not None:
                params["mark"] = mark
            return sa.text(sql), params
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

        #     !!  RECONCILE (AND A NO-WATERMARK TASK) ALWAYS FULL-EXTRACTS.  !!
        # Reconcile explicitly ignores the stored mark for FILTERING (plan §2.5
        # "full <query> extract, ignore watermark") - it still ADVANCES the
        # watermark from whatever it reads, if the column is configured (below).
        # A task with no watermark column has nothing to filter by in the first
        # place, so every one of its "incremental" runs is mechanically this
        # same full-extract diff (AC-22-12/S3 item 6) - the MODE recorded on the
        # run stays whatever the caller asked for (``incremental``), only the
        # MECHANICS change here.
        full_extract = self.mode == RUN_MODE_RECONCILE or not self.watermark_column
        read_mark = None if full_extract else mark
        incremental = bool(self.watermark_column) and read_mark is not None

        started = time.monotonic()
        window_to = datetime.now(timezone.utc)
        try:
            raw_rows = self._read(read_mark)
        except SqlSourceError as exc:
            self._record_call(started, rows=0, incremental=incremental, error=exc.message)
            raise
        self._record_call(started, rows=len(raw_rows), incremental=incremental)

        records: List[SourceRecord] = []
        hashes: Dict[str, str] = {}
        added = updated = 0
        max_seen: Optional[datetime] = None
        new_mark: Any = stored_mark

        # A full extract diffs against the WHOLE known population (a ref
        # never seen in THIS batch is exactly how a delete becomes visible);
        # a partial incremental only ever needs the refs it actually touched.
        known = (
            RowHashRepository(self._ctx.db).all_hashes(
                self._ctx.tenant_id, self._ctx.company.id, self.entity_type
            )
            if full_extract
            else self._prior_hashes(raw_rows)
        )
        current_refs: set[str] = set()
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
                # would initial-load forever. This also covers reconcile's
                # "the watermark also advances when the column is present"
                # (plan §2.5 item 3) - the loop is unconditioned on mode.
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
            current_refs.add(ref)
            value_hash = row_hash(raw, self.compared_columns)
            hashes[ref] = value_hash
            if ref not in known:
                added += 1
            elif known[ref] != value_hash:
                updated += 1

        #     !!  DELETE GUARD - FAIL SAFE, NOTHING PROPAGATES (AC-22-22).  !!
        # Raised BEFORE any hash write below, so a run this catches stages and
        # pushes NOTHING at all (not just the deletes) - a broken query or a
        # connection that dropped mid-extract must never read as "everything
        # else vanished too".
        #
        #     !!  A DOCUMENT NEVER COMPUTES DELETE INTENTS AT ALL (plan 22 S5).  !!
        # ``fromDate`` bounds the extract to a WINDOW, not the whole standing
        # set - a header outside today's window is indistinguishable, from
        # inside this diff, from one genuinely gone at the source. Computing
        # (and guarding) delete_refs for a windowed population would be
        # actively wrong, not just unnecessary, so documents skip this whole
        # block; ``sync._stage_deletes`` mirrors the same skip at staging.
        delete_refs: List[str] = []
        if full_extract and known and not self.is_document:
            #     !!  A ZERO-ROW FULL EXTRACT IS NEVER A GENUINE TOTAL WIPE.  !!
            # (S3 review BLOCKER 2.) The ratio/absolute guard below is INERT on
            # a small (<=50-row) known population: e.g. known=20 gives a
            # threshold of max(0.2*20, 50) = 50, so 20 delete refs - EVERY known
            # row - sails straight through. A broken query, a bad connection or
            # an empty result set both look, structurally, identical to "the
            # whole table vanished"; this absolute rule catches that shape
            # regardless of population size, raised BEFORE the ratio check (and
            # before any hash write) so nothing is staged or pushed either way.
            if not raw_rows:
                raise SqlDeleteGuardExceeded(
                    f"This run returned 0 rows while {len(known)} previously-known "
                    f"row(s) exist for this entity - nothing was staged or pushed. "
                    f"This looks like a broken query or connection, not a genuine "
                    f"full deletion. Check the query and the connection, then "
                    f"re-run reconcile."
                )
            delete_refs = sorted(ref for ref in known if ref not in current_refs)
            threshold = max(DELETE_GUARD_RATIO * len(known), DELETE_GUARD_MIN_ABSOLUTE)
            if len(delete_refs) > threshold:
                raise SqlDeleteGuardExceeded(
                    f"This run would delete {len(delete_refs)} of {len(known)} "
                    f"previously-known row(s) - over the safety threshold "
                    f"({threshold:.0f}). Nothing was staged or pushed. Check the "
                    f"query and the connection, then re-run reconcile."
                )

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
            window_from=_as_utc(read_mark) if incremental else None,
            window_to=window_to,
            reported_total=None,
            rows_scanned=len(raw_rows),
            added_count=added,
            updated_count=updated,
            delete_refs=delete_refs,
            # Threaded out alongside `delete_refs` (S3 review BLOCKER 1) so the
            # caller can cancel a STALE parked delete intent the instant its
            # ref reappears - always populated (not gated on `full_extract`),
            # so an incremental run's reappearance cancels a stale intent too.
            current_refs=sorted(current_refs),
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

                # SqlQueryError (not the base class, S2 review SHOULD-FIX 4) -
                # this IS "the source rejected the statement" (a dropped
                # table, a permission change since save), the same class of
                # failure ``preview.py``'s own execution path raises, and the
                # ONLY way it maps to a 400 instead of falling through to an
                # unhandled 500 at ``EtlService.preview_task``.
                raise SqlQueryError(sanitize_error(exc, secrets=self._secrets)) from exc

            #     !!  LINES - ONE lineQuery PER CHANGED HEADER, SAME SESSION.  !!
            # (plan 22 S5, AC-22-24.) ``rows`` above IS exactly the "changed
            # headers" set - the incremental WHERE clause already filtered to
            # it, or (initial/reconcile) it is every header in the fromDate
            # window, which needs its lines regardless. Nested under
            # ``SQL_DOC_LINES_KEY`` so ``MappingEngine``'s EXISTING nested-
            # detail mechanism (built for the API path's vendor envelope)
            # reads it with zero engine changes - see ``mapping.flat_profile``.
            if self.is_document:
                #     !!  CAP THE FAN-OUT (S5 review SHOULD-FIX 3).  !!
                # This is an N+1 by design (module doc) - a run with an
                # unbounded number of changed headers would hold that many
                # extra round trips open in one pass. Fails the WHOLE run
                # (nothing staged/pushed), same as the delete guard.
                if len(rows) > MAX_DOCUMENT_HEADERS_PER_RUN:
                    raise SqlDocumentCapExceeded(
                        f"This run would fetch lines for {len(rows):,} documents in "
                        f"one pass - over the safety cap "
                        f"({MAX_DOCUMENT_HEADERS_PER_RUN:,}). Nothing was staged or "
                        f"pushed. Narrow the from-date window and re-run."
                    )
                key_column = self.key_columns[0]
                for header in rows:
                    doc_key_value = header.get(key_column)
                    header[SQL_DOC_LINES_KEY] = self._read_lines(conn, doc_key_value)
        return rows

    def _read_lines(self, conn: Any, doc_key_value: Any) -> List[Dict[str, Any]]:
        """One guarded, bound SELECT for a single header's lines (plan 22 S5).

        A second, independently-guarded statement - NEVER concatenated onto
        the header query. A blank/None ``doc_key_value`` (a header whose key
        column somehow came back empty) still runs the query bound to None -
        it is expected to match nothing, and the header itself is a per-
        record identity failure the mapping engine will name; this method
        must not raise for it.
        """
        try:
            result = conn.execute(
                sa.text(self._line_query_exec), {"doc_key": doc_key_value}
            )
            rows = [dict(row._mapping) for row in result.fetchall()]
        except Exception as exc:  # noqa: BLE001 - every driver has its own class
            from .runtime import sanitize_error

            raise SqlQueryError(
                sanitize_error(exc, secrets=self._secrets)
            ) from exc
        #     !!  CAP ONE HEADER'S OWN LINE COUNT (S5 review SHOULD-FIX 3).  !!
        # A ``lineQuery`` matching far more than its own header's rows (a
        # ``WHERE`` clause that is too loose, or missing entirely) is caught
        # here rather than silently attaching thousands of unrelated rows to
        # one document. Same fail-safe contract: nothing is staged or pushed.
        if len(rows) > MAX_DOCUMENT_LINES_PER_HEADER:
            raise SqlDocumentCapExceeded(
                f"Document '{doc_key_value}' has {len(rows):,} line rows - over "
                f"the safety cap ({MAX_DOCUMENT_LINES_PER_HEADER:,}). Nothing was "
                f"staged or pushed. Check the line query's WHERE clause."
            )
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
