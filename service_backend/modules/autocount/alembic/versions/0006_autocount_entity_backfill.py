"""autocount - backfill missing entity configs for pre-existing companies (NO-OP)

    !!  UPGRADE IS NOW A DOCUMENTED NO-OP (prod incident, 2026-09-06).  !!

This migration originally ran ``seed_company_defaults`` through the LIVE
ORM/``CompanyService`` for every ``ac_company`` row, so that a company created
before the masters slices (14-16) gained the supplier/customer entity configs
it was missing (see the history below - the incident this fixed was real and
the seeding still needs to happen). The problem is WHEN it ran: as migration
0006, on a connection stamped strictly BEFORE 0007/0008/0010 - but
``CompanyService``/``AcCompany`` import the CURRENT models, which by 2026-09
carry ``sorento_company_code`` (0007), the ETL columns (0007/0008) and the
line-mapping columns (0010). ``session.query(AcCompany)`` against a 0006-stamp
table hits every one of those as ``UndefinedColumn`` - a data migration that
queries the LIVE ORM is only ever correct for the ONE stamp its author was
looking at when they wrote it, not for a chain replayed from scratch months
later against a newer model. This is exactly what got a real production
database stuck stamped before 0007 (App Store showed 0.1.0): 0006 raised,
``bootstrap_modules`` swallowed the failure, and the container went "healthy"
with the module frozen at 0.1.0 and every AutoCount write 500ing.

The fix is to never let a data migration reach through the live ORM at all -
the house rule (see ``documentation/engineering/storage-and-background-jobs.md``
migration lessons) is that a data migration that MUST stay queries a FROZEN
``sa.table(...)`` snapshot of the columns it actually needs, never the live
model, so it keeps working no matter how many later migrations add columns.
Retrofitting that snapshot here would only recreate the SAME seeding logic
``CompanyService.seed_company_defaults`` already owns, with a second copy to
keep in sync - so instead this migration's ``upgrade()`` becomes a no-op:

* The gap this migration existed to close - a pre-existing company stranded
  on GRN only - is closed a different, ORM-safe way: ``update_tenant``
  (``modules/autocount/bootstrap.py``) calls ``seed_company_defaults`` for
  every one of the tenant's companies as its OWN seed-if-absent loop, at
  HEAD (every column exists), and ``seed_company_defaults`` also runs when a
  company is created. That loop is NOT part of the deploy: nothing in
  ``bootstrap_modules`` calls ``update_tenant`` (``tenant_has_data()``
  returns False, so ``_backfill_tenant_modules`` never reaches it either).
  It fires only from ``AppStoreService.update()`` - an operator clicking
  Services > AutoCount > Update - and only while that tenant's
  ``installed_version`` is below the manifest version
  (``app_store_service.py:175`` raises "already up to date" otherwise).
  Verified on Postgres by review: rows seeded at 0002, replay 0003->0012,
  supplier/customer configs ABSENT until that Update runs.

      !!  REQUIRED POST-DEPLOY OPERATOR STEP  !!
  For every tenant whose companies predate the masters slices: Services >
  AutoCount > Update, while the version window is open. The window closes
  the moment ``installed_version`` reaches the manifest version by ANY route
  (an update taken for an unrelated reason, a fresh install at the current
  version); after that only creating a company seeds, and an existing
  stranded company needs ``seed_company_defaults`` re-run by hand.
* The revision itself, its id and its position in the chain are UNCHANGED -
  a database already stamped 0006 (this migration having run successfully
  before the incident, on a chain that had not yet added 0007-0010) is not
  re-run and does not need repair; a database stuck BEFORE 0006, or replaying
  0001->head from nothing, now passes through 0006 doing nothing and is
  seeded by the operator's next App Store Update instead of dying here.

Revision ID: 0006_autocount_entity_backfill   (30 chars <= 32)
Revises: 0005_autocount_mapping_formula
Create Date: 2026-07-25
"""
from typing import Sequence, Union

# Revision ids MUST be <= 32 chars - ``alembic_version.version_num`` is
# VARCHAR(32). "0006_autocount_entity_backfill" is 30.
revision: str = "0006_autocount_entity_backfill"
down_revision: Union[str, Sequence[str], None] = "0005_autocount_mapping_formula"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op (see the module docstring). The masters backfill this migration
    used to perform now happens at HEAD, via ``update_tenant``'s own
    seed-if-absent loop over ``seed_company_defaults`` - safe at every stamp,
    because it runs against the CURRENT schema, never a frozen one reached
    through the live ORM."""
    return None


def downgrade() -> None:
    # Not reversibly meaningful: a seeded config may already carry operator edits
    # or synced data. No-op - deliberately leaves the backfilled rows in place.
    pass
