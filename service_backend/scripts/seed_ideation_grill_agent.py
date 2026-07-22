"""Backfill the Phase B-i slice 3 grill artifacts for EXISTING tenants (AC-BI-20b,
DoD #2/#4).

``install_tenant`` seeds the ``Ideation grill`` agent only when a tenant installs
the module — it does NOT reach tenants that already have ideation ACTIVE. This
idempotent sweep:

  1. seeds the platform-tier ``grill-me-business`` skill (insert-if-missing), then
  2. seeds the ``Ideation grill`` agent (insert-if-missing) for every tenant that
     has ideation ACTIVE.

Run once after deploying slice 3:

  python -m scripts.seed_ideation_grill_agent
"""
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule
from modules.ideation.services.grill_seed import seed_grill_agent, seed_grill_skill

MODULE_NAME = "ideation"


def seed_all_grill_agents(db: Session) -> int:
    """Seed the platform-tier skill + the per-tenant grill agent for every tenant
    with ideation ACTIVE. Idempotent (insert-if-missing). Commits; returns the
    tenant count. Reused by ``bootstrap_db`` so a fresh deploy self-seeds."""
    seed_grill_skill(db)
    db.flush()
    active = (
        db.query(TenantModule)
        .join(Module, Module.id == TenantModule.module_id)
        .filter(
            Module.name == MODULE_NAME,
            TenantModule.status == MODULE_STATUS_ACTIVE,
        )
        .all()
    )
    for row in active:
        seed_grill_agent(db, row.tenant_id)
    db.commit()
    return len(active)


def main() -> None:
    db = SessionLocal()
    try:
        seeded = seed_all_grill_agents(db)
        print(
            f"grill backfill done: grill-me-business skill ensured, "
            f"'Ideation grill' agent seeded for {seeded} tenant(s) with ideation ACTIVE."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
