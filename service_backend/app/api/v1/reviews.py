"""Review/Approval engine endpoints (plan sprint-4/06 Part 2) - HTTP only
(Router → Service → Repository), no DB/raw SQL. Config admin in Part A; the
reviewer/decider SURFACES are slice 2.

Gated ``reviews.read`` (read) / ``reviews.manage`` (write). 422 carries a plain
detail string; 409 = a duplicate decision (first-wins, slice-2 surface).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_permission
from app.models.user import User
from app.review_engine.service import (
    ReviewConfigService,
    ReviewNotFound,
    ReviewValidationError,
)
from app.review_engine.service import (
    ReviewDecisionConflict,
    ReviewTransitionUnavailable,
)
from app.review_engine.surfaces import (
    ReviewSurfaceService,
    SurfaceClosed,
    SurfaceForbidden,
    SurfaceNotFound,
)
from app.schemas.review import (
    DecisionQueueItemOut,
    MyReviewOut,
    ReviewAdminSubmissionOut,
    ReviewConfigCreate,
    ReviewConfigListResponse,
    ReviewConfigMetaOut,
    ReviewConfigOut,
    ReviewConfigUpdate,
    ReviewDecisionIn,
    ReviewDraftIn,
    ReviewTwoPaneOut,
)
from typing import List

router = APIRouter()


# ── staff surfaces (AC-06-46/47/10) - user-kind actors only ───────────────────
# A staff user grades on the staff app; profile-kind assignments 404 here (the
# surface filters by actor_kind='user'). Gated by core perms (reviews.grade /
# reviews.decide) AND - inside the surface service - the per-config role
# capability via the assignment/decision actor match.


@router.get("/my-reviews", response_model=List[MyReviewOut])
def staff_my_reviews(
    contextId: Optional[str] = None,
    current_user: User = Depends(require_permission("reviews.grade")),
    db: Session = Depends(get_db),
) -> List[MyReviewOut]:
    rows = ReviewSurfaceService(db).my_reviews(
        current_user.tenant_id, "user", current_user.id, context_id=contextId
    )
    return [MyReviewOut(**r) for r in rows]


@router.get("/assignments/{assignment_id}", response_model=ReviewTwoPaneOut)
def staff_review_two_pane(
    assignment_id: str,
    current_user: User = Depends(require_permission("reviews.grade")),
    db: Session = Depends(get_db),
) -> ReviewTwoPaneOut:
    try:
        payload = ReviewSurfaceService(db).review_two_pane(
            current_user.tenant_id, assignment_id, "user", current_user.id
        )
    except SurfaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review assignment not found.")
    return ReviewTwoPaneOut(**payload)


@router.post("/assignments/{assignment_id}/draft")
def staff_save_review_draft(
    assignment_id: str,
    body: ReviewDraftIn,
    current_user: User = Depends(require_permission("reviews.grade")),
    db: Session = Depends(get_db),
):
    try:
        return ReviewSurfaceService(db).save_review_draft(
            current_user.tenant_id, assignment_id, "user", current_user.id,
            body.answers, author_user=current_user,
        )
    except SurfaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review assignment not found.")
    except SurfaceClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.post("/assignments/{assignment_id}/submit")
def staff_submit_review(
    assignment_id: str,
    body: ReviewDraftIn,
    current_user: User = Depends(require_permission("reviews.grade")),
    db: Session = Depends(get_db),
):
    try:
        return ReviewSurfaceService(db).submit_review(
            current_user.tenant_id, assignment_id, "user", current_user.id,
            body.answers, author_user=current_user,
        )
    except SurfaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review assignment not found.")
    except SurfaceClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except ReviewValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.get("/decisions", response_model=List[DecisionQueueItemOut])
def staff_decisions(
    contextId: Optional[str] = None,
    current_user: User = Depends(require_permission("reviews.decide")),
    db: Session = Depends(get_db),
) -> List[DecisionQueueItemOut]:
    rows = ReviewSurfaceService(db).decisions_queue(
        current_user.tenant_id, "user", current_user.id, context_id=contextId
    )
    return [DecisionQueueItemOut(**r) for r in rows]


@router.post("/decisions/{group_id}/decide", response_model=DecisionQueueItemOut)
def staff_decide(
    group_id: str,
    body: ReviewDecisionIn,
    current_user: User = Depends(require_permission("reviews.decide")),
    db: Session = Depends(get_db),
) -> DecisionQueueItemOut:
    svc = ReviewSurfaceService(db)
    try:
        payload = svc.decide(
            current_user.tenant_id, group_id, "user", current_user.id,
            body.decision, body.feedback, actor=current_user,
        )
    except SurfaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission group not found.")
    except SurfaceForbidden:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot decide on this submission.")
    except ReviewDecisionConflict:
        raise HTTPException(status.HTTP_409_CONFLICT, "A decision has already been made.")
    except ReviewTransitionUnavailable as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except ReviewValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return DecisionQueueItemOut(**payload)


@router.get("/configurations", response_model=ReviewConfigListResponse)
def list_configurations(
    current_user: User = Depends(require_permission("reviews.read")),
    db: Session = Depends(get_db),
) -> ReviewConfigListResponse:
    rows = ReviewConfigService(db).list_configs(current_user.tenant_id)
    return ReviewConfigListResponse(
        data=[ReviewConfigOut(**r) for r in rows], total=len(rows)
    )


@router.post("/configurations", response_model=ReviewConfigOut, status_code=status.HTTP_201_CREATED)
def create_configuration(
    body: ReviewConfigCreate,
    current_user: User = Depends(require_permission("reviews.manage")),
    db: Session = Depends(get_db),
) -> ReviewConfigOut:
    service = ReviewConfigService(db)
    payload = body.model_dump()
    roles = payload.pop("roles", None)
    try:
        config = service.create_config(current_user.tenant_id, roles=roles, **payload)
    except ReviewValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return ReviewConfigOut(**service.config_to_dict(config))


# Specific path BEFORE the /configurations/{config_id} param route - the admin
# pickers' only-valid-option universes (AC-06-55).
@router.get("/configurations/form-meta", response_model=ReviewConfigMetaOut)
def configuration_form_meta(
    submissionFormId: Optional[str] = None,
    reviewFormId: Optional[str] = None,
    current_user: User = Depends(require_permission("reviews.read")),
    db: Session = Depends(get_db),
) -> ReviewConfigMetaOut:
    meta = ReviewConfigService(db).form_meta(
        current_user.tenant_id, submissionFormId, reviewFormId
    )
    return ReviewConfigMetaOut(**meta)


@router.get(
    "/configurations/{config_id}/submissions",
    response_model=List[ReviewAdminSubmissionOut],
)
def configuration_submissions(
    config_id: str,
    current_user: User = Depends(require_permission("reviews.read")),
    db: Session = Depends(get_db),
) -> List[ReviewAdminSubmissionOut]:
    """Admin Submissions overview (read-only staff god-view) - every submission
    group for the config with its reviews/scores, live average + decision."""
    try:
        rows = ReviewSurfaceService(db).admin_submissions(
            current_user.tenant_id, config_id
        )
    except SurfaceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review configuration not found.")
    return [ReviewAdminSubmissionOut(**r) for r in rows]


@router.get("/configurations/{config_id}", response_model=ReviewConfigOut)
def get_configuration(
    config_id: str,
    current_user: User = Depends(require_permission("reviews.read")),
    db: Session = Depends(get_db),
) -> ReviewConfigOut:
    service = ReviewConfigService(db)
    try:
        config = service.get_config(current_user.tenant_id, config_id)
    except ReviewNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review configuration not found.")
    return ReviewConfigOut(**service.config_to_dict(config))


@router.patch("/configurations/{config_id}", response_model=ReviewConfigOut)
def update_configuration(
    config_id: str,
    body: ReviewConfigUpdate,
    current_user: User = Depends(require_permission("reviews.manage")),
    db: Session = Depends(get_db),
) -> ReviewConfigOut:
    service = ReviewConfigService(db)
    fields_set = set(body.model_fields_set)
    payload = body.model_dump()
    roles = payload.pop("roles", None)
    fields_set.discard("roles")
    try:
        config = service.update_config(
            current_user.tenant_id,
            config_id,
            fields_set=fields_set,
            roles=roles if "roles" in body.model_fields_set else None,
            **payload,
        )
    except ReviewNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review configuration not found.")
    except ReviewValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return ReviewConfigOut(**service.config_to_dict(config))


@router.delete("/configurations/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_configuration(
    config_id: str,
    current_user: User = Depends(require_permission("reviews.manage")),
    db: Session = Depends(get_db),
) -> None:
    try:
        ReviewConfigService(db).delete_config(current_user.tenant_id, config_id)
    except ReviewNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review configuration not found.")
