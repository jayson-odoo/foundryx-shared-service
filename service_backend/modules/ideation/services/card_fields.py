"""Canny-style card field normalisers (plan 20) - a leaf module (no service
imports) so ``ideas``/``sinks``/``actions``/``intake``/``merge`` can share it."""
from typing import List, Optional

# Canny-style card fields (plan 20) mirrored from ``captured_json`` like the
# legacy segregated keys - text keys copied verbatim (stripped), ``use_cases``
# normalised to a list of non-blank strings.
CARD_TEXT_KEYS = ("desired_outcome", "current_workaround")


def clean_text(value: Optional[str]) -> Optional[str]:
    """Stripped text, or ``None`` for missing/blank."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def clean_use_cases(value: object) -> Optional[List[str]]:
    """Normalise use cases to a list of stripped, non-blank strings (``None``
    when nothing is left). Accepts a list, or a newline-separated string (a
    conversational turn may send either)."""
    if isinstance(value, str):
        items: List[object] = value.splitlines()
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return None
    cleaned = [s.strip() for s in items if isinstance(s, str) and s.strip()]
    return cleaned or None
