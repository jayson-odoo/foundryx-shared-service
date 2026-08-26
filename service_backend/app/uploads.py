"""Shared upload sniffing (extracted from branding_service in plan 06 -
avatars need the same gate).

The DECLARED content-type is client input (browsers derive it from the file
EXTENSION, which lies: a JPEG renamed .png declares image/png). Detect the
real type from magic bytes and gate/store THAT; the declared type is ignored
entirely (sprint-2/03 review lesson).
"""
import os
from typing import Optional, Tuple

_SIGNATURES: Tuple[Tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x00\x00\x01\x00", "image/x-icon"),
)


def detect_mime(content: bytes) -> Optional[str]:
    for sig, mime in _SIGNATURES:
        if content.startswith(sig):
            return mime
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    head = content[:512].lstrip().lower()
    if head.startswith(b"<svg") or head.startswith(b"<?xml"):
        return "image/svg+xml"
    return None


# Office (OOXML) extensions → canonical mimes. A docx/xlsx/pptx is a ZIP
# container indistinguishable from a plain .zip by magic alone, so the specific
# office type is refined from the filename EXTENSION - a SOFT sub-classifier
# WITHIN the already-magic-verified zip family, never a security decision (the
# zip sniff is the gate). Lets the form-builder's "Allowed file types" config
# target a specific office format (BL-093).
_ZIP_EXT_MIMES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def detect_upload_mime(content: bytes, filename: Optional[str] = None) -> Optional[str]:
    """Sniff a form-engine file upload by magic bytes (plan sprint-3/02 D12,
    widened BL-093). SECURITY = the magic sniff: images (PNG/JPEG/WebP/ICO/GIF),
    PDF, the OOXML/ODF zip family, and UTF-8 text are accepted; executables
    (MZ/ELF), SVG and HTML are HARD-blocked regardless of any tenant config. The
    declared content-type is client input and lies, so it's ignored entirely.
    WITHIN the verified zip family the filename extension refines the office
    sub-type (.docx/.xlsx/.pptx) so a builder allowed-types whitelist can target
    a specific format; an unrecognised zip stays ``application/zip``. Returns the
    sniffed mime or None (= reject)."""
    image = detect_mime(content)
    if image is not None and image != "image/svg+xml":
        return image  # png/jpeg/webp/ico
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        ext = os.path.splitext(filename or "")[1].lower()
        return _ZIP_EXT_MIMES.get(ext, "application/zip")
    # Block the dangerous lookalikes before the text fallback.
    if content[:2] == b"MZ" or content[:4] == b"\x7fELF":
        return None  # executables
    head = content[:512].lstrip().lower()
    if (
        head.startswith(b"<svg")
        or head.startswith(b"<?xml")
        or head.startswith(b"<!doctype")
        or head.startswith(b"<html")
    ):
        return None  # script-bearing markup
    try:
        content.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return None
    return "text/plain"


def detect_document_mime(content: bytes) -> Optional[str]:
    """Sniff a Drive upload by magic bytes - the broader allow-list the document
    engine needs (plan sprint-3/04 D7): images, PDF, the zip family (docx/xlsx/
    pptx/odt/zip), GIF, and UTF-8 text/CSV. Returns the sniffed mime or None
    (= reject).

    HARD FLOOR, non-overridable: executables (MZ/ELF), HTML, SVG, and anything
    else not on the list return None - a tenant's attachment-type config can
    never open this. The declared content-type is ignored (it lies)."""
    image = detect_mime(content)
    if image is not None and image != "image/svg+xml":
        return image  # png/jpeg/webp/ico
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    # Zip container (docx/xlsx/pptx/odt are zips) - also a plain .zip. We cannot
    # cheaply distinguish office vs plain zip by magic alone; accept the family.
    if content[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return "application/zip"
    # Explicitly block the dangerous lookalikes before the text fallback.
    if content[:2] == b"MZ" or content[:4] == b"\x7fELF":
        return None  # executables
    head = content[:512].lstrip().lower()
    if (
        head.startswith(b"<svg")
        or head.startswith(b"<?xml")
        or head.startswith(b"<!doctype")
        or head.startswith(b"<html")
    ):
        return None  # script-bearing markup
    # Text fallback: decodable as UTF-8 and not markup → text/plain.
    try:
        content.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return None
    return "text/plain"
