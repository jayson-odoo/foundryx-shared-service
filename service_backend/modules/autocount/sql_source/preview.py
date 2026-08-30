"""Query preview (AC-22-06): guard → wrap as a derived table with a dialect
cap → run read-only under a timeout → JSON-safe rows + column names/types.

The cap fetches ``limit + 1`` rows so ``truncated`` is a FACT (there was a
101st row), not a guess from ``len == limit``.

Column types come from the rows themselves when there are any (the Python
value type is the most faithful thing the driver hands back), falling back to
the DBAPI cursor description for all-NULL columns and empty results. The
result vocabulary is small and dialect-neutral - ``integer``, ``float``,
``decimal``, ``number``, ``datetime``, ``date``, ``time``, ``string``,
``boolean``, ``binary``, ``json``, ``unknown`` - because the ONE consumer that
reasons about it is the watermark check ("is this orderable?").
"""
from __future__ import annotations

import base64
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.engine import Engine

from .errors import SqlQueryError
from .guard import assert_select_only
from .runtime import PREVIEW_ROW_LIMIT, QUERY_TIMEOUT_SECONDS, open_readonly, sanitize_error

__all__ = [
    "PreviewColumn",
    "PreviewResult",
    "describe_type",
    "is_orderable_type",
    "run_preview",
    "wrap_preview",
]

_ORDERABLE = frozenset({"integer", "float", "decimal", "number", "datetime", "date", "time"})
_BINARY_CAP = 64


@dataclass(frozen=True)
class PreviewColumn:
    name: str
    type: str


@dataclass
class PreviewResult:
    columns: List[PreviewColumn] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    duration_ms: int = 0

    @property
    def column_types(self) -> Dict[str, str]:
        return {c.name: c.type for c in self.columns}


def wrap_preview(sql: str, dialect: str, limit: int) -> str:
    """Guard, then wrap. MSSQL takes ``TOP``; everything else ``LIMIT``."""
    statement = assert_select_only(sql)
    n = int(limit) + 1
    if dialect == "mssql":
        return f"SELECT TOP ({n}) * FROM ({statement}) AS _preview"
    return f"SELECT * FROM ({statement}) AS _preview LIMIT {n}"


def describe_type(value: Any) -> str:
    """Type vocabulary from a Python value (the driver's own decoding)."""
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, Decimal):
        return "decimal"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, dt_time):
        return "time"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "binary"
    if isinstance(value, (dict, list)):
        return "json"
    return "string"


# psycopg2 type OIDs → vocabulary (the common ones; anything else = unknown).
_PG_OIDS: Dict[int, str] = {
    16: "boolean",
    20: "integer",
    21: "integer",
    23: "integer",
    26: "integer",
    700: "float",
    701: "float",
    1700: "decimal",
    1082: "date",
    1083: "time",
    1266: "time",
    1114: "datetime",
    1184: "datetime",
    25: "string",
    1043: "string",
    1042: "string",
    18: "string",
    19: "string",
    2950: "string",
    17: "binary",
    114: "json",
    3802: "json",
}
# pymysql FIELD_TYPE codes → vocabulary.
_MYSQL_CODES: Dict[int, str] = {
    0: "decimal",
    246: "decimal",
    1: "integer",
    2: "integer",
    3: "integer",
    8: "integer",
    9: "integer",
    13: "integer",
    16: "integer",
    4: "float",
    5: "float",
    7: "datetime",
    12: "datetime",
    10: "date",
    14: "date",
    11: "time",
    15: "string",
    253: "string",
    254: "string",
    247: "string",
    248: "string",
    249: "binary",
    250: "binary",
    251: "binary",
    252: "binary",
    255: "binary",
    245: "json",
}
# pymssql: STRING=1 BINARY=2 NUMBER=3 DATETIME=4 DECIMAL=5.
_MSSQL_CODES: Dict[int, str] = {
    1: "string",
    2: "binary",
    3: "number",
    4: "datetime",
    5: "decimal",
}


def describe_cursor_type(dialect: str, type_code: Any) -> str:
    """Best-effort type from the DBAPI cursor description (all-NULL / empty
    results). Unknown drivers or codes → ``unknown`` - never a guess."""
    if type_code is None:
        return "unknown"
    try:
        code = int(type_code)
    except (TypeError, ValueError):
        return "unknown"
    if dialect == "postgresql":
        return _PG_OIDS.get(code, "unknown")
    if dialect == "mysql":
        return _MYSQL_CODES.get(code, "unknown")
    if dialect == "mssql":
        return _MSSQL_CODES.get(code, "unknown")
    return "unknown"


def is_orderable_type(type_name: str) -> bool:
    """Whether a column of this type can drive ``WHERE col > :mark``."""
    return str(type_name or "").lower() in _ORDERABLE


def json_safe(value: Any) -> Any:
    """A cell as it may cross the wire. Source-DB datetimes are emitted as
    written (ISO), never re-zoned - they are the customer's data, not ours."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        head = base64.b16encode(raw[:_BINARY_CAP]).decode().lower()
        return f"0x{head}" + ("..." if len(raw) > _BINARY_CAP else "")
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    return str(value)


def _column_types(
    dialect: str,
    names: Sequence[str],
    rows: Sequence[Dict[str, Any]],
    description: Optional[Sequence[Any]],
) -> List[PreviewColumn]:
    columns: List[PreviewColumn] = []
    for index, name in enumerate(names):
        # Widen over EVERY non-null value: a numeric column whose first row
        # happens to be ``0`` must not read as integer when later rows carry
        # fractions (SQLite affinity, MySQL DECIMAL(…,0) mixes, etc.).
        seen: List[str] = []
        for row in rows:
            value = row.get(name)
            if value is not None:
                described = describe_type(value)
                if described not in seen:
                    seen.append(described)
        type_name = "unknown"
        if seen:
            if "decimal" in seen:
                type_name = "decimal"
            elif "float" in seen and "integer" in seen:
                type_name = "float"
            else:
                type_name = seen[0]
        if type_name == "unknown" and description is not None and index < len(description):
            entry = description[index]
            type_code = entry[1] if isinstance(entry, (tuple, list)) and len(entry) > 1 else None
            type_name = describe_cursor_type(dialect, type_code)
        columns.append(PreviewColumn(name=str(name), type=type_name))
    return columns


def _execute_preview_unguarded(
    engine: Engine,
    statement: str,
    *,
    limit: int = PREVIEW_ROW_LIMIT,
    timeout_s: int = QUERY_TIMEOUT_SECONDS,
    secrets: Sequence[str] = (),
) -> PreviewResult:
    """Run ``statement`` AS GIVEN inside a read-only, always-rolled-back
    transaction and shape the result. Internal: callers go through
    ``run_preview`` (which guards + wraps first)."""
    started = time.monotonic()
    dialect = engine.dialect.name
    with open_readonly(engine, timeout_s=timeout_s, secrets=secrets) as conn:
        try:
            result = conn.exec_driver_sql(statement)
            description = None
            cursor = getattr(result, "cursor", None)
            if cursor is not None:
                description = getattr(cursor, "description", None)
            names = list(result.keys())
            raw_rows = result.fetchmany(int(limit) + 1)
        except Exception as exc:  # noqa: BLE001 - every driver has its own class
            raise SqlQueryError(sanitize_error(exc, secrets=secrets)) from exc
    fetched: List[Dict[str, Any]] = [dict(row._mapping) for row in raw_rows]
    truncated = len(fetched) > int(limit)
    kept = fetched[: int(limit)]
    columns = _column_types(dialect, names, kept, description)
    rows = [{str(k): json_safe(v) for k, v in row.items()} for row in kept]
    return PreviewResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def run_preview(
    engine: Engine,
    sql: str,
    *,
    limit: int = PREVIEW_ROW_LIMIT,
    timeout_s: int = QUERY_TIMEOUT_SECONDS,
    secrets: Sequence[str] = (),
) -> PreviewResult:
    """Guard (422 before the source), wrap per dialect, run capped + timed."""
    wrapped = wrap_preview(sql, engine.dialect.name, limit)
    return _execute_preview_unguarded(
        engine, wrapped, limit=limit, timeout_s=timeout_s, secrets=secrets
    )
