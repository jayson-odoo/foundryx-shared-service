"""Per-module Alembic env (sprint-3/11) — ems. Reads version-table/schema/
metadata from the orchestrator's Config.attributes. Isolated history in
``alembic_version_ems`` inside ``app_ems``."""
from alembic import context
from sqlalchemy import create_engine

config = context.config
version_table = config.attributes.get("version_table", "alembic_version_ems")
version_table_schema = config.attributes.get("version_table_schema", "app_ems")
target_metadata = config.attributes.get("target_metadata")


def run_migrations_online() -> None:
    connectable = create_engine(config.get_main_option("sqlalchemy.url"))
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
