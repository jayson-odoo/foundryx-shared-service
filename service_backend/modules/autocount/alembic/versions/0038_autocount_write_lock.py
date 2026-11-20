"""autocount write-back DB-level busy lock (plan 55 hardening, H2)

Partial unique index ``uq_ac_write_action_one_in_flight`` on
``ac_write_action (tenant_id, company_id, doc_key) WHERE outcome = 'in_flight'``:
two concurrent actions on one document can no longer both pass the busy check.

Existing rows: any document that already has more than one ``in_flight`` row
(only a crashed run can leave one) is repaired first - all but the newest become
``pending_verification`` - so the index can build. Frozen ``sa.table``, never
the live model; never commits (Alembic's own transaction owns that).

Revision ID: 0038_autocount_write_lock   (27 chars <= 32)
Revises: 0037_autocount_key_scopes
Create Date: 2026-11-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0038_autocount_write_lock"
down_revision: Union[str, Sequence[str], None] = "0037_autocount_key_scopes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"
TABLE = "ac_write_action"
INDEX = "uq_ac_write_action_one_in_flight"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    actions = sa.table(
        TABLE,
        sa.column("id", sa.String()),
        sa.column("tenant_id", sa.String()),
        sa.column("company_id", sa.String()),
        sa.column("doc_key", sa.BigInteger()),
        sa.column("outcome", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        schema=SCHEMA,
    )
    rows = bind.execute(
        sa.select(
            actions.c.id, actions.c.tenant_id, actions.c.company_id, actions.c.doc_key
        )
        .where(actions.c.outcome == "in_flight")
        .order_by(actions.c.created_at.desc(), actions.c.id)
    ).all()
    seen = set()
    stale = []
    for row_id, tenant_id, company_id, doc_key in rows:
        key = (tenant_id, company_id, doc_key)
        if key in seen:
            stale.append(row_id)
        seen.add(key)
    if stale:
        bind.execute(
            actions.update().where(actions.c.id.in_(stale)).values(outcome="pending_verification")
        )

    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX} ON {SCHEMA}.{TABLE} "
        f"(tenant_id, company_id, doc_key) WHERE outcome = 'in_flight'"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.{INDEX}")
