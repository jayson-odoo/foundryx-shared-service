"""Test fixtures: isolated in-memory SQLite + seeded default tenant/users."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql import func

from app.database import Base, get_db
from app.main import app
from app.models import (
    DEFAULT_TENANT_ID,
    Role,
    User,
    UserStatus,
)
from app.config import settings
from app.seed import (
    PLATFORM_ADMIN_EMAIL,
    PLATFORM_ADMIN_PASSWORD,
    seed_default_tenant,
    seed_permissions,
    seed_platform_admin,
    seed_platform_tenant,
    seed_statuses,
    seed_tenant_transitions,
    tenant_admin_grant,
)
from app.security import hash_password

# Tests run the omnichannel adapter in DEV mode (no live Meta Graph calls), even
# when META_* is set in a local .env — blank the Meta config for the test process.
settings.meta_app_id = ""
settings.meta_app_secret = ""
# No dispatcher thread under tests — outbox tests drive dispatch_pending()
# directly against the test session (the thread would hit the real DATABASE_URL).
settings.email_dispatcher_enabled = False
# Tests must not pick up a platform SMTP connection from the local .env.
settings.platform_smtp_host = ""
# Workflow runs execute inline under tests (no Celery worker / Redis broker).
settings.celery_task_always_eager = True

ACTIVE_EMAIL = "demo@example.com"
ACTIVE_PASSWORD = "demo1234"
INACTIVE_EMAIL = "inactive@example.com"
INACTIVE_PASSWORD = "inactive1234"
PLATFORM_EMAIL = PLATFORM_ADMIN_EMAIL
PLATFORM_PASSWORD = PLATFORM_ADMIN_PASSWORD


@pytest.fixture
def session_factory():
    # The omnichannel module uses the `app_omnichannel` schema. SQLite has no
    # native schemas, so ATTACH an in-memory database as `omni` and translate
    # the module schema onto it — keeps module tables isolated from core (the
    # module's `statuses` must not collide with the core `statuses`, plan 07).
    from modules.omnichannel.db import OMNI_SCHEMA, OmniBase
    from modules.ems.db import EMS_SCHEMA, EmsBase
    from modules.crm.db import CRM_SCHEMA, CrmBase
    from modules.finance.db import FINANCE_SCHEMA, FinanceBase
    import modules.ems.models  # noqa: F401 — register tables on EmsBase.metadata
    import modules.crm.models  # noqa: F401 — register tables on CrmBase.metadata
    import modules.finance.models  # noqa: F401 — register tables on FinanceBase.metadata

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(
        # All module schemas map onto one attached in-memory db (distinct table
        # names; no collisions) — module tables stay isolated from core's.
        schema_translate_map={OMNI_SCHEMA: "omni", EMS_SCHEMA: "omni", CRM_SCHEMA: "omni", FINANCE_SCHEMA: "omni"}
    )
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH ':memory:' AS omni")
        conn.commit()
    Base.metadata.create_all(bind=engine)
    OmniBase.metadata.create_all(bind=engine)
    EmsBase.metadata.create_all(bind=engine)
    CrmBase.metadata.create_all(bind=engine)
    FinanceBase.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False
    )

    db = TestingSessionLocal()
    # Statuses + tenants (default + platform) + permission catalogs (core +
    # platform) + the platform operator — same seed path bootstrap_db runs.
    seed_statuses(db)
    seed_tenant_transitions(db)
    seed_default_tenant(db)
    seed_platform_tenant(db)
    seed_permissions(db)
    seed_platform_admin(db)
    # Template engine (plan 07): platform-tier system templates — the suite's
    # email flows render through the engine like production.
    from app.template_engine.seed_templates import seed_platform_templates

    seed_platform_templates(db)

    # Default-tenant Admin role holding the core keys (module keys arrive via
    # the App-Store install below — plan 08 §5 grant model).
    admin_role = Role(
        tenant_id=DEFAULT_TENANT_ID,
        name="Admin",
        description="Full system access",
        is_system=True,
    )
    admin_role.permissions = tenant_admin_grant(db, DEFAULT_TENANT_ID)
    db.add(admin_role)
    db.flush()

    demo = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=ACTIVE_EMAIL,
        password=hash_password(ACTIVE_PASSWORD),
        name="Demo User",
        status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    demo.roles = [admin_role]
    db.add(demo)
    db.add(
        User(
            tenant_id=DEFAULT_TENANT_ID,
            email=INACTIVE_EMAIL,
            password=hash_password(INACTIVE_PASSWORD),
            name="Inactive User",
            status=UserStatus.INACTIVE.value,
        )
    )
    db.commit()

    # Module wiring, the real path (plan 08): catalog sync + global install,
    # then INSTALL omnichannel for the default tenant via the store service —
    # seeds the default workspace and grants the module keys to the Admin role.
    from app.module_loader import bootstrap_modules
    from app.services.app_store_service import AppStoreService

    bootstrap_modules(engine=engine, db=db)
    AppStoreService(db).install(DEFAULT_TENANT_ID, "omnichannel")
    AppStoreService(db).install(DEFAULT_TENANT_ID, "finance")  # before ems (ems requires it)
    AppStoreService(db).install(DEFAULT_TENANT_ID, "ems")
    AppStoreService(db).install(DEFAULT_TENANT_ID, "crm")
    db.close()

    yield TestingSessionLocal


@pytest.fixture
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
