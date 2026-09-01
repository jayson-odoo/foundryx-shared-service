"""Server-side password policy (plan 10 §3) - defense-in-depth; the frontend
mirrors these rules for inline UX. Length is capped at 72: bcrypt hashes only
the first 72 bytes and raises on longer input (see app/security.py).
"""
import re

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 72

_POLICY = [
    (re.compile(r"[A-Z]"), "an uppercase letter"),
    (re.compile(r"[a-z]"), "a lowercase letter"),
    (re.compile(r"\d"), "a number"),
    (re.compile(r"[^A-Za-z0-9]"), "a special character"),
]


def validate_password_strength(value: str) -> str:
    """Pydantic field-validator body - raises ValueError on policy violations."""
    missing = [label for pattern, label in _POLICY if not pattern.search(value)]
    if missing:
        raise ValueError(f"Password must contain at least {', '.join(missing)}.")
    return value
