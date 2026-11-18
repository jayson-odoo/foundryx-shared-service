"""omnichannel S0 - payload version per webhook endpoint.

Adds ``webhook_endpoints.payload_version`` (nullable integer). NULL means
version 1: the delivery bodies exactly as they were before payload versions
existed. A consumer opts in on its own endpoint; nothing here changes an
existing row.

Online-safe: a nullable column with no default is a catalog-only change on
Postgres (no table rewrite, no backfill). No backfill on purpose: NULL is the
correct value for every existing endpoint (the repo's backfill rule is about
giving existing rows a value they need; here the absence of a value is the
contract).

Idempotent ``ADD COLUMN IF NOT EXISTS`` (same style as
``0022_omni_webchat_profile``); the inspector-guarded non-Postgres branch is
parity only - the module migration orchestrator skips non-Postgres dialects,
so it never runs under pytest (``conftest`` stays on ``create_all``).

Revision ID: 0027_omni_payload_version
Revises: 0026_omni_contact_erasures
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_omni_payload_version"
down_revision = "0026_omni_contact_erasures"
branch_labels = None
depends_on = None

SCHEMA = "app_omnichannel"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f'ALTER TABLE "{SCHEMA}".webhook_endpoints '
            "ADD COLUMN IF NOT EXISTS payload_version INTEGER"
        )
    else:
        inspector = sa.inspect(bind)
        cols = {c["name"] for c in inspector.get_columns("webhook_endpoints", schema=SCHEMA)}
        if "payload_version" not in cols:
            with op.batch_alter_table("webhook_endpoints", schema=SCHEMA) as batch_op:
                batch_op.add_column(sa.Column("payload_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            f'ALTER TABLE "{SCHEMA}".webhook_endpoints DROP COLUMN IF EXISTS payload_version'
        )
    else:
        with op.batch_alter_table("webhook_endpoints", schema=SCHEMA) as batch_op:
            batch_op.drop_column("payload_version")
