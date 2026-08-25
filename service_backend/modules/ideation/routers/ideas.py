"""Ideas router (operator surface) - gated by ``require_module("ideation")``
(injected by the module loader) + the relevant ``ideation.*`` permission.

Slice 3 added the read surface (list + detail, AC-A-12). Slice 4 adds the write
actions the FE prototype calls: vote (``ideation.ideas.upvote``), reorder /
status / delete (``ideation.triage.manage``). Status moves ride the core status
engine (server-authoritative - illegal moves refused)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import (
    BoardOut,
    BusinessRequirementOut,
    ClusterSuggestionsOut,
    IdeaCreateIn,
    IdeaOut,
    IdeaUpdateIn,
    ReorderIn,
    StatusIn,
    VoteIn,
)
from ..services.actions import IdeaActionService
from ..services.business_requirements import BusinessRequirementService
from ..services.clustering import ClusteringService
from ..services.ideas import IdeaReadService

router = APIRouter()


@router.get("", response_model=List[IdeaOut])
def list_ideas(
    search: Optional[str] = Query(None),
    filter: str = Query("active", pattern="^(active|archived|all)$"),
    product_id: Optional[str] = Query(None, alias="productId"),
    current_user: User = Depends(require_permission("ideation.ideas.view")),
    db: Session = Depends(get_db),
) -> List[IdeaOut]:
    """All ideas for the tenant, newest first. ``search`` matches problem/raw
    text; ``filter`` selects active (default) / archived / all; optional
    ``productId`` scopes to a single product (the canonical ideation scope -
    omitted = every product in the tenant). ``myVote`` is resolved for the
    calling user. Always tenant-scoped: the product filter never crosses tenants."""
    return IdeaReadService(db).list(
        current_user.tenant_id,
        search=search,
        filter=filter,
        product_id=product_id,
        voter_id=current_user.id,
    )


@router.post("", response_model=IdeaOut, status_code=status.HTTP_201_CREATED)
def create_idea(
    body: IdeaCreateIn,
    current_user: User = Depends(require_permission("ideation.ideas.submit")),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """Operator-facing in-app create (distinct from the conversational WhatsApp
    intake). No draft/collect/confirm gate - the idea is created straight into
    ``captured`` (rides the status engine ``draft → captured``), with the logged-in
    operator as submitter. Gated by ``ideation.ideas.submit``."""
    return IdeaActionService(db).create_operator(
        current_user.tenant_id,
        product_id=body.productId,
        problem=body.problem,
        proposed_solution=body.proposedSolution,
        impact=body.impact,
        department=body.department,
        raw_text=body.rawText,
        source=body.source,
        actor=current_user,
    )


# ── triage board + write actions (declared BEFORE /{idea_id} so static wins) ───


@router.get("/board", response_model=BoardOut)
def get_board(
    product_id: Optional[str] = Query(None, alias="productId"),
    current_user: User = Depends(require_permission("ideation.triage.manage")),
    db: Session = Depends(get_db),
) -> BoardOut:
    """Triage board (AC-A-33) - ideas grouped by lifecycle status column, in the
    board order, cards ordered by priority within a column. Optional ``productId``
    scopes to a single product (omitted = every product in the tenant). Triager
    surface - gated by ``ideation.triage.manage`` (403 without it, AC-A-37).
    Dragging a card across columns / within a column uses POST ``/{id}/status`` +
    PUT ``/reorder``."""
    return IdeaReadService(db).board(
        current_user.tenant_id, voter_id=current_user.id, product_id=product_id
    )


@router.put("/reorder", response_model=List[IdeaOut])
def reorder_ideas(
    body: ReorderIn,
    current_user: User = Depends(require_permission("ideation.triage.manage")),
    db: Session = Depends(get_db),
) -> List[IdeaOut]:
    """Set manual priority from the given id order (index = priority, top first)."""
    return IdeaActionService(db).reorder(
        current_user.tenant_id, body.orderedIds, voter_id=current_user.id
    )


@router.get("/clusters", response_model=ClusterSuggestionsOut)
def suggest_clusters(
    product_id: Optional[str] = Query(None, alias="productId"),
    current_user: User = Depends(require_permission("ideation.clusters.manage")),
    db: Session = Depends(get_db),
) -> ClusterSuggestionsOut:
    """Suggested idea clusters (AC-BI-30/31) - ``pg_trgm`` candidates grouped +
    named by ONE LLM call, degrading to ungrouped trigram candidates if the LLM
    is unavailable. Optional ``productId`` scopes to a single product (omitted =
    every product with candidates in the tenant). Suggestions only - nothing
    auto-promotes. Gated by ``ideation.clusters.manage`` (Triager)."""
    return ClusteringService(db).suggest(
        current_user.tenant_id, product_id=product_id, voter_id=current_user.id
    )


@router.get("/{idea_id}", response_model=IdeaOut)
def get_idea(
    idea_id: str,
    current_user: User = Depends(require_permission("ideation.ideas.view")),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """One idea by id - every section present (attachments empty-state), submitter
    human-readable (never a raw UUID). 404 if not found in the tenant."""
    return IdeaReadService(db).get(
        current_user.tenant_id, idea_id, voter_id=current_user.id
    )


@router.get("/{idea_id}/business-requirements", response_model=List[BusinessRequirementOut])
def list_idea_business_requirements(
    idea_id: str,
    current_user: User = Depends(
        require_permission("ideation.business_requirements.read")
    ),
    db: Session = Depends(get_db),
) -> List[BusinessRequirementOut]:
    """The Business Requirements this idea feeds (AC-BI-29c) - the reverse of the
    BR's Ideas tab, for the idea detail's Business Requirements tab. Tenant-scoped,
    newest BR first. Gated by ``ideation.business_requirements.read`` (viewing BRs
    is the BR read boundary, not the idea's)."""
    return BusinessRequirementService(db).linked_business_requirements(
        current_user.tenant_id, idea_id
    )


@router.patch("/{idea_id}", response_model=IdeaOut)
def update_idea(
    idea_id: str,
    body: IdeaUpdateIn,
    current_user: User = Depends(require_permission("ideation.triage.manage")),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """Operator-facing in-app edit of the mutable idea fields (``productId`` /
    ``problem`` / ``rawText``). Status moves ride ``POST /{idea_id}/status`` - not
    here. 404 if the idea is not in the tenant. Gated by ``ideation.triage.manage``."""
    return IdeaActionService(db).update_operator(
        current_user.tenant_id,
        idea_id,
        product_id=body.productId,
        problem=body.problem,
        proposed_solution=body.proposedSolution,
        impact=body.impact,
        department=body.department,
        raw_text=body.rawText,
        voter_id=current_user.id,
    )


@router.post("/{idea_id}/vote", response_model=IdeaOut)
def vote_idea(
    idea_id: str,
    body: VoteIn,
    current_user: User = Depends(require_permission("ideation.ideas.upvote")),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """Toggle the caller's up/down vote (one per user). Recomputes tallies +
    ``myVote``."""
    return IdeaActionService(db).vote(
        current_user.tenant_id, idea_id, current_user.id, body.dir
    )


@router.post("/{idea_id}/status", response_model=IdeaOut)
def set_idea_status(
    idea_id: str,
    body: StatusIn,
    current_user: User = Depends(require_permission("ideation.triage.manage")),
    db: Session = Depends(get_db),
) -> IdeaOut:
    """Move the idea to a lifecycle status by key (advance / archive / restore).
    Server-authoritative - illegal moves are refused (409)."""
    return IdeaActionService(db).set_status(
        current_user.tenant_id,
        idea_id,
        body.status,
        actor=current_user,
        voter_id=current_user.id,
    )


@router.delete("/{idea_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_idea(
    idea_id: str,
    current_user: User = Depends(require_permission("ideation.triage.manage")),
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete an idea (and its vote rows). 404 if not found in the tenant."""
    IdeaActionService(db).delete(current_user.tenant_id, idea_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
