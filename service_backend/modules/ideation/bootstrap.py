"""Ideation bootstrap - the App-Store module contract (plan 08 §4).

``install`` is GLOBAL and idempotent (schema + tables + permission-catalog sync);
the per-tenant hooks (``install_tenant`` / ``update_tenant`` / ``uninstall_tenant``)
are driven by AppStoreService when a tenant installs/updates/uninstalls. Permission
GRANTS are the store's concern (it grants the module keys to the tenant's roles).

Slice 1 scaffold: schema + (currently empty) tables + permission CSV. Idea status
entity, IntakeDefinition registry, capabilities and per-tenant seeds are filled by
later slices - the hooks are wired now so the module contract is complete.
"""
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.repositories.permission_repository import PermissionRepository
from app.services.permission_service import load_csv

from . import models  # noqa: F401 - register module tables on IdeationBase.metadata
from .db import IDEATION_SCHEMA, IdeationBase

MODULE_NAME = "ideation"
MODULE_CSV = Path(__file__).resolve().parent / "permissions" / "permissions.csv"


def register_capabilities() -> None:
    """Boot-time capability registration (plan sprint-3/10 D5). Idempotent.

    Ideation provides no capabilities yet (it consumes omnichannel's
    ``messaging.send@1`` for submitter notifications - later slice)."""
    return None


def register_engine_entities() -> None:
    """Boot-time engine registration (plan 11 D9). Idempotent - called by
    ``register_module_boot`` whenever the module is loaded.

    Slice 2 (AC-A-05/A-07): register the ``software`` product-kind and the
    delivery adapter-kind registry. Both registrations are GLOBAL (module-tagged);
    the ``software`` kind is filtered by the active-modules visibility gate at
    every catalog read, so it surfaces (in ``/products/kinds``) only for tenants
    with ideation installed - core ``good`` covers goods.

    Slice 3 (AC-A-10): register the Idea as a **tenant-owned** status entity on
    the core status engine (lifecycle draft→…→closed +duplicate/+rejected). The
    status ROWS + transition graph are seeded as platform defaults in ``install``
    (they need a db session); this only registers the code-side entity.

    Still placeholders for later slices: the ``ideation`` IntakeDefinition and the
    idea-attachment storage-locations declaration."""
    from app.catalog.kinds import ProductKind, register_product_kind
    from app.status_engine.registry import StatusEntity, register_status_entity

    from .adapters import registered_adapter_kinds
    from .services.statuses import (
        BR_ENTITY,
        IDEA_ENTITY,
        br_count_records,
        br_migrate_records,
        idea_count_records,
        idea_migrate_records,
    )

    # Software is the ideation-owned kind - visible only while ideation is active.
    register_product_kind(ProductKind("software", "Software", MODULE_NAME, 3))
    # Populate the adapter-kind registry (embed_connection wired; the rest dormant).
    registered_adapter_kinds()
    # Idea rides the core status engine - tenant-owned, non-scoped (D-A3).
    register_status_entity(
        StatusEntity(
            entity_type=IDEA_ENTITY,
            label="Idea",
            module=MODULE_NAME,
            count_records=idea_count_records,
            migrate_records=idea_migrate_records,
            record_label_attr="problem",
            required_flags=["is_initial", "is_terminal", "is_archived"],
        )
    )
    # Business Requirement rides the core status engine too - tenant-owned,
    # unscoped (Bi-D3, slice 2). draft → grilling → ready → in-FR → delivered →
    # archived; the draft → ready edge is the S4 promote gate.
    register_status_entity(
        StatusEntity(
            entity_type=BR_ENTITY,
            label="Business Requirement",
            module=MODULE_NAME,
            count_records=br_count_records,
            migrate_records=br_migrate_records,
            record_label_attr="title",
            required_flags=["is_initial", "is_archived"],
        )
    )
    # Conversational-Intake engine (D18, AC-A-13): register the single ``ideation``
    # IntakeDefinition (form_engine target_schema + completion_rule + sink).
    from .services.intake_definitions import register_ideation_intake

    register_ideation_intake()

    # Grill engine (Phase B-i slice 3, AC-BI-20): register the Idea → BR
    # GrillDefinition (instance one). Adding BR → FR later is a new definition
    # row, not new engine code.
    from .services.grill import register_idea_to_br_grill

    register_idea_to_br_grill()

    # Deferred (grace-window) actions (sprint-4/23, T5 fix round 1, item 15):
    # ideation's own confirm:-gated destructive actions register into the
    # CORE grace-window engine here, the same way any other module extends a
    # shared engine (status/rule/workflow) - never a fork.
    from .deferred_actions import register_ideation_deferred_actions

    register_ideation_deferred_actions()


def create_schema_and_tables(engine: Engine) -> None:
    """Create the module schema (Postgres) + all module tables. Idempotent."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{IDEATION_SCHEMA}"'))
    IdeationBase.metadata.create_all(bind=engine)


def install(engine: Engine, db: Session) -> None:
    """Global install (plan 08 §4): schema + tables + permission catalog sync.

    Runs at every bootstrap (idempotent). Per-tenant seeding happens in
    ``install_tenant`` when a tenant actually installs the module.
    """
    create_schema_and_tables(engine)
    PermissionRepository(db).sync(MODULE_NAME, load_csv(MODULE_CSV))
    # Idea status set + transition graph as platform defaults (AC-A-10, D-A3).
    # Two-tier: every tenant uses these until it forks the set. Idempotent.
    from .services.br_templates import seed_br_template
    from .services.statuses import seed_br_statuses, seed_idea_statuses

    seed_idea_statuses(db)
    # Business Requirement status set + graph + the platform-tier BR template
    # (Phase B-i slice 2, AC-BI-15/16). Idempotent + insert-if-missing.
    seed_br_statuses(db)
    seed_br_template(db)
    # The platform-tier grill-me-business skill (Phase B-i slice 3, AC-BI-28).
    # Insert-if-missing - an operator's edits survive a reseed.
    from .services.grill_seed import seed_grill_skill

    seed_grill_skill(db)


def install_tenant(db: Session, tenant_id: str) -> None:
    """Per-tenant seed (plan 08 §4). Idempotent.

    Later slices seed the tenant's Idea status set + the ``ideation``
    IntakeDefinition binding + register the ``software`` product-kind here
    (AC-A-03). The scaffold slice has no per-tenant artifacts to seed.

    Phase B-i slice 3 (AC-BI-20b): auto-seed the default ``Ideation grill`` agent
    (insert-if-missing) so grilling is zero-config. If no LLM connection resolves
    yet it is seeded connectionless and lights up when a key is later added."""
    from .services.grill_seed import seed_grill_agent

    seed_grill_agent(db, tenant_id)


def update_tenant(db: Session, tenant_id: str, from_version: str) -> None:
    """Per-tenant data migration between provisioned versions (plan 08 D3).

    All of ideation is 0.1.0 today - nothing to backfill yet."""
    return None


def uninstall_tenant(db: Session, tenant_id: str) -> None:
    """Wipe THIS tenant's rows from every module table (plan 08 §5).

    The module schema and other tenants' rows are untouched - uninstall is
    per-tenant, never global. Core ``public.products``, omnichannel contacts and
    other tenants' rows stay intact (AC-A-03). Reverse dependency order avoids FK
    violations. (No module tables in the scaffold slice - a safe no-op.)"""
    for table in reversed(IdeationBase.metadata.sorted_tables):
        if "tenant_id" in table.c:
            db.execute(table.delete().where(table.c.tenant_id == tenant_id))
    db.flush()


def tenant_has_data(db: Session, tenant_id: str) -> bool:
    """Backfill detection (loader) for pre-App-Store installs. Ideation is a
    net-new module - no legacy data ever existed - so no tenant backfills."""
    return False
