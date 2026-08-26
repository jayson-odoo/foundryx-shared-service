"""Core AI subsystem tables (Phase B-i slice 1, plan §5).

CORE, not a module (Bi-D2): four existing engines will want agents (a workflow
action, form auto-fill, an omnichannel reply-draft), and moving a table out of a
module schema later is a migration nobody wants.

Shape notes that are load-bearing:
- **Credential ≠ persona (Bi-D3).** An agent holds NO API key - it points at a
  `connections` row (`type='llm'`), which owns the Fernet-encrypted secret.
- **A skill version is IMMUTABLE (Bi-D5/AC-BI-07).** An edit inserts a new
  `ai_skill_versions` row and repoints the movable `active_version_id` label;
  rollback is a label move, never a content copy or delete.
- **Spans carry `parent_id` + `dotted_order` from day one** even though slice 1
  only ever writes depth-1 sequences - the flat renderer is the deferred piece,
  not the model (Bi-D17). Real tool loops land later with no migration.
- All datetimes `UTCDateTime`; all JSON `JSON(none_as_null=True)`.
"""
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.utc_datetime import UTCDateTime

# Trace outcome - code branches only on these.
TRACE_STATUS_OK = "ok"
TRACE_STATUS_ERROR = "error"

# Span kinds (AC-BI-09). `tool:<name>` is the open seam for future agent tools.
SPAN_KIND_LLM_CALL = "llm_call"
SPAN_KIND_VALIDATE = "validate"
SPAN_KIND_RETRY = "retry"
SPAN_KINDS = (SPAN_KIND_LLM_CALL, SPAN_KIND_VALIDATE, SPAN_KIND_RETRY)

# Transcript roles.
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
MESSAGE_ROLES = (ROLE_USER, ROLE_ASSISTANT)


def _uuid() -> str:
    return str(uuid.uuid4())


def _tenant_id_from_agent(context) -> str:
    """Context-sensitive default for the join's ``tenant_id`` (the BL-015
    pattern). Relationship appends only populate the FK columns, so the tenant
    is DERIVED from the owning agent at insert - never a static default."""
    agent_id = context.get_current_parameters().get("agent_id")
    if agent_id:
        tenant_id = context.connection.execute(
            text("SELECT tenant_id FROM ai_agents WHERE id = :aid"), {"aid": agent_id}
        ).scalar()
        if tenant_id:
            return tenant_id
    raise ValueError("ai_agent_skills.tenant_id could not be derived from the agent.")


# An agent equips a SET of skills, like a Claude agent's skill set (AC-BI-06b) -
# NOT one. Which of the equipped skills actually RUNS a given grill is the
# GrillDefinition's choice in slice 3; S1 only stores the set. `tenant_id` is
# denormalised (derived from the owning agent at insert) so the join reads stay
# tenant-scoped without a three-way join.
ai_agent_skills = Table(
    "ai_agent_skills",
    Base.metadata,
    Column(
        "agent_id",
        String,
        ForeignKey("ai_agents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "skill_id",
        String,
        ForeignKey("ai_skills.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tenant_id",
        String,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        default=_tenant_id_from_agent,
        index=True,
    ),
    UniqueConstraint("agent_id", "skill_id", name="uq_ai_agent_skills"),
)


class AiAgent(Base):
    """A persona: which connection, which model, how hot, which skills it equips."""

    __tablename__ = "ai_agents"
    __table_args__ = (
        Index("ix_ai_agents_tenant_name", "tenant_id", "name"),
        # One agent per (tenant, key) - only where a key is set (system agents).
        Index(
            "uq_ai_agents_tenant_key",
            "tenant_id",
            "key",
            unique=True,
            postgresql_where=Column("key").isnot(None),
            sqlite_where=Column("key").isnot(None),
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # A STABLE code key for system-seeded agents (mirrors AiSkill.key/is_system).
    # The display `name` is freely editable (AC-BI-20b); a consumer that must
    # resolve a specific seeded agent (the grill's "ideation-grill") binds by
    # THIS key, never by the mutable name (the hardcode-a-tenant-editable-value
    # trap). NULL for user-created agents; a partial unique index scopes it per
    # tenant only when set.
    key = Column(String, nullable=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    # Seeded system agents: `key` is locked + delete-blocked (name/model/skills
    # stay editable, AC-BI-20b). Mirrors AiSkill.is_system.
    is_system = Column(Boolean, nullable=False, default=False)
    # The LLM credential (Bi-D1/Bi-D3). RESTRICT would strand the UI, so the
    # column nulls out on delete and the agent then surfaces the missing-
    # prerequisite warning (AC-BI-06) instead of failing silently at run time.
    connection_id = Column(
        String, ForeignKey("connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # A pinned model id. If the provider retires it, a run fails LOUDLY -
    # never a silent substitution (AC-BI-05).
    model = Column(String, nullable=False, default="")
    temperature = Column(Float, nullable=False, default=0.0)
    is_enabled = Column(Boolean, nullable=False, default=True)
    # The equipped skill set (AC-BI-06b). `ondelete=CASCADE` on the join means a
    # deleted skill just drops out of the set; ordered by name for stable reads.
    skills = relationship(
        "AiSkill",
        secondary=ai_agent_skills,
        order_by="AiSkill.name",
        lazy="selectin",
    )

    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AiSkill(Base):
    """A browsable, selectable prompt artifact - never an anonymous text blob on
    the agent row (AC-BI-07). ``tenant_id IS NULL`` = the platform tier."""

    __tablename__ = "ai_skills"
    __table_args__ = (
        # Two-tier uniqueness needs PARTIAL indexes per tier (the BL-065
        # lesson): a plain unique over a nullable column doesn't constrain the
        # platform tier on Postgres.
        Index(
            "uq_ai_skills_tenant_key",
            "tenant_id",
            "key",
            unique=True,
            postgresql_where=Column("tenant_id").isnot(None),
            sqlite_where=Column("tenant_id").isnot(None),
        ),
        Index(
            "uq_ai_skills_platform_key",
            "key",
            unique=True,
            postgresql_where=Column("tenant_id").is_(None),
            sqlite_where=Column("tenant_id").is_(None),
        ),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    key = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    # The movable `active` label (AC-BI-07). No FK: the version rows FK back to
    # the skill, and a mutual FK pair deadlocks insert ordering.
    active_version_id = Column(String, nullable=True, index=True)
    # Seeded platform skills are delete-locked; their body stays editable.
    is_system = Column(Boolean, nullable=False, default=False)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AiSkillVersion(Base):
    """IMMUTABLE prompt body. Never updated in place - an edit inserts the next
    version and the skill's `active_version_id` label moves (AC-BI-07)."""

    __tablename__ = "ai_skill_versions"
    __table_args__ = (
        Index("uq_ai_skill_versions_skill_version", "skill_id", "version", unique=True),
    )

    id = Column(String, primary_key=True, default=_uuid)
    skill_id = Column(
        String, ForeignKey("ai_skills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalised so version reads stay tenant-scoped without a join.
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    version = Column(Integer, nullable=False)
    body = Column(Text, nullable=False, default="")
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)


class AiConversation(Base):
    """A grill transcript's anchor (slice 3 fills it; the table lands here so
    slice 3 adds no core migration). Binds source artifacts → target artifact."""

    __tablename__ = "ai_conversations"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type = Column(String, nullable=True)
    # Many sources → one target (an Idea cluster feeding a BR).
    source_ids_json = Column(JSON(none_as_null=True), nullable=True)
    target_type = Column(String, nullable=True, index=True)
    target_id = Column(String, nullable=True, index=True)
    grill_definition_key = Column(String, nullable=True)
    # The (prompt, template) pair this conversation ran under, so a poor result
    # is attributable to a specific prompt version (AC-BI-21).
    prompt_version = Column(Integer, nullable=True)
    template_version = Column(Integer, nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AiMessage(Base):
    """One transcript turn."""

    __tablename__ = "ai_messages"
    __table_args__ = (
        Index("ix_ai_messages_conversation_created", "conversation_id", "created_at"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    conversation_id = Column(
        String, ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False, default="")
    # The cheap coverage map a grill turn reports (slice 3, AC-BI-22).
    covered_fields_json = Column(JSON(none_as_null=True), nullable=True)
    # The running per-field captured summary a grill turn reports (AC-BI-24c) -
    # a {fieldKey: shortValue} map. Persisted on the assistant turn so the panel
    # survives a reload / resumed session (durable draft, AC-BI-21).
    captured_summary_json = Column(JSON(none_as_null=True), nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)


class AiTrace(Base):
    """One run. Field naming follows OTel GenAI semconv so a future OTLP export
    is a field-map, not a rewrite (AC-BI-09)."""

    __tablename__ = "ai_traces"
    __table_args__ = (
        Index("ix_ai_traces_tenant_created", "tenant_id", "created_at"),
        # The retention sweep scans (status, created_at) - `ok` prunes sooner
        # than `error`/`flagged` (AC-BI-10).
        Index("ix_ai_traces_status_created", "status", "created_at"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id = Column(
        String, ForeignKey("ai_conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_id = Column(
        String, ForeignKey("ai_agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Denormalised display name - survives the agent being deleted, so an old
    # trace stays readable (the whole point of keeping traces).
    agent_name = Column(String, nullable=False, default="")
    skill_key = Column(String, nullable=True)
    prompt_version = Column(Integer, nullable=True)
    # gen_ai.system / gen_ai.request.model in OTel GenAI terms.
    provider = Column(String, nullable=False, default="")
    model = Column(String, nullable=False, default="")
    # gen_ai.usage.input_tokens / .output_tokens.
    tokens_in = Column(Integer, nullable=False, default=0)
    tokens_out = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default=TRACE_STATUS_OK)
    error = Column(Text, nullable=True)
    # Operator-set review marker; keeps a trace past the `ok` TTL (AC-BI-10).
    flagged = Column(Boolean, nullable=False, default=False)
    span_count = Column(Integer, nullable=False, default=0)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)


class AiSpan(Base):
    """One step within a run - `llm_call`, `validate`, `retry`, later `tool:*`.

    `input_json`/`output_json` are SIZE-CAPPED with truncation marked so a long
    grill can't bloat Postgres unbounded (AC-BI-10) - see `app/ai/tracing.py`.
    """

    __tablename__ = "ai_spans"
    __table_args__ = (
        Index("ix_ai_spans_trace_order", "trace_id", "dotted_order"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    trace_id = Column(
        String, ForeignKey("ai_traces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id = Column(
        String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Present from day one for the future tree (Bi-D17); slice 1 writes NULL.
    parent_id = Column(String, nullable=True)
    # Sortable materialised path ("1", "2", "2.1") - one ORDER BY renders the
    # flat list now and the tree later.
    dotted_order = Column(String, nullable=False, default="")
    span_kind = Column(String, nullable=False)
    name = Column(String, nullable=False, default="")
    input_json = Column(JSON(none_as_null=True), nullable=True)
    output_json = Column(JSON(none_as_null=True), nullable=True)
    tokens_in = Column(Integer, nullable=False, default=0)
    tokens_out = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default=TRACE_STATUS_OK)
    error = Column(Text, nullable=True)
    started_at = Column(UTCDateTime(), nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
