"""WhatsApp template doc ⇄ Meta-component transform + validation (plan 07 §3).

ONE canonical store = the Meta component-array shape (`components_json`). The
friendly `WaTemplateDoc` is what the builder edits; `to_meta_components` /
`from_meta_components` are the single bidirectional transform, mirrored on the
frontend (`lib/whatsapp-template.ts`) and pinned by a parity test. No drift.

`validate_doc` is the save/submit gate → raises a 422 with a per-field map.
"""
import re
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from pydantic import BaseModel

# ── enums (mirrored FE) ──────────────────────────────────────────────────────
TEMPLATE_CATEGORIES = ["MARKETING", "UTILITY"]
HEADER_FORMATS = ["TEXT", "IMAGE", "VIDEO", "DOCUMENT"]
MEDIA_HEADER_FORMATS = ["IMAGE", "VIDEO", "DOCUMENT"]
BUTTON_TYPES = ["QUICK_REPLY", "URL", "PHONE_NUMBER", "COPY_CODE"]
# Meta status set the local row can hold (T1).
TEMPLATE_STATUSES = ["LOCAL_DRAFT", "PENDING", "APPROVED", "REJECTED", "PAUSED", "DISABLED"]
# Common Meta language codes (not exhaustive - Meta validates the full set).
TEMPLATE_LANGUAGES = [
    "en", "en_US", "en_GB", "es", "es_ES", "es_MX", "pt_BR", "pt_PT", "fr", "de",
    "it", "nl", "id", "ms", "zh_CN", "zh_HK", "zh_TW", "ja", "ko", "th", "vi",
    "ar", "hi", "ta", "ru", "tr",
]

_NAME_RE = re.compile(r"^[a-z0-9_]{1,512}$")
_VAR_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_PHONE_RE = re.compile(r"^\+?[0-9][0-9\-\s]{4,19}$")

MAX_BUTTONS = 10


# ── friendly builder doc (Pydantic mirrors of the TS interfaces) ─────────────
class WaHeader(BaseModel):
    format: str  # TEXT | IMAGE | VIDEO | DOCUMENT
    text: Optional[str] = None  # TEXT only
    example: Optional[str] = None  # TEXT var sample
    sampleKey: Optional[str] = None  # media: storage key of the draft sample


class WaBody(BaseModel):
    text: str
    examples: List[str] = []


class WaFooter(BaseModel):
    text: str


class WaButton(BaseModel):
    type: str  # QUICK_REPLY | URL | PHONE_NUMBER | COPY_CODE
    text: Optional[str] = None
    url: Optional[str] = None  # URL
    example: Optional[str] = None  # URL dynamic sample / COPY_CODE sample
    phoneNumber: Optional[str] = None  # PHONE_NUMBER


class WaTemplateDoc(BaseModel):
    name: str
    category: str
    language: str
    header: Optional[WaHeader] = None
    body: WaBody
    footer: Optional[WaFooter] = None
    buttons: Optional[List[WaButton]] = None


def distinct_var_count(text: str) -> int:
    """Number of distinct {{n}} placeholders in a string."""
    return len({int(m) for m in _VAR_RE.findall(text or "")})


def vars_sequential(text: str) -> bool:
    """True when the {{n}} placeholders are exactly {{1}}..{{N}} with no gaps -
    Meta requires sequential numbering, and our example arrays are positional."""
    nums = {int(m) for m in _VAR_RE.findall(text or "")}
    return not nums or nums == set(range(1, len(nums) + 1))


def ends_with_var(text: str) -> bool:
    """Meta rejects a body that ENDS with a variable (needs trailing text)."""
    return bool(re.search(r"\{\{\s*\d+\s*\}\}\s*$", text or ""))


def has_adjacent_vars(text: str) -> bool:
    """Meta rejects two variables with no static text between them."""
    return bool(re.search(r"\}\}\s*\{\{", text or ""))


# ── transform: friendly doc → Meta components array ──────────────────────────
def to_meta_components(doc: WaTemplateDoc) -> List[Dict[str, Any]]:
    components: List[Dict[str, Any]] = []

    if doc.header:
        if doc.header.format == "TEXT":
            comp: Dict[str, Any] = {"type": "HEADER", "format": "TEXT", "text": doc.header.text or ""}
            # Only emit a header example when the text actually has a variable -
            # a stale example on a var-less header is a Meta format rejection.
            if doc.header.example and distinct_var_count(doc.header.text or "") >= 1:
                comp["example"] = {"header_text": [doc.header.example]}
            components.append(comp)
        elif doc.header.format in MEDIA_HEADER_FORMATS:
            comp = {"type": "HEADER", "format": doc.header.format}
            # sampleKey is a local storage key pre-submit; the real header_handle
            # is injected at submit time after resumable upload (service layer).
            if doc.header.sampleKey:
                comp["example"] = {"header_handle": [doc.header.sampleKey]}
            components.append(comp)

    body_comp: Dict[str, Any] = {"type": "BODY", "text": doc.body.text}
    if doc.body.examples:
        body_comp["example"] = {"body_text": [list(doc.body.examples)]}
    components.append(body_comp)

    if doc.footer and doc.footer.text:
        components.append({"type": "FOOTER", "text": doc.footer.text})

    if doc.buttons:
        meta_buttons: List[Dict[str, Any]] = []
        for b in doc.buttons:
            if b.type == "QUICK_REPLY":
                meta_buttons.append({"type": "QUICK_REPLY", "text": b.text or ""})
            elif b.type == "URL":
                mb: Dict[str, Any] = {"type": "URL", "text": b.text or "", "url": b.url or ""}
                if b.example:  # dynamic URL
                    mb["example"] = [b.example]
                meta_buttons.append(mb)
            elif b.type == "PHONE_NUMBER":
                meta_buttons.append(
                    {"type": "PHONE_NUMBER", "text": b.text or "", "phone_number": b.phoneNumber or ""}
                )
            elif b.type == "COPY_CODE":
                meta_buttons.append({"type": "COPY_CODE", "example": b.example or ""})
        if meta_buttons:
            components.append({"type": "BUTTONS", "buttons": meta_buttons})

    return components


# ── transform: Meta components array → friendly doc ──────────────────────────
def from_meta_components(
    components: Optional[List[Dict[str, Any]]], *, name: str, category: str, language: str
) -> WaTemplateDoc:
    header: Optional[WaHeader] = None
    body = WaBody(text="", examples=[])
    footer: Optional[WaFooter] = None
    buttons: List[WaButton] = []

    for c in components or []:
        ctype = (c.get("type") or "").upper()
        if ctype == "HEADER":
            fmt = (c.get("format") or "TEXT").upper()
            if fmt == "TEXT":
                ex = (c.get("example") or {}).get("header_text") or []
                header = WaHeader(format="TEXT", text=c.get("text") or "", example=ex[0] if ex else None)
            elif fmt in MEDIA_HEADER_FORMATS:
                handle = (c.get("example") or {}).get("header_handle") or []
                header = WaHeader(format=fmt, sampleKey=handle[0] if handle else None)
        elif ctype == "BODY":
            ex = (c.get("example") or {}).get("body_text") or []
            examples = list(ex[0]) if ex and isinstance(ex[0], list) else []
            body = WaBody(text=c.get("text") or "", examples=examples)
        elif ctype == "FOOTER":
            footer = WaFooter(text=c.get("text") or "")
        elif ctype == "BUTTONS":
            for b in c.get("buttons") or []:
                bt = (b.get("type") or "").upper()
                if bt == "QUICK_REPLY":
                    buttons.append(WaButton(type="QUICK_REPLY", text=b.get("text")))
                elif bt == "URL":
                    ex = b.get("example") or []
                    buttons.append(
                        WaButton(type="URL", text=b.get("text"), url=b.get("url"),
                                 example=ex[0] if ex else None)
                    )
                elif bt == "PHONE_NUMBER":
                    buttons.append(
                        WaButton(type="PHONE_NUMBER", text=b.get("text"), phoneNumber=b.get("phone_number"))
                    )
                elif bt == "COPY_CODE":
                    buttons.append(WaButton(type="COPY_CODE", example=b.get("example")))

    return WaTemplateDoc(
        name=name, category=category, language=language,
        header=header, body=body, footer=footer, buttons=buttons or None,
    )


# ── validation ───────────────────────────────────────────────────────────────
def _err(field: str, message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"fieldErrors": {field: message}}
    )


def validate_doc(doc: WaTemplateDoc, *, existing_names: Optional[set] = None) -> None:
    """Raise 422 {fieldErrors} on the first invalid field (plan 07 §4).

    `existing_names` = other templates' names on the same channel (dup check).
    """
    if not _NAME_RE.match(doc.name or ""):
        raise _err("name", "Use lowercase letters, numbers and underscores (max 512).")
    if existing_names and doc.name in existing_names:
        raise _err("name", "A template with this name already exists on this channel.")
    if doc.category not in TEMPLATE_CATEGORIES:
        raise _err("category", "Choose Marketing or Utility.")
    if doc.language not in TEMPLATE_LANGUAGES:
        raise _err("language", "Choose a valid language.")

    # Header
    if doc.header:
        if doc.header.format not in HEADER_FORMATS:
            raise _err("header", "Unsupported header format.")
        if doc.header.format == "TEXT":
            nvars = distinct_var_count(doc.header.text or "")
            if nvars > 1:
                raise _err("header", "A text header allows at most one variable.")
            if nvars == 1 and not (doc.header.example or "").strip():
                raise _err("header", "Provide a sample value for the header variable.")

    # Body
    if not (doc.body.text or "").strip():
        raise _err("body", "Body text is required.")
    if not vars_sequential(doc.body.text):
        raise _err("body", "Variables must be numbered sequentially: {{1}}, {{2}}, …")
    if ends_with_var(doc.body.text):
        raise _err("body", "Body can’t end with a variable - add text after the last {{n}} (Meta rule).")
    if has_adjacent_vars(doc.body.text):
        raise _err("body", "Two variables can’t be adjacent - put text between them (Meta rule).")
    nvars = distinct_var_count(doc.body.text)
    provided = [e for e in (doc.body.examples or []) if (e or "").strip()]
    if len(provided) != nvars:
        raise _err("body", f"Provide exactly {nvars} sample value(s) for the body variables.")

    # Buttons
    if doc.buttons:
        if len(doc.buttons) > MAX_BUTTONS:
            raise _err("buttons", f"At most {MAX_BUTTONS} buttons.")
        for i, b in enumerate(doc.buttons):
            if b.type not in BUTTON_TYPES:
                raise _err("buttons", f"Button {i + 1}: unsupported type.")
            if b.type in ("QUICK_REPLY", "URL", "PHONE_NUMBER") and not (b.text or "").strip():
                raise _err("buttons", f"Button {i + 1}: label is required.")
            if b.type == "URL":
                if not _URL_RE.match((b.url or "").strip()):
                    raise _err("buttons", f"Button {i + 1}: enter a valid http(s) URL.")
            if b.type == "PHONE_NUMBER":
                if not _PHONE_RE.match((b.phoneNumber or "").strip()):
                    raise _err("buttons", f"Button {i + 1}: enter a valid phone number.")
            if b.type == "COPY_CODE" and not (b.example or "").strip():
                raise _err("buttons", f"Button {i + 1}: provide a sample code.")
