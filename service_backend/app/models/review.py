"""Generic Review/Approval engine models (plan sprint-4/06 Part 2) - core
``public`` tables.

A horizontal review/approval feature over ANY ``form_submission``. Role-agnostic
(free-form roles + capability flags), identity-agnostic (a role's actors are all
Users OR all Profiles - ``actor_identity_kind`` is uniform per role), reusable by
any use-case. EMS just *configures* it (Part B); NOTHING in core imports the EMS
module - PERSONA actor pools are resolved through an injectable resolver hook
(``app/review_engine/resolvers.py``), so the engine never references Profiles.

Cross-engine references (the submission form's scoped status ids, a bound
persona/staff-role id, actor ids) are stored as PLAIN indexed string columns -
the polymorphic-target_id rule (validate at save, scope at resolve) applies, NOT
DB-level FKs (these may point into a module schema).
"""
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base
from app.models.utc_datetime import UTCDateTime

# ---- actor identity (every actor ref = (actor_kind, actor_id)) ----
ACTOR_KIND_USER = "user"
ACTOR_KIND_PROFILE = "profile"
ACTOR_KINDS = (ACTOR_KIND_USER, ACTOR_KIND_PROFILE)

# ---- role population sources (D30) ----
SOURCE_RULE = "RULE"
SOURCE_EXPLICIT = "EXPLICIT"
SOURCE_PERSONA = "PERSONA"
SOURCE_STAFF_ROLE = "STAFF_ROLE"
ACTOR_SOURCES = (SOURCE_RULE, SOURCE_EXPLICIT, SOURCE_PERSONA, SOURCE_STAFF_ROLE)

# ---- assignment lifecycle (plain enum, not the status engine) ----
ASSIGNMENT_PENDING = "PENDING"
ASSIGNMENT_COMPLETED = "COMPLETED"
ASSIGNMENT_ESCALATED = "ESCALATED"
ASSIGNMENT_WITHDRAWN = "WITHDRAWN"
ASSIGNMENT_STATUSES = (
    ASSIGNMENT_PENDING,
    ASSIGNMENT_COMPLETED,
    ASSIGNMENT_ESCALATED,
    ASSIGNMENT_WITHDRAWN,
)

# ---- decision outcomes (D34) ----
DECISION_ACCEPTED = "ACCEPTED"
DECISION_REJECTED = "REJECTED"
DECISION_REVISIONS = "REVISIONS"
DECISIONS = (DECISION_ACCEPTED, DECISION_REJECTED, DECISION_REVISIONS)


def _uuid() -> str:
    return str(uuid.uuid4())


class ReviewConfiguration(Base):
    """One review/approval process over a submission form (D27). ``review_form_id``
    is the rubric form - reviews ARE ``form_submissions`` of it. The four status
    ids map into the SUBMISSION form's OWN scoped status machine (plain string
    cols; resolved scope-guarded at use)."""

    __tablename__ = "review_configurations"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)

    # The SUBMISSION form (what is reviewed) + the REVIEW (rubric) form.
    form_id = Column(String, nullable=False, index=True)
    review_form_id = Column(String, nullable=False, index=True)

    required_review_count = Column(Integer, nullable=False, default=1)
    # A numeric field key of the review form's published version (D35/D36).
    score_field_key = Column(String, nullable=True)

    # Event/context binding (AC-06-25/24/49): the granting membership's scope a
    # config belongs to - plain indexed cols (BL-030 - NOT a cross-schema FK; the
    # context_id may point into a module schema, e.g. an EMS ``app_ems.projects``
    # row). ``context_type='project'`` + ``context_id=<project_id>`` for an
    # EMS event review. NULL/NULL = unbound (a generic, context-less config).
    # The surfaces filter their lists by ``context_id`` so the global event-filter
    # pill narrows every review surface to one event.
    context_type = Column(String, nullable=True, index=True)
    context_id = Column(String, nullable=True, index=True)

    window_start = Column(UTCDateTime(), nullable=True)
    window_end = Column(UTCDateTime(), nullable=True)

    # The submission form's scoped status ids the lifecycle moves through.
    review_start_status_id = Column(String, nullable=True)
    revisions_status_id = Column(String, nullable=True)
    accepted_status_id = Column(String, nullable=True)
    rejected_status_id = Column(String, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True, server_default="true")

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ReviewRole(Base):
    """A free-form role per config (D28). Behaviour is driven by the capability
    flags; ``label`` is display-only and per-config inline-relabelable. A role is
    a SINGLE identity-kind (D29 - ``actor_identity_kind`` uniform) so surfaces
    route by kind without per-member branching."""

    __tablename__ = "review_roles"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    review_configuration_id = Column(String, nullable=False, index=True)

    key = Column(String, nullable=False)
    label = Column(String, nullable=False)

    can_submit = Column(Boolean, nullable=False, default=False, server_default="false")
    can_review = Column(Boolean, nullable=False, default=False, server_default="false")
    can_decide = Column(Boolean, nullable=False, default=False, server_default="false")

    actor_source = Column(String, nullable=False)  # RULE|EXPLICIT|PERSONA|STAFF_ROLE
    actor_identity_kind = Column(String, nullable=False)  # user|profile

    # PERSONA / STAFF_ROLE binding (membership confers the role). Plain ids.
    bound_persona_id = Column(String, nullable=True)
    bound_staff_role_id = Column(String, nullable=True)

    # RULE source - a rule tree over the submission's answers (None = no gate).
    conditions_json = Column(JSON(none_as_null=True), nullable=True)

    sort_order = Column(Integer, nullable=False, default=0)


class ReviewRoleActor(Base):
    """A named candidate actor for an EXPLICIT or RULE role (D30). ``actor_kind``
    must equal the owning role's ``actor_identity_kind`` (service-enforced).
    Candidates are ordered by ``sort_order``; allocation (Part B) takes first-N
    up to the config's ``required_review_count``. An optional per-candidate
    ``conditions_json`` further-gates a RULE candidate (null = always eligible)."""

    __tablename__ = "review_role_actors"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    role_id = Column(String, nullable=False, index=True)

    actor_kind = Column(String, nullable=False)  # user|profile
    actor_id = Column(String, nullable=False)

    conditions_json = Column(JSON(none_as_null=True), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)


class ReviewAssignment(Base):
    """One reviewer's task for a submission group at a given revision (D37). The
    review itself is a ``form_submission`` of the review form, referenced by
    ``review_submission_id`` (NULL until graded). Per-revision - prior rounds are
    retained as history. UNIQUE prevents double-assigning the same actor for the
    same (config, group, revision)."""

    __tablename__ = "review_assignments"
    __table_args__ = (
        UniqueConstraint(
            "review_configuration_id",
            "reviewed_submission_group_id",
            "actor_kind",
            "actor_id",
            "revision_number",
            name="uq_review_assignments_actor_revision",
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    review_configuration_id = Column(String, nullable=False, index=True)

    # plan-04 stable identity (the submission group) + the round.
    reviewed_submission_group_id = Column(String, nullable=False, index=True)
    revision_number = Column(Integer, nullable=False, default=1)

    role_id = Column(String, nullable=False, index=True)
    actor_kind = Column(String, nullable=False)
    actor_id = Column(String, nullable=False)

    # → form_submission of the review form (NULL until graded).
    review_submission_id = Column(String, nullable=True)
    status = Column(
        String, nullable=False, default=ASSIGNMENT_PENDING, server_default=ASSIGNMENT_PENDING
    )

    assigned_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    completed_at = Column(UTCDateTime(), nullable=True)


class ReviewDecision(Base):
    """The terminal decision for a submission group at a revision (D34). Single
    decider, first-wins - the service writes a row IFF none exists yet for
    (config, group, revision); a second concurrent attempt is a no-op/409. The
    UNIQUE is the DB-level backstop for the first-wins guard."""

    __tablename__ = "review_decisions"
    __table_args__ = (
        UniqueConstraint(
            "review_configuration_id",
            "reviewed_submission_group_id",
            "revision_number",
            name="uq_review_decisions_group_revision",
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    review_configuration_id = Column(String, nullable=False, index=True)

    reviewed_submission_group_id = Column(String, nullable=False, index=True)
    revision_number = Column(Integer, nullable=False, default=1)

    decider_kind = Column(String, nullable=False)
    decider_id = Column(String, nullable=False)

    decision = Column(String, nullable=False)  # ACCEPTED|REJECTED|REVISIONS
    feedback_text = Column(Text, nullable=True)
    decided_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
