"""Plan 73 (round 2): every PO / SPO write is read-modify-write from the AutoCount database.

hapi's PO GET blanks stored values (Remark2-4 = Remark1, no FurtherDescription), so a body built from the bare GET
would write "" over them. A ``DocDbSource`` reads the stored header and row values; ``attach_db_doc`` lays them over
the GET document and ``NotesReader`` does that on every PO / SPO read of the frame, so every builder, snapshot and
read-back sees the stored values. A read that fails (or no source) is unknown: the rows then carry no
``FurtherDescription`` and every builder refuses (``AUTOCOUNT_DB_UNREAD``) before any PUT. A Further Description the
vendor GET itself carries is NOT trusted alone: it is dropped when the database could not be read.

* ``SqlDocDb``: two bound, read-only SELECTs through the company's optional line-notes connection (a same-tenant
  ``sql_database`` connection, never an entity source).

Nothing here logs a stored value or a credential.
"""

from __future__ import annotations

import copy
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional, Protocol

import sqlalchemy as sa
from cryptography.fernet import InvalidToken

from app.secrets import decrypt_secret
from modules.autocount.sql_source.runtime import RUNTIME, SqlSourceRuntime
from modules.autocount.write_back.payloads import (
    EDIT_HEADER_KEYS,
    FURTHER_DESC,
    HEADER_KEYS,
    ROW_KEYS,
)

logger = logging.getLogger("foundryx.autocount")

Doc = Dict[str, Any]
NOTES_KINDS = ("PO", "SPO")
DB_READ_TIMEOUT_SECONDS = 20
# The header columns kept from the database, and the row columns (the builders force the transfer-option columns
# and the key itself, so those are never taken from the database).
DB_HEADER_KEYS = tuple(dict.fromkeys(HEADER_KEYS + EDIT_HEADER_KEYS))
DB_ROW_KEYS = tuple(k for k in ROW_KEYS if k not in ("DtlKey", "FullTransferOption", "FullTransferFromDocList"))
_HEADER_SELECT = sa.text("SELECT * FROM PO WHERE DocKey = :k AND DocNo = :n")
_ROWS_SELECT = sa.text("SELECT * FROM PODTL WHERE DocKey = :k")


class DocDbSource(Protocol):
    def read(self, kind: str, doc: Mapping[str, Any]) -> Optional[Dict[str, Any]]: ...


def _wire(value: Any) -> Any:
    """A database value in hapi's wire shape; None / bool / bytes are not carried (the GET value stays)."""
    if value is None or isinstance(value, (bool, bytes, bytearray, memoryview)):
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00")
    return value


def _kept(record: Mapping[str, Any], keys: tuple) -> Dict[str, Any]:
    canon = {k.lower(): k for k in keys}
    out: Dict[str, Any] = {}
    for name, value in record.items():
        key = canon.get(str(name).lower())
        wire = _wire(value)
        if key is not None and wire is not None:
            out[key] = wire
    return out


class SqlDocDb:
    """``SELECT * FROM PO WHERE DocKey = :k AND DocNo = :n`` (exactly one row) and ``SELECT * FROM PODTL WHERE
    DocKey = :k`` (its DtlKey set equal to the document's), through a ``sql_database`` connection resolved WITH
    tenant_id by the caller; read-only, time-boxed. Any error, an undecryptable credential or a mismatch is
    unknown (None)."""

    def __init__(self, connection: Any, runtime: SqlSourceRuntime = RUNTIME) -> None:
        self._connection = connection
        self._runtime = runtime

    def read(self, kind: str, doc: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        if kind not in NOTES_KINDS or doc.get("DocKey") in (None, ""):
            return None
        keys = {row.get("DtlKey") for row in doc.get("Details") or []}
        try:
            credentials: Dict[str, Any] = {}
            if self._connection.credentials_json:
                credentials = decrypt_secret(self._connection.credentials_json)
            with self._runtime.readonly_connection(
                self._connection.id, self._connection.config_json or {}, credentials,
                timeout_s=DB_READ_TIMEOUT_SECONDS,
            ) as conn:
                headers = [dict(r) for r in conn.execute(
                    _HEADER_SELECT, {"k": doc["DocKey"], "n": doc.get("DocNo")}).mappings().fetchall()]
                details = [dict(r) for r in conn.execute(_ROWS_SELECT, {"k": doc["DocKey"]}).mappings().fetchall()]
        except InvalidToken:
            logger.warning("autocount db read: the connection credentials cannot be decrypted")
            return None
        except Exception as exc:  # noqa: BLE001 - never the driver text: it can hold a host or a value
            logger.warning("autocount db read failed (%s)", type(exc).__name__)
            return None
        if len(headers) != 1:
            return None
        rows: Dict[Any, Dict[str, Any]] = {}
        for record in details:
            lowered = {str(k).lower(): v for k, v in record.items()}
            dtl = lowered.get("dtlkey")
            if dtl is None or dtl in rows:
                return None
            row = _kept(record, DB_ROW_KEYS)
            row[FURTHER_DESC] = lowered.get("furtherdescription") if isinstance(
                lowered.get("furtherdescription"), str) else ""  # a NULL note is an empty one
            rows[dtl] = row
        if set(rows) != keys:
            return None  # a row the database does not know, or one the document read does not have
        return {"header": _kept(headers[0], DB_HEADER_KEYS), "rows": rows}


def attach_db_doc(doc: Doc, db: Optional[Mapping[str, Any]]) -> Doc:
    """``doc`` with the stored header values (``DB_HEADER_KEYS``) and, per row, the stored row values and
    FurtherDescription laid over the GET values; the input is not mutated. Unknown (None) returns it unchanged."""
    if db is None:
        return doc
    out = copy.deepcopy(doc)
    for key, value in (db.get("header") or {}).items():
        if key in DB_HEADER_KEYS:
            out[key] = value
    stored_rows = db.get("rows") or {}
    for row in out.get("Details") or []:
        stored = stored_rows.get(row.get("DtlKey"))
        if stored is None:
            row.pop(FURTHER_DESC, None)  # not read from the database: unknown, whatever the GET carried
            continue
        for key, value in stored.items():
            if key in DB_ROW_KEYS or key == FURTHER_DESC:
                row[key] = value
    return out


def _unread(doc: Doc) -> Doc:
    """The GET document with no Further Description: the database could not be read, the vendor's own is not trusted."""
    if not any(FURTHER_DESC in row for row in doc.get("Details") or []):
        return doc
    out = copy.deepcopy(doc)
    for row in out.get("Details") or []:
        row.pop(FURTHER_DESC, None)
    return out


class NotesReader:
    """A document reader that overlays the stored values on every PO / SPO it returns; everything else (other kinds,
    other attributes, call log and header setters) is the wrapped reader's own."""

    def __init__(self, inner: Any, source: Optional[DocDbSource]) -> None:
        self._inner = inner
        self._source = source

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _enrich(self, kind: str, doc: Doc) -> Doc:
        if kind not in NOTES_KINDS or not isinstance(doc, dict):
            return doc
        stored = self._source.read(kind, doc) if self._source is not None else None
        return attach_db_doc(doc, stored) if stored is not None else _unread(doc)

    def get_document(self, kind: str, doc_key: int, doc_date: Any, doc_no: Optional[str] = None) -> Doc:
        return self._enrich(kind, self._inner.get_document(kind, doc_key, doc_date, doc_no=doc_no))

    def get_by_doc_no(self, kind: str, doc_no: str) -> Doc:
        return self._enrich(kind, self._inner.get_by_doc_no(kind, doc_no))
