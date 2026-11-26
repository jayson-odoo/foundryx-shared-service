"""Per-module Alembic env - planner3d. Isolated history in
``alembic_version_planner3d`` inside ``app_planner3d`` (mirrors connector)."""

from __future__ import annotations
from alembic import context
from sqlalchemy import create_engine

config = context.config

version_table = config.attributes.get("version_table", "alembic_version_planner3d")
version_table_schema = config.attributes.get("version_table_schema", "app_planner3d")
target_metadata = config.attributes.get("target_metadata")


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url")
    connectable = create_engine(url)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=version_table,
            version_table_schema=version_table_schema,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


run_migrations_online()
