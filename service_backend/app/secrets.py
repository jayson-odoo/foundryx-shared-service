"""Core secrets encryption (plan 09 D7) - Fernet, symmetric.

`connections.credentials_json` is encrypted at rest with `settings.fernet_key`.
Unset key = throwaway per-process key (dev only - a restart, or even just a
SECOND process like bootstrap vs uvicorn, cannot read each other's ciphertext;
set FERNET_KEY anywhere real). Omnichannel still uses its own
OMNICHANNEL_FERNET_KEY until BL-042 migrates it onto this helper.
"""
import json
from typing import Any, Dict, Optional, Tuple

from cryptography.fernet import Fernet

from app.config import settings

# One cached Fernet per process, re-built only if the configured key changes
# (tests mutate settings). Empty key → a single ephemeral key for the process.
_cache: Optional[Tuple[str, Fernet]] = None


def _fernet() -> Fernet:
    global _cache
    key = settings.fernet_key
    if _cache is None or _cache[0] != key:
        material = key or Fernet.generate_key().decode()
        _cache = (key, Fernet(material.encode()))
    return _cache[1]


def encrypt_secret(data: Dict[str, Any]) -> str:
    """Encrypt a secrets dict → opaque ciphertext string."""
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_secret(token: str) -> Dict[str, Any]:
    """Decrypt ciphertext → secrets dict. Raises InvalidToken on tamper/wrong key."""
    return json.loads(_fernet().decrypt(token.encode()).decode())
