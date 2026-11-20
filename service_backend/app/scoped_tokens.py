"""Scoped access tokens - the ONE mint/verify helper for every non-staff JWT
that a Service hands to an embedded or hosted page (plan 64 L-C, AC-64-07).

A scoped token is a normal signed JWT (same key, same algorithm as the staff
session) that carries a ``typ`` claim. ``typ`` is the discriminator:

- ``assert_staff_token`` (``app/dependencies.py``) refuses ANY token with a
  ``typ`` on every staff route, so a scoped token can never act as a user.
- ``decode_scoped_token(token, typ)`` accepts a token only when its ``typ``
  is exactly the one asked for, so one Service's token never opens another
  Service's routes (omnichannel ``embed`` vs Lead Capture
  ``lead_capture_embed``). Known exception: ideation also mints
  ``typ="embed"`` (its own helper); omnichannel's claim checks
  (``_embed_claims``: workspace, agent, connection) keep it out today. A new
  Service picks its own ``typ``.

Users: omnichannel embed sessions (``typ="embed"``, plan 11H) and the Lead
Capture hosted wizard (``typ="lead_capture_embed"``).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from jose import JWTError

from app.security import create_access_token, decode_access_token


def mint_scoped_token(typ: str, claims: Dict[str, Any], *, ttl_minutes: int) -> str:
    """Sign ``claims`` + ``typ`` with a ``ttl_minutes`` lifetime. ``typ`` is
    required and wins over any ``typ`` already in ``claims``."""
    if not typ:
        raise ValueError("a scoped token needs a typ")
    body = dict(claims)
    body["typ"] = typ
    return create_access_token(body, expires_minutes=ttl_minutes)


def decode_scoped_token(token: Optional[str], typ: str) -> Optional[Dict[str, Any]]:
    """The verified claims when ``token`` is a valid, unexpired token of
    exactly ``typ``; otherwise None (bad signature, expired, other type)."""
    if not token or not typ:
        return None
    try:
        payload = decode_access_token(token)
    except JWTError:
        return None
    if payload.get("typ") != typ:
        return None
    return payload
