"""autocount — backfill missing entity configs for pre-existing companies

``seed_company_defaults`` runs ONLY when a company is discovered. A company
created before the masters slices (14-16) therefore has only a
``goods_received_note`` ``ac_entity_config`` row — supplier/customer never
appeared for it, so the Entities list shows GRN alone even though the code now
supports all three (this is exactly what prod showed: masters live in code, but
the pre-existing company was stranded on GRN). Neither ``create_all`` nor the
envelope backfill (0003) CREATES a missing entity row — recurring-gap #2: a new
entity on existing records needs a real backfill, not seed-on-create.

This backfill ensures every existing ``ac_company`` has a config row for every
entity in ``SEEDED_ENTITIES`` (GRN, supplier, customer) plus its DEFAULT mapping
rows, via ``seed_company_defaults`` — which is **insert-if-missing**: it adds a
config only when absent and mapping rows only when the entity has none, so an
operator's existing GRN config and any edited mappings are NEVER touched.
Idempotent — re-running skips whatever already exists.

    !!  Data backfill — must NOT commit Alembic's own connection.  !!
Runs on a ``Session`` bound to ``op.get_bind()`` and only FLUSHES; it never
commits and never closes the session. Alembic owns the single per-migration
transaction AND the ``alembic_version`` stamp — a mid-migration ``commit()`` (or
a per-batch commit on a side connection) corrupts that stamp on live Postgres
(the storage-migration slice learned this the hard way). ``seed_company_defaults``
+ its repositories are already commit-free (``add`` → ``flush``), so reusing the
real seeding logic here keeps the mapping defaults in ONE place (no SQL twin to
drift) while staying inside Alembic's transaction.

    !!  Invisible to pytest — module Alembic is a Postgres-only no-op and
        conftest is pure ``create_all``. The only gates are code review and a
        real ``alembic upgrade head`` / a deploy. Verified locally against
        Postgres before shipping (a GRN-only company gained supplier+customer).  !!

Revision ID: 0006_autocount_entity_backfill   (30 chars ≤ 32)
Revises: 0005_autocount_mapping_formula
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.orm import Session

# Revision ids MUST be <= 32 chars — ``alembic_version.version_num`` is
# VARCHAR(32). "0006_autocount_entity_backfill" is 30.
revision: str = "0006_autocount_entity_backfill"
down_revision: Union[str, Sequence[str], None] = "0005_autocount_mapping_formula"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # The module's tables live in the ``app_autocount`` schema — module Alembic
    # only runs on Postgres; a no-op elsewhere keeps the SQLite test path clean.
    if bind.dialect.name != "postgresql":
        return

    # Lazy import so a module-load hiccup can only fail THIS migration, never the
    # whole alembic env; and so the backfill reuses the real seeding logic.
    from modules.autocount.models import AcCompany
    from modules.autocount.services.company_service import CompanyService

    # Bound to Alembic's connection: queries + inserts ride the migration's
    # transaction. FLUSH only — no commit, no close (see the header note).
    session = Session(bind=bind)
    service = CompanyService(session)
    for company in session.query(AcCompany).all():
        service.seed_company_defaults(company.tenant_id, company.id)
    session.flush()


def downgrade() -> None:
    # Not reversibly meaningful: a seeded config may already carry operator edits
    # or synced data. No-op — deliberately leaves the backfilled rows in place.
    pass
