"""Shared frame of the write-back services (plan 55 / plan 57).

The pieces every write flow needs: outcome and refusal codes, the answer type,
the per-document busy check, the committed-outcome ``_finish``, the db3-guarded
write connection lookup, the deadline clock and the stage-and-push step. Moved
out of ``service.py`` unchanged so the plan 55 flows and the plan 57 primitive
service share one implementation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modules.autocount.models import AcCompany, AcWriteAction
from modules.autocount.provider import PROVIDER_KEY
from modules.autocount.repositories import ConnectionRepository
from modules.autocount.write_back.client import AutoCountWriteClient
from modules.autocount.write_back.guard import WriteNotAllowed, assert_write_allowed
from modules.autocount.write_back.reader import AutoCountDocReader
from modules.autocount.write_back.repository import (
    StagedDocRepository,
    WriteActionRepository,
)
from modules.autocount.write_back.staging import DocStager

Doc = Dict[str, Any]
_MAX_TEXT = 2000

OUTCOME_DONE = "done"
OUTCOME_REFUSED = "refused"
OUTCOME_MISMATCH = "mismatch"
OUTCOME_PENDING = "pending_verification"
OUTCOME_VENDOR_ERROR = "vendor_error"

WRITE_DISABLED = "WRITE_DISABLED"
# An in_flight / pending_verification action blocks its document for this long;
# after it the document is free again (the old row is marked pending_verification).
BUSY_WINDOW_SECONDS = 600
# Overall budget of one action (all vendor calls together); at most half the busy window.
ACTION_DEADLINE_SECONDS = 270.0
DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
SO_LOCATION_AMBIGUOUS = "SO_LOCATION_AMBIGUOUS"

INTERNAL_ERROR = "INTERNAL_ERROR"
VENDOR_UNSUPPORTED = "VENDOR_UNSUPPORTED"
LOCATION_NOT_MOVED = "LOCATION_NOT_MOVED"
ROW_ALREADY_AT_LOCATION = "ROW_ALREADY_AT_LOCATION"
DOC_KIND_MISMATCH = "DOC_KIND_MISMATCH"
DOC_BUSY = "DOC_BUSY"
DOC_UNKNOWN = "DOC_UNKNOWN"
DOC_STALE = "DOC_STALE"


@dataclass
class WriteActionResult:
    """What a flow answered. ``document`` is the read-back document on ``done``."""

    action_id: Optional[str]
    outcome: str
    error_code: Optional[str] = None
    message: str = ""
    document: Optional[Doc] = None


class _Stop(Exception):
    """Internal early exit carrying a finished result."""

    def __init__(self, result: WriteActionResult) -> None:
        self.result = result



def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))

def _doc_date(raw: Optional[Doc]) -> Optional[date]:
    text = str((raw or {}).get("DocDate") or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None

def _lines(raw: Optional[Doc]) -> List[Doc]:
    lines = (raw or {}).get("_lines")
    return [r for r in lines if isinstance(r, dict)] if isinstance(lines, list) else []

def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _dec(a) == _dec(b)
    return a == b

def _safe_body(body: Any) -> Doc:
    if isinstance(body, (dict, list)):
        return body  # type: ignore[return-value]
    return {"text": str(body)[:_MAX_TEXT]}


class WriteFrame:
    def __init__(
        self,
        db: Session,
        *,
        client_factory: Optional[Callable[[str], AutoCountWriteClient]] = None,
        reader_factory: Optional[Callable[[str], AutoCountDocReader]] = None,
        sink_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.db = db
        self.actions = WriteActionRepository(db)
        self.staged = StagedDocRepository(db)
        self.connections = ConnectionRepository(db)
        self._client_factory = client_factory or AutoCountWriteClient
        self._reader_factory = reader_factory or AutoCountDocReader
        self._sink_factory = sink_factory
        self._deadline = 0.0
        self._put_sent = False

    def _expired(self) -> bool:
        return time.monotonic() > self._deadline

    def _check_deadline(self, row: AcWriteAction) -> None:
        """No vendor call after the action's overall deadline: refused before any
        write was sent, pending verification after."""
        if time.monotonic() <= self._deadline:
            return
        if self._put_sent:
            raise _Stop(self._finish(row, OUTCOME_PENDING, DEADLINE_EXCEEDED))
        raise self._refuse(row, DEADLINE_EXCEEDED)

    def _check_not_busy(
        self, row: AcWriteAction, tenant_id: str, company_id: str, doc_key: int
    ) -> None:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=BUSY_WINDOW_SECONDS)
        if self.actions.expire_stale_in_flight(tenant_id, company_id, doc_key, window_start):
            self.db.commit()
        if self.actions.has_open(tenant_id, company_id, doc_key, window_start):
            raise self._refuse(row, DOC_BUSY)

    def _finish(
        self,
        row: AcWriteAction,
        outcome: str,
        code: Optional[str] = None,
        *,
        document: Optional[Doc] = None,
        message: str = "",
    ) -> WriteActionResult:
        """Record the outcome (committed) and return the answer."""
        row.outcome = outcome
        row.error_code = code
        self.db.commit()
        return WriteActionResult(row.id, outcome, code, message, document)

    def _refuse(self, row: AcWriteAction, code: str, message: str = "") -> _Stop:
        return _Stop(self._finish(row, OUTCOME_REFUSED, code, message=message))

    def _resolve_write_base_url(self, company: AcCompany) -> "Tuple[Optional[str], Optional[Tuple[str, str]]]":
        """``(url, None)`` or ``(None, (code, message))``: the company's write
        connection URL resolved WITH tenant_id and the db3 guard applied."""
        conn = None
        if company.is_active and company.write_connection_id:
            conn = self.connections.get_for_provider(
                company.tenant_id, company.write_connection_id, PROVIDER_KEY
            )
        if conn is None or not conn.is_active:
            return None, (WRITE_DISABLED, "")
        base_url = str((conn.config_json or {}).get("baseUrl") or "")
        try:
            assert_write_allowed(base_url)
        except WriteNotAllowed as exc:
            return None, (exc.code, str(exc))
        return base_url, None

    def _write_base_url(self, row: AcWriteAction, company: AcCompany) -> str:
        """The write URL, or a ``_Stop`` (refused) carrying why not."""
        base_url, refusal = self._resolve_write_base_url(company)
        if base_url is None:
            code, message = refusal  # type: ignore[misc]
            raise self._refuse(row, code, message)
        return base_url

    def _stage(self, company: AcCompany, kind: str, doc: Doc) -> None:
        """Stage the verified read-back and push it once (never changes the outcome)."""
        DocStager(self.db, self._sink_factory).stage_and_push(company, doc, kind)
