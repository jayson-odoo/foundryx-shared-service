"""The AutoCount "book" a vendor connection points at (sprint-5/14, D25).

A book is the last path segment of an open connection's base URL
(``https://hapi.sorento.cc.cd/api/db1`` -> ``db1``). It qualifies the
identity of the doc feed's documents (``{book}:DO:{DocKey}``) and of the
``branch`` master entity (``{book}:BR:{AccNo}:{BranchCode}``), and rides on
every Sorento 2.7 ingest body as the top-level ``book``.

Pure and import-light on purpose: ``doc_feed.runner``, ``services.
company_service`` (the sink factory) and ``http_source.source`` all import it.
"""
from __future__ import annotations

import re
from typing import Callable, List, Optional
from urllib.parse import urlsplit

_BOOK_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


def derive_book(base_url: str) -> Optional[str]:
    """AC-14-02/13.2 - the last non-empty path segment of an open connection's
    base URL, when it matches ``^[A-Za-z0-9_-]{1,20}$``; ``None`` otherwise."""
    path = urlsplit(base_url or "").path
    segments = [s for s in path.split("/") if s]
    if not segments:
        return None
    candidate = segments[-1]
    return candidate if _BOOK_RE.match(candidate) else None


def identity_scope(
    db, tenant_id: str, company, entity_type: str, source_config: Optional[dict]
) -> str:
    """The string a task's mapping engine / HTTP source hands to its identity
    function as the "database name" (the company-qualifier of a master's
    ``source_ref``).

    Every entity qualifies by the company's AutoCount ``database_name`` -
    EXCEPT ``branch`` (sprint-5/14 section 11, D25), whose CRM-side identity is
    ``{book}:BR:{AccNo}:{BranchCode}``: it qualifies by the BOOK of the task's
    own HTTP connection (``''`` when that connection cannot be resolved, which
    the identity function turns into a named field error rather than guessing).
    """
    # Lazy imports: this module is imported by ``doc_feed.runner`` and the
    # sink factory, which must stay cycle-free.
    from ..canonical.documents import LINKED_DOCUMENT_REF_CODES
    from ..canonical.masters import ENTITY_BRANCH

    if entity_type in LINKED_DOCUMENT_REF_CODES:
        return linked_document_book(db, tenant_id, company)
    if entity_type != ENTITY_BRANCH:
        return getattr(company, "database_name", "") or ""
    from ..provider import PROVIDER_KEY
    from ..repositories import ConnectionRepository

    connection_id = str((source_config or {}).get("connectionId") or "").strip()
    if not connection_id:
        return ""
    conn = ConnectionRepository(db).get_for_provider(tenant_id, connection_id, PROVIDER_KEY)
    if conn is None:
        return ""
    return derive_book(str((conn.config_json or {}).get("baseUrl") or "")) or ""


def linked_document_book(db, tenant_id: str, company) -> str:
    """AC-CANCEL-PULL - the book the four linked documents (Cancel SO/PO,
    Consignment, Consignment Return) are filed under on the CRM: the SAME
    book as this company's own doc feeds (its Delivery Orders feed, else its
    Goods Receive Notes feed), so they land beside its DOs. ``''`` when the
    company has no doc feed with a book - the identity function turns that
    into a named field error rather than guessing. Resolved with the
    company's OWN ``tenant_id`` (the polymorphic-stored-id rule)."""
    from ..doc_feed.constants import FEED_DELIVERY_ORDERS, FEED_GOODS_RECEIVE_NOTES
    from ..repositories.doc_feed_repository import DocFeedRepository

    company_id = getattr(company, "id", None)
    if not company_id or db is None:
        return ""
    repo = DocFeedRepository(db)
    for feed in (FEED_DELIVERY_ORDERS, FEED_GOODS_RECEIVE_NOTES):
        row = repo.get(tenant_id, company_id, feed)
        book = str(getattr(row, "book", "") or "").strip() if row is not None else ""
        if book:
            return book
    return ""


def billing_link_book(db, tenant_id: str, company, entity_type: str) -> str:
    """Plan 32 (D6) - the book a billing line sourced from a delivery order is
    linked under (`{book}:DO:{DocKey}:{DtlKey}`, contract 14.3): the SAME
    doc-feed book the DO feed files its documents under. Only an invoice or a
    cash sale can come from a DO; every other entity answers ``''``. The
    header identity of a billing document is unaffected (it stays the
    company's database name, ``identity_scope``)."""
    from ..canonical.documents import BILLING_DO_LINKED_ENTITY_TYPES

    if entity_type not in BILLING_DO_LINKED_ENTITY_TYPES:
        return ""
    from ..doc_feed.constants import FEED_DELIVERY_ORDERS
    from ..repositories.doc_feed_repository import DocFeedRepository

    company_id = getattr(company, "id", None)
    if not company_id or db is None:
        return ""
    # The DELIVERY ORDERS feed's own book only (never the GRN feed's): the CRM
    # finds the DO line by (book, doc_key, dtl_key) under the book its DO
    # was ingested with.
    row = DocFeedRepository(db).get(tenant_id, company_id, FEED_DELIVERY_ORDERS)
    return str(getattr(row, "book", "") or "").strip() if row is not None else ""


def billing_do_doc_keys(
    db, tenant_id: str, company, entity_type: str,
) -> Optional[Callable[[str], List[int]]]:
    """Lane SS-BILLING-DO-API - the DO-number -> DocKeys lookup a billing
    line sourced from a delivery order resolves its DO through (owner ruling
    25 Oct: the AutoCount admin will not grant ``DODTL``, so the line query
    no longer joins it).

    Reads the DO feed's own ledger (``ac_doc_feed_ledger``: book, doc_key,
    doc_no of every DO the CRM holds from us), under the SAME book
    ``billing_link_book`` mints the ref with, so a link can only ever point
    at a DO the CRM actually has. Vanished DOs (deleted in AutoCount) are
    excluded. Returns every match - the mapping engine links on exactly one
    and fails the line otherwise. ``None`` for an entity that never links a
    DO, or a company with no Delivery Orders feed book (the engine already
    names that case). Tenant AND company scoped (polymorphic-stored-id rule).
    No vendor I/O: the hapi DO doors are by-day only, and an IV line does not
    carry its DO's date, so there is nothing exact to fetch on demand."""
    book = billing_link_book(db, tenant_id, company, entity_type)
    if not book:
        return None
    from ..doc_feed.constants import FEED_DELIVERY_ORDERS
    from ..repositories.doc_feed_repository import DocFeedLedgerRepository

    repo = DocFeedLedgerRepository(db)
    company_id = company.id

    def lookup(doc_no: str) -> List[int]:
        return repo.live_doc_keys_for_doc_no(
            tenant_id, company_id, FEED_DELIVERY_ORDERS, book, doc_no,
        )

    return lookup
