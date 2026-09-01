"""AI repositories - pure SQLAlchemy, every query tenant-scoped.

Skills are TWO-TIER (the template-engine pattern): a platform-tier row carries
`tenant_id IS NULL` and is visible to every tenant; a tenant's own row wins over
a platform row with the same key.
"""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.ai import (
    AiAgent,
    AiConversation,
    AiMessage,
    AiSkill,
    AiSkillVersion,
    AiSpan,
    AiTrace,
)

_AGENT_SORT_COLUMNS = {
    "name": AiAgent.name,
    "model": AiAgent.model,
    "isEnabled": AiAgent.is_enabled,
    "created": AiAgent.created_at,
    "updated": AiAgent.updated_at,
}

_SKILL_SORT_COLUMNS = {
    "name": AiSkill.name,
    "key": AiSkill.key,
    "created": AiSkill.created_at,
    "updated": AiSkill.updated_at,
}

_TRACE_SORT_COLUMNS = {
    "agentName": AiTrace.agent_name,
    "provider": AiTrace.provider,
    "model": AiTrace.model,
    "status": AiTrace.status,
    "latencyMs": AiTrace.latency_ms,
    "created": AiTrace.created_at,
}


class AgentRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_clause=None,
    ) -> Tuple[List[AiAgent], int]:
        q = self.db.query(AiAgent).filter(AiAgent.tenant_id == tenant_id)
        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(
                or_(
                    AiAgent.name.ilike(term),
                    AiAgent.description.ilike(term),
                    AiAgent.model.ilike(term),
                )
            )
        if filter_clause is not None:
            q = q.filter(filter_clause)
        total = q.count()
        column = _AGENT_SORT_COLUMNS.get(sort_by or "", AiAgent.name)
        q = q.order_by(column.desc() if sort_dir == "desc" else column.asc())
        q = q.order_by(AiAgent.id.asc())  # stable tiebreak for record-nav
        return q.offset(page * page_size).limit(page_size).all(), total

    def get(self, tenant_id: str, agent_id: str) -> Optional[AiAgent]:
        return (
            self.db.query(AiAgent)
            .filter(AiAgent.id == agent_id, AiAgent.tenant_id == tenant_id)
            .first()
        )

    def get_by_name(self, tenant_id: str, name: str) -> Optional[AiAgent]:
        return (
            self.db.query(AiAgent)
            .filter(AiAgent.tenant_id == tenant_id, AiAgent.name == name)
            .first()
        )

    def get_by_key(self, tenant_id: str, key: str) -> Optional[AiAgent]:
        """Resolve a system-seeded agent by its STABLE key (AC-BI-20b) - survives
        a display-name rename, unlike ``get_by_name``."""
        return (
            self.db.query(AiAgent)
            .filter(AiAgent.tenant_id == tenant_id, AiAgent.key == key)
            .first()
        )

    def add(self, agent: AiAgent) -> AiAgent:
        self.db.add(agent)
        self.db.flush()
        return agent

    def delete(self, agent: AiAgent) -> None:
        self.db.delete(agent)
        self.db.flush()

    def count_using_connection(self, tenant_id: str, connection_id: str) -> int:
        return (
            self.db.query(AiAgent)
            .filter(AiAgent.tenant_id == tenant_id, AiAgent.connection_id == connection_id)
            .count()
        )


class SkillRepository:
    def __init__(self, db: Session):
        self.db = db

    def visible_query(self, tenant_id: str):
        """Own rows + platform-tier rows (tenant_id IS NULL)."""
        return self.db.query(AiSkill).filter(
            or_(AiSkill.tenant_id == tenant_id, AiSkill.tenant_id.is_(None))
        )

    def list(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_clause=None,
    ) -> Tuple[List[AiSkill], int]:
        q = self.visible_query(tenant_id)
        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(
                or_(
                    AiSkill.name.ilike(term),
                    AiSkill.key.ilike(term),
                    AiSkill.description.ilike(term),
                )
            )
        if filter_clause is not None:
            q = q.filter(filter_clause)
        total = q.count()
        column = _SKILL_SORT_COLUMNS.get(sort_by or "", AiSkill.name)
        q = q.order_by(column.desc() if sort_dir == "desc" else column.asc())
        q = q.order_by(AiSkill.id.asc())
        return q.offset(page * page_size).limit(page_size).all(), total

    def get(self, tenant_id: str, skill_id: str) -> Optional[AiSkill]:
        return self.visible_query(tenant_id).filter(AiSkill.id == skill_id).first()

    def get_by_key(self, tenant_id: str, key: str) -> Optional[AiSkill]:
        """Tenant's own row wins over the platform-tier row of the same key."""
        own = (
            self.db.query(AiSkill)
            .filter(AiSkill.tenant_id == tenant_id, AiSkill.key == key)
            .first()
        )
        if own is not None:
            return own
        return (
            self.db.query(AiSkill)
            .filter(AiSkill.tenant_id.is_(None), AiSkill.key == key)
            .first()
        )

    def add(self, skill: AiSkill) -> AiSkill:
        self.db.add(skill)
        self.db.flush()
        return skill

    def delete(self, skill: AiSkill) -> None:
        self.db.delete(skill)
        self.db.flush()

    # ── versions (immutable, AC-BI-07) ────────────────────────────────────
    def list_versions(self, skill_id: str) -> List[AiSkillVersion]:
        return (
            self.db.query(AiSkillVersion)
            .filter(AiSkillVersion.skill_id == skill_id)
            .order_by(AiSkillVersion.version.desc())
            .all()
        )

    def get_version(self, skill_id: str, version_id: str) -> Optional[AiSkillVersion]:
        return (
            self.db.query(AiSkillVersion)
            .filter(
                AiSkillVersion.id == version_id,
                # Scope by the OWNING skill so a version id from another skill
                # can never be activated onto this one.
                AiSkillVersion.skill_id == skill_id,
            )
            .first()
        )

    def next_version_number(self, skill_id: str) -> int:
        latest = (
            self.db.query(AiSkillVersion.version)
            .filter(AiSkillVersion.skill_id == skill_id)
            .order_by(AiSkillVersion.version.desc())
            .first()
        )
        return (latest[0] + 1) if latest else 1

    def add_version(self, version: AiSkillVersion) -> AiSkillVersion:
        self.db.add(version)
        self.db.flush()
        return version


class ConversationRepository:
    """The grill transcript store (AC-BI-21). Pure SQLAlchemy, tenant-scoped,
    FLUSH-ONLY - the grill engine owns the single commit that keeps a turn atomic
    (user message + assistant message + trace land together; a provider error
    never leaves a half-written turn, AC-BI-23)."""

    def __init__(self, db: Session):
        self.db = db

    def get_for_target(
        self,
        tenant_id: str,
        *,
        target_type: str,
        target_id: str,
        grill_definition_key: str,
    ) -> Optional[AiConversation]:
        return (
            self.db.query(AiConversation)
            .filter(
                AiConversation.tenant_id == tenant_id,
                AiConversation.target_type == target_type,
                AiConversation.target_id == target_id,
                AiConversation.grill_definition_key == grill_definition_key,
            )
            .order_by(AiConversation.created_at.asc(), AiConversation.id.asc())
            .first()
        )

    def get_or_create_for_target(
        self,
        tenant_id: str,
        *,
        target_type: str,
        target_id: str,
        grill_definition_key: str,
        source_type: Optional[str] = None,
        source_ids: Optional[List[str]] = None,
        prompt_version: Optional[int] = None,
        template_version: Optional[int] = None,
    ) -> AiConversation:
        """The durable grill anchor: one conversation per (tenant, target,
        definition). Returns the existing row (a resumed session, AC-BI-21) or
        creates it. ``source_ids`` are refreshed each call so ideas linked
        mid-session re-seed the context on the NEXT turn (AC-BI-33)."""
        convo = self.get_for_target(
            tenant_id,
            target_type=target_type,
            target_id=target_id,
            grill_definition_key=grill_definition_key,
        )
        if convo is None:
            convo = AiConversation(
                tenant_id=tenant_id,
                source_type=source_type,
                source_ids_json=list(source_ids or []),
                target_type=target_type,
                target_id=target_id,
                grill_definition_key=grill_definition_key,
                prompt_version=prompt_version,
                template_version=template_version,
            )
            self.db.add(convo)
            self.db.flush()
            return convo
        # Refresh the source set + the (prompt, template) stamp it last ran under.
        if source_ids is not None:
            convo.source_ids_json = list(source_ids)
        if source_type is not None:
            convo.source_type = source_type
        if prompt_version is not None:
            convo.prompt_version = prompt_version
        if template_version is not None:
            convo.template_version = template_version
        self.db.flush()
        return convo

    def messages(self, conversation_id: str) -> List[AiMessage]:
        return (
            self.db.query(AiMessage)
            .filter(AiMessage.conversation_id == conversation_id)
            .order_by(AiMessage.created_at.asc(), AiMessage.id.asc())
            .all()
        )

    def add_message(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
        role: str,
        content: str,
        covered_fields: Optional[List[str]] = None,
        captured_summary: Optional[dict] = None,
    ) -> AiMessage:
        message = AiMessage(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            role=role,
            content=content or "",
            covered_fields_json=list(covered_fields) if covered_fields is not None else None,
            captured_summary_json=dict(captured_summary) if captured_summary else None,
            # Stamp wall-clock microsecond time - NOT ``func.now()`` (transaction
            # time in Postgres, identical for both turns of one grill turn, which
            # would make transcript order ambiguous). Successive appends get
            # distinct timestamps so ``ORDER BY created_at`` is insert order.
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(message)
        self.db.flush()
        return message


class TraceRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "desc",
        filter_clause=None,
    ) -> Tuple[List[AiTrace], int]:
        q = self.db.query(AiTrace).filter(AiTrace.tenant_id == tenant_id)
        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(
                or_(
                    AiTrace.agent_name.ilike(term),
                    AiTrace.model.ilike(term),
                    AiTrace.provider.ilike(term),
                    AiTrace.error.ilike(term),
                )
            )
        if filter_clause is not None:
            q = q.filter(filter_clause)
        total = q.count()
        column = _TRACE_SORT_COLUMNS.get(sort_by or "", AiTrace.created_at)
        # Traces default newest-first - the useful order for debugging.
        q = q.order_by(column.asc() if sort_dir == "asc" else column.desc())
        q = q.order_by(AiTrace.id.asc())
        return q.offset(page * page_size).limit(page_size).all(), total

    def get(self, tenant_id: str, trace_id: str) -> Optional[AiTrace]:
        return (
            self.db.query(AiTrace)
            .filter(AiTrace.id == trace_id, AiTrace.tenant_id == tenant_id)
            .first()
        )

    def list_spans(self, tenant_id: str, trace_id: str) -> List[AiSpan]:
        """Ordered flat step list (AC-BI-09). `dotted_order` is already the sort
        key the future tree renderer will use unchanged."""
        return (
            self.db.query(AiSpan)
            .filter(AiSpan.trace_id == trace_id, AiSpan.tenant_id == tenant_id)
            .order_by(AiSpan.dotted_order.asc(), AiSpan.created_at.asc())
            .all()
        )
