"""Connector OAuth endpoints (public; auth happens in-endpoint). HTTP only."""

from __future__ import annotations
from typing import Dict

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.throttle import ThrottleService, Throttled, client_ip

from ..services.oauth_service import (
    BIND_COOKIE,
    AuthorizeRefused,
    ConsentRefused,
    InvalidClientMetadata,
    InvalidRedirect,
    OAuthService,
    TokenError,
)
from ._common import oauth_service, require_allowed_client, require_method

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_ERROR_HTML = (
    "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
    "content='width=device-width,initial-scale=1'><title>Connection problem</title></head>"
    "<body style='font-family:sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem'>"
    "<h1>We could not complete the connection</h1>"
    "<p>Sign-in took too long or did not start in this browser. "
    "Go back to Claude and connect again.</p></body></html>"
)


def _error_page() -> HTMLResponse:
    return HTMLResponse(_ERROR_HTML, status_code=400, headers=_NO_STORE)


def _throttled(exc: Throttled) -> JSONResponse:
    return JSONResponse({"error": "too_many_requests"}, status_code=429,
                        headers={"Retry-After": str(exc.retry_after_seconds), **_NO_STORE})


def _guard(db: Session, request: Request, prefix: str):
    """Per-IP throttle for the browser/public endpoints; every attempt counts.
    Returns a 429 response or None."""
    throttle = ThrottleService(db)
    key = f"{prefix}:{client_ip(request)}"
    try:
        throttle.enforce_connector(key=key)
    except Throttled as exc:
        return _throttled(exc)
    throttle.record_connector(key=key)
    return None


def _oauth_error(error: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status, headers=_NO_STORE)


async def _form(request: Request) -> Dict[str, str]:
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001 - malformed body is just an empty form
        return {}
    return {k: v for k, v in form.items() if isinstance(v, str)}


@router.api_route("/{p}/oauth/register", methods=["GET", "POST"], include_in_schema=False,
                  dependencies=[Depends(require_allowed_client)])
async def register(request: Request, svc: OAuthService = Depends(oauth_service),
                   db: Session = Depends(get_db)) -> Response:
    require_method(request, "POST")
    throttle = ThrottleService(db)
    key = f"dcr:{client_ip(request)}"
    try:
        throttle.enforce_connector(key=key)
    except Throttled as exc:
        return _throttled(exc)
    throttle.record_connector(key=key)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _oauth_error("invalid_client_metadata")
    try:
        return JSONResponse(svc.register_client(body), status_code=201, headers=_NO_STORE)
    except InvalidRedirect:
        return _oauth_error("invalid_redirect_uri")
    except InvalidClientMetadata:
        return _oauth_error("invalid_client_metadata")


@router.api_route("/{p}/oauth/authorize", methods=["GET", "POST"], include_in_schema=False)
def authorize(request: Request, svc: OAuthService = Depends(oauth_service),
              db: Session = Depends(get_db)) -> Response:
    require_method(request, "GET")
    limited = _guard(db, request, "authz")
    if limited is not None:
        return limited
    try:
        url, bind = svc.begin_authorize(dict(request.query_params))
    except AuthorizeRefused:
        return _error_page()
    resp = RedirectResponse(url, status_code=302, headers=_NO_STORE)
    resp.set_cookie(BIND_COOKIE, bind, max_age=600, path=urlparse(svc.issuer).path + "/oauth",
                    secure=True, httponly=True, samesite="none")
    return resp


@router.api_route("/{p}/oauth/consent-return", methods=["GET", "POST"], include_in_schema=False)
async def consent_return(request: Request, svc: OAuthService = Depends(oauth_service),
                         db: Session = Depends(get_db)) -> Response:
    require_method(request, "POST")
    limited = _guard(db, request, "consent")
    if limited is not None:
        return limited
    form = await _form(request)
    try:
        url = svc.complete_consent(
            request_id=form.get("request_id", ""),
            assertion=form.get("assertion"),
            error=form.get("error"),
            bind_cookie=request.cookies.get(BIND_COOKIE),
        )
    except ConsentRefused:
        return _error_page()
    return RedirectResponse(url, status_code=302, headers=_NO_STORE)


@router.api_route("/{p}/oauth/token", methods=["GET", "POST"], include_in_schema=False,
                  dependencies=[Depends(require_allowed_client)])
async def token(request: Request, svc: OAuthService = Depends(oauth_service),
                db: Session = Depends(get_db)) -> Response:
    require_method(request, "POST")
    throttle = ThrottleService(db)
    key = f"tok:{client_ip(request)}"
    try:
        throttle.enforce_connector(key=key)
    except Throttled as exc:
        return _throttled(exc)
    try:
        return JSONResponse(svc.token(await _form(request)), headers=_NO_STORE)
    except TokenError as exc:
        throttle.record_connector(key=key)
        return _oauth_error(exc.error)


@router.api_route("/{p}/oauth/revoke", methods=["GET", "POST"], include_in_schema=False,
                  dependencies=[Depends(require_allowed_client)])
async def revoke(request: Request, svc: OAuthService = Depends(oauth_service),
                 db: Session = Depends(get_db)) -> Response:
    require_method(request, "POST")
    limited = _guard(db, request, "revoke")
    if limited is not None:
        return limited
    form = await _form(request)
    svc.revoke(form.get("token"), form.get("client_id"))
    return Response(status_code=200, headers=_NO_STORE)
