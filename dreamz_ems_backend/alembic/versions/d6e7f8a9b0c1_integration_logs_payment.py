"""core — payment-gateway webhook log + relax connection one-per-type for payment.

sprint-4/07 Cluster F slice 3 (AC-07-24/28/30):
- ``integration_logs`` table (idempotency ledger + masked webhook audit trail,
  ``UNIQUE(tenant_id, provider, external_event_id)``).
- Relax the connection ``UNIQUE(tenant_id, type)`` to a PARTIAL unique index that
  EXCLUDES ``type='payment'`` (a tenant may hold Stripe + Billplz; same-provider
  duplicates stay blocked by the existing (tenant, provider) unique).

Revision ID: d6e7f8a9b0c1  (≤ 32 chars — alembic_version is VARCHAR(32))
Revises: c4d5e6f7a8b9
Create Date: 2026-06-23
"""
import app.models.utc_datetime  # noqa: F401 (UTCDateTime column type)
import sqlalchemy as sa
from alembic import op

revision = "d6e7f8a9b0c1"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # ── integration_logs ──
    if "integration_logs" not in insp.get_table_names():
        op.create_table(
            "integration_logs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("connection_id", sa.String(), nullable=True, index=True),
            sa.Column("provider", sa.String(), nullable=False, index=True),
            sa.Column("external_event_id", sa.String(), nullable=True),
            sa.Column("event_type", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="RECEIVED"),
            sa.Column("request_json", sa.JSON(), nullable=True),
            sa.Column("response_json", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "tenant_id", "provider", "external_event_id", name="uq_integration_log_event"
            ),
        )

    # ── relax connection one-per-type for payment ──
    if bind.dialect.name != "postgresql":
        return  # SQLite tests build the partial index off the model in create_all
    # Drop the old full UNIQUE constraint (named in the original migration) if
    # present, then add a partial unique index excluding payment.
    existing = {c["name"] for c in insp.get_unique_constraints("connections")}
    if "uq_connection_tenant_type" in existing:
        op.drop_constraint("uq_connection_tenant_type", "connections", type_="unique")
    idx_names = {i["name"] for i in insp.get_indexes("connections")}
    if "uq_connection_tenant_type" not in idx_names:
        op.create_index(
            "uq_connection_tenant_type",
            "connections",
            ["tenant_id", "type"],
            unique=True,
            postgresql_where=sa.text("type <> 'payment'"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("integration_logs")
    if bind.dialect.name != "postgresql":
        return
    insp = sa.inspect(bind)
    idx_names = {i["name"] for i in insp.get_indexes("connections")}
    if "uq_connection_tenant_type" in idx_names:
        op.drop_index("uq_connection_tenant_type", table_name="connections")
    op.create_unique_constraint(
        "uq_connection_tenant_type", "connections", ["tenant_id", "type"]
    )
