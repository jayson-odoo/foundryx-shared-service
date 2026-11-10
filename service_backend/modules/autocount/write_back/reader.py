"""One-document GET for write-back (plan 55 section 6b, AC-55-20; plan 61 section 4.4).

The vendor has no get-by-DocKey door. When the DocNo is known the document is read
with ``GET /<Doc>bydocno?DocNo=`` (plan 61 F1); a document whose DocKey is not the
expected one is never accepted. Only when that GET fails (transport error, non-2xx)
or no DocNo is known is the day list ``<doc>bydocdate?DocDate=YYYYMMDD`` read and
filtered on ``DocKey``: none or more than one match is refused. Each GET is single,
never retried (the doc-feed ladder sleeps and retries, wrong for a read that gates
a write). Uses the house SSRF-guarded client with redirects off.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from app.services.url_guard import UrlGuardError

from modules.autocount.http_client import autocount_guarded_client
from modules.autocount.write_back.doc_kinds import KINDS

DOC_NOT_FOUND = "DOC_NOT_FOUND"
DOC_AMBIGUOUS = "DOC_AMBIGUOUS"
READ_FAILED = "READ_FAILED"

Document = Dict[str, object]

# SS-QTSO-DISPLAYTERM: the Debtor master door of the open REST API (paged
# envelope ``{TotalPages, Data: [...]}``), walked until the debtor is found.
DEBTOR_PAGE_PATH = "/debtorbypage"
DEBTOR_PAGE_SIZE = 1000
DEBTOR_MAX_PAGES = 100  # 100k debtors; a book past that is refused READ_FAILED



def _by_modified_path(kind: str) -> Optional[str]:
    found = KINDS.get(kind)
    return found.by_modified_path if found else None


def _by_date_path(kind: str) -> Optional[str]:
    found = KINDS.get(kind)
    return found.by_date_path if found else None


def _by_doc_no_path(kind: str) -> Optional[str]:
    found = KINDS.get(kind)
    return found.by_doc_no_path if found else None


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
        except (httpx.HTTPError, httpx.InvalidURL, UrlGuardError, ValueError):
            raise DocReadError(READ_FAILED) from None
        if not isinstance(body, list):
            raise DocReadError(READ_FAILED)
        return [d for d in body if isinstance(d, dict)]

    def _fetch_day(self, kind: str, doc_date: date) -> List[Document]:
        return self._fetch(_by_date_path(kind), {"DocDate": doc_date.strftime("%Y%m%d")})

    def list_day(self, kind: str, day: date, *, by_last_modified: bool) -> List[Document]:
        """Every ``kind`` document of one day, by ``lastModified`` or ``DocDate``
        (a PO answer also carries SPO documents)."""
        if by_last_modified:
            return self._fetch(
                _by_modified_path(kind), {"lastModified": day.strftime("%Y%m%d")}
            )
        return self._fetch_day(kind, day)

    def get_by_doc_no(self, kind: str, doc_no: str) -> Document:
        """The single ``kind`` document numbered ``doc_no`` (``GET /<Doc>bydocno``);
        ``[]`` is ``DOC_NOT_FOUND``."""
        matches = self._fetch(_by_doc_no_path(kind), {"DocNo": doc_no})
        if not matches:
            raise DocReadError(DOC_NOT_FOUND)
        if len(matches) > 1:
            raise DocReadError(DOC_AMBIGUOUS)
        return matches[0]

    def get_document(
        self, kind: str, doc_key: int, doc_date: Optional[date], doc_no: Optional[str] = None
    ) -> Document:
        """The single document of ``kind`` (QT | SO | PO | SPO) with ``doc_key``: by its
        ``doc_no`` when known, else (or when that GET fails) from the ``doc_date`` list.
        A bydocno answer with another DocKey is ``DOC_NOT_FOUND`` (AC-61-02)."""
        if doc_no:
            try:
                found = self.get_by_doc_no(kind, doc_no)
            except DocReadError as exc:
                if exc.code != READ_FAILED or doc_date is None:
                    raise
            else:
                if found.get("DocKey") != doc_key:
                    raise DocReadError(DOC_NOT_FOUND)
                return found
        if doc_date is None:
            raise DocReadError(READ_FAILED)
        matches = [d for d in self._fetch_day(kind, doc_date) if d.get("DocKey") == doc_key]
        if not matches:
            raise DocReadError(DOC_NOT_FOUND)
        if len(matches) > 1:
            raise DocReadError(DOC_AMBIGUOUS)
        return matches[0]

    def find_by_doc_no(self, kind: str, doc_no: str, doc_date: date) -> Document:
        """The single ``kind`` document numbered ``doc_no``: the bydocno door, else
        (when that GET fails) the ``doc_date`` list."""
        try:
            return self.get_by_doc_no(kind, doc_no)
        except DocReadError as exc:
            if exc.code != READ_FAILED:
                raise
        matches = [d for d in self._fetch_day(kind, doc_date) if d.get("DocNo") == doc_no]
        if not matches:
            raise DocReadError(DOC_NOT_FOUND)
        if len(matches) > 1:
            raise DocReadError(DOC_AMBIGUOUS)
        return matches[0]

    def debtor_term(
        self, debtor_code: str, *, before_page: Optional[Callable[[], None]] = None
    ) -> Tuple[bool, Optional[str]]:
        """``(found, DisplayTerm)`` of the debtor ``debtor_code`` in this book.

        ``DisplayTerm`` is the debtor's own AutoCount term code (from AutoCount's
        Terms list), ``None`` when the debtor carries none. Codes compare trimmed
        and case-insensitively (AutoCount's SQL collation). Pages are walked with
        one client and stop at the first match; any failed or mis-shaped page is
        ``DocReadError(READ_FAILED)`` - never a guess. ``before_page`` runs before
        every page after the first (the caller's deadline check; it may raise).
        """
        wanted = debtor_code.strip().casefold()
        url = self.base_url.rstrip("/") + DEBTOR_PAGE_PATH
        try:
            with self._http() as http:
                page = 1
                while page <= DEBTOR_MAX_PAGES:
                    if page > 1 and before_page is not None:
                        before_page()
                    response = http.get(url, params={"page": str(page), "pageSize": str(DEBTOR_PAGE_SIZE)})
                    if not response.is_success:
                        raise DocReadError(READ_FAILED)
                    body: Any = response.json()
                    if not isinstance(body, dict) or not isinstance(body.get("Data"), list):
                        raise DocReadError(READ_FAILED)
                    for row in body["Data"]:
                        if isinstance(row, dict) and str(row.get("AccNo") or "").strip().casefold() == wanted:
                            term = row.get("DisplayTerm")
                            text = term.strip() if isinstance(term, str) else ""
                            return True, (text or None)
                    if not body["Data"]:
                        return False, None
                    total = body.get("TotalPages")
                    if not isinstance(total, int) or isinstance(total, bool):
                        raise DocReadError(READ_FAILED)  # cannot tell "absent" from "unread"
                    if page >= total:
                        return False, None
                    page += 1
        except (httpx.HTTPError, httpx.InvalidURL, UrlGuardError, ValueError):
            raise DocReadError(READ_FAILED) from None
        raise DocReadError(READ_FAILED)
