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

``POST /page-select {pickToken, pageId?}`` (wp-6) finishes a Page connect
(``channelType`` FACEBOOK): its callback answers ``{pagePicker: {pickToken,
pages}}`` instead of a redirect, the same page shows the list, and this
route spends the single-use pick token: a ``pageId`` from the list gives
``status=authorized``, none gives ``status=cancelled``; both answer
``200 {redirect}``. A spent, unknown or expired token: the same uniform 404
and throttle; a Page id that was not offered: ``422 invalid_page`` (also a
throttle miss). The third wrong Page id of one pick token ends the session
``FAILED`` (``page_select_attempts_exceeded``) and answers the redirect with
``status=failed``.

The request carries the Meta code: it is never logged and never echoed.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db
from app.services.throttle import ThrottleService, Throttled, client_ip

from ..schemas import ConnectCallbackRequest, ConnectCallbackResponse, ConnectPageSelectRequest
from ..services.partner_connect_service import (
    ConnectNotConfigured,
    ConnectSessionNotFound,
    PageNotOffered,
    PartnerConnectService,
)

router = APIRouter()


def _enforce(request: Request, db: Session):
    throttle_key = f"wa-connect:{client_ip(request)}"
    throttle = ThrottleService(db)
    try:
        throttle.enforce_embed(ip=throttle_key)
    except Throttled as exc:
        raise ApiError(429, "rate_limited", "Too many attempts. Try again later.").with_retry_after(
            exc.retry_after_seconds
        )
    return throttle, throttle_key


@router.post("/wa-callback", response_model=ConnectCallbackResponse, response_model_exclude_none=True)
def wa_callback(
    payload: ConnectCallbackRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ConnectCallbackResponse:
    throttle, throttle_key = _enforce(request, db)
    try:
        return PartnerConnectService(db).callback(payload.state, payload.code, payload.error)
    except ConnectNotConfigured:
        raise ApiError(503, "connect_not_configured", "Hosted connect is not configured.")
    except ConnectSessionNotFound:
        throttle.record_embed(ip=throttle_key)
        raise ApiError(404, "connect_session_not_found", "Connect session not found.")


@router.post("/page-select", response_model=ConnectCallbackResponse, response_model_exclude_none=True)
def page_select(
    payload: ConnectPageSelectRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ConnectCallbackResponse:
    throttle, throttle_key = _enforce(request, db)
    try:
        return PartnerConnectService(db).select_page(payload.pickToken, payload.pageId)
    except ConnectNotConfigured:
        raise ApiError(503, "connect_not_configured", "Hosted connect is not configured.")
    except ConnectSessionNotFound:
        throttle.record_embed(ip=throttle_key)
        raise ApiError(404, "connect_session_not_found", "Connect session not found.")
    except PageNotOffered:
        # A wrong Page id is a miss like an unknown token: it pumps the same bucket.
        throttle.record_embed(ip=throttle_key)
        raise ApiError(422, "invalid_page", "That Page was not offered for this connection.")
