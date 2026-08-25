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
    ENTITY_SUPPLIER,
    VENDOR_AUTOKEY_PATH,
    VENDOR_LAST_MODIFIED_PATH,
    CanonicalCustomer,
    CanonicalSupplier,
)

SCOPE_HEADER = "header"
SCOPE_LINE = "line"
SCOPES = (SCOPE_HEADER, SCOPE_LINE)


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

    def coerce(self, value: Any) -> Any:
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
                return evaluate_formula(self.formula, value)
            except FormulaError as exc:
                # A runtime formula fault becomes a NAMED per-field error via the
                # engine's existing ``except TransformError`` path (AC-16-03).
                raise TransformError(str(exc)) from exc
        fn = TRANSFORMS.get(self.transform)
        if fn is None:
            raise TransformError(f"unknown transform '{self.transform}'")
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

ENTITY_PROFILES: Dict[str, EntityProfile] = {
    GRN_PROFILE.entity_type: GRN_PROFILE,
    SUPPLIER_PROFILE.entity_type: SUPPLIER_PROFILE,
    CUSTOMER_PROFILE.entity_type: CUSTOMER_PROFILE,
}


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
        # ``source_ref`` from it (AC-14-10); documents ignore it.
        self.database_name = database_name
        self._record_fields = self.profile.record_fields()
        self._line_fields = self.profile.line_fields()
        # Declared field types, for coercing a FORMULA row's output (AC-16-04).
        self._record_field_types = _field_type_tokens(self.profile.record_model)
        self._line_field_types = _field_type_tokens(self.profile.line_model)

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

        header, header_extras = self._apply(
            self.header_rows,
            raw,
            fields=self._record_fields,
            errors=errors,
            doc_key=doc_key,
            doc_no=doc_no,
            line_no=None,
            field_types=self._record_field_types,
        )

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

        header_fields = self._project_rows(
            self.header_rows, raw, self._record_fields, self._record_field_types,
            SCOPE_HEADER,
        )
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
        # or None + the per-field errors it would reject on).
        mapped = self.map_document(raw)
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
                coerced = row.coerce(raw_value)
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
                coerced = row.coerce(raw_value)
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

# Debtor → Sorento customers. Same core plus the three fields Debtor actually
# carries and Sorento actually writes.
DEFAULT_CUSTOMER_MAPPING: Tuple[MappingRow, ...] = _MASTER_COMMON + (
    MappingRow("Mobile", "phone_number", "string", SCOPE_HEADER),
    MappingRow("CreditLimit", "credit_limit", "decimal", SCOPE_HEADER),
    MappingRow("TIN", "tax_id", "string", SCOPE_HEADER),
)

DEFAULT_MAPPINGS: Dict[str, Tuple[MappingRow, ...]] = {
    ENTITY_GOODS_RECEIVED_NOTE: DEFAULT_GRN_MAPPING,
    ENTITY_SUPPLIER: DEFAULT_SUPPLIER_MAPPING,
    ENTITY_CUSTOMER: DEFAULT_CUSTOMER_MAPPING,
}
