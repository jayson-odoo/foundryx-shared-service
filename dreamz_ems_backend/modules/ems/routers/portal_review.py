"""Profile-portal review surfaces (plan sprint-4/06 slice 2) — ``/portal/*``.

Profile-authed (``current_profile``) + gated by portal-permission keys
(``require_portal_permission``). HTTP only — Router → ``PortalReviewService`` →
core review/form services. The router NEVER accepts a ``tenant_id`` from the
client (it comes from the Profile JWT, AC-06-14/57).

Wired as a ``"public": true`` manifest router so the loader does NOT inject the
staff ``require_module`` gate — these are Profile-authed, not staff-authed (same
as ``portal``/``portal_auth``).

Surfaces:
- My Submissions (AC-06-43/52/08): list + submit-form view + submit + revise.
- My Reviews (AC-06-44/05/48): queue + two-pane + draft + submit (reviewer-isolated).
- Decisions (AC-06-45/07): queue (live average + ready) + first-wins decide.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.review_engine.service import (
    ReviewDecisionConflict,
    ReviewTransitionUnavailable,
    ReviewValidationError,
)
from app.schemas.review import (
    DecisionQueueItemOut,
    MyReviewOut,
    MySubmissionOut,
    ReviewDecisionIn,
    ReviewDraftIn,
    ReviewTwoPaneOut,
)
from modules.ems.models import Profile
from modules.ems.portal_deps import require_portal_permission
from modules.ems.portal_review_service import (
    PortalReviewClosed,
    PortalReviewForbidden,
    PortalReviewNotFound,
    PortalReviewService,
)

router = APIRouter()


# ── My Submissions (AC-06-43/52/08) ───────────────────────────────────────────


@router.get("/submissions", response_model=List[MySubmissionOut])
def my_submissions(
    contextId: Optional[str] = None,
    profile: Profile = Depends(require_portal_permission("my_submissions.read")),
    db: Session = Depends(get_db),
) -> List[MySubmissionOut]:
    """My Submissions — narrowed to one event when ``contextId`` is set (AC-06-25),
    else across all contexts (each row carries its event for per-row labelling)."""
    rows = PortalReviewService(db).my_submissions(profile, context_id=contextId)
    return [MySubmissionOut(**r) for r in rows]


@router.get("/submit-options")
def submit_options(
    contextId: Optional[str] = None,
    profile: Profile = Depends(require_portal_permission("forms.submit")),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Review configurations the current Profile may submit to (AC-06-03) — drives
    the Submit actions on My Submissions even with zero prior submissions.
    ``contextId`` narrows to one event (AC-06-25)."""
    return PortalReviewService(db).submit_options(profile, context_id=contextId)


@router.get("/submissions/{group_id}")
def submission_detail(
    group_id: str,
    profile: Profile = Depends(require_portal_permission("my_submissions.read")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """The author's own submission group with the current revision's answers
    (AC-06-09 — prefills revise). Author-only; 404 otherwise / cross-tenant."""
    try:
        return PortalReviewService(db).submission_detail(profile, group_id)
    except PortalReviewNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found.")


@router.get("/review-configs/{config_id}/submit-form")
def submit_form_view(
    config_id: str,
    profile: Profile = Depends(require_portal_permission("forms.submit")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return PortalReviewService(db).submit_form_view(profile, config_id)
    except PortalReviewNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review process not found.")


@router.post("/review-configs/{config_id}/submissions", response_model=MySubmissionOut)
def submit(
    config_id: str,
    body: ReviewDraftIn,
    profile: Profile = Depends(require_portal_permission("forms.submit")),
    db: Session = Depends(get_db),
) -> MySubmissionOut:
    from app.services.form_service import FormClosed, FormSubmitInvalid

    try:
        payload = PortalReviewService(db).submit(profile, config_id, body.answers)
    except PortalReviewNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review process not found.")
    except PortalReviewForbidden:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot submit to this process.")
    except PortalReviewClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except FormClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except FormSubmitInvalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"fieldErrors": exc.field_errors})
    return MySubmissionOut(**payload)


@router.post("/submissions/{group_id}/revise")
def revise(
    group_id: str,
    profile: Profile = Depends(require_portal_permission("my_submissions.read")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return PortalReviewService(db).revise(profile, group_id)
    except PortalReviewNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found.")
    except PortalReviewForbidden:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot revise this submission.")
    except PortalReviewClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.post("/submissions/{submission_id}/resubmit", response_model=MySubmissionOut)
def resubmit(
    submission_id: str,
    body: ReviewDraftIn,
    profile: Profile = Depends(require_portal_permission("my_submissions.read")),
    db: Session = Depends(get_db),
) -> MySubmissionOut:
    from app.services.form_service import FormSubmitInvalid

    try:
        payload = PortalReviewService(db).resubmit(profile, submission_id, body.answers)
    except PortalReviewNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found.")
    except PortalReviewForbidden:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot revise this submission.")
    except PortalReviewClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except FormSubmitInvalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"fieldErrors": exc.field_errors})
    return MySubmissionOut(**payload)


# ── My Reviews (AC-06-44/05/48) ───────────────────────────────────────────────


@router.get("/reviews", response_model=List[MyReviewOut])
def my_reviews(
    contextId: Optional[str] = None,
    profile: Profile = Depends(require_portal_permission("my_reviews.read")),
    db: Session = Depends(get_db),
) -> List[MyReviewOut]:
    rows = PortalReviewService(db).my_reviews(profile, context_id=contextId)
    return [MyReviewOut(**r) for r in rows]


@router.get("/reviews/{assignment_id}", response_model=ReviewTwoPaneOut)
def review_two_pane(
    assignment_id: str,
    profile: Profile = Depends(require_portal_permission("my_reviews.read")),
    db: Session = Depends(get_db),
) -> ReviewTwoPaneOut:
    try:
        payload = PortalReviewService(db).review_two_pane(profile, assignment_id)
    except PortalReviewNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review assignment not found.")
    return ReviewTwoPaneOut(**payload)


@router.post("/reviews/{assignment_id}/draft")
def save_review_draft(
    assignment_id: str,
    body: ReviewDraftIn,
    profile: Profile = Depends(require_portal_permission("my_reviews.read")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return PortalReviewService(db).save_review_draft(profile, assignment_id, body.answers)
    except PortalReviewNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review assignment not found.")
    except PortalReviewClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.post("/reviews/{assignment_id}/submit")
def submit_review(
    assignment_id: str,
    body: ReviewDraftIn,
    profile: Profile = Depends(require_portal_permission("my_reviews.read")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    try:
        return PortalReviewService(db).submit_review(profile, assignment_id, body.answers)
    except PortalReviewNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review assignment not found.")
    except PortalReviewClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    except ReviewValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


# ── Decisions (AC-06-45/07) ───────────────────────────────────────────────────


@router.get("/decisions", response_model=List[DecisionQueueItemOut])
def decisions(
    contextId: Optional[str] = None,
    profile: Profile = Depends(require_portal_permission("decisions.read")),
    db: Session = Depends(get_db),
) -> List[DecisionQueueItemOut]:
    rows = PortalReviewService(db).decisions(profile, context_id=contextId)
    return [DecisionQueueItemOut(**r) for r in rows]


@router.post("/decisions/{group_id}/decide", response_model=DecisionQueueItemOut)
def decide(
    group_id: str,
    body: ReviewDecisionIn,
    profile: Profile = Depends(require_portal_permission("decisions.read")),
    db: Session = Depends(get_db),
) -> DecisionQueueItemOut:
    try:
        payload = PortalReviewService(db).decide(profile, group_id, body.decision, body.feedback)
    except PortalReviewNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission group not found.")
    except PortalReviewForbidden:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot decide on this submission.")
    except ReviewDecisionConflict:
        raise HTTPException(status.HTTP_409_CONFLICT, "A decision has already been made.")
    except ReviewTransitionUnavailable as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except ReviewValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return DecisionQueueItemOut(**payload)
