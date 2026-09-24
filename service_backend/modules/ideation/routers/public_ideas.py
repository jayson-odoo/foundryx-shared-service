"""Public idea status page router (S5, AC-1601..1604) - ``GET
/public/ideas/{token}``. No auth: the ``status_token`` itself is the
capability. Uniform ``{error:{code,message}}`` 404 for unknown, malformed, or
still-draft rows - never distinguishes "wrong token" from "not yours".

Lookup is by ``status_token`` alone, across EVERY tenant (the token is the
credential, not a tenant-scoped lookup) - deliberate exception to the "every
repository query is tenant-scoped" rule, matching the analogous public
document-share route.
"""
import re

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db
from app.models.status import Status

from ..models import Idea
from ..schemas import PublicIdeaStatusOut

router = APIRouter()

# 16-64 chars, URL-safe - matches ``secrets.token_urlsafe(24)`` output shape
# (AC-1603). Anything outside this shape is rejected before ever touching the
# database (also closes off path-traversal-flavoured tokens like "../etc/passwd").
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")

_NOT_FOUND = "Not found."


@router.get("/{token}", response_model=PublicIdeaStatusOut)
def get_public_idea_status(token: str, db: Session = Depends(get_db)) -> PublicIdeaStatusOut:
    if not _TOKEN_RE.fullmatch(token or ""):
        raise ApiError(404, "not_found", _NOT_FOUND)

    idea = db.query(Idea).filter(Idea.status_token == token).first()
    if idea is None:
        raise ApiError(404, "not_found", _NOT_FOUND)

    status_row = db.query(Status).filter(Status.id == idea.status_id).first()
    # A draft (or a row whose status somehow resolved to nothing) never has a
    # public status - uniform 404, same as "unknown token" (AC-1602).
    if status_row is None or status_row.key == "draft":
        raise ApiError(404, "not_found", _NOT_FOUND)

    return PublicIdeaStatusOut(
        title=idea.title, status=status_row.label, ideaNumber=idea.idea_number
    )
