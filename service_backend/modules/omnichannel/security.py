"""Credential encryption for connected channels (Fernet, symmetric).

``channels.credentials_json`` (access tokens etc) is encrypted at rest. The key
comes from ``settings.omnichannel_fernet_key``; if unset a throwaway key is
generated per-process (dev only — a restart invalidates previously-stored
ciphertext, which is fine for dev but MUST be set in prod).
"""
import json
from functools import lru_cache
from typing import Any, Dict

from cryptography.fernet import Fernet

from app.config import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings.omnichannel_fernet_key
    if not key:
        # Dev fallback: ephemeral key (warn-by-design — see module docstring).
        key = Fernet.generate_key().decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_credentials(data: Dict[str, Any]) -> str:
    """Encrypt a credentials dict → opaque ciphertext string."""
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_credentials(token: str) -> Dict[str, Any]:
    """Decrypt ciphertext → credentials dict. Raises on tamper/wrong key."""
    return json.loads(_fernet().decrypt(token.encode()).decode())
