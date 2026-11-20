"""Sprint-5/10 S3 review round 1 - SHOULD-FIX 3: the ORM and migration 0020
must mint exactly ONE index per column, never two.

Coordinator finding: ``AcPullSnapshot.job_id``/``expires_at`` and
``AcPullSnapshotRow.company_id`` carried BOTH a column-level ``index=True``
(an auto-named index under ``create_all``) AND an explicit, separately-named
``Index`` the migration ALSO creates - confirmed live on the lane Postgres
(``foundryx_service_s40``) as a genuine duplicate pair per column
(``ix_ac_pull_snapshot_expires_at`` beside
``ix_app_autocount_ac_pull_snapshot_expires_at``, same for ``job_id`` and the
row table's ``company_id``). The migration verification transcript
(downgrade to 0019, clean ``upgrade head``, then a create_all-first
simulation followed by ``upgrade head`` again) is reported separately - this
file pins the ORM side under this suite's own SQLite ``create_all`` rig, so
a future re-introduction of ``index=True`` on one of these three columns
fails a fast, always-run test rather than only showing up on live Postgres.

RED before the fix (proven by reverting locally - see the coder's final
report): with ``index=True`` restored on any of the three columns, this
suite's own ``create_all`` mints a SECOND index for that column (SQLite
supports column-level auto-indexes too), and the count assertions below go
from 1 to 2.
"""
from __future__ import annotations

import httpx
import pytest
import sqlalchemy as sa

from modules.autocount.models import AcPullSnapshot, AcPullSnapshotRow


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    ``test_s10_s3_delivery_mode.py``'s copy of this fixture for the full
    rationale (coordinator finding 2026-09-20). Review round 2 nit (item 6) -
    this file makes no HTTP call at all (pure ORM/inspector checks), but
    carried no explicit guard against a future addition that did."""

    real_send = httpx.Client.send
    real_async_send = httpx.AsyncClient.send

    def guarded_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return real_send(self, request, *args, **kwargs)

    async def guarded_async_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return await real_async_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(httpx.AsyncClient, "send", guarded_async_send)


def _indexes_covering(table: sa.Table, column_name: str) -> list:
    """Every index on ``table`` whose column set is EXACTLY ``{column_name}``
    (a composite index covering the column too, e.g. ``ix_ac_pull_snapshot_
    triple``, is a different index entirely and never counted here)."""
    return [
        ix for ix in table.indexes
        if {c.name for c in ix.columns} == {column_name}
    ]


def test_orm_declares_exactly_one_index_for_expires_at():
    covering = _indexes_covering(AcPullSnapshot.__table__, "expires_at")
    assert len(covering) == 1, (
        f"expected exactly ONE index on expires_at, found {[ix.name for ix in covering]} - "
        "a column-level index=True beside the explicit named Index mints two"
    )
    assert covering[0].name == "ix_ac_pull_snapshot_expires_at"
    assert AcPullSnapshot.__table__.c.expires_at.index is not True


def test_orm_declares_exactly_one_index_for_job_id():
    covering = _indexes_covering(AcPullSnapshot.__table__, "job_id")
    assert len(covering) == 1, (
        f"expected exactly ONE index on job_id, found {[ix.name for ix in covering]}"
    )
    assert covering[0].name == "ix_ac_pull_snapshot_job"
    assert AcPullSnapshot.__table__.c.job_id.index is not True


def test_orm_declares_exactly_one_index_for_row_company_id():
    covering = _indexes_covering(AcPullSnapshotRow.__table__, "company_id")
    assert len(covering) == 1, (
        f"expected exactly ONE index on company_id, found {[ix.name for ix in covering]}"
    )
    assert covering[0].name == "ix_ac_pull_snapshot_row_company"
    assert AcPullSnapshotRow.__table__.c.company_id.index is not True


def test_create_all_mints_exactly_the_named_indexes_no_more(session_factory):
    """End-to-end proof on THIS suite's own ``create_all`` rig (SQLite,
    ``AUTOCOUNT_SCHEMA`` attached as its own in-memory db per conftest) -
    never trusts the ORM-level ``__table_args__`` inspection alone."""
    session = session_factory()
    try:
        engine = session.get_bind()
        insp = sa.inspect(engine)
        # This suite's conftest attaches AUTOCOUNT_SCHEMA to the SQLite
        # in-memory db named "omni" (schema_translate_map) - the table
        # itself is unqualified, but the inspector needs to be told where
        # to look, exactly like every other module table under this rig.
        names = {ix["name"] for ix in insp.get_indexes("ac_pull_snapshot", schema="omni")}
        row_names = {
            ix["name"] for ix in insp.get_indexes("ac_pull_snapshot_row", schema="omni")
        }
    finally:
        session.close()

    for expected in (
        "ix_ac_pull_snapshot_expires_at",
        "ix_ac_pull_snapshot_job",
        "ix_ac_pull_snapshot_triple",
        "ix_ac_pull_snapshot_status",
        "uq_ac_pull_snapshot_one_building",
    ):
        assert expected in names, f"missing {expected}: {names}"
    # Never a SECOND, differently-named index on expires_at/job_id.
    assert sum(1 for n in names if "expires_at" in n) == 1, names
    assert sum(1 for n in names if "job" in n) == 1, names

    for expected in ("ix_ac_pull_snapshot_row_company", "ix_ac_pull_snapshot_row_snapshot"):
        assert expected in row_names, f"missing {expected}: {row_names}"
    assert sum(1 for n in row_names if "company" in n) == 1, row_names
