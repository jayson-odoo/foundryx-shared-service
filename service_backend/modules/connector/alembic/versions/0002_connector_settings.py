"""connector settings in the database (lane SETTINGS-IN-DB-SS).

Adds "product_settings", "tenant_settings", "settings_audit" (schema
app_connector). Idempotent (skips an existing table) because the module's
global install also runs create_all at boot. Postgres-only, like the baseline.

Revision ID: 0002_connector_settings
Revises: 0001_connector_baseline
Create Date: 2026-10-10
"""

from __future__ import annotations
from alembic import op

revision = "0002_connector_settings"
down_revision = "0001_connector_baseline"
branch_labels = None
depends_on = None

SCHEMA = "app_connector"


def _has(bind, name: str) -> bool:
    import sqlalchemy as sa

    return sa.inspect(bind).has_table(name, schema=SCHEMA)


def upgrade() -> None:
    """Columns are spelled out (not taken from the live models) so a later
    ADD COLUMN migration never collides with this one on a fresh database."""
    import sqlalchemy as sa

    from app.models.utc_datetime import UTCDateTime

    bind = op.get_bind()
    if not _has(bind, "product_settings"):
        op.create_table(
            "product_settings",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("key", sa.String(32), nullable=False, unique=True),
            sa.Column("display_name", sa.String(120), nullable=True),
            sa.Column("connection_id", sa.String(128), nullable=True),
            sa.Column("consent_url", sa.Text(), nullable=True),
            sa.Column("api_base_url", sa.Text(), nullable=True),
            sa.Column("issuer", sa.String(128), nullable=True),
            sa.Column("consent_audience", sa.String(128), nullable=True),
            sa.Column("call_audience", sa.String(128), nullable=True),
            sa.Column("secrets_encrypted", sa.Text(), nullable=True),
            sa.Column("updated_by", sa.String(), nullable=True),
            sa.Column("updated_at", UTCDateTime(), nullable=True),
            sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
            schema=SCHEMA,
        )
    if not _has(bind, "tenant_settings"):
        op.create_table(
            "tenant_settings",
            sa.Column("tenant_id", sa.String(), primary_key=True),
            sa.Column("public_base_url", sa.Text(), nullable=True),
            sa.Column("allowed_client_cidrs", sa.Text(), nullable=True),
            sa.Column("redirect_allowlist", sa.Text(), nullable=True),
            sa.Column("manifest_ttl_seconds", sa.Integer(), nullable=True),
            sa.Column("call_timeout_seconds", sa.Integer(), nullable=True),
            sa.Column("call_log_retention_days", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.String(), nullable=True),
            sa.Column("updated_at", UTCDateTime(), nullable=True),
            schema=SCHEMA,
        )
    if not _has(bind, "settings_audit"):
        op.create_table(
            "settings_audit",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=False, index=True),
            sa.Column("actor_user_id", sa.String(), nullable=True),
            sa.Column("target", sa.String(64), nullable=False),
            sa.Column("action", sa.String(16), nullable=False),
            sa.Column("fields", sa.JSON(none_as_null=True), nullable=True),
            sa.Column("created_at", UTCDateTime(), server_default=sa.func.now(), nullable=False),
            schema=SCHEMA,
        )


def downgrade() -> None:
    bind = op.get_bind()
    for name in ("settings_audit", "tenant_settings", "product_settings"):
        if _has(bind, name):
            op.drop_table(name, schema=SCHEMA)
