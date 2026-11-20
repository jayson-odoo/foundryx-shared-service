"""Document line linkage backfill (sprint-5/06 slice S2, AC-06-16..19)

Every existing ``purchase_order``/``shipping_order`` task predates the
FromSO*/FromPO* line-linkage fields (AC-06-01..15, this branch's slice S1):
its mapping rows never carry the six link targets, and its stored
``query``/``lineQuery``/``fingerprintQuery`` never select the columns the
NEW preset text needs. This migration ships the repair for every EXISTING
task, via ``backfill_document_line_linkage`` (see that function's own
docstring, ``modules/autocount/backfill.py``), for every PO/SPO
``ac_entity_config`` row across every tenant:

* skips a task with ZERO existing line-scope rows entirely (review round S2)
  - that state hands off to ``EtlService.update_task``'s own first-save
  preset seed instead, which now carries the six rows itself;
* otherwise adds the six not-required ``FromSO*``/``FromPO*`` line mapping
  rows of AC-06-14 when a row for that target is not already there (an
  operator's own row for the same target, in any state, is left alone) -
  ENABLED only when THIS pass also rewrote ``lineQuery`` (review round B1:
  an enabled row referencing a column the query does not yet select 422s
  the very next Mapping-tab save), disabled otherwise;
* when a statement is byte-identical to the OLD preset text (own company's
  ``database_name`` substituted), replaces it with the NEW text; when the
  header ``query`` is replaced this way, the four aggregate names of
  AC-06-13 are appended to ``result_columns``; when ``lineQuery`` is
  replaced this way, the seven names it newly selects are appended to
  ``line_result_columns`` in the SAME update (review round B1) - the
  compared-column set a paged run's change-detection hash derives from
  ``result_columns``, so without the header half the newly-selected link
  columns never enter the hash and a document whose only change is a newly
  populated link would never re-stage. A customised statement is left
  untouched with a WARNING naming the config id; the mapping rows above
  still land regardless (for a task the zero-row skip above did not already
  exclude).

No column is added here - every field this migration touches already lives
on ``ac_entity_config``/``ac_field_mapping`` (``source_config``,
``result_columns``, the mapping row columns); this is pure DATA, the same
shape as 0016's ``backfill_shipping_order_container_number`` and 0017's
``backfill_document_fingerprint_queries``.

    !!  EVERY REWRITTEN PO/SPO RE-STAGES ONCE AFTER DEPLOY - INTENDED.  !!
Appending the four aggregate names to a task's ``result_columns`` changes
that header row's own hash (the change-detection engine has no special
knowledge of any one column), so the very next run re-offers every PO/SPO
whose statements were rewritten as an update carrying its line linkage.
This is the intended one-time cost of picking up columns that were never
selected before - see the plan's backfill runbook (section 2.4) for the
deploy-order sequencing (PO task first, then SPO).

    !!  DEPLOY ORDER: SORENTO CONTRACT 2.2 MUST BE LIVE FIRST.  !!
The re-staged family pushes with the FIVE new wire fields on it
(AC-06-23) - if the receiving Sorento does not yet declare them,
``extra="forbid"`` there quarantines every one of them.

    !!  FROZEN ``sa.table`` BACKFILL - NEVER THE LIVE ORM MODEL.  !!
Same rule, same incident, as 0016/0017 (module Alembic 0006,
``documentation/engineering/storage-and-background-jobs.md`` - it queried
the live ``AcCompany`` model from inside a migration and raised
``UndefinedColumn`` on a fresh ``0001`` -> head replay once a LATER
migration added a column the model had already grown to expect).
``backfill_document_line_linkage`` therefore selects/inserts/updates
through frozen ``sa.table`` snapshots naming only the columns it actually
needs, and is schema-tolerant on its own (``existing_columns`` first) -
the module docstring's "test the FUNCTION directly" rule is why this is a
plain function at all, not inline here. It does not commit; Alembic's own
connection/transaction owns that, as always.

Revision ID: 0018_autocount_line_linkage   (27 chars <= 32)
Revises: 0017_autocount_fingerprint
Create Date: 2026-09-08
"""
from typing import Sequence, Union

from alembic import op

from modules.autocount.backfill import backfill_document_line_linkage

revision: str = "0018_autocount_line_linkage"
down_revision: Union[str, Sequence[str], None] = "0017_autocount_fingerprint"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    backfill_document_line_linkage(bind, schema="app_autocount")


def downgrade() -> None:
    # The mapping rows and rewritten statements this migration adds/repairs
    # are left in place on downgrade - they are ordinary operator-editable
    # `ac_field_mapping`/`ac_entity_config` state now, no different from an
    # operator's own edit; nothing to reverse (same posture as 0016/0017).
    pass
