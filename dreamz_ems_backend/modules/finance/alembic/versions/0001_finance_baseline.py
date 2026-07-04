"""finance baseline (sprint-4/05, Cluster D / R3-1) — invoices + invoice_lines in
``app_finance``. create_all of the module metadata (Postgres; SQLite tests use
create_all directly via conftest).

Revision ID: 0001_finance_baseline
Revises:
Create Date: 2026-06-20
"""
import app.models.utc_datetime  # noqa: F401 (UTCDateTime column type)
from alembic import op

revision = "0001_finance_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    import modules.finance.models  # noqa: F401 (register tables on the metadata)
    from modules.finance.db import FinanceBase

    FinanceBase.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    import modules.finance.models  # noqa: F401
    from modules.finance.db import FinanceBase

    FinanceBase.metadata.drop_all(bind=op.get_bind())
