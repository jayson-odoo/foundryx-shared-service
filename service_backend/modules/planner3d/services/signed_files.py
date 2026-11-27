"""Signed, time-limited result links (contract 3.1).

HMAC-SHA256 over ``p3file:<file id>:<exp>`` keyed by the server secret; the
``p3file:`` prefix keeps it apart from the omnichannel media signature, which uses
the same secret. The link opens without the key: the signature binds the exact
file id, so it cannot be re-pointed. Expiry is checked before the compare, and the
compare is constant-time.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Tuple

from app.config import settings

TTL_SECONDS = 3600


def _now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _sig(file_id: str, exp: int) -> str:
    payload = f"p3file:{file_id}:{exp}".encode()
    return hmac.new(settings.jwt_secret.encode(), payload, hashlib.sha256).hexdigest()


def verify(file_id: str, exp: int, sig: str) -> bool:
    if exp < _now():
        return False
    return hmac.compare_digest(_sig(file_id, exp), sig or "")


def signed_url(file_id: str) -> Tuple[str, datetime]:
    """``(absolute url, expires at)``."""
    exp = _now() + TTL_SECONDS
    base = settings.public_base_url.rstrip("/")
    return (
        f"{base}/planner3d/files/{file_id}?exp={exp}&sig={_sig(file_id, exp)}",
        datetime.fromtimestamp(exp, tz=timezone.utc),
    )
