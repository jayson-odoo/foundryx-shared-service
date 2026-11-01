"""Channel repository - tenant-scoped channel queries. Pure SQLAlchemy."""
from typing import List, Optional, Tuple

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.models.tenant import DEFAULT_TENANT_ID
from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule
from app.models.tenant import Tenant
from app.schemas.filters import FilterCondition, FilterGroup
from app.services.filter_translator import FilterError, translate_filter
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from ..models import Channel, Status

# Whitelist of filterable fields (the screen's filter bar sends these names).
_FILTER_COLUMNS = {
    "name": Channel.name,
    "displayPhoneNumber": Channel.display_phone_number,
    "channelType": Channel.channel_type,
    "type": Channel.channel_type,
    "created": Channel.created_at,
}
_SCALARS = (str, int, float, bool, type(None))


def _check_scalars(group: FilterGroup) -> None:
    """A condition value is a scalar or a list of scalars; anything else is the
    existing filter error, never a database error."""
    for rule in group.rules:
        if isinstance(rule, FilterGroup):
            _check_scalars(rule)
            continue
        value = rule.value
        values = value if isinstance(value, list) else [value]
        if not all(isinstance(v, _SCALARS) for v in values):
            raise FilterError(f"invalid value for {rule.field}")


_SORT = {
    "name": Channel.name,
    "created": Channel.created_at,
    "displayPhoneNumber": Channel.display_phone_number,
}


class ChannelRepository:
    def __init__(self, db: Session):
        self.db = db

    def paginate(
        self,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        trashed: bool = False,
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[List[Channel], int]:
        q = self.db.query(Channel).filter(
            Channel.tenant_id == tenant_id, Channel.is_trashed.is_(trashed)
        )
        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(or_(Channel.name.ilike(term), Channel.display_phone_number.ilike(term)))
        clause = self._filter_clause(filter_group, tenant_id)
        if clause is not None:
            q = q.filter(clause)
        total = q.count()
        col = _SORT.get(sort_by or "", Channel.created_at)
        q = q.order_by(col.desc() if sort_dir == "desc" else col.asc(), Channel.id.asc())
        rows = q.offset(page * page_size).limit(page_size).all()
        return rows, total

    @staticmethod
    def _filter_clause(group: Optional[FilterGroup], tenant_id: str):
        """List filter over the whitelisted columns; ``status`` compares the
        tenant's own CHANNEL status keys."""
        if group is None:
            return None
        _check_scalars(group)

        def status_clause(cond: FilterCondition):
            if cond.field != "status":
                return None
            values = cond.value if isinstance(cond.value, list) else [cond.value]
            ids = select(Status.id).where(
                Status.tenant_id == tenant_id, Status.scope == "CHANNEL", Status.key.in_(values)
            )
            if cond.operator in ("eq", "in"):
                return Channel.status_id.in_(ids)
            if cond.operator in ("neq", "nin"):
                return or_(Channel.status_id.is_(None), Channel.status_id.notin_(ids))
            raise FilterError(f"unknown operator: {cond.operator}")

        return translate_filter(group, _FILTER_COLUMNS, status_clause)

    def all_scoped(self, tenant_id: str, *, trashed: bool = False) -> List[Channel]:
        return (
            self.db.query(Channel)
            .filter(Channel.tenant_id == tenant_id, Channel.is_trashed.is_(trashed))
            .order_by(Channel.created_at.desc(), Channel.id.asc())
            .all()
        )

    def active_scoped(self, tenant_id: str) -> List[Channel]:
        """Live channel candidates. Credential suitability stays in service
        logic because repositories never decrypt secrets."""
        return (
            self.db.query(Channel)
            .filter(
                Channel.tenant_id == tenant_id,
                Channel.is_active.is_(True),
                Channel.is_trashed.is_(False),
            )
            .order_by(Channel.name.asc(), Channel.id.asc())
            .all()
        )

    def get_active_by_id(self, channel_id: str, tenant_id: str) -> Optional[Channel]:
        return (
            self.db.query(Channel)
            .filter(
                Channel.id == channel_id,
                Channel.tenant_id == tenant_id,
                Channel.is_active.is_(True),
                Channel.is_trashed.is_(False),
            )
            .first()
        )

    def list_by_workspace(
        self, workspace_id: str, tenant_id: str, *, oldest_first: bool = False
    ) -> List[Channel]:
        order = Channel.created_at.asc() if oldest_first else Channel.created_at.desc()
        return (
            self.db.query(Channel)
            .filter(
                Channel.tenant_id == tenant_id,
                Channel.workspace_id == workspace_id,
                Channel.is_trashed.is_(False),
            )
            .order_by(order, Channel.id.asc())
            .all()
        )

    def get_by_id(self, channel_id: str, tenant_id: str = DEFAULT_TENANT_ID) -> Optional[Channel]:
        return (
            self.db.query(Channel)
            .filter(Channel.tenant_id == tenant_id, Channel.id == channel_id)
            .first()
        )

    def get_many(self, ids: List[str], tenant_id: str = DEFAULT_TENANT_ID) -> List[Channel]:
        if not ids:
            return []
        return (
            self.db.query(Channel)
            .filter(Channel.tenant_id == tenant_id, Channel.id.in_(ids))
            .all()
        )

    # ---- token health (plan 42) ----
    def token_check_candidates(self) -> List[Channel]:
        """Live WhatsApp channels of tenants that have the module active and may
        sign in (not suspended or archived), paused ones included. Tenant-agnostic
        on purpose: a scan, with each channel carrying its own tenant."""
        active_tenants = (
            self.db.query(TenantModule.tenant_id)
            .join(Module, Module.id == TenantModule.module_id)
            .filter(Module.name == "omnichannel", TenantModule.status == MODULE_STATUS_ACTIVE)
        )
        rows = (
            self.db.query(Channel)
            .filter(
                Channel.channel_type == "WHATSAPP",
                Channel.is_trashed.is_(False),
                Channel.phone_number_id.isnot(None),
                Channel.tenant_id.in_(active_tenants),
            )
            .order_by(Channel.created_at.asc(), Channel.id.asc())
            .all()
        )
        allowed: dict = {}
        out = []
        for ch in rows:
            if ch.tenant_id not in allowed:
                tenant = self.db.get(Tenant, ch.tenant_id)
                allowed[ch.tenant_id] = tenant is not None and tenant.signin_allowed
            if allowed[ch.tenant_id]:
                out.append(ch)
        return out

    def get_unscoped(self, channel_id: str) -> Optional[Channel]:
        """Worker entry only: a task carries a channel id and no user. Every
        later query reads the tenant off this row."""
        return self.db.query(Channel).filter(Channel.id == channel_id).first()

    def set_status_if_credentials_unchanged(
        self,
        channel: Channel,
        credentials_json: Optional[str],
        status_id: str,
        *,
        from_status_id: Optional[str] = None,
        not_status_id: Optional[str] = None,
    ) -> bool:
        """Guarded status write: lands only while the stored credentials are still
        the value the check read, so a replace made during a check wins. Never
        touches ``is_active``. True when a row was updated."""
        conds = [
            Channel.id == channel.id,
            Channel.tenant_id == channel.tenant_id,
            Channel.credentials_json == credentials_json,
        ]
        if from_status_id is not None:
            conds.append(Channel.status_id == from_status_id)
        if not_status_id is not None:
            conds.append(or_(Channel.status_id.is_(None), Channel.status_id != not_status_id))
        result = self.db.execute(
            update(Channel).where(*conds).values(status_id=status_id), execution_options={"synchronize_session": False}
        )
        return result.rowcount == 1

    def users_with_permission(self, tenant_id: str, permission_key: str) -> List[User]:
        """Users of THIS tenant holding ``permission_key`` through a role of this
        same tenant."""
        return (
            self.db.query(User)
            .join(User.roles)
            .filter(
                User.tenant_id == tenant_id,
                User.is_trashed.is_(False),
                Role.tenant_id == tenant_id,
                Role.permissions.any(Permission.key == permission_key),
            )
            .distinct()
            .all()
        )
