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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import sqlalchemy as sa
from cryptography.fernet import InvalidToken
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.secrets import decrypt_secret

from ..canonical.documents import (
    LINE_QUERY_DOC_KEY_PARAM,
    SQL_DOC_LINES_KEY,
    is_document_entity,
)
from ..client import CallRecord
from ..formula import FormulaError, evaluate_row_filter
from ..mapping import IdentityError, flat_source_ref
from ..models import (
    RUN_MODE_MANUAL,
    RUN_MODE_RECONCILE,
    SOURCE_IMPL_SQL_DB,
    AcRowHash,  # noqa: F401 - documents what ``persist_hashes`` writes
)
from ..presets import LINE_COUNT_FINGERPRINT_COLUMN
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
    SqlFilterFormulaError,
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
    "PageCursor",
    "PageResult",
    "SqlDbSource",
    "SqlTaskNotConfigured",
    "build_document_header_wrap",
    "build_incremental_wrap",
    "build_paged_wrap",
    "decode_mark",
    "register_sql_db_source",
]

# Rows are streamed from the server in blocks of this size; the extract is
# still materialised in memory for mapping, so a hard ceiling fails LOUDLY
# rather than taking the worker out with a MemoryError. Raising it is a
# deliberate act, not a silent degradation (the house line on the record cap).
STREAM_BATCH = 1000
# Guards an UNPAGED read (a no-watermark master, the API path's own record cap
# is separate) and a SINGLE PAGE (plan sprint-5/03 S1) - a page is already
# bounded by ``AUTOCOUNT_PAGE_SIZE``, so this only ever fires on a tie group
# vastly larger than any sane page size.
MAX_EXTRACT_ROWS = 200_000

# ── document line-fan-out cap (S5 review SHOULD-FIX 3) ───────────────────────
# A document task runs ONE bound ``lineQuery`` PER CHANGED HEADER, in the same
# read-only session - an N+1 by design (§2.8: the operator authors a scalar
# ``WHERE ... = :doc_key``, so rewriting it into a batched ``IN`` is fragile
# string surgery and was rejected; the batched-``IN`` approach is a backlog
# item instead). One header carrying an unreasonable number of lines (a WHERE
# clause matching more than its own header, most likely) fails the WHOLE run -
# same fail-safe contract as the delete guard above: nothing is staged or
# pushed, and the run's error names the cap. The sibling "too many changed
# headers in one pass" cap (``MAX_DOCUMENT_HEADERS_PER_RUN``) is REMOVED (plan
# sprint-5/03 S1, AC-03-01): paging is now the bound on how many headers a
# single read can return, so a fixed count-of-documents ceiling on top of it
# would only ever fire below a pass that paging already keeps safe.
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
# The key-column SHAPE the top-level ``lastKey`` was last recorded under
# (S2, review round 5) - a fingerprint, not a resume value itself.
# ``key_columns`` determines BOTH ``lastKey``'s own shape (scalar vs list,
# S2's multi-key generalisation) AND ``source_ref``'s identity SCHEME - a
# reshape (grown, shrunk, or a same-count rename) makes a stored value
# recorded under the OLD columns unsafe to resume from (wrong shape, or a
# shape that still "fits" but means something else entirely, e.g. a
# same-cardinality rename). ``sync.py``'s run loop is where a MISMATCH here
# also triggers the wider identity reset (clearing ``ac_row_hash``, never
# just this cursor) - this module only carries the fingerprint and refuses
# to resume against a mismatched one.
CURSOR_KEY_COLUMNS = "sqlKeyColumns"

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


# Public alias (R-NIT, review round 2): ``sync.py`` needs this to decode a
# stored mark for its OWN monotonic top-level-watermark comparison - importing
# a leading-underscore name from another module read like reaching into a
# private implementation detail it should not touch. Kept as an alias (not a
# rename) so every one of this module's OWN call sites, which predate the
# public name, needs no churn.
decode_mark = _decode_mark


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


def _lexicographic_key_predicate(quoted_keys: List[str]) -> str:
    """``t.k0 > :last_key0 OR (t.k0 = :last_key0 AND (t.k1 > :last_key1 OR
    ...))`` - one key column degenerates to ``t.k > :last_key`` (the single
    bind name ``last_key`` kept, unindexed, so a single-key task's generated
    SQL text is byte-identical to before round 4's multi-key generalisation,
    S2)."""
    n = len(quoted_keys)

    def build(idx: int) -> str:
        column = quoted_keys[idx]
        bind = "last_key" if n == 1 else f"last_key{idx}"
        if idx == n - 1:
            return f"t.{column} > :{bind}"
        return f"(t.{column} > :{bind} OR (t.{column} = :{bind} AND {build(idx + 1)}))"

    return build(0)


def build_paged_wrap(
    query: str,
    quoted_watermark: str,
    quoted_date_column: Optional[str],
    mark: Any,
    *,
    dialect: str,
    page_size: int,
    quoted_key: Optional[Union[str, Sequence[str]]] = None,
    last_key: Any = None,
) -> str:
    """The PAGED statement shape (plan sprint-5/03 S1, AC-03-07; composite
    seek ordering, review round 3 R2-B1) - the SAME derived-table wrap as
    ``build_incremental_wrap``/``build_document_header_wrap``, plus a
    bounded, ORDERED page.

    ``quoted_key`` (round 3) is the task's key column, seeked ALONGSIDE the
    watermark - ``ORDER BY t.<wm>, t.<key>`` with a compound predicate
    ``(t.<wm> > :mark) OR (t.<wm> = :mark AND t.<key> > :last_key)``. This
    REPLACES round 2's ``>=``-plus-Python-exclusion design entirely: that
    design paged a same-mark tie group by re-reading the boundary and
    dropping already-taken refs in Python, which only works if the DATABASE
    returns ties in the SAME relative order on every statement - a real
    engine gives NO such guarantee for an ``ORDER BY`` on a single column
    with duplicate values, so a row could be silently skipped (or, on a
    reconcile, misread as a phantom delete). A STRICT ``>`` seek on a fully
    deterministic ``(watermark, key)`` ordering has no such gap: exactly one
    statement per page, always bounded by ``:page_size``, regardless of how
    large a same-mark tie group is.

    ``quoted_key is None`` keeps the OLD watermark-only shape byte-for-byte
    (every caller that has not been updated to pass one) - the inclusive
    ``>=`` bound plus Python-side exclusion this used to require is now ONLY
    reachable this way, kept for a caller with no key to seek on (there is
    none in this codebase any more; ``SqlDbSource.fetch_page`` always has a
    key column, construction-time-guarded already).

    ``page_size`` rides as the bound parameter ``:page_size`` - NEVER
    spliced into the text - so a huge page size can never widen the SQL
    shape itself, only the bound value; ``last_key`` rides as ``:last_key``
    the same way, never spliced (a business key can be arbitrary tenant
    text).

    ``quoted_date_column is None`` = a paged MASTER (no from-date floor);
    given = a document task's permanent ``fromDate`` scope boundary, ANDed
    with the seek predicate exactly like ``build_document_header_wrap`` -
    the seek predicate is parenthesised as ONE group when it is ANDed with
    the date floor (AND binds tighter than OR in SQL; an ungrouped
    ``date_floor AND wm > mark OR (...)`` would silently drop the date
    floor off the second branch of the seek). ``mark is None`` = the first
    page of a pass - no mark predicate (and no seek predicate) at all.
    """
    if page_size <= 0:
        raise SqlSourceError("page_size must be a positive bind value")
    inner = _strip_trailing_order_by(query).replace(":", r"\:")

    quoted_keys: List[str] = (
        [quoted_key] if isinstance(quoted_key, str) else list(quoted_key or [])
    )

    seek_predicate: Optional[str] = None
    if mark is not None:
        if quoted_keys:
            seek_predicate = (
                f"(t.{quoted_watermark} > :mark) OR "
                f"(t.{quoted_watermark} = :mark AND {_lexicographic_key_predicate(quoted_keys)})"
            )
        else:
            seek_predicate = f"t.{quoted_watermark} >= :mark"

    predicates: List[str] = []
    if quoted_date_column is not None:
        predicates.append(f"t.{quoted_date_column} >= :from_date")
    if seek_predicate is not None:
        needs_grouping = quoted_date_column is not None and bool(quoted_keys)
        predicates.append(f"({seek_predicate})" if needs_grouping else seek_predicate)
    where = f" WHERE {' AND '.join(predicates)}" if predicates else ""

    order_by = ", ".join(
        [f"t.{quoted_watermark}"] + [f"t.{column}" for column in quoted_keys]
    )
    if dialect == "mssql":
        return f"SELECT TOP (:page_size) * FROM ({inner}) AS t{where} ORDER BY {order_by}"
    return f"SELECT * FROM ({inner}) AS t{where} ORDER BY {order_by} LIMIT :page_size"


@dataclass
class PageCursor:
    """Where a paged pass resumes from (plan sprint-5/03 S1/S2, AC-03-01..04).

    No schema change (D7): ``sync.py`` reads/writes this shape straight to
    ``AcWatermark.cursor_json`` (``from_watermark_row``/its inverse in the
    run loop) - this dataclass is only the in-memory carrier ``fetch_page``
    takes and returns pieces of.

    ``PageCursor()`` (every field default) IS the first page of a fresh
    pass: no mark, nothing excluded, nothing done yet.
    """

    mark: Any = None
    # The LAST KEY-COLUMN value taken at ``mark`` (composite seek ordering,
    # review round 3 R2-B1) - together ``(mark, last_key)`` is the exact
    # ``(watermark, key)`` position the SEEK predicate resumes strictly
    # AFTER. REPLACES round 2's ``tie_refs`` ref-set exclusion entirely: a
    # deterministic ``ORDER BY t.<wm>, t.<key>`` plus a strict ``>`` seek
    # never needs to re-read a boundary and drop already-taken refs in
    # Python, which depended on the database returning ties in a STABLE
    # order across separate statements - a guarantee no engine actually
    # makes for an ``ORDER BY`` on a column with duplicate values.
    last_key: Any = None
    pass_kind: str = RUN_MODE_MANUAL
    pass_started_at: Optional[datetime] = None
    pages_done: int = 0
    # Cumulative rows scanned across the WHOLE pass so far (review round 2,
    # R-NIT) - carried across runs the same way ``pages_done`` already is, so
    # the zero-rows delete guard can tell "this pass has never read anything"
    # apart from "a LATER page's own read happened to be empty" without
    # loading the pass's own row count from anywhere but the cursor itself.
    rows_scanned: int = 0

    @classmethod
    def from_watermark_row(
        cls,
        watermark_row: Any,
        mode: str,
        *,
        watermark_column: str,
        key_columns: Sequence[str] = (),
    ) -> "PageCursor":
        """Resume an UNFINISHED pass matching ``mode``, or start a fresh one.

        A reconcile tick firing while an initial/incremental pass is still
        open continues THAT pass first (its ``kind`` will not match
        ``reconcile``) - the reconcile is simply re-armed by
        ``next_run_times`` and fires again once the open pass completes.

        ``column_matches`` (F4, review round 2) gates BOTH branches now - a
        resumed pass whose watermark column no longer matches the task's
        CURRENT one belongs to a comparison that no longer exists (an
        operator switched columns mid-pass) and must start fresh exactly
        like a never-run task would, never resume with the old column's
        stale mark under the new column's semantics. Only the fresh-pass
        branch carried this check before; the resume branch did not, which
        is the bug.

        The pass's OWN position (``pass.mark``/``pass.lastKey``/
        ``pass.rowsScanned``, review round 2 F3 + round 3 R2-B1) is what a
        RESUME reads - never the top-level ``CURSOR_MARK``/``lastKey``,
        which is a SEPARATE, purely monotonic public position (``sync.py``'s
        own ``_advance_mark_and_ties``) that a reconcile pass does not move
        until it completes. The top-level pair is what the FRESH-pass
        branch below still reads, to resume a plain incremental/manual run
        from wherever the public position last stood - the legacy shape,
        unchanged.

        !!  A MARK WITH NO ``lastKey`` IS NOT RESUMABLE (round 3 R2-B1).  !!
        Round 2 stored ``mark``/``tieRefs`` but never a ``lastKey`` - a row
        left mid-pass by that code (or the round-2 legacy shape at the top
        level) has a ``mark`` with nothing to seek a KEY from, so resuming
        it under the composite predicate would silently re-admit or drop
        whatever shares that exact mark. Both branches below treat a stored
        ``mark`` with no matching ``lastKey`` as equivalent to no stored
        position at all - the pass restarts fresh. This is a LOCAL-lane-only
        concern (only a lane DB mid-migration between review rounds carries
        such a row); the real company has never run either round yet.

        !!  A ``lastKey`` SHAPED FOR A DIFFERENT ``key_columns`` IS ALSO NOT
            RESUMABLE (S2-a, review round 5 - a second line of defence).  !!
        A stored ``lastKey`` was recorded under whatever ``key_columns`` the
        task had AT THE TIME - a task reconfigured since (a column added or
        removed, changing SCALAR vs LIST; or, same count, a different
        column entirely) leaves a value whose shape no longer matches
        ``len(key_columns)``. Blindly threading it through would eventually
        reach a bind step that has to guess how to split it - `list()`-ing a
        stored STRING would slice it into individual CHARACTERS, not
        columns. Any mismatch is treated exactly like nothing stored: a
        fresh full read. (The PRIMARY defence against a reshape is
        ``sync.py``'s own identity reset, which clears the stale position
        - and the now-mis-scoped ``ac_row_hash`` population - the moment a
        run detects one; this guard only prevents a residual bad bind if
        that reset is somehow bypassed.)
        """
        cursor = watermark_row.cursor_json if isinstance(watermark_row.cursor_json, dict) else {}
        pass_state = cursor.get("pass") if isinstance(cursor.get("pass"), dict) else None
        now = datetime.now(timezone.utc)
        column_matches = cursor.get(CURSOR_COLUMN) == watermark_column
        key_count = len(key_columns)

        def _last_key_shape_ok(value: Any) -> bool:
            if value is None:
                return True
            if key_count > 1:
                return isinstance(value, list) and len(value) == key_count
            return not isinstance(value, (list, tuple))

        if (
            pass_state is not None
            and column_matches
            and pass_state.get("kind") == mode
            and not pass_state.get("complete", False)
            and (pass_state.get("mark") is None or pass_state.get("lastKey") is not None)
            and _last_key_shape_ok(pass_state.get("lastKey"))
        ):
            started_raw = pass_state.get("startedAt")
            started = _decode_mark(started_raw) if started_raw else now
            if not isinstance(started, datetime):
                started = now
            return cls(
                mark=pass_state.get("mark"),
                last_key=pass_state.get("lastKey"),
                pass_kind=mode,
                pass_started_at=started,
                pages_done=int(pass_state.get("pagesDone") or 0),
                rows_scanned=int(pass_state.get("rowsScanned") or 0),
            )
        # A brand new pass. A RECONCILE always restarts extraction from
        # scratch regardless of any stored incremental mark (D2/plan §2.5
        # "full <query> extract, ignore watermark"); an incremental/manual
        # pass resumes from the STORED watermark mark, when it was left by
        # THIS SAME watermark column (a reconfigured column's stored mark
        # belongs to a different comparison and must never be reused) AND
        # carries a ``lastKey`` to seek from (see the module note above).
        # The cursor keeps the LEGACY keys (``CURSOR_COLUMN``/``CURSOR_MARK``
        # - live rows on the real company already carry them; renaming
        # would orphan every task's mark and force a full re-read) -
        # ``lastKey`` and ``pass`` are the only ADDED top-level keys.
        start_mark = None
        start_last_key = None
        if (
            mode != RUN_MODE_RECONCILE
            and column_matches
            and cursor.get("lastKey") is not None
            and _last_key_shape_ok(cursor.get("lastKey"))
        ):
            start_mark = cursor.get(CURSOR_MARK)
            start_last_key = cursor.get("lastKey")
        return cls(
            mark=start_mark,
            last_key=start_last_key,
            pass_kind=mode,
            pass_started_at=now,
            pages_done=0,
            rows_scanned=0,
        )


@dataclass
class PageResult:
    """One page's worth of extraction (plan sprint-5/03 S1/S2, AC-03-01/09).

    ``records`` carries ONLY changed/new rows (change-only staging, D2) -
    lines fetched for a document only among these. ``unchanged_refs`` and
    ``hashes`` (every fetched ref, changed or not) are what ``sync.py``'s
    run loop needs to keep ``ac_row_hash`` truthful without restaging
    anything: an upsert for the changed ones, a seen-stamp touch for the
    rest.
    """

    records: List["SourceRecord"] = field(default_factory=list)
    # EVERY candidate row on this page, regardless of changed/unchanged
    # status (R2-S1, review round 3) - a preview immediately after a real
    # run has already hashed the page, so ``records`` (change-only by
    # design, D2) would report 0 rows for a task that plainly has some;
    # ``EtlService._extract_and_map``'s preview path maps THIS instead,
    # while the run loop keeps using ``records`` (change-only staging is
    # unaffected). Lines are attached for a document's row here too, same
    # as ``records`` - see the note in ``fetch_page`` on the one exception
    # (an UNCHANGED document row's lines are not re-fetched).
    preview_records: List["SourceRecord"] = field(default_factory=list)
    # A SET (R-S3, review round 2) - the caller (``sync.py``) tests membership
    # against this on every hashed ref; a list made that an O(n) scan per ref
    # instead of O(1).
    unchanged_refs: set = field(default_factory=set)
    hashes: Dict[str, str] = field(default_factory=dict)
    last_mark: Any = None
    # The key-column value of the LAST row on this page (composite seek
    # ordering, review round 3 R2-B1) - paired with ``last_mark`` as the
    # exact ``(mark, last_key)`` position the NEXT page's cursor seeks
    # strictly after. Replaces ``tie_refs`` entirely.
    last_key: Any = None
    rows_scanned: int = 0
    added: int = 0
    updated: int = 0
    complete: bool = False


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
        self.filter_formula: Optional[str] = None
        self._last_skipped_by_filter = 0
        # The headers `filterFormula` dropped this run (B4, sprint-5/02
        # review round) - `fetch_changes` needs these to keep a filtered-out
        # header from ever reading as a "vanished" delete, and to drop its
        # stale row hash so a later unfiltered re-appearance stages as a
        # fresh ADD, not a phantom update.
        self._filtered_out_headers: List[Dict[str, Any]] = []
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
            # sprint-5/02 (AC-02-05): the `lineKeyColumn`/`lineProductColumn`/
            # `lineWarehouseColumn` pickers are gone - a document's line
            # fields are persisted, operator-editable `ac_field_mapping` rows
            # now (`CompanyService.replace_mapping`), never source_config
            # picks. Nothing to validate or store here any more.
            # sprint-5/02 (AC-02-11) - a row-set filter (e.g. the PO/SPO
            # sibling-task split), evaluated against the RAW header row
            # before line fetch. Blank/absent = every header passes.
            self.filter_formula = str(config.get("filterFormula") or "").strip() or None

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

    def _quoted_keys(self) -> List[str]:
        """EVERY key column, checked-then-quoted the same way the watermark
        column is - a paged task seeks on ``(watermark, key0, key1, ...)``
        lexicographically (S2, review round 4 - supersedes round 3's F5,
        which seeked on ``keyColumns[0]`` alone: two rows sharing
        ``(watermark, key0)`` but differing in a LATER key column silently
        collapsed onto the same seek frontier, so one of them was never
        seen again once the other had already consumed that exact
        position)."""
        if not self.result_columns:
            raise SqlTaskNotConfigured(
                "This task has no cached result columns to check the key "
                "columns against. Re-test the query and re-save the task."
            )
        quoted: List[str] = []
        for column in self.key_columns:
            if column not in self.result_columns:
                raise SqlTaskNotConfigured(
                    f"The key column '{column}' is not one this task's query "
                    f"returns. Re-test the query and re-save the task."
                )
            quoted.append(self._engine.dialect.identifier_preparer.quote(column))
        return quoted

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

            ref = self.source_ref(raw)
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
        #     !!  A DOCUMENT NOW COMPUTES DELETE INTENTS TOO (sprint-5/02, S3,
        #         AC-02-13 - reverses the plan-22 S5 decision below).  !!
        # The plan-22 S5 reasoning was: `fromDate` bounds the extract to a
        # WINDOW, not the whole standing set, so a header outside today's
        # window would be indistinguishable from one genuinely gone. That
        # reasoning does not survive scrutiny: `fromDate` is a PERMANENT scope
        # boundary (module docstring), never a moving one-time lookback, and
        # AutoCount dates do not travel backwards - a header that was ever
        # inside the window stays inside it forever, so its disappearance from
        # a later extract IS genuine evidence of deletion, not a window
        # artifact. `sync._stage_deletes` mirrors this reversal (no more
        # document special-case there either).
        #     !!  A FILTERED-OUT HEADER IS NEVER A DELETE CANDIDATE (B4,
        #         AC-02-11).  !!
        # `_read` already dropped these rows before they ever reached
        # `current_refs` above - indistinguishable, from here, from a header
        # genuinely gone at source. Compute their refs the SAME way a kept
        # row's ref is computed, and treat them as neither current nor
        # missing: excluded from the delete diff below, and their stale hash
        # (if the filter was only just added/tightened) is dropped so a
        # later unfiltered re-appearance stages as a fresh ADD, not a
        # phantom update.
        filtered_refs: set[str] = {
            ref
            for ref in (self.source_ref(header) for header in self._filtered_out_headers)
            if ref is not None
        }

        delete_refs: List[str] = []
        if full_extract and known:
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
            delete_refs = sorted(
                ref for ref in known if ref not in current_refs and ref not in filtered_refs
            )
            threshold = max(DELETE_GUARD_RATIO * len(known), DELETE_GUARD_MIN_ABSOLUTE)
            if len(delete_refs) > threshold:
                raise SqlDeleteGuardExceeded(
                    f"This run would delete {len(delete_refs)} of {len(known)} "
                    f"previously-known row(s) - over the safety threshold "
                    f"({threshold:.0f}). Nothing was staged or pushed. Check the "
                    f"query and the connection, then re-run reconcile."
                )

        # Only ever finds anything on a FULL extract (review-round nit): on an
        # incremental run `known` is `self._prior_hashes(raw_rows)` - built
        # from the POST-FILTER `raw_rows` this method already returned above,
        # so it can never contain a filtered-out ref to begin with. That is
        # fine, not a gap: an incremental run's filtered-out header was never
        # a "changed header" this pass (the watermark WHERE clause excluded
        # it), so it cannot be carrying a stale hash from THIS run's extract
        # either. The case this drop exists for - a filter newly added/
        # tightened so a PREVIOUSLY-hashed header now falls outside it - only
        # ever surfaces on a reconcile's full-population diff (F1 covers the
        # sibling case: editing the filter itself re-baselines the whole
        # entity's hashes at save time).
        stale_filtered_refs = [ref for ref in filtered_refs if ref in known]
        if self.persist_hashes and (hashes or stale_filtered_refs):
            if hashes:
                RowHashRepository(self._ctx.db).upsert_many(
                    self._ctx.tenant_id,
                    self._ctx.company.id,
                    self.entity_type,
                    hashes,
                    seen_at=window_to,
                )
            if stale_filtered_refs:
                RowHashRepository(self._ctx.db).delete_many(
                    self._ctx.tenant_id,
                    self._ctx.company.id,
                    self.entity_type,
                    stale_filtered_refs,
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
            skipped_by_filter=self._last_skipped_by_filter,
        )

    def fetch_page(self, cursor: "PageCursor") -> "PageResult":
        """One page of a paged pass (plan sprint-5/03 S1/S2, AC-03-01..04/09;
        composite seek ordering, review round 3 R2-B1).

        ``fetch_changes`` stays the thin, unpaged, whole-population read for
        a non-watermarked master and the API path; a WATERMARKED task's run
        loop (``sync.py``) calls this instead, once per page, threading
        ``cursor`` through so a pass can span several runs (D3) without ever
        re-reading a page already staged. Requires a watermark column - the
        caller only reaches this method for a task that has one.

        ONE statement, ALWAYS - ``ORDER BY t.<wm>, t.<k0>, t.<k1>, ...`` over
        EVERY key column (S2, review round 4 - `key_columns[0]` alone let
        two rows sharing `(watermark, key0)` but differing in a later
        column collapse onto the same seek frontier), checked/quoted the
        same way as the watermark, with a strict lexicographic SEEK
        predicate that makes the read order fully
        deterministic, so a page never needs to re-read a boundary and drop
        already-taken rows in Python (round 2's design, which relied on the
        database returning ties in a stable order across separate
        statements - a guarantee no engine actually makes for duplicate
        ``ORDER BY`` values, and the reason a row could be silently skipped,
        or misread as a phantom delete on a reconcile).
        """
        from app.config import settings as _settings  # read at CALL time, D-note

        page_size = int(getattr(_settings, "autocount_page_size", 2000) or 2000)

        wm_column = self._quoted_watermark()
        key_columns = self._quoted_keys()
        date_column = self._quoted_doc_date_column() if self.is_document else None
        dialect = self._engine.dialect.name

        sql = build_paged_wrap(
            self.query, wm_column, date_column, cursor.mark,
            dialect=dialect, page_size=page_size,
            quoted_key=key_columns, last_key=cursor.last_key,
        )
        #     !!  BIND ``page_size + 1`` - PEEK ONE ROW AHEAD, ONE STATEMENT
        #         PER PAGE.  !!
        # ``complete`` must be knowable from THIS page's own read alone - an
        # exact-multiple population (e.g. 9 rows at page_size=3) would
        # otherwise need a TRAILING, all-empty page just to confirm nothing
        # remains, which is a real extra round trip the "one statement per
        # page" guarantee (T1(b)) must not pay. Fetching one row beyond
        # ``page_size`` answers "is there more" for free; the extra row is
        # trimmed back off before anything downstream ever sees it - it
        # belongs to the NEXT page, re-read there via the normal seek.
        params: Dict[str, Any] = {"page_size": page_size + 1}
        if self.is_document:
            params["from_date"] = self.from_date
        if cursor.mark is not None:
            #     !!  BIND A NAIVE INSTANT, NOT AN OFFSET-DECORATED ONE.  !!
            # A driver that stores a plain datetime column (no offset in its
            # own text/native form) and is handed an aware ``+00:00``-
            # suffixed value can render it as a DIFFERENT, textually-later
            # string than an equal, naive one. ``_decode_mark``'s tzinfo
            # attachment is correct for comparing INSTANTS in a real
            # DATETIME/TIMESTAMP column (Postgres/MSSQL numeric compare); it
            # is normalised back to naive-UTC here purely for the bind, so
            # the wall-clock instant is unchanged either way.
            decoded_mark = _decode_mark(cursor.mark)
            if isinstance(decoded_mark, datetime) and decoded_mark.tzinfo is not None:
                decoded_mark = decoded_mark.astimezone(timezone.utc).replace(tzinfo=None)
            params["mark"] = decoded_mark
            # Bound even when ``None`` (the SEEK predicate's second branch
            # then reads ``key > NULL``, which SQL evaluates to unknown/
            # false on every dialect - the predicate degrades cleanly to a
            # strict ``t.wm > :mark``, never a crash and never a duplicate).
            #
            #     !!  A KEY VALUE RIDES AS-IS, NEVER THROUGH ``_decode_mark``
            #         (S1, review round 4).  !!
            # ``_decode_mark`` exists to turn an ISO-looking STRING back into
            # a real ``datetime`` for a WATERMARK bind - correct there
            # because a watermark column genuinely IS a timestamp. A key
            # column is a business identifier: it can happen to hold
            # date-shaped TEXT ('2026-08-01') that must stay exactly that
            # text, never get silently reparsed into a ``datetime`` (which
            # a live task did, and lost the second half of a tie group to a
            # type mismatch the driver could not compare against a TEXT
            # column). ``last_key`` is one value for a single-key task, a
            # list (one per ``key_columns``, same order) for a multi-key one
            # (S2) - both bind their elements verbatim.
            #
            # Known, accepted asymmetry: the STORED value already went
            # through ``_encode_mark`` for JSON-safety on the way IN (a
            # ``Decimal`` key becomes its string form, ``bytes`` becomes
            # hex) - binding it back out AS-IS means a non-str/int key
            # column rides as that stringified/hex text, not its native
            # Python type. A paged task's key column is virtually always a
            # business code (str) or a plain int, for which this never
            # matters; a genuinely ``Decimal``/``bytes`` key column would
            # need a real, type-aware reversal this deliberately does not
            # attempt - the string-key correctness this fixes is the
            # common, load-bearing case; the other is exotic enough that
            # guessing wrong (the KEY-decoding bug this whole fix exists
            # to remove) is worse than not guessing at all.
            if len(key_columns) > 1:
                last_key_values = (
                    list(cursor.last_key) if cursor.last_key is not None else [None] * len(key_columns)
                )
                for index in range(len(key_columns)):
                    params[f"last_key{index}"] = (
                        last_key_values[index] if index < len(last_key_values) else None
                    )
            else:
                params["last_key"] = cursor.last_key
        executable = sa.text(sql)

        started = time.monotonic()
        raw_rows: List[Dict[str, Any]] = []
        try:
            with open_readonly(
                self._engine, timeout_s=self.timeout_s, secrets=self._secrets
            ) as conn:
                streaming = conn.execution_options(
                    stream_results=True, max_row_buffer=STREAM_BATCH
                )
                result = streaming.execute(executable, params)
                #     !!  THE ROW CAP IS CHECKED PER PARTITION (F6, review
                #         round 2), NOT AFTER THE WHOLE RESULT IS PULLED.  !!
                # Mirrors ``_read`` exactly - materialising the entire
                # result before ever looking at ``row_limit`` would defeat
                # the cap's whole point (a runaway query still pulls
                # everything before failing).
                for partition in result.partitions(STREAM_BATCH):
                    for row in partition:
                        raw_rows.append(dict(row._mapping))
                    if len(raw_rows) > self.row_limit:
                        raise SqlSourceError(
                            f"The extract passed {self.row_limit:,} rows without "
                            f"finishing, so it was stopped and nothing was "
                            f"accepted. Narrow the query or set a watermark "
                            f"column so runs stay incremental."
                        )

                # ── trim the peeked-ahead row back off ──────────────────────
                # ``len(raw_rows) <= page_size`` means the query's own
                # ``page_size + 1`` LIMIT was never actually filled - this IS
                # the last page, whether it came back short or landed on an
                # exact multiple. ``> page_size`` means one row beyond this
                # page exists; drop it (it is re-read, unchanged, as the
                # first row the NEXT page's seek predicate finds).
                complete = len(raw_rows) <= page_size
                if not complete:
                    raw_rows = raw_rows[:page_size]

                # ── the frontier for the NEXT cursor ────────────────────────
                #     !!  A NULL WATERMARK OR KEY ON THE TAIL ROW FAILS LOUD
                #         (S3, review round 4) - NEVER SILENTLY RE-READS. !!
                # The tail row is the one the NEXT page's seek resumes from;
                # the old code only advanced ``last_mark``/``last_key`` "if
                # not None", silently leaving them AT THE PREVIOUS PAGE'S
                # value otherwise - the next page then re-runs the EXACT
                # SAME statement forever (a livelock, not a crash: nothing
                # ever raises, the run just never makes progress). A NULL
                # watermark/key on the row a page keeps is a source-data
                # fault this task cannot resume past; it must be a named,
                # immediate failure - not a second statement, not a retry.
                last_mark = cursor.mark
                last_key = cursor.last_key
                if raw_rows:
                    tail = raw_rows[-1]
                    tail_mark_value = tail.get(self.watermark_column)
                    if tail_mark_value is None:
                        raise SqlSourceError(
                            f"The watermark column '{self.watermark_column}' is "
                            f"NULL on the last row of this page - a paged task "
                            f"cannot resume from a NULL watermark. Nothing was "
                            f"staged or pushed."
                        )
                    last_mark = _encode_mark(tail_mark_value)
                    tail_key_values: List[Any] = []
                    for key_column in self.key_columns:
                        tail_key_value = tail.get(key_column)
                        if tail_key_value is None:
                            raise SqlSourceError(
                                f"The key column '{key_column}' is NULL on the "
                                f"last row of this page - a paged task cannot "
                                f"resume from a NULL key. Nothing was staged or "
                                f"pushed."
                            )
                        tail_key_values.append(_encode_mark(tail_key_value))
                    last_key = (
                        tail_key_values[0]
                        if len(tail_key_values) == 1
                        else tail_key_values
                    )

                rows_scanned = len(raw_rows)

                # ── document row-set filter, BEFORE the hash diff (AC-02-11) ─
                candidates = raw_rows
                filtered_this_page: List[Dict[str, Any]] = []
                if self.is_document and self.filter_formula:
                    keep_rows = []
                    for header in raw_rows:
                        try:
                            if evaluate_row_filter(self.filter_formula, header):
                                keep_rows.append(header)
                            else:
                                filtered_this_page.append(header)
                        except FormulaError as exc:
                            raise SqlFilterFormulaError(
                                f"The filter could not be evaluated: {exc}. "
                                f"Nothing was staged or pushed."
                            ) from exc
                    candidates = keep_rows

                # ── hash diff BEFORE lines (plan §2.1) ──────────────────────
                known = self._prior_hashes(candidates)
                hashes: Dict[str, str] = {}
                unchanged_refs: set = set()
                changed_headers: List[Dict[str, Any]] = []
                changed_stamps: Dict[int, Optional[datetime]] = {}
                records: List[SourceRecord] = []
                added = updated = 0
                key_column_name = self.key_columns[0] if self.is_document else None

                for header in candidates:
                    ref = self.source_ref(header)
                    stamp = (
                        _as_utc(header.get(self.watermark_column))
                        if self.watermark_column
                        else None
                    )
                    if ref is None:
                        # A blank key is a per-RECORD identity fault the
                        # mapping engine will name; it has no ref to hash on,
                        # so it always counts as "changed" and is staged
                        # FAILED downstream rather than silently vanishing.
                        records.append(SourceRecord(raw=json_safe(header), last_modified=stamp))
                        continue
                    value_hash = row_hash(header, self.compared_columns)
                    hashes[ref] = value_hash
                    if known.get(ref) == value_hash:
                        unchanged_refs.add(ref)
                        continue
                    if ref in known:
                        updated += 1
                    else:
                        added += 1
                    changed_headers.append(header)
                    changed_stamps[id(header)] = stamp

                #     !!  LINES ONLY FOR CHANGED/NEW HEADERS (plan §2.1) -
                #         UP TO N CONCURRENT CONNECTIONS (S5, performance
                #         round).  !!
                if self.is_document and changed_headers:
                    self._attach_lines(conn, changed_headers, key_column_name)

                #     !!  A CHANGED HEADER'S ``SourceRecord`` IS BUILT ONLY
                #         AFTER LINES ARE ATTACHED (URGENT fix, review round
                #         4) - NEVER BEFORE.  !!
                # ``json_safe(header)`` is a dict-comprehension SNAPSHOT, not
                # a live reference - a live load found ``raw_json`` missing
                # ``_lines`` entirely because the OLD code built this
                # ``SourceRecord`` right inside the loop above, BEFORE the
                # lines-attach loop mutated the SAME ``header`` dict; the
                # snapshot already taken never saw ``_lines`` land. Building
                # every changed header's record here, after lines are
                # attached, is the fix.
                for header in changed_headers:
                    stamp = changed_stamps.get(id(header))
                    mismatch = (
                        self._line_count_mismatch(header) if self.is_document else None
                    )
                    records.append(
                        SourceRecord(
                            raw=json_safe(header), last_modified=stamp, error=mismatch,
                        )
                    )

                #     !!  PREVIEW NEEDS EVERY CANDIDATE, NOT JUST CHANGED ONES
                #         (R2-S1, review round 3) - ONLY BUILT ON A PREVIEW,
                #         NEVER ON A REAL RUN (NIT, review round 4: a real
                #         run has no reader for it and must not pay to build
                #         a second, throwaway copy of every row on every
                #         page).  !!
                # Built AFTER the lines-for-changed-headers step above, so a
                # CHANGED document row's snapshot here carries its lines too
                # - an UNCHANGED document row's does not (its lines were
                # never fetched this page, matching the "only for changed
                # headers" rule above); a preview of an all-unchanged page
                # still reports the right ROW COUNT either way, which is
                # what regressed to 0.
                preview_records: List[SourceRecord] = (
                    [
                        SourceRecord(
                            raw=json_safe(header),
                            last_modified=(
                                _as_utc(header.get(self.watermark_column))
                                if self.watermark_column
                                else None
                            ),
                        )
                        for header in candidates
                    ]
                    if not self.persist_hashes
                    else []
                )

                #     !!  A FILTERED-OUT HEADER'S STALE HASH IS DROPPED HERE
                #         (AC-03-18) - the ONLY write ``fetch_page`` itself
                #         performs; the per-row hash upsert / seen-touch for
                #         everything else is the CALLER's job (``sync.py``'s
                #         run loop), which alone knows which refs a mapping
                #         failure disqualifies from a hash write.  !!
                if self.persist_hashes and filtered_this_page:
                    filtered_refs = [
                        ref
                        for ref in (self.source_ref(h) for h in filtered_this_page)
                        if ref is not None
                    ]
                    if filtered_refs:
                        filtered_known = RowHashRepository(self._ctx.db).hashes_for(
                            self._ctx.tenant_id, self._ctx.company.id, self.entity_type,
                            filtered_refs,
                        )
                        stale_filtered = [ref for ref in filtered_refs if ref in filtered_known]
                        if stale_filtered:
                            RowHashRepository(self._ctx.db).delete_many(
                                self._ctx.tenant_id, self._ctx.company.id, self.entity_type,
                                stale_filtered,
                            )
                            self._ctx.db.commit()
        except SqlSourceError as exc:
            self._record_call(
                started, rows=len(raw_rows), incremental=cursor.mark is not None,
                error=exc.message,
            )
            raise
        except Exception as exc:  # noqa: BLE001 - every driver has its own class
            from .runtime import sanitize_error

            message = sanitize_error(exc, secrets=self._secrets)
            self._record_call(
                started, rows=len(raw_rows), incremental=cursor.mark is not None,
                error=message,
            )
            raise SqlQueryError(message) from exc

        self._record_call(started, rows=len(raw_rows), incremental=cursor.mark is not None)

        return PageResult(
            records=records,
            preview_records=preview_records,
            unchanged_refs=unchanged_refs,
            hashes=hashes,
            last_mark=last_mark,
            last_key=last_key,
            rows_scanned=rows_scanned,
            added=added,
            updated=updated,
            complete=complete,
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
            self._last_skipped_by_filter = 0
            self._filtered_out_headers = []
            if self.is_document:
                #     !!  THE ROW-SET FILTER RUNS BEFORE LINE FETCH (AC-02-11).  !!
                # A header the filter drops (e.g. the SPO-numbered rows a PO
                # task's sibling task owns) never fetches lines, never enters
                # `rows` at all - so it cannot be staged, mapped, or counted
                # as a delete candidate either.
                if self.filter_formula:
                    kept = []
                    try:
                        for header in rows:
                            if evaluate_row_filter(self.filter_formula, header):
                                kept.append(header)
                            else:
                                self._last_skipped_by_filter += 1
                                self._filtered_out_headers.append(header)
                    except FormulaError as exc:
                        #     !!  A RUNTIME FILTER FAULT IS A NAMED TASK
                        #         ERROR, NEVER A SILENT KEEP-EVERYTHING.  !!
                        # (F2/B3.) `validate_source_config` already proved
                        # this formula PARSES against the saved result
                        # columns - a failure reaching here is a genuine
                        # per-row runtime fault (a value that doesn't coerce
                        # the way the formula expects). Fails the WHOLE run,
                        # same fail-safe contract as the delete guard/document
                        # caps: nothing staged, nothing pushed, hashes
                        # untouched.
                        raise SqlFilterFormulaError(
                            f"The filter could not be evaluated: {exc}. Nothing "
                            f"was staged or pushed."
                        ) from exc
                    rows = kept
                #     !!  NO PER-RUN HEADER-COUNT CAP HERE ANY MORE.  !!
                # (plan sprint-5/03 S1, AC-03-01.) A document task ALWAYS
                # carries a watermark column (construction-time guard above),
                # so every real document run now goes through ``fetch_page``
                # (``AUTOCOUNT_PAGE_SIZE`` bounds each read); this unpaged
                # ``_read``/``fetch_changes`` path only remains reachable for
                # the initial-load preview probe, which caps rows a different
                # way (``MAX_EXTRACT_ROWS``, still enforced above).
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

    def _attach_lines(
        self,
        conn: Any,
        changed_headers: List[Dict[str, Any]],
        key_column_name: str,
    ) -> None:
        """Fetch every changed/new header's lines for THIS page (S5,
        performance round) - sequential over the page's OWN ``conn`` when
        there is nothing to gain from concurrency, or a small thread pool
        when there is.

        A live pass over ZeroTier (~25ms RTT) spent ~60s per page on 2,000
        sequential line queries. ``settings.autocount_line_fetch_workers``
        (read at CALL time, never cached) bounds how many run at once, each
        on its OWN ``open_readonly`` connection off ``self._engine`` -
        NEVER the page's shared ``conn``, which is a single DB-API
        connection object and is not safe to use from more than one
        thread. Results are attached back onto each header IN THE SAME
        ORDER ``changed_headers`` already has (never by which worker
        happened to finish first), so the ``records``/``hashes`` built
        from ``changed_headers`` immediately afterwards are byte-identical
        to the old sequential path regardless of concurrency - only the
        wall-clock time changes. One header's line query failing
        propagates exactly like the OLD sequential loop did (whatever
        ``_read_lines`` raises bubbles straight out of ``fetch_page`` -
        nothing staged, the top-level cursor untouched); any OTHER
        header's future still in the pool's queue (not yet started) is
        cancelled rather than left to make a wasted call.

        ``workers <= 1`` OR a single-connection pool (``StaticPool`` - the
        in-memory SQLite rig every other test in this suite uses, which
        hands back the SAME underlying connection every time) both fall
        back to the exact old sequential loop: a second ``open_readonly``
        against a ``StaticPool`` engine while the first is still open would
        deadlock or corrupt the shared cursor, never run genuinely in
        parallel.
        """
        from app.config import settings as _settings

        workers = int(getattr(_settings, "autocount_line_fetch_workers", 4) or 4)
        if workers <= 1 or isinstance(self._engine.pool, StaticPool):
            for header in changed_headers:
                doc_key_value = header.get(key_column_name)
                header[SQL_DOC_LINES_KEY] = self._read_lines(conn, doc_key_value)
            return

        workers = min(workers, len(changed_headers))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    self._read_lines_own_connection, header.get(key_column_name)
                )
                for header in changed_headers
            ]
            try:
                for header, future in zip(changed_headers, futures):
                    header[SQL_DOC_LINES_KEY] = future.result()
            except BaseException:
                for pending in futures:
                    pending.cancel()
                raise

    def _read_lines_own_connection(self, doc_key_value: Any) -> List[Dict[str, Any]]:
        """A worker's OWN ``open_readonly`` connection off ``self._engine``
        (S5) - never the page's shared connection, which is not safe to
        use from more than one thread at once."""
        with open_readonly(
            self._engine, timeout_s=self.timeout_s, secrets=self._secrets
        ) as worker_conn:
            return self._read_lines(worker_conn, doc_key_value)

    def _line_count_mismatch(self, header: Dict[str, Any]) -> Optional[str]:
        """The ``LineCount`` fingerprint mismatch guard (S2, review round 4).

        Called AFTER ``_read_lines`` has already populated
        ``header[SQL_DOC_LINES_KEY]``. A header carrying a ``LineCount``
        column (``presets.LINE_COUNT_FINGERPRINT_COLUMN`` - a plain
        column-name CONVENTION documented next to the preset queries, never
        an engine concept) with a value greater than zero, whose own
        ``lineQuery`` fetch came back with ZERO rows, is a genuine mismatch
        (a broken line query/join) - never a silently-accepted, valid
        zero-line document. A task with no such column, or one reporting
        zero (a real lineless document, AC-13's own rule), is untouched.

        Deliberately checks only the ALL-OR-NOTHING case (``expected > 0``
        and ``fetched == 0``), never a PARTIAL mismatch (``fetched`` some
        smaller positive number than ``expected``): the preset's own
        ``LineCount`` aggregate is computed with an ``ItemCode IS NOT
        NULL`` filter (dropping description-only/sub-total display lines),
        while ``lineQuery`` is not - a header with, say, 2 description
        lines and 3 real ones legitimately reports ``LineCount=3`` but
        fetches 5 rows, and the reverse skew is just as possible depending
        on how an operator wrote their OWN ``lineQuery``. Zero fetched is
        the one shape no such skew can ever produce when the fingerprint
        says lines exist, which is what makes it - and only it - a safe,
        unambiguous signal of a genuinely broken join.
        """
        if LINE_COUNT_FINGERPRINT_COLUMN not in header:
            return None
        raw_value = header.get(LINE_COUNT_FINGERPRINT_COLUMN)
        if raw_value is None:
            return None
        try:
            expected = int(raw_value)
        except (TypeError, ValueError):
            return None
        if expected <= 0:
            return None
        fetched = len(header.get(SQL_DOC_LINES_KEY) or [])
        if fetched > 0:
            return None
        doc_key_value = (
            header.get(self.key_columns[0]) if self.key_columns else None
        )
        return f"LineCount {expected} but {fetched} lines fetched for DocKey {doc_key_value}"

    def source_ref(self, raw: Dict[str, Any]) -> Optional[str]:
        """The identity ``sync.py`` keys ``ac_row_hash``/a failed-row hash
        drop on (NIT, review round 2 - was a leading-underscore "private"
        method a SIBLING module called directly)."""
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
        refs = [ref for ref in (self.source_ref(raw) for raw in raw_rows) if ref]
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
