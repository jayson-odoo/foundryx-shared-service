"""ImporterDef registry (sprint-3/09 D1/D2/D6) - code-side, opt-in, per entity.

A separate registry of ``ImporterDef`` keyed by ``entity_type`` (house parallel-
registry style). Core entities register at ``lazy_once``; modules at install.
Importable columns are a subset of the server-writable whitelist (D2) -
``infer_import_columns(model, writable)`` seeds defaults from the SQLAlchemy
columns (mirrors ``rule_engine.infer_facts``); the ``ImporterDef`` overrides only
the special bits (resolver/options/validators/multiValue/transform).

``match_on`` is universally ``id`` (D5) - not declared per entity.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Numeric
from sqlalchemy.orm import Session

from app.lazy_registry import lazy_once
from app.workflow_engine.entities import attr_for

# Column value types - coerced; a bad parse = a cell error with the expected fmt.
ColumnType = str  # 'string'|'integer'|'decimal'|'boolean'|'date'|'datetime'|'enum'

# Static option list, or callable(db, user) for tenant-scoped options (drives the
# in-xlsx dropdown when bounded; ≤25 surfaced).
OptionsProvider = Optional[
    "List[Dict[str, str]] | Callable[[Session, Any], List[Dict[str, str]]]"
]

# A resolver maps a cell (name/email/reference) → a system id, tenant-scoped.
# find-only (default; unresolvable = cell error) or find_or_create (D18).
RESOLVE_FIND = "find"
RESOLVE_FIND_OR_CREATE = "find_or_create"


@dataclass(frozen=True)
class ResolverDef:
    """FK/reference resolution for a column (D6/D18). ``lookup(db, tenant_id,
    values) -> {value: id}`` is BATCHED (set-based - one query for the page).
    ``options(db, user)`` optionally bounds the cell to a dropdown (≤25).
    ``create(db, tenant_id, row, ctx) -> id`` is required iff mode is
    find_or_create (existing match → link, no match → create; NEVER update)."""

    lookup: Callable[[Session, str, List[str]], Dict[str, str]]
    mode: str = RESOLVE_FIND
    options: OptionsProvider = None
    create: Optional[Callable[[Session, str, dict, dict], str]] = None
    label: Optional[str] = None  # e.g. "Profile (by email)"


@dataclass(frozen=True)
class ImportColumn:
    """One importable column. ``key`` is the camelCase field key the template +
    mapping advertise; ``attr`` is the snake_case model attribute (the writable-
    whitelist space). Coercion + validation are server-authoritative (D7)."""

    key: str
    label: str
    type: ColumnType = "string"
    required: bool = False
    unique: bool = False  # validated against in-file + table dups, NOT a match key
    decimals: Optional[int] = None  # for decimal type (Decimal-exponent check)
    options: OptionsProvider = None  # enum/bounded sets → in-xlsx dropdown
    resolver: Optional[ResolverDef] = None
    multi_value: bool = False  # delimited cell, per-item resolve
    validators: Tuple[Callable[[Any], Optional[str]], ...] = ()  # ret err msg|None
    transform: Optional[Callable[[Any], Any]] = None  # trim/normalize

    @property
    def attr(self) -> str:
        return attr_for(self.key)


@dataclass(frozen=True)
class ImporterDef:
    """A per-entity importer config. ``columns`` ⊆ the entity's writable
    whitelist (drift-guard test). ``create``/``update``/``existing_ids`` are the
    set-based DML hooks the service calls (one batched query each)."""

    entity_type: str
    label: str
    model: Any
    columns: Tuple[ImportColumn, ...]
    # Set-based hooks (D7). Each takes the whole valid set, never per-row.
    create_rows: Optional[Callable[[Session, str, List[dict], dict], List[str]]] = None
    update_rows: Optional[Callable[[Session, str, List[dict], dict], List[str]]] = None
    existing_ids: Optional[Callable[[Session, str, List[str]], set]] = None
    # Imperative cross-column escape hatch (D6) - returns {colKey: msg} or {}.
    validate_row: Optional[Callable[[dict, dict], Dict[str, str]]] = None
    # Aggregate/set-based validation hook (sprint-4/05) - runs ONCE over the whole
    # valid prepared set (zero writes) in BOTH Test and commit, so a batch-level
    # constraint (e.g. GA capacity ``sold + held + import_qty <= capacity``) blocks
    # the commit, never oversells. Returns a list of error dicts
    # ``{"row": int|None, "column": str, "message": str}`` (row None = aggregate).
    validate_prepared: Optional[
        Callable[[Session, str, List[dict], dict], List[dict]]
    ] = None
    # Context keys this importer accepts from an embedded-list launch (D17).
    context_keys: Tuple[str, ...] = ()
    module: str = "core"
    write_permission: str = ""  # the entity write perm gating import (D12)

    def column(self, key: str) -> Optional[ImportColumn]:
        for c in self.columns:
            if c.key == key:
                return c
        return None

    @property
    def required_columns(self) -> List[ImportColumn]:
        return [c for c in self.columns if c.required]


_REGISTRY: Dict[str, ImporterDef] = {}


def register_importer(importer: ImporterDef) -> None:
    """Idempotent - re-registration on bootstrap overwrites."""
    _REGISTRY[importer.entity_type] = importer


def get_importer(entity_type: str) -> Optional[ImporterDef]:
    ensure_core()
    return _REGISTRY.get(entity_type)


def list_importers() -> List[ImporterDef]:
    ensure_core()
    return list(_REGISTRY.values())


# ---- inference helper (mirrors rule_engine.infer_facts) ----


def _camel(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(p.capitalize() for p in rest)


def _title(snake: str) -> str:
    return " ".join(p.capitalize() for p in snake.split("_"))


def _column_type(column) -> ColumnType:
    col_type = getattr(column.type, "impl", column.type)
    if isinstance(col_type, Boolean):
        return "boolean"
    if isinstance(col_type, DateTime):
        return "datetime"
    if isinstance(col_type, Date):
        return "date"
    if isinstance(col_type, Integer):
        return "integer"
    if isinstance(col_type, (Numeric, Float)):
        return "decimal"
    return "string"


def infer_import_columns(
    model: Any,
    writable: Sequence[str],
    *,
    overrides: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[ImportColumn]:
    """Seed ``ImportColumn`` defaults from the SQLAlchemy columns named in the
    writable whitelist (type from the column, required from non-nullable).
    ``overrides[attr]`` patches label/type/required/resolver/options/etc."""
    overrides = overrides or {}
    cols: List[ImportColumn] = []
    for attr in writable:
        column = model.__table__.columns.get(attr)
        patch = overrides.get(attr, {})
        inferred_type = _column_type(column) if column is not None else "string"
        required = (not column.nullable) if column is not None else False
        cols.append(
            ImportColumn(
                key=patch.get("key", _camel(attr)),
                label=patch.get("label", _title(attr)),
                type=patch.get("type", inferred_type),
                required=patch.get("required", required),
                unique=patch.get("unique", False),
                decimals=patch.get("decimals"),
                options=patch.get("options"),
                resolver=patch.get("resolver"),
                multi_value=patch.get("multi_value", False),
                validators=tuple(patch.get("validators", ())),
                transform=patch.get("transform"),
            )
        )
    return cols


def _register_core() -> None:
    from app.import_engine.core_importers import register_core_importers

    register_core_importers()


ensure_core = lazy_once(_register_core)
