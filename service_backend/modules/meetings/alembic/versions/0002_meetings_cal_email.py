"""user_opt_ins.calendar_email - WHICH calendar a user's events are read from.

Nullable, no backfill needed and none possible: NULL is the correct value for
every existing row and means "my login email", which is exactly what the sync did
before this column existed. A user only sets it when the calendar they can share
is not their login address (a Workspace that blocks external sharing).

Explicit DDL, added as its OWN revision rather than by editing 0001 - a shipped
revision is a snapshot and editing it in place leaves every database that already
ran it silently behind.

Revision ID: 0002_meetings_cal_email
Revises: 0001_meetings_init
Create Date: 2026-08-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_meetings_cal_email"
down_revision = "0001_meetings_init"
branch_labels = None
depends_on = None

SCHEMA = "app_meetings"


def upgrade() -> None:
    op.add_column(
        "user_opt_ins",
        sa.Column("calendar_email", sa.String(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("user_opt_ins", "calendar_email", schema=SCHEMA)
