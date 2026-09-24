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
import re

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db

from ..schemas import PublicIdeaStatusOut
from ..services.public_status import PublicIdeaStatusService

router = APIRouter()

# 16-64 chars, URL-safe - matches ``secrets.token_urlsafe(24)`` output shape
# (AC-1603). Anything outside this shape is rejected before ever touching the
# database (also closes off path-traversal-flavoured tokens).
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")

_NOT_FOUND = "Not found."


@router.get("/{token}", response_model=PublicIdeaStatusOut)
def get_public_idea_status(token: str, db: Session = Depends(get_db)) -> PublicIdeaStatusOut:
    if not _TOKEN_RE.fullmatch(token or ""):
        raise ApiError(404, "not_found", _NOT_FOUND)

    view = PublicIdeaStatusService(db).resolve(token)
    if view is None:
        raise ApiError(404, "not_found", _NOT_FOUND)
    return view
