"""autocount call person (plan 63 section 3.3)

* ``ac_api_call_log``: nullable ``acting_user_id``, ``acting_user_name`` (the person in the
  calling system who caused the write).
* ``ac_write_action``: nullable ``request_id``, ``acting_user_id``, ``acting_user_name``.
  Additive only. No backfill: rows written before this have no known person, NULL reads "-".
  Never commits.

Revision ID: 0045_autocount_call_person   (28 chars <= 32)
Revises: 0044_autocount_api_call_log
Create Date: 2026-11-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045_autocount_call_person"
down_revision: Union[str, Sequence[str], None] = "0044_autocount_api_call_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
COLUMNS = {
    "ac_api_call_log": ("acting_user_id", "acting_user_name"),
    "ac_write_action": ("request_id", "acting_user_id", "acting_user_name"),
}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table, names in COLUMNS.items():
        for name in names:
            op.add_column(table, sa.Column(name, sa.String(), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table, names in COLUMNS.items():
        for name in reversed(names):
            op.drop_column(table, name, schema=SCHEMA)
