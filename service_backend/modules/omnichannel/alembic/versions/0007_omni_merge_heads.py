"""omnichannel — merge the two divergent 0006 heads into one.

Two feature branches each added a ``0006`` revision off ``0005_omni_reactions``
(``0006_omni_embed`` from the embed framework, ``0006_omni_media_url_bf`` from the
sprint-4/10 media backfill). Both merged to main independently, leaving the module
Alembic history with TWO heads — so ``alembic upgrade head`` aborts with
"Multiple head revisions are present" and the module bootstrap (and the whole
blue/green deploy) fails. This is a no-op merge revision that joins both heads;
it alters no schema.

Revision ID: 0007_omni_merge_heads
Revises: 0006_omni_embed, 0006_omni_media_url_bf
Create Date: 2026-07-22
"""

# revision identifiers, used by Alembic.
revision = "0007_omni_merge_heads"
down_revision = ("0006_omni_embed", "0006_omni_media_url_bf")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op — this revision only reconciles the two heads."""
    pass


def downgrade() -> None:
    """No-op."""
    pass
