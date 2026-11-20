"""Code-level write allowlist (plan 55 section 6, plan 63 section 3.2).

``WRITE_ALLOWED_BOOKS`` is the code ceiling: no setting can widen it past this
set. Inside it, ``writable_books()`` narrows per call: the operator's
``AUTOCOUNT_WRITE_ALLOWED_BOOKS`` list, and off production only the test books.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional
from urllib.parse import urlsplit

from app.config import settings

# Books that are test copies: writable on any environment (still host-pinned).
TEST_BOOKS = frozenset({"db3"})
# The code ceiling; widening it needs a change and a review.
WRITE_ALLOWED_BOOKS = frozenset({"db1", "db3"})
_PRODUCTION = "production"

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


class WriteConnectionError(Exception):
    """A write connection refused: ``code`` is WRITE_NOT_ALLOWED, CONNECTION_NOT_FOUND or
    WRITE_COMPANY_NOT_TEST. ``set_write_connection`` leaves the company unchanged."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def writable_books() -> frozenset[str]:
    """The books a write may name right now: the code ceiling AND the operator list AND,
    unless the environment is exactly ``production``, the test books. Read per call."""
    listed = frozenset(settings.autocount_write_allowed_books_list)
    books = WRITE_ALLOWED_BOOKS & listed
    if settings.environment != _PRODUCTION:
        books = books & TEST_BOOKS
    return books


def assert_test_company(db, tenant_id: str, company_id: str, book: Optional[str] = None) -> None:
    """AC-57-22 / AC-57-47: the ONE write-time check that a company is a test book. A
    company that reads SQL, or holds a staged PO / SPO / SO row of a job other than
    write-back, is a live book: ``WriteConnectionError("WRITE_COMPANY_NOT_TEST")``.
    ``set_write_connection`` and every write frame call it as ``guard.assert_test_company``
    (the module attribute), so opening a live book is one reviewed change here. The live-book
    check is skipped only for ``book`` that is writable and not a test book (production only)."""
    if book is not None and book in writable_books() - TEST_BOOKS:
        return
    from modules.autocount.write_back.constants import STAGING_JOB_ID
    from modules.autocount.write_back.repository import CompanyDataRepository

    data = CompanyDataRepository(db)
    if data.has_sql_source(tenant_id, company_id) or data.has_foreign_document_rows(
        tenant_id, company_id, ("purchase_order", "shipping_order", "sales_order"), STAGING_JOB_ID
    ):
        raise WriteConnectionError("WRITE_COMPANY_NOT_TEST")


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


def host_allowlisted(base_url: str) -> bool:
    """Whether the URL's host is on the pinned wrapper host allowlist (any path)."""
    try:
        host = urlsplit(base_url or "").hostname
    except ValueError:
        return False
    return bool(host) and _host_allowed(host)


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
    if book not in writable_books():
        raise WriteNotAllowed(book if _SAFE_BOOK.match(book) else "")
    return book


def book_of(base_url: str) -> Optional[str]:
    """The book segment of a ``/api/<book>`` URL on the pinned host, whether or not it is
    writable (None when the shape is refused). For ``assert_test_company``."""
    segments = _clean_segments(base_url)
    book = segments[-1] if len(segments) == 2 and segments[0] == _API_SEGMENT else ""
    return book if _SAFE_BOOK.match(book) else None
