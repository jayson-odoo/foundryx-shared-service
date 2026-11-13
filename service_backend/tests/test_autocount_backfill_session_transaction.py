"""``existing_columns`` must inspect on the SESSION's OWN connection.

Found via lane 04 on ``fe406635``: ``existing_columns`` unwraps a ``Session``
with ``bind.get_bind()``, which is the ENGINE, so ``sa.inspect`` checks out a
SECOND pooled connection outside the session's transaction. Under the suite's
``StaticPool`` SQLite (one DBAPI connection shared by every checkout) returning
that checkout to the pool issues a ROLLBACK that undoes the session's own
uncommitted writes. ``update_tenant`` runs several backfills in one session
transaction with no commit in between, so a backfill's UPDATE can be silently
rolled back by the very next helper's column check.

Both tests run against the conftest session (the real module tables through
the suite's ``schema_translate_map``, exactly as the ``update_tenant`` tests
do) and never commit between the write and the check.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa

from app.models import DEFAULT_TENANT_ID
from modules.autocount.backfill import backfill_sink_impl_defaults, existing_columns
from modules.autocount.models import SINK_IMPL_LOGGING, AcCompany


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _blank_company(db, *, database_name: str) -> str:
    """A company whose ``sink_impl`` is blank, committed - the shape a
    create_all-first host leaves behind before the sink columns existed."""
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id="conn-legacy",
        database_name=database_name, name=database_name,
    )
    db.add(company)
    db.commit()
    db.execute(
        sa.text("UPDATE ac_company SET sink_impl = '' WHERE id = :id"),
        {"id": company.id},
    )
    db.commit()
    return company.id


def _sink_impl(db, company_id: str) -> str:
    return db.execute(
        sa.text("SELECT sink_impl FROM ac_company WHERE id = :id"), {"id": company_id}
    ).scalar_one()


def test_second_backfill_pass_in_the_same_uncommitted_transaction_touches_nothing(db):
    """Two passes in ONE session transaction, no commit between: the first
    fills the blank rows, the second must find nothing left - unless the
    column check's pooled checkout rolled the first pass back."""
    first_id = _blank_company(db, database_name="AED_ONE")
    second_id = _blank_company(db, database_name="AED_TWO")

    first_pass = backfill_sink_impl_defaults(db, schema=None)
    assert first_pass == 2

    second_pass = backfill_sink_impl_defaults(db, schema=None)
    assert second_pass == 0, "the first pass was rolled back before the second ran"

    # Still inside the same transaction, the rows read as filled.
    assert _sink_impl(db, first_id) == SINK_IMPL_LOGGING
    assert _sink_impl(db, second_id) == SINK_IMPL_LOGGING


def test_existing_columns_does_not_roll_back_a_pending_uncommitted_update(db):
    """Write, inspect, read back - all in the session's own transaction. The
    inspection must ride the session's connection, never a second checkout."""
    company_id = _blank_company(db, database_name="AED_PENDING")

    db.execute(
        sa.text("UPDATE ac_company SET sink_impl = 'pending-marker' WHERE id = :id"),
        {"id": company_id},
    )
    assert _sink_impl(db, company_id) == "pending-marker"

    columns = existing_columns(db, "ac_company", schema=None)
    assert columns is not None and "sink_impl" in columns

    assert _sink_impl(db, company_id) == "pending-marker", (
        "existing_columns rolled back the session's uncommitted UPDATE"
    )


# ── the COMPOSED production path (reviewer finding S2) ──────────────────────


def test_update_tenant_delivers_every_backfill_before_any_commit(db):
    """``update_tenant`` runs four backfills and then ``seed_company_defaults``
    in ONE session transaction. The existing upgrade tests assert only the
    seed's output, so a column check that rolled the earlier backfills back
    left them green while every filled value was lost. Blank every value the
    first three helpers own on committed rows, run the upgrade ONCE, and read
    all of them back in the same session before anything commits."""
    from modules.autocount.bootstrap import update_tenant
    from modules.autocount.canonical.grn import ENTITY_GOODS_RECEIVED_NOTE
    from modules.autocount.envelopes import ENVELOPE_STATUS_DICT
    from modules.autocount.models import ETL_STATUS_DRAFT, AcEntityConfig
    from modules.autocount.sources import INITIAL_LOAD_WINDOWED

    company_id = _blank_company(db, database_name="AED_UPGRADE")
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company_id,
        entity_type=ENTITY_GOODS_RECEIVED_NOTE,
    )
    db.add(config)
    db.commit()
    config_id = config.id
    db.execute(
        sa.text(
            "UPDATE ac_entity_config SET envelope = '', initial_load = '', etl_status = '' "
            "WHERE id = :id"
        ),
        {"id": config_id},
    )
    db.commit()
    db.expire_all()

    update_tenant(db, DEFAULT_TENANT_ID, "0.3.0")

    # No commit: what the session sees now is what the upgrade delivered.
    envelope, initial_load, etl_status = db.execute(
        sa.text(
            "SELECT envelope, initial_load, etl_status FROM ac_entity_config WHERE id = :id"
        ),
        {"id": config_id},
    ).one()
    assert envelope == ENVELOPE_STATUS_DICT
    assert initial_load == INITIAL_LOAD_WINDOWED
    assert etl_status == ETL_STATUS_DRAFT
    assert _sink_impl(db, company_id) == SINK_IMPL_LOGGING
