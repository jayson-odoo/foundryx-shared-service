"""crm baseline (sprint-4/08) — clients + leads + quotations + quotation_lines in
``app_crm``. create_all of the module metadata (Postgres; SQLite tests use
create_all directly via conftest).

Revision ID: 0001_crm_baseline
Revises:
Create Date: 2026-06-20
"""
import app.models.utc_datetime  # noqa: F401 (UTCDateTime column type)
from alembic import op

revision = "0001_crm_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from modules.crm.db import CrmBase
    import modules.crm.models  # noqa: F401 (register tables on the metadata)

    CrmBase.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from modules.crm.db import CrmBase
    import modules.crm.models  # noqa: F401

    CrmBase.metadata.drop_all(bind=op.get_bind())
