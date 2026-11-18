"""ideation - merge the two divergent heads off 0022 into one.

PR #261 (board image attachments, ``0025_ideation_comment_attach``) and lane
FEEDBACK-SUBSCRIBE (``0023_ideation_follow_share`` -> ``0024_ideation_history``)
each branched off ``0022_ideation_board_product`` and reached main separately,
leaving TWO heads, so ``alembic upgrade head`` would abort with "Multiple head
revisions are present". This no-op revision joins them, so a database on either
branch upgrades cleanly: one at 0025 runs 0023 + 0024, one at 0024 runs 0025.
It alters no schema (same pattern as ``omnichannel/0007_omni_merge_heads``).

Revision ID: 0026_ideation_merge_heads
Revises: 0024_ideation_history, 0025_ideation_comment_attach
Create Date: 2026-11-17
"""

# revision identifiers, used by Alembic.
revision = "0026_ideation_merge_heads"
down_revision = ("0024_ideation_history", "0025_ideation_comment_attach")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op - this revision only reconciles the two heads."""
    pass


def downgrade() -> None:
    """No-op."""
    pass
