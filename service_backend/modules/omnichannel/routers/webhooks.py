"""Meta webhook receiver (plan 05 §4.1) — PUBLIC endpoints, signature-verified.

Contract: verify fast, ACK fast (<50ms), do NOTHING else synchronously — the
raw payload goes to the Celery queue and the worker owns processing. A slow
handler makes Meta retry + eventually disable the subscription.
"""
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_BODY_BYTES = 1_000_000  # size guard — webhook bodies are tiny; 1MB is generous


@router.get("/{channel_id}")
def verify_handshake(
    channel_id: str,
    mode: str = Query("", alias="hub.mode"),
    verify_token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
) -> PlainTextResponse:
    """Meta's GET subscription handshake: echo hub.challenge on token match."""
    if mode == "subscribe" and verify_token == settings.meta_webhook_verify_token:
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


def _signature_valid(body: bytes, header: str) -> bool:
    """X-Hub-Signature-256 = HMAC-SHA256(app_secret, raw_body).

    Fail-OPEN only in development with no secret set (local testing without a
    Meta app). In any other environment a missing secret fails CLOSED — a prod
    misconfig must never silently accept forged webhooks.
    """
    if not settings.meta_app_secret:
        return settings.environment == "development"
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.meta_app_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(header[len("sha256=") :], expected)


@router.post("/{channel_id}")
async def receive_webhook(channel_id: str, request: Request) -> dict:
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    if not _signature_valid(body, request.headers.get("X-Hub-Signature-256", "")):
        raise HTTPException(status_code=403, detail="Invalid signature")
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Fast ACK: enqueue and return. Channel validity, parsing, contact
    # resolution — all the worker's job (plan 05 §4.2).
    from ..worker import process_inbound_webhook

    process_inbound_webhook.delay(channel_id, payload)
    return {"status": "queued"}
