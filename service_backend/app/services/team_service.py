"""Team management business logic (Service layer, plan 28 S1).

Owns name uniqueness (case-insensitive, per tenant), member-set replace with
per-user tenant validation, and the delete reference-guard check. Routers
translate these to HTTP; the repository does the SQL.
"""
from typing import Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.team import TEAM_MEMBER_ROLES, Team, TeamMember
from app.models.tenant import DEFAULT_TENANT_ID, PLATFORM_TENANT_ID
from app.models.user import User
from app.module_platform import reference_counts
from app.repositories.team_repository import TeamRepository
from app.repositories.user_repository import UserRepository

TEAM_NAME_MAX_LENGTH = 120


class TeamServiceError(Exception):
    """Base class for team-management domain errors."""


class TeamNotFound(TeamServiceError):
    pass


class TeamValidationError(TeamServiceError):
    """Carries a `{field: message}` map - the router renders it as
    `422 {fieldErrors: ...}` (AC-TEM-02/03/04)."""

    def __init__(self, field_errors: Dict[str, str]):
        self.field_errors = field_errors
        super().__init__(str(field_errors))


class TeamInUse(TeamServiceError):
    """Carries the reference-guard's per-source counts (AC-TEM-06)."""

    def __init__(self, counts: Dict[str, int]):
        self.counts = counts
        super().__init__("team_in_use")


def _clean_description(description: Optional[str]) -> Optional[str]:
    if description is None:
        return None
    cleaned = description.strip()
    return cleaned or None


def _is_name_conflict(exc: IntegrityError) -> bool:
    """Only the case-insensitive-name unique index (`ix_teams_tenant_name_lower`
    on Postgres; `_validate_name`'s pre-check is what actually enforces it on
    the sqlite test path, which carries no such index) means "name already
    exists". A `team_members` constraint hit (`uq_team_members_team_user`) is
    a DIFFERENT failure - genuine duplicates within the payload are already
    422'd by `_validate_members` before any DB call, so this is a real,
    unexpected write conflict and must never be mislabeled as a name clash."""
    message = str(getattr(exc, "orig", exc) or exc).lower()
    return "team_members" not in message


class TeamService:
    def __init__(self, db: Session):
        self.db = db
        self.teams = TeamRepository(db)
        self.users = UserRepository(db)

    # ---- reads ----

    def list(
        self,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
    ) -> Tuple[List[Team], int]:
        return self.teams.list(
            tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

    def get(self, team_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> Team:
        team = self.teams.get(team_id, tenant_id)
        if team is None:
            raise TeamNotFound()
        return team

    def get_at(
        self,
        index: int,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
    ) -> Tuple[Optional[Team], int]:
        rows, total = self.list(
            tenant_id,
            page=max(index, 0),
            page_size=1,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        return (rows[0] if rows else None), total

    def mine(self, user: User) -> List[Team]:
        """AC-TEM-08/16 - the caller's own teams, no `teams.read` required."""
        return self.teams.teams_for_user(user.id, user.tenant_id)

    # ---- validation ----

    def _validate_name(
        self, name: str, tenant_id: str, exclude_id: Optional[str] = None
    ) -> str:
        trimmed = (name or "").strip()
        if not trimmed:
            raise TeamValidationError({"name": "Name is required."})
        if len(trimmed) > TEAM_NAME_MAX_LENGTH:
            raise TeamValidationError({"name": "Name is too long."})
        if self.teams.name_taken(trimmed, tenant_id, exclude_id):
            raise TeamValidationError({"name": "A team with this name already exists."})
        return trimmed

    def _validate_members(self, members, tenant_id: str) -> List[dict]:
        """Every entry must resolve to a user of the SAME tenant, and that
        tenant must not be the platform tenant (AC-TEM-03: no platform-tenant
        user is ever a team member, even on a platform-tenant-owned team -
        teams are a per-Service operator/agent concept, not the operator
        console). Duplicate userId across the payload is also invalid (a lead
        is always ALSO a member row - one row, one role)."""
        if not members:
            return []
        if tenant_id == PLATFORM_TENANT_ID:
            raise TeamValidationError(
                {"members": "The platform tenant cannot hold team members."}
            )
        seen: set = set()
        resolved: List[dict] = []
        for entry in members:
            role = entry.role
            if role not in TEAM_MEMBER_ROLES:
                raise TeamValidationError(
                    {"members": 'Each member must be "member" or "lead".'}
                )
            if entry.userId in seen:
                raise TeamValidationError({"members": "Each member may only appear once."})
            seen.add(entry.userId)
            user = self.users.get_by_id(entry.userId, tenant_id, include_trashed=True)
            if user is None or user.tenant_id != tenant_id:
                raise TeamValidationError(
                    {"members": "One of the selected members is invalid."}
                )
            resolved.append({"user_id": user.id, "role": role})
        return resolved

    def _apply_members(self, team: Team, resolved: List[dict]) -> None:
        """Diff the member set in place - remove missing, add new, update role
        changes for retained rows - rather than blind delete-all + insert.

        A blind `team.members = [...]` replace marks every EXISTING row as an
        orphan (deleted) and appends brand-new `TeamMember` rows (fresh ids)
        for the WHOLE incoming set. SQLAlchemy's unit-of-work has no ordering
        dependency between those deletes and inserts (no FK relates them), so
        it can emit the INSERT for a retained `(team_id, user_id)` pair before
        the DELETE of its old row and trip `uq_team_members_team_user` - which
        the old blanket `except IntegrityError` then mis-reported as a NAME
        collision. Diffing means a retained pair is never deleted at all.
        """
        incoming = {m["user_id"]: m["role"] for m in resolved}
        existing = {m.user_id: m for m in team.members}

        for user_id, member in list(existing.items()):
            if user_id not in incoming:
                team.members.remove(member)

        for user_id, role in incoming.items():
            member = existing.get(user_id)
            if member is None:
                team.members.append(
                    TeamMember(tenant_id=team.tenant_id, user_id=user_id, role=role)
                )
            elif member.role != role:
                member.role = role

    # ---- writes ----

    def create(
        self,
        tenant_id: str,
        *,
        name: str,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
        sort_order: Optional[int] = None,
        members=None,
    ) -> Team:
        clean_name = self._validate_name(name, tenant_id)
        resolved_members = self._validate_members(members or [], tenant_id)
        team = Team(
            tenant_id=tenant_id,
            name=clean_name,
            description=_clean_description(description),
            is_active=is_active if is_active is not None else True,
            sort_order=sort_order or 0,
        )
        self._apply_members(team, resolved_members)
        try:
            self.teams.add(team)
        except IntegrityError as exc:
            self.teams.rollback()
            if not _is_name_conflict(exc):
                raise
            raise TeamValidationError(
                {"name": "A team with this name already exists."}
            )
        return team

    def update(
        self,
        team_id: str,
        tenant_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
        sort_order: Optional[int] = None,
        members=None,
    ) -> Team:
        team = self.get(team_id, tenant_id)
        if name is not None:
            team.name = self._validate_name(name, tenant_id, exclude_id=team_id)
        if description is not None:
            team.description = _clean_description(description)
        if is_active is not None:
            team.is_active = is_active
        if sort_order is not None:
            team.sort_order = sort_order
        if members is not None:
            resolved_members = self._validate_members(members, tenant_id)
            self._apply_members(team, resolved_members)
        try:
            return self.teams.save(team)
        except IntegrityError as exc:
            self.teams.rollback()
            if not _is_name_conflict(exc):
                raise
            raise TeamValidationError(
                {"name": "A team with this name already exists."}
            )

    def delete(self, team_id: str, tenant_id: str) -> None:
        team = self.get(team_id, tenant_id)
        counts = reference_counts(self.db, tenant_id, "team", team_id)
        if counts:
            raise TeamInUse(counts)
        self.teams.delete(team)
