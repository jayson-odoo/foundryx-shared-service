"""omnichannel baseline (sprint-3/10 D3) — adopt per-module Alembic.

Captures the current ``app_omnichannel`` schema as rev 1. Existing DBs (tables
already built by the legacy ``create_all``) are STAMPED to this rev (no DDL);
fresh DBs run ``upgrade`` which builds the schema + tables here. Future
omnichannel schema changes get their own revisions chaining from this one.

Revision ID: 0001_omni_baseline
Revises:
Create Date: 2026-06-16
"""
from alembic import op

revision = "0001_omni_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Baseline = the current schema. Build it from the module's metadata so we
    # never hand-transcribe ~20 tables; fresh DBs get the exact create_all shape,
    # existing DBs are stamped (this body never runs for them).
    from sqlalchemy import text

    from modules.omnichannel.db import OMNI_SCHEMA, OmniBase

    bind = op.get_bind()
    bind.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{OMNI_SCHEMA}"'))
    OmniBase.metadata.create_all(bind=bind)


def downgrade() -> None:
    from modules.omnichannel.db import OmniBase

    OmniBase.metadata.drop_all(bind=op.get_bind())
