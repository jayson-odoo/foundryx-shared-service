"""Notify-on-transition specs (sprint-2/01 D6) — generic, NOT transition-owned.

A spec = channel + inline merge-field template + recipient list. Transitions
*reference* specs via the ``notification_spec_transitions`` link (N:N — a spec
is reusable across edges). Dispatch is EMAIL via the plan-09 outbox; ``IN_APP``
is modeled but inert (inbox UI = follow-up backlog). ``template_key`` is a
loose string for the future Template engine (BL-024) to claim.
"""
import uuid

from sqlalchemy import JSON, Column, ForeignKey, String, Table, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base

# Channels — flags-not-enums applies to statuses; channels ARE a closed set.
CHANNEL_EMAIL = "EMAIL"
CHANNEL_IN_APP = "IN_APP"
NOTIFICATION_CHANNELS = (CHANNEL_EMAIL, CHANNEL_IN_APP)

# Recipient targeting.
TARGET_USER = "USER"
TARGET_ROLE = "ROLE"
TARGET_DYNAMIC = "DYNAMIC"
RECIPIENT_TARGET_TYPES = (TARGET_USER, TARGET_ROLE, TARGET_DYNAMIC)

DYNAMIC_ACTOR = "ACTOR"
DYNAMIC_ASSIGNEE = "ASSIGNEE"
DYNAMIC_RECORD_OWNER = "RECORD_OWNER"
DYNAMIC_KEYS = (DYNAMIC_ACTOR, DYNAMIC_ASSIGNEE, DYNAMIC_RECORD_OWNER)


# Which transitions fire which specs (N:N).
notification_spec_transitions = Table(
    "notification_spec_transitions",
    Base.metadata,
    Column(
        "transition_id",
        String,
        ForeignKey("status_transitions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "spec_id",
        String,
        ForeignKey("notification_specs.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class NotificationSpec(Base):
    __tablename__ = "notification_specs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # NULL = platform-owned default spec.
    tenant_id = Column(String, nullable=True, index=True)
    channel = Column(String, nullable=False, default=CHANNEL_EMAIL)
    # Inline merge-field templates ({{recordLabel}}, {{toStatus}}, …) — the
    # Template engine (BL-024) swaps this renderer later via template_key.
    template_subject = Column(String, nullable=False)
    template_body = Column(Text, nullable=False)
    template_key = Column(String, nullable=True)
    # Engine template reference (plan 07 D10) — when set, dispatch renders
    # the referenced template instead of the inline subject/body; template
    # deletion falls the spec back to inline (SET NULL).
    template_id = Column(
        String, ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )
    # Per-use COPY of a template's block document (plan 10 follow-up) — the
    # operator picked a template and edited the wording inline. When set,
    # dispatch renders this doc branded (subject = template_subject), taking
    # precedence over template_id + the inline subject/body.
    doc_json = Column(JSON(none_as_null=True), nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # delete-orphan: recipients live and die with their spec.
    recipients = relationship(
        "NotificationRecipient",
        lazy="selectin",
        cascade="all, delete-orphan",
        backref="spec",
    )


class NotificationRecipient(Base):
    __tablename__ = "notification_recipients"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    spec_id = Column(
        String, ForeignKey("notification_specs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # USER → target_id = user id; ROLE → target_id = role id;
    # DYNAMIC → dynamic_key resolves against the record/actor at fire time.
    target_type = Column(String, nullable=False)
    target_id = Column(String, nullable=True)
    dynamic_key = Column(String, nullable=True)
