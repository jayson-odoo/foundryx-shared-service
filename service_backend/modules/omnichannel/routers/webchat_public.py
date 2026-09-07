"""Public web chat visitor API (plan 34 / A7b S2) - unauthenticated, mounted
`"public": true` (manifest prefix `/public/omnichannel/webchat`). Mirrors
`routers/webchat_widget.py`'s note: no `require_module` gate here, so every
call re-derives tenant lifecycle + module-active from the widget key alone,
GLOBALLY, via `WebchatVisitorService.resolve_live_channel`.

Router = HTTP + Pydantic only (layering rule). Every uniform-404/401/422/429
decision and every DB read/write lives in
`services/webchat_visitor_service.py`; `visitor_projection.py` is the only
place a stored message becomes a `VisitorMessage`.

Who calls what (amended 2026-09-09, BL-SS-183): `POST /session` is called by
the LOADER from the customer's top-level page (that is the only way its
`Origin` can carry the embedding website); `POST /messages`, `GET /messages`
and the WS are called by the PANEL from inside the iframe, carry the app's
own origin, and are authorized by the Bearer visitor token alone.
`GET /frame-policy` is read server-side by the Next.js middleware.
"""
import hashlib
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db
from app.services.throttle import ThrottleService, Throttled, client_ip

from ..schemas import (
    VisitorMessage,
    WebchatMessageRequest,
    WebchatMessagesPage,
    WebchatSessionRequest,
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
    resolve_frame_policy,
    resolve_live_channel,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _throttle_tag(raw: str) -> str:
    """A stable, non-reversible tag for a throttled caller (review round 1,
    S7). An operator correlating repeated 429s never needs the IP itself in
    a log line, and this surface is anonymous internet traffic - the address
    is the only identifying thing about it."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


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


def _rate_limited(retry_after_seconds: int, *, route: str, bucket: str, key: str) -> ApiError:
    """The 429 AND the one operator-facing signal this surface emits (review
    round 1, S7). A throttled loader renders nothing at all on the customer's
    page by design (silent `.catch`), so without this line a widget that
    "randomly disappears" for a whole NAT'd office leaves no trace anywhere."""
    logger.warning(
        "webchat throttled: route=%s bucket=%s key=%s retry_after=%ss",
        route,
        bucket,
        _throttle_tag(key),
        retry_after_seconds,
    )
    return ApiError(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "rate_limited",
        "Too many attempts - try again later.",
    ).with_retry_after(retry_after_seconds)


def _invalid_body(field_errors: Dict[str, str]) -> ApiError:
    """The typed 422 for a body whose SHAPE is wrong (review round 1, S1).
    Keeps this surface's ONE error envelope (`{"error": {...}}`, never the
    `{detail: ...}` shape) and carries the house `{fieldErrors}` map in
    `details` so a caller can point at the offending key."""
    return ApiError(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "invalid_request",
        "Request body is not valid.",
        {"fieldErrors": field_errors},
    )


def _field_errors_of(exc: ValidationError) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()) if part != "body")
        out[loc or "body"] = err.get("msg", "Invalid value.")
    return out


@router.get("/{widget_key}/frame-policy")
def frame_policy(widget_key: str, request: Request, db: Session = Depends(get_db)) -> dict:
    """S4 (AC-WEB-47) - the panel document's `frame-ancestors` CSP source. The
    Next.js middleware (`middleware.ts`) reads this on every
    `/public/webchat/{widgetKey}` request and never renders the panel without
    the header. Read-only, zero DB writes, mirrors `/embed/frame-policy`
    (plan-11H): unknown/dead widget key -> empty list -> the middleware emits
    `frame-ancestors 'none'`.

    Review round 1 (S8) - two changes, both about cost rather than
    disclosure:

    1. The lookup is CACHED for 60s per widget key
       (`resolve_frame_policy`), so the common case costs zero DB queries
       instead of three. **Accepted staleness, not invalidated:** an origin
       edit, a channel deactivation or a module switch-off can take up to a
       minute to reach this header. Session start re-reads the live channel
       row on every call, so a stale allow here never lets anyone actually
       start a chat from a de-listed site - it only lets that site keep
       FRAMING the panel for up to a minute.
    2. It joins the webchat throttle bucket, but spends a token ONLY on a
       lookup that went to the database and resolved nothing - i.e. on key
       enumeration. Legitimate traffic arrives from the Next.js server's
       single IP, so counting it would let one busy deployment throttle its
       own panels off the air."""
    ip = client_ip(request)
    throttle = ThrottleService(db)
    try:
        throttle.enforce_webchat(ip=ip)
    except Throttled as exc:
        raise _rate_limited(exc.retry_after_seconds, route="frame-policy", bucket="ip", key=ip)
    origins, unresolved = resolve_frame_policy(db, widget_key)
    if unresolved:
        throttle.record_webchat(ip=ip)
    return {"allowedOrigins": origins}


@router.post("/{widget_key}/session")
async def start_session(
    widget_key: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> WebchatSessionResult:
    """AC-WEB-23/24/25/28/29 - throttled BEFORE any database work (AC-WEB-30);
    origin-checked; mints or renews a visitor token; NEVER writes a row
    (D-A7B-7).

    Amended 2026-09-09 (BL-SS-183): the caller is the LOADER, running in the
    customer's own top-level document, so the `Origin` header here really is
    the embedding website's - the value the channel allowlist is about, and
    one no other site can forge. The panel never calls this route: a fetch
    from inside the iframe would always carry the PANEL's origin, which made
    the check undecidable. The panel receives this response over
    postMessage from the loader."""
    ip = client_ip(request)
    throttle = ThrottleService(db)
    try:
        throttle.enforce_webchat(ip=ip)
    except Throttled as exc:
        raise _rate_limited(exc.retry_after_seconds, route="session", bucket="ip", key=ip)

    def spend_ip_token() -> None:
        throttle.record_webchat(ip=ip)

    try:
        body = await read_capped_json(request)
    except WebchatInvalidRequest as exc:
        spend_ip_token()
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code, exc.message)

    # Review round 1 (S1/N1) - the declared model is now actually used. It
    # is the ONLY thing between a hand-typed JSON scalar and
    # `verify_visitor_token(123, ...)` -> `AttributeError` -> 500 on an
    # unauthenticated surface whose whole contract is a uniform 404/401/422.
    # A malformed session body is just another session failure mode, so it
    # gets that same uniform 404 rather than a shape an attacker can use to
    # tell "this widget key is real" from "this body was wrong".
    try:
        parsed = WebchatSessionRequest.model_validate(body)
    except ValidationError:
        spend_ip_token()
        raise _uniform_404()

    try:
        channel = resolve_live_channel(db, widget_key)
    except WebchatNotFound:
        spend_ip_token()
        raise _uniform_404()

    origin = request.headers.get("origin")
    service = WebchatVisitorService(db)
    try:
        result, resumed = service.start_session(
            channel, origin=origin, token=parsed.token, identity=parsed.identity
        )
    except WebchatNotFound:
        spend_ip_token()
        raise _uniform_404()

    # S7 - a session start carrying a token that VERIFIED against this
    # channel is a page reload by a visitor who has already been here; it is
    # not an attempt at anything and must not eat one of a shared office
    # IP's tokens. Everything else (a fresh visitor, a revoked/foreign
    # token, any failure above) still counts.
    if not resumed:
        spend_ip_token()

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
    stores nothing (AC-WEB-32 - the router does not branch on it AT ALL, so
    the two responses cannot drift apart)."""
    ip = client_ip(request)
    throttle = ThrottleService(db)
    try:
        throttle.enforce_webchat(ip=ip)
    except Throttled as exc:
        raise _rate_limited(exc.retry_after_seconds, route="messages", bucket="ip", key=ip)
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
        raise _rate_limited(
            exc.retry_after_seconds, route="messages", bucket="visitor", key=claims.visitor_id
        )
    throttle.record_webchat(visitor_id=claims.visitor_id)

    try:
        body = await read_capped_json(request)
    except WebchatInvalidRequest as exc:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code, exc.message)

    origin = request.headers.get("origin")
    for key, value in cors_headers_for(channel, origin, allow_panel_origin=True).items():
        response.headers[key] = value

    # Review round 1 (S1) - typed BEFORE the service sees it. `{"hp": 1}` used
    # to reach `(1 or "").strip()` and 500; every scalar field is now checked
    # here, in the layer that owns request shape.
    try:
        parsed = WebchatMessageRequest.model_validate(body)
    except ValidationError as exc:
        raise _invalid_body(_field_errors_of(exc))

    payload: Dict[str, Any] = {
        "text": parsed.text,
        "preChat": parsed.preChat,
        "hp": parsed.hp,
        # AC-WEB-33 - the service refuses either key with a typed 422; they
        # are NOT on the model (a visitor has no media path at all), so they
        # ride through verbatim to keep that refusal exactly where it is.
        "media": body.get("media"),
        "mediaKey": body.get("mediaKey"),
    }
    try:
        item = service.post_message(channel, claims, payload)
    except WebchatInvalidRequest as exc:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code, exc.message)

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
    for key, value in cors_headers_for(channel, origin, allow_panel_origin=True).items():
        response.headers[key] = value

    data, next_after = service.history(channel, claims, after=after, limit=limit)
    return WebchatMessagesPage(data=[VisitorMessage(**item) for item in data], nextAfter=next_after)
