"""AutoCount bulk document load - round 5 composite-key additions (plan
sprint-5/03), at HEAD c755c37.

(a) build_paged_wrap text: TWO key columns emit the NESTED lexicographic
seek predicate on mssql/postgresql, and single-key text is unchanged after
round 4's composite generalisation.
(b) behavioural walk: a composite-key population with DUPLICATE key0 values
at a shared watermark mark, split across a page boundary - every row staged
exactly once, no gaps, and the cursor's stored lastKey is a 2-element list.
(c) stale shape: a task whose stored TOP-LEVEL lastKey no longer matches the
CURRENT keyColumns shape (grown 1->2, shrunk 2->1, or renamed 1-> a
different 1) must start from NO stored position - full re-read, no rows
skipped, no delete intents, never bind a character of the old key - and
EtlService.update_task must clear the top-level lastKey/sqlWatermark (not
only cursor_json["pass"]) the moment keyColumns or watermarkColumn changes.

(a)/(b) are written against ``SqlDbSource``/``build_paged_wrap`` directly,
reusing ``tests/test_autocount_sql_db_source.py``'s rig helpers (cross-test-
file import, established pattern). (c) reuses ``tests/
test_autocount_bulk_load.py``'s master rig for the run-time backstop, and
``tests/test_autocount_document_mapping.py``'s connection/company helpers
for the update_task save-time test (it needs a REAL, previewable
connection - ``update_task`` runs a fresh preview to validate columns).
"""
from __future__ import annotations

from typing import List

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import (
    RUN_MODE_MANUAL,
    RUN_MODE_RECONCILE,
    RUN_SUCCESS,
    AcStagedRecord,
    STAGED_OP_DELETE,
)
from modules.autocount.sql_source.runtime import RUNTIME
from modules.autocount.sql_source.source import CURSOR_COLUMN, CURSOR_MARK

from tests.test_autocount_bulk_load import (
    DB_NAME,
    _config_row,
    _insert_rows,
    _make_rig,
    _run,
    _run_row,
    _rows,
    _watermark_row,
    consumer,  # noqa: F401 - re-exported as a fixture for this module
)
from tests.test_autocount_sql_db_source import (
    _company as _sql_company,
    _configure,
    _ctx,
    _sql_connection,
)


# ── (a) build_paged_wrap text - composite ordering ─────────────────────────


@pytest.mark.parametrize("dialect", ["mssql", "postgresql"])
def test_build_paged_wrap_two_key_columns_emits_the_nested_lexicographic_predicate(
    dialect,
):
    from modules.autocount.sql_source.source import build_paged_wrap

    quoted_wm = '"LastModified"'
    quoted_k0 = '"DocKey"'
    quoted_k1 = '"LineSeq"'
    sql = build_paged_wrap(
        "SELECT DocKey, LineSeq, LastModified FROM SO", quoted_wm, None, "2026-01-01",
        dialect=dialect, page_size=500, quoted_key=[quoted_k0, quoted_k1],
        last_key=["D001", 3],
    )
    assert (
        f"(t.{quoted_k0} > :last_key0 OR (t.{quoted_k0} = :last_key0 AND "
        f"t.{quoted_k1} > :last_key1))"
    ) in sql, sql
    assert f"ORDER BY t.{quoted_wm}, t.{quoted_k0}, t.{quoted_k1}" in sql, sql
    assert "D001" not in sql, "last_key values must ride as binds, never spliced"
    for forbidden in ("OFFSET", "FETCH", ":skip"):
        assert forbidden not in sql, f"{forbidden!r} must never appear - got:\n{sql}"


def test_build_paged_wrap_single_key_text_is_unchanged_after_the_composite_generalisation():
    from modules.autocount.sql_source.source import build_paged_wrap

    quoted_wm = '"last_modified"'
    quoted_key = '"acc_no"'
    sql = build_paged_wrap(
        "SELECT acc_no, last_modified FROM debtor", quoted_wm, None, "2026-01-01",
        dialect="postgresql", page_size=500, quoted_key=quoted_key, last_key="300-A001",
    )
    assert (
        f"(t.{quoted_wm} > :mark) OR (t.{quoted_wm} = :mark AND "
        f"t.{quoted_key} > :last_key)"
    ) in sql, sql
    assert "last_key0" not in sql, "a single-key task must never gain an indexed bind name"


# ── (b) behavioural walk - duplicate key0 across a page boundary ───────────


def test_composite_key_duplicate_key0_across_a_page_boundary_is_staged_exactly_once_no_gaps(
    session_factory, monkeypatch,
):
    from app.config import settings as cfg
    from modules.autocount.sql_source.source import PageCursor, SqlDbSource

    db = session_factory()
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE composite (key0 TEXT, key1 TEXT, name TEXT, wm TEXT)"
        )
        for row in [
            # three rows share BOTH the same watermark AND the same key0 -
            # only key1 disambiguates a strict seek order.
            ("K1", "A", "Row A", "2026-09-01 00:00:00"),
            ("K1", "B", "Row B", "2026-09-01 00:00:00"),
            ("K1", "C", "Row C", "2026-09-01 00:00:00"),
        ]:
            conn.exec_driver_sql("INSERT INTO composite VALUES (?, ?, ?, ?)", row)

    conn_row = _sql_connection(db, engine)
    company = _sql_company(db)
    config = _configure(
        db, company,
        query="SELECT key0, key1, name, wm FROM composite",
        key_columns=("key0", "key1"),
        watermark="wm",
        connection_id=conn_row.id,
        result_columns=("key0", "key1", "name", "wm"),
    )
    monkeypatch.setattr(cfg, "autocount_page_size", 2, raising=False)
    source = SqlDbSource(_ctx(db, company, config), entity_type=ENTITY_CUSTOMER)

    cursor = PageCursor()
    seen: List[str] = []
    for _ in range(6):
        page = source.fetch_page(cursor)
        seen.extend(r.raw["key1"] for r in page.records)
        if page.complete:
            break
        assert isinstance(page.last_key, (list, tuple)) and len(page.last_key) == 2, (
            f"a composite-key task's cursor lastKey must be a 2-element "
            f"list/tuple - got {page.last_key!r}"
        )
        cursor = PageCursor(mark=page.last_mark, last_key=page.last_key)
    else:
        pytest.fail("the pass never completed")

    assert seen == ["A", "B", "C"], (
        f"every row sharing (watermark, key0) must be staged exactly once, "
        f"in order, with no gaps - got {seen}"
    )
    RUNTIME.dispose_all()


# ── (c) stale shape - top-level lastKey no longer matches keyColumns ───────


@pytest.mark.parametrize(
    "case", ["grow_1_to_2", "shrink_2_to_1", "rename_1_to_a_different_1"]
)
def test_a_key_columns_reshape_never_resumes_a_stale_top_level_position(
    session_factory, monkeypatch, consumer, case,
):
    """A stored top-level ``lastKey`` (the PUBLIC, monotonic position -
    ``PageCursor.from_watermark_row``'s fresh-pass branch reads it whenever
    the WATERMARK column still matches) is shaped for the OLD
    ``keyColumns`` - the watermark column itself never changes in any of
    these three cases, so ``column_matches`` alone (today's only check)
    says "safe to resume" when it is not. Driven through a REAL reconcile
    run (``run_autocount_sync``) - a full re-read must occur, no delete
    intents may appear (every row is still genuinely present), and no
    statement may bind a lone character sliced off the old scalar key."""
    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(5)
    _insert_rows(engine, rows)
    db = session_factory()

    if case == "shrink_2_to_1":
        config = _config_row(db, company_id)
        config.source_config = {**config.source_config, "keyColumns": ["acc_no", "email"]}
        db.commit()

    seed = _run(db, company_id, RUN_MODE_MANUAL)
    assert seed.status == JOB_DONE

    watermark = _watermark_row(db, company_id)
    assert watermark.cursor_json.get(CURSOR_MARK) is not None, (
        "the seed run must have established a top-level position"
    )
    stored_last_key = watermark.cursor_json.get("lastKey")
    if case == "shrink_2_to_1":
        assert isinstance(stored_last_key, list) and len(stored_last_key) == 2
    else:
        assert isinstance(stored_last_key, str) and len(stored_last_key) > 1

    # Reshape keyColumns directly (isolates the RUN-time backstop from the
    # update_task SAVE-time clear, tested separately below) - the watermark
    # column is left UNTOUCHED in every case.
    config = _config_row(db, company_id)
    if case == "grow_1_to_2":
        config.source_config = {**config.source_config, "keyColumns": ["acc_no", "email"]}
    elif case == "shrink_2_to_1":
        config.source_config = {**config.source_config, "keyColumns": ["acc_no"]}
    else:
        config.source_config = {**config.source_config, "keyColumns": ["email"]}
    db.commit()

    binds_seen: List[dict] = []

    def before_cursor_execute(conn2, cursor, statement, parameters, context, executemany):
        if "debtor" in statement.lower() and isinstance(parameters, dict):
            binds_seen.append(dict(parameters))

    sa.event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        job2 = _run(db, company_id, RUN_MODE_RECONCILE)
        run2 = _run_row(db, company_id, job2.id)
    finally:
        sa.event.remove(engine, "before_cursor_execute", before_cursor_execute)

    assert run2.outcome == RUN_SUCCESS, (
        f"a keyColumns reshape must never crash/fail a run - "
        f"outcome={run2.outcome!r} error={run2.error!r}"
    )

    for params in binds_seen:
        for bind_name, value in params.items():
            if bind_name.startswith("last_key") and isinstance(value, str):
                assert len(value) > 1, (
                    f"{bind_name}={value!r} looks like a single character "
                    f"sliced off the stale scalar key {stored_last_key!r} - "
                    f"real key values are never 1 character long"
                )

    assert run2.rows_scanned == len(rows), (
        f"a reshape must force a FULL re-read (no stored position reused) - "
        f"expected rows_scanned={len(rows)}, got {run2.rows_scanned}"
    )
    intents = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.op == STAGED_OP_DELETE,
        )
        .all()
    )
    assert intents == [], (
        f"every row is still genuinely present - a reshape must never "
        f"misread it as vanished: got delete intents for "
        f"{[i.source_ref for i in intents]}"
    )
    db.close()


def test_update_task_clears_the_top_level_cursor_when_key_columns_change(
    session_factory,
):
    """EtlService.update_task already clears ``cursor_json['pass']`` on a
    ``keyColumns``/``watermarkColumn`` change (F4, review round 2) - it
    must ALSO clear the TOP-LEVEL ``sqlWatermark``/``lastKey`` pair (the
    PUBLIC, monotonic position ``PageCursor.from_watermark_row``'s
    fresh-pass branch resumes from), or a save-time keyColumns change still
    leaves a stale scalar/list position sitting there for the very next
    run to misread."""
    import sqlite3
    from datetime import datetime as _dt

    from modules.autocount.repositories import WatermarkRepository
    from modules.autocount.services.etl_service import EtlService

    db = session_factory()
    # A typed TIMESTAMP column (PARSE_DECLTYPES) so the live preview
    # `update_task` runs to validate the watermark column reads back a real
    # `datetime`, not TEXT - the same discipline
    # `test_autocount_document_mapping.py`'s `_source_engine_typed` uses for
    # exactly this reason.
    engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False, "detect_types": sqlite3.PARSE_DECLTYPES},
        poolclass=StaticPool,
    )
    with engine.begin() as conn2:
        conn2.exec_driver_sql(
            "CREATE TABLE debtor (acc_no TEXT PRIMARY KEY, company_name TEXT, "
            "email TEXT, last_modified TIMESTAMP)"
        )
        conn2.execute(
            sa.text(
                "INSERT INTO debtor VALUES (:acc, :name, :email, :lm)"
            ),
            {
                "acc": "300-A001", "name": "Acme", "email": "a@x.com",
                "lm": _dt(2026, 8, 1, 9, 0, 0),
            },
        )
    conn = _sql_connection(db, engine)
    company = _sql_company(db)
    _configure(db, company, connection_id=conn.id)

    # A pre-existing top-level position, as if a prior run had already
    # advanced it (single-key shape).
    watermark = WatermarkRepository(db).get_or_create(
        DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER
    )
    watermark.cursor_json = {
        CURSOR_COLUMN: "last_modified",
        CURSOR_MARK: "2026-08-01 09:00:00",
        "lastKey": "300-A001",
    }
    db.commit()

    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_CUSTOMER,
        {
            "connectionId": conn.id,
            "query": "SELECT acc_no, company_name, email, last_modified FROM debtor",
            "keyColumns": ["acc_no", "email"],  # the reshape
            "watermarkColumn": "last_modified",
            "comparedColumns": [],
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
        },
    )

    db.refresh(watermark)
    cursor = watermark.cursor_json or {}
    assert cursor.get(CURSOR_MARK) is None, (
        f"update_task must clear the top-level sqlWatermark on a keyColumns "
        f"change, not just cursor_json['pass'] - got {cursor.get(CURSOR_MARK)!r}"
    )
    assert cursor.get("lastKey") is None, (
        f"update_task must clear the top-level lastKey on a keyColumns "
        f"change - got {cursor.get('lastKey')!r}"
    )
    db.close()
    RUNTIME.dispose_all()
