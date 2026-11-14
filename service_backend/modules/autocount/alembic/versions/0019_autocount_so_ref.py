"""SO `Ref` (project label) backfill (sprint-5/07, AC-07-07..12)

Every existing ``sales_order`` task predates ``h.Ref AS Ref`` on the header
query and the ``Ref -> ref`` mapping row: this migration ships the repair
for every EXISTING task, via ``backfill_sales_order_ref`` (see that
function's own docstring, ``modules/autocount/backfill.py``), for every
``sales_order`` ``ac_entity_config`` row across every tenant:

* a query byte-identical to the OLD preset text (own company's
  ``database_name`` substituted) is rewritten to the NEW text (``h.Ref AS
  Ref`` added right after ``h.Note AS Note``) and ``"Ref"`` is appended to
  ``result_columns``; a query already at the NEW text is skipped silently;
* a ``Ref -> ref`` header mapping row (transform ``string``, not required,
  source-owned, next ``sort_order``) is created the moment none exists yet
  in ANY state - an operator's own row, enabled or disabled, is never
  duplicated or modified. ENABLED when the query was just rewritten to the
  NEW preset text OR the stored query already selects ``Ref`` on its own;
  DISABLED (with one WARNING naming the config id) otherwise - the
  production ``AED_SORENTO`` shape, whose query the backfill leaves byte-
  untouched (splicing an operator-authored statement is exactly the kind of
  silent edit the 0016 review rejected - see the plan's operator runbook,
  section 2.4, for the one-line fix).

No column is added here - every field this migration touches already lives
on ``ac_entity_config``/``ac_field_mapping`` (``source_config``,
``result_columns``, the mapping row columns); this is pure DATA, the same
shape as 0016's ``backfill_shipping_order_container_number``, 0017's
``backfill_document_fingerprint_queries`` and 0018's
``backfill_document_line_linkage``.

    !!  EVERY REWRITTEN SO TASK RE-STAGES ONCE AFTER DEPLOY - INTENDED.  !!
Appending ``"Ref"`` to a task's ``result_columns`` changes that header row's
own hash (the change-detection engine has no special knowledge of any one
column), so the very next run re-offers every SO whose non-empty ``Ref``
changed the hash as an update carrying its project label - see the plan's
backfill runbook (section 2.4) for the deploy-order sequencing.

    !!  DEPLOY ORDER: SORENTO MUST ACCEPT `ref` FIRST.  !!
Sorento's ``extra="forbid"`` rejects every SO record carrying ``ref`` until
their project-label PR is deployed (plan section 2.6) - the production
``Sorento`` task's row lands DISABLED by this migration (its query is
customised, so `ref` never leaves the ESB from it until the operator runbook
step is done); ``ac_sim`` (a simulation company) swaps to the NEW preset
text immediately and starts sending `ref` on its next push.

    !!  FROZEN ``sa.table`` BACKFILL - NEVER THE LIVE ORM MODEL.  !!
Same rule, same incident, as 0016/0017/0018 (module Alembic 0006,
``documentation/engineering/storage-and-background-jobs.md`` - it queried
the live ``AcCompany`` model from inside a migration and raised
``UndefinedColumn`` on a fresh ``0001`` -> head replay once a LATER
migration added a column the model had already grown to expect).
``backfill_sales_order_ref`` therefore selects/inserts/updates through
frozen ``sa.table`` snapshots naming only the columns it actually needs, and
is schema-tolerant on its own (``existing_columns`` first). It does not
commit; Alembic's own connection/transaction owns that, as always.

Revision ID: 0019_autocount_so_ref   (21 chars <= 32)
Revises: 0018_autocount_line_linkage
Create Date: 2026-09-10
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_sales_order_ref

revision: str = "0019_autocount_so_ref"
down_revision: Union[str, Sequence[str], None] = "0018_autocount_line_linkage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    backfill_sales_order_ref(bind, schema="app_autocount")


def downgrade() -> None:
    # The mapping row and rewritten statement this migration adds/repairs
    # are left in place on downgrade - ordinary operator-editable
    # `ac_field_mapping`/`ac_entity_config` state now, no different from an
    # operator's own edit; nothing to reverse (same posture as 0016/0017/0018).
    pass
