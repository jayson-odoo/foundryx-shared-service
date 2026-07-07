"""Uniform upload-by-id media pipeline (plan 12 §Locked D-Q2, AC-12-02/04/12).

ONE path for every outbound media source (inbox file · gateway multipart ·
gateway url→fetch): bytes → sniff mime (magic bytes; the declared type lies) →
per-workspace cap check (clamped ≤ Meta ceiling) → StorageService (``media_key``)
→ the send task later uploads to Meta ``/{phone}/media`` → ``media_id`` →
``adapter.send``.

Voice recordings arrive from the browser as webm/opus and are transcoded to
ogg/opus with **ffmpeg** in the send task (AC-12-04). This module owns the sniff,
cap and transcode primitives; the send task (``send_runner``) owns the Meta
upload + ``adapter.send``.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

# ── WhatsApp Cloud API hard ceilings (bytes) — never exceed these ────────────
# https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media
META_CEILINGS = {
    "IMAGE": 5 * 1024 * 1024,
    "VIDEO": 16 * 1024 * 1024,
    "AUDIO": 16 * 1024 * 1024,
    "VOICE": 16 * 1024 * 1024,
    "DOCUMENT": 100 * 1024 * 1024,
    "STICKER": 500 * 1024,  # animated cap (static is 100KB)
}

# Accepted mimes per kind — Meta's fixed set (NOT tenant-configurable). For VOICE
# the browser sends webm; the accepted set here is what we upload AFTER transcode.
ACCEPTED_MIMES = {
    "IMAGE": {"image/jpeg", "image/png"},
    "VIDEO": {"video/mp4", "video/3gpp"},
    "AUDIO": {"audio/aac", "audio/mpeg", "audio/mp4", "audio/amr", "audio/ogg"},
    "VOICE": {"audio/ogg"},
    "DOCUMENT": {
        "application/pdf",
        "application/zip",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/plain",
    },
    "STICKER": {"image/webp"},
}

# The raw recording mimes we accept as VOICE INPUT (pre-transcode).
_VOICE_INPUT_MIMES = {"video/webm", "audio/webm", "audio/ogg"}


class MediaRejected(Exception):
    """Sniff / cap / transcode rejection. ``code`` is the stable machine code the
    gateway/inbox surfaces (``oversize`` | ``unsupported_media`` | ``transcode_failed``)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class SniffedMedia:
    content: bytes
    mime: str
    size: int


def detect_media_mime(content: bytes, filename: Optional[str] = None) -> Optional[str]:
    """Sniff a WhatsApp media blob by magic bytes. Returns the detected mime or
    None (= reject). The declared content-type is IGNORED — browsers derive it
    from the extension, which lies."""
    if not content:
        return None
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content[:4] == b"OggS":
        return "audio/ogg"
    if content[:5] == b"#!AMR":
        return "audio/amr"
    if content[:3] == b"ID3" or content[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if content[:2] in (b"\xff\xf1", b"\xff\xf9"):
        return "audio/aac"
    # EBML (webm / matroska) — the browser MediaRecorder voice/video format.
    if content[:4] == b"\x1aE\xdf\xa3":
        return "video/webm"
    # ISO Base Media File Format (mp4 / m4a / 3gp): 'ftyp' box at offset 4.
    if content[4:8] == b"ftyp":
        brand = content[8:12]
        if brand[:3] == b"3gp":
            return "video/3gpp"
        if brand[:3] in (b"M4A", b"M4B"):
            return "audio/mp4"
        return "video/mp4"
    # Office/zip container (document family). The office sub-type is refined from
    # the extension WITHIN the magic-verified zip family (never a security call).
    if content[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        ext = os.path.splitext(filename or "")[1].lower()
        return {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }.get(ext, "application/zip")
    # Block executables outright before the text fallback.
    if content[:2] == b"MZ" or content[:4] == b"\x7fELF":
        return None
    head = content[:512].lstrip().lower()
    if head.startswith(b"<") :  # SVG/HTML/XML — script-bearing markup
        return None
    try:
        content.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return None
    return "text/plain"


def sniff_and_validate(
    kind: str,
    content: bytes,
    *,
    filename: Optional[str],
    max_bytes: int,
) -> SniffedMedia:
    """Sniff + cap-check a raw upload for ``kind`` (IMAGE/VIDEO/AUDIO/VOICE/
    DOCUMENT/STICKER). Raises ``MediaRejected`` on a wrong mime or oversize.
    VOICE is validated against the raw recording mimes (transcode happens later
    in the send task)."""
    kind = (kind or "").upper()
    if kind not in META_CEILINGS:
        raise MediaRejected("unsupported_media", f"Unsupported media kind '{kind}'.")
    size = len(content or b"")
    if size == 0:
        raise MediaRejected("unsupported_media", "The uploaded file is empty.")
    if size > max_bytes:
        raise MediaRejected(
            "oversize",
            f"File is {size} bytes; the limit for {kind.lower()} is {max_bytes} bytes.",
        )
    mime = detect_media_mime(content, filename)
    if mime is None:
        raise MediaRejected("unsupported_media", "The file type could not be verified.")
    allowed = _VOICE_INPUT_MIMES if kind == "VOICE" else ACCEPTED_MIMES[kind]
    if mime not in allowed:
        raise MediaRejected(
            "unsupported_media",
            f"'{mime}' is not an accepted {kind.lower()} type.",
        )
    return SniffedMedia(content=content, mime=mime, size=size)


def transcode_voice(content: bytes) -> bytes:
    """Transcode a browser voice recording (webm/opus) → ogg/opus via ffmpeg so
    WhatsApp treats it as a true voice note (AC-12-04). A failure raises
    ``MediaRejected('transcode_failed')`` — never a silent no-op. Tests monkey-
    patch this."""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in")
        dst = os.path.join(tmp, "out.ogg")
        with open(src, "wb") as fh:
            fh.write(content)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", src, "-c:a", "libopus", "-b:a", "32k", dst],
                capture_output=True,
                check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise MediaRejected(
                "transcode_failed", "Could not process the voice recording."
            ) from exc
        with open(dst, "rb") as fh:
            return fh.read()
