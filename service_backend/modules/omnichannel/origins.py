"""Shared origin validator (plan 34 / A7b S1, D-A7B-13).

``_validate_origin`` / ``_validate_origins`` were MOVED verbatim out of
``services/embed_config_service.py`` (plan 11H) so the web chat channel
(``services/webchat_service.py``, allowed-origins on connect + widget config)
can reuse the SAME validator instead of a second copy drifting alongside it -
"two origin validators in one module is exactly how a security control
drifts" (plan §3, D-A7B-13). ``embed_config_service.py`` re-imports these
three names so its own callers (the router, `test_omnichannel_embed_config.py`)
see zero change - a pure move, same discipline `meta_graph.py` used for the
Meta Graph plumbing shared between the WhatsApp/Messenger/Instagram adapters.
"""
import re
from typing import Dict, List
from urllib.parse import urlsplit

# Exact hostname (or IPv4) - dot-separated labels of letters/digits/hyphen only.
# Rejects wildcards (`*.acme.com`) and other special characters.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,62})?(\.[a-z0-9]([a-z0-9-]{0,62})?)*$"
)


class InvalidOrigin(Exception):
    """A submitted origin failed validation (router -> 422)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _validate_origin(raw: str) -> str:
    """Return the normalized origin, or raise ``InvalidOrigin``.

    A valid origin is a bare ``scheme://host[:port]`` - NO path, trailing slash,
    query, fragment, or credentials. ``https://`` is required for real hosts;
    ``http://`` is allowed ONLY for ``localhost`` / ``127.0.0.1`` (dev)."""
    value = (raw or "").strip()
    if not value:
        raise InvalidOrigin("An origin cannot be blank.")

    parts = urlsplit(value)
    if parts.scheme not in ("https", "http"):
        raise InvalidOrigin(
            f"'{value}' must start with https:// (or http:// for localhost)."
        )
    if parts.username or parts.password:
        raise InvalidOrigin(f"'{value}' must not include credentials.")
    if parts.query or parts.fragment:
        raise InvalidOrigin(f"'{value}' must not include a query or fragment.")
    # A trailing slash / any path both surface as a non-empty path.
    if parts.path not in ("", "/") or value.endswith("/"):
        raise InvalidOrigin(
            f"'{value}' must be a bare origin with no path or trailing slash "
            "(e.g. https://crm.acme.com)."
        )

    host = (parts.hostname or "").lower()
    if not host:
        raise InvalidOrigin(f"'{value}' is missing a host.")
    # Exact hostnames only - no wildcards / other special chars. A '*' is a legal
    # urlsplit host code point and would otherwise pass and (if fed to a CSP
    # frame-ancestors) silently broaden who may embed. Labels: letters/digits/hyphen.
    if not _HOSTNAME_RE.match(host):
        raise InvalidOrigin(
            f"'{value}' has an invalid host - wildcards and special characters "
            "are not allowed (e.g. https://crm.acme.com)."
        )
    try:
        port = parts.port
    except ValueError:
        raise InvalidOrigin(f"'{value}' has an invalid port.")

    is_local = host in ("localhost", "127.0.0.1")
    if parts.scheme == "http" and not is_local:
        raise InvalidOrigin(
            f"'{value}' must use https:// (http:// is only allowed for localhost)."
        )

    # Drop the scheme's default port so the stored value matches a browser Origin
    # header (which omits :443/:80) - keeps the origins-editor dirty flag honest.
    default_port = 443 if parts.scheme == "https" else 80
    netloc = host if port is None or port == default_port else f"{host}:{port}"
    return f"{parts.scheme}://{netloc}"


def _validate_origins(origins: List[str]) -> List[str]:
    """Validate + normalize + dedupe (preserving first-seen order)."""
    seen: Dict[str, None] = {}
    for raw in origins:
        normalized = _validate_origin(raw)
        seen.setdefault(normalized, None)
    return list(seen.keys())
