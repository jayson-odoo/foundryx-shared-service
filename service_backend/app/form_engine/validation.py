"""Form submission validation pipeline (plan sprint-3/01 D14) — the SERVER
boundary. ``validate_submission`` is the authoritative twin of the client mirror
(``lib/form-validate.ts``): it re-derives the visible set, drops hidden answers,
applies required-if-visible, runs per-type constraints, recomputes computed
fields, and returns ``(clean_answers, errors)`` — the per-field error map being
the 422 contract.

Never trust the client (D14): options-membership, type, regex and computed values
are ALL re-validated/re-derived here.

Pure functions — no DB/ORM imports. Visibility evaluates the rule-engine trees
against ``{'answers.<key>': value}`` facts via ``evaluate`` (fail-closed, so a
stale/garbage condition simply hides the field). Hidden field answers are
silently DROPPED (never stored, never an error); ``required`` therefore applies
ONLY when visible. Computed fields are recomputed server-side and the CLIENT
value is IGNORED.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from app.form_engine.computed import evaluate as compute_eval
from app.form_engine.schemas import (
    INPUT_FIELD_TYPES,
    FormDocument,
    FormField,
    FormSubField,
)
from app.rule_engine.evaluator import evaluate as rule_eval

# Pragmatic email shape — matches the client (deliverability never asserted).
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
# Permissive phone — digits/space/+-() , 7..20 chars.
_PHONE_RE = re.compile(r"^[0-9+\-()\s]{7,20}$")

# Address composite — whitelist of allowed sub-keys (D14).
_ADDRESS_KEYS = ("line1", "line2", "city", "state", "postcode", "country")
_ADDRESS_REQUIRED = ("line1", "city", "country")

_REQUIRED_MSG = "This field is required."


# ---- public entry ----


def validate_submission(
    doc: "FormDocument | Dict[str, Any]", answers: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Validate a raw answer map against the form doc.

    Returns ``(clean_answers, errors)``:
    - ``clean_answers`` — the stored payload: visible answers only, hidden
      dropped, unknown keys dropped, computed fields recomputed.
    - ``errors`` — per-field ``{fieldKey: message}`` (repeater rows keyed
      ``<key>.<rowIndex>.<subKey>``). Empty ⇒ valid.
    """
    form = doc if isinstance(doc, FormDocument) else FormDocument.model_validate(doc)
    answers = answers or {}

    clean: Dict[str, Any] = {}
    errors: Dict[str, str] = {}

    # Conditions evaluate against the VISIBLE set accumulated so far, NOT the
    # raw client map (D14): conditions reference earlier fields only (publish
    # gate), and we walk in document order, so a hidden upstream field
    # contributes no fact — its leaf fails closed. This means curl can't
    # force-feed a hidden field's value to flip a downstream field's
    # visibility (the hidden value is dropped from both storage AND facts).
    def _facts() -> Dict[str, Any]:
        return {f"answers.{k}": v for k, v in clean.items()}

    for page in form.pages:
        for section in page.sections:
            if not rule_eval(section.conditions_json, _facts()):
                continue  # whole section hidden — every field within drops
            for field in section.fields:
                if field.type not in INPUT_FIELD_TYPES or not field.key:
                    continue  # display field (no answer) / keyless
                if not rule_eval(field.conditions_json, _facts()):
                    continue  # field hidden — drop its answer, never an error

                if field.type == "computed":
                    # Server RECOMPUTES; the client value is ignored entirely.
                    clean[field.key] = _recompute(field, clean)
                    continue

                value = answers.get(field.key)
                error = _validate_field(field, value, errors)
                if error:
                    errors[field.key] = error
                # Store the answer (present or not) so a visible-but-empty
                # optional field round-trips as the user left it.
                if field.key in answers:
                    clean[field.key] = _clean_value(field, value)

    return clean, errors


# ---- per-field validation ----


def _validate_field(
    field: FormField, value: Any, errors: Dict[str, str]
) -> Optional[str]:
    """Return an error string for *value* against *field*, or None. Composite
    types (repeater) write row-keyed errors into *errors* directly and return
    None (their own message, if any, is set by the helper)."""
    ftype = field.type

    if ftype == "address":
        return _validate_address(field, value)
    if ftype == "repeater":
        return _validate_repeater(field, value, errors)
    if ftype == "table":
        return _validate_table(field, value, errors)
    if ftype == "file":
        return _validate_file(field, value)

    if _is_empty(value):
        return _REQUIRED_MSG if field.required else None

    if ftype in ("text", "textarea"):
        return _validate_text(field, str(value))
    if ftype == "email":
        if not _EMAIL_RE.match(str(value)):
            return "Enter a valid email address."
        return _validate_text(field, str(value))
    if ftype == "url":
        if not _is_url(str(value)):
            return "Enter a valid URL."
        return _validate_text(field, str(value))
    if ftype == "phone":
        if not _PHONE_RE.match(str(value)):
            return "Enter a valid phone number."
        return _validate_text(field, str(value))
    if ftype in ("number", "integer"):
        return _validate_number(field, value)
    if ftype in ("select", "radio"):
        return _validate_choice(field, [str(value)])
    if ftype in ("multiselect", "checkboxes"):
        return _validate_multi_choice(field, value)
    if ftype == "yesno":
        if not isinstance(value, bool):
            return "Choose an option."
        return None
    if ftype == "date":
        if not _is_date(str(value)):
            return "Enter a valid date."
        return None
    if ftype == "datetime":
        if not _is_datetime(str(value)):
            return "Enter a valid date and time."
        return None
    if ftype == "rating":
        return _validate_rating(field, value)
    if ftype == "signature":
        # Presence checked above; a non-empty value is an opaque data-URL /
        # storage-key string — accept any non-empty str.
        if not isinstance(value, str) or not value.strip():
            return _REQUIRED_MSG if field.required else None
        return None
    return None


def _validate_text(field: FormField, value: str) -> Optional[str]:
    cfg = field.text
    if cfg is None:
        return None
    if cfg.min_length is not None and len(value) < cfg.min_length:
        return f"Enter at least {cfg.min_length} characters."
    if cfg.max_length is not None and len(value) > cfg.max_length:
        return f"Enter at most {cfg.max_length} characters."
    if cfg.pattern:
        try:
            compiled = re.compile(cfg.pattern)
        except re.error:
            compiled = None  # invalid author pattern → fail open (publish gate)
        # JS `.test()` semantics = search (not fullmatch) — mirror the client.
        if compiled is not None and not compiled.search(value):
            return (cfg.pattern_message or "").strip() or (
                "This value is not in the expected format."
            )
    return None


def _decimal_places(value: Any) -> int:
    """Count decimal digits in *value*, robust to scientific notation (1e-7 → 7)
    via Decimal's exponent."""
    from decimal import Decimal, InvalidOperation

    try:
        exponent = Decimal(str(value).strip()).as_tuple().exponent
    except (InvalidOperation, ValueError):
        return 0
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _number_kind_error(value: Any, num: float, *, integer: Optional[bool], decimals: Optional[int]) -> Optional[str]:
    """Integer/decimal-places enforcement (sprint-3/02 follow-up)."""
    if integer:
        return None if num == int(num) else "Enter a whole number."
    if decimals is not None and _decimal_places(value) > decimals:
        return f"Enter at most {decimals} decimal place{'' if decimals == 1 else 's'}."
    return None


def _validate_number(field: FormField, value: Any) -> Optional[str]:
    num = _to_number(value)
    if num is None:
        return "Enter a valid number."
    cfg = field.number
    # `integer` field type OR the legacy number.integer flag → whole numbers.
    is_integer = field.type == "integer" or bool(cfg and cfg.integer)
    decimals = cfg.decimals if cfg else None
    kind_error = _number_kind_error(value, num, integer=is_integer, decimals=decimals)
    if kind_error:
        return kind_error
    if cfg is None:
        return None
    if cfg.min is not None and num < cfg.min:
        return f"Enter a value of at least {cfg.min}."
    if cfg.max is not None and num > cfg.max:
        return f"Enter a value of at most {cfg.max}."
    if cfg.step is not None and cfg.step > 0:
        base = cfg.min if cfg.min is not None else 0
        steps = (num - base) / cfg.step
        if abs(steps - round(steps)) > 1e-9:
            return f"Enter a value in steps of {cfg.step}."
    return None


def _validate_choice(field: FormField, values: List[str]) -> Optional[str]:
    allowed = _option_values(field)
    if any(v not in allowed for v in values):
        return "Choose a valid option."
    return None


def _validate_multi_choice(field: FormField, value: Any) -> Optional[str]:
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        return "Choose a valid option."
    if len(set(value)) != len(value):
        return "Duplicate selection."
    return _validate_choice(field, value)


def _validate_rating(field: FormField, value: Any) -> Optional[str]:
    num = _to_number(value)
    max_v = field.rating.max if field.rating else 5
    if num is None or num != int(num) or int(num) < 1 or int(num) > max_v:
        return "Choose a rating."
    return None


def _validate_address(field: FormField, value: Any) -> Optional[str]:
    if not isinstance(value, dict):
        return _REQUIRED_MSG if field.required else None
    # Only whitelisted keys exist post-clean; presence drives the required check.
    present = any(
        isinstance(value.get(k), str) and value[k].strip()
        for k in ("line1", "city", "country")
    )
    if not present:
        return _REQUIRED_MSG if field.required else None
    for k in _ADDRESS_REQUIRED:
        if not (isinstance(value.get(k), str) and value[k].strip()):
            return {
                "line1": "Address line 1 is required.",
                "city": "City is required.",
                "country": "Country is required.",
            }[k]
    return None


def _validate_file(field: FormField, value: Any) -> Optional[str]:
    files = value if isinstance(value, list) else []
    files = [f for f in files if _is_file_shape(f)]
    if not files:
        return _REQUIRED_MSG if field.required else None
    max_count = field.file.max_count if field.file else None
    if max_count is not None and len(files) > max_count:
        return f"Attach at most {max_count} file{'' if max_count == 1 else 's'}."
    # Per-file size/mime re-checks happen at upload time (service layer); here
    # we only shape-check + enforce count.
    return None


def _validate_repeater(
    field: FormField, value: Any, errors: Dict[str, str]
) -> Optional[str]:
    rows = value if isinstance(value, list) else []
    real_rows = [r for r in rows if isinstance(r, dict)]
    cfg = field.repeater
    lo = cfg.min_rows if cfg else None
    hi = cfg.max_rows if cfg else None
    key = field.key or ""

    if not real_rows:
        if field.required or (lo is not None and lo > 0):
            if lo is not None and lo > 0:
                return f"Add at least {lo} item{'' if lo == 1 else 's'}."
            return _REQUIRED_MSG
        return None

    bound_error: Optional[str] = None
    if lo is not None and len(real_rows) < lo:
        bound_error = f"Add at least {lo} item{'' if lo == 1 else 's'}."
    elif hi is not None and len(real_rows) > hi:
        bound_error = f"Add at most {hi} item{'' if hi == 1 else 's'}."

    subs = cfg.fields if cfg else []
    for row_index, row in enumerate(real_rows):
        for sub in subs:
            sub_error = _validate_sub_field(sub, row.get(sub.key))
            if sub_error:
                errors[f"{key}.{row_index}.{sub.key}"] = sub_error

    return bound_error


def _validate_table(field: FormField, value: Any, errors: Dict[str, str]) -> Optional[str]:
    """Validate Table rows. Computed columns are NOT validated (derived, read-
    only — recomputed in _clean_value). Per-cell errors keyed key.rowIndex.col."""
    rows = [r for r in (value if isinstance(value, list) else []) if isinstance(r, dict)]
    cfg = field.table
    cols = cfg.columns if cfg else []
    lo = cfg.min_rows if cfg else None
    hi = cfg.max_rows if cfg else None
    key = field.key or ""

    if not rows:
        if field.required or (lo is not None and lo > 0):
            if lo is not None and lo > 0:
                return f"Add at least {lo} item{'' if lo == 1 else 's'}."
            return _REQUIRED_MSG
        return None

    bound_error: Optional[str] = None
    if lo is not None and len(rows) < lo:
        bound_error = f"Add at least {lo} item{'' if lo == 1 else 's'}."
    elif hi is not None and len(rows) > hi:
        bound_error = f"Add at most {hi} item{'' if hi == 1 else 's'}."

    for row_index, row in enumerate(rows):
        for col in cols:
            if col.type in ("computed", "fixed"):
                continue  # derived / server-stamped — not user input
            cell_error = _validate_table_cell(col, row.get(col.key))
            if cell_error:
                errors[f"{key}.{row_index}.{col.key}"] = cell_error

    return bound_error


def _validate_table_cell(col: Any, value: Any) -> Optional[str]:
    if _is_empty(value):
        return _REQUIRED_MSG if col.required else None
    ctype = col.type
    s = str(value)
    if ctype in ("number", "integer"):
        num = _to_number(value)
        if num is None:
            return "Enter a valid number."
        is_integer = ctype == "integer" or bool(col.integer)
        kind_error = _number_kind_error(value, num, integer=is_integer, decimals=col.decimals)
        if kind_error:
            return kind_error
        cfg = col.number
        if cfg and cfg.min is not None and num < cfg.min:
            return f"Enter a value of at least {cfg.min}."
        if cfg and cfg.max is not None and num > cfg.max:
            return f"Enter a value of at most {cfg.max}."
        return None
    if ctype == "date":
        return None if _is_date(s) else "Enter a valid date."
    if ctype == "select":
        allowed = {item.value for item in (col.options.items if col.options else [])}
        return None if s in allowed else "Choose a valid option."
    return None  # text


def _validate_sub_field(sub: FormSubField, value: Any) -> Optional[str]:
    if _is_empty(value):
        return _REQUIRED_MSG if sub.required else None
    stype = sub.type
    s = str(value)
    if stype in ("text", "textarea"):
        cfg = sub.text
        if cfg and cfg.min_length is not None and len(s) < cfg.min_length:
            return f"Enter at least {cfg.min_length} characters."
        if cfg and cfg.max_length is not None and len(s) > cfg.max_length:
            return f"Enter at most {cfg.max_length} characters."
        return None
    if stype == "email":
        return None if _EMAIL_RE.match(s) else "Enter a valid email address."
    if stype == "url":
        return None if _is_url(s) else "Enter a valid URL."
    if stype == "phone":
        return None if _PHONE_RE.match(s) else "Enter a valid phone number."
    if stype == "number":
        num = _to_number(value)
        if num is None:
            return "Enter a valid number."
        cfg = sub.number
        if cfg and cfg.min is not None and num < cfg.min:
            return f"Enter a value of at least {cfg.min}."
        if cfg and cfg.max is not None and num > cfg.max:
            return f"Enter a value of at most {cfg.max}."
        return None
    if stype == "date":
        return None if _is_date(s) else "Enter a valid date."
    if stype == "rating":
        num = _to_number(value)
        max_v = sub.rating.max if sub.rating else 5
        if num is None or num != int(num) or int(num) < 1 or int(num) > max_v:
            return "Choose a rating."
        return None
    if stype in ("select", "radio"):
        allowed = {item.value for item in (sub.options.items if sub.options else [])}
        return None if s in allowed else "Choose a valid option."
    if stype == "yesno":
        return None if isinstance(value, bool) else "Choose an option."
    return None


# ---- clean-value coercion (what gets STORED) ----


def _recompute(field: FormField, clean: Dict[str, Any]) -> Optional[float]:
    """Recompute a computed field against the already-cleaned numeric answers
    (visible only — clean holds only visible upstream values). Fail-closed."""
    expr = (field.computed.expression or "").strip() if field.computed else ""
    if not expr:
        return None
    result = compute_eval(expr, clean)
    # Even finite inputs can overflow to inf (huge * huge) — inf/nan serialize
    # as invalid JSON, so fail closed to None (code-review finding).
    if result is None or not math.isfinite(result):
        return None
    return result


def _clean_value(field: FormField, value: Any) -> Any:
    """Normalize the stored answer. Repeaters drop undeclared sub-keys; address
    drops keys outside the whitelist. Other types store as-given."""
    if field.type == "address" and isinstance(value, dict):
        return {k: value[k] for k in _ADDRESS_KEYS if k in value}
    if field.type == "repeater" and isinstance(value, list):
        sub_keys = {s.key for s in (field.repeater.fields if field.repeater else [])}
        cleaned_rows = []
        for row in value:
            if isinstance(row, dict):
                cleaned_rows.append({k: v for k, v in row.items() if k in sub_keys})
        return cleaned_rows
    if field.type == "table" and isinstance(value, list):
        # Drop undeclared keys; STAMP fixed columns + RECOMPUTE computed columns
        # server-side per row (client values for those are never trusted). Walk
        # columns in order so a fixed/computed column is available to a later
        # computed column.
        cols = field.table.columns if field.table else []
        input_keys = {c.key for c in cols if c.type not in ("computed", "fixed")}
        cleaned_rows = []
        for row in value:
            if not isinstance(row, dict):
                continue
            clean_row = {k: v for k, v in row.items() if k in input_keys}
            for col in cols:
                if col.type == "fixed":
                    clean_row[col.key] = col.fixed_value if col.fixed_value is not None else ""
                elif col.type == "computed":
                    expr = (col.computed.expression or "").strip() if col.computed else ""
                    result = compute_eval(expr, clean_row) if expr else None
                    clean_row[col.key] = (
                        result if (result is not None and math.isfinite(result)) else ""
                    )
            cleaned_rows.append(clean_row)
        return cleaned_rows
    if field.type == "file" and isinstance(value, list):
        return [f for f in value if _is_file_shape(f)]
    # Choice answers store the STRING option value — membership accepts a
    # numeric 0 against option "0" (str()-compared), so coerce to match what
    # equality conditions / CSV export / label lookup expect (code-review).
    if field.type in ("select", "radio") and value is not None:
        return str(value)
    if field.type in ("multiselect", "checkboxes") and isinstance(value, list):
        return [str(v) for v in value]
    return value


# ---- primitive predicates / coercion ----


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None  # booleans are not numbers in this domain
    if isinstance(value, (int, float)):
        num = float(value)
    elif isinstance(value, str):
        try:
            num = float(value.strip())
        except (ValueError, OverflowError):
            return None
    else:
        return None
    # Reject inf/-inf/nan: they round-trip as `Infinity`/`NaN` (invalid JSON),
    # which the JSON column rejects on insert (code-review finding).
    return num if math.isfinite(num) else None


def _is_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except (ValueError, AttributeError):
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _is_date(value: str) -> bool:
    """Strict 'YYYY-MM-DD'."""
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value.strip(), "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _is_datetime(value: str) -> bool:
    """ISO-8601 parseable (date-only also accepted — a calendar instant)."""
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = value.strip().replace("Z", "+00:00")
    try:
        datetime.fromisoformat(candidate)
        return True
    except ValueError:
        pass
    try:
        date.fromisoformat(candidate)
        return True
    except ValueError:
        return False


def _option_values(field: FormField) -> set:
    return {item.value for item in (field.options.items if field.options else [])}


def _is_file_shape(f: Any) -> bool:
    return (
        isinstance(f, dict)
        and isinstance(f.get("key"), str)
        and isinstance(f.get("name"), str)
        and "size" in f
        and isinstance(f.get("mime"), str)
    )
