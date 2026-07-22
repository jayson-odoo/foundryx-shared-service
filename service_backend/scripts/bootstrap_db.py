"""Canonical DB bootstrap — idempotent, re-runnable, zero-touch for on-prem.

  python -m scripts.bootstrap_db

Steps (Postgres):
  1. connect as admin (POSTGRES_ADMIN_URL) and ensure the app role + database
  2. run `alembic upgrade head`
  3. seed the default tenant + roles + demo users

Operators set POSTGRES_ADMIN_URL + DATABASE_URL in .env and run this once; the
same command handles a blank server and a later upgrade. For SQLite the
role/db step is skipped (file is created on connect).
"""
import os

from alembic import command
from alembic.config import Config

from app.config import settings
from app.database import SessionLocal
from app.seed import seed_all

APP_ROLE = "foundryx"
APP_PASSWORD = "foundryx"
APP_DB = "foundryx_service"


def _admin_url() -> str:
    # Default to the local superuser on the maintenance DB.
    user = os.environ.get("USER", "postgres")
    return os.environ.get(
        "POSTGRES_ADMIN_URL", f"postgresql://{user}@localhost:5432/postgres"
    )


def ensure_role_and_db() -> None:
    import psycopg2
    from psycopg2 import sql

    conn = psycopg2.connect(_admin_url())
    conn.autocommit = True  # CREATE DATABASE can't run inside a transaction
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,))
        if not cur.fetchone():
            cur.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s").format(sql.Identifier(APP_ROLE)),
                (APP_PASSWORD,),
            )
            print(f"created role: {APP_ROLE}")
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (APP_DB,))
        if not cur.fetchone():
            cur.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(APP_DB), sql.Identifier(APP_ROLE)
                )
            )
            print(f"created database: {APP_DB}")
        cur.close()
    finally:
        conn.close()


def run_migrations() -> None:
    command.upgrade(Config("alembic.ini"), "head")


def main() -> None:
    if settings.database_url.startswith("postgresql"):
        ensure_role_and_db()
    run_migrations()
    db = SessionLocal()
    try:
        seed_all(db)
    finally:
        db.close()

    # Install/seed App-Store modules (omnichannel, …) — schema, tables, perms.
    from app.module_loader import bootstrap_modules

    bootstrap_modules()

    # Install the first Service (omnichannel) for the built-in default tenant so
    # the platform is usable out of the box (inbox + demo). Idempotent — skips if
    # already installed. Other tenants install via the App Store. (Slice 2 §2.1)
    from app.models.tenant import DEFAULT_TENANT_ID
    from app.services.app_store_service import AlreadyInstalled, AppStoreService

    db = SessionLocal()
    try:
        AppStoreService(db).install(DEFAULT_TENANT_ID, "omnichannel")
    except AlreadyInstalled:
        pass
    finally:
        db.close()

    # Grant sweep AFTER module perms are synced (DoD gate #4): the seed_all
    # sweep above runs BEFORE the module CSVs load, so every tenant's Admin
    # would miss freshly-synced installed-module keys (e.g. api_keys.*). Re-run
    # tenant_admin_grant now that the catalog is complete. Idempotent.
    from app.seed import sweep_tenant_admin_grants

    db = SessionLocal()
    try:
        sweep_tenant_admin_grants(db)
    finally:
        db.close()

    # Seed the ideation grill skill + per-tenant "Ideation grill" agent for every
    # tenant with ideation ACTIVE (Phase B-i S3, AC-BI-20b). Like the grant sweep
    # above, this reaches tenants that got ideation via the backfill path (which
    # doesn't run install_tenant) — e.g. the demo tenant on a fresh bootstrap.
    # Idempotent (insert-if-missing). Best-effort: never fail bootstrap.
    try:
        from scripts.seed_ideation_grill_agent import seed_all_grill_agents

        db = SessionLocal()
        try:
            count = seed_all_grill_agents(db)
            print(f"ideation: grill agent seeded for {count} tenant(s)")
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — ideation may be absent/errored
        print(f"ideation grill seed skipped: {exc}")

    # DEV-only demo inbox (plan 05) — never seeds in prod.
    if settings.environment == "development":
        from app.models.tenant import DEFAULT_TENANT_ID
        from modules.omnichannel.bootstrap import seed_demo_conversations

        db = SessionLocal()
        try:
            seed_demo_conversations(db, DEFAULT_TENANT_ID)
            print("omnichannel: demo conversations seeded")
        finally:
            db.close()

    print("bootstrap complete: migrated + seeded + modules")


if __name__ == "__main__":
    main()
