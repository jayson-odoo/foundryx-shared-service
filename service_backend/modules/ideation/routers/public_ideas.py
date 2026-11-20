"""Public idea status page router (S5, AC-1601..1604) - ``GET
/public/ideas/{token}``. No auth: the ``status_token`` itself is the
capability. Uniform ``{error:{code,message}}`` 404 for unknown, malformed, or
still-draft rows - never distinguishes "wrong token" from "not yours".

HTTP/Pydantic only (review round 1, blocking #2): the token-SHAPE check is
input validation (no DB access, so it stays here, same as a Pydantic field
validator would); the actual lookup lives in
``services/public_status.py::PublicIdeaStatusService`` - the router never
touches ``db.query`` directly.
"""
import hashlib
import re
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db
from app.services.throttle import Throttled, ThrottleService, client_ip

from ..schemas import IdeaCommentOut, PublicIdeaCommentCreate, PublicIdeaStatusOut
from ..services.comments import IdeaCommentService
from ..services.public_status import PublicIdeaStatusService

router = APIRouter()

# 16-64 chars, URL-safe - matches ``secrets.token_urlsafe(24)`` output shape
# (AC-1603). Anything outside this shape is rejected before ever touching the
# database (also closes off path-traversal-flavoured tokens).
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")

_NOT_FOUND = "Not found."


@router.get("/{token}", response_model=PublicIdeaStatusOut)
def get_public_idea_status(
    token: str, response: Response, db: Session = Depends(get_db)
) -> PublicIdeaStatusOut:
    if not _TOKEN_RE.fullmatch(token or ""):
        raise ApiError(404, "not_found", _NOT_FOUND)

    view = PublicIdeaStatusService(db).resolve(token)
    if view is None:
        raise ApiError(404, "not_found", _NOT_FOUND)
    # Issue #90 (AC-90-109): the page now carries idea content (problem/
    # solution/impact/department) - it must never sit in a shared cache.
    response.headers["Cache-Control"] = "no-store"
    # Optional hardening (review round 2): the token is a bearer credential
    # forwarded over WhatsApp/links - never let a search engine index it and
    # never leak it via an outbound Referer header from whatever this JSON
    # response might be embedded/linked into.
    response.headers["X-Robots-Tag"] = "noindex"
    response.headers["Referrer-Policy"] = "no-referrer"
    return view


def _no_index_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex"
    response.headers["Referrer-Policy"] = "no-referrer"


def _resolve_idea_or_404(token: str, db: Session):
    if not _TOKEN_RE.fullmatch(token or ""):
        raise ApiError(404, "not_found", _NOT_FOUND)
    idea = PublicIdeaStatusService(db).resolve_idea(token)
    if idea is None:
        raise ApiError(404, "not_found", _NOT_FOUND)
    return idea


@router.get("/{token}/comments", response_model=List[IdeaCommentOut])
def list_public_idea_comments(
    token: str, response: Response, db: Session = Depends(get_db)
) -> List[IdeaCommentOut]:
    """The thread of THIS idea (plan 19, AC-19-28): same shape as the operator
    list, flags always false, no author id. Same uniform 404 as the status page."""
    idea = _resolve_idea_or_404(token, db)
    _no_index_headers(response)
    return IdeaCommentService(db).list_public(idea)


@router.post(
    "/{token}/comments", response_model=IdeaCommentOut, status_code=status.HTTP_201_CREATED
)
def create_public_idea_comment(
    token: str,
    body: PublicIdeaCommentCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> IdeaCommentOut:
    """A visitor posts on the status page (AC-19-29/30). Body validation (422)
    runs before this handler, so an invalid post never reaches the throttle; only
    a SUCCESSFUL post consumes budget (5 per token, 20 per IP per window)."""
    idea = _resolve_idea_or_404(token, db)
    throttle = ThrottleService(db)
    ip = client_ip(request)
    token_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        throttle.enforce_idea_comment(ip=ip, token_key=token_key)
    except Throttled as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many comments. Try again later.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    service = IdeaCommentService(db)
    created = service.create_public(
        idea,
        body=body.body,
        parent_id=body.parentId,
        author_name=PublicIdeaStatusService(db).comment_author_name(idea),
    )
    throttle.record_idea_comment(ip=ip, token_key=token_key)
    _no_index_headers(response)
    return created
