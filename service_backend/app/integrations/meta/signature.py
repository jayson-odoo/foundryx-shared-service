"""Meta webhook signature check - CORE since plan 64 (D3).

Moved verbatim from ``modules/omnichannel/routers/webhooks.py``
(``_signature_valid``, which is now an alias of ``signature_valid``) so every
Service receiving Meta webhooks (omnichannel, Lead Capture) applies the SAME
rule from the SAME code.
"""
import hashlib
import hmac

from app.config import settings


def signature_valid(body: bytes, header: str) -> bool:
    """X-Hub-Signature-256 = HMAC-SHA256(app_secret, raw_body).

    Fail-OPEN only in development with no secret set (local testing without a
    Meta app). In any other environment a missing secret fails CLOSED - a prod
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
