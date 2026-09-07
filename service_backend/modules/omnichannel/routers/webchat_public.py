"""Public web chat visitor API (plan 34 / A7b S2) - unauthenticated, mounted
`"public": true` (manifest prefix `/public/omnichannel/webchat`). Mirrors
`routers/webchat_widget.py`'s note: no `require_module` gate here, so every
call re-derives tenant lifecycle + module-active from the widget key alone,
GLOBALLY, via `WebchatVisitorService.resolve_live_channel`.

Router = HTTP + Pydantic only (layering rule). Every uniform-404/401/422/429
decision and every DB read/write lives in
`services/webchat_visitor_service.py`; `visitor_projection.py` is the only
place a stored message becomes a `VisitorMessage`.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db
from app.services.throttle import ThrottleService, Throttled, client_ip

from ..schemas import (
    VisitorMessage,
    WebchatHoneypotResult,
    WebchatMessagesPage,
    WebchatSessionResult,
)
from ..services.webchat_visitor_service import (
    HISTORY_PAGE_LIMIT,
    HISTORY_PAGE_LIMIT_MAX,
    WebchatInvalidRequest,
    WebchatNotFound,
    WebchatUnauthorized,
    WebchatVisitorService,
    cors_headers_for,
    read_capped_json,
    resolve_live_channel,
)

router = APIRouter()


def _uniform_404() -> HTTPException:
    """AC-WEB-24 - byte-identical for every session-start failure mode
    (unknown key, trashed/inactive channel, module off, tenant blocked,
    disallowed/missing origin). Plain FastAPI-style body (not the `{error:
    {...}}` envelope) - this surface is not under `/api/v1/`, and the plan's
    own uniform-404 definition is literally `{"detail": "Not found."}`."""
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")


def _uniform_401() -> ApiError:
    """AC-WEB-27/R4 - one indistinguishable 401 for a forged, expired,
    wrong-`typ`, wrong-channel or epoch-revoked token, AND for a widget key
    that fails to resolve on this Bearer-authed surface (no 404 exists here
    - the token, not the key, is this surface's credential)."""
    return ApiError(status.HTTP_401_UNAUTHORIZED, "invalid_token", "Invalid or expired session.")


def _rate_limited(retry_after_seconds: int) -> ApiError:
    return ApiError(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "rate_limited",
        "Too many attempts - try again later.",
    ).with_retry_after(retry_after_seconds)


@router.post("/{widget_key}/session")
async def start_session(
    widget_key: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> WebchatSessionResult:
    """AC-WEB-23/24/25/28/29 - throttled BEFORE any database work (AC-WEB-30);
    origin-checked; mints or renews a visitor token; NEVER writes a row
    (D-A7B-7)."""
    ip = client_ip(request)
    throttle = ThrottleService(db)
    try:
        throttle.enforce_webchat(ip=ip)
    except Throttled as exc:
        raise _rate_limited(exc.retry_after_seconds)
    throttle.record_webchat(ip=ip)

    try:
        body = await read_capped_json(request)
    except WebchatInvalidRequest as exc:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code, exc.message)

    try:
        channel = resolve_live_channel(db, widget_key)
    except WebchatNotFound:
        raise _uniform_404()

    origin = request.headers.get("origin")
    service = WebchatVisitorService(db)
    try:
        result = service.start_session(channel, origin=origin, token=body.get("token"))
    except WebchatNotFound:
        raise _uniform_404()

    for key, value in cors_headers_for(channel, origin).items():
        response.headers[key] = value
    return WebchatSessionResult(**result)


@router.post("/{widget_key}/messages", status_code=status.HTTP_201_CREATED)
async def post_message(
    widget_key: str,
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """AC-WEB-26/31/32/33 - the ONE write on this surface. Lazy contact
    creation on the visitor's FIRST message via the UNCHANGED
    `InboundService`; a honeypot hit returns the normal success shape and
    stores nothing (AC-WEB-32)."""
    ip = client_ip(request)
    throttle = ThrottleService(db)
    try:
        throttle.enforce_webchat(ip=ip)
    except Throttled as exc:
        raise _rate_limited(exc.retry_after_seconds)
    throttle.record_webchat(ip=ip)

    try:
        channel = resolve_live_channel(db, widget_key)
    except WebchatNotFound:
        raise _uniform_401()

    service = WebchatVisitorService(db)
    try:
        claims = service.verify_token(channel, authorization)
    except WebchatUnauthorized:
        raise _uniform_401()

    # A SECOND, visitor-scoped check (D-A7B-22) now that the visitor id is
    # known - independent of the IP bucket above, so one abusive visitor id
    # is caught on its own counter without throttling a whole shared office.
    try:
        throttle.enforce_webchat(visitor_id=claims.visitor_id)
    except Throttled as exc:
        raise _rate_limited(exc.retry_after_seconds)
    throttle.record_webchat(visitor_id=claims.visitor_id)

    try:
        body = await read_capped_json(request)
    except WebchatInvalidRequest as exc:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code, exc.message)

    origin = request.headers.get("origin")
    for key, value in cors_headers_for(channel, origin).items():
        response.headers[key] = value

    try:
        item, is_honeypot = service.post_message(channel, claims, body)
    except WebchatInvalidRequest as exc:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code, exc.message)

    if is_honeypot:
        response.status_code = status.HTTP_200_OK
        return WebchatHoneypotResult()
    return VisitorMessage(**item)


@router.get("/{widget_key}/messages")
def get_messages(
    widget_key: str,
    request: Request,
    response: Response,
    after: Optional[str] = None,
    limit: int = Query(default=HISTORY_PAGE_LIMIT, ge=1, le=HISTORY_PAGE_LIMIT_MAX),
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> WebchatMessagesPage:
    """AC-WEB-34/40 - this visitor's OWN thread only, oldest to newest,
    page-capped; also the poll fallback (D-A7B-16, no third transport).
    NOT throttled (the contract's own throttle rows cover only `/session`
    and `POST /messages` - AC-WEB-30)."""
    try:
        channel = resolve_live_channel(db, widget_key)
    except WebchatNotFound:
        raise _uniform_401()

    service = WebchatVisitorService(db)
    try:
        claims = service.verify_token(channel, authorization)
    except WebchatUnauthorized:
        raise _uniform_401()

    origin = request.headers.get("origin")
    for key, value in cors_headers_for(channel, origin).items():
        response.headers[key] = value

    data, next_after = service.history(channel, claims, after=after, limit=limit)
    return WebchatMessagesPage(data=[VisitorMessage(**item) for item in data], nextAfter=next_after)
