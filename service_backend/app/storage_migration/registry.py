"""StorageKeyLocation registry + generic enumerate/rewrite (sprint-4/10 D9).

Every place a ``conn:<connection_id>:<raw>`` storage key is persisted registers
here, so a storage migration finds + rewrites ALL of them automatically:

- **Scalar** ``StorageKeyLoc(model, column, tenant_column)`` — a ``*_key``
  column. Enumerate = ``SELECT DISTINCT col WHERE col LIKE 'conn:<id>:%'``;
  rewrite = ``SET col = replace(col,'conn:<A>:','conn:<B>:') WHERE col LIKE
  'conn:<A>:%'`` (value-checked — a row already re-pointed to B is skipped).
- **JSON** ``StorageKeyLoc(model, json_column, tenant_column, walk=…,
  rewrite_json=…)`` — keys embedded in a JSON document (form answers, template
  block-docs, workflow definitions). Defaults to a GENERIC recursive walker /
  rewriter that finds every ``conn:``-string anywhere in the doc. The rewrite
  **reassigns a FRESH dict** (``json.loads(json.dumps(...))``) so SQLAlchemy
  tracks the change — an in-place mutation of the same dict object is silently
  dropped (the documented JSON-tracking gotcha, form-engine §Slice-2).

**Enumeration is connection-scoped, not tenant-scoped** (grill Q9/Q10): a
value-checked ``conn:<id>:`` filter naturally isolates a tenant-own connection's
keys to that tenant's rows, while the platform connection's keys span every
fallback tenant — one rule serves both, no tenant_column needed at run time
(it's stored for documentation / future use).
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from sqlalchemy import String, cast, distinct, func
from sqlalchemy.orm import Session

_CONN_PREFIX = "conn:"


def _prefix(connection_id: str) -> str:
    return f"{_CONN_PREFIX}{connection_id}:"


# ── generic recursive JSON walk / rewrite (default for JSON locations) ────────


def generic_json_walk(doc: Any) -> Iterator[str]:
    """Yield EVERY ``conn:``-prefixed string anywhere in a JSON document."""
    if isinstance(doc, str):
        if doc.startswith(_CONN_PREFIX):
            yield doc
    elif isinstance(doc, dict):
        for value in doc.values():
            yield from generic_json_walk(value)
    elif isinstance(doc, (list, tuple)):
        for value in doc:
            yield from generic_json_walk(value)


def generic_json_rewrite(
    doc: Any, from_prefix: str, to_prefix: str, only_keys: Optional[Set[str]]
) -> Any:
    """Return a NEW document with every matching ``conn:<A>:`` string prefix-
    swapped to ``conn:<B>:``. Value-checked (only the from-prefix is touched)
    and ``only_keys``-checked (a key not in the copied set is left on A)."""
    if isinstance(doc, str):
        if doc.startswith(from_prefix) and (only_keys is None or doc in only_keys):
            return to_prefix + doc[len(from_prefix):]
        return doc
    if isinstance(doc, dict):
        return {k: generic_json_rewrite(v, from_prefix, to_prefix, only_keys) for k, v in doc.items()}
    if isinstance(doc, list):
        return [generic_json_rewrite(v, from_prefix, to_prefix, only_keys) for v in doc]
    return doc


# ── location definition ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class StorageKeyLoc:
    model: Any
    tenant_column: Optional[str] = None
    # scalar
    column: Optional[str] = None
    # json
    json_column: Optional[str] = None
    walk: Callable[[Any], Iterable[str]] = generic_json_walk
    rewrite_json: Callable[[Any, str, str, Optional[Set[str]]], Any] = generic_json_rewrite
    module: str = "core"

    @property
    def is_json(self) -> bool:
        return self.json_column is not None

    @property
    def _column_name(self) -> str:
        return self.json_column if self.is_json else (self.column or "")

    @property
    def signature(self) -> Tuple[str, str]:
        return (self.model.__tablename__, self._column_name)


_LOCATIONS: Dict[Tuple[str, str], StorageKeyLoc] = {}


def register_storage_key_location(loc: StorageKeyLoc) -> None:
    """Register a location. Idempotent — re-registration (module boot) overwrites
    the same (table, column) signature."""
    if not loc.is_json and not loc.column:
        raise ValueError("StorageKeyLoc needs either `column` (scalar) or `json_column`.")
    _LOCATIONS[loc.signature] = loc


def list_locations() -> List[StorageKeyLoc]:
    return list(_LOCATIONS.values())


def registered_scalar_columns() -> Set[Tuple[str, str]]:
    """(table_name, column_name) for every registered SCALAR location — the set
    the drift test checks ``all_key_columns()`` against."""
    return {loc.signature for loc in _LOCATIONS.values() if not loc.is_json}


def _reset_locations_for_tests() -> None:
    _LOCATIONS.clear()


# ── enumerate + rewrite engine ────────────────────────────────────────────────


def _json_candidate_rows(db: Session, loc: StorageKeyLoc, connection_id: str) -> List[Any]:
    """Rows whose serialized JSON contains ``conn:<id>:`` (a cheap prefilter —
    the in-Python walk then confirms the exact keys)."""
    col = getattr(loc.model, loc.json_column)
    return (
        db.query(loc.model)
        .filter(cast(col, String).like(f"%{_prefix(connection_id)}%"))
        .all()
    )


def enumerate_keys(db: Session, connection_id: str) -> Set[str]:
    """Every DISTINCT ``conn:<connection_id>:<raw>`` blob across ALL registered
    locations (scalar + JSON)."""
    prefix = _prefix(connection_id)
    keys: Set[str] = set()
    for loc in _LOCATIONS.values():
        if loc.is_json:
            for row in _json_candidate_rows(db, loc, connection_id):
                doc = getattr(row, loc.json_column)
                for key in loc.walk(doc):
                    if isinstance(key, str) and key.startswith(prefix):
                        keys.add(key)
        else:
            col = getattr(loc.model, loc.column)
            rows = db.query(distinct(col)).filter(col.like(f"{prefix}%")).all()
            keys.update(r[0] for r in rows if r[0])
    return keys


def rewrite_keys(
    db: Session,
    from_id: str,
    to_id: str,
    only_keys: Optional[Iterable[str]] = None,
) -> int:
    """Rewrite ``conn:<from_id>:`` → ``conn:<to_id>:`` across ALL registered
    locations, value-checked (``LIKE 'conn:<from>:%'``). When ``only_keys`` is
    given, only those exact keys are rewritten (the successfully-copied set —
    Slice-2 D5). Returns the number of affected columns/rows."""
    from_prefix = _prefix(from_id)
    to_prefix = _prefix(to_id)
    only_set: Optional[Set[str]] = set(only_keys) if only_keys is not None else None
    count = 0

    for loc in _LOCATIONS.values():
        if loc.is_json:
            for row in _json_candidate_rows(db, loc, from_id):
                doc = getattr(row, loc.json_column)
                new_doc = loc.rewrite_json(doc, from_prefix, to_prefix, only_set)
                if new_doc != doc:
                    # Reassign a FRESH dict — an in-place mutation of the same
                    # object is not tracked by SQLAlchemy on a plain JSON column.
                    import json

                    setattr(row, loc.json_column, json.loads(json.dumps(new_doc)))
                    count += 1
        else:
            col = getattr(loc.model, loc.column)
            q = db.query(loc.model).filter(col.like(f"{from_prefix}%"))
            if only_set is not None:
                q = q.filter(col.in_(only_set))
            count += q.update(
                {col: func.replace(col, from_prefix, to_prefix)},
                synchronize_session=False,
            )
        db.flush()
    return count


# ── drift-test reflection helper (D9 / AC-10-07) ──────────────────────────────

# Storage-key columns store ``conn:<id>:`` blobs and MUST have a registration.
# Predicate: any column whose name ends with ``_key`` EXCEPT this explicit
# exclude-set (documented so the drift gate is meaningful, not noisy). A NEW
# ``*_key`` column forces a decision — register it or add it here with a reason.
_NON_STORAGE_KEY_COLUMNS = frozenset(
    {
        "template_key",  # template-engine template key (email_outbox, notification_specs)
        "view_key",  # per-user view-preference identifier
        "entity_key",  # terminology entity key
        "dynamic_key",  # notification dynamic-recipient key
        "period_key",  # numbering period key
        "score_field_key",  # review score-field reference
        # A DRAFT WhatsApp media-header sample IS a storage key, but full
        # omnichannel migration wiring is Slice 3 (plan §6) — deferred, tracked.
        "media_sample_key",
    }
)


def _is_storage_key_column(name: str) -> bool:
    return name.endswith("_key") and name not in _NON_STORAGE_KEY_COLUMNS


def all_key_columns(metadatas: Optional[Iterable[Any]] = None) -> Set[Tuple[str, str]]:
    """Reflect every storage-key-shaped column ``(table_name, column_name)`` from
    the given SQLAlchemy metadatas (core ``Base.metadata`` by default). The drift
    test asserts this set ⊆ ``registered_scalar_columns()``."""
    from app.database import Base

    metas = list(metadatas) if metadatas is not None else [Base.metadata]
    found: Set[Tuple[str, str]] = set()
    for meta in metas:
        for table in meta.tables.values():
            for column in table.columns:
                if _is_storage_key_column(column.name):
                    found.add((table.name, column.name))
    return found
