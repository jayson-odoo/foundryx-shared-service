"""Secret/PAN masking for the integration log (sprint-4/07 Cluster F slice 3,
AC-07-28). The webhook request/response we persist must NEVER carry raw secrets
or card data - mask before it touches ``integration_logs``.
"""
import re
from typing import Any

# Keys whose value is sensitive regardless of content (signatures, tokens,
# secrets, raw card data). Matched case-insensitively as a substring.
_SENSITIVE_KEY_PARTS = (
    "secret", "signature", "sig", "token", "password", "key", "authorization",
    "card", "pan", "cvc", "cvv", "account_number", "iban", "client_secret",
    # AutoCount's AppId is a CREDENTIAL, not an identifier: it authenticates the
    # request AND selects the company database. The provider already declares it
    # ``"type": "password", "secret": True``, so the system treats it as one
    # everywhere except here. Both spellings - substring matching is literal, so
    # "appid" does not cover "app_id".
    "appid", "app_id",
)
# A 13-19 digit run = a probable PAN; mask all but the last 4.
_PAN_RE = re.compile(r"\b(\d{13,19})\b")
_MASK = "***"


def _is_sensitive_key(key: str) -> bool:
    k = key.lower()
    return any(part in k for part in _SENSITIVE_KEY_PARTS)


def _mask_string(value: str) -> str:
    def repl(m: re.Match) -> str:
        digits = m.group(1)
        return f"{_MASK}{digits[-4:]}"

    return _PAN_RE.sub(repl, value)


def mask_payload(value: Any, _depth: int = 0) -> Any:
    """Recursively mask a JSON-ish structure. Sensitive KEYS are redacted
    wholesale; string VALUES have PAN-like digit runs masked. Depth-capped so a
    pathological payload can't recurse forever."""
    if _depth > 12:
        return _MASK
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _is_sensitive_key(str(k)):
                out[k] = _MASK
            else:
                out[k] = mask_payload(v, _depth + 1)
        return out
    if isinstance(value, list):
        return [mask_payload(v, _depth + 1) for v in value[:200]]
    if isinstance(value, str):
        return _mask_string(value)
    return value
