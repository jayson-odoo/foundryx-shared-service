"""Code-level write allowlist (plan 55 section 6, AC-55-02..04).

Only books named in ``WRITE_ALLOWED_BOOKS`` may be written. The set is a module
constant on purpose: opening a live book needs a code change and a review,
never an env var or a setting.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional
from urllib.parse import urlsplit

WRITE_ALLOWED_BOOKS = frozenset({"db3"})

# sha256 (lowercase hex) of each allowed AutoCount test wrapper host. A code
# constant, like the book list: widening it needs a change and a review, never
# an env var or a setting. Only the digest is kept, never the host name.
ALLOWED_WRITE_HOST_SHA256: frozenset[str] = frozenset(
    {
        "4470ef4eed269510404eeed2189ea8ee8381507ad461ab86b3b6fd9ea599c87a",
    }
)

_HTTPS_PORT = 443
_API_SEGMENT = "api"
_SAFE_BOOK = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_FORBIDDEN_CHARS = ("?", "#", ";", "%", "\\", "@")


class WriteNotAllowed(Exception):
    """The base URL does not name an allowlisted book. Carries only the book
    segment (never the URL), so no credential or query can leak into a log."""

    code = "WRITE_NOT_ALLOWED"

    def __init__(self, book: str = "") -> None:
        self.book = book
        super().__init__(f"Writes are not allowed for book '{book}'.")


def _host_allowed(host: str) -> bool:
    digest = hashlib.sha256(host.lower().encode("utf-8")).hexdigest()
    return digest in ALLOWED_WRITE_HOST_SHA256


def _clean_segments(base_url: str) -> list[str]:
    """Path segments of a strictly-shaped https URL, or [] when the shape is
    refused (not https, userinfo, query, fragment, params, encoded or dot
    segments, empty segments, a port other than 443, a host off the hashed
    allowlist)."""
    if not base_url or any(c in base_url for c in _FORBIDDEN_CHARS):
        return []
    try:  # malformed hosts raise ValueError inside urlsplit / hostname / port
        parts = urlsplit(base_url)
        host = parts.hostname
        port: Optional[int] = parts.port
    except ValueError:
        return []
    if parts.scheme != "https" or not host:
        return []
    if port not in (None, _HTTPS_PORT) or not _host_allowed(host):
        return []
    path = parts.path[:-1] if parts.path.endswith("/") else parts.path
    segments = path.split("/")[1:] if path else []
    if any(s in ("", ".", "..") for s in segments):
        return []
    return segments


def assert_write_allowed(base_url: str) -> str:
    """Return the allowlisted book the URL names (path exactly ``/api/<book>``),
    else raise ``WriteNotAllowed``."""
    segments = _clean_segments(base_url)
    book = segments[-1] if len(segments) == 2 and segments[0] == _API_SEGMENT else ""
    if book not in WRITE_ALLOWED_BOOKS:
        raise WriteNotAllowed(book if _SAFE_BOOK.match(book) else "")
    return book
