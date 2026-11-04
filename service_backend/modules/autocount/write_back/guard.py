"""Code-level write allowlist (plan 55 section 6, AC-55-02..04).

Only books named in ``WRITE_ALLOWED_BOOKS`` may be written. The set is a module
constant on purpose: opening a live book needs a code change and a review,
never an env var or a setting.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

WRITE_ALLOWED_BOOKS = frozenset({"db3"})

_SAFE_BOOK = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_FORBIDDEN_CHARS = ("?", "#", ";", "%", "\\", "@")


class WriteNotAllowed(Exception):
    """The base URL does not name an allowlisted book. Carries only the book
    segment (never the URL), so no credential or query can leak into a log."""

    code = "WRITE_NOT_ALLOWED"

    def __init__(self, book: str = "") -> None:
        self.book = book
        super().__init__(f"Writes are not allowed for book '{book}'.")


def _clean_segments(base_url: str) -> list[str]:
    """Path segments of a strictly-shaped https URL, or [] when the shape is
    refused (not https, userinfo, query, fragment, params, encoded or dot
    segments, empty segments)."""
    if not base_url or any(c in base_url for c in _FORBIDDEN_CHARS):
        return []
    parts = urlsplit(base_url)
    if parts.scheme != "https" or not parts.hostname:
        return []
    path = parts.path[:-1] if parts.path.endswith("/") else parts.path
    segments = path.split("/")[1:] if path else []
    if any(s in ("", ".", "..") for s in segments):
        return []
    return segments


def assert_write_allowed(base_url: str) -> str:
    """Return the allowlisted book the URL ends in, else raise ``WriteNotAllowed``."""
    segments = _clean_segments(base_url)
    book = segments[-1] if segments else ""
    if book not in WRITE_ALLOWED_BOOKS:
        raise WriteNotAllowed(book if _SAFE_BOOK.match(book) else "")
    return book
