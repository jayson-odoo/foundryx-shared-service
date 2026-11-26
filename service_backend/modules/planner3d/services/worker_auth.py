"""Worker token check. SS holds only the sha256 hex of the token; the bearer is
hashed and compared in constant time. Neither the token nor its hash is ever
logged or echoed."""

from __future__ import annotations

import hashlib
import hmac
from typing import Optional

from app.config import settings


class WorkerAuthError(Exception):
    pass


def authenticate(authorization: Optional[str], worker_name: Optional[str]) -> str:
    """Returns the worker name, or raises ``WorkerAuthError``."""
    expected = (getattr(settings, "planner3d_worker_token_sha256", "") or "").strip().lower()
    if not expected:
        raise WorkerAuthError("worker access is not configured")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise WorkerAuthError("missing bearer token")
    digest = hashlib.sha256(token.strip().encode("utf-8")).hexdigest()
    if not hmac.compare_digest(digest.encode("ascii"), expected.encode("utf-8", "replace")):
        raise WorkerAuthError("invalid token")
    name = (worker_name or "").strip()
    if not name or len(name) > 100:
        raise WorkerAuthError("missing worker name")
    return name
