"""finance money Float → Numeric(14,4) (sprint-4/07, Cluster F / AC-07-01).

Exact decimal money — invoices.{subtotal,tax,total} + invoice_lines.{unit_price,
tax,amount}. ``USING col::numeric(14,4)`` preserves existing values (total=12.5
reads 12.5000 post-migration). Postgres only (the SQLite test suite uses
create_all off the updated model, so the column type is already Numeric there).

Revision ID: 0002_finance_money_numeric  (≤ 32 chars — alembic_version is VARCHAR(32))
Revises: 0001_finance_baseline
Create Date: 2026-06-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_finance_money_numeric"
down_revision = "0001_finance_baseline"
branch_labels = None
depends_on = None

SCHEMA = "app_finance"

_MONEY_COLUMNS = [
    ("invoices", "subtotal"),
    ("invoices", "tax"),
    ("invoices", "total"),
    ("invoice_lines", "unit_price"),
    ("invoice_lines", "tax"),
    ("invoice_lines", "amount"),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite tests use create_all off the updated model
    for table, col in _MONEY_COLUMNS:
        op.alter_column(
            table,
            col,
            type_=sa.Numeric(14, 4),
            existing_type=sa.Float(),
            existing_nullable=False,
            schema=SCHEMA,
            postgresql_using=f"{col}::numeric(14,4)",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table, col in _MONEY_COLUMNS:
        op.alter_column(
            table,
            col,
            type_=sa.Float(),
            existing_type=sa.Numeric(14, 4),
            existing_nullable=False,
            schema=SCHEMA,
            postgresql_using=f"{col}::double precision",
        )
