"""autocount preview job claim (sprint-5/11 S4, AC-11-23/72)

Adds the single nullable column the preview-job claim needs:
``ac_entity_config`` += ``preview_job_id`` (nullable String) - the in-flight
``autocount_source_preview`` job claimed by this task, one preview per task
(D10: a module column, never a core ``background_jobs`` index). No backfill
needed - every existing row reads NULL ("no preview in flight"), which is
exactly right; nothing is stamped by this migration.

Existence-checked ADD (same convention as 0007/0014 in this module) so a
host where ``create_all`` already carries the column from the model
(``bootstrap_modules`` calls ``install()`` before ``run_module_migrations``)
is a clean no-op here.

Revision ID: 0022_autocount_preview_job   (27 chars <= 32)
Revises: 0021_autocount_pull_gateway
Create Date: 2026-09-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_autocount_preview_job"
down_revision: Union[str, Sequence[str], None] = "0021_autocount_pull_gateway"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_entity_config"


def _columns() -> set:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in set(inspector.get_table_names(schema=SCHEMA)):
        return set()
    return {col["name"] for col in inspector.get_columns(TABLE, schema=SCHEMA)}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    if "preview_job_id" not in _columns():
        op.add_column(
            TABLE, sa.Column("preview_job_id", sa.String(), nullable=True), schema=SCHEMA,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    if "preview_job_id" in _columns():
        op.drop_column(TABLE, "preview_job_id", schema=SCHEMA)
