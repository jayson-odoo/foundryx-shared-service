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
from typing import Optional
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
    from ..canonical.masters import ENTITY_BRANCH

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
