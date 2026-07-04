"""ems — Cluster E slice 0a (sprint-4/06): Profile Portal auth tokens.

Adds the ``profile_auth_tokens`` table (single-use, expiring SET_PASSWORD + OTP
secrets for Profile portal authentication). New table via create_all
(checkfirst). Postgres only; SQLite tests use create_all in conftest.

Revision ID: 0006_profile_auth_tokens
Revises: 0005_ticket_status_checkpoints
Create Date: 2026-06-21
"""
import app.models.utc_datetime  # noqa: F401
from alembic import op

revision = "0006_profile_auth_tokens"
down_revision = "0005_ticket_status_checkpoints"
branch_labels = None
depends_on = None

_NEW_TABLES = ("profile_auth_tokens",)


def upgrade() -> None:
    import modules.ems.models  # noqa: F401
    from modules.ems.db import EmsBase

    bind = op.get_bind()
    tables = [EmsBase.metadata.tables[f"app_ems.{n}"] for n in _NEW_TABLES]
    EmsBase.metadata.create_all(bind=bind, tables=tables, checkfirst=True)


def downgrade() -> None:
    import modules.ems.models  # noqa: F401
    from modules.ems.db import EmsBase

    bind = op.get_bind()
    tables = [EmsBase.metadata.tables[f"app_ems.{n}"] for n in reversed(_NEW_TABLES)]
    EmsBase.metadata.drop_all(bind=bind, tables=tables, checkfirst=True)
