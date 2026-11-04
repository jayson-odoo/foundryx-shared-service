"""One-document GET by DocKey for write-back (plan 55 section 6b, AC-55-20).

The vendor has no get-by-DocKey door, so the document is read through
``<doc>bydocdate?DocDate=YYYYMMDD`` and filtered on ``DocKey``: none or more
than one match is refused. A single GET, never retried (the doc-feed ladder
sleeps and retries, wrong for a read that gates a write). Uses the house
SSRF-guarded client with redirects off.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

import httpx

from modules.autocount.http_client import autocount_guarded_client
from modules.autocount.write_back.constants import (
    PO_BY_DOC_DATE_PATH,
    PO_BY_LAST_MODIFIED_PATH,
    SO_BY_DOC_DATE_PATH,
    SO_BY_LAST_MODIFIED_PATH,
)

DOC_NOT_FOUND = "DOC_NOT_FOUND"
DOC_AMBIGUOUS = "DOC_AMBIGUOUS"
READ_FAILED = "READ_FAILED"

Document = Dict[str, object]

_LAST_MODIFIED_PATHS = {
    "PO": PO_BY_LAST_MODIFIED_PATH,
    "SPO": PO_BY_LAST_MODIFIED_PATH,
    "SO": SO_BY_LAST_MODIFIED_PATH,
}
_PATHS = {"PO": PO_BY_DOC_DATE_PATH, "SPO": PO_BY_DOC_DATE_PATH, "SO": SO_BY_DOC_DATE_PATH}


class DocReadError(Exception):
    """A document read that did not yield exactly one document. Text = code only."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AutoCountDocReader:
    def __init__(
        self,
        base_url: str,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 90.0,
    ) -> None:
        self.base_url = base_url
        self._transport = transport
        self._timeout = timeout

    def _http(self) -> httpx.Client:
        if self._transport is not None:
            return httpx.Client(
                transport=self._transport, timeout=self._timeout, follow_redirects=False
            )
        return autocount_guarded_client(self._timeout)

    def _fetch(self, path: Optional[str], params: Dict[str, str]) -> List[Document]:
        if path is None:
            raise DocReadError(READ_FAILED)
        url = self.base_url.rstrip("/") + path
        try:
            with self._http() as http:
                response = http.get(url, params=params)
            if not response.is_success:
                raise DocReadError(READ_FAILED)
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise DocReadError(READ_FAILED) from None
        if not isinstance(body, list):
            raise DocReadError(READ_FAILED)
        return [d for d in body if isinstance(d, dict)]

    def _fetch_day(self, kind: str, doc_date: date) -> List[Document]:
        return self._fetch(_PATHS.get(kind), {"DocDate": doc_date.strftime("%Y%m%d")})

    def list_day(self, kind: str, day: date, *, by_last_modified: bool) -> List[Document]:
        """Every ``kind`` document of one day, by ``lastModified`` or ``DocDate``
        (a PO answer also carries SPO documents)."""
        if by_last_modified:
            return self._fetch(
                _LAST_MODIFIED_PATHS.get(kind), {"lastModified": day.strftime("%Y%m%d")}
            )
        return self._fetch_day(kind, day)

    def get_document(self, kind: str, doc_key: int, doc_date: date) -> Document:
        """The single document of ``kind`` (PO | SPO | SO) with ``doc_key`` dated ``doc_date``."""
        matches = [d for d in self._fetch_day(kind, doc_date) if d.get("DocKey") == doc_key]
        if not matches:
            raise DocReadError(DOC_NOT_FOUND)
        if len(matches) > 1:
            raise DocReadError(DOC_AMBIGUOUS)
        return matches[0]
