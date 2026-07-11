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


def encrypt_secret(value: str) -> str:
    """Encrypt an opaque string (e.g. a webhook signing secret) at rest."""
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Decrypt an encrypted string. Raises on tamper/wrong key."""
    return _fernet().decrypt(token.encode()).decode()


# ── Signed media URLs (public gateway, respond.io parity) ────────────────────
# A stored blob is served through the authed ``/omnichannel/media/{id}`` route.
# For external consumers we hand back an ABSOLUTE, HMAC-signed, time-limited URL
# that carries its own authorization (``exp`` + ``sig``) so a raw browser click
# works with no Authorization header. The signature binds the message id + expiry
# under ``settings.jwt_secret`` — unforgeable, and the media route resolves the
# message GLOBALLY (the valid signature IS the authz) once verified.
import hashlib
import hmac
from datetime import datetime, timezone


def _media_sig(message_id: str, exp: int) -> str:
    from app.config import settings

    payload = f"{message_id}:{exp}".encode()
    return hmac.new(settings.jwt_secret.encode(), payload, hashlib.sha256).hexdigest()


def verify_media_sig(message_id: str, exp: int, sig: str) -> bool:
    """True iff ``sig`` is a valid, unexpired signature for ``message_id``.
    Constant-time compare; a malformed/expired token is a clean False."""
    now = int(datetime.now(timezone.utc).timestamp())
    if exp < now:
        return False
    expected = _media_sig(message_id, exp)
    return hmac.compare_digest(expected, sig or "")


def signed_media_url(message_id: str) -> str:
    """Absolute, time-limited, clickable URL for a message's media blob."""
    from app.config import settings

    exp = int(datetime.now(timezone.utc).timestamp()) + settings.media_signed_url_ttl_seconds
    sig = _media_sig(message_id, exp)
    base = settings.public_base_url.rstrip("/")
    return f"{base}/omnichannel/media/{message_id}?exp={exp}&sig={sig}"
