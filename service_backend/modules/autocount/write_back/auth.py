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
from modules.autocount.write_back import guard

AUTH_CONFIG_INVALID = "AUTH_CONFIG_INVALID"
DEFAULT_HEADER = "X-API-Key"
DEFAULT_FORMAT = "{key}"
PLACEHOLDER = "{key}"
READS_YES = "yes"

_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")  # RFC 7230 token
_RESERVED = frozenset({"host", "content-length", "content-type", "transfer-encoding", "connection", "cookie"})
MESSAGE = "The AutoCount API key settings are not valid."


MASK = "***"


class AuthHeaders(dict):
    """The key header plus the secret strings (the key and the rendered value) a vendor
    answer must never echo back into a record."""

    secrets: Tuple[str, ...] = ()


def mask(text: str, secrets: Tuple[str, ...]) -> str:
    """``text`` with every secret replaced by ``***`` (longest first)."""
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, MASK)
    return text


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
    if fmt.count(PLACEHOLDER) != 1 or not _printable(fmt) or fmt != fmt.strip():
        return "The API key format must contain {key} exactly once, without spaces around it."
    return None


def _field_value_ok(value: str) -> bool:
    """RFC 7230 field-value as the HTTP stack accepts it: visible ASCII (inner spaces allowed),
    no leading or trailing whitespace."""
    return bool(value) and _printable(value) and value == value.strip()


def auth_headers(
    config: Optional[Mapping[str, Any]], credentials: Optional[Mapping[str, Any]], *, for_read: bool
) -> Dict[str, str]:
    """``{}`` with no key, or on a read when the reads flag is not Yes; else the one key header."""
    cfg, creds = config or {}, credentials or {}
    key = str(creds.get("apiKey") or "")
    if not key.strip():
        return {}
    if for_read and not _reads_enabled(cfg):
        return {}
    header = str(cfg.get("apiKeyHeader") or "").strip() or DEFAULT_HEADER
    fmt = str(cfg.get("apiKeyFormat") or "") or DEFAULT_FORMAT
    if settings_problem(cfg) is not None or key != key.strip():
        raise AuthConfigInvalid()
    value = fmt.replace(PLACEHOLDER, key)
    if not _field_value_ok(value):
        raise AuthConfigInvalid()
    if for_read and cfg.get("baseUrl") and not guard.host_allowlisted(str(cfg.get("baseUrl"))):
        return {}  # a read to a host off the write allowlist never carries the key
    out = AuthHeaders({header: value})
    out.secrets = (key, value)
    return out


def _reads_enabled(cfg: Mapping[str, Any]) -> bool:
    return str(cfg.get("apiKeyOnReads") or "").strip().lower() == READS_YES


def credentials_of(conn: Any) -> Dict[str, Any]:
    """The connection's decrypted credentials; an undecryptable blob is ``AuthConfigInvalid``."""
    blob = getattr(conn, "credentials_json", None)
    if not blob:
        return {}
    try:
        return decrypt_secret(blob)
    except (InvalidToken, ValueError, TypeError):
        raise AuthConfigInvalid() from None


def write_headers(conn: Any) -> Dict[str, str]:
    """The headers a WRITE through this connection carries; undecryptable credentials refuse."""
    cfg = getattr(conn, "config_json", None) or {}
    return auth_headers(cfg, credentials_of(conn), for_read=False)


def read_headers(conn: Any) -> Dict[str, str]:
    """The headers a READ (pull sync, probe, doc feed) of this connection carries."""
    cfg = getattr(conn, "config_json", None) or {}
    if not _reads_enabled(cfg):
        return {}  # reads without the flag never need the key, so never decrypt
    return auth_headers(cfg, credentials_of(conn), for_read=True)


def attach_headers(target: Any, headers: Mapping[str, str]) -> Any:
    """Hand ``headers`` to a client or reader (or a wrapper that forwards them); returns ``target``."""
    setter = getattr(target, "set_auth_headers", None)
    if headers and callable(setter):
        setter(headers)
    return target
