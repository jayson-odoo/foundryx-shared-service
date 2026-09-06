"""Business hours (plan sprint-4/31 S5, D-A5-13/F6/AC-WFP-55/56).

Per-workspace weekly open windows + IANA timezone, stored on
`omnichannel_settings` - the SAME `workspace_id` (per-workspace) / `NULL`
(tenant-wide default) resolution `MediaSettingsService` already uses for
media caps (D-A5-13: two new columns on an existing table, not a new one).

`windows` shape: ``{"mon": [{"from": "09:00", "to": "18:00"}], "tue": [...],
..., "sun": []}``. A window whose ``to`` is lexically <= ``from`` is an
OVERNIGHT window ending the next day - explicitly VALID (§5.4), never a
validation error; ``evaluate`` below implements that by also checking the
PREVIOUS day's overnight windows for a window that started yesterday and
hasn't ended yet. The one case rejected as malformed is ``from == to`` (a
degenerate, ambiguous window - neither a real span nor unambiguously
"overnight") - the decision the plan/UAC left implicit between "overnight
windows are allowed" (§5.4, defined as `to <= from`) and AC-WFP-55's "an end
before a start returns 422" wording.
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..models import OmnichannelSettings

DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class BusinessHoursValidationError(Exception):
    """Carries a `{field: message}` map - the router turns this into a 422
    `{fieldErrors}` body (mirrors `ContactFieldService.FieldValidationError`)."""

    def __init__(self, errors: Dict[str, str]):
        super().__init__("Business hours validation failed")
        self.errors = errors


class MissingBusinessHours(Exception):
    """Neither the workspace nor the tenant default has configured hours - the
    `omnichannel.business_hours` node fails with this rather than guessing
    "always open"/"always closed" (AC-WFP-56)."""


def validate_timezone(value: Any) -> str:
    tz = str(value or "").strip()
    if not tz:
        raise BusinessHoursValidationError({"timezone": "Choose a timezone."})
    try:
        ZoneInfo(tz)
    except Exception as exc:  # noqa: BLE001 - any zoneinfo failure = a bad name
        raise BusinessHoursValidationError(
            {"timezone": f"Unknown timezone: {tz!r} (use an IANA name)."}
        ) from exc
    return tz


def validate_windows(value: Any) -> Dict[str, List[Dict[str, str]]]:
    """Validate + normalize the per-weekday window map. Unknown day keys are
    rejected (foolproof-UI - the editor only ever sends the 7 known keys);
    each window needs exactly `from`/`to` HH:MM (24h) strings. Overnight
    windows (`to` <= `from`, distinct) are VALID; `from == to` is rejected as
    a degenerate window (see module docstring)."""
    if not isinstance(value, dict):
        raise BusinessHoursValidationError(
            {"windows": "Windows must be an object keyed by weekday."}
        )
    errors: Dict[str, str] = {}
    unknown = sorted(k for k in value if k not in DAY_KEYS)
    if unknown:
        errors["windows"] = f"Unknown weekday key(s): {', '.join(unknown)}."
    cleaned: Dict[str, List[Dict[str, str]]] = {day: [] for day in DAY_KEYS}
    for day in DAY_KEYS:
        rows = value.get(day) or []
        if not isinstance(rows, list):
            errors[f"windows.{day}"] = "Must be a list of windows."
            continue
        for idx, row in enumerate(rows):
            field_key = f"windows.{day}.{idx}"
            if not isinstance(row, dict):
                errors[field_key] = "Malformed window."
                continue
            start = str(row.get("from") or "")
            end = str(row.get("to") or "")
            if _TIME_RE.fullmatch(start) is None or _TIME_RE.fullmatch(end) is None:
                errors[field_key] = "Times must be HH:MM (24-hour)."
                continue
            if start == end:
                errors[field_key] = "End time must differ from the start time."
                continue
            cleaned[day].append({"from": start, "to": end})
    if errors:
        raise BusinessHoursValidationError(errors)
    return cleaned


class BusinessHoursService:
    def __init__(self, db: Session):
        self.db = db

    def _row(self, tenant_id: str, workspace_id: Optional[str]) -> Optional[OmnichannelSettings]:
        return (
            self.db.query(OmnichannelSettings)
            .filter(
                OmnichannelSettings.tenant_id == tenant_id,
                OmnichannelSettings.workspace_id == workspace_id,
            )
            .first()
        )

    def get(self, tenant_id: str, workspace_id: str) -> Dict[str, Any]:
        row = self._row(tenant_id, workspace_id)
        return {
            "timezone": row.business_timezone if row else None,
            "windows": (row.business_hours_json if row and row.business_hours_json else {day: [] for day in DAY_KEYS}),
        }

    def set(
        self, tenant_id: str, workspace_id: str, *, timezone: Any, windows: Any
    ) -> Dict[str, Any]:
        """Validate FIRST (nothing written on a 422) then upsert."""
        tz = validate_timezone(timezone)
        clean_windows = validate_windows(windows)
        row = self._row(tenant_id, workspace_id)
        if row is None:
            row = OmnichannelSettings(tenant_id=tenant_id, workspace_id=workspace_id)
            self.db.add(row)
        row.business_timezone = tz
        row.business_hours_json = clean_windows
        self.db.commit()
        self.db.refresh(row)
        return self.get(tenant_id, workspace_id)

    def resolve(
        self, tenant_id: str, workspace_id: Optional[str]
    ) -> Optional[Tuple[str, Dict[str, List[Dict[str, str]]]]]:
        """The workspace's own row -> the tenant-default row (workspace_id
        NULL) -> None (unconfigured either way). Mirrors
        `MediaSettingsService._resolve_row`."""
        row = self._row(tenant_id, workspace_id) if workspace_id else None
        if row is None or not row.business_timezone:
            row = self._row(tenant_id, None)
        if row is None or not row.business_timezone:
            return None
        return row.business_timezone, (row.business_hours_json or {})


def _inside(windows: Dict[str, List[Dict[str, str]]], local: datetime) -> bool:
    today_idx = local.weekday()  # Monday == 0
    today_key = DAY_KEYS[today_idx]
    time_str = local.strftime("%H:%M")
    for window in windows.get(today_key, []) or []:
        start, end = window.get("from", ""), window.get("to", "")
        if end > start:
            if start <= time_str <= end:
                return True
        else:
            # Overnight window that STARTED today - still open until it wraps.
            if time_str >= start:
                return True
    prev_key = DAY_KEYS[(today_idx - 1) % 7]
    for window in windows.get(prev_key, []) or []:
        start, end = window.get("from", ""), window.get("to", "")
        if end <= start:
            # Overnight window that started YESTERDAY, ends this morning.
            if time_str < end:
                return True
    return False


def evaluate(
    db: Session, tenant_id: str, workspace_id: str, *, at: Optional[datetime] = None
) -> Tuple[bool, str, datetime]:
    """``(is_open, resolved_timezone, checked_at_utc)``. Raises
    `MissingBusinessHours` when neither the workspace nor the tenant default
    has configured hours (AC-WFP-56 - fail loud, never guess)."""
    resolved = BusinessHoursService(db).resolve(tenant_id, workspace_id)
    if resolved is None:
        raise MissingBusinessHours(
            "Business hours are not configured for this workspace."
        )
    tzname, windows = resolved
    now = at or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo(tzname))
    return _inside(windows, local), tzname, now
