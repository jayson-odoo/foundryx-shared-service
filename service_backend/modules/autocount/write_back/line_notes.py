"""Plan 73: the Further Description (FD) of every PO / SPO line, read from outside hapi.

hapi's PO GET never returns ``FurtherDescription``, and a write that re-sends or re-adds a row without it
loses the note (RTF, pictures included). One interface, ``notes(kind, doc) -> {DtlKey: FD} | None`` (None =
unknown, fail closed), three implementations:

* ``HapiLineNotes``: the FD the GET rows carry themselves (once the vendor adds the key).
* ``SqlLineNotes``: a read-only ``SELECT`` on the company's optional line-notes connection (a same-tenant
  ``sql_database`` connection, never an entity source).
* ``CompositeLineNotes``: the first source that knows.

``NotesReader`` wraps the frame's document reader and sets ``FurtherDescription`` on every PO / SPO row it
returns, so every builder, snapshot and read-back sees it. Nothing here logs an FD or a credential.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, Mapping, Optional, Protocol

import sqlalchemy as sa
from cryptography.fernet import InvalidToken

from app.secrets import decrypt_secret
from modules.autocount.sql_source.runtime import (
    RUNTIME,
    SqlSourceRuntime,
)
from modules.autocount.write_back.payloads import FURTHER_DESC

logger = logging.getLogger("foundryx.autocount")

Doc = Dict[str, Any]
NOTES_KINDS = ("PO", "SPO")
LINE_NOTES_TIMEOUT_SECONDS = 20
_SELECT = sa.text("SELECT DtlKey, FurtherDescription FROM PODTL WHERE DocKey = :k")


class LineNotesSource(Protocol):
    def notes(self, kind: str, doc: Mapping[str, Any]) -> Optional[Dict[Any, str]]: ...


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


class HapiLineNotes:
    """The FD the GET rows carry; one row without the key makes the whole document unknown."""

    def notes(self, kind: str, doc: Mapping[str, Any]) -> Optional[Dict[Any, str]]:
        rows = doc.get("Details") or []
        if any(FURTHER_DESC not in row for row in rows):
            return None
        return {row.get("DtlKey"): _text(row.get(FURTHER_DESC)) for row in rows}


class SqlLineNotes:
    """``SELECT DtlKey, FurtherDescription FROM PODTL WHERE DocKey = :k`` through a ``sql_database``
    connection (resolved WITH tenant_id by the caller), read-only and time-boxed. Any error, a row the
    query did not return or an undecryptable credential is unknown (None)."""

    def __init__(self, connection: Any, runtime: SqlSourceRuntime = RUNTIME) -> None:
        self._connection = connection
        self._runtime = runtime

    def notes(self, kind: str, doc: Mapping[str, Any]) -> Optional[Dict[Any, str]]:
        if kind not in NOTES_KINDS or doc.get("DocKey") in (None, ""):
            return None
        keys = [row.get("DtlKey") for row in doc.get("Details") or []]
        try:
            credentials: Dict[str, Any] = {}
            if self._connection.credentials_json:
                credentials = decrypt_secret(self._connection.credentials_json)
            with self._runtime.readonly_connection(
                self._connection.id, self._connection.config_json or {}, credentials,
                timeout_s=LINE_NOTES_TIMEOUT_SECONDS,
            ) as conn:
                found = {r[0]: _text(r[1]) for r in conn.execute(_SELECT, {"k": doc["DocKey"]}).fetchall()}
        except InvalidToken:
            logger.warning("autocount line notes: the connection credentials cannot be decrypted")
            return None
        except Exception as exc:  # noqa: BLE001 - never the driver text: it can hold a host or a value
            logger.warning("autocount line notes read failed (%s)", type(exc).__name__)
            return None
        if any(key not in found for key in keys):
            return None  # a row the database does not know: unknown, never a guessed blank
        return {key: found[key] for key in keys}


class CompositeLineNotes:
    """The first source that knows the document's notes; None when none does."""

    def __init__(self, *sources: Optional[LineNotesSource]) -> None:
        self._sources = [s for s in sources if s is not None]

    def notes(self, kind: str, doc: Mapping[str, Any]) -> Optional[Dict[Any, str]]:
        for source in self._sources:
            found = source.notes(kind, doc)
            if found is not None:
                return found
        return None


def attach_line_notes(doc: Doc, notes: Optional[Mapping[Any, str]]) -> Doc:
    """``doc`` with ``FurtherDescription`` on every row ("" for a DtlKey the notes do not hold); the input
    is not mutated. Unknown notes (None) return the document unchanged."""
    if notes is None:
        return doc
    out = copy.deepcopy(doc)
    for row in out.get("Details") or []:
        row[FURTHER_DESC] = _text(notes.get(row.get("DtlKey")))
    return out


class NotesReader:
    """A document reader that sets the FD on every row of a PO / SPO; everything else (other kinds, other
    attributes, call log and header setters) is the wrapped reader's own."""

    def __init__(self, inner: Any, source: LineNotesSource) -> None:
        self._inner = inner
        self._source = source

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _enrich(self, kind: str, doc: Doc) -> Doc:
        if kind not in NOTES_KINDS or not isinstance(doc, dict):
            return doc
        return attach_line_notes(doc, self._source.notes(kind, doc))

    def get_document(self, kind: str, doc_key: int, doc_date: Any, doc_no: Optional[str] = None) -> Doc:
        return self._enrich(kind, self._inner.get_document(kind, doc_key, doc_date, doc_no=doc_no))

    def get_by_doc_no(self, kind: str, doc_no: str) -> Doc:
        return self._enrich(kind, self._inner.get_by_doc_no(kind, doc_no))
