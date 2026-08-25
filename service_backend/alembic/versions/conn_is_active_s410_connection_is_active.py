"""connections.is_active + relaxed partial-unique index (sprint-4/10 Slice 2)

Adds the write-target flag ``connections.is_active`` (D10). During a storage
migration a RETIRED connection A (is_active=false) and its ACTIVE successor B
coexist, so the one-per-type partial-unique index gains an ``AND is_active``
predicate. ``resolve_for_type`` filters ``is_active`` (only B is the write
target); resolve-BY-KEY ignores it (A still serves its historical blobs).

Every pre-existing row is BACKFILLED to ``true`` (explicit UPDATE, not merely
default-on-insert - DoD backfill rule).

Revision id length: 19 chars (≤ 32 - alembic_version.version_num VARCHAR(32)).

Revision ID: conn_is_active_s410
Revises: bgjobs_1a2b3c4d5e6f
Create Date: 2026-07-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "conn_is_active_s410"
down_revision: Union[str, Sequence[str], None] = "bgjobs_1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "connections",
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    # Explicit backfill of pre-existing rows (real backfill, not seed-if-absent).
    op.execute("UPDATE connections SET is_active = true")

    # Relax the one-per-type partial-unique index: it now also requires the row
    # to be active, so A(inactive)+B(active) of the same type coexist.
    op.drop_index("uq_connection_tenant_type", table_name="connections")
    op.create_index(
        "uq_connection_tenant_type",
        "connections",
        ["tenant_id", "type"],
        unique=True,
        postgresql_where=sa.text("type != 'payment' AND is_active"),
        sqlite_where=sa.text("type != 'payment' AND is_active"),
    )

    # Relax the (tenant, provider) plain unique CONSTRAINT to a partial unique
    # INDEX on is_active - a SAME-PROVIDER bucket migration (s3→s3) must let the
    # retired A and active B coexist. Two ACTIVE same-provider rows stay blocked.
    op.drop_constraint("uq_connection_tenant_provider", "connections", type_="unique")
    op.create_index(
        "uq_connection_tenant_provider",
        "connections",
        ["tenant_id", "provider"],
        unique=True,
        postgresql_where=sa.text("is_active"),
        sqlite_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index("uq_connection_tenant_provider", table_name="connections")
    op.create_unique_constraint(
        "uq_connection_tenant_provider", "connections", ["tenant_id", "provider"]
    )
    op.drop_index("uq_connection_tenant_type", table_name="connections")
    op.create_index(
        "uq_connection_tenant_type",
        "connections",
        ["tenant_id", "type"],
        unique=True,
        postgresql_where=sa.text("type != 'payment'"),
        sqlite_where=sa.text("type != 'payment'"),
    )
    op.drop_column("connections", "is_active")
