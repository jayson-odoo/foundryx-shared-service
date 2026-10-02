"""ONE-pass conditional-aggregate query core (plan 30, D-A9-8/D-A9-9).

`bucketed_counts` builds ONE SQL statement with one `SUM(CASE ...)` column per
(series, bucket) pair - dialect-free (no `date_trunc`/`strftime`), so the
pytest SQLite numbers and production Postgres numbers are byte-identical
(AC-RPT-11). `duration_samples` is the bounded single-column/tuple projection
every percentile/median/average reduction (`report_stats.py`) runs over -
`REPORT_MAX_SAMPLE_ROWS` rows fetched via `LIMIT cap + 1` so an over-cap
request is detected WITHOUT an unbounded fetch (AC-RPT-13).

Nothing in this module builds SQL from client input - every predicate a
caller passes in is a server-side SQLAlchemy column/constant.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Query, Session

from .report_windows import Bucket

REPORT_MAX_SAMPLE_ROWS = 100_000


class SampleCapExceeded(Exception):
    """AC-RPT-13/36 - the request would need to read more than the cap."""

    def __init__(self, count: int, cap: int = REPORT_MAX_SAMPLE_ROWS):
        self.count = count
        self.cap = cap
        super().__init__(
            f"This request would need to read {count} rows (max {cap}); narrow the date range."
        )


def bucketed_select_columns(
    ts_column: Any, edges: List[Bucket], series_predicates: Dict[str, Optional[Any]]
) -> List[Any]:
    """The pure column-building half of `bucketed_counts` - no `db`/execution,
    so it is directly compile-testable against any dialect (AC-RPT-11's
    golden two-dialect test, S-8 review round 1: the test asserts against
    the SAME columns the real query builds, never a hand-built stand-in)."""
    columns = []
    for series_index, (_, predicate) in enumerate(series_predicates.items()):
        for bucket_index, bucket in enumerate(edges):
            window = and_(ts_column >= bucket.starts_at, ts_column < bucket.ends_at)
            condition = and_(window, predicate) if predicate is not None else window
            columns.append(
                func.sum(case((condition, 1), else_=0)).label(f"s{series_index}_b{bucket_index}")
            )
    return columns


def bucketed_counts(
    db: Session,
    ts_column: Any,
    filters: Sequence[Any],
    edges: List[Bucket],
    series_predicates: Dict[str, Optional[Any]],
) -> Dict[str, List[int]]:
    """Every (series, bucket) count in ONE round trip. `series_predicates` maps
    a series key to an extra predicate ANDed with that bucket's window (`None`
    = just the window, i.e. every row counts). Returns counts aligned to
    `edges` by index, per series key - `[]` per series when `edges` is empty."""
    names = list(series_predicates.items())
    if not edges:
        return {name: [] for name, _ in names}

    columns = bucketed_select_columns(ts_column, edges, series_predicates)
    row = db.query(*columns).filter(*filters).one()

    result: Dict[str, List[int]] = {}
    offset = 0
    for name, _ in names:
        result[name] = [int(row[offset + bucket_index] or 0) for bucket_index in range(len(edges))]
        offset += len(edges)
    return result


def duration_samples(query: Query, cap: int = REPORT_MAX_SAMPLE_ROWS) -> List[Any]:
    """`query` is an already-filtered/selected SQLAlchemy `Query` (scalar
    column or tuple projection). Fetches at most `cap + 1` rows - if that many
    come back, the true count exceeds the cap and `SampleCapExceeded` is
    raised (naming the exact row count read, never a truncated silent
    fetch)."""
    rows = query.limit(cap + 1).all()
    if len(rows) > cap:
        raise SampleCapExceeded(len(rows), cap)
    return rows
