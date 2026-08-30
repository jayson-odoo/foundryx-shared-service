"""Workflow engine models (plan sprint-2/08) - core ``public`` tables.

A ``Workflow`` carries a mutable ``draft_definition_json`` (the editor's working
graph). Publishing snapshots the draft into an immutable ``WorkflowVersion`` and
points ``current_version_id`` at it (D4) - only the current version fires.
A ``WorkflowRun`` snapshots the EXACT graph it executed (draft or version) so
the Logs replay is always faithful regardless of later edits (D6); per-node
trace lives in ``WorkflowRunNode``.
"""
import uuid

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.utc_datetime import UTCDateTime

# Run lifecycle - code branches only on these.
RUN_PENDING = "pending"
RUN_RUNNING = "running"
RUN_SUCCESS = "success"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"

# Per-node lifecycle.
NODE_PENDING = "pending"
NODE_RUNNING = "running"
NODE_SUCCESS = "success"
NODE_FAILED = "failed"
NODE_SKIPPED = "skipped"

# How a run was triggered.
TRIGGER_MANUAL = "manual"
TRIGGER_SCHEDULE = "schedule"
TRIGGER_EVENT = "event"

# Loop-guard backstop (D-loop, slice 09 enforces; 08 carries the column).
MAX_RUN_DEPTH = 5


def _uuid() -> str:
    return str(uuid.uuid4())


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    is_active = Column(Boolean, nullable=False, default=False)
    is_trashed = Column(Boolean, nullable=False, default=False, index=True)

    # The editor's working copy (forever-contract doc, D3).
    draft_definition_json = Column(JSON, nullable=False, default=dict)
    # The published version that fires (NULL = never published).
    current_version_id = Column(String, nullable=True)

    # Denormalized trigger of the PUBLISHED version - fast event/schedule
    # matching without parsing JSON (set on publish, D4 / slice 09).
    trigger_type = Column(String, nullable=True, index=True)
    trigger_entity_type = Column(String, nullable=True, index=True)
    trigger_action = Column(String, nullable=True, index=True)
    # Scheduled-trigger drain pointer (slice 09).
    next_run_at = Column(UTCDateTime(), nullable=True, index=True)

    created_by = Column(String, nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    versions = relationship(
        "WorkflowVersion",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowVersion.version_number",
    )
    agent_states = relationship(
        "WorkflowAgentState",
        back_populates="workflow",
        cascade="all, delete-orphan",
    )


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"

    id = Column(String, primary_key=True, default=_uuid)
    workflow_id = Column(
        String, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number = Column(Integer, nullable=False)
    # Immutable snapshot of the draft at publish time.
    definition_json = Column(JSON, nullable=False)
    published_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    published_by = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    # Set when the publishing actor held ``workflows.code`` and the graph carries
    # a Code node (sprint-4/19 S4). Automated triggers execute a Code-bearing
    # version ONLY when it is stamped - no per-run end-user permission context.
    code_authorized_by = Column(String, nullable=True)

    workflow = relationship("Workflow", back_populates="versions")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index(
            "ix_workflow_runs_serialized_pending",
            "tenant_id",
            "workflow_id",
            "correlation_key_digest",
            "status",
            "created_at",
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    workflow_id = Column(
        String, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The version this run executed (NULL = a draft/manual run, D13).
    version_id = Column(String, nullable=True)
    version_number = Column(Integer, nullable=False, default=0)  # 0 = draft

    status = Column(String, nullable=False, default=RUN_PENDING, index=True)
    triggered_by = Column(String, nullable=False, default=TRIGGER_MANUAL)
    is_test = Column(Boolean, nullable=False, default=False)

    # The EXACT graph executed - replay is faithful even after edits (D6).
    definition_snapshot_json = Column(JSON, nullable=False)
    trigger_payload_json = Column(JSON, nullable=False, default=dict)
    # Resolved exactly once from the immutable definition + trigger payload at
    # creation. The digest scopes Redis leases without exposing the raw key.
    correlation_key = Column(String, nullable=True)
    correlation_key_digest = Column(String(64), nullable=True)

    # Loop chain (slice 09 loop-guard).
    triggered_by_run_id = Column(String, nullable=True)
    depth = Column(Integer, nullable=False, default=0)
    actor_id = Column(String, nullable=True)

    error = Column(Text, nullable=True)
    started_at = Column(UTCDateTime(), nullable=True)
    finished_at = Column(UTCDateTime(), nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False, index=True)

    nodes = relationship(
        "WorkflowRunNode",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="WorkflowRunNode.order_index",
    )


class WorkflowRunNode(Base):
    __tablename__ = "workflow_run_nodes"

    id = Column(String, primary_key=True, default=_uuid)
    run_id = Column(
        String, ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id = Column(String, nullable=False)
    node_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default=NODE_PENDING)
    order_index = Column(Integer, nullable=False, default=0)
    input_json = Column(JSON, nullable=True)
    output_json = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(UTCDateTime(), nullable=True)
    finished_at = Column(UTCDateTime(), nullable=True)

    run = relationship("WorkflowRun", back_populates="nodes")


class WorkflowAgentState(Base):
    """Durable accepted state for one stateful AI Agent node and key."""

    __tablename__ = "workflow_agent_states"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workflow_id",
            "node_id",
            "correlation_key",
            name="uq_workflow_agent_state_scope",
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_id = Column(
        String, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id = Column(String, nullable=False)
    correlation_key = Column(String, nullable=False)
    state_json = Column(JSON(none_as_null=True), nullable=False, default=dict)
    provenance_json = Column(JSON(none_as_null=True), nullable=False, default=dict)
    pending_question = Column(String, nullable=True)
    pending_field = Column(String, nullable=True)
    revision = Column(Integer, nullable=False, default=0)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    workflow = relationship("Workflow", back_populates="agent_states")


class WorkflowSettings(Base):
    """Per-tenant workflow engine settings (plan sprint-2/10) - one row per
    tenant. ``run_retention_days`` NULL = fall back to the global default
    (``settings.workflow_run_retention_days``)."""

    __tablename__ = "workflow_settings"

    tenant_id = Column(String, primary_key=True)
    run_retention_days = Column(Integer, nullable=True)
