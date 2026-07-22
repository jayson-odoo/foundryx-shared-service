"""Grant sweep for the Phase B-i slice 2 BR permissions (DoD #4, AC-BI-19).

A new module permission is computed at install/provision, so it does NOT reach
tenants that already have ideation installed — they would silently 403 the new
Business-Requirement surface until re-granted. This idempotent sweep:

  1. re-syncs the ideation permission catalog from the module CSV (so the new
     ``ideation.business_requirements.*`` rows exist), then
  2. for every tenant with ideation ACTIVE, appends the module's catalog rows to
     that tenant's **Admin** role (mirrors ``AppStoreService._grant_admin``).

Run once after deploying slice 2:

  python -m scripts.grant_ideation_br_perms
"""
from pathlib import Path

from app.database import SessionLocal
from app.models.module import MODULE_STATUS_ACTIVE, Module, TenantModule
from app.models.permission import Permission
from app.models.role import Role
from app.repositories.permission_repository import PermissionRepository
from app.services.permission_service import load_csv

MODULE_NAME = "ideation"
MODULE_CSV = (
    Path(__file__).resolve().parents[1]
    / "modules"
    / "ideation"
    / "permissions"
    / "permissions.csv"
)


def main() -> None:
    db = SessionLocal()
    try:
        # 1. Ensure the new BR rows exist in the global catalog.
        PermissionRepository(db).sync(MODULE_NAME, load_csv(MODULE_CSV))
        db.flush()

        module_perms = (
            db.query(Permission).filter(Permission.module == MODULE_NAME).all()
        )

        # 2. Grant to every tenant that has ideation ACTIVE.
        active = (
            db.query(TenantModule)
            .join(Module, Module.id == TenantModule.module_id)
            .filter(
                Module.name == MODULE_NAME,
                TenantModule.status == MODULE_STATUS_ACTIVE,
            )
            .all()
        )
        granted = 0
        for row in active:
            admin = (
                db.query(Role)
                .filter(Role.tenant_id == row.tenant_id, Role.name == "Admin")
                .first()
            )
            if admin is None:
                continue
            held = {p.id for p in admin.permissions}
            for perm in module_perms:
                if perm.id not in held:
                    admin.permissions.append(perm)
            granted += 1
        db.commit()
        print(
            f"grant sweep done: {len(module_perms)} ideation perms, "
            f"re-granted to Admin of {granted} tenant(s) with ideation ACTIVE."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
