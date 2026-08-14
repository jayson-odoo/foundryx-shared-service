"""Interactive / location / contacts message helpers (plan 12 Slice 2).

ONE place for the friendly ``payload_json`` shape (stored + rendered), its
validation (buttons≤3, list≤10 rows, title/URL limits), and the transform to the
Meta Cloud API object - reused by the inbox composer AND the public gateway so
both enforce the same rules. Pure functions (no DB/HTTP); the send task builds the
Meta object here at send time (injecting an uploaded media-header id).
"""
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# WhatsApp Cloud API limits.
MAX_BUTTONS = 3
MAX_BUTTON_TITLE = 20
MAX_LIST_ROWS = 10
MAX_ROW_TITLE = 24
MAX_ROW_DESCRIPTION = 72
MAX_SECTION_TITLE = 24
MAX_HEADER_TEXT = 60
MAX_BODY = 1024
MAX_FOOTER = 60
MAX_CTA_DISPLAY = 20

INTERACTIVE_KINDS = ("buttons", "list", "cta_url", "location_request")
MEDIA_HEADER_TYPES = ("image", "video", "document")
# WhatsApp contacts phone-type enum - anything else is dropped (Meta rejects it).
CONTACT_PHONE_TYPES = ("CELL", "HOME", "WORK", "MAIN", "IPHONE")


class StructuredError(ValueError):
    """Validation failure - carries a human message the composer/gateway surface."""


def _s(v: Any) -> str:
    return (v or "").strip() if isinstance(v, str) else ""


# ── Interactive ──────────────────────────────────────────────────────────────
def validate_interactive(defn: Dict[str, Any]) -> None:
    """Validate a friendly interactive definition. Raises StructuredError."""
    kind = _s(defn.get("kind"))
    if kind not in INTERACTIVE_KINDS:
        raise StructuredError(f"Unknown interactive kind '{kind}'.")
    body = _s(defn.get("body"))
    if not body:
        raise StructuredError("An interactive message needs body text.")
    if len(body) > MAX_BODY:
        raise StructuredError(f"Body must be ≤ {MAX_BODY} characters.")
    footer = _s(defn.get("footer"))
    if footer and len(footer) > MAX_FOOTER:
        raise StructuredError(f"Footer must be ≤ {MAX_FOOTER} characters.")

    header = defn.get("header")
    if header is not None:
        htype = _s(header.get("type"))
        if htype == "text":
            if len(_s(header.get("text"))) > MAX_HEADER_TEXT:
                raise StructuredError(f"Header text must be ≤ {MAX_HEADER_TEXT} characters.")
        elif htype not in MEDIA_HEADER_TYPES:
            raise StructuredError("Header type must be text, image, video or document.")

    if kind == "buttons":
        buttons = defn.get("buttons") or []
        if not (1 <= len(buttons) <= MAX_BUTTONS):
            raise StructuredError(f"Provide 1-{MAX_BUTTONS} reply buttons.")
        seen = set()
        for b in buttons:
            title = _s(b.get("title"))
            bid = _s(b.get("id"))
            if not title or not bid:
                raise StructuredError("Each button needs an id and a title.")
            if len(title) > MAX_BUTTON_TITLE:
                raise StructuredError(f"Button titles must be ≤ {MAX_BUTTON_TITLE} characters.")
            if bid in seen:
                raise StructuredError("Button ids must be unique.")
            seen.add(bid)
    elif kind == "list":
        lst = defn.get("list") or {}
        if not _s(lst.get("button")):
            raise StructuredError("A list needs a button label.")
        sections = lst.get("sections") or []
        if not sections:
            raise StructuredError("A list needs at least one section.")
        total_rows = 0
        seen = set()
        for sec in sections:
            if len(_s(sec.get("title"))) > MAX_SECTION_TITLE:
                raise StructuredError(f"Section titles must be ≤ {MAX_SECTION_TITLE} characters.")
            rows = sec.get("rows") or []
            if not rows:
                raise StructuredError("Each section needs at least one row.")
            for row in rows:
                total_rows += 1
                rid = _s(row.get("id"))
                title = _s(row.get("title"))
                if not rid or not title:
                    raise StructuredError("Each row needs an id and a title.")
                if len(title) > MAX_ROW_TITLE:
                    raise StructuredError(f"Row titles must be ≤ {MAX_ROW_TITLE} characters.")
                if len(_s(row.get("description"))) > MAX_ROW_DESCRIPTION:
                    raise StructuredError(
                        f"Row descriptions must be ≤ {MAX_ROW_DESCRIPTION} characters."
                    )
                if rid in seen:
                    raise StructuredError("Row ids must be unique across the list.")
                seen.add(rid)
        if total_rows > MAX_LIST_ROWS:
            raise StructuredError(f"A list can have at most {MAX_LIST_ROWS} rows.")
    elif kind == "cta_url":
        cta = defn.get("cta") or {}
        display = _s(cta.get("displayText"))
        url = _s(cta.get("url"))
        if not display or not url:
            raise StructuredError("A CTA button needs display text and a URL.")
        if len(display) > MAX_CTA_DISPLAY:
            raise StructuredError(f"CTA display text must be ≤ {MAX_CTA_DISPLAY} characters.")
        # We hand the URL to Meta (never fetch it ourselves) - still enforce a safe
        # scheme so the recipient's tap opens a real link, not javascript:/data:.
        scheme = urlparse(url).scheme.lower()
        if scheme not in ("http", "https"):
            raise StructuredError("The CTA URL must start with http:// or https://.")
    # location_request needs only body (validated above).


def header_media_kind(defn: Dict[str, Any]) -> Optional[str]:
    """The media kind of an interactive header (image/video/document) or None."""
    header = defn.get("header") or {}
    htype = _s(header.get("type"))
    return htype if htype in MEDIA_HEADER_TYPES else None


def build_meta_interactive(defn: Dict[str, Any], *, media_id: Optional[str] = None) -> Dict[str, Any]:
    """Transform a validated friendly definition → the Meta ``interactive`` object.
    ``media_id`` is the uploaded header-media id (required when the header is media)."""
    kind = _s(defn.get("kind"))
    out: Dict[str, Any] = {"body": {"text": _s(defn.get("body"))}}
    footer = _s(defn.get("footer"))
    if footer:
        out["footer"] = {"text": footer}

    header = defn.get("header")
    if header is not None:
        htype = _s(header.get("type"))
        if htype == "text":
            out["header"] = {"type": "text", "text": _s(header.get("text"))}
        elif htype in MEDIA_HEADER_TYPES and media_id:
            out["header"] = {"type": htype, htype: {"id": media_id}}

    if kind == "buttons":
        out["type"] = "button"
        out["action"] = {
            "buttons": [
                {"type": "reply", "reply": {"id": _s(b.get("id")), "title": _s(b.get("title"))}}
                for b in (defn.get("buttons") or [])
            ]
        }
    elif kind == "list":
        lst = defn.get("list") or {}
        sections: List[Dict[str, Any]] = []
        for sec in lst.get("sections") or []:
            rows = [
                {
                    "id": _s(r.get("id")),
                    "title": _s(r.get("title")),
                    **({"description": _s(r.get("description"))} if _s(r.get("description")) else {}),
                }
                for r in (sec.get("rows") or [])
            ]
            section: Dict[str, Any] = {"rows": rows}
            if _s(sec.get("title")):
                section["title"] = _s(sec.get("title"))
            sections.append(section)
        out["type"] = "list"
        out["action"] = {"button": _s(lst.get("button")), "sections": sections}
    elif kind == "cta_url":
        cta = defn.get("cta") or {}
        out["type"] = "cta_url"
        out["action"] = {
            "name": "cta_url",
            "parameters": {"display_text": _s(cta.get("displayText")), "url": _s(cta.get("url"))},
        }
    elif kind == "location_request":
        out["type"] = "location_request_message"
        out["action"] = {"name": "send_location"}
    return out


# ── Location ─────────────────────────────────────────────────────────────────
def validate_location(defn: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + normalize a location payload → {lat,lng,name,address}."""
    try:
        lat = float(defn.get("lat") if defn.get("lat") is not None else defn.get("latitude"))
        lng = float(defn.get("lng") if defn.get("lng") is not None else defn.get("longitude"))
    except (TypeError, ValueError):
        raise StructuredError("Location needs numeric latitude and longitude.")
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise StructuredError("Latitude/longitude are out of range.")
    return {
        "lat": lat,
        "lng": lng,
        "name": _s(defn.get("name")) or None,
        "address": _s(defn.get("address")) or None,
    }


def build_meta_location(defn: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"latitude": defn["lat"], "longitude": defn["lng"]}
    if defn.get("name"):
        out["name"] = defn["name"]
    if defn.get("address"):
        out["address"] = defn["address"]
    return out


# ── Contacts ─────────────────────────────────────────────────────────────────
def validate_contacts(defn: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + normalize a contacts payload → WhatsApp-native {contacts:[...]}.

    Accepts either the friendly ``{contacts:[{name, phones:[{phone,type?}]}]}`` or a
    pre-shaped Meta contact (``name.formatted_name``). Requires each contact to have
    a display name + at least one phone."""
    raw = defn.get("contacts") or []
    if not raw:
        raise StructuredError("Provide at least one contact.")
    contacts: List[Dict[str, Any]] = []
    for c in raw:
        name = c.get("name")
        if isinstance(name, str):
            formatted = _s(name)
            name_obj = {"formatted_name": formatted, "first_name": formatted}
        else:
            name = name or {}
            formatted = _s(name.get("formatted_name")) or _s(name.get("first_name"))
            name_obj = {"formatted_name": formatted}
            if _s(name.get("first_name")):
                name_obj["first_name"] = _s(name.get("first_name"))
            if _s(name.get("last_name")):
                name_obj["last_name"] = _s(name.get("last_name"))
        if not formatted:
            raise StructuredError("Each contact needs a name.")
        phones = []
        for p in c.get("phones") or []:
            phone = _s(p.get("phone"))
            if not phone:
                continue
            entry = {"phone": phone}
            ptype = _s(p.get("type")).upper()
            if ptype in CONTACT_PHONE_TYPES:
                entry["type"] = ptype
            if _s(p.get("wa_id")):
                entry["wa_id"] = _s(p.get("wa_id"))
            phones.append(entry)
        if not phones:
            raise StructuredError(f"Contact '{formatted}' needs at least one phone number.")
        contacts.append({"name": name_obj, "phones": phones})
    return {"contacts": contacts}
