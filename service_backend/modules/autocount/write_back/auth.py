"""Optional AutoCount API key (plan 63 section 3.1): ONE header builder for every call.

The key lives Fernet-encrypted in the connection's ``credentials_json`` (``apiKey``); the
header name, the value format and the reads flag live in ``config_json``. No key, no
header. The key value never reaches a log line, a call-log row, an exception text or an
API answer: ``AuthConfigInvalid`` carries a code only.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional, Tuple

from cryptography.fernet import InvalidToken

from app.secrets import decrypt_secret

AUTH_CONFIG_INVALID = "AUTH_CONFIG_INVALID"
DEFAULT_HEADER = "X-API-Key"
DEFAULT_FORMAT = "{key}"
PLACEHOLDER = "{key}"
READS_YES = "yes"

_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")  # RFC 7230 token
_RESERVED = frozenset({"host", "content-length", "content-type", "transfer-encoding", "connection", "cookie"})
MESSAGE = "The AutoCount API key settings are not valid."


class AuthConfigInvalid(Exception):
    """The key settings of a connection cannot produce a valid header. Code only, never a value."""

    code = AUTH_CONFIG_INVALID

    def __init__(self) -> None:
        super().__init__(MESSAGE)


def _printable(value: str) -> bool:
    return all(0x20 <= ord(c) <= 0x7E for c in value)


def settings_problem(config: Optional[Mapping[str, Any]]) -> Optional[str]:
    """A plain message when the header name or the format of ``config`` is unusable, else None
    (a blank value means the default). Used at save time and before every send."""
    cfg = config or {}
    header = str(cfg.get("apiKeyHeader") or "").strip() or DEFAULT_HEADER
    fmt = str(cfg.get("apiKeyFormat") or "") or DEFAULT_FORMAT
    if not _TOKEN.match(header) or header.lower() in _RESERVED:
        return "The API key header is not a usable header name."
    if fmt.count(PLACEHOLDER) != 1 or not _printable(fmt):
        return "The API key format must contain {key} exactly once."
    return None


def auth_headers(
    config: Optional[Mapping[str, Any]], credentials: Optional[Mapping[str, Any]], *, for_read: bool
) -> Dict[str, str]:
    """``{}`` with no key, or on a read when the reads flag is not Yes; else the one key header."""
    cfg, creds = config or {}, credentials or {}
    key = str(creds.get("apiKey") or "").strip()
    if not key:
        return {}
    if for_read and str(cfg.get("apiKeyOnReads") or "").strip().lower() != READS_YES:
        return {}
    if settings_problem(cfg) is not None or not _printable(key):
        raise AuthConfigInvalid()
    header = str(cfg.get("apiKeyHeader") or "").strip() or DEFAULT_HEADER
    fmt = str(cfg.get("apiKeyFormat") or "") or DEFAULT_FORMAT
    return {header: fmt.replace(PLACEHOLDER, key)}


def credentials_of(conn: Any) -> Dict[str, Any]:
    """The connection's decrypted credentials; an undecryptable blob is ``AuthConfigInvalid``."""
    blob = getattr(conn, "credentials_json", None)
    if not blob:
        return {}
    try:
        return decrypt_secret(blob)
    except (InvalidToken, ValueError, TypeError):
        raise AuthConfigInvalid() from None


def connection_headers(conn: Any) -> Tuple[Dict[str, str], Dict[str, str]]:
    """``(write_headers, read_headers)`` for a stored connection, read fresh (no cache)."""
    cfg = getattr(conn, "config_json", None) or {}
    creds = credentials_of(conn)
    return auth_headers(cfg, creds, for_read=False), auth_headers(cfg, creds, for_read=True)


def read_headers(conn: Any) -> Dict[str, str]:
    """The headers a READ (pull sync, probe, doc feed) of this connection carries."""
    cfg = getattr(conn, "config_json", None) or {}
    return auth_headers(cfg, credentials_of(conn), for_read=True)


def attach_headers(target: Any, headers: Mapping[str, str]) -> Any:
    """Hand ``headers`` to a client or reader (or a wrapper that forwards them); returns ``target``."""
    setter = getattr(target, "set_auth_headers", None)
    if headers and callable(setter):
        setter(dict(headers))
    return target
