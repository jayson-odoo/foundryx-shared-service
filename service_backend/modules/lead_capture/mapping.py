"""Answer mapping + the documented lead body (AC-64-24/35/50/62/65).

Default targets with no consumer field list (AC-64-61): ``name``, ``phone``,
``email``, ``notes``. Meta's standard question keys map by name; every other
answer goes to ``notes`` as one ``key: value`` line (owner D3 = a: the lead is
delivered at once and the source records a "Map fields" notice).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_TARGETS = ("name", "phone", "email", "notes")

# Meta standard Instant Form question keys -> default target.
STANDARD_KEYS = {
    "full_name": "name",
    "email": "email",
    "phone_number": "phone",
}
NAME_PARTS = ("first_name", "last_name")


def iso_z(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_meta_time(value: Any) -> Optional[datetime]:
    """Meta sends ``2026-11-15T05:19:11+0000`` on the lead and epoch seconds on
    the webhook. Anything else = None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z",):
            try:
                return datetime.strptime(value, fmt).astimezone(timezone.utc)
            except ValueError:
                continue
    return None


def answers_from(field_data: Any) -> List[Dict[str, Any]]:
    """Meta ``field_data`` -> ``[{"key", "values": [str]}]`` (malformed items dropped)."""
    out: List[Dict[str, Any]] = []
    if not isinstance(field_data, list):
        return out
    for item in field_data:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        values = item.get("values")
        vals = [str(v) for v in values if isinstance(v, (str, int, float)) and not isinstance(v, bool)] if isinstance(values, list) else []
        out.append({"key": item["name"], "values": vals})
    return out


def map_answers(
    answers: List[Dict[str, Any]], form_map: Optional[Dict[str, str]] = None
) -> Tuple[Dict[str, Optional[str]], int]:
    """Return ``(fields, unmapped_count)``. ``form_map`` (question key -> target)
    wins over the standard keys; with none, standard keys map by name."""
    form_map = form_map or {}
    fields: Dict[str, Optional[str]] = {t: None for t in DEFAULT_TARGETS}
    notes: List[str] = []
    name_parts: Dict[str, str] = {}
    unmapped = 0
    for ans in answers:
        key, value = ans["key"], ", ".join(ans["values"]).strip()
        if not value:
            continue
        target = form_map.get(key) or STANDARD_KEYS.get(key)
        if target is None and key in NAME_PARTS:
            name_parts[key] = value
            continue
        if target in fields and target != "notes" and fields[target] is None:
            fields[target] = value
            continue
        notes.append(f"{key}: {value}")
        if key not in form_map:
            unmapped += 1
    if fields["name"] is None and name_parts:
        fields["name"] = " ".join(name_parts[p] for p in NAME_PARTS if p in name_parts)
    fields["notes"] = "\n".join(notes) or None
    return fields, unmapped


def normalise_email(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip().lower()
    return v if "@" in v else None


def normalise_phone(value: Optional[str]) -> Optional[str]:
    """E.164 when the value already carries a country code (Meta sends
    ``+60...``); otherwise None (default-country rule = later lane)."""
    raw = (value or "").strip()
    digits = "".join(c for c in raw if c.isdigit())
    if raw.startswith("+") and 8 <= len(digits) <= 15:
        return "+" + digits
    return None


def lead_body(
    *,
    lead_id: str,
    source_id: str,
    source_name: str,
    platform: str,
    platform_lead_id: str,
    page_id: Optional[str],
    form_id: Optional[str],
    received_at: datetime,
    platform_created_at: Optional[datetime],
    is_test: bool,
    duplicate_of: Optional[str],
    fields: Dict[str, Optional[str]],
    answers: List[Dict[str, Any]],
    attribution: Dict[str, Any],
) -> Dict[str, Any]:
    """The ONE lead shape: webhook ``data`` and every pull item (AC-64-65)."""
    return {
        "id": lead_id,
        "sourceId": source_id,
        "sourceName": source_name,
        "platform": platform,
        "platformLeadId": platform_lead_id,
        "pageId": page_id,
        "formId": form_id,
        "receivedAt": iso_z(received_at),
        "createdAt": iso_z(platform_created_at),
        "isTest": bool(is_test),
        "duplicateOf": duplicate_of,
        "fields": fields,
        "answers": answers,
        "attribution": attribution,
    }
