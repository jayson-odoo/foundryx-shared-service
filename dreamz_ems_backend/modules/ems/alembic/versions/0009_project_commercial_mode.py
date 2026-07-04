"""ems — Cluster F slice 4 (sprint-4/07): project commercial mode + fee config.

Adds ``projects.commercial_mode`` (default SELF_RUN) / ``fee_type`` / ``fee_value``
(AC-07-45). Existing projects backfill to SELF_RUN (the column default + an
explicit UPDATE for any NULL), so they produce no settlement until set to AGENCY.

Also backfills the Eligible→Pending Payment drop AUTO edge onto every existing
SCOPED participant graph (AC-07-44/53) — seed-if-absent does NOT repair an
existing scoped graph. Postgres only; SQLite tests use create_all + the in-tenant
update_tenant self-heal (which runs the same backfill helper).

Revision ID: 0009_project_commercial
Revises: 0008_project_payment_conn
Create Date: 2026-06-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0009_project_commercial"
down_revision = "0008_project_payment_conn"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE app_ems.projects "
        "ADD COLUMN IF NOT EXISTS commercial_mode VARCHAR NOT NULL DEFAULT 'SELF_RUN'"
    )
    op.execute("ALTER TABLE app_ems.projects ADD COLUMN IF NOT EXISTS fee_type VARCHAR")
    op.execute("ALTER TABLE app_ems.projects ADD COLUMN IF NOT EXISTS fee_value DOUBLE PRECISION")
    # Defensive backfill — any pre-existing NULL → SELF_RUN (AC-07-45/53).
    op.execute("UPDATE app_ems.projects SET commercial_mode = 'SELF_RUN' WHERE commercial_mode IS NULL")

    # Participant scoped-graph drop-edge backfill (AC-07-44/53).
    from sqlalchemy.orm import Session

    from modules.ems.bootstrap import _backfill_participant_drop_edge

    sess = Session(bind=bind)
    tenant_ids = [
        r[0]
        for r in sess.execute(
            sa.text(
                "SELECT DISTINCT tenant_id FROM public.statuses "
                "WHERE entity_type = 'project_participant' AND scope_id IS NOT NULL"
            )
        )
    ]
    for tid in tenant_ids:
        _backfill_participant_drop_edge(sess, tid)
    sess.flush()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE app_ems.projects DROP COLUMN IF EXISTS fee_value")
    op.execute("ALTER TABLE app_ems.projects DROP COLUMN IF EXISTS fee_type")
    op.execute("ALTER TABLE app_ems.projects DROP COLUMN IF EXISTS commercial_mode")
