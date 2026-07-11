"""Embed session router — plan 11H Slice 2 (AC-11H-04..08).

PUBLIC (mounted with ``"public": true`` — no JWT/require_module gate; the
assertion signature IS the credential). ``POST /embed/session`` exchanges a
consumer-minted assertion for a short-lived access token. Rides the platform
throttle (own per-IP bucket). Errors use the uniform ``{"error":{code,message}}``
envelope via ``ApiError``.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db
from app.services.throttle import ThrottleService, Throttled, client_ip

from ..services.embed_session_service import EmbedError, EmbedSessionService

router = APIRouter()


class EmbedSessionRequest(BaseModel):
    assertion: str
    # The VALIDATED parent (embedding page) origin the widget captured from the
    # accepted `init` — NOT the widget's own request Origin header (which is the
    # shared-service origin and meaningless against the connection's PARENT
    # allowedOrigins). See EmbedSessionService.exchange for the trust rationale.
    parentOrigin: Optional[str] = None


@router.post("/session")
def create_embed_session(
    payload: EmbedSessionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    ip = client_ip(request)
    throttle = ThrottleService(db)
    try:
        throttle.enforce_embed(ip=ip)
    except Throttled as exc:
        raise ApiError(
            429,
            "rate_limited",
            "Too many attempts — try again later.",
        ).with_retry_after(exc.retry_after_seconds)

    try:
        return EmbedSessionService(db).exchange(payload.assertion, payload.parentOrigin)
    except EmbedError as exc:
        # A failed exchange pumps the IP bucket (bounds assertion-forgery spam).
        throttle.record_embed(ip=ip)
        raise ApiError(exc.status_code, exc.code, exc.message)


@router.get("/frame-policy")
def frame_policy(
    c: Optional[str] = None,
    db: Session = Depends(get_db),
) -> dict:
    """AC-11H-15 — the embed page's ``frame-ancestors`` source. The Next.js
    middleware reads the non-secret connection id (``?c=``) from the iframe src
    and sets the CSP from these origins. Unknown connection → empty (uniform)."""
    return {"allowedOrigins": EmbedSessionService(db).allowed_origins_for(c)}
