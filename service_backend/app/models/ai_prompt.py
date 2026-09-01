"""AI prompt registry - immutable versions + movable labels (Meetings S4, R4).

Platform-global (no `tenant_id`, deliberate - R4/R5): prompts are platform
infra, runtime-editable without a deploy; the editor UI is platform-admin
only and a per-tenant fork is not built (R5's trigger: a second tenant asking
for different minutes structure).

Ported from sorento's `ai_prompt_versions` / `ai_prompt_labels` two-table
mechanism (`app/models/ai_prompt.py` there), trimmed for shared-service's
single consumer (`meetings_minutes`): no per-key registry dict, no per-label
`provider`/`model` override (R1's LLM resolution lives in
`tenant_settings.llm_connection_id` / the platform env default, not on the
label - trigger to add one: a second prompt consumer wanting its own model).

- `AIPromptVersion` - immutable, append-only snapshot per `(name, version)`.
- `AIPromptLabel` - movable pointer, one row per `(name, label)`. Publish =
  repoint `version_id`; version rows never change. No update/delete route
  exists anywhere for a version (AC-S4-9).
"""
import uuid

from sqlalchemy import Column, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base
from app.models.utc_datetime import UTCDateTime


def _uuid() -> str:
    return str(uuid.uuid4())


class AIPromptVersion(Base):
    """Immutable, append-only prompt snapshot. Never edited in place."""

    __tablename__ = "ai_prompt_versions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_ai_prompt_versions_name_version"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    # Stable key, e.g. "meetings_minutes". Not an FK - the registry resolver
    # falls back to a hardcoded spec when no row exists for a known name.
    name = Column(String, nullable=False, index=True)
    # Auto-incremented PER name (max(version)+1 on insert), never global.
    version = Column(Integer, nullable=False)
    template = Column(Text, nullable=False, default="")
    # Declared template variables, e.g. ["title", "participants"].
    variables = Column(JSON, nullable=False, default=list)
    commit_message = Column(Text, nullable=True)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)


class AIPromptLabel(Base):
    """Movable pointer: one row per `(name, label)` -> a version id."""

    __tablename__ = "ai_prompt_labels"
    __table_args__ = (
        UniqueConstraint("name", "label", name="uq_ai_prompt_labels_name_label"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False, index=True)
    # "production" | "staging" (AI_PROMPT_LABELS).
    label = Column(String, nullable=False)
    version_id = Column(
        String, ForeignKey("ai_prompt_versions.id", ondelete="CASCADE"), nullable=False
    )
    updated_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
