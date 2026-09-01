"""Secret redaction for the integration-activity log (sprint-4/12, AC-DLC-04/25).

A stored request/response summary must NEVER carry a plaintext credential - API
keys, bearer tokens, ``embedSecret``, Meta access tokens, passwords, assertions
are masked. WhatsApp message *content* is NOT a secret key → preserved (it's
needed to troubleshoot). Recursive over dicts/lists, size-capped so a
pathological payload can't blow up memory or the row.
"""
import re
from typing import Any

MASK = "***"

# Case-insensitive KEY patterns whose value is a secret regardless of content.
# ``api[_-]?key`` matches apiKey / api_key / api-key; ``embedsecret`` covers the
# iframe embed secret. ``token``/``secret``/``password``/``assertion`` are broad
# by design. NOTE: only the KEY is matched - a value like a WhatsApp message
# body is never masked by key name.
_SECRET_KEY_RE = re.compile(
    r"authorization|api[_-]?key|token|secret|password|assertion|embedsecret",
    re.IGNORECASE,
)

# Bounds so a hostile / huge payload degrades gracefully rather than bloating a
# log row.
_MAX_DEPTH = 12
_MAX_LIST = 200
_MAX_STR = 4096


def _is_secret_key(key: str) -> bool:
    return _SECRET_KEY_RE.search(key) is not None


def redact(obj: Any, _depth: int = 0) -> Any:
    """Return a redacted, size-capped copy of a JSON-ish structure. Secret KEYS
    are replaced wholesale with ``"***"``; nothing else is altered (message
    content survives)."""
    if _depth > _MAX_DEPTH:
        return MASK
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _is_secret_key(str(k)):
                out[k] = MASK
            else:
                out[k] = redact(v, _depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact(v, _depth + 1) for v in list(obj)[:_MAX_LIST]]
    if isinstance(obj, str):
        return obj if len(obj) <= _MAX_STR else obj[:_MAX_STR] + "…"
    return obj
