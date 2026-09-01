"""Per-module Alembic env (sprint-3/10 D3) - omnichannel.

Reads the version-table name + schema + target metadata from the orchestrator's
``Config.attributes`` (``app/module_platform/migrations.py``). Isolated history
in ``alembic_version_omnichannel`` inside the ``app_omnichannel`` schema, so the
module's migrations never collide with core's.
"""
from alembic import context
from sqlalchemy import create_engine

config = context.config

version_table = config.attributes.get("version_table", "alembic_version_omnichannel")
version_table_schema = config.attributes.get("version_table_schema", "app_omnichannel")
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
