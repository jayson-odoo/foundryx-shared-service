"""One place that turns a database error into fixed, value-free text.

The text holds the caller's sentence, the SQLAlchemy error class and, when the
driver supplies them, the error code and the constraint name. The driver's
message, detail, statement and bound values never ride along: they can carry
tenant data. Callers log the full exception separately.
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

__all__ = ["db_error_text", "stored_error_text", "db_error_in", "is_db_error", "error_code_of", "constraint_of"]

_TOKEN_MAX = 64
_SQLSTATE = re.compile(r"^[0-9A-Z]{5}$")


def is_db_error(exc: BaseException) -> bool:
    return isinstance(exc, SQLAlchemyError)


def _clean(value: object) -> Optional[str]:
    """A short single-token string, or None. Keeps codes/names, drops prose."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, bytes):
        return None
    text = str(value).strip()
    if not text or len(text) > _TOKEN_MAX or any(ch.isspace() for ch in text):
        return None
    return text


def error_code_of(exc: BaseException) -> Optional[str]:
    try:
        orig = getattr(exc, "orig", None)
        if orig is None:
            return None
        code = _clean(getattr(orig, "pgcode", None))
        if code and _SQLSTATE.match(code):
            return code
        args = getattr(orig, "args", None)
        head = args[0] if args else None
        if isinstance(head, (tuple, list)) and head:
            head = head[0]  # pymssql nests (code, message)
        if isinstance(head, int) and not isinstance(head, bool):
            return str(head)
    except Exception:  # noqa: BLE001 - odd driver shapes never raise
        return None
    return None


def constraint_of(exc: BaseException) -> Optional[str]:
    try:
        orig = getattr(exc, "orig", None)
        if orig is None:
            return None
        diag = getattr(orig, "diag", None)
        return _clean(getattr(diag, "constraint_name", None))
    except Exception:  # noqa: BLE001
        return None


def db_error_text(exc: BaseException, what: str, *, with_constraint: bool = True) -> str:
    detail = type(exc).__name__
    code = error_code_of(exc)
    if code:
        detail += f", code {code}"
    constraint = constraint_of(exc) if with_constraint else None
    if constraint:
        detail += f", constraint {constraint}"
    return f"{what} ({detail})."


def db_error_in(exc: BaseException) -> Optional[BaseException]:
    """The database error behind ``exc`` (itself or through ``__cause__``), else None."""
    seen = 0
    cur: Optional[BaseException] = exc
    while cur is not None and seen < 8:
        if is_db_error(cur):
            return cur
        cur = cur.__cause__
        seen += 1
    return None


def stored_error_text(exc: BaseException, what: str, fallback: Optional[str] = None) -> str:
    """Text for an error that is stored or emailed. A database error becomes
    ``db_error_text`` under the caller's sentence; any other error keeps the
    caller's own text (``fallback``, default ``"<what>: <exc>"``)."""
    db_exc = db_error_in(exc)
    if db_exc is not None:
        return db_error_text(db_exc, what)
    return fallback if fallback is not None else f"{what}: {exc}"
