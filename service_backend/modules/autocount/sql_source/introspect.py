"""Schema introspection (AC-22-05): schemas → tables (+ views) → columns
(name + the dialect's reported type), via ``sqlalchemy.inspect`` so the code
never branches on dialect for the tree itself.

Cached per connection with a TTL and an explicit refresh - the editor's tree
and autocomplete read the cache, NEVER the source per keystroke.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, TypeVar

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from .errors import SqlConnectError
from .runtime import sanitize_error

__all__ = [
    "SCHEMA_CACHE",
    "SchemaCache",
    "SqlColumnInfo",
    "SqlSchemaInfo",
    "SqlSchemaTree",
    "SqlTableInfo",
    "introspect_schema",
]

# Namespaces no operator wants in the tree.
_SYSTEM_SCHEMAS = frozenset(
    {
        "information_schema",
        "pg_catalog",
        "pg_toast",
        "sys",
        "guest",
        "mysql",
        "performance_schema",
        "innodb",
    }
)
_SYSTEM_PREFIXES = ("pg_", "db_")
SCHEMA_CACHE_TTL_SECONDS = 600


@dataclass(frozen=True)
class SqlColumnInfo:
    name: str
    type: str


@dataclass(frozen=True)
class SqlTableInfo:
    name: str
    columns: Tuple[SqlColumnInfo, ...] = ()


@dataclass(frozen=True)
class SqlSchemaInfo:
    name: str
    tables: Tuple[SqlTableInfo, ...] = ()


@dataclass(frozen=True)
class SqlSchemaTree:
    schemas: Tuple[SqlSchemaInfo, ...] = ()
    introspected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


def _type_name(column: Dict[str, Any]) -> str:
    try:
        return str(column.get("type")) or "unknown"
    except Exception:  # noqa: BLE001 - an exotic dialect type with no compile
        return "unknown"


def _is_system(name: str) -> bool:
    lowered = name.lower()
    return lowered in _SYSTEM_SCHEMAS or lowered.startswith(_SYSTEM_PREFIXES)


def introspect_schema(
    engine: Engine, *, database: str = "", secrets: Sequence[str] = ()
) -> SqlSchemaTree:
    """Walk the source's namespaces. MySQL's "schemas" are databases, so it is
    pinned to the connection's own; other dialects list every non-system
    schema. Connect failures surface as a sanitised ``SqlConnectError``."""
    dialect = engine.dialect.name
    try:
        inspector = sa.inspect(engine)
        if dialect == "mysql":
            names = [database or inspector.default_schema_name or ""]
        else:
            try:
                names = list(inspector.get_schema_names())
            except NotImplementedError:
                names = [inspector.default_schema_name or ""]
        schemas: List[SqlSchemaInfo] = []
        for schema_name in sorted(n for n in names if n and not _is_system(n)):
            table_names = set(inspector.get_table_names(schema=schema_name))
            try:
                table_names |= set(inspector.get_view_names(schema=schema_name))
            except NotImplementedError:
                pass
            tables: List[SqlTableInfo] = []
            for table_name in sorted(table_names):
                try:
                    raw_columns = inspector.get_columns(table_name, schema=schema_name)
                except sa.exc.NoSuchTableError:
                    continue
                tables.append(
                    SqlTableInfo(
                        name=table_name,
                        columns=tuple(
                            SqlColumnInfo(name=str(c["name"]), type=_type_name(c))
                            for c in raw_columns
                        ),
                    )
                )
            schemas.append(SqlSchemaInfo(name=schema_name, tables=tuple(tables)))
    except sa.exc.SQLAlchemyError as exc:
        raise SqlConnectError(
            "Could not connect to the database: " + sanitize_error(exc, secrets=secrets)
        ) from exc
    return SqlSchemaTree(schemas=tuple(schemas))


T = TypeVar("T")


class SchemaCache:
    """Per-key TTL cache with explicit refresh/invalidate. ``clock`` is
    injectable (tests drive expiry without sleeping)."""

    def __init__(
        self,
        ttl_seconds: float = SCHEMA_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl = ttl_seconds
        self._clock = clock
        self._entries: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, loader: Callable[[], T], *, refresh: bool = False) -> T:
        now = self._clock()
        if not refresh:
            with self._lock:
                held = self._entries.get(key)
            if held is not None and (now - held[0]) < self.ttl:
                return held[1]
        value = loader()
        with self._lock:
            self._entries[key] = (self._clock(), value)
        return value

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def peek(self, key: str) -> Optional[Any]:
        with self._lock:
            held = self._entries.get(key)
        return held[1] if held else None


SCHEMA_CACHE = SchemaCache()
