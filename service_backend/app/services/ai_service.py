"""AI services (Phase B-i slice 1) - business logic over the AI repositories.

Three services, one per surface:
- `AgentService`   - the persona registry (+ the missing-prerequisite warning).
- `SkillService`   - versioned prompt artifacts: an edit MINTS a new immutable
                     version and moves the `active` label; rollback is a label
                     move. A version row is never mutated (AC-BI-07).
- `TraceService`   - read-only observability + the flag toggle.

Every query is tenant-scoped through the repositories; ids arriving from a
client (connection, skill, version) are re-validated against the caller's tenant
before they are stored (the polymorphic-target rule).
"""
import csv
import io
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.integrations import get_provider
from app.integrations.base import LLMError
from app.models.ai import (
    AiAgent,
    AiSkill,
    AiSkillVersion,
    AiTrace,
    ai_agent_skills,
)
from app.models.connection import (
    CONNECTION_STATUS_ERROR,
    Connection,
)
from app.models.tenant import PLATFORM_TENANT_ID
from app.models.user import User
from app.repositories.ai_repository import AgentRepository, SkillRepository, TraceRepository
from app.schemas.ai import (
    AgentCreateRequest,
    AgentOut,
    AgentUpdateRequest,
    AiPrerequisiteOut,
    ConnectionOptionOut,
    EquippedSkillOut,
    ModelListResponse,
    ModelOptionOut,
    SkillCreateRequest,
    SkillOptionOut,
    SkillOut,
    SkillUpdateRequest,
    SkillVersionOut,
    SpanOut,
    TraceDetailOut,
    TraceOut,
)
from app.schemas.user import FilterGroup
from app.services.filter_translator import translate_filter

LLM_TYPE = "llm"

_AGENT_FILTER_COLUMNS = {
    "name": AiAgent.name,
    "model": AiAgent.model,
    "isEnabled": AiAgent.is_enabled,
    "created": AiAgent.created_at,
}
_SKILL_FILTER_COLUMNS = {
    "name": AiSkill.name,
    "key": AiSkill.key,
    "created": AiSkill.created_at,
}
_TRACE_FILTER_COLUMNS = {
    "agentName": AiTrace.agent_name,
    "provider": AiTrace.provider,
    "model": AiTrace.model,
    "status": AiTrace.status,
    "flagged": AiTrace.flagged,
    "created": AiTrace.created_at,
}


def _translate(filter_group: Optional[FilterGroup], columns):
    return translate_filter(filter_group, columns) if filter_group else None


class AgentService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AgentRepository(db)
        self.skills = SkillRepository(db)

    # ── prerequisite + option sources ─────────────────────────────────────
    def _llm_connections(self, tenant_id: str) -> List[Connection]:
        """Every LLM connection this tenant may point an agent at: its own rows
        plus the platform tenant's (the SMTP/storage fallback shape, Bi-D18)."""
        owners = [tenant_id]
        if tenant_id != PLATFORM_TENANT_ID:
            owners.append(PLATFORM_TENANT_ID)
        return (
            self.db.query(Connection)
            .filter(
                Connection.tenant_id.in_(owners),
                Connection.type == LLM_TYPE,
                Connection.is_active.is_(True),
            )
            .order_by(Connection.created_at.asc(), Connection.id.asc())
            .all()
        )

    def prerequisite(self, tenant_id: str) -> AiPrerequisiteOut:
        rows = self._llm_connections(tenant_id)
        usable = [c for c in rows if c.status != CONNECTION_STATUS_ERROR]
        return AiPrerequisiteOut(
            hasConnection=bool(usable),
            connections=[
                ConnectionOptionOut(
                    id=c.id,
                    name=c.name,
                    provider=c.provider,
                    status=c.status,
                    isPlatform=c.tenant_id == PLATFORM_TENANT_ID,
                )
                for c in rows
            ],
        )

    def skill_options(self, tenant_id: str) -> List[SkillOptionOut]:
        rows, _ = self.skills.list(tenant_id, page=0, page_size=200, sort_by="name")
        return [SkillOptionOut(id=s.id, name=s.name) for s in rows]

    def models(self, tenant_id: str, connection_id: str) -> ModelListResponse:
        """Live model list, falling back to the provider's curated static list.

        The form MUST still render when the live call fails (AC-BI-05), so a
        provider error is reported in `message` rather than raised.
        """
        connection = self._get_connection(tenant_id, connection_id)
        provider = get_provider(connection.provider)
        if provider is None or getattr(provider, "type", "") != LLM_TYPE:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "That connection is not an AI provider.",
            )

        from app.ai.stub import is_dev  # noqa: PLC0415 - avoids an import cycle
        from app.secrets import decrypt_secret
        from cryptography.fernet import InvalidToken

        try:
            credentials = decrypt_secret(connection.credentials_json) if connection.credentials_json else {}
        except InvalidToken:
            credentials = {}

        static = [
            ModelOptionOut(id=m.id, label=m.label)
            for m in getattr(provider, "static_models", [])
        ]

        if is_dev(credentials, has_connection=True):
            from app.ai.stub import stub_provider  # noqa: PLC0415

            return ModelListResponse(
                data=[
                    ModelOptionOut(id=m.id, label=m.label)
                    for m in stub_provider.models({}, credentials)
                ],
                isLive=True,
            )

        try:
            live = provider.models(dict(connection.config_json or {}), credentials)
        except LLMError as exc:
            return ModelListResponse(data=static, isLive=False, message=str(exc))
        if not live:
            return ModelListResponse(
                data=static,
                isLive=False,
                message="The provider listed no chat models.",
            )
        return ModelListResponse(
            data=[ModelOptionOut(id=m.id, label=m.label) for m in live], isLive=True
        )

    # ── reads ─────────────────────────────────────────────────────────────
    def list(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[List[AgentOut], int]:
        rows, total = self.repo.list(
            tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_clause=_translate(filter_group, _AGENT_FILTER_COLUMNS),
        )
        return self._to_out_many(tenant_id, rows), total

    def get(self, tenant_id: str, agent_id: str) -> AgentOut:
        return self._to_out_many(tenant_id, [self._get_or_404(tenant_id, agent_id)])[0]

    def at(
        self,
        tenant_id: str,
        index: int,
        *,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[Optional[AgentOut], int]:
        rows, total = self.repo.list(
            tenant_id,
            page=index,
            page_size=1,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_clause=_translate(filter_group, _AGENT_FILTER_COLUMNS),
        )
        out = self._to_out_many(tenant_id, rows)
        return (out[0] if out else None), total

    def export(
        self,
        tenant_id: str,
        columns: List[str],
        *,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> str:
        rows, _ = self.repo.list(
            tenant_id,
            page=0,
            page_size=10_000,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_clause=_translate(filter_group, _AGENT_FILTER_COLUMNS),
        )
        out = self._to_out_many(tenant_id, rows)
        labels = {
            "id": "ID",
            "name": "Name",
            "description": "Description",
            "connectionName": "Connection",
            "provider": "Provider",
            "model": "Model",
            "temperature": "Temperature",
            "isEnabled": "Enabled",
            "createdAt": "Created",
        }
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([labels.get(c, c) for c in columns])
        for row in out:
            writer.writerow([_csv_cell(getattr(row, c, "")) for c in columns])
        return buffer.getvalue()

    # ── writes ────────────────────────────────────────────────────────────
    def create(self, tenant_id: str, req: AgentCreateRequest, actor: User) -> AgentOut:
        name = (req.name or "").strip()
        if not name:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name is required.")
        if self.repo.get_by_name(tenant_id, name) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f'An agent named "{name}" already exists.'
            )
        agent = AiAgent(
            tenant_id=tenant_id,
            name=name,
            description=(req.description or "").strip(),
            connection_id=self._validated_connection_id(tenant_id, req.connectionId),
            model=(req.model or "").strip(),
            temperature=_validated_temperature(req.temperature),
            skills=self._validated_skills(tenant_id, req.skillIds),
            is_enabled=req.isEnabled,
            created_by=actor.id,
            updated_by=actor.id,
        )
        self.repo.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return self._to_out_many(tenant_id, [agent])[0]

    def update(
        self, tenant_id: str, agent_id: str, req: AgentUpdateRequest, actor: User
    ) -> AgentOut:
        agent = self._get_or_404(tenant_id, agent_id)
        if req.name is not None:
            name = req.name.strip()
            if not name:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name is required.")
            clash = self.repo.get_by_name(tenant_id, name)
            if clash is not None and clash.id != agent.id:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, f'An agent named "{name}" already exists.'
                )
            agent.name = name
        if req.description is not None:
            agent.description = req.description.strip()
        if req.connectionId is not None:
            agent.connection_id = self._validated_connection_id(tenant_id, req.connectionId)
        if req.model is not None:
            agent.model = req.model.strip()
        if req.temperature is not None:
            agent.temperature = _validated_temperature(req.temperature)
        if req.skillIds is not None:
            # Replace the whole equipped set; [] clears it. selectin-loaded, so
            # reassigning the list syncs the join rows.
            agent.skills = self._validated_skills(tenant_id, req.skillIds)
        if req.isEnabled is not None:
            agent.is_enabled = req.isEnabled
        agent.updated_by = actor.id
        self.db.commit()
        self.db.refresh(agent)
        return self._to_out_many(tenant_id, [agent])[0]

    def delete(self, tenant_id: str, agent_id: str) -> None:
        agent = self._get_or_404(tenant_id, agent_id)
        # System-seeded agents (e.g. the grill's "ideation-grill") are delete-
        # locked - a consumer binds to them by key (mirrors AiSkill.is_system).
        # Name/model/skills stay editable (AC-BI-20b).
        if agent.is_system:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This is a system agent and cannot be deleted.",
            )
        self.repo.delete(agent)
        self.db.commit()

    # ── helpers ───────────────────────────────────────────────────────────
    def _get_or_404(self, tenant_id: str, agent_id: str) -> AiAgent:
        agent = self.repo.get(tenant_id, agent_id)
        if agent is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found.")
        return agent

    def _get_connection(self, tenant_id: str, connection_id: str) -> Connection:
        owners = [tenant_id]
        if tenant_id != PLATFORM_TENANT_ID:
            owners.append(PLATFORM_TENANT_ID)
        connection = (
            self.db.query(Connection)
            .filter(Connection.id == connection_id, Connection.tenant_id.in_(owners))
            .first()
        )
        if connection is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found.")
        return connection

    def _validated_connection_id(
        self, tenant_id: str, connection_id: Optional[str]
    ) -> Optional[str]:
        """Validate on WRITE that the connection belongs to this tenant (or the
        platform fallback) and is an LLM connection - a cross-tenant id is
        refused here, and `resolve_for_agent` re-scopes it at USE time."""
        if not connection_id:
            return None
        connection = self._get_connection(tenant_id, connection_id)
        if connection.type != LLM_TYPE:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "That connection is not an AI provider.",
            )
        return connection.id

    def _validated_skills(self, tenant_id: str, skill_ids: Optional[List[str]]) -> List[AiSkill]:
        """Resolve the equipped set (AC-BI-06b), validating EACH id belongs to
        this tenant's own tier OR the platform tier - a foreign-tenant skill id
        is refused (the polymorphic-target rule: validate on write). Duplicates
        collapse; order is preserved for a stable set."""
        if not skill_ids:
            return []
        seen: set[str] = set()
        resolved: List[AiSkill] = []
        for skill_id in skill_ids:
            if not skill_id or skill_id in seen:
                continue
            seen.add(skill_id)
            skill = self.skills.get(tenant_id, skill_id)  # own tier OR platform tier
            if skill is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "One or more selected skills do not exist for this workspace.",
                )
            resolved.append(skill)
        return resolved

    def _to_out_many(self, tenant_id: str, agents: List[AiAgent]) -> List[AgentOut]:
        """Batch-resolve connection display data (one query, never per-row) and
        derive the missing-prerequisite warning. The equipped skill set rides
        the selectin-loaded `agent.skills` relationship - tenant-scoped by
        construction (the join is per-agent, the agent is tenant-scoped)."""
        if not agents:
            return []
        connection_ids = {a.connection_id for a in agents if a.connection_id}

        connections: Dict[str, Connection] = {}
        if connection_ids:
            owners = [tenant_id]
            if tenant_id != PLATFORM_TENANT_ID:
                owners.append(PLATFORM_TENANT_ID)
            # Tenant-scope even though the write path validated - a stored id is
            # never resolved unscoped (defense in depth).
            connections = {
                c.id: c
                for c in self.db.query(Connection).filter(
                    Connection.id.in_(connection_ids), Connection.tenant_id.in_(owners)
                )
            }

        out: List[AgentOut] = []
        for agent in agents:
            connection = connections.get(agent.connection_id or "")
            out.append(
                AgentOut(
                    id=agent.id,
                    name=agent.name,
                    description=agent.description or "",
                    connectionId=agent.connection_id,
                    connectionName=connection.name if connection else None,
                    provider=connection.provider if connection else None,
                    model=agent.model or "",
                    temperature=agent.temperature or 0.0,
                    skills=[
                        EquippedSkillOut(id=s.id, name=s.name) for s in agent.skills
                    ],
                    isEnabled=bool(agent.is_enabled),
                    warning=_agent_warning(agent, connection),
                    createdAt=agent.created_at,
                    updatedAt=agent.updated_at,
                )
            )
        return out


def _agent_warning(agent: AiAgent, connection: Optional[Connection]) -> Optional[str]:
    """The missing-prerequisite warning (AC-BI-06). Surfaced on the list AND the
    form so a broken agent is visible BEFORE someone runs it - never a silent
    runtime failure."""
    if connection is None:
        return "No AI connection - pick one before this agent can run."
    if not connection.is_active:
        return f'Its connection "{connection.name}" is inactive.'
    if connection.status == CONNECTION_STATUS_ERROR:
        return f'Its connection "{connection.name}" last failed its test.'
    if not agent.model:
        return "No model selected."
    return None


def _validated_temperature(value: Optional[float]) -> float:
    temperature = float(value or 0.0)
    if temperature < 0 or temperature > 2:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Temperature must be between 0 and 2."
        )
    return temperature


def _csv_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


class SkillService:
    """Versioned prompt artifacts. A version row is NEVER mutated (AC-BI-07)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = SkillRepository(db)

    def list(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[List[SkillOut], int]:
        rows, total = self.repo.list(
            tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_clause=_translate(filter_group, _SKILL_FILTER_COLUMNS),
        )
        return [self._to_out(s) for s in rows], total

    def get(self, tenant_id: str, skill_id: str) -> SkillOut:
        return self._to_out(self._get_or_404(tenant_id, skill_id))

    def at(
        self,
        tenant_id: str,
        index: int,
        *,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[Optional[SkillOut], int]:
        rows, total = self.repo.list(
            tenant_id,
            page=index,
            page_size=1,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_clause=_translate(filter_group, _SKILL_FILTER_COLUMNS),
        )
        return (self._to_out(rows[0]) if rows else None), total

    def export(
        self,
        tenant_id: str,
        columns: List[str],
        *,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> str:
        rows, _ = self.repo.list(
            tenant_id,
            page=0,
            page_size=10_000,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_clause=_translate(filter_group, _SKILL_FILTER_COLUMNS),
        )
        labels = {
            "id": "ID",
            "key": "Key",
            "name": "Name",
            "description": "Description",
            "activeVersionNumber": "Active version",
            "versionCount": "Versions",
            "createdAt": "Created",
        }
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([labels.get(c, c) for c in columns])
        for skill in rows:
            out = self._to_out(skill)
            writer.writerow([_csv_cell(getattr(out, c, "")) for c in columns])
        return buffer.getvalue()

    def versions(self, tenant_id: str, skill_id: str) -> List[SkillVersionOut]:
        skill = self._get_or_404(tenant_id, skill_id)
        rows = self.repo.list_versions(skill.id)
        names = self._author_names([v.created_by for v in rows])
        return [
            SkillVersionOut(
                id=v.id,
                version=v.version,
                body=v.body or "",
                isActive=v.id == skill.active_version_id,
                createdByName=names.get(v.created_by or ""),
                createdAt=v.created_at,
            )
            for v in rows
        ]

    def create(self, tenant_id: str, req: SkillCreateRequest, actor: User) -> SkillOut:
        key = (req.key or "").strip()
        name = (req.name or "").strip()
        if not key or not name:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Key and name are required."
            )
        existing = (
            self.db.query(AiSkill)
            .filter(AiSkill.tenant_id == tenant_id, AiSkill.key == key)
            .first()
        )
        if existing is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f'A skill with key "{key}" already exists.'
            )
        skill = AiSkill(
            tenant_id=tenant_id,
            key=key,
            name=name,
            description=(req.description or "").strip(),
        )
        self.repo.add(skill)
        # Every skill starts at v1 - an agent must never point at a bodyless skill.
        self._mint_version(skill, req.body or "", actor)
        self.db.commit()
        self.db.refresh(skill)
        return self._to_out(skill)

    def update(
        self, tenant_id: str, skill_id: str, req: SkillUpdateRequest, actor: User
    ) -> SkillOut:
        skill = self._get_or_404(tenant_id, skill_id)
        skill = self._own_tier(tenant_id, skill, actor)
        if req.name is not None:
            name = req.name.strip()
            if not name:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name is required.")
            skill.name = name
        if req.description is not None:
            skill.description = req.description.strip()
        if req.body is not None:
            current = self._active_body(skill)
            # Only a REAL change mints a version - otherwise saving the form
            # twice would inflate history with identical rows.
            if req.body != current:
                self._mint_version(skill, req.body, actor)
        self.db.commit()
        self.db.refresh(skill)
        return self._to_out(skill)

    def rollback(self, tenant_id: str, skill_id: str, version_id: str, actor: User) -> SkillOut:
        """Rollback = a LABEL MOVE. No content copy, no delete (AC-BI-07)."""
        skill = self._get_or_404(tenant_id, skill_id)
        skill = self._own_tier(tenant_id, skill, actor)
        version = self.repo.get_version(skill.id, version_id)
        if version is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found.")
        skill.active_version_id = version.id
        self.db.commit()
        self.db.refresh(skill)
        return self._to_out(skill)

    def delete(self, tenant_id: str, skill_id: str) -> None:
        skill = self._get_or_404(tenant_id, skill_id)
        if skill.tenant_id is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Platform-provided skills cannot be deleted.",
            )
        if skill.is_system:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "System skills cannot be deleted."
            )
        # Count agents equipping this skill via the join (AC-BI-06b). The FK
        # CASCADEs, so a delete would silently un-equip - warn first instead.
        in_use = (
            self.db.query(ai_agent_skills)
            .filter(
                ai_agent_skills.c.tenant_id == tenant_id,
                ai_agent_skills.c.skill_id == skill.id,
            )
            .count()
        )
        if in_use:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{in_use} agent(s) still equip this skill - remove it from them first.",
            )
        self.repo.delete(skill)
        self.db.commit()

    # ── helpers ───────────────────────────────────────────────────────────
    def _get_or_404(self, tenant_id: str, skill_id: str) -> AiSkill:
        skill = self.repo.get(tenant_id, skill_id)
        if skill is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Skill not found.")
        return skill

    def _own_tier(self, tenant_id: str, skill: AiSkill, actor: User) -> AiSkill:
        """Editing a PLATFORM-tier skill FORKS a tenant copy (the template-engine
        two-tier pattern) - a tenant's edit must never mutate the shared default.
        The platform tenant itself edits the NULL-tier row in place, since it is
        the operator maintaining those defaults."""
        if skill.tenant_id is not None or tenant_id == PLATFORM_TENANT_ID:
            return skill
        fork = AiSkill(
            tenant_id=tenant_id,
            key=skill.key,
            name=skill.name,
            description=skill.description,
            is_system=False,
        )
        self.repo.add(fork)
        # Carry the active body over as the fork's v1 so history starts honest.
        self._mint_version(fork, self._active_body(skill), actor)
        return fork

    def _active_body(self, skill: AiSkill) -> str:
        if not skill.active_version_id:
            return ""
        version = (
            self.db.query(AiSkillVersion)
            .filter(AiSkillVersion.id == skill.active_version_id)
            .first()
        )
        return (version.body or "") if version else ""

    def _mint_version(self, skill: AiSkill, body: str, actor: User) -> AiSkillVersion:
        """Insert the next IMMUTABLE version and move the `active` label."""
        version = AiSkillVersion(
            skill_id=skill.id,
            tenant_id=skill.tenant_id,
            version=self.repo.next_version_number(skill.id),
            body=body,
            created_by=actor.id,
        )
        self.repo.add_version(version)
        skill.active_version_id = version.id
        self.db.flush()
        return version

    def _author_names(self, user_ids: List[Optional[str]]) -> Dict[str, str]:
        ids = {uid for uid in user_ids if uid}
        if not ids:
            return {}
        return {
            u.id: u.name
            for u in self.db.query(User).filter(User.id.in_(ids))
        }

    def _to_out(self, skill: AiSkill) -> SkillOut:
        versions = self.repo.list_versions(skill.id)
        active = next((v for v in versions if v.id == skill.active_version_id), None)
        return SkillOut(
            id=skill.id,
            key=skill.key,
            name=skill.name,
            description=skill.description or "",
            body=(active.body if active else ""),
            activeVersionId=skill.active_version_id,
            activeVersionNumber=(active.version if active else None),
            versionCount=len(versions),
            isSystem=bool(skill.is_system),
            isPlatform=skill.tenant_id is None,
            createdAt=skill.created_at,
            updatedAt=skill.updated_at,
        )


class TraceService:
    """Read-only observability (+ the flag toggle). Gated `ai_traces.read` -
    separate from `ai_agents.manage` because a trace holds RAW prompts and
    completions: debugging access is not the same as re-keying providers
    (AC-BI-14)."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = TraceRepository(db)

    def list(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "desc",
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[List[TraceOut], int]:
        rows, total = self.repo.list(
            tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_clause=_translate(filter_group, _TRACE_FILTER_COLUMNS),
        )
        return [TraceOut.model_validate(t) for t in rows], total

    def get(self, tenant_id: str, trace_id: str) -> TraceDetailOut:
        trace = self.repo.get(tenant_id, trace_id)
        if trace is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Trace not found.")
        spans = self.repo.list_spans(tenant_id, trace.id)
        detail = TraceDetailOut.model_validate(trace)
        detail.spans = [SpanOut.model_validate(s) for s in spans]
        return detail

    def set_flagged(self, tenant_id: str, trace_id: str, flagged: bool) -> TraceOut:
        trace = self.repo.get(tenant_id, trace_id)
        if trace is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Trace not found.")
        trace.flagged = flagged
        self.db.commit()
        self.db.refresh(trace)
        return TraceOut.model_validate(trace)
