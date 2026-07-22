"""AI repositories — pure SQLAlchemy, every query tenant-scoped.

Skills are TWO-TIER (the template-engine pattern): a platform-tier row carries
`tenant_id IS NULL` and is visible to every tenant; a tenant's own row wins over
a platform row with the same key.
"""
from typing import List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.ai import AiAgent, AiSkill, AiSkillVersion, AiSpan, AiTrace

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
        # Traces default newest-first — the useful order for debugging.
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
