"""autocount baseline — establish the module's isolated Alembic history

Stage 1 is a scaffold: the module owns schema ``app_autocount`` but declares NO
tables yet (see ``modules/autocount/models.py``). This revision therefore emits
no DDL — its whole job is to create ``alembic_version_autocount`` inside the
module schema and stamp it, so slice 1's real table-creating revision has a
parent to chain from and ``run_module_migrations`` takes the
``has_version_table -> upgrade head`` branch on every subsequent boot.

The schema itself is created by the orchestrator (``run_module_migrations``
issues ``CREATE SCHEMA IF NOT EXISTS`` before Alembic runs) and by
``bootstrap.create_schema_and_tables`` — both idempotent.

Revision ID: 0001_autocount_baseline
Revises:
Create Date: 2026-07-21
"""
from typing import Sequence, Union

revision: str = "0001_autocount_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No DDL — the module has no tables yet (see the module docstring)."""


def downgrade() -> None:
    """No DDL to reverse."""
