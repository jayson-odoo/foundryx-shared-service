"""Ideation iframe-embed SSO router (PLAN-ideation-embed-sso §8/§9, AC-E-5..9).

PUBLIC (mounted with ``"public": true`` — no JWT/require_module gate; the
assertion signature / embed token IS the credential).

Endpoints:
  ``POST /embed/session``   — the SSO exchange. Verifies a host-minted assertion
                              against the connection's secret and mints a
                              short-lived embed token.
  ``POST /embed/validate``  — verify an embed token → its tenant scope (the
                              chrome-less FE page calls this to gate render).
  ``GET  /embed/ideas``     — embed-token-authed, tenant-scoped ideas list.
  ``GET  /embed/ideas/{id}``— embed-token-authed, tenant-scoped idea detail.

DISPATCH NOTE — ``POST /embed/session`` COLLIDES by path with the omnichannel
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

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db

from ..schemas import IdeaOut
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
        "scope": principal.scope,
    }


def require_embed_principal(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> EmbedTokenPrincipal:
    """Resolve the embed token from ``Authorization: Bearer <embed token>`` →
    tenant scope. 401 on any failure — the boundary is the backend, never the
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


@router.get("/ideas", response_model=List[IdeaOut])
def embed_list_ideas(
    search: Optional[str] = None,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> List[IdeaOut]:
    """Tenant-scoped ideas list for the embed page (AC-E-8). Reuses
    ``IdeaReadService`` — the tenant comes from the TOKEN, so a token for tenant A
    can never read tenant B (AC-E-8/12). Read-only; no ``myVote`` (no operator)."""
    return IdeaReadService(db).list(
        principal.tenant_id, search=search, filter="active", voter_id=None
    )


@router.get("/ideas/{idea_id}", response_model=IdeaOut)
def embed_get_idea(
    idea_id: str,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """Tenant-scoped idea detail for the embed page. 404 for an idea outside the
    token's tenant (cross-tenant read denied, AC-E-8/12)."""
    return IdeaReadService(db).get(principal.tenant_id, idea_id, voter_id=None)
