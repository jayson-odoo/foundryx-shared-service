"""One place that turns a database error into fixed, value-free text.

The text holds the caller's sentence, the SQLAlchemy error class and, when the
driver supplies them, the error code and the constraint name. The driver's
message, detail, statement and bound values never ride along: they can carry
tenant data. Callers log the full exception separately.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

__all__ = ["db_error_text", "is_db_error", "error_code_of", "constraint_of"]

_TOKEN_MAX = 64


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
    orig = getattr(exc, "orig", None)
    if orig is None:
        return None
    try:
        code = _clean(getattr(orig, "pgcode", None))
        if code:
            return code
        args = getattr(orig, "args", None)
        if args and isinstance(args[0], int) and not isinstance(args[0], bool):
            return str(args[0])
    except Exception:  # noqa: BLE001 - odd driver shapes never raise
        return None
    return None


def constraint_of(exc: BaseException) -> Optional[str]:
    orig = getattr(exc, "orig", None)
    if orig is None:
        return None
    try:
        diag = getattr(orig, "diag", None)
        return _clean(getattr(diag, "constraint_name", None))
    except Exception:  # noqa: BLE001
        return None


def db_error_text(exc: BaseException, what: str) -> str:
    detail = type(exc).__name__
    code = error_code_of(exc)
    if code:
        detail += f", code {code}"
    constraint = constraint_of(exc)
    if constraint:
        detail += f", constraint {constraint}"
    return f"{what} ({detail})."
