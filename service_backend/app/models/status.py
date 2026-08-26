"""Core statuses - the status & state-machine engine (sprint-2/01, BL-027).

One row per (entity_type, tenant, key). Behavior binds to **boolean trait
flags** (``blocks_access``, ``is_archived``, ``is_initial``, ``is_terminal``),
NEVER to a named enum - tenants define arbitrary states. ``category`` is a
legacy cosmetic mirror (uppercase key) kept for the wire/filter contract of
already-shipped surfaces; code must never branch on it.

Two-tier ownership: platform defaults carry ``tenant_id NULL``; a tenant forks
the whole set for an entity on first edit (``tenant_id`` set), which then
overrides. System rows: label/color/order editable, key/behavior/delete locked.

Scoped machines (sprint-3/01 D4): entities registered ``scoped`` carry one
graph PER OWNING RECORD via ``scope_id`` (e.g. each form's submissions get
their own pipeline) - materialized at scope creation, tenant-owned from
birth, no two-tier resolution. Unscoped entities keep ``scope_id NULL``.
"""
import uuid

from sqlalchemy import Boolean, Column, Float, Integer, String, UniqueConstraint
from sqlalchemy.sql import func
from app.models.utc_datetime import UTCDateTime

from app.database import Base

# Entity types adopting the engine. Modules register theirs via the registry
# (app/status_engine/registry.py); core registers "tenant".
TENANT_ENTITY = "tenant"

# Legacy uppercase wire values for the seeded tenant lifecycle rows. These are
# DISPLAY/filter constants only - lifecycle behavior reads the trait flags.
TENANT_STATUS_ACTIVE = "ACTIVE"
TENANT_STATUS_SUSPENDED = "SUSPENDED"
TENANT_STATUS_ARCHIVED = "ARCHIVED"

# Stable ids so migrations + seed can reference the system rows directly.
TENANT_STATUS_IDS = {
    TENANT_STATUS_ACTIVE: "20000000-0000-0000-0000-000000000001",
    TENANT_STATUS_SUSPENDED: "20000000-0000-0000-0000-000000000002",
    TENANT_STATUS_ARCHIVED: "20000000-0000-0000-0000-000000000003",
}

# (id, key, label, color, sort_order, flags) - system rows, label/color editable.
# flags = dict of trait columns; everything unset defaults False.
TENANT_STATUS_SEED = [
    (
        TENANT_STATUS_IDS[TENANT_STATUS_ACTIVE],
        "active",
        "Active",
        "green",
        1,
        {"is_initial": True, "is_default": True},
    ),
    (
        TENANT_STATUS_IDS[TENANT_STATUS_SUSPENDED],
        "suspended",
        "Suspended",
        "amber",
        2,
        {"blocks_access": True},
    ),
    (
        TENANT_STATUS_IDS[TENANT_STATUS_ARCHIVED],
        "archived",
        "Archived",
        "gray",
        3,
        # NOT terminal (sprint-2/02 revision - user decision): an archived
        # tenant can be restored to active. is_terminal stays False explicitly
        # so the always-converge seed un-flags pre-revision DBs.
        {"is_terminal": False, "is_archived": True},
    ),
]

# Stable ids for the seeded tenant transition graph (sprint-2/01; Restore
# added sprint-2/02 - archive is reversible, hard purge stays BL-035).
TENANT_TRANSITION_SEED = [
    # (id, from_status, to_status, label, sort_order)
    ("30000000-0000-0000-0000-000000000001", TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED, "Suspend", 1),
    ("30000000-0000-0000-0000-000000000002", TENANT_STATUS_SUSPENDED, TENANT_STATUS_ACTIVE, "Reactivate", 2),
    ("30000000-0000-0000-0000-000000000003", TENANT_STATUS_ACTIVE, TENANT_STATUS_ARCHIVED, "Archive", 3),
    ("30000000-0000-0000-0000-000000000004", TENANT_STATUS_SUSPENDED, TENANT_STATUS_ARCHIVED, "Archive", 4),
    ("30000000-0000-0000-0000-000000000005", TENANT_STATUS_ARCHIVED, TENANT_STATUS_ACTIVE, "Restore", 5),
]


class Status(Base):
    __tablename__ = "statuses"
    __table_args__ = (
        UniqueConstraint(
            "entity_type", "tenant_id", "scope_id", "key", name="uq_statuses_entity_tenant_key"
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_type = Column(String, nullable=False, index=True)
    # Machine key, stable per entity_type (e.g. "active").
    key = Column(String, nullable=False)
    # LEGACY cosmetic mirror (uppercase key) - wire/filter display only.
    # Behavior branches on the trait flags below, never here (sprint-2/01 D2).
    category = Column(String, nullable=True)
    # Display - editable on any row, system rows included.
    label = Column(String, nullable=False)
    color = Column(String, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)

    # ---- trait flags (the machine semantics - sprint-2/01 D2) ----
    # Records of this entity start here (one per entity set - validated app-side).
    is_initial = Column(Boolean, nullable=False, default=False)
    # No outgoing transitions allowed from a terminal status.
    is_terminal = Column(Boolean, nullable=False, default=False)
    # Deactivated statuses are hidden from pickers/new edges; records keep them.
    is_active = Column(Boolean, nullable=False, default=True)
    # Tenant lifecycle: signing in / requests blocked while record holds this.
    blocks_access = Column(Boolean, nullable=False, default=False)
    # Record hidden from the default ("Active") list view; data intact.
    is_archived = Column(Boolean, nullable=False, default=False)
    # Pre-selected status for new records.
    is_default = Column(Boolean, nullable=False, default=False)

    # Canvas layout (status-engine graph editor) - nullable = auto-layout.
    position_x = Column(Float, nullable=True)
    position_y = Column(Float, nullable=True)

    # System rows: key/flags immutable, row non-deletable.
    is_system = Column(Boolean, nullable=False, default=False)
    # NULL = platform default set. Plain column (no FK) to avoid a
    # tenants<->statuses dependency cycle; integrity enforced app-side.
    tenant_id = Column(String, nullable=True, index=True)
    # Scoped machines (sprint-3/01 D4): for entities registered ``scoped``,
    # each owning record (e.g. a form) carries its OWN graph - rows are
    # materialized at scope creation with ``(tenant_id, scope_id)`` set,
    # tenant-owned from birth (no two-tier fork). NULL = unscoped entity
    # (tenant, …) - behavior unchanged. Plain column (no FK) - the scope
    # table varies per entity; integrity enforced app-side like tenant_id.
    scope_id = Column(String, nullable=True, index=True)

    created_at = Column(UTCDateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
