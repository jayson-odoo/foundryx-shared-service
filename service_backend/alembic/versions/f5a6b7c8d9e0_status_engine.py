"""status & state-machine engine (sprint-2/01, BL-027)

statuses gains trait flags (behavior binds to flags, never enums) + canvas
position; category becomes nullable + cosmetic. New: status_transitions (the
strict edge graph), transition_roles (fire authorization), notification_specs
+ recipients + the spec<->transition link.

Revision ID: f5a6b7c8d9e0
Revises: abbca98c3966
Create Date: 2026-06-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, Sequence[str], None] = "abbca98c3966"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    false = sa.text("false")
    true = sa.text("true")
    with op.batch_alter_table("statuses", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_initial", sa.Boolean(), nullable=False, server_default=false))
        batch_op.add_column(sa.Column("is_terminal", sa.Boolean(), nullable=False, server_default=false))
        batch_op.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=true))
        batch_op.add_column(sa.Column("blocks_access", sa.Boolean(), nullable=False, server_default=false))
        batch_op.add_column(sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=false))
        batch_op.add_column(sa.Column("is_default", sa.Boolean(), nullable=False, server_default=false))
        batch_op.add_column(sa.Column("position_x", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("position_y", sa.Float(), nullable=True))
        # Legacy cosmetic mirror - no code branches on it anymore (D2).
        batch_op.alter_column("category", existing_type=sa.String(), nullable=True)

    # Backfill the seeded tenant lifecycle flags (sprint-2/01 §migration).
    # Matched by (entity_type, key) - NOT by the seeded UUID constants - so a
    # deployment whose rows were ever re-created with different ids still gets
    # the flags (a missed `blocks_access` would re-open suspended-tenant login).
    op.execute(
        "UPDATE statuses SET is_initial = true, is_default = true "
        "WHERE entity_type = 'tenant' AND key = 'active'"
    )
    op.execute(
        "UPDATE statuses SET blocks_access = true "
        "WHERE entity_type = 'tenant' AND key = 'suspended'"
    )
    op.execute(
        "UPDATE statuses SET is_terminal = true, is_archived = true "
        "WHERE entity_type = 'tenant' AND key = 'archived'"
    )

    op.create_table(
        "status_transitions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("from_status_id", sa.String(), nullable=False),
        sa.Column("to_status_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("from_status_id != to_status_id", name="ck_transition_no_self_loop"),
        sa.ForeignKeyConstraint(["from_status_id"], ["statuses.id"]),
        sa.ForeignKeyConstraint(["to_status_id"], ["statuses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "from_status_id", "to_status_id", name="uq_transition_edge"),
    )
    with op.batch_alter_table("status_transitions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_status_transitions_entity_type"), ["entity_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_status_transitions_tenant_id"), ["tenant_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_status_transitions_from_status_id"), ["from_status_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_status_transitions_to_status_id"), ["to_status_id"], unique=False)

    op.create_table(
        "transition_roles",
        sa.Column("transition_id", sa.String(), nullable=False),
        sa.Column("role_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["transition_id"], ["status_transitions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("transition_id", "role_id"),
    )

    op.create_table(
        "notification_specs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("template_subject", sa.String(), nullable=False),
        sa.Column("template_body", sa.Text(), nullable=False),
        sa.Column("template_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("notification_specs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_notification_specs_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "notification_recipients",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("spec_id", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("dynamic_key", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["spec_id"], ["notification_specs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("notification_recipients", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_notification_recipients_spec_id"), ["spec_id"], unique=False)

    op.create_table(
        "notification_spec_transitions",
        sa.Column("transition_id", sa.String(), nullable=False),
        sa.Column("spec_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["transition_id"], ["status_transitions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["spec_id"], ["notification_specs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("transition_id", "spec_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("notification_spec_transitions")
    with op.batch_alter_table("notification_recipients", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notification_recipients_spec_id"))
    op.drop_table("notification_recipients")
    with op.batch_alter_table("notification_specs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notification_specs_tenant_id"))
    op.drop_table("notification_specs")
    op.drop_table("transition_roles")
    with op.batch_alter_table("status_transitions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_status_transitions_to_status_id"))
        batch_op.drop_index(batch_op.f("ix_status_transitions_from_status_id"))
        batch_op.drop_index(batch_op.f("ix_status_transitions_tenant_id"))
        batch_op.drop_index(batch_op.f("ix_status_transitions_entity_type"))
    op.drop_table("status_transitions")

    # Best-effort: restore the NOT NULL category by mirroring the key.
    op.execute("UPDATE statuses SET category = UPPER(key) WHERE category IS NULL")
    with op.batch_alter_table("statuses", schema=None) as batch_op:
        batch_op.alter_column("category", existing_type=sa.String(), nullable=False)
        batch_op.drop_column("position_y")
        batch_op.drop_column("position_x")
        batch_op.drop_column("is_default")
        batch_op.drop_column("is_archived")
        batch_op.drop_column("blocks_access")
        batch_op.drop_column("is_active")
        batch_op.drop_column("is_terminal")
        batch_op.drop_column("is_initial")
