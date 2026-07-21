"""Hop 1 — AutoCount → canonical. **Field mapping is DATA, not code** (D5,
AC-13-08 / AC-13-09).

Why data: per-customer UDF arrays. Customer A's GRN lines carry
``UDF_DriverName``; customer B's carry nothing; customer C's carry three other
things. Encoding that in Python means a release per customer. So a mapping is a
ROW — source path, canonical field, transform — and adding or removing a row
changes behaviour with **no code change** (pinned by a test).

What this layer absorbs, so nothing downstream ever sees it:

* ``"T"`` / ``"F"`` string booleans (and real bools, which also occur)
* three date formats — ``2023/12/01``, ``2024/08/05 16:37:34``, ``2024-09-15``
* 8-dp numeric STRINGS (``"120.00000000"``) → ``Decimal``
* numerics inconsistently typed — ``2`` (int) and ``"10"`` (str) for one field
* the nested detail array key, which is **``GRDTL``** for GRN (not ``GRNDTL``)
* **inconsistent casing, which is inconsistent ON PURPOSE**: GRN uses ``DtlKey``,
  DO uses ``Dtlkey``. Paths are matched **LITERALLY** — no case-folding, no
  normalisation. Normalising would paper over a real vendor difference and make
  the mapping table lie about what the API returns.

**An unconvertible value produces a NAMED per-field error, never a silent null**
(AC-13-09). A silent null is the worst outcome available here: it looks like
"the customer left it blank" and lands in a financial document as zero.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .canonical.grn import (
    ENTITY_GOODS_RECEIVED_NOTE,
    VENDOR_DETAIL_KEY,
    CanonicalGrn,
    CanonicalGrnLine,
)

SCOPE_HEADER = "header"
SCOPE_LINE = "line"
SCOPES = (SCOPE_HEADER, SCOPE_LINE)


class TransformError(ValueError):
    """A value could not be coerced by its configured transform. Always becomes
    a NAMED per-field error — never a silent null."""


# ── transforms (declarative coercion) ─────────────────────────────────────────
# Each returns the coerced value or raises TransformError. ``None``/blank always
# passes through as None: "absent" is not "unconvertible", and a required-but-
# absent field is caught by the mapping row's ``is_required`` flag instead.

_TRUE_TOKENS = {"t", "true", "y", "yes", "1"}
_FALSE_TOKENS = {"f", "false", "n", "no", "0"}

# The three formats observed live, most-specific first. Order matters: a
# date-only parse of "2024/08/05 16:37:34" would fail, but a datetime parse of
# "2024-09-15" must not silently invent a time before the date-only branch runs.
_DATETIME_FORMATS = (
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d",
    "%Y-%m-%d",
)


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def t_string(value: Any) -> Optional[str]:
    if _blank(value):
        return None
    return str(value).strip()


def t_bool(value: Any) -> Optional[bool]:
    """``"T"``/``"F"`` — and real bools, and 1/0, all of which occur."""
    if _blank(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    token = str(value).strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    raise TransformError(f"expected a boolean like 'T' or 'F', got {value!r}")


def t_decimal(value: Any) -> Optional[Decimal]:
    """8-dp strings AND real numbers — the vendor mixes ``2`` and ``"10"`` for
    one field, so both are accepted. Via ``str()`` so a float never introduces
    binary-float noise into money."""
    if _blank(value):
        return None
    if isinstance(value, bool):
        raise TransformError(f"expected a number, got boolean {value!r}")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise TransformError(f"expected a number, got {value!r}") from exc


def t_int(value: Any) -> Optional[int]:
    if _blank(value):
        return None
    if isinstance(value, bool):
        raise TransformError(f"expected an integer, got boolean {value!r}")
    try:
        as_decimal = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise TransformError(f"expected an integer, got {value!r}") from exc
    if as_decimal != as_decimal.to_integral_value():
        raise TransformError(f"expected a whole number, got {value!r}")
    return int(as_decimal)


def _parse_temporal(value: Any) -> datetime:
    raw = str(value).strip()
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:  # ISO-8601 fallback ("2024-09-15T16:37:34Z")
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransformError(
            f"expected a date like '2024/08/05' or '2024-09-15', got {value!r}"
        ) from exc


def t_date(value: Any) -> Optional[date]:
    if _blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return _parse_temporal(value).date()


def t_datetime(value: Any) -> Optional[datetime]:
    """Aware-**UTC** out, always (house datetime rule). The vendor sends no
    offset; its timestamps are read as UTC — the one assumption this layer makes,
    stated here rather than scattered."""
    if _blank(value):
        return None
    parsed = value if isinstance(value, datetime) else _parse_temporal(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


TRANSFORMS = {
    "string": t_string,
    "bool": t_bool,
    "decimal": t_decimal,
    "int": t_int,
    "date": t_date,
    "datetime": t_datetime,
}


# ── source paths ──────────────────────────────────────────────────────────────
# Grammar, deliberately tiny (a mapping row is edited by an operator, not a
# programmer):
#     DocNo                      a top-level key, matched LITERALLY
#     Supplier.Name              a nested dict
#     UDF[UDFDetail].DriverName  a per-customer UDF array (see below)
#
# UDF arrays arrive as ``[{"FieldName": ..., "FieldName2": ..., "Value": ...}]``
# and vary per customer. The path names the ARRAY key and the FieldName to match;
# ``FieldName2`` is checked too because the vendor populates either.

_UDF_PATH = re.compile(r"^UDF\[(?P<array>[^\]]+)\]\.(?P<name>.+)$")

_MISSING = object()


def resolve_path(source: Dict[str, Any], path: str) -> Any:
    """Read ``path`` out of a raw vendor record. Returns ``_MISSING`` when the
    path is absent — distinct from a present-but-null value, which is a real
    ``None`` the customer actually sent."""
    match = _UDF_PATH.match(path)
    if match:
        entries = source.get(match.group("array"))
        if not isinstance(entries, list):
            return _MISSING
        wanted = match.group("name")
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            # LITERAL match on either field-name column — no case folding.
            if entry.get("FieldName") == wanted or entry.get("FieldName2") == wanted:
                return entry.get("Value")
        return _MISSING

    current: Any = source
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


# ── mapping rows ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MappingRow:
    """ONE mapping instruction. This is the unit that lives in
    ``ac_field_mapping`` and the unit an operator adds or removes.

    ``canonical_field`` may be either a declared canonical field (``doc_no``) or
    an arbitrary name, in which case the value lands in the record's ``extras``
    bag. That is what lets a customer surface ``UDF_DriverName`` with no schema
    change anywhere.
    """

    source_path: str
    canonical_field: str
    transform: str = "string"
    scope: str = SCOPE_HEADER
    is_required: bool = False
    is_enabled: bool = True

    def coerce(self, value: Any) -> Any:
        fn = TRANSFORMS.get(self.transform)
        if fn is None:
            raise TransformError(f"unknown transform '{self.transform}'")
        return fn(value)


@dataclass(frozen=True)
class FieldError:
    """A NAMED per-field failure (AC-13-09) — and the raw material for the
    per-document failure message required by AC-13-10, which must name the
    document, the line, and the field."""

    field: str
    source_path: str
    reason: str
    line_no: Optional[int] = None
    doc_no: Optional[str] = None
    doc_key: Optional[str] = None

    def message(self) -> str:
        where = f"line {self.line_no}" if self.line_no else "header"
        doc = self.doc_no or self.doc_key or "document"
        return f"{doc} {where}: field '{self.field}' ({self.source_path}) — {self.reason}"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "sourcePath": self.source_path,
            "reason": self.reason,
            "lineNo": self.line_no,
            "docNo": self.doc_no,
            "docKey": self.doc_key,
            "message": self.message(),
        }


@dataclass
class MappedDocument:
    """One document's hop-1 outcome. ``record`` is None whenever ``errors`` is
    non-empty — **a partially-mapped transaction is never produced** (D13): the
    caller cannot accidentally push half a GRN because half a GRN does not
    exist as a value."""

    record: Optional[CanonicalGrn]
    errors: List[FieldError] = dc_field(default_factory=list)
    raw: Dict[str, Any] = dc_field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.record is not None and not self.errors


# Canonical fields declared on the model; anything else a row targets is an
# ``extras`` key. Computed once per class, not per record.
_HEADER_FIELDS = set(CanonicalGrn.model_fields) - {"lines", "extras"}
_LINE_FIELDS = set(CanonicalGrnLine.model_fields) - {"extras"}


class MappingEngine:
    """Applies mapping ROWS to raw vendor records. Holds no per-customer
    knowledge itself — everything customer-specific arrives as rows.

    One engine per (company, entity); build it from ``ac_field_mapping`` via
    ``MappingEngine.from_rows``.
    """

    def __init__(
        self,
        rows: Sequence[MappingRow],
        *,
        detail_key: str = VENDOR_DETAIL_KEY,
        entity_type: str = ENTITY_GOODS_RECEIVED_NOTE,
    ):
        enabled = [row for row in rows if row.is_enabled]
        self.header_rows = [r for r in enabled if r.scope == SCOPE_HEADER]
        self.line_rows = [r for r in enabled if r.scope == SCOPE_LINE]
        # Per-entity, from config — GRN is GRDTL, DO is DODTL. Never guessed.
        self.detail_key = detail_key
        self.entity_type = entity_type

    # ── one document ──────────────────────────────────────────────────────

    def map_document(self, raw: Dict[str, Any]) -> MappedDocument:
        """Map ONE raw vendor record. Collects EVERY field error rather than
        stopping at the first — an operator fixing a mapping wants the whole
        list, not one error per sync cycle."""
        errors: List[FieldError] = []
        doc_key = t_string(raw.get("DocKey")) or ""
        doc_no = t_string(raw.get("DocNo"))

        header, header_extras = self._apply(
            self.header_rows,
            raw,
            fields=_HEADER_FIELDS,
            errors=errors,
            doc_key=doc_key,
            doc_no=doc_no,
            line_no=None,
        )

        lines: List[CanonicalGrnLine] = []
        details = raw.get(self.detail_key)
        if details is None:
            details = []
        if not isinstance(details, list):
            errors.append(
                FieldError(
                    field="lines",
                    source_path=self.detail_key,
                    reason=f"expected a list of detail lines, got {type(details).__name__}",
                    doc_key=doc_key,
                    doc_no=doc_no,
                )
            )
            details = []

        for index, detail in enumerate(details, start=1):
            if not isinstance(detail, dict):
                errors.append(
                    FieldError(
                        field="lines",
                        source_path=f"{self.detail_key}[{index}]",
                        reason="detail line was not an object",
                        line_no=index,
                        doc_key=doc_key,
                        doc_no=doc_no,
                    )
                )
                continue
            values, extras = self._apply(
                self.line_rows,
                detail,
                fields=_LINE_FIELDS,
                errors=errors,
                doc_key=doc_key,
                doc_no=doc_no,
                line_no=index,
            )
            values.setdefault("line_no", index)
            values["extras"] = extras
            try:
                lines.append(CanonicalGrnLine(**values))
            except Exception as exc:  # noqa: BLE001 — a model reject is a field error
                # Same guard as the header below, and for the same reason: a
                # mapping row is OPERATOR-EDITABLE DATA, so a row can hand the
                # model a value pydantic rejects (``qty`` mapped ``string``, a
                # UOM landing in a Decimal field). Unguarded, that ValidationError
                # escapes map_document → _stage_documents → run_autocount_sync
                # and kills the WHOLE batch, losing every sibling GRN — exactly
                # what AC-13-10 forbids. Named, line-scoped, document-local.
                errors.append(
                    FieldError(
                        field="line",
                        source_path=f"{self.detail_key}[{index}]",
                        reason=f"canonical line rejected the mapped values: {exc}",
                        line_no=index,
                        doc_key=doc_key,
                        doc_no=doc_no,
                    )
                )
                continue

        if not doc_key:
            # Without DocKey there is no stable correlation handle at all — the
            # record could never be re-pushed, diffed or written back.
            errors.append(
                FieldError(
                    field="source_ref",
                    source_path="DocKey",
                    reason="the document carries no DocKey, so it cannot be correlated",
                    doc_no=doc_no,
                )
            )

        if errors:
            # All-or-nothing per document (D13/AC-13-10): no partial record.
            return MappedDocument(record=None, errors=errors, raw=raw)

        header["source_ref"] = doc_key
        header["entity_type"] = self.entity_type
        header["extras"] = header_extras
        header["lines"] = lines
        try:
            record = CanonicalGrn(**header)
        except Exception as exc:  # noqa: BLE001 — a model reject is a field error
            return MappedDocument(
                record=None,
                errors=[
                    FieldError(
                        field="document",
                        source_path="-",
                        reason=f"canonical record rejected the mapped values: {exc}",
                        doc_key=doc_key,
                        doc_no=doc_no,
                    )
                ],
                raw=raw,
            )
        return MappedDocument(record=record, errors=[], raw=raw)

    def map_batch(self, records: Sequence[Dict[str, Any]]) -> List[MappedDocument]:
        """Map many. Each document stands alone — one failure never contaminates
        a sibling (AC-13-10)."""
        return [self.map_document(raw) for raw in records]

    # ── internals ─────────────────────────────────────────────────────────

    def _apply(
        self,
        rows: Sequence[MappingRow],
        source: Dict[str, Any],
        *,
        fields: set,
        errors: List[FieldError],
        doc_key: str,
        doc_no: Optional[str],
        line_no: Optional[int],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        values: Dict[str, Any] = {}
        extras: Dict[str, Any] = {}
        for row in rows:
            raw_value = resolve_path(source, row.source_path)
            missing = raw_value is _MISSING

            if missing and row.is_required:
                errors.append(
                    FieldError(
                        field=row.canonical_field,
                        source_path=row.source_path,
                        reason="required by its mapping row but absent from the response",
                        line_no=line_no,
                        doc_key=doc_key,
                        doc_no=doc_no,
                    )
                )
                continue
            if missing:
                continue

            try:
                coerced = row.coerce(raw_value)
            except TransformError as exc:
                # NAMED per-field error — never a silent null (AC-13-09).
                errors.append(
                    FieldError(
                        field=row.canonical_field,
                        source_path=row.source_path,
                        reason=str(exc),
                        line_no=line_no,
                        doc_key=doc_key,
                        doc_no=doc_no,
                    )
                )
                continue

            if coerced is None and row.is_required:
                errors.append(
                    FieldError(
                        field=row.canonical_field,
                        source_path=row.source_path,
                        reason="required by its mapping row but the value was empty",
                        line_no=line_no,
                        doc_key=doc_key,
                        doc_no=doc_no,
                    )
                )
                continue

            if row.canonical_field in fields:
                values[row.canonical_field] = coerced
            else:
                # Undeclared target → the extras bag. This is what makes a
                # per-customer UDF a pure config change (AC-13-08).
                extras[row.canonical_field] = _json_safe(coerced)
        return values, extras


def _json_safe(value: Any) -> Any:
    """Extras land in a JSON column; Decimal/date are not JSON-serialisable."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


# ── default GRN mapping (SEED DATA, not behaviour) ────────────────────────────
# Seeded into ``ac_field_mapping`` when a company is created. From that moment
# the DATABASE is the source of truth: this list is never consulted again, so an
# operator's edits are never silently reverted by a deploy. It is a starting
# point, deliberately not a fallback.
#
# Casing here is LITERAL vendor casing (GRN's ``DtlKey`` — DO's is ``Dtlkey``).

DEFAULT_GRN_MAPPING: Tuple[MappingRow, ...] = (
    # header
    MappingRow("DocNo", "doc_no", "string", SCOPE_HEADER),
    MappingRow("CreditorCode", "supplier_code", "string", SCOPE_HEADER),
    MappingRow("CompanyName", "supplier_name", "string", SCOPE_HEADER),
    MappingRow("DocDate", "doc_date", "date", SCOPE_HEADER),
    MappingRow("CurrencyCode", "currency_code", "string", SCOPE_HEADER),
    MappingRow("CurrencyRate", "currency_rate", "decimal", SCOPE_HEADER),
    MappingRow("Description", "description", "string", SCOPE_HEADER),
    MappingRow("NetTotal", "net_total", "decimal", SCOPE_HEADER),
    MappingRow("TaxTotal", "tax_total", "decimal", SCOPE_HEADER),
    MappingRow("FinalTotal", "total", "decimal", SCOPE_HEADER),
    MappingRow("Cancelled", "cancelled", "bool", SCOPE_HEADER),
    MappingRow("LastModified", "last_modified", "datetime", SCOPE_HEADER),
    MappingRow("LastModifiedUserID", "last_modified_user_id", "string", SCOPE_HEADER),
    MappingRow("CreatedTimeStamp", "created_at_source", "datetime", SCOPE_HEADER),
    MappingRow("CreatedUserID", "created_user_id", "string", SCOPE_HEADER),
    # lines — GRN detail casing is ``DtlKey`` (DO's is ``Dtlkey``; map literally)
    MappingRow("DtlKey", "source_ref", "string", SCOPE_LINE),
    MappingRow("ItemCode", "item_code", "string", SCOPE_LINE),
    MappingRow("Description", "description", "string", SCOPE_LINE),
    MappingRow("Qty", "qty", "decimal", SCOPE_LINE),
    MappingRow("UOM", "uom", "string", SCOPE_LINE),
    MappingRow("UnitPrice", "unit_price", "decimal", SCOPE_LINE),
    MappingRow("SubTotal", "sub_total", "decimal", SCOPE_LINE),
    MappingRow("Tax", "tax", "decimal", SCOPE_LINE),
    MappingRow("TaxRate", "tax_rate", "string", SCOPE_LINE),
    MappingRow("Location", "location", "string", SCOPE_LINE),
    MappingRow("DeliveryDate", "delivery_date", "date", SCOPE_LINE),
)

DEFAULT_MAPPINGS: Dict[str, Tuple[MappingRow, ...]] = {
    ENTITY_GOODS_RECEIVED_NOTE: DEFAULT_GRN_MAPPING,
}
