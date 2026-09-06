"""autocount repair a DB company's never-run entity configs: sql_db, GRN deleted (0.6.0)

Prod incident 2026-09-06: ``seed_company_defaults`` seeded the vendor-API
entity set onto EVERY company on the App Store Update reseed, so a DATABASE
company (source connection = the ``sql_database`` provider) got API-sourced
Customer/Supplier/GRN rows, and the entities list hid "Change source" for it
(AC-01-18) - no UI way out. The seed now stops at a DB company (D13: born
empty, the operator adds entities); this migration runs
``backfill.backfill_db_company_entity_sources`` once for every tenant and
company to repair what the old seed produced: a DB company's
``ac_entity_config`` still at ``autocount_read`` that never ran
(``last_run_at IS NULL`` and no ``ac_watermark`` row with a
``last_modified_at``) becomes ``sql_db`` - except ``goods_received_note``,
which is DELETED together with its ``ac_field_mapping`` rows (GRN has no
database task; a flipped row would only show a dead Configure control).
Anything with run history is left to the operator. Idempotent.

Delivered twice on purpose (same as 0013): this revision covers a deploy,
``bootstrap.update_tenant`` covers the App Store 0.5.0 -> 0.6.0 update path.
The helper joins core ``connections`` (unqualified) READ-ONLY for the provider -
the module never alters a core table. Postgres-only guard, frozen raw SQL,
no commit, live-schema check first (``existing_columns``) so it is a no-op at
a stamp that does not yet carry the tables it names.

Revision ID: 0014_autocount_db_entity_source   (31 chars <= 32)
Revises: 0013_autocount_drop_credit_limit
Create Date: 2026-09-06
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_db_company_entity_sources

revision: str = "0014_autocount_db_entity_source"
down_revision: Union[str, Sequence[str], None] = "0013_autocount_drop_credit_limit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    backfill_db_company_entity_sources(bind, schema=SCHEMA)


def downgrade() -> None:
    # The flipped rows are ordinary, operator-editable entity configs and the
    # source picker offers both values, so there is nothing meaningful to
    # reverse - same stance as 0010-0013.
    pass
