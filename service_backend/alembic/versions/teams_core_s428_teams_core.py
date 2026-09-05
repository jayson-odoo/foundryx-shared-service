"""Teams (core) - plan 28 S1, roadmap A8 D-A8-1.

`public.teams` + `public.team_members`: a tenant-scoped grouping of users next
to roles, platform-wide, so any Service (omnichannel first) can assign work to
a team. Name is unique per tenant CASE-INSENSITIVELY via a Postgres functional
unique index (`lower(name)`) - the ORM model carries no such index, so the
service layer ALSO enforces it (the sqlite pytest path behaves identically).

Revision ID: teams_core_s428
Revises: b7c1d2e3f4a5
Create Date: 2026-09-06
"""
from alembic import op
import sqlalchemy as sa

from app.models.utc_datetime import UTCDateTime  # house autogen gotcha

revision = "teams_core_s428"
down_revision = "b7c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", UTCDateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_teams_tenant_id", "teams", ["tenant_id"])
    # Postgres-only functional unique index (case-insensitive name per tenant).
    # Not represented in the ORM model - the service layer mirrors this check
    # so the sqlite test path (create_all, no migration) behaves identically.
    op.execute(
        "CREATE UNIQUE INDEX ix_teams_tenant_name_lower "
        "ON teams (tenant_id, lower(name))"
    )

    op.create_table(
        "team_members",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="member"),
        sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_members_team_user"),
        sa.CheckConstraint("role IN ('member','lead')", name="ck_team_members_role"),
    )
    op.create_index("ix_team_members_team_id", "team_members", ["team_id"])
    op.create_index("ix_team_members_tenant_id", "team_members", ["tenant_id"])
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_team_members_user_id", table_name="team_members")
    op.drop_index("ix_team_members_tenant_id", table_name="team_members")
    op.drop_index("ix_team_members_team_id", table_name="team_members")
    op.drop_table("team_members")

    op.execute("DROP INDEX IF EXISTS ix_teams_tenant_name_lower")
    op.drop_index("ix_teams_tenant_id", table_name="teams")
    op.drop_table("teams")
