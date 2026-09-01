"""Form engine wire schemas (plan sprint-3/01) - camelCase out (mirror of the
frontend ``types/forms.ts``). Datetime-bearing models inherit ``ApiModel`` so
every timestamp leaves the API as Z-suffixed UTC (BL-012). Requests use camel
field names directly (the frontend sends those verbatim).

The published-vs-draft split (D9): ``FormRowOut``/``FormDetailOut`` describe the
DEFINITION; fill surfaces serve a slimmed ``FormFillViewOut`` (published version
only, the draft for preview). Submissions ride the form's OWN scoped status
machine (D4) - ``FormSubmissionGraphOut`` exposes that scope-filtered graph so
the Submissions tab's transition buttons render without ``statuses.read`` (D15).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.form import ACCESS_INTERNAL
from app.schemas.base import ApiModel


# ---- form definition (list + detail) ----


class FormRowOut(ApiModel):
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    status: str
    access: str
    is_trashed: bool = Field(serialization_alias="isTrashed")
    current_version_id: Optional[str] = Field(serialization_alias="currentVersionId")
    current_version_number: Optional[int] = Field(
        serialization_alias="currentVersionNumber"
    )
    has_unpublished_changes: bool = Field(serialization_alias="hasUnpublishedChanges")
    opens_at: Optional[datetime] = Field(serialization_alias="opensAt")
    closes_at: Optional[datetime] = Field(serialization_alias="closesAt")
    max_submissions: Optional[int] = Field(serialization_alias="maxSubmissions")
    submission_limit_per_user: Optional[int] = Field(
        serialization_alias="submissionLimitPerUser"
    )
    pinned_columns: List[str] = Field(serialization_alias="pinnedColumns")
    display_mode: str = Field(serialization_alias="displayMode")
    allow_revisions: bool = Field(serialization_alias="allowRevisions")
    submission_count: int = Field(serialization_alias="submissionCount")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class FormDetailOut(FormRowOut):
    draft_definition: Dict[str, Any] = Field(serialization_alias="draftDefinition")


class FormListResponse(ApiModel):
    data: List[FormRowOut]
    total: int
    page: int


class FormNeighborResponse(ApiModel):
    form: Optional[FormRowOut] = None
    total: int


# ---- versions ----


class FormVersionOut(ApiModel):
    id: str
    version_number: int = Field(serialization_alias="versionNumber")
    published_by: Optional[str] = Field(serialization_alias="publishedBy")
    published_by_name: Optional[str] = Field(serialization_alias="publishedByName")
    created_at: datetime = Field(serialization_alias="createdAt")


class FormVersionListResponse(ApiModel):
    data: List[FormVersionOut]
    total: int
    page: int


class FormVersionDefinitionOut(ApiModel):
    """One version's immutable doc - submission re-render contract (D9)."""

    id: str
    version_number: int = Field(serialization_alias="versionNumber")
    definition: Dict[str, Any]


# ---- fill surface (D9 read-model) ----


class FormFillViewOut(ApiModel):
    form_id: str = Field(serialization_alias="formId")
    version_id: str = Field(serialization_alias="versionId")
    version_number: int = Field(serialization_alias="versionNumber")
    name: str
    description: Optional[str] = None
    definition: Dict[str, Any]
    paged: bool


# ---- submissions ----


class FormSubmissionOut(ApiModel):
    id: str
    form_id: str = Field(serialization_alias="formId")
    submission_group_id: str = Field(serialization_alias="submissionGroupId")
    revision_number: int = Field(serialization_alias="revisionNumber")
    is_current: bool = Field(serialization_alias="isCurrent")
    version_id: str = Field(serialization_alias="versionId")
    version_number: int = Field(serialization_alias="versionNumber")
    status_id: str = Field(serialization_alias="statusId")
    status_key: str = Field(serialization_alias="statusKey")
    status_label: str = Field(serialization_alias="statusLabel")
    status_color: str = Field(serialization_alias="statusColor")
    user_id: Optional[str] = Field(serialization_alias="userId")
    user_name: Optional[str] = Field(serialization_alias="userName")
    subject_type: Optional[str] = Field(serialization_alias="subjectType")
    subject_id: Optional[str] = Field(serialization_alias="subjectId")
    answers: Dict[str, Any]
    submitted_at: Optional[datetime] = Field(serialization_alias="submittedAt")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    # Per-record fireable edge ids (graph-driven buttons, D15) - may be omitted.
    available_transition_ids: Optional[List[str]] = Field(
        default=None, serialization_alias="availableTransitionIds"
    )


class SubmissionListResponse(ApiModel):
    data: List[FormSubmissionOut]
    total: int
    page: int


class FormSubmissionGraphStatusOut(ApiModel):
    id: str
    key: str
    label: str
    color: str
    is_initial: bool = Field(serialization_alias="isInitial")
    is_active: bool = Field(serialization_alias="isActive")
    is_terminal: bool = Field(serialization_alias="isTerminal")


class FormSubmissionGraphEdgeOut(ApiModel):
    id: str
    label: str
    from_status_id: str = Field(serialization_alias="fromStatusId")
    to_status_id: str = Field(serialization_alias="toStatusId")


class FormSubmissionGraphOut(ApiModel):
    statuses: List[FormSubmissionGraphStatusOut]
    transitions: List[FormSubmissionGraphEdgeOut]


# ---- requests (camelCase field names - frontend sends these) ----


class FormCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    access: str = ACCESS_INTERNAL


class FormUpdateRequest(BaseModel):
    """PATCH semantics - every field optional, only the provided ones apply.
    ``model_fields_set`` distinguishes "absent" from "explicitly null"."""

    name: Optional[str] = None
    description: Optional[str] = None
    access: Optional[str] = None
    draftDefinition: Optional[Dict[str, Any]] = None
    opensAt: Optional[datetime] = None
    closesAt: Optional[datetime] = None
    maxSubmissions: Optional[int] = None
    submissionLimitPerUser: Optional[int] = None
    pinnedColumns: Optional[List[str]] = None
    displayMode: Optional[str] = None
    allowRevisions: Optional[bool] = None


class SubmitRequest(BaseModel):
    answers: Dict[str, Any] = Field(default_factory=dict)


class TransitionRequest(BaseModel):
    transitionId: str


# ---- public (pre-auth) surface (plan sprint-3/02) ----


class PublicFormViewOut(ApiModel):
    """The anonymous fill view. `state` distinguishes open vs closed/full for an
    EXISTING public form; an unknown/non-public/unpublished form is a uniform
    404 (handled in the router, never surfaced here)."""

    state: str
    form_id: str = Field(serialization_alias="formId")
    version_id: str = Field(serialization_alias="versionId")
    name: str
    description: Optional[str] = None
    # Only populated when state == 'open'.
    definition: Optional[Dict[str, Any]] = None
    paged: bool
    honeypot_field: str = Field(serialization_alias="honeypotField")
    message: Optional[str] = None


class PublicSubmitRequest(BaseModel):
    answers: Dict[str, Any] = Field(default_factory=dict)
    # The bot-trap value (D12). Non-empty → the submission is silently dropped.
    honeypot: str = ""
