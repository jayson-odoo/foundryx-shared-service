"""SPO container_number backfill (feat/spo-container-number)

Sorento held 68,519 SPO allocations with no container because the SPO
task's header query never selected AutoCount ``PO.Ref`` at all, on any
tenant (live samples "WHSU6476731 (MOCHA)", "CMAU7650091" prove the column
carries real container numbers). ``presets._PO_HEADER_QUERY`` now selects
``h.Ref AS Ref`` and ``SPO_PRESET.header`` gains a ``Ref -> container_number``
row for a BRAND NEW task's first save - this migration is the repair for
every task that predates that change.

No column is added here - `container_number` lives on the CANONICAL model
(``CanonicalShippingOrder``), never a database column. What this migration
DOES do, via ``backfill_shipping_order_container_number`` (see that
function's own docstring, ``modules/autocount/backfill.py``), for every
EXISTING ``shipping_order`` ``ac_entity_config`` row across every tenant:

* add an enabled ``Ref -> container_number`` header mapping row when one is
  not already there (an operator's own row, in any state, is left alone);
* when the stored header query is byte-identical to the OLD preset text
  (with the task's own company's database name substituted), replace it
  with the NEW text and add ``"Ref"`` to ``result_columns`` - the compared-
  column set a paged run's change detection hashes derives from
  ``result_columns``, so without this a document whose only change is a
  newly populated ``Ref`` would never re-stage; a customised query is left
  untouched with a warning naming the config id.

    !!  EVERY SPO RE-STAGES ONCE AFTER DEPLOY - INTENDED.  !!
Adding ``Ref`` to a task's ``result_columns`` changes that header row's own
hash (the change-detection engine has no special knowledge of any one
column - see ``presets.py``'s own "LINE FINGERPRINT" note for the same
mechanism), so the very next run re-offers every SPO as an update carrying
its container number. This is the intended one-time cost of picking up a
column that was never selected before.

    !!  ORM-LEVEL BACKFILL (matches 0010's own precedent).  !!
``backfill_shipping_order_container_number`` builds/edits rows, not a bare
column UPDATE - a natural ORM operation, run on a ``Session(bind=op.get_bind())``
sharing Alembic's own transaction/connection so Alembic's own commit at the
end is the only commit (the storage-migration lesson: a migration must
never commit Alembic's own connection). The function is schema-tolerant on
its own (``existing_columns`` first) - the module docstring's "test the
FUNCTION directly" rule is why this is a plain function at all, not inline
here.

Revision ID: 0016_autocount_spo_container   (29 chars <= 32)
Revises: 0015_autocount_run_requests
Create Date: 2026-09-07
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.orm import Session

from modules.autocount.backfill import backfill_shipping_order_container_number

revision: str = "0016_autocount_spo_container"
down_revision: Union[str, Sequence[str], None] = "0015_autocount_run_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    session = Session(bind=bind)
    try:
        backfill_shipping_order_container_number(session, schema="app_autocount")
        session.flush()
    finally:
        session.close()


def downgrade() -> None:
    # The mapping rows and rewritten queries this migration adds/repairs are
    # left in place on downgrade - they are ordinary operator-editable
    # `ac_field_mapping`/`ac_entity_config` state now, no different from an
    # operator's own edit; nothing to reverse (same posture as 0010).
    pass
