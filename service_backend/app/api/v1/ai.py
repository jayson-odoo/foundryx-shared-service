"""AI endpoints (Phase B-i slice 1) — HTTP validation + responses only.

No DB access and no SQL here: every read/write goes through `AgentService` /
`SkillService` / `TraceService`.

Gating (AC-BI-14): agents AND skills ride `ai_agents.read` / `ai_agents.manage`;
traces ride a SEPARATE `ai_traces.read`, because a trace holds raw prompts and
completions — granting debugging access must not also grant the ability to
re-key providers or rewrite prompts. LLM *connections* need no new permission:
they ride the existing `integrations.read` / `integrations.manage`.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from app.schemas.ai import (
    AgentCreateRequest,
    AgentListResponse,
    AgentNeighborResponse,
    AgentOut,
    AgentUpdateRequest,
    AiPrerequisiteOut,
    ModelListResponse,
    SkillCreateRequest,
    SkillListResponse,
    SkillNeighborResponse,
    SkillOptionOut,
    SkillOut,
    SkillRollbackRequest,
    SkillUpdateRequest,
    SkillVersionOut,
    TraceDetailOut,
    TraceFlagRequest,
    TraceListResponse,
    TraceOut,
)
from app.schemas.user import FilterGroup
from app.services.ai_service import AgentService, SkillService, TraceService
from app.services.filter_translator import FilterError

agents_router = APIRouter()
skills_router = APIRouter()
traces_router = APIRouter()


def _parse_filter(raw: Optional[str]) -> Optional[FilterGroup]:
    if not raw:
        return None
    try:
        return FilterGroup.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid filter.") from exc


def _filter_error(exc: FilterError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


# ── agents ───────────────────────────────────────────────────────────────
@agents_router.get("", response_model=AgentListResponse)
def list_agents(
    user: User = Depends(require_permission("ai_agents.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> AgentListResponse:
    try:
        rows, total = AgentService(db).list(
            user.tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise _filter_error(exc) from exc
    return AgentListResponse(data=rows, total=total, page=page)


# Literal routes BEFORE /{agent_id} — route order matters.
@agents_router.get("/at", response_model=AgentNeighborResponse)
def agent_at(
    user: User = Depends(require_permission("ai_agents.read")),
    db: Session = Depends(get_db),
    index: int = Query(0, ge=0),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> AgentNeighborResponse:
    try:
        agent, total = AgentService(db).at(
            user.tenant_id,
            index,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise _filter_error(exc) from exc
    return AgentNeighborResponse(agent=agent, total=total)


@agents_router.get("/export", response_class=PlainTextResponse)
def export_agents(
    user: User = Depends(require_permission("ai_agents.read")),
    db: Session = Depends(get_db),
    columns: str = Query("name,connectionName,model,isEnabled"),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> str:
    try:
        return AgentService(db).export(
            user.tenant_id,
            [c for c in columns.split(",") if c],
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise _filter_error(exc) from exc


@agents_router.get("/prerequisite", response_model=AiPrerequisiteOut)
def ai_prerequisite(
    user: User = Depends(require_permission("ai_agents.read")),
    db: Session = Depends(get_db),
) -> AiPrerequisiteOut:
    """AC-BI-11 — is any LLM connection configured, and which may an agent use?"""
    return AgentService(db).prerequisite(user.tenant_id)


@agents_router.get("/skill-options", response_model=List[SkillOptionOut])
def agent_skill_options(
    user: User = Depends(require_permission("ai_agents.read")),
    db: Session = Depends(get_db),
) -> List[SkillOptionOut]:
    return AgentService(db).skill_options(user.tenant_id)


@agents_router.get("/models", response_model=ModelListResponse)
def list_models(
    user: User = Depends(require_permission("ai_agents.read")),
    db: Session = Depends(get_db),
    connection_id: str = Query(...),
) -> ModelListResponse:
    """The model picker's source (AC-BI-05). Never raises on a provider outage —
    it returns the curated static list with `isLive=false` so the form renders."""
    return AgentService(db).models(user.tenant_id, connection_id)


@agents_router.get("/{agent_id}", response_model=AgentOut)
def get_agent(
    agent_id: str,
    user: User = Depends(require_permission("ai_agents.read")),
    db: Session = Depends(get_db),
) -> AgentOut:
    return AgentService(db).get(user.tenant_id, agent_id)


@agents_router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
def create_agent(
    req: AgentCreateRequest,
    user: User = Depends(require_permission("ai_agents.manage")),
    db: Session = Depends(get_db),
) -> AgentOut:
    return AgentService(db).create(user.tenant_id, req, user)


@agents_router.patch("/{agent_id}", response_model=AgentOut)
def update_agent(
    agent_id: str,
    req: AgentUpdateRequest,
    user: User = Depends(require_permission("ai_agents.manage")),
    db: Session = Depends(get_db),
) -> AgentOut:
    return AgentService(db).update(user.tenant_id, agent_id, req, user)


@agents_router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(
    agent_id: str,
    user: User = Depends(require_permission("ai_agents.manage")),
    db: Session = Depends(get_db),
) -> None:
    AgentService(db).delete(user.tenant_id, agent_id)


# ── skills (same permission family as agents, AC-BI-07/14) ───────────────
@skills_router.get("", response_model=SkillListResponse)
def list_skills(
    user: User = Depends(require_permission("ai_agents.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> SkillListResponse:
    try:
        rows, total = SkillService(db).list(
            user.tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise _filter_error(exc) from exc
    return SkillListResponse(data=rows, total=total, page=page)


@skills_router.get("/at", response_model=SkillNeighborResponse)
def skill_at(
    user: User = Depends(require_permission("ai_agents.read")),
    db: Session = Depends(get_db),
    index: int = Query(0, ge=0),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> SkillNeighborResponse:
    try:
        skill, total = SkillService(db).at(
            user.tenant_id,
            index,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise _filter_error(exc) from exc
    return SkillNeighborResponse(skill=skill, total=total)


@skills_router.get("/export", response_class=PlainTextResponse)
def export_skills(
    user: User = Depends(require_permission("ai_agents.read")),
    db: Session = Depends(get_db),
    columns: str = Query("key,name,activeVersionNumber,versionCount"),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> str:
    try:
        return SkillService(db).export(
            user.tenant_id,
            [c for c in columns.split(",") if c],
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise _filter_error(exc) from exc


@skills_router.get("/{skill_id}", response_model=SkillOut)
def get_skill(
    skill_id: str,
    user: User = Depends(require_permission("ai_agents.read")),
    db: Session = Depends(get_db),
) -> SkillOut:
    return SkillService(db).get(user.tenant_id, skill_id)


@skills_router.get("/{skill_id}/versions", response_model=List[SkillVersionOut])
def list_skill_versions(
    skill_id: str,
    user: User = Depends(require_permission("ai_agents.read")),
    db: Session = Depends(get_db),
) -> List[SkillVersionOut]:
    return SkillService(db).versions(user.tenant_id, skill_id)


@skills_router.post("", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
def create_skill(
    req: SkillCreateRequest,
    user: User = Depends(require_permission("ai_agents.manage")),
    db: Session = Depends(get_db),
) -> SkillOut:
    return SkillService(db).create(user.tenant_id, req, user)


@skills_router.patch("/{skill_id}", response_model=SkillOut)
def update_skill(
    skill_id: str,
    req: SkillUpdateRequest,
    user: User = Depends(require_permission("ai_agents.manage")),
    db: Session = Depends(get_db),
) -> SkillOut:
    """A changed body mints a NEW immutable version and moves the active label
    — prior versions are never mutated (AC-BI-07)."""
    return SkillService(db).update(user.tenant_id, skill_id, req, user)


@skills_router.post("/{skill_id}/rollback", response_model=SkillOut)
def rollback_skill(
    skill_id: str,
    req: SkillRollbackRequest,
    user: User = Depends(require_permission("ai_agents.manage")),
    db: Session = Depends(get_db),
) -> SkillOut:
    """Rollback = a LABEL MOVE. No content copy, no delete (AC-BI-07)."""
    return SkillService(db).rollback(user.tenant_id, skill_id, req.versionId, user)


@skills_router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_skill(
    skill_id: str,
    user: User = Depends(require_permission("ai_agents.manage")),
    db: Session = Depends(get_db),
) -> None:
    SkillService(db).delete(user.tenant_id, skill_id)


# ── traces (SEPARATE permission — raw prompts/completions, AC-BI-14) ──────
@traces_router.get("", response_model=TraceListResponse)
def list_traces(
    user: User = Depends(require_permission("ai_traces.read")),
    db: Session = Depends(get_db),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    filter: Optional[str] = None,
) -> TraceListResponse:
    try:
        rows, total = TraceService(db).list(
            user.tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=_parse_filter(filter),
        )
    except FilterError as exc:
        raise _filter_error(exc) from exc
    return TraceListResponse(data=rows, total=total, page=page)


@traces_router.get("/{trace_id}", response_model=TraceDetailOut)
def get_trace(
    trace_id: str,
    user: User = Depends(require_permission("ai_traces.read")),
    db: Session = Depends(get_db),
) -> TraceDetailOut:
    """Trace + its ordered FLAT step list (Bi-D17 — a tree renderer waits for
    real depth > 1)."""
    return TraceService(db).get(user.tenant_id, trace_id)


@traces_router.post("/{trace_id}/flag", response_model=TraceOut)
def flag_trace(
    trace_id: str,
    req: TraceFlagRequest,
    user: User = Depends(require_permission("ai_traces.read")),
    db: Session = Depends(get_db),
) -> TraceOut:
    """Flagging keeps a trace past the short `ok` retention window (AC-BI-10)."""
    return TraceService(db).set_flagged(user.tenant_id, trace_id, req.flagged)
