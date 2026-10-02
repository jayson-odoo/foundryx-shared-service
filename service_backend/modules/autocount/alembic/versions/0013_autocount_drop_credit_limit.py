"""autocount disable enabled customer credit_limit mapping rows (sprint-5/04)

Sorento contract 2.1 removed ``credit_limit`` from ``customers``
(``PLAN-autocount-cross-repo-contract.md`` section 10, D15: ``extra="forbid"``
rejects a payload naming it), so ``CanonicalCustomer.SINK_FIELDS`` no longer
carries it and a tenant's already-saved ENABLED customer row targeting
``credit_limit`` is a dead row - mapped, never sent, invisible in the editor,
pruned on the next save. This migration runs
``backfill.backfill_disable_credit_limit_mapping_rows`` once for every
tenant/company so the stored mapping table matches the accepted target set
WITHOUT waiting for each operator's next save (customer rows only; a row of
another entity type sharing the name is untouched; idempotent).

Delivered twice on purpose: this revision covers a deploy (module Alembic
runs at container start) and ``bootstrap.update_tenant`` covers the App
Store 0.4.0 -> 0.5.0 update path. Both call the same helper.

Same discipline as 0012: Postgres-only guard, a frozen raw-SQL helper (never
the ORM model), no commit - Alembic owns the single transaction and the
stamp. The helper inspects the live table first (``backfill.existing_
columns``), so it is a no-op at any stamp whose ``ac_field_mapping`` does not
yet carry the columns it names (the 2026-09-06 prod lesson: a backfill runs
at ANY point in the chain, not just the day it was written).

Revision ID: 0013_autocount_drop_credit_limit   (32 chars <= 32)
Revises: 0012_autocount_disable_stale
Create Date: 2026-09-06
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_disable_credit_limit_mapping_rows

revision: str = "0013_autocount_drop_credit_limit"
down_revision: Union[str, Sequence[str], None] = "0012_autocount_disable_stale"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "app_autocount"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    backfill_disable_credit_limit_mapping_rows(bind, schema=SCHEMA)


def downgrade() -> None:
    # A disabled row is still an ordinary, editable ac_field_mapping row and
    # ``credit_limit`` is no longer a target the editor can offer, so there is
    # nothing meaningful to reverse - same stance as 0010/0011/0012.
    pass
