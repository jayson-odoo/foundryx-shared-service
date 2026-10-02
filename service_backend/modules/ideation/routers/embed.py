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

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.api.v1.documents import _serve_blob
from app.database import get_db
from app.dependencies import effective_permission_keys
from app.models.user import UserStatus
from app.repositories.user_repository import UserRepository

from ..models import Idea
from ..schemas import (
    BoardOut,
    BusinessRequirementDetailOut,
    IdeaAttachmentOut,
    IdeaOut,
    IdeaUpdateIn,
    MergeIn,
    ReorderIn,
    StatusIn,
    VoteIn,
)
from ..services.actions import IdeaActionService
from ..services.attachments import IdeaAttachmentService
from ..services.business_requirements import BusinessRequirementService
from ..services.embed import (
    EmbedTokenPrincipal,
    IdeationEmbedError,
    resolve_embed_token,
    verify_and_mint,
)
from ..services.ideas import IdeaReadService
from ..services.merge import IdeaMergeService
from ..services.ownership import SubmitterIdentity, owned_ids

router = APIRouter()

EMBED_CONTENT_PREFIX = "/embed/ideas"
ATTACHMENT_CAP_BYTES = 25 * 1024 * 1024
PROMOTE_PERMISSION = "ideation.business_requirements.manage"


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


class EmbedPromoteIn(BaseModel):
    ideaIds: List[str] = Field(..., min_length=1, max_length=100)
    title: str = ""


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


def _assert_in_scope(db: Session, principal: EmbedTokenPrincipal, idea_id: str) -> None:
    """Scope guard ONLY - tenant + product (404 for either mismatch), never
    mutated, never leaked (AC-CAP-11). Review round 1 #7: this is a LIGHT raw
    ``(id, tenant_id, product_id)`` row load, not a full ``IdeaOut`` serialize
    (no rank-lane scan, no transitions, no attachments) - merge/reorder call
    this PER id in a loop, so a full serialize here would be O(N^2) on a bulk
    request. A handler that actually needs the serialized idea for its
    response (``embed_get_idea``) does its OWN ``IdeaReadService.get`` call
    after this passes."""
    idea = (
        db.query(Idea.id, Idea.tenant_id, Idea.product_id)
        .filter(Idea.id == idea_id, Idea.tenant_id == principal.tenant_id)
        .first()
    )
    if idea is None:
        raise ApiError(404, "not_found", "Idea not found.")
    if principal.product_id and idea.product_id != principal.product_id:
        raise ApiError(404, "not_found", "Idea not found.")


def _viewer(principal: EmbedTokenPrincipal) -> SubmitterIdentity:
    """The viewing CRM user's ownership identity (SS-IDEATION-OWN): the assertion
    ``sub`` (CRM user id) + the optional ``phone`` claim. Never the name."""
    return SubmitterIdentity(crm_user_id=principal.sub, phone=principal.phone)


def _mark_mine(
    db: Session, principal: EmbedTokenPrincipal, outs: List[IdeaOut]
) -> List[IdeaOut]:
    """Stamp ``isMine`` for the viewing CRM user on serialized ideas (the shared
    read/action services serialize without a viewer). One ownership query for
    the whole batch, tenant-scoped."""
    mine = owned_ids(db, principal.tenant_id, [o.id for o in outs], _viewer(principal))
    return [o.model_copy(update={"isMine": o.id in mine}) for o in outs]


def _mark_one(db: Session, principal: EmbedTokenPrincipal, out: IdeaOut) -> IdeaOut:
    return _mark_mine(db, principal, [out])[0]


def _assert_can_manage(
    db: Session, principal: EmbedTokenPrincipal, idea_ids: List[str]
) -> None:
    """Owner rule (SS-IDEATION-OWN): when the host sent ``ideas_manage=false`` the
    viewer may only change their OWN ideas (edit / status / delete / reorder /
    merge / unmerge / attach) - anything else is 403 ``not_owner``. Voting stays
    open to everyone. ``ideas_manage`` true or absent keeps today's behaviour,
    so hosts that do not send the claim are unaffected."""
    if principal.ideas_manage is not False:
        return
    ids = list(dict.fromkeys(i for i in idea_ids if i))
    mine = owned_ids(db, principal.tenant_id, ids, _viewer(principal))
    if any(i not in mine for i in ids):
        raise ApiError(403, "not_owner", "You can only change ideas you submitted.")


@router.get("/ideas", response_model=List[IdeaOut])
def embed_list_ideas(
    search: Optional[str] = None,
    filter: str = "active",
    mine: bool = False,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> List[IdeaOut]:
    """Product-scoped ideas list for the embed page (AC-CAP-11). Reuses
    ``IdeaReadService`` - the tenant AND product come from the TOKEN, so a token
    for tenant A / product X can never read tenant B or another product
    (AC-E-8/12). ``product_id=None`` (unscoped connection) falls back to
    tenant-only (today's behaviour).

    SS-IDEATION-OWN: every idea carries ``isMine`` for the viewing CRM user, and
    ``mine=true`` narrows to the viewer's own ideas (CRM user id or ``phone``
    claim - never name; no identity = an empty list, never "all")."""
    outs = IdeaReadService(db, EMBED_CONTENT_PREFIX).list(
        principal.tenant_id,
        search=search,
        filter=filter,
        product_id=principal.product_id,
        voter_id=_embed_voter_id(principal),
        owner=_viewer(principal) if mine else None,
    )
    return _mark_mine(db, principal, outs)


@router.get("/board", response_model=BoardOut)
def embed_get_board(
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> BoardOut:
    """Product-scoped triage board for the embed page (full operator parity,
    AC-CAP-9/11). Same board columns as the operator surface, scoped to the
    connection's tenant + product. Cards carry ``isMine`` for the viewer."""
    board = IdeaReadService(db, EMBED_CONTENT_PREFIX).board(
        principal.tenant_id,
        voter_id=_embed_voter_id(principal),
        product_id=principal.product_id,
    )
    for col in board.columns:
        col.ideas = _mark_mine(db, principal, col.ideas)
    return board


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
    _assert_can_manage(db, principal, list(body.orderedIds))
    ordered = IdeaActionService(db).reorder(
        principal.tenant_id, body.orderedIds, voter_id=voter_id
    )
    # Only surface the connection's product in the response (the service returns
    # every tenant idea by priority - filter so an unscoped column never leaks).
    if principal.product_id:
        ordered = [o for o in ordered if o.productId == principal.product_id]
    return _mark_mine(db, principal, ordered)


@router.post("/ideas/merge", response_model=IdeaOut)
def embed_merge_ideas(
    body: MergeIn,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """Merge ideas from the iframe (AC-94-16). Every id (survivor + members)
    must resolve inside the connection's tenant+product - any id outside the
    scope denies the WHOLE merge (404) and nothing is written."""
    for idea_id in dict.fromkeys([body.survivorId, *body.ideaIds]):
        _assert_in_scope(db, principal, idea_id)
    _assert_can_manage(db, principal, [body.survivorId, *body.ideaIds])
    return _mark_one(
        db,
        principal,
        IdeaMergeService(db).merge(principal.tenant_id, body.survivorId, body.ideaIds),
    )


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
    out = IdeaActionService(db).create_operator(
        principal.tenant_id,
        product_id=principal.product_id,
        problem=body.problem,
        proposed_solution=body.proposedSolution,
        impact=body.impact,
        department=body.department,
        raw_text=body.rawText,
        source=(body.source or "embed"),
        actor=None,
        # The viewing CRM user is the submitter (the isMine ownership link).
        submitter_crm_user_id=principal.sub,
        submitter_name=principal.name,
    )
    return _mark_one(db, principal, out)


@router.post(
    "/ideas/promote",
    response_model=BusinessRequirementDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def embed_promote_ideas(
    body: EmbedPromoteIn,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> BusinessRequirementDetailOut:
    """Promote ideas to a draft Business Requirement from the iframe (AC-15-20).
    The token's ``email`` claim resolves to a shared-service user in the token's
    tenant, who must hold the operator's ``ideation.business_requirements.manage``
    (no widening). Every id is scope-checked BEFORE anything is created."""
    user = (
        UserRepository(db).get_by_email(principal.email, principal.tenant_id)
        if principal.email
        else None
    )
    # Same lifecycle rules as sign-in / `get_current_user`: an inactive user or a
    # tenant that cannot sign in never promotes via a still-valid embed token.
    if (
        user is None
        or user.status != UserStatus.ACTIVE.value
        or user.tenant is None
        or not user.tenant.signin_allowed
        or PROMOTE_PERMISSION not in effective_permission_keys(user)
    ):
        raise ApiError(403, "forbidden", "You do not have permission to promote ideas.")
    for idea_id in dict.fromkeys(body.ideaIds):
        _assert_in_scope(db, principal, idea_id)
    product_id = principal.product_id or IdeaReadService(db).single_product_id(
        principal.tenant_id, body.ideaIds
    )
    return BusinessRequirementService(db).create(
        principal.tenant_id,
        product_id=product_id,
        title=body.title,
        idea_ids=body.ideaIds,
        actor=user,
    )


@router.post(
    "/ideas/{idea_id}/attachments",
    response_model=IdeaAttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def embed_upload_attachment(
    idea_id: str,
    file: UploadFile = File(...),
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> IdeaAttachmentOut:
    """Upload a file onto an idea from the iframe. Scoped to tenant+product (404
    otherwise); the token is the boundary (no operator permission)."""
    _assert_in_scope(db, principal, idea_id)
    _assert_can_manage(db, principal, [idea_id])
    content = await file.read(ATTACHMENT_CAP_BYTES + 1)
    if len(content) > ATTACHMENT_CAP_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large.")
    return IdeaAttachmentService(db).upload(
        principal.tenant_id,
        idea_id,
        file.filename or "",
        content,
        content_prefix=EMBED_CONTENT_PREFIX,
    )


@router.get("/ideas/{idea_id}/attachments/{attachment_id}/content")
def embed_attachment_content(
    idea_id: str,
    attachment_id: str,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
):
    """Serve an uploaded attachment CSP-sandboxed + nosniff. Scoped to
    tenant+product (404 otherwise)."""
    _assert_in_scope(db, principal, idea_id)
    key, mime, filename = IdeaAttachmentService(db).content(
        principal.tenant_id, idea_id, attachment_id
    )
    return _serve_blob(db, principal.tenant_id, key, mime, filename, "inline")


@router.get("/ideas/{idea_id}", response_model=IdeaOut)
def embed_get_idea(
    idea_id: str,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """Product-scoped idea detail for the embed page. 404 for an idea outside the
    token's tenant OR product (cross-tenant/cross-product read denied,
    AC-CAP-11)."""
    _assert_in_scope(db, principal, idea_id)
    out = IdeaReadService(db, EMBED_CONTENT_PREFIX).get(
        principal.tenant_id, idea_id, voter_id=None, product_id=principal.product_id
    )
    return _mark_one(db, principal, out)


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
    _assert_can_manage(db, principal, [idea_id])
    out = IdeaActionService(db).update_operator(
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
    return _mark_one(db, principal, out)


@router.get("/ideas/{idea_id}/merged", response_model=List[IdeaOut])
def embed_list_merged_ideas(
    idea_id: str,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> List[IdeaOut]:
    """The ideas merged into this one, from the iframe (AC-94-16). Scoped to
    tenant+product (404 otherwise)."""
    _assert_in_scope(db, principal, idea_id)
    return _mark_mine(
        db,
        principal,
        IdeaReadService(db, EMBED_CONTENT_PREFIX).merged_children(
            principal.tenant_id, idea_id, voter_id=_embed_voter_id(principal)
        ),
    )


@router.post("/ideas/{idea_id}/unmerge", response_model=List[IdeaOut])
def embed_unmerge_idea(
    idea_id: str,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> List[IdeaOut]:
    """Restore a merged child, or dissolve a survivor's whole group, from the
    iframe (AC-94-16). Scoped to tenant+product (404 otherwise)."""
    _assert_in_scope(db, principal, idea_id)
    _assert_can_manage(db, principal, [idea_id])
    return _mark_mine(db, principal, IdeaMergeService(db).unmerge(principal.tenant_id, idea_id))


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
    out = IdeaActionService(db).vote(
        principal.tenant_id, idea_id, _embed_voter_id(principal), body.dir
    )
    return _mark_one(db, principal, out)


@router.post("/ideas/{idea_id}/status", response_model=IdeaOut)
def embed_set_idea_status(
    idea_id: str,
    body: StatusIn,
    principal: EmbedTokenPrincipal = Depends(require_embed_principal),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """Move the idea to a lifecycle status - by key or by status-engine
    ``toStatusId`` (issue #94). Server-authoritative (illegal moves refused,
    409). Scoped to tenant+product (404 otherwise). ``actor=None`` - there is
    no operator user in the iframe."""
    _assert_in_scope(db, principal, idea_id)
    _assert_can_manage(db, principal, [idea_id])
    out = IdeaActionService(db).set_status(
        principal.tenant_id,
        idea_id,
        body.status,
        actor=None,
        voter_id=_embed_voter_id(principal),
        to_status_id=body.toStatusId,
    )
    return _mark_one(db, principal, out)


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
    _assert_can_manage(db, principal, [idea_id])
    IdeaActionService(db).delete(principal.tenant_id, idea_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
