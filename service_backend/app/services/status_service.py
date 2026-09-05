"""Status-engine configuration service (sprint-2/01).

Owns the rules: two-tier fork-on-edit (D7), strict graph validation (D4/D8),
system-row locks, reorder, deactivate + migrate-records, transition role +
notification-spec management. Routers translate outcomes to HTTP; the
repositories do the SQL; the EXECUTION of transitions lives in
``status_machine`` - this service only configures the machine.

Tier rules: a platform-tenant caller edits the platform defaults
(``tenant_id NULL``); a tenant caller edits their own fork - created on first
write by copying the platform set for that entity (statuses + transitions) and
remapping the tenant's existing records onto the forked rows. Platform-owned
entities (e.g. ``tenant``) reject tenant callers outright.
"""
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.notification_spec import (
    DYNAMIC_KEYS,
    NOTIFICATION_CHANNELS,
    NotificationRecipient,
    NotificationSpec,
    RECIPIENT_TARGET_TYPES,
    TARGET_DYNAMIC,
    TARGET_ROLE,
    TARGET_USER,
)
from app.models.role import Role
from app.models.status import Status
from app.models.tenant import PLATFORM_TENANT_ID
from app.models.status_transition import StatusTransition
from app.models.user import User
from app.repositories.status_repository import StatusRepository
from app.repositories.status_transition_repository import StatusTransitionRepository
from app.rule_engine.schemas import validate_tree
from app.status_engine.registry import (
    StatusEntity,
    get_status_entity,
    list_status_entities,
)

# "Field not provided" sentinel for PATCH semantics (None = clear).
UNSET: Any = object()

# Trait flags a caller may set (mirrors the Status columns).
_FLAG_FIELDS = (
    "is_initial",
    "is_terminal",
    "is_active",
    "blocks_access",
    "is_archived",
    "is_default",
)

_KEY_RE = re.compile(r"[^a-z0-9]+")


class StatusEngineError(Exception):
    def __init__(self, message: str = ""):
        super().__init__(message)
        self.message = message


class EntityNotFound(StatusEngineError):
    pass


class EntityNotEditable(StatusEngineError):
    """Tenant caller on a platform-owned entity (e.g. tenant lifecycle)."""


class StatusNotFound(StatusEngineError):
    pass


class TransitionNotFound(StatusEngineError):
    pass


class SystemStatusProtected(StatusEngineError):
    """System rows: key/flags immutable, row non-deletable."""


class StatusValidationError(StatusEngineError):
    pass


class StatusReferenced(StatusEngineError):
    """Hard delete blocked - records still hold this status (D8)."""

    def __init__(self, count: int):
        super().__init__(f"{count} record(s) still use this status.")
        self.count = count


class StatusService:
    def __init__(self, db: Session):
        self.db = db
        self.statuses = StatusRepository(db)
        self.transitions = StatusTransitionRepository(db)

    # ---- entity + tier resolution ----

    def list_entities(self, user: User) -> List[StatusEntity]:
        """Registry entries visible to the caller - tenant callers don't see
        platform-owned entities (they can't configure or read them usefully).
        SCOPED entities (sprint-3/01 D4) never list here: their graphs live
        on the owning record's own surface (a form's Flow tab), and the
        global graph endpoint requires a scope (foolproof-UI)."""
        entities = [e for e in list_status_entities() if not e.scoped]
        if user.tenant is not None and user.tenant.is_platform:
            return entities
        return [e for e in entities if not e.platform_owned]

    def entity_stats(self, entity: StatusEntity, user: User) -> Dict[str, Any]:
        """Caller-tier counts for the entity LIST surface (statuses,
        transitions, whether the caller's tenant forked the set)."""
        tier = self._read_scope(entity, user)
        return {
            "status_count": len(
                self.statuses.list_for_entity(entity.entity_type, tier)
            ),
            "transition_count": len(
                self.transitions.list_for_entity(entity.entity_type, tier)
            ),
            "customized": tier is not None,
        }

    def _entity(self, entity_type: str) -> StatusEntity:
        entity = get_status_entity(entity_type)
        if entity is None:
            raise EntityNotFound(f"Unknown status entity '{entity_type}'.")
        return entity

    def _is_platform_caller(self, user: User) -> bool:
        return user.tenant is not None and user.tenant.is_platform

    def _read_scope(self, entity: StatusEntity, user: User) -> Optional[str]:
        if self._is_platform_caller(user) or entity.platform_owned:
            return None
        return self.statuses.resolve_tier(entity.entity_type, user.tenant_id)

    def _write_scope(self, entity: StatusEntity, user: User) -> Optional[str]:
        """The tier a write lands in - forks the platform set first when a
        tenant touches an entity it hasn't forked yet (D7)."""
        if self._is_platform_caller(user):
            return None
        if entity.platform_owned:
            raise EntityNotEditable(
                f"'{entity.label}' statuses are managed by the platform."
            )
        if not self.statuses.tenant_has_fork(entity.entity_type, user.tenant_id):
            self._fork(entity, user.tenant_id)
        return user.tenant_id

    # ---- scoped machines (sprint-3/01 D4) ----

    def _scope_for_write(
        self, entity: StatusEntity, user: User, scope_id: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        """(tier, scope_id) a write lands in. Scoped entities are tenant-owned
        from birth - no fork, the caller's tenant IS the tier, and the scope
        owner must exist in that tenant (polymorphic guard class). Unscoped
        entities keep the legacy two-tier path."""
        if entity.scoped:
            if not scope_id:
                raise StatusValidationError(
                    f"{entity.scope_label or 'Scope'} is required for this entity."
                )
            if entity.scope_exists is not None and not entity.scope_exists(
                self.db, user.tenant_id, scope_id
            ):
                raise EntityNotFound(f"{entity.scope_label or 'Scope'} not found.")
            return user.tenant_id, scope_id
        return self._write_scope(entity, user), None

    def _row_write_context(
        self, row: Status, entity: StatusEntity, user: User
    ) -> Tuple[Optional[str], Optional[str]]:
        """Write context derived from an EXISTING row (update/delete paths) -
        a scoped row must belong to the caller's tenant + carry its scope."""
        if entity.scoped:
            if row.tenant_id != user.tenant_id or row.scope_id is None:
                raise StatusNotFound("Status not found.")
            return user.tenant_id, row.scope_id
        return self._write_scope(entity, user), None

    # ---- fork (D7) ----

    def _fork(self, entity: StatusEntity, tenant_id: str) -> Dict[str, str]:
        """Copy the platform default set for ``entity`` to ``tenant_id`` and
        remap the tenant's existing records onto the forked rows. Returns the
        old→new status id map (callers translate incoming ids through it)."""
        platform_statuses = (
            self.db.query(Status)
            .filter(Status.entity_type == entity.entity_type, Status.tenant_id.is_(None))
            .all()
        )
        id_map: Dict[str, str] = {}
        for source in platform_statuses:
            clone = Status(
                id=str(uuid.uuid4()),
                entity_type=source.entity_type,
                key=source.key,
                category=source.category,
                label=source.label,
                color=source.color,
                sort_order=source.sort_order,
                is_initial=source.is_initial,
                is_terminal=source.is_terminal,
                is_active=source.is_active,
                blocks_access=source.blocks_access,
                is_archived=source.is_archived,
                is_default=source.is_default,
                position_x=source.position_x,
                position_y=source.position_y,
                is_system=source.is_system,
                tenant_id=tenant_id,
            )
            self.db.add(clone)
            id_map[source.id] = clone.id
        self.db.flush()

        # Copy the edge graph (roles/notification specs start empty - platform
        # defaults carry none today; revisit if platform-seeded specs arrive).
        edge_map: Dict[str, str] = {}
        for edge in (
            self.db.query(StatusTransition)
            .filter(
                StatusTransition.entity_type == entity.entity_type,
                StatusTransition.tenant_id.is_(None),
            )
            .all()
        ):
            clone = StatusTransition(
                id=str(uuid.uuid4()),
                entity_type=edge.entity_type,
                tenant_id=tenant_id,
                from_status_id=id_map[edge.from_status_id],
                to_status_id=id_map[edge.to_status_id],
                label=edge.label,
                sort_order=edge.sort_order,
                # Conditions copy verbatim - fact keys are tier-independent.
                conditions_json=edge.conditions_json,
                # Derived status (sprint-4/03) - an auto-edge stays auto in the fork.
                trigger_mode=edge.trigger_mode,
            )
            self.db.add(clone)
            edge_map[edge.id] = clone.id
        self.db.flush()

        # The tenant's existing records point at platform rows - remap.
        for old_id, new_id in id_map.items():
            entity.migrate_records(self.db, old_id, new_id, tenant_id)
        self._fork_id_map = id_map
        self._fork_edge_map = edge_map
        return id_map

    def _translate(self, status_id: Optional[str]) -> Optional[str]:
        """Map a platform-tier id the client sent to its forked counterpart
        when a fork just happened inside this request."""
        id_map = getattr(self, "_fork_id_map", None)
        if id_map and status_id in id_map:
            return id_map[status_id]
        return status_id

    # ---- graph read ----

    def get_graph(
        self, entity_type: str, user: User, scope_id: Optional[str] = None
    ) -> Tuple[StatusEntity, Optional[str], List[Status], List[StatusTransition], Dict[str, int]]:
        entity = self._entity(entity_type)
        if entity.scoped:
            # Scoped machines (sprint-3/01 D4): ONE owning record's graph,
            # tenant-owned from birth - no tier resolution.
            if not scope_id:
                raise StatusValidationError(
                    f"{entity.scope_label or 'Scope'} is required for this entity."
                )
            if entity.scope_exists is not None and not entity.scope_exists(
                self.db, user.tenant_id, scope_id
            ):
                raise EntityNotFound(f"{entity.scope_label or 'Scope'} not found.")
            statuses = self.statuses.list_for_entity(
                entity_type, user.tenant_id, scope_id=scope_id
            )
            transitions = self.transitions.list_for_statuses(
                [s.id for s in statuses], user.tenant_id
            )
            counts = {
                s.id: entity.count_records(self.db, s.id, user.tenant_id) for s in statuses
            }
            return entity, user.tenant_id, statuses, transitions, counts
        tier = self._read_scope(entity, user)
        statuses = self.statuses.list_for_entity(entity_type, tier)
        transitions = self.transitions.list_for_entity(entity_type, tier)
        # Platform callers see references across ALL (unforked) tenants; a
        # tenant caller only ever counts their own records.
        record_scope = (
            None
            if (self._is_platform_caller(user) or entity.platform_owned)
            else user.tenant_id
        )
        counts = {
            s.id: entity.count_records(self.db, s.id, record_scope) for s in statuses
        }
        return entity, tier, statuses, transitions, counts

    # ---- status CRUD ----

    def _get_status_in_scope(
        self,
        status_id: str,
        entity: StatusEntity,
        scope: Optional[str],
        scope_id: Optional[str] = None,
    ) -> Status:
        status = self.statuses.get_by_id(self._translate(status_id))
        if (
            status is None
            or status.entity_type != entity.entity_type
            or status.tenant_id != scope
            or status.scope_id != scope_id
        ):
            raise StatusNotFound("Status not found.")
        return status

    def _slug_key(self, label: str) -> str:
        key = _KEY_RE.sub("_", label.strip().lower()).strip("_")
        if not key:
            raise StatusValidationError("Label must contain letters or numbers.")
        return key

    def create_status(
        self,
        entity_type: str,
        user: User,
        *,
        label: str,
        color: str = "gray",
        key: Optional[str] = None,
        flags: Optional[Dict[str, bool]] = None,
        position_x: Optional[float] = None,
        position_y: Optional[float] = None,
        scope_id: Optional[str] = None,
    ) -> Status:
        entity = self._entity(entity_type)
        scope, scope_id = self._scope_for_write(entity, user, scope_id)
        key = (key or self._slug_key(label)).strip().lower()
        if self.statuses.get_by_key(entity_type, key, scope, scope_id=scope_id) is not None:
            raise StatusValidationError(f'A status with key "{key}" already exists.')

        siblings = self.statuses.list_for_entity(entity_type, scope, scope_id=scope_id)
        status = Status(
            entity_type=entity_type,
            key=key,
            category=key.upper(),  # cosmetic mirror - never branched on
            label=label.strip(),
            color=color,
            sort_order=(max((s.sort_order for s in siblings), default=0) + 1),
            is_system=False,
            tenant_id=scope,
            scope_id=scope_id,
            position_x=position_x,
            position_y=position_y,
        )
        self._apply_flags(status, flags or {}, scope, entity, creating=True, scope_id=scope_id)
        self.statuses.add(status)
        self.db.commit()
        return status

    def _apply_flags(
        self,
        status: Status,
        flags: Dict[str, bool],
        scope: Optional[str],
        entity: StatusEntity,
        *,
        creating: bool,
        scope_id: Optional[str] = None,
    ) -> None:
        unknown = set(flags) - set(_FLAG_FIELDS)
        if unknown:
            raise StatusValidationError(f"Unknown flags: {', '.join(sorted(unknown))}.")
        if flags.get("is_terminal") and not creating:
            if self.transitions.outgoing(status.id, scope):
                raise StatusValidationError(
                    "A terminal status cannot have outgoing transitions - remove them first."
                )
        # AC-20: `is_initial` converges to AT MOST one via the silent-converge
        # below, but a set must never converge to ZERO either - turning the
        # LAST initial stage off would leave new records with nowhere to
        # start. Only relevant on an existing status (creation can't yet be
        # the sole initial row being un-set).
        if (
            not creating
            and "is_initial" in flags
            and not flags["is_initial"]
            and status.is_initial
        ):
            self._assert_not_sole_initial(status, scope, scope_id, entity)
        for flag, value in flags.items():
            setattr(status, flag, bool(value))
        # Single default per entity set (per SCOPE for scoped machines) -
        # converge silently.
        if flags.get("is_default"):
            (
                self.db.query(Status)
                .filter(
                    Status.entity_type == entity.entity_type,
                    Status.tenant_id.is_(None) if scope is None else Status.tenant_id == scope,
                    Status.scope_id.is_(None) if scope_id is None else Status.scope_id == scope_id,
                    Status.id != status.id,
                )
                .update({Status.is_default: False}, synchronize_session=False)
            )
        # Exactly one ``is_initial`` per entity set (per SCOPE for scoped
        # machines, generic - every adopter benefits, not just a module's
        # entity) - converge silently, same pattern as ``is_default`` above.
        if flags.get("is_initial"):
            (
                self.db.query(Status)
                .filter(
                    Status.entity_type == entity.entity_type,
                    Status.tenant_id.is_(None) if scope is None else Status.tenant_id == scope,
                    Status.scope_id.is_(None) if scope_id is None else Status.scope_id == scope_id,
                    Status.id != status.id,
                )
                .update({Status.is_initial: False}, synchronize_session=False)
            )

    def _assert_not_sole_initial(
        self,
        status: Status,
        scope: Optional[str],
        scope_id: Optional[str],
        entity: StatusEntity,
    ) -> None:
        """AC-20: EXACTLY one `is_initial` per (entity_type, scope, scope_id)
        set - never zero. Raises a 422 if `status` is the only `is_initial=True`
        row in its set (turning it off / deleting it would leave the set with
        nowhere for a new record to start). Generic - applies to every
        adopting entity, unscoped (`scope_id=None`) and scoped alike."""
        still_initial = (
            self.db.query(Status)
            .filter(
                Status.entity_type == entity.entity_type,
                Status.tenant_id.is_(None) if scope is None else Status.tenant_id == scope,
                Status.scope_id.is_(None) if scope_id is None else Status.scope_id == scope_id,
                Status.id != status.id,
                Status.is_initial.is_(True),
            )
            .count()
        )
        if still_initial == 0:
            raise StatusValidationError(
                "At least one status must be marked as the initial stage."
            )

    def update_status(
        self,
        status_id: str,
        user: User,
        *,
        label: Optional[str] = None,
        color: Optional[str] = None,
        flags: Optional[Dict[str, bool]] = None,
        position_x: Optional[float] = None,
        position_y: Optional[float] = None,
        fields_set: Optional[set] = None,
    ) -> Status:
        # Find the entity through the row (id is globally unique).
        row = self.statuses.get_by_id(status_id)
        if row is None:
            raise StatusNotFound("Status not found.")
        entity = self._entity(row.entity_type)
        scope, scope_id = self._row_write_context(row, entity, user)
        status = self._get_status_in_scope(status_id, entity, scope, scope_id=scope_id)
        fields_set = fields_set or set()

        if label is not None:
            status.label = label.strip()
        if color is not None:
            status.color = color
        if "positionX" in fields_set:
            status.position_x = position_x
        if "positionY" in fields_set:
            status.position_y = position_y
        if flags:
            if status.is_system:
                # System rows: behavior locked (label/color/order stay editable).
                raise SystemStatusProtected(
                    "System status behavior flags cannot be changed."
                )
            self._apply_flags(status, flags, scope, entity, creating=False, scope_id=scope_id)
        self.db.commit()
        return status

    def delete_status(self, status_id: str, user: User) -> None:
        row = self.statuses.get_by_id(status_id)
        if row is None:
            raise StatusNotFound("Status not found.")
        entity = self._entity(row.entity_type)
        scope, scope_id = self._row_write_context(row, entity, user)
        status = self._get_status_in_scope(status_id, entity, scope, scope_id=scope_id)
        if status.is_system:
            raise SystemStatusProtected("System statuses cannot be deleted.")
        # scope == None ⇔ platform tier: count references across all tenants
        # still riding the defaults; a tenant fork counts only its own.
        count = entity.count_records(self.db, status.id, scope)
        if count > 0:
            raise StatusReferenced(count)
        # AC-20: even after migrate-records cleared every reference, deleting
        # the SOLE `is_initial` status would strand the set with nowhere for
        # a new record to start - same guard as `_apply_flags`'s
        # is_initial:false path.
        if status.is_initial:
            self._assert_not_sole_initial(status, scope, scope_id, entity)
        # Deleting a node drops its connected edges (graph-editor semantics).
        self.transitions.delete_for_status(status.id)
        self.statuses.delete(status)
        self.db.commit()

    def set_status_active(self, status_id: str, user: User, active: bool) -> Status:
        row = self.statuses.get_by_id(status_id)
        if row is None:
            raise StatusNotFound("Status not found.")
        entity = self._entity(row.entity_type)
        scope, scope_id = self._row_write_context(row, entity, user)
        status = self._get_status_in_scope(status_id, entity, scope, scope_id=scope_id)
        if status.is_system and not active:
            raise SystemStatusProtected("System statuses cannot be deactivated.")
        status.is_active = active
        self.db.commit()
        return status

    def migrate_records(self, status_id: str, to_status_id: str, user: User) -> int:
        row = self.statuses.get_by_id(status_id)
        if row is None:
            raise StatusNotFound("Status not found.")
        entity = self._entity(row.entity_type)
        scope, scope_id = self._row_write_context(row, entity, user)
        source = self._get_status_in_scope(status_id, entity, scope, scope_id=scope_id)
        target = self._get_status_in_scope(to_status_id, entity, scope, scope_id=scope_id)
        if source.id == target.id:
            raise StatusValidationError("Source and target are the same status.")
        if not target.is_active:
            raise StatusValidationError("Cannot migrate records to a deactivated status.")
        count = entity.migrate_records(self.db, source.id, target.id, scope)
        self.db.commit()
        return count

    def reorder(
        self,
        entity_type: str,
        ordered_ids: List[str],
        user: User,
        scope_id: Optional[str] = None,
    ) -> List[Status]:
        entity = self._entity(entity_type)
        scope, scope_id = self._scope_for_write(entity, user, scope_id)
        ordered_ids = [self._translate(i) for i in ordered_ids]
        rows = {
            s.id: s
            for s in self.statuses.list_for_entity(entity_type, scope, scope_id=scope_id)
        }
        unknown = [i for i in ordered_ids if i not in rows]
        if unknown or len(set(ordered_ids)) != len(rows):
            raise StatusValidationError("Reorder must include every status exactly once.")
        for index, status_id in enumerate(ordered_ids, start=1):
            rows[status_id].sort_order = index
        self.db.commit()
        return [rows[i] for i in ordered_ids]

    # ---- transitions ----

    def _get_transition_in_scope(
        self, transition_id: str, user: User
    ) -> Tuple[StatusTransition, StatusEntity, Optional[str]]:
        edge = self.transitions.get_by_id(transition_id)
        if edge is None:
            raise TransitionNotFound("Transition not found.")
        entity = self._entity(edge.entity_type)
        if entity.scoped:
            # Scoped edges are tenant-owned; endpoints carry the scope -
            # the tenant check below suffices (edges never bridge scopes).
            if edge.tenant_id != user.tenant_id:
                raise TransitionNotFound("Transition not found.")
            return edge, entity, user.tenant_id
        scope = self._write_scope(entity, user)
        if edge.tenant_id != scope:
            # The write may have just forked - the client sent a platform-tier
            # edge id; follow it to its forked counterpart.
            edge_map = getattr(self, "_fork_edge_map", None)
            if edge_map and edge.id in edge_map:
                edge = self.transitions.get_by_id(edge_map[edge.id])
            if edge is None or edge.tenant_id != scope:
                raise TransitionNotFound("Transition not found.")
        return edge, entity, scope

    def _resolve_roles(self, role_ids: List[str], user: User) -> List[Role]:
        if not role_ids:
            return []
        roles = (
            self.db.query(Role)
            .filter(Role.id.in_(role_ids), Role.tenant_id == user.tenant_id)
            .all()
        )
        if len(roles) != len(set(role_ids)):
            raise StatusValidationError("One or more roles were not found.")
        return roles

    def create_transition(
        self,
        entity_type: str,
        user: User,
        *,
        from_status_id: str,
        to_status_id: str,
        label: str,
        sort_order: Optional[int] = None,
        role_ids: Optional[List[str]] = None,
        notifications: Optional[List[Dict[str, Any]]] = None,
        conditions: Optional[Dict[str, Any]] = None,
        trigger_mode: str = "manual",
        scope_id: Optional[str] = None,
    ) -> StatusTransition:
        entity = self._entity(entity_type)
        scope, scope_id = self._scope_for_write(entity, user, scope_id)
        self._validate_conditions(conditions, entity_type)
        self._validate_trigger_mode(trigger_mode, conditions, role_ids or [])
        # Both endpoints must live in the SAME scope (D4 - an edge can never
        # bridge two forms' graphs).
        source = self._get_status_in_scope(from_status_id, entity, scope, scope_id=scope_id)
        target = self._get_status_in_scope(to_status_id, entity, scope, scope_id=scope_id)
        if source.id == target.id:
            raise StatusValidationError("A status cannot transition to itself.")
        if source.is_terminal:
            raise StatusValidationError(
                f'"{source.label}" is terminal - it cannot have outgoing transitions.'
            )
        if self.transitions.find_edge(source.id, target.id, scope) is not None:
            raise StatusValidationError("This transition already exists.")

        siblings = (
            self.transitions.list_for_statuses(
                [s.id for s in self.statuses.list_for_entity(entity_type, scope, scope_id=scope_id)],
                scope,
            )
            if entity.scoped
            else self.transitions.list_for_entity(entity_type, scope)
        )
        edge = StatusTransition(
            entity_type=entity_type,
            tenant_id=scope,
            from_status_id=source.id,
            to_status_id=target.id,
            label=label.strip(),
            sort_order=sort_order
            if sort_order is not None
            else (max((t.sort_order for t in siblings), default=0) + 1),
            conditions_json=conditions,
            trigger_mode=trigger_mode,
        )
        edge.roles = self._resolve_roles(role_ids or [], user)
        self.transitions.add(edge)
        if notifications is not None:
            self._sync_notifications(edge, notifications, scope)
        self.db.commit()
        return edge

    def update_transition(
        self,
        transition_id: str,
        user: User,
        *,
        label: Optional[str] = None,
        sort_order: Optional[int] = None,
        role_ids: Optional[List[str]] = None,
        notifications: Optional[List[Dict[str, Any]]] = None,
        conditions: Any = UNSET,
        trigger_mode: Optional[str] = None,
    ) -> StatusTransition:
        edge, _entity, scope = self._get_transition_in_scope(transition_id, user)
        if label is not None:
            edge.label = label.strip()
        if sort_order is not None:
            edge.sort_order = sort_order
        if role_ids is not None:
            edge.roles = self._resolve_roles(role_ids, user)
        if notifications is not None:
            self._sync_notifications(edge, notifications, scope)
        if conditions is not UNSET:  # provided: None = clear, dict = replace
            self._validate_conditions(conditions, edge.entity_type)
            edge.conditions_json = conditions
        if trigger_mode is not None:
            edge.trigger_mode = trigger_mode
        # Validate the RESULTING auto-edge invariants over the merged state -
        # an auto edge needs conditions and no roles whether they were just set
        # or already on the row (sprint-4/03 G6).
        self._validate_trigger_mode(
            edge.trigger_mode,
            edge.conditions_json,
            [r.id for r in edge.roles],
        )
        self.db.commit()
        return edge

    def _validate_conditions(
        self, conditions: Optional[Dict[str, Any]], entity_type: str
    ) -> None:
        """Save-time rule validation (sprint-2/02 D11) - 422 with specifics."""
        if conditions is None:
            return
        problems = validate_tree(conditions, ["actor", f"record:{entity_type}"])
        if problems:
            raise StatusValidationError(" ".join(problems))

    def _validate_trigger_mode(
        self,
        trigger_mode: str,
        conditions: Optional[Dict[str, Any]],
        role_ids: List[str],
    ) -> None:
        """Auto-edge invariants (sprint-4/03 G6): an AUTO edge is system-fired
        when its conditions become true - so it MUST carry conditions (an
        unconditioned auto-edge would fire always) and MUST NOT carry roles
        (no human fires it). 422 on violation."""
        if trigger_mode not in ("manual", "auto"):
            raise StatusValidationError(
                "Trigger mode must be 'manual' or 'auto'."
            )
        if trigger_mode != "auto":
            return
        if not conditions or not conditions.get("rules"):
            raise StatusValidationError(
                "An automatic transition must carry conditions."
            )
        if role_ids:
            raise StatusValidationError(
                "An automatic transition cannot be role-restricted."
            )

    def delete_transition(self, transition_id: str, user: User) -> None:
        edge, _entity, _scope = self._get_transition_in_scope(transition_id, user)
        # Inline-managed specs die with their only edge (link cascade keeps
        # shared specs alive for other edges).
        for spec in list(edge.notification_specs):
            if all(t.id == edge.id for t in self._spec_transitions(spec)):
                self.db.delete(spec)
        self.transitions.delete(edge)
        self.db.commit()

    # ---- notification specs (inline-managed per edge, D6) ----

    def _spec_transitions(self, spec: NotificationSpec) -> List[StatusTransition]:
        from app.models.notification_spec import notification_spec_transitions as link

        return (
            self.db.query(StatusTransition)
            .join(link, link.c.transition_id == StatusTransition.id)
            .filter(link.c.spec_id == spec.id)
            .all()
        )

    def _sync_notifications(
        self,
        edge: StatusTransition,
        notifications: List[Dict[str, Any]],
        scope: Optional[str],
    ) -> None:
        """Full-replace sync of the edge's specs (drawer sub-form semantics).
        The schema stays shareable (N:N link); this plan manages specs inline."""
        for spec in list(edge.notification_specs):
            others = [t for t in self._spec_transitions(spec) if t.id != edge.id]
            if not others:
                self.db.delete(spec)
        edge.notification_specs = []
        self.db.flush()

        specs: List[NotificationSpec] = []
        for item in notifications:
            channel = item.get("channel", "EMAIL")
            if channel not in NOTIFICATION_CHANNELS:
                raise StatusValidationError(f"Unknown channel '{channel}'.")
            subject = (item.get("templateSubject") or "").strip()
            body = (item.get("templateBody") or "").strip()
            if not subject or not body:
                raise StatusValidationError(
                    "Notification subject and body are required."
                )
            template_id = item.get("templateId")
            if template_id:
                # Polymorphic target_id rule: the referenced template must be
                # visible to the AUTHOR tier (platform row or own-tenant fork).
                from app.models.template import Template as _Template

                t = self.db.get(_Template, template_id)
                if t is None or (t.tenant_id is not None and t.tenant_id != scope):
                    raise StatusValidationError("Unknown template for this workspace.")
            spec = NotificationSpec(
                tenant_id=scope,
                channel=channel,
                template_subject=subject,
                template_body=body,
                template_key=item.get("templateKey"),
                template_id=template_id,
                doc_json=item.get("doc"),
            )
            # Recipient targets may only reference the AUTHOR tier's own
            # users/roles (platform-tier authors = the platform tenant) - a
            # foreign tenant's id here would leak email cross-tenant.
            author_tenant = scope or PLATFORM_TENANT_ID
            for r in item.get("recipients", []):
                target_type = r.get("targetType")
                if target_type not in RECIPIENT_TARGET_TYPES:
                    raise StatusValidationError(f"Unknown recipient type '{target_type}'.")
                target_id = r.get("targetId")
                dynamic_key = r.get("dynamicKey")
                if target_type in (TARGET_USER, TARGET_ROLE) and not target_id:
                    raise StatusValidationError("Recipient targetId is required.")
                if target_type == TARGET_DYNAMIC and dynamic_key not in DYNAMIC_KEYS:
                    raise StatusValidationError(
                        f"Unknown dynamic recipient '{dynamic_key}'."
                    )
                if target_type == TARGET_USER and (
                    self.db.query(User.id)
                    .filter(User.id == target_id, User.tenant_id == author_tenant)
                    .first()
                    is None
                ):
                    raise StatusValidationError("Recipient user not found.")
                if target_type == TARGET_ROLE and (
                    self.db.query(Role.id)
                    .filter(Role.id == target_id, Role.tenant_id == author_tenant)
                    .first()
                    is None
                ):
                    raise StatusValidationError("Recipient role not found.")
                spec.recipients.append(
                    NotificationRecipient(
                        target_type=target_type,
                        target_id=target_id,
                        dynamic_key=dynamic_key,
                    )
                )
            if not spec.recipients:
                raise StatusValidationError("A notification needs at least one recipient.")
            self.db.add(spec)
            specs.append(spec)
        edge.notification_specs = specs
        self.db.flush()
