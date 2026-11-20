"""meetings.status_reason + meetings.screenshot_key - the S2 run outcome.

``not_admitted_reason`` is RENAMED to ``status_reason``: S2 has three unhappy
statuses (``not_admitted``, ``failed``, ``skipped``) and one reason column that
tells the truth about all three beats one that lies about two. Nothing had
written the old column - S0 only ever creates a meeting ``scheduled`` and never
sets a reason - so the rename carries no data and needs no backfill. It is a
RENAME rather than a drop-and-add so a database that somehow does hold a value
keeps it.

``screenshot_key`` holds the storage key of the bot's ``last.png`` (AC-S2-8):
the container is gone by the time anyone looks, and the screenshot is the only
thing that says what the page actually showed.

Revision ID: 0003_meetings_run_reason
Revises: 0002_meetings_cal_email
Create Date: 2026-08-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_meetings_run_reason"
down_revision = "0002_meetings_cal_email"
branch_labels = None
depends_on = None

SCHEMA = "app_meetings"


def upgrade() -> None:
    op.alter_column(
        "meetings",
        "not_admitted_reason",
        new_column_name="status_reason",
        schema=SCHEMA,
    )
    op.add_column(
        "meetings",
        sa.Column("screenshot_key", sa.Text(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("meetings", "screenshot_key", schema=SCHEMA)
    op.alter_column(
        "meetings",
        "status_reason",
        new_column_name="not_admitted_reason",
        schema=SCHEMA,
    )
