"""Sprint-5/10 S3+S4 review round 2 - MUST-FIX 5 (item 5, AC-10-25's 90-day
audit prune): ``ac_pull_audit`` had no index on ``created_at`` at all - the
retention sweep (``prune_pull_snapshots``'s own
``PullAuditRepository.delete_older_than``) full-scans the table forever as
it grows. Migration 0021 (unreleased - the only stamped host is the lane
Postgres) is amended IN PLACE to add ``ix_ac_pull_audit_created_at``,
mirroring the ORM's own new ``Index`` in ``__table_args__`` - the exact
"amend the in-flight revision, never a follow-up migration" precedent
migration 0020's own SHOULD-FIX 4 docstring already sets on this branch.

RED before the fix: ``AcPullAudit.__table__`` carries no index whose column
set is exactly ``{created_at}``, and this suite's own ``create_all`` mints
none either.
"""
from __future__ import annotations

import sqlalchemy as sa

from modules.autocount.models import AcPullAudit


def _indexes_covering(table: sa.Table, column_name: str) -> list:
    return [
        ix for ix in table.indexes
        if {c.name for c in ix.columns} == {column_name}
    ]


def test_orm_declares_an_index_for_ac_pull_audit_created_at():
    covering = _indexes_covering(AcPullAudit.__table__, "created_at")
    assert len(covering) == 1, (
        f"expected exactly ONE index on ac_pull_audit.created_at, found "
        f"{[ix.name for ix in covering]}"
    )
    assert covering[0].name == "ix_ac_pull_audit_created_at"


def test_create_all_mints_the_named_created_at_index(session_factory):
    session = session_factory()
    try:
        engine = session.get_bind()
        insp = sa.inspect(engine)
        names = {ix["name"] for ix in insp.get_indexes("ac_pull_audit", schema="omni")}
    finally:
        session.close()
    assert "ix_ac_pull_audit_created_at" in names, names
