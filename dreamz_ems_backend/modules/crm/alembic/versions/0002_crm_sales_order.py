"""crm sales order (sprint-4/07, Cluster F slice 2) — sales_orders +
sales_order_lines in ``app_crm``. New tables → create_all of the module metadata
(idempotent; the baseline already created the rest). No legacy rows to backfill.

Revision ID: 0002_crm_sales_order
Revises: 0001_crm_baseline
Create Date: 2026-06-23
"""
import app.models.utc_datetime  # noqa: F401 (UTCDateTime column type)
from alembic import op

revision = "0002_crm_sales_order"
down_revision = "0001_crm_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from modules.crm.db import CrmBase
    import modules.crm.models  # noqa: F401 (register tables on the metadata)

    # create_all is idempotent — it skips existing tables and creates only the new
    # sales_orders / sales_order_lines.
    CrmBase.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from modules.crm.models import SalesOrder, SalesOrderLine

    bind = op.get_bind()
    SalesOrderLine.__table__.drop(bind=bind, checkfirst=True)
    SalesOrder.__table__.drop(bind=bind, checkfirst=True)
