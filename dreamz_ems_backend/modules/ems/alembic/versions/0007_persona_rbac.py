"""ems — Cluster E slice 0b (sprint-4/06): Profile-persona RBAC.

Adds the persona tables (``personas``, ``persona_permissions``,
``persona_memberships``) and the optional grant-on-acceptance columns on
``profile_auth_tokens`` (an INVITE may carry a persona+context to grant). New
tables via create_all (checkfirst); the new columns via ADD COLUMN IF NOT
EXISTS so re-runs are safe. Postgres only; SQLite tests use create_all in
conftest.

Revision ID: 0007_persona_rbac
Revises: 0006_profile_auth_tokens
Create Date: 2026-06-21
"""
import app.models.utc_datetime  # noqa: F401
from alembic import op

revision = "0007_persona_rbac"
down_revision = "0006_profile_auth_tokens"
branch_labels = None
depends_on = None

_NEW_TABLES = ("personas", "persona_permissions", "persona_memberships")
_NEW_TOKEN_COLS = ("grant_persona_key", "grant_scope_type", "grant_scope_id")


def upgrade() -> None:
    import modules.ems.models  # noqa: F401
    from modules.ems.db import EmsBase

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for col in _NEW_TOKEN_COLS:
            op.execute(
                f'ALTER TABLE app_ems.profile_auth_tokens '
                f'ADD COLUMN IF NOT EXISTS {col} VARCHAR'
            )
    tables = [EmsBase.metadata.tables[f"app_ems.{n}"] for n in _NEW_TABLES]
    EmsBase.metadata.create_all(bind=bind, tables=tables, checkfirst=True)


def downgrade() -> None:
    import modules.ems.models  # noqa: F401
    from modules.ems.db import EmsBase

    bind = op.get_bind()
    tables = [EmsBase.metadata.tables[f"app_ems.{n}"] for n in reversed(_NEW_TABLES)]
    EmsBase.metadata.drop_all(bind=bind, tables=tables, checkfirst=True)
    if bind.dialect.name == "postgresql":
        for col in _NEW_TOKEN_COLS:
            op.execute(
                f'ALTER TABLE app_ems.profile_auth_tokens DROP COLUMN IF EXISTS {col}'
            )
