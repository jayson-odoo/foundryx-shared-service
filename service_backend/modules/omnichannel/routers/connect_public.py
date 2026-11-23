"""Public connect callback (``/api/v1/omnichannel/connect/*``, FSS-1).

``POST /wa-callback {state, code?, error?}`` is called by the existing
``/wa-callback`` page when Meta returns with a ``state`` (a partner connect
session). No login and no key: the single-use state IS the credential. It is
marked ``"public": true`` in the manifest like ``partner_v1``.

* Off until configured: ``503 connect_not_configured``.
* An unknown, used or expired state, or a session whose client app,
  workspace or tenant is no longer usable: one uniform
  ``404 connect_session_not_found``. Each miss pumps a per-IP bucket (the
  embed throttle's limits, its own key namespace); over it, ``429``.
* Otherwise ``200 {redirect}``, built from the STORED return URL. Meta's
  ``error`` gives ``status=cancelled``, a failed code exchange
  ``status=failed``, success ``status=authorized``.

The request carries the Meta code: it is never logged and never echoed.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db
from app.services.throttle import ThrottleService, Throttled, client_ip

from ..schemas import ConnectCallbackRequest, ConnectCallbackResponse
from ..services.partner_connect_service import (
    ConnectNotConfigured,
    ConnectSessionNotFound,
    PartnerConnectService,
)

router = APIRouter()


@router.post("/wa-callback", response_model=ConnectCallbackResponse)
def wa_callback(
    payload: ConnectCallbackRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ConnectCallbackResponse:
    throttle_key = f"wa-connect:{client_ip(request)}"
    throttle = ThrottleService(db)
    try:
        throttle.enforce_embed(ip=throttle_key)
    except Throttled as exc:
        raise ApiError(429, "rate_limited", "Too many attempts. Try again later.").with_retry_after(
            exc.retry_after_seconds
        )
    try:
        redirect = PartnerConnectService(db).callback(payload.state, payload.code, payload.error)
    except ConnectNotConfigured:
        raise ApiError(503, "connect_not_configured", "Hosted connect is not configured.")
    except ConnectSessionNotFound:
        throttle.record_embed(ip=throttle_key)
        raise ApiError(404, "connect_session_not_found", "Connect session not found.")
    return ConnectCallbackResponse(redirect=redirect)
