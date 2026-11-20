"""AutoCount bulk document load - security-reviewer fix round (plan sprint-5/03).

RED tests written BEFORE the coder, at HEAD 692e579, from the security
reviewer's findings F1-F7 plus the follow-up round R-S1/R-S6/R-NIT/R-S7.
Every finding is driven through a REAL entry point
(``scheduler._sweep_one`` -> ``JobService`` eager -> ``run_autocount_sync``)
rather than by calling internals directly, per the coordinator's brief -
where the finding IS an interleave (F2), a real abort is forced with a
SQLAlchemy ``before_cursor_execute``/statement-count hook exactly like the
existing real-interleave abort tests in ``tests/test_autocount_pipeline.py``
and ``tests/test_autocount_bulk_load.py``.

Reuses ``tests/test_autocount_bulk_load.py``'s fixture plumbing
(``_make_rig``, ``Consumer``, ``_rows``, ``_insert_rows``, ``_run``,
``_run_row``, ``_config_row``, ``_watermark_row``, ``DB_NAME``) rather than
duplicating it - cross-test-file imports are an established pattern in this
suite (``tests/test_activity_embed.py`` imports from
``tests/test_omnichannel_embed.py``).

ASSUMPTIONS / notes on what each test targets (named so the coder can find
the exact line):

* F1 - ``EtlService.preview_task`` -> ``_extract_and_map`` always calls
  ``source.fetch_changes(Watermark())`` (the OLD unpaged path), never
  ``fetch_page`` - a document preview reads the WHOLE from-date window and
  fans out a line query per header, not one page.
* F2/F3/F4 - ``sync._run_paged_sql_db`` and
  ``PageCursor.from_watermark_row`` (``sql_source/source.py``).
* F5 - ``SqlDbSource.fetch_page``'s tie handling: ``exclude_refs =
  set(cursor.tie_refs or ())`` and ``bind_limit = page_size +
  len(exclude_refs)`` - for a tie group spanning several pages,
  ``tie_refs`` keeps ACCUMULATING (``tie_refs = sorted((exclude_refs |
  group_refs) if same_group else group_refs)``), so ``bind_limit`` (and the
  real per-page statement size) grows roughly linearly with how much of the
  tie group has been seen so far, not with ``page_size``.
* F6 - ``SqlDbSource.fetch_page``'s row-limit check
  (``if len(raw_rows) > self.row_limit: raise ...``) sits AFTER the
  ``for partition in result.partitions(STREAM_BATCH): for row in
  partition: ...`` loop entirely, unlike ``_read``'s per-PARTITION check -
  it materialises the WHOLE result before ever looking at the cap.
* F7 - ``sync._run_paged_sql_db`` never calls ``record_activity`` (grepped
  clean) - only the legacy branch above it does.
* R-S1 - ``_stage_deletes``/``discard_stale_deletes`` is only ever called
  from the "deletes, ONLY when a RECONCILE pass just completed" block in
  ``_run_paged_sql_db`` - an INCREMENTAL paged run never cancels a stale
  parked delete intent even when the very ref it targets just reappeared.
* R-S6 - ``PageCursor.from_watermark_row``'s "brand new pass" branch reads
  ``cursor.get(CURSOR_COLUMN)``/``cursor.get(CURSOR_MARK)``/
  ``cursor.get("tieRefs")`` directly off whatever dict is stored - a REAL
  pre-migration row (only the two legacy keys) should resume as a plain
  incremental with no special handling needed; this is a regression guard,
  not necessarily a bug.
* R-NIT - the zero-row guard inside ``fetch_page``
  (``if full_extract and not raw_rows: ... raise SqlDeleteGuardExceeded``)
  fires on EVERY page of a full extract, not just the first - a later
  page's raw read legitimately empties out once the pass nears its end
  (the previous page's own boundary row can be genuinely gone by then),
  which is normal completion, not evidence of a wipe.
* R-S7 - ``service.set_total(job, total_rows_scanned)`` is called only
  ONCE, at the very end of the whole paged run (after every page's
  ``service.advance`` calls already happened) - the legacy branch calls
  ``set_total`` BEFORE staging starts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest
import sqlalchemy as sa

from app.jobs.service import JobService
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_ABORTED, JOB_DONE, JOB_NEEDS_REVIEW
from app.models.integration_activity import ACTIVITY_ERROR, ACTIVITY_SUCCESS, IntegrationActivity
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    RUN_ABORTED,
    RUN_FAILED,
    RUN_MODE_INCREMENTAL,
    RUN_MODE_MANUAL,
    RUN_MODE_RECONCILE,
    RUN_SUCCESS,
    STAGED,
    STAGED_DISCARDED,
    STAGED_OP_DELETE,
    AcStagedRecord,
    AcSyncRun,
)
from modules.autocount.repositories import RowHashRepository
from modules.autocount.sql_source.runtime import RUNTIME
from modules.autocount.sql_source.source import CURSOR_COLUMN, CURSOR_MARK

from tests.test_autocount_bulk_load import (
    DB_NAME,
    Consumer,
    _config_row,
    _insert_rows,
    _make_rig,
    _run,
    _run_row,
    _rows,
    _watermark_row,
)


@pytest.fixture
def consumer(monkeypatch) -> Consumer:
    import modules.autocount.services.company_service as company_module
    from modules.autocount.sinks_sorento import sorento_sink_from_connection as real

    rec = Consumer()

    def fake(config, credentials, *, entity_type, company_code=None, transport=None):
        return real(
            config, credentials, entity_type=entity_type,
            company_code=company_code, transport=rec.transport,
        )

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", fake)
    return rec


@pytest.fixture(autouse=True)
def _clean_runtime():
    yield
    RUNTIME.dispose_all()


def _sweep_tick(db, company_id: str, *, reconcile: bool) -> AcSyncRun:
    """Drive one tick through the REAL scheduler entry point - the finding
    explicitly wants F2-F4 proven through ``scheduler._sweep_one``, not
    ``_run(mode)``'s direct ``JobService.create_and_enqueue``."""
    from modules.autocount.scheduler import _sweep_one

    before_ids = {
        row.id
        for row in db.query(AcSyncRun.id).filter(
            AcSyncRun.tenant_id == DEFAULT_TENANT_ID, AcSyncRun.company_id == company_id
        )
    }
    now = datetime.now(timezone.utc)
    config = _config_row(db, company_id)
    if reconcile:
        config.next_reconcile_at = now
    else:
        config.next_incremental_at = now
    db.commit()
    outcome = _sweep_one(db, config, now=now)
    assert outcome == "fired", f"the tick did not fire (outcome={outcome!r})"
    after = (
        db.query(AcSyncRun)
        .filter(AcSyncRun.tenant_id == DEFAULT_TENANT_ID, AcSyncRun.company_id == company_id)
        .all()
    )
    new_runs = [r for r in after if r.id not in before_ids]
    assert len(new_runs) == 1, f"expected exactly one new run this tick, got {len(new_runs)}"
    return new_runs[0]


# ── F1 - preview fan-out ─────────────────────────────────────────────────────


def test_preview_reads_at_most_one_page_of_headers_and_fans_out_no_further(
    monkeypatch, session_factory,
):
    """F1. A document task's preview (``EtlService.preview_task`` - the real
    entry point ``POST .../etl-task/preview`` calls) must read AT MOST one
    page of headers, counted as real executed statements against the source
    engine (1 header query + at most ``page_size`` line queries) - not the
    whole from-date window."""
    from app.config import settings as cfg
    from modules.autocount.canonical.documents import ENTITY_SALES_ORDER
    from modules.autocount.models import (
        ETL_STATUS_DRAFT,
        SOURCE_IMPL_SQL_DB,
        AcCompany,
        AcEntityConfig,
    )
    from modules.autocount.services.etl_service import EtlService
    from app.models.connection import Connection
    from app.secrets import encrypt_secret

    db = session_factory()
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE so_header (doc_key TEXT PRIMARY KEY, doc_no TEXT, last_modified TEXT)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE so_line (dtl_key TEXT PRIMARY KEY, doc_key TEXT, item_code TEXT)"
        )
        for i in range(5):
            conn.exec_driver_sql(
                "INSERT INTO so_header VALUES (?, ?, ?)",
                (f"D{i:03d}", f"SO-{i:03d}", f"2026-09-{i + 1:02d} 09:00:00"),
            )
            conn.exec_driver_sql(
                "INSERT INTO so_line VALUES (?, ?, ?)", (f"D{i:03d}-1", f"D{i:03d}", "ITEM-A")
            )

    sql_conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sql_database", type="erp", name="Source DB",
        config_json={"dbType": "postgresql", "host": "db.example.com", "port": "5432",
                     "database": "AED_PREVIEW", "username": "readonly"},
        credentials_json=encrypt_secret({"password": "S3cret!Pa55"}), is_active=True,
    )
    db.add(sql_conn)
    db.commit()
    db.refresh(sql_conn)
    RUNTIME.put_engine(sql_conn.id, engine)

    api_conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="AutoCount API",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}), is_active=True,
    )
    db.add(api_conn)
    db.flush()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api_conn.id, database_name="AED_PREVIEW",
        company_name="AED Preview Sdn Bhd", name="AED Preview", is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)

    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_SALES_ORDER,
        source_impl=SOURCE_IMPL_SQL_DB, etl_status=ETL_STATUS_DRAFT,
    )
    config.source_config = {
        "connectionId": sql_conn.id,
        "query": "SELECT doc_key, doc_no, last_modified FROM so_header",
        "lineQuery": "SELECT dtl_key, item_code FROM so_line WHERE doc_key = :doc_key",
        "keyColumns": ["doc_key"],
        "watermarkColumn": "last_modified",
        "comparedColumns": [],
        "fromDate": "2026-01-01",
        "docDateColumn": "last_modified",
        "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
    }
    config.result_columns = ["doc_key", "doc_no", "last_modified"]
    db.add(config)
    db.commit()

    monkeypatch.setattr(cfg, "autocount_page_size", 2, raising=False)

    statements = {"n": 0}

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        lowered = statement.lower()
        if "so_header" in lowered or "so_line" in lowered:
            statements["n"] += 1

    sa.event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        EtlService(db).preview_task(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER)
    finally:
        sa.event.remove(engine, "before_cursor_execute", before_cursor_execute)

    assert statements["n"] <= 3, (
        f"preview must read AT MOST one page (1 header query + up to "
        f"page_size=2 line queries = 3 statements) - executed "
        f"{statements['n']} against the source"
    )
    assert RowHashRepository(db).all_hashes(
        DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER
    ) == {}
    assert db.query(AcStagedRecord).count() == 0


# ── F2 - abort between pages, no skip, no double-push, via the scheduler ───


def test_an_abort_between_pages_delivers_page_one_exactly_once_via_the_scheduler(
    session_factory, monkeypatch, consumer,
):
    # page_size=1, 4 rows: with round-3's page_size+1 peek, this pass needs
    # FOUR statements/pages (page1..3 each read 2 rows and trim the peeked
    # one back off; page4 reads the last remaining row and completes) - the
    # injected abort below lands on statement #2, a NON-final page
    # (round-3b: page_size=2 made statement #2 the LAST page for a 4-row
    # population, which tested an abort on the FINAL page instead of a
    # mid-pass one - see the refuted mid-pass-abort candidate (no backlog row) for that separate scenario).
    monkeypatch.setattr(
        __import__("app.config", fromlist=["settings"]).settings,
        "autocount_page_size", 1, raising=False,
    )
    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(4)
    _insert_rows(engine, rows)
    expected_refs = {f"{DB_NAME}:{r[0]}" for r in rows}

    calls = {"n": 0}
    aborted_once = {"done": False}
    aborting = session_factory()

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if "debtor" not in statement.lower():
            return
        calls["n"] += 1
        if calls["n"] == 2 and not aborted_once["done"]:
            aborted_once["done"] = True
            job_id = aborting.execute(
                sa.text(
                    "SELECT id FROM background_jobs WHERE tenant_id = :t "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"t": DEFAULT_TENANT_ID},
            ).scalar()
            aborting.execute(
                sa.text("UPDATE background_jobs SET status = :s WHERE id = :i"),
                {"s": JOB_ABORTED, "i": job_id},
            )
            aborting.commit()

    sa.event.listen(engine, "before_cursor_execute", before_cursor_execute)
    db = session_factory()
    try:
        run1 = _sweep_tick(db, company_id, reconcile=False)
        assert run1.outcome == RUN_ABORTED
    finally:
        sa.event.remove(engine, "before_cursor_execute", before_cursor_execute)
    aborting.close()

    def _pending_count() -> int:
        return (
            db.query(AcStagedRecord)
            .filter(
                AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
                AcStagedRecord.company_id == company_id,
                AcStagedRecord.status == STAGED,
            )
            .count()
        )

    # Drive the continuation ticks (real scheduler entry point each time)
    # until every staged row has actually been PUSHED (round 3b: "the pass
    # completed" is not the same question - an aborted run can leave a
    # complete pass with its own page's rows staged but never auto-pushed,
    # S4/the refuted mid-pass-abort candidate (no backlog row)) - a generous cap, defensive about exactly how many
    # pages/ticks 4 rows needs.
    for _ in range(10):
        if _pending_count() == 0:
            break
        _sweep_tick(db, company_id, reconcile=False)
    else:
        pytest.fail("staged rows were never fully pushed within the tick budget")

    upsert_calls = [r for r in consumer.requests if not r["path"].endswith("/deletions")]
    pushed_refs: List[str] = []
    for call in upsert_calls:
        pushed_refs.extend(r["source_ref"] for r in call["json"].get("records") or [])

    assert set(pushed_refs) == expected_refs, (
        f"every document must reach the sink eventually - got {sorted(pushed_refs)}, "
        f"expected {sorted(expected_refs)}"
    )
    duplicates = [ref for ref in expected_refs if pushed_refs.count(ref) > 1]
    assert duplicates == [], f"no document may be pushed twice - duplicated: {duplicates}"
    db.close()


def test_an_abort_on_the_final_page_still_gets_pushed_by_the_next_ordinary_tick(
    session_factory, monkeypatch, consumer,
):
    """S4 / the refuted mid-pass-abort candidate (no backlog row) refutation. Abort lands on the FINAL page's own
    statement (page_size=2, 4 rows -> exactly 2 statements/pages) - that
    page's rows are staged and committed (the abort is only detected AFTER
    the page's own commit), and ``pass.complete`` is written True before the
    abort check runs, so the pass is never resumed. The claim was that
    those rows are then STRANDED because no later tick "continues" a
    complete pass - refuted here: ``auto_push`` runs unconditionally on
    EVERY run of an ACTIVE task (new rows fetched or not), so the very next
    ORDINARY incremental tick (which finds nothing new to fetch) still
    drains the entity's pending staged rows and pushes every one exactly
    once."""
    monkeypatch.setattr(
        __import__("app.config", fromlist=["settings"]).settings,
        "autocount_page_size", 2, raising=False,
    )
    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(4)
    _insert_rows(engine, rows)
    expected_refs = {f"{DB_NAME}:{r[0]}" for r in rows}

    calls = {"n": 0}
    aborted_once = {"done": False}
    aborting = session_factory()

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if "debtor" not in statement.lower():
            return
        calls["n"] += 1
        if calls["n"] == 2 and not aborted_once["done"]:
            aborted_once["done"] = True
            job_id = aborting.execute(
                sa.text(
                    "SELECT id FROM background_jobs WHERE tenant_id = :t "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"t": DEFAULT_TENANT_ID},
            ).scalar()
            aborting.execute(
                sa.text("UPDATE background_jobs SET status = :s WHERE id = :i"),
                {"s": JOB_ABORTED, "i": job_id},
            )
            aborting.commit()

    sa.event.listen(engine, "before_cursor_execute", before_cursor_execute)
    db = session_factory()
    try:
        run1 = _sweep_tick(db, company_id, reconcile=False)
        assert run1.outcome == RUN_ABORTED
    finally:
        sa.event.remove(engine, "before_cursor_execute", before_cursor_execute)
    aborting.close()

    watermark = _watermark_row(db, company_id)
    assert ((watermark.cursor_json or {}).get("pass") or {}).get("complete") is True, (
        "the final page's own read must have completed the pass before the "
        "abort was detected - otherwise this is not the the refuted mid-pass-abort candidate (no backlog row) scenario"
    )
    pending_before = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.status == STAGED,
        )
        .count()
    )
    assert pending_before == 4, (
        f"all 4 rows must have been staged (final page committed before the "
        f"abort) - found {pending_before} pending"
    )

    # The NEXT tick is an ORDINARY incremental sweep - the pass is already
    # complete, so it starts a fresh (empty) incremental read; it must still
    # drain and push the stranded rows via its own unconditional auto_push.
    run2 = _sweep_tick(db, company_id, reconcile=False)
    assert run2.outcome == RUN_SUCCESS

    upsert_calls = [r for r in consumer.requests if not r["path"].endswith("/deletions")]
    pushed_refs: List[str] = []
    for call in upsert_calls:
        pushed_refs.extend(r["source_ref"] for r in call["json"].get("records") or [])
    assert set(pushed_refs) == expected_refs, (
        f"the stranded final-page rows must be delivered by the very next "
        f"ordinary tick's auto_push - got {sorted(pushed_refs)}, expected "
        f"{sorted(expected_refs)}"
    )
    duplicates = [ref for ref in expected_refs if pushed_refs.count(ref) > 1]
    assert duplicates == [], f"no document may be pushed twice - duplicated: {duplicates}"
    db.close()


# ── F3 - truncated reconcile under the scheduler ────────────────────────────


def test_a_truncated_reconcile_is_continued_as_reconcile_when_only_incremental_is_due(
    session_factory, monkeypatch, consumer,
):
    from app.config import settings as cfg

    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(6)
    _insert_rows(engine, rows)
    deleted_ref = f"{DB_NAME}:{rows[-1][0]}"

    db = session_factory()
    seed = _run(db, company_id, RUN_MODE_MANUAL)
    assert seed.status == JOB_DONE
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM debtor WHERE acc_no = ?", (rows[-1][0],))

    monkeypatch.setattr(cfg, "autocount_page_size", 2, raising=False)
    monkeypatch.setattr(cfg, "autocount_run_time_budget_seconds", 0, raising=False)

    run1 = _sweep_tick(db, company_id, reconcile=True)
    assert run1.truncated is True
    pass1 = (_watermark_row(db, company_id).cursor_json or {}).get("pass") or {}
    assert pass1.get("kind") == RUN_MODE_RECONCILE
    pages1 = pass1.get("pagesDone")

    # Tick 2: next_incremental_at is due (the truncation armed it to "now"),
    # next_reconcile_at is NOT (the sweep's own claim already re-armed it
    # into the future) - exactly the scenario the finding names.
    config = _config_row(db, company_id)
    assert config.next_incremental_at is not None
    assert config.next_incremental_at <= datetime.now(timezone.utc) + timedelta(seconds=5)
    assert config.next_reconcile_at is None or config.next_reconcile_at > datetime.now(
        timezone.utc
    ) + timedelta(minutes=1)

    marks: List[str] = [((_watermark_row(db, company_id).cursor_json or {}).get(CURSOR_MARK))]
    for _ in range(10):
        watermark = _watermark_row(db, company_id)
        pass_state = (watermark.cursor_json or {}).get("pass") or {}
        if pass_state.get("complete"):
            break
        assert pass_state.get("kind") == RUN_MODE_RECONCILE, (
            "the open RECONCILE pass must be continued as reconcile even "
            "when only the incremental schedule is due this tick - got "
            f"kind={pass_state.get('kind')!r}"
        )
        _sweep_tick(db, company_id, reconcile=False)
        marks.append((_watermark_row(db, company_id).cursor_json or {}).get(CURSOR_MARK))
        assert pass_state.get("pagesDone", 0) >= pages1
    else:
        pytest.fail("the reconcile pass never completed")

    # The top-level mark must never move BACKWARDS across ticks.
    non_null_marks = [m for m in marks if m is not None]
    assert non_null_marks == sorted(non_null_marks), (
        f"sqlWatermark regressed across ticks: {non_null_marks}"
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
    assert [r.source_ref for r in intents] == [deleted_ref]
    db.close()


# ── F4 - resume after a watermark column change ─────────────────────────────


def test_resuming_a_pass_after_the_watermark_column_changed_starts_fresh(
    session_factory, monkeypatch, consumer,
):
    from app.config import settings as cfg

    company_id, sql_id, engine = _make_rig(session_factory)
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE debtor ADD COLUMN secondary_modified TEXT")
    rows = _rows(3)
    with engine.begin() as conn:
        for row in rows:
            conn.exec_driver_sql(
                "INSERT INTO debtor (acc_no, company_name, email, last_modified, "
                "secondary_modified) VALUES (?, ?, ?, ?, ?)",
                (*row, "2020-01-01 00:00:00"),
            )

    db = session_factory()
    seed = _run(db, company_id, RUN_MODE_MANUAL)
    assert seed.status == JOB_DONE

    monkeypatch.setattr(cfg, "autocount_page_size", 1, raising=False)
    monkeypatch.setattr(cfg, "autocount_run_time_budget_seconds", 0, raising=False)

    run1 = _sweep_tick(db, company_id, reconcile=True)
    assert run1.truncated is True
    watermark = _watermark_row(db, company_id)
    assert (watermark.cursor_json or {}).get(CURSOR_COLUMN) == "last_modified"

    # Simulate an operator switching the watermark column mid-pass (an
    # ordinary etl-task PUT would run this update through EtlService; the
    # bug under test lives in the RUN-time resume, not the save validation,
    # so the config is mutated directly here).
    config = _config_row(db, company_id)
    config.source_config = {
        **config.source_config,
        "query": (
            "SELECT acc_no, company_name, email, last_modified, secondary_modified "
            "FROM debtor"
        ),
        "watermarkColumn": "secondary_modified",
    }
    config.result_columns = list(config.result_columns) + ["secondary_modified"]
    db.commit()

    monkeypatch.setattr(cfg, "autocount_page_size", 10, raising=False)
    monkeypatch.setattr(cfg, "autocount_run_time_budget_seconds", 600, raising=False)

    run2 = _sweep_tick(db, company_id, reconcile=True)
    assert run2.outcome == RUN_SUCCESS, (
        f"a watermark-column switch must start a FRESH pass, not misapply "
        f"the old column's stale mark to the new column - got outcome="
        f"{run2.outcome!r} error={run2.error!r}"
    )
    assert run2.rows_scanned == 3, (
        "every header must be read fresh under the NEW column - none may be "
        f"silently skipped by a stale cross-column mark - got {run2.rows_scanned}"
    )
    db.close()


# ── F5 - ties larger than 3x page_size ───────────────────────────────────────


def test_a_tie_group_larger_than_3x_page_size_stays_bounded_per_page(
    session_factory, monkeypatch, consumer,
):
    """F5 (round 3: composite ``(watermark, key)`` seek replaces the old
    ``bind_limit = page_size + len(exclude_refs)`` OFFSET-retry design) - the
    bound ``page_size`` parameter fed to the real SQL statement must not grow
    past a small, fixed multiple of ``page_size`` as an oversized tie group
    is paged through (it must stay flat at ``page_size + 1``, never
    accumulate with the tie group's size)."""
    from modules.autocount.sql_source.source import PageCursor, SqlDbSource
    from modules.autocount.sources import SourceContext, Watermark
    from modules.autocount.services.company_service import CompanyService
    from app.config import settings as cfg

    company_id, sql_id, engine = _make_rig(session_factory)
    page_size = 3
    tie_count = 3 * page_size + 4  # larger than 3x page_size
    tie_mark = "2026-09-01 00:00:00"
    with engine.begin() as conn:
        for i in range(tie_count):
            conn.exec_driver_sql(
                "INSERT INTO debtor VALUES (?, ?, ?, ?)",
                (f"300-T{i:04d}", f"Tie {i}", f"t{i}@x.com", tie_mark),
            )
    monkeypatch.setattr(cfg, "autocount_page_size", page_size, raising=False)

    db = session_factory()
    from modules.autocount.models import AcCompany, AcEntityConfig

    company = db.query(AcCompany).filter(AcCompany.id == company_id).one()
    config = db.query(AcEntityConfig).filter(
        AcEntityConfig.tenant_id == DEFAULT_TENANT_ID, AcEntityConfig.company_id == company_id,
        AcEntityConfig.entity_type == ENTITY_CUSTOMER,
    ).one()
    source = SqlDbSource(
        SourceContext(
            db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
            company_service=CompanyService(db),
        ),
        entity_type=ENTITY_CUSTOMER,
    )

    page_size_binds: List[int] = []
    real_execute = sa.engine.Connection.execute

    def counting_execute(self, statement, parameters=None, *a, **kw):
        if parameters and isinstance(parameters, dict) and "page_size" in parameters:
            page_size_binds.append(parameters["page_size"])
        return real_execute(self, statement, parameters, *a, **kw)

    monkeypatch.setattr(sa.engine.Connection, "execute", counting_execute)

    cursor = PageCursor()
    seen_refs: set[str] = set()
    for _ in range(30):
        page = source.fetch_page(cursor)
        seen_refs |= {r.raw["acc_no"] for r in page.records}
        if page.complete:
            break
        cursor = PageCursor(mark=page.last_mark, last_key=page.last_key)
    else:
        pytest.fail("the oversized tie group never completed within the tick budget")

    assert seen_refs == {f"300-T{i:04d}" for i in range(tie_count)}, (
        "every row in the tie group must be staged exactly once"
    )
    assert max(page_size_binds) <= 2 * page_size, (
        f"the bound page_size parameter must stay close to page_size={page_size} "
        f"on every page - it grew to {max(page_size_binds)} as the tie group's "
        f"own tie_refs list accumulated (unbounded per-page statement size)"
    )


# ── F6 - row cap inside the streaming loop ──────────────────────────────────


def test_the_row_cap_fires_before_materialising_the_whole_result(
    session_factory, monkeypatch, consumer,
):
    import modules.autocount.sql_source.source as src_mod
    from modules.autocount.sources import SourceContext
    from modules.autocount.services.company_service import CompanyService

    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(40)
    _insert_rows(engine, rows)
    monkeypatch.setattr(src_mod, "STREAM_BATCH", 3, raising=False)

    db = session_factory()
    from modules.autocount.models import AcCompany, AcEntityConfig

    company = db.query(AcCompany).filter(AcCompany.id == company_id).one()
    config = db.query(AcEntityConfig).filter(
        AcEntityConfig.tenant_id == DEFAULT_TENANT_ID, AcEntityConfig.company_id == company_id,
        AcEntityConfig.entity_type == ENTITY_CUSTOMER,
    ).one()
    source = src_mod.SqlDbSource(
        SourceContext(
            db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
            company_service=CompanyService(db),
        ),
        entity_type=ENTITY_CUSTOMER, row_limit=5,
    )

    counts = {"n": 0}
    from sqlalchemy.engine.cursor import CursorResult

    original_partitions = CursorResult.partitions

    def counting_partitions(self, size=None):
        for batch in original_partitions(self, size):
            counts["n"] += len(batch)
            yield batch

    monkeypatch.setattr(CursorResult, "partitions", counting_partitions)

    with pytest.raises(Exception):
        source.fetch_page(src_mod.PageCursor())

    assert counts["n"] <= 5 + 3, (
        f"fetch_page must stop pulling once the row cap is exceeded, "
        f"checked PER STREAM_BATCH partition like `_read` already does - "
        f"pulled {counts['n']} rows before raising (row_limit=5, "
        f"STREAM_BATCH=3)"
    )


# ── F7 - activity rows for a paged run ───────────────────────────────────────


def _activity_rows(db, tenant_id: str = DEFAULT_TENANT_ID) -> List[IntegrationActivity]:
    return (
        db.query(IntegrationActivity)
        .filter(IntegrationActivity.tenant_id == tenant_id, IntegrationActivity.source == "autocount")
        .all()
    )


def test_a_paged_run_writes_the_same_activity_rows_as_the_legacy_branch(
    session_factory, monkeypatch, consumer,
):
    company_id, sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(2))

    db = session_factory()
    job = _run(db, company_id, RUN_MODE_MANUAL)
    assert job.status == JOB_DONE

    activity = [
        r for r in _activity_rows(db, DEFAULT_TENANT_ID)
        if r.operation == f"sync {ENTITY_CUSTOMER}" and r.status == ACTIVITY_SUCCESS
    ]
    assert len(activity) == 1, (
        f"a successful paged run must write ONE {ACTIVITY_SUCCESS} activity "
        f"row (window + counts), exactly like the legacy branch - found "
        f"{len(activity)}"
    )

    # A failing paged run (delete guard) must ALSO write an ACTIVITY_ERROR row.
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM debtor")
    job2 = _run(db, company_id, RUN_MODE_RECONCILE)
    assert job2.status != JOB_DONE or True  # outcome checked via the run row below
    run2 = _run_row(db, company_id, job2.id)
    assert run2.outcome == RUN_FAILED

    error_activity = [
        r for r in _activity_rows(db, DEFAULT_TENANT_ID)
        if r.operation == f"sync {ENTITY_CUSTOMER}" and r.status == ACTIVITY_ERROR
    ]
    assert len(error_activity) == 1, (
        f"a FAILED paged run must ALSO write one {ACTIVITY_ERROR} activity "
        f"row - found {len(error_activity)}"
    )


# ── R-S1 - an incremental paged run cancels a stale parked delete intent ────


def test_an_incremental_run_cancels_a_parked_delete_intent_whose_ref_reappears(
    session_factory, monkeypatch, consumer,
):
    from modules.autocount.models import ETL_STATUS_DRAFT

    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(2)
    _insert_rows(engine, rows)
    ref_r = f"{DB_NAME}:{rows[1][0]}"

    db = session_factory()
    seed = _run(db, company_id, RUN_MODE_MANUAL)
    assert seed.status == JOB_DONE

    # A draft task never auto-pushes - the delete intent PARKS, exactly the
    # scenario the finding names ("on a draft task").
    _config_row(db, company_id).etl_status = ETL_STATUS_DRAFT
    db.commit()

    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM debtor WHERE acc_no = ?", (rows[1][0],))
    reconcile_job = _run(db, company_id, RUN_MODE_RECONCILE)
    assert reconcile_job.status == JOB_NEEDS_REVIEW  # a draft task never auto-pushes
    delete_row = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.source_ref == ref_r,
            AcStagedRecord.op == STAGED_OP_DELETE,
        )
        .one()
    )
    assert delete_row.status == STAGED  # parked, on a draft/paused-equivalent state

    # R reappears at source with a NEW, newest last_modified.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO debtor VALUES (?, ?, ?, ?)",
            (rows[1][0], "Reappeared", "r@x.com", "2026-12-01 00:00:00"),
        )
    incremental_job = _run(db, company_id, RUN_MODE_INCREMENTAL)
    assert incremental_job.status == JOB_NEEDS_REVIEW

    db.refresh(delete_row)
    assert delete_row.status == STAGED_DISCARDED, (
        "R reappeared and was staged fresh by an INCREMENTAL paged run - the "
        "stale parked delete intent for the SAME ref must be cancelled the "
        "same way a completed reconcile already cancels one, not left "
        "STAGED to fire later against a document that is back"
    )


# ── R-S6 - a genuine legacy cursor resumes as a plain incremental ──────────


def test_a_bare_legacy_cursor_resumes_as_a_plain_incremental(
    session_factory, monkeypatch, consumer,
):
    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(3)
    _insert_rows(engine, rows)

    db = session_factory()
    seed = _run(db, company_id, RUN_MODE_MANUAL)
    assert seed.status == JOB_DONE

    # A REAL pre-migration watermark row - only the two legacy keys, no
    # "pass"/"tieRefs" at all (every row on a real company predates this
    # slice).
    watermark = _watermark_row(db, company_id)
    legacy_mark = watermark.cursor_json[CURSOR_MARK]
    watermark.cursor_json = {CURSOR_COLUMN: "last_modified", CURSOR_MARK: legacy_mark}
    db.commit()

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO debtor VALUES (?, ?, ?, ?)",
            ("300-NEW1", "Brand New", "n@x.com", "2026-12-31 00:00:00"),
        )

    job2 = _run(db, company_id, RUN_MODE_INCREMENTAL)
    assert job2.status == JOB_DONE
    run2 = _run_row(db, company_id, job2.id)

    staged_for_job2 = (
        db.query(AcStagedRecord)
        .filter(AcStagedRecord.tenant_id == DEFAULT_TENANT_ID, AcStagedRecord.job_id == job2.id)
        .all()
    )
    assert len(staged_for_job2) == 1, (
        f"only the ONE new row after the legacy mark must be (re)staged - "
        f"rows at or before it must not be re-fetched as changes - got "
        f"{len(staged_for_job2)} staged rows"
    )
    assert staged_for_job2[0].source_ref == f"{DB_NAME}:300-NEW1"
    assert run2.added_count == 1
    assert run2.updated_count == 0


# ── R-NIT - the zero-rows guard must not misfire on a later page ───────────


def test_a_later_pages_empty_read_completes_normally_not_a_guard_trip(
    session_factory, monkeypatch, consumer,
):
    """Round 3b: ``fetch_page`` now peeks ``page_size + 1`` rows to know
    completion from its OWN read, so an EMPTY page is always the pass's
    LAST page (0 raw rows can never be a page with more still to come) -
    the "a later page reads empty but the pass has more pages left" shape
    this test originally built no longer exists. What still must hold: the
    completed-pass guard reads the PASS's CUMULATIVE ``rows_scanned``
    (across every page/run so far), not this one page's own count - so a
    pass whose FIRST page (this run's own page) genuinely read some rows,
    followed by a LATER page (a later run, same pass) whose own read comes
    back empty purely because its own boundary row was concurrently
    deleted, must complete normally, never trip the zero-rows guard (3
    known rows exist for this entity; the pass's cumulative scan is 1, not
    0)."""
    from app.config import settings as cfg

    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(3)
    _insert_rows(engine, rows)

    db = session_factory()
    seed = _run(db, company_id, RUN_MODE_MANUAL)
    assert seed.status == JOB_DONE

    monkeypatch.setattr(cfg, "autocount_page_size", 1, raising=False)
    monkeypatch.setattr(cfg, "autocount_run_time_budget_seconds", 0, raising=False)

    # Page 1/N: page_size=1 peeks 2 rows out of 3 -> not complete, one row
    # (rows[0]) staged, cumulative rows_scanned = 1.
    run1 = _run_row(db, company_id, _run(db, company_id, RUN_MODE_RECONCILE).id)
    assert run1.truncated is True

    # Both remaining rows vanish at source between page 1 and page 2 - a
    # normal concurrent edit mid-pass, not a mass wipe (page 1 already
    # proved the pass is reading real data).
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM debtor WHERE acc_no = ?", (rows[1][0],))
        conn.exec_driver_sql("DELETE FROM debtor WHERE acc_no = ?", (rows[2][0],))

    # Page 2's own raw read is genuinely empty (0 rows) purely because its
    # own boundary rows are gone - 0 <= page_size means THIS page completes
    # the pass, but the pass's CUMULATIVE scan (1, from page 1) is not 0, so
    # the zero-rows guard must not fire.
    run2 = _run_row(db, company_id, _run(db, company_id, RUN_MODE_RECONCILE).id)
    assert run2.outcome == RUN_SUCCESS, (
        f"a later page's empty raw read (its own boundary rows concurrently "
        f"deleted) must complete the pass normally, not trip the zero-rows "
        f"guard - got outcome={run2.outcome!r} error={run2.error!r}"
    )


def test_a_whole_empty_pass_with_known_rows_still_trips_the_guard(
    session_factory, monkeypatch, consumer,
):
    """Control/mutation-pair for the test above - the guard must still fire
    when the ENTIRE population vanishes on the FIRST read of a pass."""
    company_id, sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(5))
    db = session_factory()
    seed = _run(db, company_id, RUN_MODE_MANUAL)
    assert seed.status == JOB_DONE
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM debtor")

    job = _run(db, company_id, RUN_MODE_RECONCILE)
    run = _run_row(db, company_id, job.id)
    assert run.outcome == RUN_FAILED
    assert "0 rows" in (run.error or "") or "threshold" in (run.error or "").lower()


# ── R-S7 - job progress total set before the first page stages ────────────


def test_progress_total_is_set_before_the_first_page_is_staged(
    session_factory, monkeypatch, consumer,
):
    company_id, sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(2))

    calls: List[str] = []
    real_set_total = JobService.set_total
    real_advance = JobService.advance

    def traced_set_total(self, job, total):
        calls.append("set_total")
        return real_set_total(self, job, total)

    def traced_advance(self, job, **kw):
        calls.append("advance")
        return real_advance(self, job, **kw)

    monkeypatch.setattr(JobService, "set_total", traced_set_total)
    monkeypatch.setattr(JobService, "advance", traced_advance)

    db = session_factory()
    job = _run(db, company_id, RUN_MODE_MANUAL)
    assert job.status == JOB_DONE

    assert "set_total" in calls, "set_total was never called"
    assert "advance" in calls, "advance was never called"
    assert calls.index("set_total") < calls.index("advance"), (
        f"set_total must be observed BEFORE the first page's advance call - "
        f"got call order {calls[:6]}..."
    )
