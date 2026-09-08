"""Hop 1 - AutoCount → canonical. **Field mapping is DATA, not code** (D5,
AC-13-08 / AC-13-09).

Why data: per-customer UDF arrays. Customer A's GRN lines carry
``UDF_DriverName``; customer B's carry nothing; customer C's carry three other
things. Encoding that in Python means a release per customer. So a mapping is a
ROW - source path, canonical field, transform - and adding or removing a row
changes behaviour with **no code change** (pinned by a test).

What this layer absorbs, so nothing downstream ever sees it:

* ``"T"`` / ``"F"`` string booleans (and real bools, which also occur)
* three date formats - ``2023/12/01``, ``2024/08/05 16:37:34``, ``2024-09-15``
* 8-dp numeric STRINGS (``"120.00000000"``) → ``Decimal``
* numerics inconsistently typed - ``2`` (int) and ``"10"`` (str) for one field
* the nested detail array key, which is **``GRDTL``** for GRN (not ``GRNDTL``)
* **inconsistent casing, which is inconsistent ON PURPOSE**: GRN uses ``DtlKey``,
  DO uses ``Dtlkey``. Paths are matched **LITERALLY** - no case-folding, no
  normalisation. Normalising would paper over a real vendor difference and make
  the mapping table lie about what the API returns.

**An unconvertible value produces a NAMED per-field error, never a silent null**
(AC-13-09). A silent null is the worst outcome available here: it looks like
"the customer left it blank" and lands in a financial document as zero.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Type

from .canonical.base import CanonicalLine, CanonicalRecord
from .formula import FormulaDate, FormulaError, evaluate_formula
from .canonical.grn import (
    ENTITY_GOODS_RECEIVED_NOTE,
    VENDOR_DETAIL_KEY,
    CanonicalGrn,
    CanonicalGrnLine,
)
from .canonical.masters import (
    ENTITY_CUSTOMER,
    ENTITY_PRODUCT,
    ENTITY_PRODUCT_CATEGORY,
    ENTITY_SALES_AGENT,
    ENTITY_SUPPLIER,
    ENTITY_UNIT_OF_MEASURE,
    ENTITY_WAREHOUSE,
    VENDOR_AUTOKEY_PATH,
    VENDOR_LAST_MODIFIED_PATH,
    CanonicalCustomer,
    CanonicalProduct,
    CanonicalProductCategory,
    CanonicalSalesAgent,
    CanonicalSupplier,
    CanonicalUnitOfMeasure,
    CanonicalWarehouse,
)
from .canonical.documents import (
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
    SQL_DOC_LINES_KEY,
    CanonicalPurchaseOrder,
    CanonicalPurchaseOrderLine,
    CanonicalSalesOrder,
    CanonicalSalesOrderLine,
    CanonicalShippingOrder,
    CanonicalShippingOrderLine,
    is_document_entity,
)

SCOPE_HEADER = "header"
SCOPE_LINE = "line"
SCOPES = (SCOPE_HEADER, SCOPE_LINE)

logger = logging.getLogger(__name__)


class TransformError(ValueError):
    """A value could not be coerced by its configured transform. Always becomes
    a NAMED per-field error - never a silent null."""


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
    """``"T"``/``"F"`` - and real bools, and 1/0, all of which occur."""
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
    """8-dp strings AND real numbers - the vendor mixes ``2`` and ``"10"`` for
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
    offset; its timestamps are read as UTC - the one assumption this layer makes,
    stated here rather than scattered."""
    if _blank(value):
        return None
    parsed = value if isinstance(value, datetime) else _parse_temporal(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def t_f_bool(value: Any) -> Optional[bool]:
    """The STRICT master active-flag: ``"T"`` → True, ``"F"`` → False.

    Deliberately narrower than ``t_bool`` (which also takes ``true``/``yes``/1/0)
    because this one governs ``is_active`` on a live supplier or customer in the
    consumer system. **An unrecognised value fails THAT RECORD ONLY, naming the
    field** (AC-14-05) - it is never coerced and never defaulted. A silent
    ``False`` here would deactivate a live supplier in Sorento, and nothing in
    either system would report a problem.

    Blank passes through as None, per the house rule that "absent" is not
    "unconvertible". That is only safe because the seeded ``is_active`` mapping
    rows are ``is_required=True``: a blank then fails the record by the row's own
    flag, with the same named error, instead of falling through to Sorento's
    ``is_active: bool = True`` default.
    """
    if _blank(value):
        return None
    if isinstance(value, bool):
        return value
    token = str(value).strip()
    if token == "T" or token == "t":
        return True
    if token == "F" or token == "f":
        return False
    raise TransformError(f"expected the active flag 'T' or 'F', got {value!r}")


# The master timestamp format, slash-separated and WITHOUT a timezone:
# "2026/03/18 16:03:21".
_SLASH_DATETIME_FORMATS = ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d")


def slash_datetime(value: Any) -> Optional[datetime]:
    """``"2026/03/18 16:03:21"`` → **aware UTC** (house datetime rule).

    The vendor sends no offset. Reading it as UTC is the one assumption this
    layer makes and it is stated here rather than scattered - the same assumption
    ``t_datetime`` already makes for documents.

    Strict about the FORMAT on purpose: this transform is named for the shape it
    accepts, so a value in some other shape is a mapping-row mistake worth a
    named error rather than a lenient parse that hides a wrong path.
    """
    if _blank(value):
        return None
    if isinstance(value, datetime):
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )
    raw = str(value).strip()
    for fmt in _SLASH_DATETIME_FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise TransformError(
        f"expected a timestamp like '2026/03/18 16:03:21', got {value!r}"
    )


# sprint-5/06 (AC-06-01) - Sorento's own `max_length=50` on the linkage
# list fields; extra entries are dropped (never silently truncated with no
# trace) with a WARNING.
LINE_LIST_MAX_LEN = 50


def t_string_list(value: Any, source_path: Optional[str] = None) -> Optional[List[str]]:
    """``"SO1, SO2,,SO1 "`` → ``["SO1", "SO2"]`` - split on comma, strip,
    drop blanks, dedupe preserving first occurrence. Blank passes through as
    None (the same "absent is not unconvertible" house rule every other
    transform follows); a non-string value is a NAMED ``TransformError``
    (AC-13-09), never a silent coercion attempt.

    ``source_path`` (sprint-5/06 review nit) names the mapping row's OWN
    source column in the cap warning below - ``MappingRow.coerce`` passes its
    own ``source_path`` through for this one transform. The raw cell VALUE is
    never logged: a capped list is, by definition, a long (and potentially
    sensitive) comma blob, and a warning worth reading needs to name WHICH
    line source produced it, not echo the blob back.
    """
    if _blank(value):
        return None
    if not isinstance(value, str):
        raise TransformError(f"expected a comma-separated string, got {value!r}")
    seen: List[str] = []
    for piece in value.split(","):
        item = piece.strip()
        if not item or item in seen:
            continue
        seen.append(item)
    if len(seen) > LINE_LIST_MAX_LEN:
        logger.warning(
            "string_list transform capped at %d entries (dropped %d) for "
            "source %s",
            LINE_LIST_MAX_LEN, len(seen) - LINE_LIST_MAX_LEN,
            source_path or "<unknown source>",
        )
        seen = seen[:LINE_LIST_MAX_LEN]
    return seen


TRANSFORMS = {
    "string": t_string,
    "bool": t_bool,
    "decimal": t_decimal,
    "int": t_int,
    "date": t_date,
    "datetime": t_datetime,
    # Master coercions (AC-14-05).
    "t_f_bool": t_f_bool,
    "slash_datetime": slash_datetime,
    # sprint-5/06 (AC-06-01) - `FromSODocList`/comma-separated line targets.
    "string_list": t_string_list,
}


# ── output-type coercion for FORMULA rows (slice 16, AC-16-04) ─────────────────
# A formula produces a language value (str/number/bool/None/FormulaDate). The
# target Sorento/canonical field has a declared type, and the formula's output
# is coerced/validated to it - a mismatch (a formula feeding a boolean field that
# yields a string) is a NAMED per-field error, never a wrong value sent onward.
# Named transforms are NOT run through this: they already return the right type.

# Simple type tokens the engine reasons about.
TYPE_STRING = "string"
TYPE_BOOLEAN = "boolean"
TYPE_DECIMAL = "decimal"
TYPE_INTEGER = "integer"
TYPE_DATETIME = "datetime"
TYPE_DATE = "date"


def _annotation_type_token(annotation: Any) -> Optional[str]:
    """Map a pydantic field annotation → a simple type token, unwrapping
    ``Optional[...]``. Returns None for a shape we don't coerce (list/dict/etc.)."""
    import typing

    origin = typing.get_origin(annotation)
    if origin is typing.Union:  # Optional[X] == Union[X, None]
        inner = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(inner) == 1:
            return _annotation_type_token(inner[0])
        return None
    if annotation is bool:
        return TYPE_BOOLEAN
    if annotation is int:
        return TYPE_INTEGER
    if annotation is Decimal:
        return TYPE_DECIMAL
    if annotation is datetime:
        return TYPE_DATETIME
    if annotation is date:
        return TYPE_DATE
    if annotation is str:
        return TYPE_STRING
    return None


def _field_type_tokens(model: Optional[Type[Any]]) -> Dict[str, Optional[str]]:
    """A canonical field name → type token map derived from a pydantic model,
    used to coerce a formula's output to its target field's type."""
    if model is None:
        return {}
    tokens: Dict[str, Optional[str]] = {}
    for name, info in model.model_fields.items():
        tokens[name] = _annotation_type_token(info.annotation)
    return tokens


def coerce_output(value: Any, type_token: Optional[str]) -> Any:
    """Coerce a FORMULA result to the target field's declared type (AC-16-04).

    A ``FormulaDate`` is materialised to an aware-UTC datetime/date. Numeric and
    datetime targets reuse the module's own transforms (``t_decimal``/``t_int``/
    ``t_datetime``/``t_date``), so a formula and a named transform land the SAME
    Python type in the canonical record. A boolean target demands a real boolean
    - anything else is a ``TransformError`` naming the mismatch.
    """
    if value is None:
        return None

    if isinstance(value, FormulaDate):
        aware = datetime(
            value.year, value.month, value.day,
            value.hour, value.minute, value.second, tzinfo=timezone.utc,
        )
        if type_token == TYPE_DATE:
            return aware.date()
        return aware

    if type_token == TYPE_BOOLEAN:
        if isinstance(value, bool):
            return value
        raise TransformError(
            f"this formula feeds a true/false field but produced {value!r}"
        )
    if type_token == TYPE_DECIMAL:
        return t_decimal(value)
    if type_token == TYPE_INTEGER:
        return t_int(value)
    if type_token == TYPE_DATETIME:
        return t_datetime(value)
    if type_token == TYPE_DATE:
        return t_date(value)
    # string / unknown target - stringify (a bool/number feeding a text field).
    if type_token == TYPE_STRING:
        return t_string(value)
    return value


# ── source paths ──────────────────────────────────────────────────────────────
# Grammar, deliberately tiny (a mapping row is edited by an operator, not a
# programmer):
#     DocNo                      a top-level key, matched LITERALLY
#     Supplier.Name              a nested dict
#     Data.0.AutoKey             a LIST INDEX (masters nest their DB row here)
#     UDF[UDFDetail].DriverName  a per-customer UDF array (see below)
#
# UDF arrays arrive as ``[{"FieldName": ..., "FieldName2": ..., "Value": ...}]``
# and vary per customer. The path names the ARRAY key and the FieldName to match;
# ``FieldName2`` is checked too because the vendor populates either.
#
# The list-index segment exists because a MASTER record nests its real DB row
# under ``Data[0]`` while keeping other fields at the top level - so a mapping
# row genuinely needs to address both (``EmailAddress`` and ``Data.0.AutoKey``).
# Flattening ``Data[0]`` into the parent instead would be simpler to implement
# and worse to operate: both levels carry unique fields AND overlapping ones
# (``AccNo``/``CompanyName``/``IsActive``/``CreditLimit``), so a flatten needs an
# invisible precedence rule for the overlaps. An explicit path keeps the source
# of every value visible to the operator editing the row, which is the whole
# point of mapping being data.

_UDF_PATH = re.compile(r"^UDF\[(?P<array>[^\]]+)\]\.(?P<name>.+)$")

_MISSING = object()


def resolve_path(source: Dict[str, Any], path: str) -> Any:
    """Read ``path`` out of a raw vendor record. Returns ``_MISSING`` when the
    path is absent - distinct from a present-but-null value, which is a real
    ``None`` the customer actually sent.

    **Never raises.** A wrong path is an operator's data-entry mistake in a
    mapping row, and it must surface as that row's named per-field error (or as
    a skipped optional field), never as an exception that kills the batch.
    """
    match = _UDF_PATH.match(path)
    if match:
        entries = source.get(match.group("array"))
        if not isinstance(entries, list):
            return _MISSING
        wanted = match.group("name")
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            # LITERAL match on either field-name column - no case folding.
            if entry.get("FieldName") == wanted or entry.get("FieldName2") == wanted:
                return entry.get("Value")
        return _MISSING

    current: Any = source
    for part in path.split("."):
        if isinstance(current, list):
            # A numeric segment indexes a list. Non-negative only: "-1" would be
            # Python's last-element sugar, which reads as a typo in a mapping row
            # and would silently point at a different record as the list grows.
            if not part.isdigit():
                return _MISSING
            index = int(part)
            if index >= len(current):
                return _MISSING
            current = current[index]
        elif isinstance(current, dict):
            if part not in current:
                return _MISSING
            current = current[part]
        else:
            # A scalar with path left to walk - the path does not fit this
            # record's shape.
            return _MISSING
    return current


def read_path(source: Dict[str, Any], path: str) -> Optional[Any]:
    """``resolve_path`` for callers outside the mapping loop, with the sentinel
    normalised to ``None`` (they have no per-field error to raise)."""
    value = resolve_path(source, path)
    return None if value is _MISSING else value


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
    # Optional safe transform formula (slice 16). NULL ⇒ the named ``transform``
    # runs (byte-identical to before this slice). Set ⇒ the formula is
    # authoritative and the named transform is ignored for value production.
    formula: Optional[str] = None

    def coerce(
        self,
        value: Any,
        transforms: Optional[Dict[str, Callable[[Any], Any]]] = None,
        facts: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """``transforms`` overrides the module-level ``TRANSFORMS`` lookup -
        ``MappingEngine`` passes its own INSTANCE-bound table (plan 22 S5) so a
        ``ref_*`` transform can close over the engine's ``database_name``.
        ``None`` (every pre-S5 caller) falls back to the plain module table -
        byte-identical to before.

        ``facts`` (sprint-5/02, AC-02-07/09) - the NAMED-variable dict a
        document header formula may reference (its own raw record + the
        ``lines.*`` aggregates), passed straight through to
        ``evaluate_formula``. ``None`` for every non-document/non-header row -
        the formula then sees only the built-in ``value``, byte-identical to
        before this slice.
        """
        if self.formula:
            # A BLANK source value short-circuits to None WITHOUT evaluating -
            # exactly as every named transform treats blank (``_blank`` → None).
            # This keeps "absent is not unconvertible" and lets the row's
            # ``is_required`` flag catch a required-but-empty field, so a formula
            # preset (e.g. the Boolean ``if(value=="T",…)``) can never silently
            # turn a blank ``is_active`` into False.
            if _blank(value):
                return None
            try:
                return evaluate_formula(self.formula, value, facts)
            except FormulaError as exc:
                # A runtime formula fault becomes a NAMED per-field error via the
                # engine's existing ``except TransformError`` path (AC-16-03).
                raise TransformError(str(exc)) from exc
        table = transforms if transforms is not None else TRANSFORMS
        fn = table.get(self.transform)
        if fn is None:
            raise TransformError(f"unknown transform '{self.transform}'")
        # `string_list` is the one transform that names its OWN source in a
        # cap warning (review nit) - every other transform keeps the plain
        # single-arg call, byte-identical to before.
        if self.transform in LIST_TRANSFORMS:
            return fn(value, source_path=self.source_path)
        return fn(value)


@dataclass(frozen=True)
class FieldError:
    """A NAMED per-field failure (AC-13-09) - and the raw material for the
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
        return f"{doc} {where}: field '{self.field}' ({self.source_path}) - {self.reason}"

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
    non-empty - **a partially-mapped transaction is never produced** (D13): the
    caller cannot accidentally push half a GRN because half a GRN does not
    exist as a value."""

    record: Optional[CanonicalRecord]
    errors: List[FieldError] = dc_field(default_factory=list)
    raw: Dict[str, Any] = dc_field(default_factory=dict)
    # The human-facing number for this record (``DocNo`` on a document, ``AccNo``
    # on a master). Carried here rather than read off ``record`` because the
    # attribute NAME differs per entity, and a caller reaching for
    # ``record.doc_no`` on a master silently gets None.
    doc_no: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.record is not None and not self.errors


# ── identity (AC-14-10/11) ────────────────────────────────────────────────────


class IdentityError(ValueError):
    """A record carries no usable correlation handle. Becomes a named per-record
    error, exactly like a failed coercion."""


def doc_key_identity(raw: Dict[str, Any], database_name: str) -> str:
    """Documents: the vendor's ``DocKey``.

    Never ``DocNo`` - the vendor exposes ``NewDocNo``, so ``DocNo`` is MUTABLE
    and correlating on it forks a document in two the first time a customer
    renumbers one.
    """
    key = t_string(raw.get("DocKey")) or ""
    if not key:
        raise IdentityError(
            "the document carries no DocKey, so it cannot be correlated"
        )
    return key


def company_qualified_identity(raw: Dict[str, Any], database_name: str) -> str:
    """Masters: ``"{DatabaseName}:{AutoKey}"`` (AC-14-10).

        !!  THE COMPANY PREFIX IS LOAD-BEARING, NOT DECORATION.  !!

    ``AutoKey`` is a PER-COMPANY primary key - ``AutoKey=1`` exists in every
    AutoCount company - while the consumer's uniqueness is
    ``(source_system, entity_type, source_ref)`` with **no company dimension**.
    We support several companies per tenant, so an unqualified ref collides on
    the second company connected: two different suppliers would resolve to one
    consumer row and overwrite each other silently.

    Not ``Guid`` (Debtor rows carry one, Creditor rows do not) and not ``AccNo``
    (a business code an operator can renumber, which would orphan the link and
    duplicate the record - AC-14-11).
    """
    key = t_string(read_path(raw, VENDOR_AUTOKEY_PATH)) or ""
    if not key:
        raise IdentityError(
            f"the record carries no {VENDOR_AUTOKEY_PATH}, so it cannot be correlated"
        )
    company = (database_name or "").strip()
    if not company:
        raise IdentityError(
            "the company database name is unknown, so the record cannot be "
            "company-qualified and would collide with another company's records"
        )
    return f"{company}:{key}"


# ── flat (direct-DB) identity - plan 22 §2.5, AC-22-10 ───────────────────────
# A ``sql_db`` task's rows are FLAT: the source path is a result column name and
# there is no vendor envelope to reach into. Only IDENTITY differs from the API
# path, and it must land on the SAME string (see below).

# The one entity whose ``source_ref`` is deliberately NOT company-qualified.
UNQUALIFIED_REF_ENTITIES = {ENTITY_SALES_AGENT}
SALES_AGENT_REF_PREFIX = "agent"
# Separator between the parts of a COMPOSITE key. Not ``:`` - that already
# separates the company qualifier from the key, and reusing it would make
# ``("A:B", "C")`` and ``("A", "B:C")`` the same ref.
KEY_PART_SEPARATOR = "|"


def flat_source_ref(
    raw: Dict[str, Any],
    *,
    database_name: str,
    key_columns: Sequence[str],
    entity_type: str,
) -> str:
    """``"{DatabaseName}:{key1[|key2]}"`` from a flat DB row (AC-22-10).

        !!  THIS MUST EQUAL ``company_qualified_identity`` FOR THE SAME ROW.  !!

    A company that already synced customers over the API path and then switches
    to the DB path keeps its consumer records ONLY if the ref is byte-identical:
    Sorento's uniqueness is ``(source_system, entity_type, source_ref)``, so a
    different scheme is not a migration, it is a duplicate ``created`` wave on a
    live consumer. The API path mints ``{DatabaseName}:{AutoKey}``; pointing a
    DB task's key column at ``AutoKey`` therefore lands on the same string.

    ``sales_agent`` is the ONE exception (Appendix A6 §6): Sorento's agent rows
    are SHARED across companies (``company_id`` NULL), so a company-qualified
    ref would make the second company's push ``failed``. Its ref is
    ``agent:{CODE}``, upper-cased and trimmed, so every company resolves to the
    one shared row. ``CanonicalSalesAgent.code`` normalizes the SAME way on
    construction (S4 review NIT) - so the payload's ``code`` can never
    disagree with the ref it is filed under, regardless of which mapping
    transform an operator picked for the source column.
    """
    columns = [str(c) for c in key_columns if str(c).strip()]
    if not columns:
        raise IdentityError(
            "the task has no key columns, so its rows cannot be correlated"
        )
    parts: List[str] = []
    for column in columns:
        value = t_string(raw.get(column))
        if not value:
            raise IdentityError(
                f"the row carries no '{column}', so it cannot be correlated"
            )
        parts.append(value)

    if entity_type in UNQUALIFIED_REF_ENTITIES:
        key = KEY_PART_SEPARATOR.join(p.upper() for p in parts)
        return f"{SALES_AGENT_REF_PREFIX}:{key}"

    company = (database_name or "").strip()
    if not company:
        raise IdentityError(
            "the company database name is unknown, so the row cannot be "
            "company-qualified and would collide with another company's records"
        )
    return f"{company}:{KEY_PART_SEPARATOR.join(parts)}"


# ── master reference minting (plan 22 S5, Appendix A6 item 3) ────────────────
# A document field like ``customer_ref``/``product_ref`` must carry the EXACT
# ``source_ref`` the referenced master was pushed under - never invented here.
# ``mint_master_ref`` reuses ``flat_source_ref`` itself (the SAME function a
# master task uses for its own identity, single-column) so the two schemes can
# never drift apart. Named "ref_<entity>" TRANSFORMS below let an operator pick
# one in the mapping editor for a HEADER ref field (``customer_ref``,
# ``sales_agent_ref``, ``supplier_ref``); a document's LINE ref fields
# (``product_ref``/``warehouse_ref``) are minted the SAME way but via
# ``document_line_rows`` (below), never operator-mapped (plan §Scope item 3 -
# "FIXED column-name convention").

_REF_COLUMN = "_ref"


def mint_master_ref(value: Any, *, database_name: str, entity_type: str) -> Optional[str]:
    """``value`` (a master's own code column, raw) -> that master's
    ``source_ref`` scheme. Blank passes through as None (absent is not
    unconvertible, the house rule every named transform follows)."""
    if _blank(value):
        return None
    try:
        return flat_source_ref(
            {_REF_COLUMN: value},
            database_name=database_name,
            key_columns=[_REF_COLUMN],
            entity_type=entity_type,
        )
    except IdentityError as exc:
        raise TransformError(str(exc)) from exc


# transform name -> the master entity_type it mints a ref for. Registered as
# INSTANCE-bound transforms on ``MappingEngine`` (they need ``database_name``,
# which a module-level pure function cannot close over) - see
# ``MappingEngine._transforms``.
REF_TRANSFORM_ENTITIES: Dict[str, str] = {
    "ref_customer": ENTITY_CUSTOMER,
    "ref_supplier": ENTITY_SUPPLIER,
    "ref_product": ENTITY_PRODUCT,
    "ref_warehouse": ENTITY_WAREHOUSE,
    "ref_sales_agent": ENTITY_SALES_AGENT,
}


def _unbound_ref_transform(entity_type: str) -> Callable[[Any], Any]:
    """The ``TRANSFORMS``-dict entry for a ``ref_*`` name - present ONLY so
    ``company_service.replace_mapping``'s "is this a known transform?" save
    guard accepts the name. A real coercion always goes through
    ``MappingEngine._transforms`` (bound to a ``database_name`` at
    construction) - reaching this unbound version is a wiring bug, so it fails
    loudly rather than minting an un-company-qualified ref."""

    def _unbound(value: Any) -> Any:
        raise TransformError(
            f"'{entity_type}' reference minting needs a company context and "
            "cannot run outside a MappingEngine."
        )

    return _unbound


# Registered into the module-level TRANSFORMS dict below (import order: this
# runs after TRANSFORMS is defined) purely for the save-time "is this a known
# transform name" check - never invoked for real coercion (see the docstring
# above).
TRANSFORMS.update(
    {name: _unbound_ref_transform(entity) for name, entity in REF_TRANSFORM_ENTITIES.items()}
)


# ── field <-> ref-transform pairing (S5 review BLOCKER 2) ────────────────────
# Which canonical field REQUIRES which ``ref_*`` transform - the save-time
# guard (``company_service.replace_mapping``) enforces BOTH directions: a
# ``ref_*`` transform may only be used on ITS matching field (never smuggled
# onto an unrelated one - the field-level equivalent of the accepted-target
# guard), and a ``*_ref`` field may ONLY be saved with its own ref transform
# (a plain/string transform would ship the bare AutoCount code as the "ref" -
# Sorento cannot resolve it as a reference, and the row is stuck retrying
# forever with no error naming why). ``product_ref``/``warehouse_ref`` are
# deliberately absent HERE (never absent from the engine): they are
# LINE-scope fields, paired in ``LINE_FIELD_REF_TRANSFORMS`` below against the
# LINE catalog instead - this dict is the HEADER-scope pairing only.
FIELD_REF_TRANSFORMS: Dict[str, str] = {
    "customer_ref": "ref_customer",
    "supplier_ref": "ref_supplier",
    "sales_agent_ref": "ref_sales_agent",
}

# The LINE-scope equivalent (sprint-5/02, AC-02-03) - now that a document's
# line fields are operator-editable persisted rows (never code-generated),
# ``product_ref``/``warehouse_ref`` need the SAME locked-pair guard header
# ref fields already have.
LINE_FIELD_REF_TRANSFORMS: Dict[str, str] = {
    "product_ref": "ref_product",
    "warehouse_ref": "ref_warehouse",
}

# sprint-5/06 (AC-06-11) - the line-linkage fields each accept a NARROW
# transform set, foolproof server-side: an input KEY field is only ever an
# AutoCount int key (Pydantic coerces a numeric string into the int field,
# so "string" is accepted too for a source column typed as text); the two
# same-book db/doc-no fields are plain text; `from_so_numbers` is the ONE
# field the `string_list` transform may target (a plain "string" would ship
# the raw comma-separated cell straight through, which Sorento's
# `max_length=50` list field would reject whole).
LINE_FIELD_ALLOWED_TRANSFORMS: Dict[str, frozenset] = {
    "from_so_doc_key": frozenset({"int", "string"}),
    "from_so_line_key": frozenset({"int", "string"}),
    "from_so_external_doc_key": frozenset({"int", "string"}),
    "from_so_external_line_key": frozenset({"int", "string"}),
    "from_po_doc_key": frozenset({"int", "string"}),
    "from_po_line_key": frozenset({"int", "string"}),
    "from_so_external_db": frozenset({"string"}),
    "from_so_external_doc_no": frozenset({"string"}),
    "from_so_numbers": frozenset({"string_list"}),
}

# A canonical LINE field whose declared shape is a LIST (only
# `from_so_numbers` today) - a formula row may never target it (AC-06-11):
# the formula language produces a scalar, never a list.
LINE_LIST_FIELDS: frozenset = frozenset({"from_so_numbers"})

# (sprint-5/06 review S3) - the transform(s) that PRODUCE a list value (only
# `string_list` today). A list transform saved onto a target outside
# ``LINE_LIST_FIELDS`` - any other line field, or ANY header field (a header
# has no list-shaped target at all) - is the same both-directions mistake
# ``FIELD_REF_TRANSFORMS``/``LINE_FIELD_REF_TRANSFORMS`` already lock: the
# transform and its one legitimate target are a pair, enforced at save time
# by ``company_service._replace_header_mapping``/``_replace_line_mapping``.
LIST_TRANSFORMS: frozenset = frozenset({"string_list"})

# The documented default `status` formula a document preset seeds (sprint-5/02,
# AC-02-08, amended by the review round - a header with ZERO lines yet (a
# fresh SO/PO before its detail rows have synced) must read "open", not
# "closed" - `lines.open_count == 0` alone cannot distinguish "no lines" from
# "every line closed"). Defined ONCE here (mapping.py, not presets.py) so the
# ENGINE-level tests (which build ``MappingRow`` by hand, never through a
# preset) and the seeding code share the exact same string.
DEFAULT_STATUS_FORMULA = (
    'if(Cancelled == "T", "cancelled", '
    'if(lines.count == 0, "open", '
    'if(lines.open_count == 0, "closed", "open")))'
)

# canonical line field -> (transform name, is required) per document entity
# (review-round B1 - reintroduced). This is the FIXED set of line fields
# every document header carries alongside its picker-derived ref rows
# (source_ref/product_ref/warehouse_ref) - the shape the now-deleted
# `document_line_rows` code-generated before line rows became operator-
# editable persisted `AcFieldMapping` rows (sprint-5/02 AC-02-03). It is NOT
# an engine input any more; it exists solely as the reference the migration
# backfill (`backfill.backfill_document_line_mapping_pickers`) seeds against,
# using the FIXED column-name convention the old code-gen path relied on
# (`source_path == canonical_field` - the lineQuery must return a column
# named exactly like the canonical field it feeds).
_SO_LINE_FIXED_FIELDS: Tuple[Tuple[str, str, bool], ...] = (
    ("qty_ordered", "decimal", True),
    ("qty_delivered", "decimal", False),
    ("unit_price", "decimal", False),
    ("discount", "decimal", False),
    ("line_total", "decimal", False),
    ("uom", "string", False),
    ("required_date", "date", False),
)
_PO_LINE_FIXED_FIELDS: Tuple[Tuple[str, str, bool], ...] = (
    ("qty_ordered", "decimal", True),
    ("qty_received", "decimal", False),
    ("unit_cost", "decimal", False),
    ("discount", "decimal", False),
    ("line_total", "decimal", False),
    ("uom", "string", False),
    ("currency", "string", False),
    ("expected_date", "date", False),
)
DOCUMENT_LINE_FIXED_FIELDS: Dict[str, Tuple[Tuple[str, str, bool], ...]] = {
    ENTITY_SALES_ORDER: _SO_LINE_FIXED_FIELDS,
    ENTITY_PURCHASE_ORDER: _PO_LINE_FIXED_FIELDS,
    # SPO shares the PO shape end-to-end (presets.py reuses the PO header/
    # line SQL verbatim) - same fixed-field set.
    ENTITY_SHIPPING_ORDER: _PO_LINE_FIXED_FIELDS,
}


# ── entity profiles ───────────────────────────────────────────────────────────
# What differs BETWEEN entities, in one place. Adding an entity is a profile plus
# mapping rows; the engine below is entity-agnostic.


@dataclass(frozen=True)
class EntityProfile:
    """The per-entity shape the mapping engine works against."""

    entity_type: str
    record_model: Type[CanonicalRecord]
    # How ``source_ref`` is minted. Identity is part of the CANONICAL SHAPE, not
    # of transport: staging, the diff and the eventual push must all key on the
    # same string, and minting it at push time would let a staged record and its
    # pushed counterpart disagree.
    identity: Callable[[Dict[str, Any], str], str] = doc_key_identity
    # The source path of the human-facing number, for display + error messages.
    display_path: str = "DocNo"
    # Nested detail lines. None = this entity has none (masters are flat).
    line_model: Optional[Type[CanonicalLine]] = None
    detail_key: Optional[str] = None
    # The path the identity function reads, named so a failure can point at it.
    identity_path: str = "DocKey"
    # Documents only (plan 22 S5): a mapped line's ``source_ref`` (the raw
    # DtlKey-equivalent a mapping row produced) is composed into
    # ``{header_source_ref}:{line_source_ref}`` AFTER mapping, never before -
    # the header's OWN ref is not known until identity resolves. False for
    # every non-document profile (a GRN line's ``source_ref`` stays the bare
    # DtlKey it always was - unchanged behaviour, S1 regression pin).
    line_ref_prefix: bool = False
    # sprint-5/02 (AC-02-07) - which mapped LINE canonical field carries the
    # "fulfilled" quantity for this document's aggregates (`qty_delivered`
    # for a sales order, `qty_received` for a purchase/shipping order). None
    # for every non-document profile - `MappingEngine` skips aggregate
    # computation entirely rather than guess a field name.
    line_fulfilled_field: Optional[str] = None

    def record_fields(self) -> set:
        return set(self.record_model.model_fields) - {"lines", "extras"}

    def line_fields(self) -> set:
        if self.line_model is None:
            return set()
        return set(self.line_model.model_fields) - {"extras"}


GRN_PROFILE = EntityProfile(
    entity_type=ENTITY_GOODS_RECEIVED_NOTE,
    record_model=CanonicalGrn,
    identity=doc_key_identity,
    display_path="DocNo",
    line_model=CanonicalGrnLine,
    detail_key=VENDOR_DETAIL_KEY,
    identity_path="DocKey",
)

SUPPLIER_PROFILE = EntityProfile(
    entity_type=ENTITY_SUPPLIER,
    record_model=CanonicalSupplier,
    identity=company_qualified_identity,
    display_path="AccNo",
    identity_path=VENDOR_AUTOKEY_PATH,
)

CUSTOMER_PROFILE = EntityProfile(
    entity_type=ENTITY_CUSTOMER,
    record_model=CanonicalCustomer,
    identity=company_qualified_identity,
    display_path="AccNo",
    identity_path=VENDOR_AUTOKEY_PATH,
)

# ── plan 22 S4 masters fan-out (AC-22-23) ─────────────────────────────────────
# These five are DB-source ONLY - there is no confirmed AutoCount API payload
# behind them (``services/company_service.py``'s ``SEEDED_ENTITIES`` guard), so
# their ``identity``/``display_path``/``identity_path`` below are the profile's
# API-path defaults ONLY in shape; every real task runs through
# ``flat_profile()``, which re-points identity at ``flat_source_ref`` (masters:
# company-qualified; sales_agent: the shared ``agent:{CODE}`` ref via
# ``UNQUALIFIED_REF_ENTITIES`` below) regardless of what is registered here.
PRODUCT_CATEGORY_PROFILE = EntityProfile(
    entity_type=ENTITY_PRODUCT_CATEGORY,
    record_model=CanonicalProductCategory,
    identity=company_qualified_identity,
    display_path="Code",
    identity_path="Code",
)

UNIT_OF_MEASURE_PROFILE = EntityProfile(
    entity_type=ENTITY_UNIT_OF_MEASURE,
    record_model=CanonicalUnitOfMeasure,
    identity=company_qualified_identity,
    display_path="Code",
    identity_path="Code",
)

WAREHOUSE_PROFILE = EntityProfile(
    entity_type=ENTITY_WAREHOUSE,
    record_model=CanonicalWarehouse,
    identity=company_qualified_identity,
    display_path="Code",
    identity_path="Code",
)

PRODUCT_PROFILE = EntityProfile(
    entity_type=ENTITY_PRODUCT,
    record_model=CanonicalProduct,
    identity=company_qualified_identity,
    display_path="Code",
    identity_path="Code",
)

SALES_AGENT_PROFILE = EntityProfile(
    entity_type=ENTITY_SALES_AGENT,
    record_model=CanonicalSalesAgent,
    identity=company_qualified_identity,
    display_path="Code",
    identity_path="Code",
)

# ── plan 22 S5 documents (AC-22-24) - DB-source ONLY, same reasoning as the S4
# masters fan-out above: no confirmed AutoCount API payload backs a document
# task, so `identity`/`display_path`/`identity_path` below are API-path-shape
# defaults ONLY; every real task runs through `flat_profile`, which re-points
# identity at `flat_source_ref` regardless of what is registered here. What
# DOES carry through `flat_profile` unchanged is `line_model`/`detail_key`/
# `line_ref_prefix` - a document's lines are real, fetched by a second query
# (`sql_source.source.SqlDbSource`), nested under `SQL_DOC_LINES_KEY`.
SALES_ORDER_PROFILE = EntityProfile(
    entity_type=ENTITY_SALES_ORDER,
    record_model=CanonicalSalesOrder,
    identity=doc_key_identity,
    display_path="DocNo",
    line_model=CanonicalSalesOrderLine,
    detail_key=SQL_DOC_LINES_KEY,
    identity_path="DocKey",
    line_ref_prefix=True,
    line_fulfilled_field="qty_delivered",
)

PURCHASE_ORDER_PROFILE = EntityProfile(
    entity_type=ENTITY_PURCHASE_ORDER,
    record_model=CanonicalPurchaseOrder,
    identity=doc_key_identity,
    display_path="DocNo",
    line_model=CanonicalPurchaseOrderLine,
    detail_key=SQL_DOC_LINES_KEY,
    identity_path="DocKey",
    line_ref_prefix=True,
    line_fulfilled_field="qty_received",
)

# sprint-5/02 S3 (addendum section 3) - a LINE-SET entity on Sorento's side,
# but an ordinary document on the ESB's own fetch/mapping side: same shape as
# the PO family (a receiving document), zero engine changes needed here.
SHIPPING_ORDER_PROFILE = EntityProfile(
    entity_type=ENTITY_SHIPPING_ORDER,
    record_model=CanonicalShippingOrder,
    identity=doc_key_identity,
    display_path="DocNo",
    line_model=CanonicalShippingOrderLine,
    detail_key=SQL_DOC_LINES_KEY,
    identity_path="DocKey",
    line_ref_prefix=True,
    line_fulfilled_field="qty_received",
)

ENTITY_PROFILES: Dict[str, EntityProfile] = {
    GRN_PROFILE.entity_type: GRN_PROFILE,
    SUPPLIER_PROFILE.entity_type: SUPPLIER_PROFILE,
    CUSTOMER_PROFILE.entity_type: CUSTOMER_PROFILE,
    PRODUCT_CATEGORY_PROFILE.entity_type: PRODUCT_CATEGORY_PROFILE,
    UNIT_OF_MEASURE_PROFILE.entity_type: UNIT_OF_MEASURE_PROFILE,
    WAREHOUSE_PROFILE.entity_type: WAREHOUSE_PROFILE,
    PRODUCT_PROFILE.entity_type: PRODUCT_PROFILE,
    SALES_AGENT_PROFILE.entity_type: SALES_AGENT_PROFILE,
    SALES_ORDER_PROFILE.entity_type: SALES_ORDER_PROFILE,
    PURCHASE_ORDER_PROFILE.entity_type: PURCHASE_ORDER_PROFILE,
    SHIPPING_ORDER_PROFILE.entity_type: SHIPPING_ORDER_PROFILE,
}


def flat_profile(entity_type: str, key_columns: Sequence[str]) -> EntityProfile:
    """The entity's profile re-pointed at FLAT rows (plan 22 §2.5).

    Identity is minted from the task's key columns and the display path is the
    first key column. ``line_model``/``detail_key``/``line_ref_prefix`` carry
    through UNCHANGED from the base profile (S5) - a master's are all
    None/False (masters are flat, no change from before S5); a document's
    point at ``SQL_DOC_LINES_KEY`` so `SqlDbSource`'s per-header line fetch
    (nested there) maps through the SAME engine a nested API envelope would.
    The CANONICAL MODEL is untouched either way, so the sink still receives
    exactly the shape it would over an API path.
    """
    base = profile_for(entity_type)
    columns = [str(c) for c in key_columns if str(c).strip()]

    def identity(raw: Dict[str, Any], database_name: str) -> str:
        return flat_source_ref(
            raw,
            database_name=database_name,
            key_columns=columns,
            entity_type=entity_type,
        )

    return EntityProfile(
        entity_type=base.entity_type,
        record_model=base.record_model,
        identity=identity,
        display_path=columns[0] if columns else base.display_path,
        line_model=base.line_model,
        detail_key=base.detail_key,
        identity_path=", ".join(columns) or base.identity_path,
        line_ref_prefix=base.line_ref_prefix,
        line_fulfilled_field=base.line_fulfilled_field,
    )


class UnknownEntityProfile(Exception):
    """A configured entity has no profile. LOUD - mapping it as a GRN would
    produce a canonical record of the wrong shape and no error at all."""


def profile_for(entity_type: str) -> EntityProfile:
    profile = ENTITY_PROFILES.get(entity_type)
    if profile is None:
        raise UnknownEntityProfile(
            f"No AutoCount entity profile registered for '{entity_type}'."
        )
    return profile


class MappingEngine:
    """Applies mapping ROWS to raw vendor records. Holds no per-customer
    knowledge itself - everything customer-specific arrives as rows.

    One engine per (company, entity); build it from ``ac_field_mapping`` via
    ``MappingEngine.from_rows``.
    """

    def __init__(
        self,
        rows: Sequence[MappingRow],
        *,
        detail_key: Optional[str] = None,
        entity_type: str = ENTITY_GOODS_RECEIVED_NOTE,
        profile: Optional[EntityProfile] = None,
        database_name: str = "",
    ):
        enabled = [row for row in rows if row.is_enabled]
        self.header_rows = [r for r in enabled if r.scope == SCOPE_HEADER]
        self.line_rows = [r for r in enabled if r.scope == SCOPE_LINE]
        self.profile = profile or profile_for(entity_type)
        self.entity_type = self.profile.entity_type
        # Per-entity, from config - GRN is GRDTL, DO is DODTL. Never guessed.
        # ``None`` means "use the profile's", NOT "no lines": an explicit
        # override still wins, so a customer whose wrapper renames the array can
        # be fixed from config.
        self.detail_key = detail_key if detail_key is not None else self.profile.detail_key
        # The company this engine maps FOR. Masters mint a company-qualified
        # ``source_ref`` from it (AC-14-10); a document's ``ref_*`` transforms
        # (plan 22 S5) use it the SAME way to mint the master refs a line/
        # header points AT.
        self.database_name = database_name
        # INSTANCE-bound transform table (plan 22 S5): the module-level
        # ``TRANSFORMS`` entries plus this engine's own ``ref_*`` closures -
        # everything else about ``MappingRow.coerce`` is unchanged.
        self._transforms: Dict[str, Callable[[Any], Any]] = dict(TRANSFORMS)
        for transform_name, ref_entity_type in REF_TRANSFORM_ENTITIES.items():
            self._transforms[transform_name] = self._ref_transform(ref_entity_type)
        self._record_fields = self.profile.record_fields()
        self._line_fields = self.profile.line_fields()
        # Declared field types, for coercing a FORMULA row's output (AC-16-04).
        self._record_field_types = _field_type_tokens(self.profile.record_model)
        self._line_field_types = _field_type_tokens(self.profile.line_model)

    def _ref_transform(self, ref_entity_type: str) -> Callable[[Any], Any]:
        """Bind ``mint_master_ref`` to THIS engine's ``database_name`` - the
        thing a module-level pure transform cannot do (plan 22 S5)."""

        def transform(value: Any) -> Optional[str]:
            return mint_master_ref(
                value, database_name=self.database_name, entity_type=ref_entity_type
            )

        return transform

    def _header_facts(self, raw: Dict[str, Any], lines: Sequence[Any]) -> Dict[str, Any]:
        """The NAMED-variable fact dict a header formula may reference
        (sprint-5/02, AC-02-07/09): the header's own raw record verbatim
        (so ``Cancelled`` resolves straight off the source row) PLUS, for a
        document entity whose profile names a ``line_fulfilled_field``, the
        ``lines.*`` aggregates over the ALREADY-MAPPED line objects.

        ``outstanding`` per line is ``max(0, ordered - fulfilled)`` - a line
        somehow over-delivered/over-received never goes NEGATIVE and cancel
        out another line's genuine shortfall in the sum.
        """
        facts: Dict[str, Any] = dict(raw)
        if not (is_document_entity(self.entity_type) and self.profile.line_fulfilled_field):
            return facts
        ordered_field = "qty_ordered"
        fulfilled_field = self.profile.line_fulfilled_field
        zero = Decimal("0")
        ordered_sum = zero
        fulfilled_sum = zero
        outstanding_sum = zero
        open_count = 0
        for line in lines:
            ordered = getattr(line, ordered_field, None) or zero
            fulfilled = getattr(line, fulfilled_field, None) or zero
            outstanding = ordered - fulfilled
            if outstanding < zero:
                outstanding = zero
            ordered_sum += ordered
            fulfilled_sum += fulfilled
            outstanding_sum += outstanding
            if outstanding > zero:
                open_count += 1
        facts.update({
            "lines.count": len(lines),
            "lines.open_count": open_count,
            "lines.ordered_sum": ordered_sum,
            "lines.fulfilled_sum": fulfilled_sum,
            "lines.outstanding_sum": outstanding_sum,
        })
        return facts

    # ── one document ──────────────────────────────────────────────────────

    def map_document(self, raw: Dict[str, Any]) -> MappedDocument:
        """Map ONE raw vendor record. Collects EVERY field error rather than
        stopping at the first - an operator fixing a mapping wants the whole
        list, not one error per sync cycle."""
        errors: List[FieldError] = []
        doc_no = t_string(read_path(raw, self.profile.display_path))

        # Identity FIRST, so every error below can name the record. A failure
        # here is recorded and mapping continues: the operator gets the whole
        # error list in one pass rather than one error per sync cycle.
        source_ref = ""
        try:
            source_ref = self.profile.identity(raw, self.database_name)
        except IdentityError as exc:
            errors.append(
                FieldError(
                    field="source_ref",
                    source_path=self.profile.identity_path,
                    reason=str(exc),
                    doc_no=doc_no,
                )
            )
        doc_key = source_ref

        #     !!  LINES MAP BEFORE THE HEADER (sprint-5/02, AC-02-07).  !!
        # A document's `status` (and any other header formula) may reference
        # the mapped LINES' own aggregate facts (`lines.open_count`, …) - so
        # the line pass must complete FIRST and its aggregates be computed
        # BEFORE the header row is evaluated. Reordered from the original
        # header-then-lines pass (a pure internals change - the header ref
        # composition below is unaffected, since `doc_key`/`source_ref`
        # already resolved above from identity, never from header mapping).
        lines: List[CanonicalLine] = []
        details: List[Any] = []
        if self.detail_key is not None:
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
                fields=self._line_fields,
                errors=errors,
                doc_key=doc_key,
                doc_no=doc_no,
                line_no=index,
                field_types=self._line_field_types,
            )
            values.setdefault("line_no", index)
            values["extras"] = extras
            #     !!  LINE REF COMPOSITION - DOCUMENTS ONLY (plan 22 S5).  !!
            # The mapped ``source_ref`` above is the bare line key (DtlKey);
            # here it becomes ``{header_source_ref}:{line_key}`` (Appendix A6)
            # - composed AFTER mapping (the header's own ref is not known
            # until identity resolves above) and ONLY when the profile opts in
            # (``line_ref_prefix`` - a GRN line's ref stays untouched, S1
            # regression pin). A blank/missing line key is left alone; the
            # canonical line model's own validation names it if required.
            if self.profile.line_ref_prefix and doc_key and values.get("source_ref"):
                values["source_ref"] = f"{doc_key}:{values['source_ref']}"
            #     !!  LINE LINKAGE MINTING (sprint-5/06, AC-06-05..09).  !!
            # Same spot as the ref composition above: AFTER `_apply`
            # (mapped input values are ready), BEFORE the canonical line
            # model is constructed. `values` only ever carries a
            # `from_*_doc_key`/`from_*_line_key`/`from_so_external_*` entry
            # when the profile's OWN line model declares that field
            # (`_apply` only writes a canonical target that is `in fields`)
            # - so this is a correct no-op for `sales_order`, whose line
            # model declares none of them, with no entity-type branch
            # needed here. The ref format is the SAME `{database}:{DocKey}
            # :{DtlKey}` scheme the line's own `source_ref` just got above.
            so_doc_key = values.get("from_so_doc_key")
            so_line_key = values.get("from_so_line_key")
            if so_doc_key is not None and so_line_key is not None:
                values["from_so_line_ref"] = f"{self.database_name}:{so_doc_key}:{so_line_key}"
            po_doc_key = values.get("from_po_doc_key")
            po_line_key = values.get("from_po_line_key")
            if po_doc_key is not None and po_line_key is not None:
                values["from_po_line_ref"] = f"{self.database_name}:{po_doc_key}:{po_line_key}"
            ext_db = values.get("from_so_external_db")
            if ext_db is not None:
                # A key that does not resolve in THIS book never sits in a
                # same-book ref field (D6) - the object is minted ONLY when
                # `db` itself is set, even if the other three are.
                values["from_so_external"] = {
                    "db": ext_db,
                    "doc_key": values.get("from_so_external_doc_key"),
                    "doc_no": values.get("from_so_external_doc_no"),
                    "dtl_key": values.get("from_so_external_line_key"),
                }
            try:
                lines.append(self.profile.line_model(**values))
            except Exception as exc:  # noqa: BLE001 - a model reject is a field error
                # Same guard as the header below, and for the same reason: a
                # mapping row is OPERATOR-EDITABLE DATA, so a row can hand the
                # model a value pydantic rejects (``qty`` mapped ``string``, a
                # UOM landing in a Decimal field). Unguarded, that ValidationError
                # escapes map_document → _stage_documents → run_autocount_sync
                # and kills the WHOLE batch, losing every sibling GRN - exactly
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

        header, header_extras = self._apply(
            self.header_rows,
            raw,
            fields=self._record_fields,
            errors=errors,
            doc_key=doc_key,
            doc_no=doc_no,
            line_no=None,
            field_types=self._record_field_types,
            facts=self._header_facts(raw, lines),
        )

        if errors:
            # All-or-nothing per document (D13/AC-13-10): no partial record.
            return MappedDocument(record=None, errors=errors, raw=raw, doc_no=doc_no)

        # Identity is minted into the CANONICAL SHAPE (D2/AC-14-10) - never at
        # push time - so the staged record, its diff and the pushed record all
        # key on one string.
        header["source_ref"] = source_ref
        header["entity_type"] = self.entity_type
        header["extras"] = header_extras
        if self.profile.line_model is not None:
            header["lines"] = lines
        try:
            record = self.profile.record_model(**header)
        except Exception as exc:  # noqa: BLE001 - a model reject is a field error
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
                doc_no=doc_no,
            )
        return MappedDocument(record=record, errors=[], raw=raw, doc_no=doc_no)

    def map_batch(self, records: Sequence[Dict[str, Any]]) -> List[MappedDocument]:
        """Map many. Each document stands alone - one failure never contaminates
        a sibling (AC-13-10)."""
        return [self.map_document(raw) for raw in records]

    # ── whole-mapping SIMULATION (slice 16, AC-16-30) ─────────────────────────

    def project_document(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Run the REAL mapping over a mock record and return a LEGIBLE
        per-field projection PLUS the authoritative all-or-nothing verdict.

        Unlike ``map_document`` (which discards partial values when any field
        fails), this evaluates each row INDEPENDENTLY so the operator sees every
        field's value or its error side-by-side (record-in → record-out,
        AC-16-30/31). It WRITES NOTHING - pure preview.
        """
        doc_no = t_string(read_path(raw, self.profile.display_path))
        try:
            source_ref: Optional[str] = self.profile.identity(raw, self.database_name)
        except IdentityError:
            source_ref = None

        line_projections: List[List[Dict[str, Any]]] = []
        if self.detail_key is not None:
            details = raw.get(self.detail_key)
            if isinstance(details, list):
                for detail in details:
                    if isinstance(detail, dict):
                        line_projections.append(
                            self._project_rows(
                                self.line_rows, detail, self._line_fields,
                                self._line_field_types, SCOPE_LINE,
                            )
                        )

        # The authoritative verdict (the exact record a real sync would push,
        # or None + the per-field errors it would reject on) - computed BEFORE
        # the header projection (sprint-5/02) so a header formula referencing
        # `lines.*` (AC-02-07) sees the SAME aggregate facts the real sync
        # would compute. When the document as a whole fails (any line error),
        # `mapped.record` is None and the header projection falls back to no
        # facts - a broken record's preview degrading gracefully, never a 500.
        mapped = self.map_document(raw)
        mapped_lines = (
            mapped.record.lines
            if mapped.record is not None and self.profile.line_model is not None
            else []
        )
        header_facts = self._header_facts(raw, mapped_lines)
        header_fields = self._project_rows(
            self.header_rows, raw, self._record_fields, self._record_field_types,
            SCOPE_HEADER, facts=header_facts,
        )
        record_payload: Optional[Dict[str, Any]] = None
        if mapped.record is not None:
            sink_payload = getattr(mapped.record, "sink_payload", None)
            record_payload = sink_payload() if callable(sink_payload) else mapped.record.comparable()

        return {
            "ok": mapped.ok,
            "sourceRef": source_ref or "",
            "docNo": doc_no,
            "record": record_payload,
            "headerFields": header_fields,
            "lineFields": line_projections,
            "errors": [e.as_dict() for e in mapped.errors],
        }

    def _project_rows(
        self,
        rows: Sequence[MappingRow],
        source: Dict[str, Any],
        fields: set,
        field_types: Dict[str, Optional[str]],
        scope: str,
        facts: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        types = field_types or {}
        for row in rows:
            raw_value = resolve_path(source, row.source_path)
            present = raw_value is not _MISSING
            entry: Dict[str, Any] = {
                "scope": scope,
                "sourcePath": row.source_path,
                "canonicalField": row.canonical_field,
                "present": present,
                "ok": True,
                "value": None,
                "error": None,
            }
            if not present:
                if row.is_required:
                    entry["ok"] = False
                    entry["error"] = "required by its mapping row but absent"
                out.append(entry)
                continue
            try:
                coerced = row.coerce(raw_value, self._transforms, facts)
                if row.formula and row.canonical_field in fields:
                    coerced = coerce_output(coerced, types.get(row.canonical_field))
            except TransformError as exc:
                entry["ok"] = False
                entry["error"] = str(exc)
                out.append(entry)
                continue
            if coerced is None and row.is_required:
                entry["ok"] = False
                entry["error"] = "required by its mapping row but the value was empty"
                out.append(entry)
                continue
            entry["value"] = _json_safe(coerced)
            out.append(entry)
        return out

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
        field_types: Optional[Dict[str, Optional[str]]] = None,
        facts: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        values: Dict[str, Any] = {}
        extras: Dict[str, Any] = {}
        types = field_types or {}
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
                coerced = row.coerce(raw_value, self._transforms, facts)
                # A FORMULA row's output is coerced/validated to the target
                # field's declared type (AC-16-04). Named-transform rows already
                # return the right type, so they skip this. Extras (undeclared
                # target) have no declared type - the raw value is kept.
                if row.formula and row.canonical_field in fields:
                    coerced = coerce_output(coerced, types.get(row.canonical_field))
            except TransformError as exc:
                # NAMED per-field error - never a silent null (AC-13-09/16-03).
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
# Casing here is LITERAL vendor casing (GRN's ``DtlKey`` - DO's is ``Dtlkey``).

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
    # lines - GRN detail casing is ``DtlKey`` (DO's is ``Dtlkey``; map literally)
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

# ── default MASTER mappings (SEED DATA, AC-14-05) ─────────────────────────────
#
# Masters are FLAT - one scope, no detail array - but they nest their real DB row
# under ``Data[0]``, so paths address BOTH levels explicitly (see ``resolve_path``
# for why this is not flattened).
#
# ``source_ref`` is NOT a mapping row: it is minted by the profile's identity
# function (``company_qualified_identity``), exactly as GRN's DocKey is. An
# operator can remap a field; they must not be able to remap identity.
#
#     !!  NO PAYMENT-TERMS ROW EXISTS HERE, AND ADDING ONE WOULD BE A BUG.  !!
# ``payment_terms_code`` is an UNCONDITIONAL permanent-``retryable`` in the
# consumer (it performs no lookup until their Phase D), so any value would build
# a queue that can never drain. AutoCount's ``DisplayTerm`` is a code
# (``"C.O.D."``), not a number of days, so ``payment_terms_days`` cannot be
# derived either. Absent by decision, not by oversight (AC-14-12).

_MASTER_COMMON: Tuple[MappingRow, ...] = (
    MappingRow("AccNo", "code", "string", SCOPE_HEADER, is_required=True),
    MappingRow("CompanyName", "name", "string", SCOPE_HEADER, is_required=True),
    MappingRow("EmailAddress", "email", "string", SCOPE_HEADER),
    # STRICT "T"/"F" + REQUIRED, together. The transform refuses to guess and the
    # required flag refuses a blank - so an unreadable active flag fails THAT
    # record with the field named, and never falls through to the consumer's
    # ``is_active: bool = True`` default. A silently-activated blacklisted
    # supplier, or a silently-deactivated live one, is the failure this pair
    # exists to make impossible (AC-14-05).
    MappingRow("IsActive", "is_active", "t_f_bool", SCOPE_HEADER, is_required=True),
    # Human-facing account number. DISPLAY only - mutable at source, which is
    # precisely why identity is AutoKey and not this (AC-14-11).
    MappingRow("AccNo", "source_doc_no", "string", SCOPE_HEADER),
    # Lives in the NESTED row, not at the top level (AC-14-02). Drives the
    # watermark, so a wrong path here silently disables delta forever.
    MappingRow(
        VENDOR_LAST_MODIFIED_PATH, "last_modified", "slash_datetime", SCOPE_HEADER
    ),
)

# Creditor → Sorento suppliers. Code, name, email, active flag ONLY - Creditor
# has no phone field, and the seven address fields Sorento accepts are ones it
# never persists, so sending them would let us report a sync that did not happen
# (AC-14-13).
DEFAULT_SUPPLIER_MAPPING: Tuple[MappingRow, ...] = _MASTER_COMMON

# Debtor → Sorento customers. Same core plus the two fields Debtor actually
# carries and Sorento actually writes (CreditLimit left with Sorento contract 2.1 -
# `credit_limit` is no longer a sink field, see canonical/masters.py).
DEFAULT_CUSTOMER_MAPPING: Tuple[MappingRow, ...] = _MASTER_COMMON + (
    MappingRow("Mobile", "phone_number", "string", SCOPE_HEADER),
    MappingRow("TIN", "tax_id", "string", SCOPE_HEADER),
)

DEFAULT_MAPPINGS: Dict[str, Tuple[MappingRow, ...]] = {
    ENTITY_GOODS_RECEIVED_NOTE: DEFAULT_GRN_MAPPING,
    ENTITY_SUPPLIER: DEFAULT_SUPPLIER_MAPPING,
    ENTITY_CUSTOMER: DEFAULT_CUSTOMER_MAPPING,
}


# ── document LINE mapping is now FIRST-CLASS, operator-editable, PERSISTED
# data (sprint-5/02, AC-02-01..05) ───────────────────────────────────────────
#
# The FIXED column-name convention this section used to hold
# (`document_line_rows`, `DOCUMENT_LINE_FIXED_FIELDS`, `DOCUMENT_LINE_REF_
# COLUMNS`) is GONE: a document's line fields are `ac_field_mapping` rows
# exactly like its header fields, `scope='line'` (`mapping_catalog.
# SORENTO_LINE_FIELDS` is the accepted-target catalog; `LINE_FIELD_REF_
# TRANSFORMS` above is the ref-pairing guard). The migration that converts a
# pre-existing task's `lineKeyColumn`/`lineProductColumn`/`lineWarehouseColumn`
# pickers into three persisted rows lives in `backfill.py`
# (`backfill_document_line_mapping_pickers`, AC-02-05).


def build_mapping_rows_for_run(
    entity_type: str,
    rows: Sequence[MappingRow],
    *,
    is_sql_db_source: bool,
    source_config: Optional[Dict[str, Any]],
) -> List[MappingRow]:
    """The FULL engine row set for one extract/preview/push.

    Pre-sprint-5/02 this ALSO code-generated a document's line rows from three
    `source_config` picker columns (`document_line_rows`) - line rows are now
    operator-persisted data, already included in ``rows`` (whatever
    ``CompanyService.mapping_rows`` returns, header AND line scope alike), so
    this is now a thin pass-through. Kept as ONE function (not inlined at each
    call site) so ``sync.py``'s real run and ``etl_service.py``'s activation-
    gate preview stay wired through the SAME seam - the anti-drift reason this
    function existed in the first place, and the reason a future addition
    (e.g. a filter-formula gate) belongs here too, once needed.

    ``entity_type``/``is_sql_db_source``/``source_config`` are UNUSED now
    (review nit) - the code-generation era's own inputs, left on the
    signature deliberately rather than removed: both call sites AND the
    engine-composition tests (``test_autocount_document_mapping.py``) already
    pass them, and this seam is exactly the kind of place a FUTURE
    per-run gate (a filter-formula check, say) would need them again - a
    churn-for-churn's-sake signature change here buys nothing.
    """
    return list(rows)
