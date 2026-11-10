"""Per-HTTP-call log of the write layer (plan 61 section 4.8, owner ruling R3, AC-61-60..64).

``AutoCountWriteClient`` and ``AutoCountDocReader`` call ``CallLog.record`` once per
request (or once per refused request: the allowlist guard ran first and nothing was
sent). The caller hands the log in explicitly (``attach_call_log``) with a
``CallContext``: tenant, company, actor, request id, operation / action, document.

Durable and harmless: each row is written through the ``AcApiCallLog`` model on its
OWN short session (``Session(bind=db.get_bind())``, committed at once), so it survives
a rollback of the business transaction; any failure to write it is swallowed (the app
logger gets the code only, never a body). Never stored: API keys, header values, the
base URL host (``book`` is the URL's last path segment, ``path`` the vendor path plus
query as sent).
"""

from __future__ import annotations

import logging
import string
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from modules.autocount.models import AcApiCallLog

logger = logging.getLogger("foundryx.autocount")

BODY_CAP = 32768
ACTOR_SYSTEM = "system"
ACTOR_RUNNER = "runner"

OK = "ok"
HTTP_ERROR = "http_error"
TIMEOUT = "timeout"
CONNECT_ERROR = "connect_error"
GUARD_REFUSED = "guard_refused"

# The caller's optional correlation header (contract 57 section 8); else the Idempotency-Key.
REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_MAX = 128
_PRINTABLE = frozenset(string.printable) - frozenset("\t\n\r\x0b\x0c")


def clean_request_id(value: Optional[str]) -> Optional[str]:
    """The caller's ``X-Request-ID`` when it is 1..128 printable characters, else None."""
    if not value or len(value) > REQUEST_ID_MAX or not all(c in _PRINTABLE for c in value):
        return None
    return value


def request_id_of(x_request_id: Optional[str], idempotency_key: Optional[str]) -> Optional[str]:
    """``X-Request-ID`` when valid, else the ``Idempotency-Key`` (same 1..128 printable rule)."""
    return clean_request_id(x_request_id) or clean_request_id(idempotency_key)


@dataclass
class CallContext:
    """Who and what one call belongs to; the frame fills ``action_id`` / ``doc_no`` as
    they become known (the same object is shared by the client and the reader)."""

    tenant_id: str
    company_id: str
    actor: str = ACTOR_SYSTEM
    request_id: Optional[str] = None
    operation_id: Optional[str] = None
    action_id: Optional[str] = None
    doc_type: Optional[str] = None
    doc_no: Optional[str] = None
    doc_key: Optional[int] = None


def book_of(base_url: str) -> Optional[str]:
    """The base URL's last path segment (``db3``), never the host."""
    segments = [s for s in (urlsplit(base_url).path or "").split("/") if s]
    return segments[-1][:64] if segments else None


def vendor_path(base_url: str, raw_path: str) -> str:
    """``raw_path`` (path + query as sent) without the base URL's own path prefix."""
    prefix = (urlsplit(base_url).path or "").rstrip("/")
    return raw_path[len(prefix):] if prefix and raw_path.startswith(prefix) else raw_path


class CallLog:
    def __init__(self, bind: "Engine | Connection", context: CallContext) -> None:
        self._bind = bind
        self.context = context

    def started(self) -> "tuple[datetime, float]":
        return datetime.now(timezone.utc), time.monotonic()

    def record(
        self, *, base_url: str, method: str, path: str, started: "tuple[datetime, float]",
        request_json: Any = None, status: Optional[int] = None, body: Optional[str] = None,
        outcome: str, error_code: Optional[str] = None,
    ) -> None:
        """Write one row on its own session; never raises."""
        try:
            at, t0 = started
            text = body if isinstance(body, str) else None
            ctx = self.context
            row = AcApiCallLog(
                tenant_id=ctx.tenant_id, company_id=ctx.company_id, created_at=at, actor=ctx.actor,
                request_id=ctx.request_id, operation_id=ctx.operation_id, action_id=ctx.action_id,
                book=book_of(base_url), method=method, path=path, doc_type=ctx.doc_type,
                doc_no=ctx.doc_no, doc_key=ctx.doc_key,
                request_json=request_json if method in ("POST", "PUT") else None,
                response_status=status, response_body=text[:BODY_CAP] if text is not None else None,
                response_truncated=bool(text is not None and len(text) > BODY_CAP),
                duration_ms=max(int((time.monotonic() - t0) * 1000), 0), outcome=outcome,
                error_code=error_code,
            )
            session = Session(bind=self._bind)
            try:
                session.add(row)
                session.commit()
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001 - the log never breaks the call
            logger.warning("autocount call log write failed (%s)", type(exc).__name__)


def give_request_id(target: Any, request_id: Optional[str]) -> None:
    """Hand the caller's request id to a write service (any object without the hook is left alone)."""
    use = getattr(target, "use_request_id", None)
    if callable(use):
        use(request_id)


def attach_call_log(target: Any, log: Optional[CallLog]) -> Any:
    """Hand ``log`` to a client or reader (or a wrapper that forwards it); returns ``target``."""
    attach = getattr(target, "attach_call_log", None)
    if log is not None and callable(attach):
        attach(log)
    return target
