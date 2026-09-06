"""Team repository - pure SQLAlchemy queries, all tenant-scoped (plan 28 S1).

Every method takes `tenant_id` and filters on it - there is no unscoped
getter to misuse (the polymorphic stored-id rule: a stored team/user id is
never resolved without a tenant filter). Mirrors `UserRepository`.
"""
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.team import Team, TeamMember
from app.models.tenant import DEFAULT_TENANT_ID

# Sortable list columns (frontend column id -> Team column).
_SORT_COLUMNS = {
    "name": Team.name,
    "sortOrder": Team.sort_order,
    "createdAt": Team.created_at,
}


class TeamRepository:
    def __init__(self, db: Session):
        self.db = db

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
        filter_clause=None,
    ) -> Tuple[List[Team], int]:
        q = self.db.query(Team).filter(Team.tenant_id == tenant_id)

        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(or_(Team.name.ilike(term), Team.description.ilike(term)))

        if filter_clause is not None:
            q = q.filter(filter_clause)

        total = q.count()

        column = _SORT_COLUMNS.get(sort_by or "", Team.sort_order)
        q = q.order_by(column.desc() if sort_dir == "desc" else column.asc())
        # Stable tiebreak so pagination + record-nav are deterministic.
        q = q.order_by(Team.id.asc())

        rows = q.offset(page * page_size).limit(page_size).all()
        return rows, total

    def get(self, team_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> Optional[Team]:
        return (
            self.db.query(Team)
            .filter(Team.id == team_id, Team.tenant_id == tenant_id)
            .first()
        )

    def by_ids(self, ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> List[Team]:
        if not ids:
            return []
        return (
            self.db.query(Team)
            .filter(Team.tenant_id == tenant_id, Team.id.in_(ids))
            .all()
        )

    def name_taken(
        self, name: str, tenant_id: str = DEFAULT_TENANT_ID, exclude_id: Optional[str] = None
    ) -> bool:
        """Case-insensitive dupe check - mirrors the Postgres functional
        unique index (`lower(name)`) so the sqlite test path matches
        production exactly."""
        q = self.db.query(Team.id).filter(
            Team.tenant_id == tenant_id, func.lower(Team.name) == name.strip().lower()
        )
        if exclude_id:
            q = q.filter(Team.id != exclude_id)
        return q.first() is not None

    def members_for(
        self, team_ids: List[str], tenant_id: str = DEFAULT_TENANT_ID
    ) -> Dict[str, List[TeamMember]]:
        """Batched membership lookup for several teams at once (one query per
        list render - AC-TEM-29's "one batched call" contract)."""
        if not team_ids:
            return {}
        rows = (
            self.db.query(TeamMember)
            .join(Team, TeamMember.team_id == Team.id)
            .filter(Team.tenant_id == tenant_id, TeamMember.team_id.in_(team_ids))
            .all()
        )
        out: Dict[str, List[TeamMember]] = defaultdict(list)
        for row in rows:
            out[row.team_id].append(row)
        return out

    def teams_for_user(
        self, user_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> List[Team]:
        return (
            self.db.query(Team)
            .join(TeamMember, TeamMember.team_id == Team.id)
            .filter(Team.tenant_id == tenant_id, TeamMember.user_id == user_id)
            .order_by(Team.sort_order.asc(), Team.id.asc())
            .distinct()
            .all()
        )

    def member_user_ids(
        self, team_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> List[str]:
        rows = (
            self.db.query(TeamMember.user_id)
            .join(Team, TeamMember.team_id == Team.id)
            .filter(Team.tenant_id == tenant_id, TeamMember.team_id == team_id)
            .all()
        )
        return [r[0] for r in rows]

    # ---- writes ----

    def add(self, team: Team) -> Team:
        self.db.add(team)
        self.db.commit()
        self.db.refresh(team)
        return team

    def save(self, team: Team) -> Team:
        self.db.add(team)
        self.db.commit()
        self.db.refresh(team)
        return team

    def delete(self, team: Team) -> None:
        self.db.delete(team)
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
