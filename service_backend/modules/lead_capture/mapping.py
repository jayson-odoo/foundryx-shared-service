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
FIELD_TYPES = ("name", "phone", "email", "notes", "text")
# (key, type) of the default targets, used when a product published no field list.
DEFAULT_FIELDS: Tuple[Tuple[str, str], ...] = (("name", "name"), ("phone", "phone"), ("email", "email"), ("notes", "notes"))

# Meta standard Instant Form question keys -> the field TYPE they fill.
STANDARD_KEYS = {
    "full_name": "name",
    "email": "email",
    "phone_number": "phone",
    # Google Ads lead form column ids (card 68a R7,
    # https://developers.google.com/google-ads/webhook/docs/implementation)
    "FULL_NAME": "name",
    "EMAIL": "email",
    "WORK_EMAIL": "email",
    "PHONE_NUMBER": "phone",
    "WORK_PHONE": "phone",
}
NAME_PARTS = ("first_name", "last_name")
# Google's name-part column ids -> the Meta name-part keys they stand for.
NAME_PART_ALIASES = {"FIRST_NAME": "first_name", "LAST_NAME": "last_name"}
ANY_FORM = "*"


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


def form_map_for(field_map: Optional[Dict[str, Any]], form_id: Optional[str]) -> Tuple[Dict[str, str], bool]:
    """``(question -> target, has_explicit_map)``: the "*" (every form) map,
    overlaid by the form's own map."""
    field_map = field_map or {}
    base = field_map.get(ANY_FORM) or {}
    own = (field_map.get(form_id) or {}) if form_id else {}
    merged = {**base, **own}
    return merged, bool(base or own)


def map_answers(
    answers: List[Dict[str, Any]],
    form_map: Optional[Dict[str, str]] = None,
    targets: Optional[List[Tuple[str, str]]] = None,
) -> Tuple[Dict[str, Optional[str]], int]:
    """Return ``(fields, unmapped_count)``.

    ``targets`` are the product's own fields as ``(key, type)`` (default:
    name/phone/email/notes). An answer goes to the target the map names; else
    a Meta standard question goes to the first target of its type; else it is
    one ``key: value`` line in the first ``notes``-type target and counts as
    unmapped. ``fields`` always has every target key."""
    form_map = form_map or {}
    targets = list(targets or DEFAULT_FIELDS)
    keys = [k for k, _t in targets]
    by_type: Dict[str, str] = {}
    for key, typ in targets:
        by_type.setdefault(typ, key)
    notes_key = by_type.get("notes")
    fields: Dict[str, Optional[str]] = {k: None for k in keys}
    notes: List[str] = []
    name_parts: Dict[str, str] = {}
    unmapped = 0
    for ans in answers:
        key, value = ans["key"], ", ".join(ans["values"]).strip()
        if not value:
            continue
        target = form_map.get(key)
        if target in fields and target != notes_key:
            fields[target] = value if fields[target] is None else f"{fields[target]}, {value}"
            continue
        if target is None:
            std = STANDARD_KEYS.get(key)
            std_target = by_type.get(std) if std else None
            if std_target and fields[std_target] is None:
                fields[std_target] = value
                continue
            part = NAME_PART_ALIASES.get(key, key)
            if part in NAME_PARTS and by_type.get("name"):
                name_parts[part] = value
                continue
            unmapped += 1
        notes.append(f"{key}: {value}")
    name_key = by_type.get("name")
    if name_key and fields[name_key] is None and name_parts:
        fields[name_key] = " ".join(name_parts[p] for p in NAME_PARTS if p in name_parts)
    if notes_key:
        fields[notes_key] = "\n".join(notes) or None
    return fields, unmapped


def typed_value(fields: Dict[str, Optional[str]], targets: Optional[List[Tuple[str, str]]], typ: str) -> Optional[str]:
    """The value of the first target of ``typ`` (for email / phone search)."""
    for key, t in targets or DEFAULT_FIELDS:
        if t == typ:
            return fields.get(key)
    return None


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
    form_name: Optional[str],
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
        "formName": form_name,
        "receivedAt": iso_z(received_at),
        "createdAt": iso_z(platform_created_at),
        "isTest": bool(is_test),
        "duplicateOf": duplicate_of,
        "fields": fields,
        "answers": answers,
        "attribution": attribution,
    }
