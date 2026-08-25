"""Review/Approval engine wire schemas (plan sprint-4/06 Part 2) - camelCase out.
Datetime-bearing models inherit ``ApiModel`` so timestamps leave the API as
Z-suffixed UTC (BL-012). Requests accept camelCase via ``validation_alias``
(``populate_by_name`` lets the service pass snake kwargs too).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import ApiModel


class _Req(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# ---- requests ----


class ReviewRoleActorIn(_Req):
    actor_kind: str = Field(validation_alias="actorKind")
    actor_id: str = Field(validation_alias="actorId")
    conditions_json: Optional[Dict[str, Any]] = Field(default=None, validation_alias="conditionsJson")
    sort_order: Optional[int] = Field(default=None, validation_alias="sortOrder")


class ReviewRoleIn(_Req):
    key: str
    label: str
    can_submit: bool = Field(default=False, validation_alias="canSubmit")
    can_review: bool = Field(default=False, validation_alias="canReview")
    can_decide: bool = Field(default=False, validation_alias="canDecide")
    actor_source: str = Field(validation_alias="actorSource")
    actor_identity_kind: str = Field(validation_alias="actorIdentityKind")
    bound_persona_id: Optional[str] = Field(default=None, validation_alias="boundPersonaId")
    bound_staff_role_id: Optional[str] = Field(default=None, validation_alias="boundStaffRoleId")
    conditions_json: Optional[Dict[str, Any]] = Field(default=None, validation_alias="conditionsJson")
    sort_order: Optional[int] = Field(default=None, validation_alias="sortOrder")
    actors: Optional[List[ReviewRoleActorIn]] = None


class ReviewConfigCreate(_Req):
    name: str
    form_id: str = Field(validation_alias="formId")
    review_form_id: str = Field(validation_alias="reviewFormId")
    required_review_count: int = Field(default=1, validation_alias="requiredReviewCount")
    score_field_key: Optional[str] = Field(default=None, validation_alias="scoreFieldKey")
    context_type: Optional[str] = Field(default=None, validation_alias="contextType")
    context_id: Optional[str] = Field(default=None, validation_alias="contextId")
    window_start: Optional[datetime] = Field(default=None, validation_alias="windowStart")
    window_end: Optional[datetime] = Field(default=None, validation_alias="windowEnd")
    review_start_status_id: Optional[str] = Field(default=None, validation_alias="reviewStartStatusId")
    revisions_status_id: Optional[str] = Field(default=None, validation_alias="revisionsStatusId")
    accepted_status_id: Optional[str] = Field(default=None, validation_alias="acceptedStatusId")
    rejected_status_id: Optional[str] = Field(default=None, validation_alias="rejectedStatusId")
    is_active: bool = Field(default=True, validation_alias="isActive")
    roles: Optional[List[ReviewRoleIn]] = None


class ReviewConfigUpdate(_Req):
    name: Optional[str] = None
    form_id: Optional[str] = Field(default=None, validation_alias="formId")
    review_form_id: Optional[str] = Field(default=None, validation_alias="reviewFormId")
    required_review_count: Optional[int] = Field(default=None, validation_alias="requiredReviewCount")
    score_field_key: Optional[str] = Field(default=None, validation_alias="scoreFieldKey")
    context_type: Optional[str] = Field(default=None, validation_alias="contextType")
    context_id: Optional[str] = Field(default=None, validation_alias="contextId")
    window_start: Optional[datetime] = Field(default=None, validation_alias="windowStart")
    window_end: Optional[datetime] = Field(default=None, validation_alias="windowEnd")
    review_start_status_id: Optional[str] = Field(default=None, validation_alias="reviewStartStatusId")
    revisions_status_id: Optional[str] = Field(default=None, validation_alias="revisionsStatusId")
    accepted_status_id: Optional[str] = Field(default=None, validation_alias="acceptedStatusId")
    rejected_status_id: Optional[str] = Field(default=None, validation_alias="rejectedStatusId")
    is_active: Optional[bool] = Field(default=None, validation_alias="isActive")
    roles: Optional[List[ReviewRoleIn]] = None


# ---- responses ----


class ReviewRoleActorOut(ApiModel):
    id: str
    actor_kind: str = Field(serialization_alias="actorKind")
    actor_id: str = Field(serialization_alias="actorId")
    conditions_json: Optional[Dict[str, Any]] = Field(serialization_alias="conditionsJson")
    sort_order: int = Field(serialization_alias="sortOrder")


class ReviewRoleOut(ApiModel):
    id: str
    review_configuration_id: str = Field(serialization_alias="reviewConfigurationId")
    key: str
    label: str
    can_submit: bool = Field(serialization_alias="canSubmit")
    can_review: bool = Field(serialization_alias="canReview")
    can_decide: bool = Field(serialization_alias="canDecide")
    actor_source: str = Field(serialization_alias="actorSource")
    actor_identity_kind: str = Field(serialization_alias="actorIdentityKind")
    bound_persona_id: Optional[str] = Field(serialization_alias="boundPersonaId")
    bound_staff_role_id: Optional[str] = Field(serialization_alias="boundStaffRoleId")
    conditions_json: Optional[Dict[str, Any]] = Field(serialization_alias="conditionsJson")
    sort_order: int = Field(serialization_alias="sortOrder")
    actors: List[ReviewRoleActorOut]


class ReviewConfigOut(ApiModel):
    id: str
    name: str
    form_id: str = Field(serialization_alias="formId")
    review_form_id: str = Field(serialization_alias="reviewFormId")
    required_review_count: int = Field(serialization_alias="requiredReviewCount")
    score_field_key: Optional[str] = Field(serialization_alias="scoreFieldKey")
    context_type: Optional[str] = Field(default=None, serialization_alias="contextType")
    context_id: Optional[str] = Field(default=None, serialization_alias="contextId")
    window_start: Optional[datetime] = Field(serialization_alias="windowStart")
    window_end: Optional[datetime] = Field(serialization_alias="windowEnd")
    review_start_status_id: Optional[str] = Field(serialization_alias="reviewStartStatusId")
    revisions_status_id: Optional[str] = Field(serialization_alias="revisionsStatusId")
    accepted_status_id: Optional[str] = Field(serialization_alias="acceptedStatusId")
    rejected_status_id: Optional[str] = Field(serialization_alias="rejectedStatusId")
    is_active: bool = Field(serialization_alias="isActive")
    roles: List[ReviewRoleOut]
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class ReviewConfigListResponse(ApiModel):
    data: List[ReviewConfigOut]
    total: int


# ---- editor metadata (the admin pickers - AC-06-55) ----


class ReviewMetaStatusOut(ApiModel):
    id: str
    label: str
    color: str


class ReviewMetaFieldOut(ApiModel):
    key: str
    label: str


class ReviewMetaFactOut(ApiModel):
    key: str
    label: str
    type: str
    options: Optional[List[Dict[str, str]]] = None


# ---- surfaces (slice 2 - My Submissions / My Reviews / Decisions) ----


class MySubmissionOut(ApiModel):
    """Author view of a submission group (AC-06-43/08) - lifecycle + decision +
    feedback ONLY; never raw reviews/scores."""

    group_id: str = Field(serialization_alias="groupId")
    submission_id: str = Field(serialization_alias="submissionId")
    review_configuration_id: str = Field(serialization_alias="reviewConfigurationId")
    review_configuration_name: str = Field(serialization_alias="reviewConfigurationName")
    context_id: Optional[str] = Field(default=None, serialization_alias="contextId")
    context_label: Optional[str] = Field(default=None, serialization_alias="contextLabel")
    form_id: str = Field(serialization_alias="formId")
    title: str
    revision_number: int = Field(serialization_alias="revisionNumber")
    status_id: str = Field(serialization_alias="statusId")
    status_label: str = Field(serialization_alias="statusLabel")
    status_color: str = Field(serialization_alias="statusColor")
    decision: Optional[str] = None
    feedback_text: Optional[str] = Field(default=None, serialization_alias="feedbackText")
    decided_at: Optional[datetime] = Field(default=None, serialization_alias="decidedAt")
    can_revise: bool = Field(serialization_alias="canRevise")
    submitted_at: Optional[datetime] = Field(default=None, serialization_alias="submittedAt")
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")


class MyReviewOut(ApiModel):
    """One assignment in the reviewer's queue (AC-06-44)."""

    assignment_id: str = Field(serialization_alias="assignmentId")
    review_configuration_id: str = Field(serialization_alias="reviewConfigurationId")
    review_configuration_name: str = Field(serialization_alias="reviewConfigurationName")
    context_id: Optional[str] = Field(default=None, serialization_alias="contextId")
    context_label: Optional[str] = Field(default=None, serialization_alias="contextLabel")
    group_id: str = Field(serialization_alias="groupId")
    revision_number: int = Field(serialization_alias="revisionNumber")
    status: str
    due_at: Optional[datetime] = Field(default=None, serialization_alias="dueAt")
    assigned_at: Optional[datetime] = Field(default=None, serialization_alias="assignedAt")
    completed_at: Optional[datetime] = Field(default=None, serialization_alias="completedAt")
    title: str


class ReviewTwoPaneOut(ApiModel):
    """The two-pane grade payload (AC-06-05/48) - submission (pinned) ‖ review form
    + THIS reviewer's draft only (reviewer isolation)."""

    assignment_id: str = Field(serialization_alias="assignmentId")
    status: str
    review_configuration_id: str = Field(serialization_alias="reviewConfigurationId")
    review_configuration_name: str = Field(serialization_alias="reviewConfigurationName")
    submission: Dict[str, Any]
    review_form: Optional[Dict[str, Any]] = Field(serialization_alias="reviewForm")
    review_draft: Optional[Dict[str, Any]] = Field(serialization_alias="reviewDraft")


class ReviewDraftIn(_Req):
    answers: Dict[str, Any] = Field(default_factory=dict)


class ReviewDecisionIn(_Req):
    decision: str
    feedback: Optional[str] = None


class DecisionQueueReviewOut(ApiModel):
    assignment_id: str = Field(serialization_alias="assignmentId")
    review_submission_id: str = Field(serialization_alias="reviewSubmissionId")
    answers: Dict[str, Any]
    score: Optional[float] = None
    completed_at: Optional[datetime] = Field(default=None, serialization_alias="completedAt")


class DecisionQueueItemOut(ApiModel):
    """One group in the decider's Decisions surface (AC-06-45/07)."""

    group_id: str = Field(serialization_alias="groupId")
    submission_id: str = Field(serialization_alias="submissionId")
    review_configuration_id: str = Field(serialization_alias="reviewConfigurationId")
    review_configuration_name: str = Field(serialization_alias="reviewConfigurationName")
    context_id: Optional[str] = Field(default=None, serialization_alias="contextId")
    context_label: Optional[str] = Field(default=None, serialization_alias="contextLabel")
    title: str
    revision_number: int = Field(serialization_alias="revisionNumber")
    status_id: str = Field(serialization_alias="statusId")
    status_label: str = Field(serialization_alias="statusLabel")
    status_color: str = Field(serialization_alias="statusColor")
    average_score: Optional[float] = Field(default=None, serialization_alias="averageScore")
    completed_count: int = Field(serialization_alias="completedCount")
    required_review_count: int = Field(serialization_alias="requiredReviewCount")
    ready: bool
    decision: Optional[str] = None
    feedback_text: Optional[str] = Field(default=None, serialization_alias="feedbackText")
    reviews: List[DecisionQueueReviewOut]
    submitted_at: Optional[datetime] = Field(default=None, serialization_alias="submittedAt")
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")


# ---- admin overview (the staff god-view - AC §10 deferred) ----


class ReviewAdminAuthorOut(ApiModel):
    kind: str
    id: str
    name: str


class ReviewAdminReviewOut(ApiModel):
    """One reviewer's review on the admin overview - MAY surface the raw score
    (staff view, unlike the author-visible surface)."""

    assignment_id: str = Field(serialization_alias="assignmentId")
    reviewer_kind: str = Field(serialization_alias="reviewerKind")
    reviewer_id: str = Field(serialization_alias="reviewerId")
    reviewer_name: str = Field(serialization_alias="reviewerName")
    status: str  # PENDING | COMPLETED | ESCALATED | WITHDRAWN
    score: Optional[float] = None


class ReviewAdminDecisionOut(ApiModel):
    decision: str
    feedback_text: Optional[str] = Field(default=None, serialization_alias="feedbackText")
    decider_kind: str = Field(serialization_alias="deciderKind")
    decider_id: str = Field(serialization_alias="deciderId")
    decider_name: str = Field(serialization_alias="deciderName")
    decided_at: Optional[datetime] = Field(default=None, serialization_alias="decidedAt")


class ReviewAdminSubmissionOut(ApiModel):
    """One submission group on the Review-process admin Submissions overview
    (read-only staff god-view): status + author + each review + live average +
    decision."""

    group_id: str = Field(serialization_alias="groupId")
    submission_id: str = Field(serialization_alias="submissionId")
    revision_number: int = Field(serialization_alias="revisionNumber")
    title: str
    status_id: str = Field(serialization_alias="statusId")
    status_label: str = Field(serialization_alias="statusLabel")
    status_color: str = Field(serialization_alias="statusColor")
    author: Optional[ReviewAdminAuthorOut] = None
    submitted_at: Optional[datetime] = Field(default=None, serialization_alias="submittedAt")
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    reviews: List[ReviewAdminReviewOut]
    average_score: Optional[float] = Field(default=None, serialization_alias="averageScore")
    required_review_count: int = Field(serialization_alias="requiredReviewCount")
    completed_count: int = Field(serialization_alias="completedCount")
    ready: bool
    decision: Optional[ReviewAdminDecisionOut] = None


class ReviewConfigMetaOut(ApiModel):
    """Only-valid-option universes for the Review-process admin (AC-06-55):
    submission-form scoped statuses (status mapping), review-form numeric fields
    (``scoreFieldKey``), and submission-form answer facts (RULE-role builder)."""

    submission_statuses: List[ReviewMetaStatusOut] = Field(
        serialization_alias="submissionStatuses"
    )
    numeric_fields: List[ReviewMetaFieldOut] = Field(serialization_alias="numericFields")
    submission_facts: List[ReviewMetaFactOut] = Field(serialization_alias="submissionFacts")
