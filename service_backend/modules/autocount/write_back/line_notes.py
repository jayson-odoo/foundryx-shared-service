"""Plan 73 (round 2): every PO / SPO write is read-modify-write from the AutoCount database.

hapi's PO GET blanks stored values (Remark2-4 = Remark1, no FurtherDescription), so a body built from the bare GET
would write "" over them. A ``DocDbSource`` reads the stored header and row values; ``attach_db_doc`` lays them over
the GET document and ``NotesReader`` does that on every PO / SPO read of the frame, so every builder, snapshot and
read-back sees the stored values. A source that is set but whose read fails is unknown: the document is marked
unread and every builder refuses (``AUTOCOUNT_DB_UNREAD``) before any PUT; a Further Description the vendor GET itself
carries is NOT trusted then. NO source set is legacy mode (crew ruling s20): the document is marked legacy, nothing is
refused and no Further Description is re-sent.

* ``SqlDocDb``: two bound, read-only SELECTs through the company's optional line-notes connection (a same-tenant
  ``sql_database`` connection, never an entity source).

Nothing here logs a stored value or a credential.
"""

from __future__ import annotations

import copy
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Protocol

import sqlalchemy as sa
from cryptography.fernet import InvalidToken

from app.secrets import decrypt_secret
from modules.autocount.sql_source.runtime import RUNTIME, SqlSourceRuntime
from modules.autocount.write_back import payloads
from modules.autocount.write_back.payloads import (
    DB_LEGACY_MARKER,
    DB_UNREAD_MARKER,
    HAPI_FD_MARKER,
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
# DocKey and DocNo are the request's own identity: the PUT keeps the key and number it was asked for.
DB_HEADER_KEYS = tuple(k for k in dict.fromkeys(HEADER_KEYS + EDIT_HEADER_KEYS) if k not in ("DocKey", "DocNo"))
DB_ROW_KEYS = tuple(k for k in ROW_KEYS if k not in ("DtlKey", "FullTransferOption", "FullTransferFromDocList"))
# Static statements, bound parameters only. The rows read is SELECT * (no sensitive columns there); the columns are
# whitelisted after the read.
# The header read selects only the fields SS writes (never every column of the table): a static, bracket-quoted list.
DB_HEADER_COLUMNS = (
    "DocKey", "DocNo", "CreditorCode", "CreditorName", "Ref", "Description", "DisplayTerm", "PurchaseAgent",
    "InvAddr1", "InvAddr2", "InvAddr3", "InvAddr4", "Phone1", "Fax1", "Attention", "BranchCode",
    "DeliverAddr1", "DeliverAddr2", "DeliverAddr3", "DeliverAddr4", "DeliverPhone1", "DeliverFax1", "DeliverContact",
    "CurrencyCode", "CurrencyRate", "Remark1", "Remark2", "Remark3", "Remark4", "RefDocNo", "ShipVia", "ShipInfo",
    "InclusiveTax", "DocDate",
)
_HEADER_SELECT = sa.text(
    "SELECT " + ", ".join(f"[{c}]" for c in DB_HEADER_COLUMNS) + " FROM PO WHERE DocKey = :k AND DocNo = :n"
)
_ROWS_SELECT = sa.text("SELECT * FROM PODTL WHERE DocKey = :k")
# SS-FURTHER-DESC-SEND: the B6 read of a sales order. hapi's SO GET carries no
# FurtherDescription, so the read adds each row's stored text (raw RTF, bytes
# unchanged). Two columns only, and the DocNo must match the document read.
_SO_NOTES_SELECT = sa.text(
    "SELECT d.DtlKey AS DtlKey, d.FurtherDescription AS FurtherDescription "
    "FROM SODTL AS d JOIN SO AS h ON h.DocKey = d.DocKey WHERE d.DocKey = :k AND h.DocNo = :n"
)


# The release guard's probes: one row of each table, nothing read from it (SQL Server dialect, like AutoCount itself).
_PROBE_HEADER = sa.text("SELECT TOP 1 DocKey FROM PO")
_PROBE_ROWS = sa.text("SELECT TOP 1 DtlKey FROM PODTL")
PROBE_TIMEOUT_SECONDS = 10


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
    """``SELECT <the written header fields> FROM PO WHERE DocKey = :k AND DocNo = :n`` (exactly one row) and ``SELECT * FROM PODTL WHERE
    DocKey = :k`` (its DtlKey set equal to the document's), through a ``sql_database`` connection resolved WITH
    tenant_id by the caller; read-only, time-boxed. Any error, an undecryptable credential or a mismatch is
    unknown (None)."""

    def __init__(self, connection: Any, runtime: SqlSourceRuntime = RUNTIME) -> None:
        self._connection = connection
        self._runtime = runtime

    def probe(self) -> bool:
        """The release guard: both tables answer a one row read-only SELECT through this connection. Raises on any
        failure (the caller reports a code, never the driver text)."""
        credentials: Dict[str, Any] = {}
        if self._connection.credentials_json:
            credentials = decrypt_secret(self._connection.credentials_json)
        with self._runtime.readonly_connection(
            self._connection.id, self._connection.config_json or {}, credentials, timeout_s=PROBE_TIMEOUT_SECONDS,
        ) as conn:
            conn.execute(_PROBE_HEADER).fetchall()
            conn.execute(_PROBE_ROWS).fetchall()
        return True

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

    def read_so_notes(self, doc: Mapping[str, Any]) -> Optional[Dict[Any, str]]:
        """SS-FURTHER-DESC-SEND: ``{DtlKey: FurtherDescription}`` of one sales order (``_SO_NOTES_SELECT``), the
        text exactly as stored (NULL is ""). None when unknown: any error, an undecryptable credential, no row, or a
        DtlKey twice."""
        if doc.get("DocKey") in (None, ""):
            return None
        try:
            credentials: Dict[str, Any] = {}
            if self._connection.credentials_json:
                credentials = decrypt_secret(self._connection.credentials_json)
            with self._runtime.readonly_connection(
                self._connection.id, self._connection.config_json or {}, credentials,
                timeout_s=DB_READ_TIMEOUT_SECONDS,
            ) as conn:
                records = [dict(r) for r in conn.execute(
                    _SO_NOTES_SELECT, {"k": doc["DocKey"], "n": doc.get("DocNo")}).mappings().fetchall()]
        except InvalidToken:
            logger.warning("autocount db read: the connection credentials cannot be decrypted")
            return None
        except Exception as exc:  # noqa: BLE001 - never the driver text: it can hold a host or a value
            logger.warning("autocount db read failed (%s)", type(exc).__name__)
            return None
        notes: Dict[Any, str] = {}
        for record in records:
            lowered = {str(k).lower(): v for k, v in record.items()}
            dtl = lowered.get("dtlkey")
            if dtl is None or dtl in notes:
                return None
            text = lowered.get("furtherdescription")
            notes[dtl] = text if isinstance(text, str) else ""
        return notes or None


def so_read_notes(source: Any, doc: Mapping[str, Any]) -> Optional[Dict[Any, str]]:
    """``{DtlKey: FurtherDescription}`` of the sales order ``doc`` from the AutoCount DB (NULL is ""), or None when
    unknown: no ``read_so_notes`` on the source, a failed read, or no row at all for the document."""
    reader = getattr(source, "read_so_notes", None)
    return reader(doc) if callable(reader) else None


def attach_so_notes(doc: Doc, source: Optional[Any]) -> Doc:
    """SS-FURTHER-DESC-SEND, B6 read only: ``doc`` (a sales order) with each row's stored FurtherDescription, raw.
    The same three states as a PO read: no source set is legacy (``_legacy``), a read that fails or misses a row of
    the document is unread (``_unread``: no row carries the key), else every row carries its stored text. Never used
    by a write: QT / SO / PO / SPO bodies and Link PO are unchanged. The input is not mutated."""
    if not isinstance(doc, dict):
        return doc
    if source is None:
        return _legacy(doc)
    notes = so_read_notes(source, doc)
    rows = doc.get("Details") or []
    if notes is None or any(row.get("DtlKey") not in notes for row in rows):
        return _unread(doc)
    out = copy.deepcopy(doc)
    for row in out.get("Details") or []:
        row[FURTHER_DESC] = notes[row.get("DtlKey")]
    return out


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


def _legacy(doc: Doc) -> Doc:
    """Legacy mode (no source set): the GET document marked so the builders neither refuse nor require anything.
    When the vendor GET carries FurtherDescription on EVERY row the notes are known and kept as read (marked
    ``HAPI_FD_MARKER``: every re-sent or re-added row carries its note byte for byte); otherwise none is kept, so none
    is ever re-sent."""
    out = copy.deepcopy(doc)
    rows = out.get("Details") or []
    if rows and all(FURTHER_DESC in row for row in rows):
        out[HAPI_FD_MARKER] = True
    else:
        for row in rows:
            row.pop(FURTHER_DESC, None)
    out[DB_LEGACY_MARKER] = True
    return out


def _unread(doc: Doc) -> Doc:
    """The GET document marked unread: the database could not be read, so no PO / SPO body may be built from it, and
    the vendor's own Further Description is not trusted (dropped)."""
    out = copy.deepcopy(doc)
    for row in out.get("Details") or []:
        row.pop(FURTHER_DESC, None)
    out[DB_UNREAD_MARKER] = True
    return out


def stored_fields_changed(
    before: Any, after: Any, *, intended_header: Any = (), intended_fd_rows: Any = (),
) -> List[str]:
    """Plan 73 post-write check: the NAMES of the stored fields that differ between the pre-write document and the
    read-back although the write did not intend to change them. Only when both came from the AutoCount DB (neither is
    marked unread): every ``DB_HEADER_KEYS`` header field except ``intended_header``, and the Further Description of
    every row present in both except ``intended_fd_rows`` (a new row is not in ``before``). The Remark2-4 mirror
    tolerance of the read-back verifiers is deliberately NOT applied: the mirror is what this reports. Never values."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    if (before.get(DB_UNREAD_MARKER) or after.get(DB_UNREAD_MARKER)
            or before.get(DB_LEGACY_MARKER) or after.get(DB_LEGACY_MARKER)):
        return []
    skip = set(intended_header)
    out: List[str] = [
        key for key in DB_HEADER_KEYS
        if key in before and key not in skip and not payloads._same(before.get(key), after.get(key))
    ]
    now = {r.get("DtlKey"): r for r in after.get("Details") or []}
    deliberate = set(intended_fd_rows)
    for row in before.get("Details") or []:
        key = row.get("DtlKey")
        if key in deliberate or key not in now or FURTHER_DESC not in row or FURTHER_DESC not in now[key]:
            continue
        if row[FURTHER_DESC] != now[key][FURTHER_DESC]:
            out.append(f"Details[{key}].{FURTHER_DESC}")
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
        if self._source is None:  # no line notes database set: legacy mode, never a refusal (crew ruling s20)
            return _legacy(doc)
        stored = self._source.read(kind, doc)
        return attach_db_doc(doc, stored) if stored is not None else _unread(doc)

    def get_document(self, kind: str, doc_key: int, doc_date: Any, doc_no: Optional[str] = None) -> Doc:
        return self._enrich(kind, self._inner.get_document(kind, doc_key, doc_date, doc_no=doc_no))

    def get_by_doc_no(self, kind: str, doc_no: str) -> Doc:
        return self._enrich(kind, self._inner.get_by_doc_no(kind, doc_no))
