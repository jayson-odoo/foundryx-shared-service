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
