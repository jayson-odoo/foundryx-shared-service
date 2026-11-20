"""autocount write action response status holds a list for a split (plan 55)

``ac_write_action.response_status`` INTEGER -> JSON: a single write keeps one
status, a split link records both statuses as a list. Existing integer values
convert in place (``to_json``); no data is lost. Never commits.

Revision ID: 0039_autocount_write_status   (28 chars <= 32)
Revises: 0038_autocount_write_lock
Create Date: 2026-11-06
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0039_autocount_write_status"
down_revision: Union[str, Sequence[str], None] = "0038_autocount_write_lock"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "app_autocount.ac_write_action"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        f"ALTER TABLE {TABLE} ALTER COLUMN response_status TYPE JSON USING to_json(response_status)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        f"ALTER TABLE {TABLE} ALTER COLUMN response_status TYPE INTEGER "
        f"USING (CASE WHEN json_typeof(response_status) = 'number' "
        f"THEN (response_status::text)::integer ELSE NULL END)"
    )
