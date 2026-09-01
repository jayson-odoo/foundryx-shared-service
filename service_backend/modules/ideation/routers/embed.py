"""Ideation iframe-embed SSO router (PLAN-ideation-embed-sso §8/§9, AC-E-5..9).

PUBLIC (mounted with ``"public": true`` - no JWT/require_module gate; the
assertion signature / embed token IS the credential).

Endpoints:
  ``POST /embed/session``   - the SSO exchange. Verifies a host-minted assertion
                              against the connection's secret and mints a
                              short-lived embed token.
  ``POST /embed/validate``  - verify an embed token → its tenant scope (the
                              chrome-less FE page calls this to gate render).
  ``GET  /embed/ideas``     - embed-token-authed, tenant-scoped ideas list.
  ``GET  /embed/ideas/{id}``- embed-token-authed, tenant-scoped idea detail.

DISPATCH NOTE - ``POST /embed/session`` COLLIDES by path with the omnichannel
widget's own ``POST /embed/session`` (both modules mount at prefix ``/embed``;
the module loader wires ideation BEFORE omnichannel alphabetically, so THIS route
wins the match). To preserve omnichannel embed, this handler dispatches: a body
carrying ``connection_id`` is an ideation SSO request (sorento always sends it);
a body WITHOUT ``connection_id`` is delegated verbatim to the omnichannel handler
(throttle + envelope intact). ``/embed/frame-policy`` (omnichannel-only) and
``/embed/validate`` + ``/embed/ideas`` (ideation-only) don't collide.

Secrets are never logged.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db

from ..schemas import (
    BoardOut,
    IdeaOut,
    IdeaUpdateIn,
    ReorderIn,
    StatusIn,
    VoteIn,
)
from ..services.actions import IdeaActionService
from ..services.embed import (
    EmbedTokenPrincipal,
    IdeationEmbedError,
    resolve_embed_token,
    verify_and_mint,
)
from ..services.ideas import IdeaReadService

router = APIRouter()


class EmbedSessionBody(BaseModel):
    assertion: str
    # Present iff this is an ideation SSO request (sorento always sends it). Its
    # absence routes the request to the omnichannel embed handler.
    connection_id: Optional[str] = None
    idea_id: Optional[str] = None
    # Omnichannel-only field, carried through on delegation.
    parentOrigin: Optional[str] = None


class EmbedValidateBody(BaseModel):
    token: str


class EmbedIdeaCreateIn(BaseModel):
    """Embed-mode idea create - mirrors ``IdeaCreateIn`` MINUS ``productId`` (the
    product is FORCED to the connection's ``principal.product_id`` server-side, so
    the iframe never chooses/leaks another product). All other fields match the
    operator create contract."""

    problem: str
    proposedSolution: Optional[str] = None
    impact: Optional[str] = None
    department: Optional[str] = None
    rawText: str = ""
    source: str = "embed"


@router.post("/session")
def create_embed_session(
    payload: EmbedSessionBody,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    # No connection_id → not an ideation request; hand off to omnichannel so its
    # widget embed keeps working (this route shadows omnichannel's identical path).
    if not payload.connection_id:
        from modules.omnichannel.routers.embed import (
            EmbedSessionRequest as OmniEmbedRequest,
        )
        from modules.omnichannel.routers.embed import (
            create_embed_session as omni_create_embed_session,
        )

        return omni_create_embed_session(
            OmniEmbedRequest(assertion=payload.assertion, parentOrigin=payload.parentOrigin),
            request,
            db,
        )

    try:
        return verify_and_mint(
            db,
            connection_id=payload.connection_id,
            assertion=payload.assertion,
            idea_id=payload.idea_id,
        )
    except IdeationEmbedError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message)


@router.post("/validate")
def validate_embed_token(payload: EmbedValidateBody, db: Session = Depends(get_db)) -> dict:
    """Verify an embed token and return its tenant scope (AC-E-8). The FE embed
    page calls this to decide render-vs-``session expired``; a bad/expired token
    → 401 (never leaks another tenant)."""
    try:
        principal = resolve_embed_token(db, payload.token)
    except IdeationEmbedError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message)
    return {
        "tenant_id": principal.tenant_id,
        "connection_id": principal.connection_id,
        "idea_id": principal.idea_id,
        "product_id": principal.product_id,
        "scope": principal.scope,
    }


def require_embed_principal(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> EmbedTokenPrincipal:
    """Resolve the embed token from ``Authorization: Bearer <embed token>`` →
    tenant scope. 401 on any failure - the boundary is the backend, never the
    iframe."""
    token: Optional[str] = None
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
    if not token:
        raise ApiError(401, "invalid_token", "Missing embed token.")
    try:
        return resolve_embed_token(db, token)
    except IdeationEmbedError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message)


def _embed_voter_id(principal: EmbedTokenPrincipal) -> str:
    """Voter identity for embed writes = the HOST (sorento) USER, taken from the
    assertion ``sub`` the host minted (``mint_embed_assertion`` sets it to the
    logged-in user id). This makes voting per-sorento-user: two different users
    each cast a distinct up/down vote on the same idea (1 up + 1 down), instead of
    one shared vote per connection. Namespaced ``embed-user:`` so it never collides
    with a shared-service operator ``users.id``. Falls back to the connection only
    when no user is present in the token (e.g. a service assertion)."""
    sub = (principal.sub or "").strip()
    if sub:
        return f"embed-user:{sub}"
    return f"embed:{principal.connection_id}"


def _assert_in_scope(
    db: Session, principal: EmbedTokenPrincipal, idea_id: str
) -> IdeaOut:
    """Resolve an idea scoped to ``principal.tenant_id`` (404 if outside the
    tenant), then enforce the PRODUCT scope: when the connection is product-scoped
    (``principal.product_id`` set) an idea in the same tenant but a DIFFERENT
    product is denied (404) - never mutated, never leaked (AC-CAP-11). When the
    connection is tenant-only (no product), tenant scope is the whole guard."""
    idea = IdeaReadService(db).get(principal.tenant_id, idea_id, voter_id=None)
    if principal.product_id and idea.productId != principal.product_id:
        raise ApiError(404, "not_found", "Idea not found.")
    return idea


@router.get("/ideas", response_model=List[IdeaOut])
def embed_list_ideas(
    search: Optional[str] = None,
    filter: str = "active",
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> List[IdeaOut]:
    """Product-scoped ideas list for the embed page (AC-CAP-11). Reuses
    ``IdeaReadService`` - the tenant AND product come from the TOKEN, so a token
    for tenant A / product X can never read tenant B or another product
    (AC-E-8/12). ``product_id=None`` (unscoped connection) falls back to
    tenant-only (today's behaviour)."""
    return IdeaReadService(db).list(
        principal.tenant_id,
        search=search,
        filter=filter,
        product_id=principal.product_id,
        voter_id=_embed_voter_id(principal),
    )


@router.get("/board", response_model=BoardOut)
def embed_get_board(
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> BoardOut:
    """Product-scoped triage board for the embed page (full operator parity,
    AC-CAP-9/11). Same board columns as the operator surface, scoped to the
    connection's tenant + product."""
    return IdeaReadService(db).board(
        principal.tenant_id,
        voter_id=_embed_voter_id(principal),
        product_id=principal.product_id,
    )


# ── embed-authed write routes (full operator parity, G1/G2 - dedicated /embed/*
#    routes, each asserting tenant+product scope; declared BEFORE /ideas/{id}
#    so static paths win the match) ──────────────────────────────────────────


@router.put("/ideas/reorder", response_model=List[IdeaOut])
def embed_reorder_ideas(
    body: ReorderIn,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> List[IdeaOut]:
    """Set manual priority from the given id order. Every id must resolve inside
    the connection's tenant+product - any id outside the scope is denied (404)
    and NOTHING is reordered (no cross-product mutation, AC-CAP-11)."""
    voter_id = _embed_voter_id(principal)
    for idea_id in body.orderedIds:
        _assert_in_scope(db, principal, idea_id)
    ordered = IdeaActionService(db).reorder(
        principal.tenant_id, body.orderedIds, voter_id=voter_id
    )
    # Only surface the connection's product in the response (the service returns
    # every tenant idea by priority - filter so an unscoped column never leaks).
    if principal.product_id:
        return [o for o in ordered if o.productId == principal.product_id]
    return ordered


@router.post("/ideas", response_model=IdeaOut, status_code=status.HTTP_201_CREATED)
def embed_create_idea(
    body: EmbedIdeaCreateIn,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """Create an idea from the iframe (full parity). The product is FORCED to the
    connection's ``product_id`` - a create is rejected (403) when the connection
    is not product-scoped (there is no product to attribute the idea to)."""
    if not principal.product_id:
        raise ApiError(
            403,
            "embed_scope_required",
            "This embed connection is not scoped to a product; create is unavailable.",
        )
    return IdeaActionService(db).create_operator(
        principal.tenant_id,
        product_id=principal.product_id,
        problem=body.problem,
        proposed_solution=body.proposedSolution,
        impact=body.impact,
        department=body.department,
        raw_text=body.rawText,
        source=(body.source or "embed"),
        actor=None,
    )


@router.get("/ideas/{idea_id}", response_model=IdeaOut)
def embed_get_idea(
    idea_id: str,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """Product-scoped idea detail for the embed page. 404 for an idea outside the
    token's tenant OR product (cross-tenant/cross-product read denied,
    AC-CAP-11)."""
    return _assert_in_scope(db, principal, idea_id)


@router.patch("/ideas/{idea_id}", response_model=IdeaOut)
def embed_update_idea(
    idea_id: str,
    body: IdeaUpdateIn,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """Edit the mutable idea fields from the iframe. Scoped to tenant+product;
    the idea's product is NOT reassignable via the embed (``productId`` in the
    body is ignored) so an idea can never be moved out of the connection's scope."""
    _assert_in_scope(db, principal, idea_id)
    return IdeaActionService(db).update_operator(
        principal.tenant_id,
        idea_id,
        product_id=None,  # embed never reassigns the product (scope integrity)
        problem=body.problem,
        proposed_solution=body.proposedSolution,
        impact=body.impact,
        department=body.department,
        raw_text=body.rawText,
        voter_id=_embed_voter_id(principal),
    )


@router.post("/ideas/{idea_id}/vote", response_model=IdeaOut)
def embed_vote_idea(
    idea_id: str,
    body: VoteIn,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """Toggle the connection's vote on an idea (one synthetic voter per
    connection). Scoped to tenant+product (404 otherwise)."""
    _assert_in_scope(db, principal, idea_id)
    return IdeaActionService(db).vote(
        principal.tenant_id, idea_id, _embed_voter_id(principal), body.dir
    )


@router.post("/ideas/{idea_id}/status", response_model=IdeaOut)
def embed_set_idea_status(
    idea_id: str,
    body: StatusIn,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """Move the idea to a lifecycle status by key. Server-authoritative (illegal
    moves refused, 409). Scoped to tenant+product (404 otherwise). ``actor=None``
    - there is no operator user in the iframe."""
    _assert_in_scope(db, principal, idea_id)
    return IdeaActionService(db).set_status(
        principal.tenant_id,
        idea_id,
        body.status,
        actor=None,
        voter_id=_embed_voter_id(principal),
    )


@router.delete("/ideas/{idea_id}", status_code=status.HTTP_204_NO_CONTENT)
def embed_delete_idea(
    idea_id: str,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete an idea from the iframe (full parity, G1). Scoped to
    tenant+product - a delete targeting another product is denied (404) before
    any row is touched."""
    _assert_in_scope(db, principal, idea_id)
    IdeaActionService(db).delete(principal.tenant_id, idea_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
