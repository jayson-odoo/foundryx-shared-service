"""Per-type cell coercion (sprint-3/09 D6) - server-authoritative.

Each coercer returns ``(value, error)``: a parsed value or an error message with
the expected format. Empty-after-trim = None (absent). Dates = strict ISO-8601
for strings (ambiguous DD-MM rejected) / Excel typed-date used directly; naive
datetimes are interpreted in the importing user's tz → UTC by the service.
"""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Tuple

Result = Tuple[Any, Optional[str]]

_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def coerce_string(value: Any) -> Result:
    if _empty(value):
        return None, None
    return (str(value).strip(), None)


def coerce_integer(value: Any) -> Result:
    if _empty(value):
        return None, None
    if isinstance(value, bool):
        return None, "expected an integer"
    if isinstance(value, int):
        return value, None
    s = str(value).strip()
    try:
        # Reject decimals (1.5) and sci-notation for integers.
        if isinstance(value, float):
            if value != int(value):
                return None, "expected a whole number"
            return int(value), None
        return int(s), None
    except (ValueError, TypeError):
        return None, "expected a whole number"


def coerce_decimal(value: Any, decimals: Optional[int]) -> Result:
    if _empty(value):
        return None, None
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None, "expected a number"
    if decimals is not None:
        # Decimal-exponent check (never a .split('.') digit count - sci-notation
        # would slip past; house rule, plan sprint-3/01 review).
        exp = d.as_tuple().exponent
        places = -exp if isinstance(exp, int) and exp < 0 else 0
        if places > decimals:
            return None, f"at most {decimals} decimal place(s)"
    return d, None


def coerce_boolean(value: Any) -> Result:
    if _empty(value):
        return None, None
    if isinstance(value, bool):
        return value, None
    s = str(value).strip().lower()
    if s in _TRUE:
        return True, None
    if s in _FALSE:
        return False, None
    return None, "expected yes/no, true/false, or 1/0"


def coerce_date(value: Any) -> Result:
    if _empty(value):
        return None, None
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    s = str(value).strip()
    try:
        return date.fromisoformat(s), None
    except ValueError:
        return None, "expected a date (YYYY-MM-DD)"


def coerce_datetime(value: Any) -> Result:
    """Returns a datetime that is naive (caller stamps the assumed tz) or aware
    (offset respected). The service converts naive → user tz → UTC (D6)."""
    if _empty(value):
        return None, None
    if isinstance(value, datetime):
        return value, None
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day), None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s), None
    except ValueError:
        return None, "expected an ISO-8601 datetime"


def to_utc(dt: datetime, assumed_tz) -> datetime:
    """Naive → interpret in assumed_tz → UTC; aware → convert to UTC."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    if assumed_tz is not None:
        return dt.replace(tzinfo=assumed_tz).astimezone(timezone.utc)
    return dt.replace(tzinfo=timezone.utc)


def coerce_enum(value: Any, options) -> Result:
    """Trim + case-insensitive match → canonical option value."""
    if _empty(value):
        return None, None
    s = str(value).strip().lower()
    for opt in options or []:
        canonical = opt["value"] if isinstance(opt, dict) else opt
        if str(canonical).strip().lower() == s:
            return canonical, None
    allowed = ", ".join(
        str(o["value"] if isinstance(o, dict) else o) for o in (options or [])
    )
    return None, f"must be one of: {allowed}"


def coerce(value: Any, col) -> Result:
    """Dispatch on the column type. Applies transform first."""
    if col.transform and not _empty(value):
        try:
            value = col.transform(value)
        except Exception:  # noqa: BLE001
            return None, "could not normalize value"
    t = col.type
    if t == "integer":
        return coerce_integer(value)
    if t == "decimal":
        return coerce_decimal(value, col.decimals)
    if t == "boolean":
        return coerce_boolean(value)
    if t == "date":
        return coerce_date(value)
    if t == "datetime":
        return coerce_datetime(value)
    if t == "enum":
        return coerce_enum(value, _materialize_options(col.options))
    return coerce_string(value)


def _materialize_options(options) -> list:
    return options if isinstance(options, list) else []
