"""form submission revisions (plan sprint-4/04)

Adds the revision identity to ``form_submissions`` (``submission_group_id`` +
``revision_number`` + ``is_current``) and the form-level ``allow_revisions``
toggle. Backfills every existing row as its own group's sole, current rev 1.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""
from alembic import op
import sqlalchemy as sa


revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Form-level opt-in.
    op.add_column(
        "forms",
        sa.Column(
            "allow_revisions",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Submission revision identity. Add group_id nullable first so we can
    # backfill it from the row's own id before enforcing NOT NULL.
    op.add_column(
        "form_submissions",
        sa.Column("submission_group_id", sa.String(), nullable=True),
    )
    op.add_column(
        "form_submissions",
        sa.Column(
            "revision_number",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "form_submissions",
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    # Backfill: every existing row is its own group's sole, current rev 1.
    # revision_number/is_current already defaulted via server_default.
    op.execute(
        "UPDATE form_submissions SET submission_group_id = id "
        "WHERE submission_group_id IS NULL"
    )
    op.alter_column("form_submissions", "submission_group_id", nullable=False)

    op.create_index(
        "ix_form_submissions_submission_group_id",
        "form_submissions",
        ["submission_group_id"],
    )
    op.create_index(
        "ix_form_submissions_is_current",
        "form_submissions",
        ["is_current"],
    )
    # Exactly ONE current revision per group, enforced at the DB level (a
    # concurrent double-revise can't create two live rows — the partial UNIQUE
    # index rejects the second). Doubles as the fast "latest per group" lookup.
    op.create_index(
        "ix_form_submissions_group_current",
        "form_submissions",
        ["submission_group_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )


def downgrade() -> None:
    op.drop_index("ix_form_submissions_group_current", table_name="form_submissions")
    op.drop_index("ix_form_submissions_is_current", table_name="form_submissions")
    op.drop_index(
        "ix_form_submissions_submission_group_id", table_name="form_submissions"
    )
    op.drop_column("form_submissions", "is_current")
    op.drop_column("form_submissions", "revision_number")
    op.drop_column("form_submissions", "submission_group_id")
    op.drop_column("forms", "allow_revisions")
