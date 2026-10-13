"""Idea portal router (lane IDEA-PORTAL) - ``/portal/ideas/*``.

Mounted ``"public": true`` (no core JWT / ``require_module`` gate at mount):
every route below is gated by a PORTAL token (``require_portal_principal``),
except the two session exchanges, each of which authenticates with its own
credential (core staff login / ideation embed token). Staff only - dealers
cannot sign in (owner Q1). The portal-token resolve re-checks tenant sign-in +
module ACTIVE + the user / connection per request.

HTTP + Pydantic only; every query lives in ``services/portal.py``.
"""
from typing import List, Optional

from typing import Callable

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db
from app.dependencies import get_current_user, get_real_user
from app.models.user import User

from ..schemas import (
    IdeaCommentCreate,
    PortalActivityOut,
    PortalChangelogOut,
    PortalCommentOut,
    PortalEmbedSessionIn,
    PortalHiddenIn,
    PortalIdeaCreateIn,
    PortalIdeaOut,
    PortalLikeOut,
    PortalListOut,
    PortalNoteIn,
    PortalPrincipalOut,
    PortalProductOut,
    PortalRoadmapOut,
    PortalSessionOut,
    PortalVoteOut,
    PortalVoterOut,
)
from ..services.portal import (
    IdeaPortalService,
    PortalError,
    PortalPrincipal,
    principal_out,
    resolve_portal_token,
    session_for_embed,
    session_for_staff,
)

NO_STORE_HEADERS = {
    # Ideas can carry internal business detail: never cache, never index.
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex",
    "Referrer-Policy": "no-referrer",
}


class _NoStoreRoute(APIRoute):
    """Security review #4: stamp the private headers on EVERY response of this
    router - errors (401/403/404/422/429) included, which build their own
    response and would otherwise drop headers set on the dependency's."""

    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            try:
                response = await handler(request)
            except Exception as exc:  # noqa: BLE001 - converted by the app's own handler
                convert = None
                for cls in type(exc).__mro__:
                    convert = request.app.exception_handlers.get(cls)
                    if convert is not None:
                        break
                if convert is None:
                    raise
                response = await convert(request, exc)
            response.headers.update(NO_STORE_HEADERS)
            return response

        return wrapped


router = APIRouter(route_class=_NoStoreRoute)
MAX_COLUMNS = 20


def _raise(exc: PortalError):
    if exc.status_code == 429:
        from fastapi import HTTPException

        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            exc.message,
            headers={"Retry-After": str(exc.retry_after or 60)},
        )
    raise ApiError(exc.status_code, exc.code, exc.message)


def _private(response: Response) -> None:
    # Ideas can carry internal business detail: never cache, never index.
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex"
    response.headers["Referrer-Policy"] = "no-referrer"


def require_portal_principal(
    response: Response,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> PortalPrincipal:
    token = None
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
    if not token:
        raise ApiError(401, "unauthorized", "Sign in to continue.")
    try:
        principal = resolve_portal_token(db, token)
    except PortalError as exc:
        _raise(exc)
    _private(response)
    return principal


def _svc(db: Session, p: PortalPrincipal) -> IdeaPortalService:
    return IdeaPortalService(db, p)


# ── sessions ──────────────────────────────────────────────────────────────────


@router.post("/session/staff", response_model=PortalSessionOut)
def staff_session(
    response: Response,
    user: User = Depends(get_current_user),
    real_user: User = Depends(get_real_user),
    db: Session = Depends(get_db),
):
    _private(response)
    try:
        return session_for_staff(db, user, impersonating=user.id != real_user.id)
    except PortalError as exc:
        _raise(exc)


@router.post("/session/embed", response_model=PortalSessionOut)
def embed_session(body: PortalEmbedSessionIn, response: Response, db: Session = Depends(get_db)):
    _private(response)
    try:
        return session_for_embed(db, body.token)
    except PortalError as exc:
        _raise(exc)


@router.get("/me", response_model=PortalPrincipalOut)
def me(p: PortalPrincipal = Depends(require_portal_principal)):
    return principal_out(p)


# ── reads ─────────────────────────────────────────────────────────────────────


@router.get("/roadmap", response_model=PortalRoadmapOut)
def roadmap(
    productId: Optional[str] = None,
    mine: bool = False,
    p: PortalPrincipal = Depends(require_portal_principal),
    db: Session = Depends(get_db),
):
    return _svc(db, p).roadmap(product_id=productId, mine=mine)


@router.get("/changelog", response_model=PortalChangelogOut)
def changelog(p: PortalPrincipal = Depends(require_portal_principal), db: Session = Depends(get_db)):
    return _svc(db, p).changelog()


@router.get("/products", response_model=List[PortalProductOut])
def products(p: PortalPrincipal = Depends(require_portal_principal), db: Session = Depends(get_db)):
    return _svc(db, p).products()


@router.get("", response_model=PortalListOut)
def list_ideas(
    q: Optional[str] = Query(default=None, max_length=200),
    column: Optional[List[str]] = Query(default=None),
    sort: str = Query(default="top", pattern="^(top|new)$"),
    mine: bool = False,
    productId: Optional[str] = None,
    includeClosed: bool = False,
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=25, ge=1, le=100),
    p: PortalPrincipal = Depends(require_portal_principal),
    db: Session = Depends(get_db),
):
    if column and len(column) > MAX_COLUMNS:
        raise ApiError(422, "too_many_columns", "Too many status filters.")
    return _svc(db, p).list(
        q=q, columns=column, sort=sort, mine=mine, product_id=productId,
        include_closed=includeClosed, page=page, page_size=pageSize,
    )


@router.post("", response_model=PortalIdeaOut, status_code=status.HTTP_201_CREATED)
def submit_idea(
    body: PortalIdeaCreateIn,
    p: PortalPrincipal = Depends(require_portal_principal),
    db: Session = Depends(get_db),
):
    try:
        return _svc(db, p).submit(
            title=body.title,
            problem=body.problem,
            product_id=body.productId,
            desired_outcome=body.desiredOutcome,
            use_cases=body.useCases,
            current_workaround=body.currentWorkaround,
        )
    except PortalError as exc:
        _raise(exc)


@router.get("/{idea_id}", response_model=PortalIdeaOut)
def idea_detail(idea_id: str, p: PortalPrincipal = Depends(require_portal_principal), db: Session = Depends(get_db)):
    try:
        return _svc(db, p).detail(idea_id)
    except PortalError as exc:
        _raise(exc)


@router.put("/{idea_id}/hidden", response_model=PortalIdeaOut)
def set_hidden(
    idea_id: str,
    body: PortalHiddenIn,
    p: PortalPrincipal = Depends(require_portal_principal),
    db: Session = Depends(get_db),
):
    try:
        return _svc(db, p).set_hidden(idea_id, body.hidden)
    except PortalError as exc:
        _raise(exc)


@router.put("/{idea_id}/note", response_model=PortalIdeaOut)
def set_note(
    idea_id: str,
    body: PortalNoteIn,
    p: PortalPrincipal = Depends(require_portal_principal),
    db: Session = Depends(get_db),
):
    try:
        return _svc(db, p).set_note(idea_id, body.note)
    except PortalError as exc:
        _raise(exc)


@router.post("/{idea_id}/vote", response_model=PortalVoteOut)
def vote(idea_id: str, p: PortalPrincipal = Depends(require_portal_principal), db: Session = Depends(get_db)):
    try:
        return _svc(db, p).vote(idea_id)
    except PortalError as exc:
        _raise(exc)


@router.get("/{idea_id}/voters", response_model=List[PortalVoterOut])
def voters(idea_id: str, p: PortalPrincipal = Depends(require_portal_principal), db: Session = Depends(get_db)):
    try:
        return _svc(db, p).voters(idea_id)
    except PortalError as exc:
        _raise(exc)


@router.get("/{idea_id}/activity", response_model=List[PortalActivityOut])
def activity(
    idea_id: str,
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    p: PortalPrincipal = Depends(require_portal_principal),
    db: Session = Depends(get_db),
):
    try:
        return _svc(db, p).activity(idea_id, order=order)
    except PortalError as exc:
        _raise(exc)


@router.get("/{idea_id}/comments", response_model=List[PortalCommentOut])
def comments(idea_id: str, p: PortalPrincipal = Depends(require_portal_principal), db: Session = Depends(get_db)):
    try:
        return _svc(db, p).comments(idea_id)
    except PortalError as exc:
        _raise(exc)


@router.post("/{idea_id}/comments", response_model=PortalCommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(
    idea_id: str,
    body: IdeaCommentCreate,
    p: PortalPrincipal = Depends(require_portal_principal),
    db: Session = Depends(get_db),
):
    if len(body.body) > 2000:
        raise ApiError(422, "too_long", "Comments can be at most 2000 characters.")
    try:
        return _svc(db, p).add_comment(idea_id, body=body.body, parent_id=body.parentId)
    except PortalError as exc:
        _raise(exc)


@router.delete("/{idea_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    idea_id: str,
    comment_id: str,
    p: PortalPrincipal = Depends(require_portal_principal),
    db: Session = Depends(get_db),
):
    try:
        _svc(db, p).delete_comment(idea_id, comment_id)
    except PortalError as exc:
        _raise(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{idea_id}/comments/{comment_id}/like", response_model=PortalLikeOut)
def like_comment(
    idea_id: str,
    comment_id: str,
    p: PortalPrincipal = Depends(require_portal_principal),
    db: Session = Depends(get_db),
):
    try:
        return _svc(db, p).toggle_like(idea_id, comment_id)
    except PortalError as exc:
        _raise(exc)
