"""AutoCount bulk document load - RUN LOOP behaviour (plan sprint-5/03, S1-S3).

RED tests written BEFORE the coder, from the UAC
(`documentation/plans/sprint-5/03-autocount-bulk-document-load-acceptance-
criteria.md`, AC-03-01..24) and the plan
(`03-autocount-bulk-document-load.md` sections 2.2-2.4, 3).

Every test here drives a REAL job end to end through
``JobService.create_and_enqueue`` (eager mode runs ``run_autocount_sync``
inline, exactly like ``tests/test_autocount_reconcile_push.py`` already
does) rather than importing not-yet-built internals directly - the run
LOOP's orchestration (paging, the time budget, change-only staging, the
watermark rule, seen stamps, deletes-at-completion) all live inside
``sync.py``'s handler body, so the black-box, job-level assertion is the
right level for this file. The PAGING MECHANICS themselves (the derived-
table wrap, the hash-diff-before-lines rule, tie handling) are pinned
directly against ``SqlDbSource`` in ``tests/test_autocount_sql_db_source.py``
instead.

ASSUMPTIONS this file makes about not-yet-built names (so the coder can
match them, per the plan's own naming):

* ``app.config.Settings`` gains two fields, ``autocount_page_size`` (default
  2000) and ``autocount_run_time_budget_seconds`` (default 600) - read at
  CALL time (not cached at import time) by ``sync.py``'s run loop, so
  monkeypatching the shared ``app.config.settings`` singleton instance
  (``raising=False`` - the attribute does not exist yet) is enough to steer a
  run without a subprocess restart. Setting ``autocount_run_time_budget_
  seconds = 0`` deterministically cuts a run after its FIRST page (any
  nonzero wall-clock time elapses before the check), because plan section
  2.2's ``while True`` loop checks ``page.complete`` BEFORE the budget - a
  page that is itself the pass's last, short page completes the pass and
  breaks the loop for that reason instead, never reading as "truncated".
* A watermarked ``sql_db`` task's run loop (``sync.run_autocount_sync``) now
  reads in a page loop (``SqlDbSource.fetch_page``/``PageCursor``/
  ``PageResult`` - plan section 2.1/2.2) instead of one ``fetch_changes``
  call; the ``AcWatermark.cursor_json`` shape gains a ``"pass"`` key
  (``{"kind", "startedAt", "pagesDone", "complete"}``) alongside the
  existing watermark-column/mark keys - both read via
  ``watermark_row.cursor_json`` directly in these tests (no schema change,
  per plan D7).
* This new run-loop shape (paging, change-only staging, watermark-advances-
  past-failures, seen-stamps, deletes-only-at-completion) applies ONLY to a
  ``sql_db`` task WITH a watermark column configured (plan section 2.2's own
  header: "``run_autocount_sync``, sql_db branch with a watermark column") -
  the vendor/API path (GRN, ``tests/test_autocount_pipeline.py``) is
  UNCHANGED, so its "watermark holds on any failed document" tests are NOT
  reversed and are not touched here.
* ``ac_watermark.last_error`` on a batch with N mapping failures (N > 0)
  reads ``"N record(s) failed to map; see staged records"`` - never
  "watermark held" (AC-03-11; this DOES change the sql_db branch's existing
  wording, but no existing test pins the old sql_db wording - grepped clean).

Fixture shape mirrors ``tests/test_autocount_reconcile_push.py``: one
in-process SQLite ``debtor`` table per test (through
``RUNTIME.put_engine``), an ACTIVE ``sql_db`` customer task pointed at a
scripted Sorento consumer (``httpx.MockTransport``), driven with
``JobService.create_and_enqueue(type=AUTOCOUNT_SYNC, ...)``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.jobs.service import JobService
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import (
    JOB_ABORTED,
    JOB_DONE,
    BackgroundJob,
)
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    RUN_ABORTED,
    RUN_MODE_INCREMENTAL,
    RUN_MODE_MANUAL,
    RUN_MODE_RECONCILE,
    RUN_SUCCESS,
    STAGED,
    STAGED_FAILED,
    STAGED_OP_DELETE,
    STAGED_PUSHED,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
    AcRowHash,
    AcStagedRecord,
    AcSyncRun,
    AcWatermark,
)
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sql_source.runtime import RUNTIME
from modules.autocount.sql_source.source import CURSOR_KEY_COLUMNS, CURSOR_MARK
from modules.autocount.sync import AUTOCOUNT_SYNC

PASSWORD = "S3cret!Pa55"
DB_NAME = "AED_BULK"
CODE = "SRT"

QUERY = "SELECT acc_no, company_name, email, last_modified FROM debtor"
RESULT_COLUMNS = ["acc_no", "company_name", "email", "last_modified"]


# ── shared fixture plumbing (each test seeds its own row data) ─────────────


def _source_engine() -> sa.engine.Engine:
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE debtor (acc_no TEXT PRIMARY KEY, company_name TEXT, "
            "email TEXT, last_modified TEXT)"
        )
    return engine


def _insert_rows(engine: sa.engine.Engine, rows: List[tuple]) -> None:
    with engine.begin() as conn:
        for row in rows:
            conn.exec_driver_sql("INSERT INTO debtor VALUES (?, ?, ?, ?)", row)


def _rows(n: int, *, start_minute: int = 1) -> List[tuple]:
    """``n`` distinct rows, STRICTLY increasing ``last_modified`` - a
    deterministic page/watermark order.

    Review-round fix: the earlier version formatted the hour as
    ``(start_hour + i) % 24``, which WRAPS back to 0 past 24 rows - every
    test seeding more than a day's worth of rows (the 100/200-row change-
    only-staging and delete-guard tests in this file) got a mark sequence
    that silently stopped increasing and repeated, which would have made
    any assertion keyed on "the max mark seen" or "strictly after" unsound
    for exactly the tests that most need a trustworthy ordering. A real
    ``timedelta`` (one minute per row, from a fixed base) never wraps for
    any ``n`` this file plausibly seeds.
    """
    base = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
    return [
        (
            f"300-B{i:04d}",
            f"Company {i}",
            f"c{i}@x.com",
            (base + timedelta(minutes=start_minute + i)).strftime("%Y-%m-%d %H:%M:%S"),
        )
        for i in range(n)
    ]


def _connection(db, provider: str, config, credentials):
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID,
        provider=provider,
        type="erp" if provider != "sorento" else "consumer",
        name=f"{provider} conn",
        config_json=config,
        credentials_json=encrypt_secret(credentials),
        is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db) -> AcCompany:
    api = _connection(
        db, "autocount", {"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        {"appId": "app-1", "password": "secret"},
    )
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name=DB_NAME,
        company_name="AED Bulk Sdn Bhd", name="AED Bulk", is_active=True,
    )
    db.add(company)
    db.flush()
    CompanyService(db).seed_company_defaults(DEFAULT_TENANT_ID, company.id)
    db.commit()
    db.refresh(company)
    return company


def _map_customer(db, company, *, email_required: bool = False) -> None:
    flat = {"code": "acc_no", "name": "company_name", "email": "email"}
    rows = (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.tenant_id == DEFAULT_TENANT_ID,
            AcFieldMapping.company_id == company.id,
            AcFieldMapping.entity_type == ENTITY_CUSTOMER,
        )
        .all()
    )
    for row in rows:
        path = flat.get(row.canonical_field)
        if path is not None:
            row.source_path = path
            if email_required and row.canonical_field == "email":
                row.is_required = True
        else:
            row.is_enabled = False
    db.commit()


class Consumer:
    """A scripted Sorento. ``script`` maps a source_ref to a per-call verdict
    sequence; unlisted refs always succeed."""

    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []
        self.script: Dict[str, List[str]] = {}

    def verdict_for(self, ref: str) -> str:
        queue = self.script.get(ref)
        if not queue:
            return "created"
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def _upsert(self, body: Dict[str, Any]) -> httpx.Response:
        records = body.get("records") or []
        out = []
        summary = {"total": len(records), "created": 0, "updated": 0, "failed": 0, "retryable": 0}
        for r in records:
            verdict = self.verdict_for(r["source_ref"])
            summary[verdict if verdict != "created" else "created"] = summary.get(
                verdict if verdict != "created" else "created", 0
            ) + 1
            out.append({"source_ref": r["source_ref"], "outcome": verdict, "entity_id": "x"})
        return httpx.Response(200, json={"summary": summary, "records": out})

    def _deletions(self, body: Dict[str, Any]) -> httpx.Response:
        refs = body.get("source_refs") or []
        return httpx.Response(
            200,
            json={
                "summary": {
                    "total": len(refs), "deleted": len(refs),
                    "deactivated": 0, "not_found": 0, "failed": 0,
                },
                "records": [
                    {"source_ref": r, "outcome": "deleted", "entity_id": "x"} for r in refs
                ],
            },
        )

    @property
    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content or b"{}")
            self.requests.append(
                {"path": request.url.path, "params": dict(request.url.params), "json": body}
            )
            if request.url.path.endswith("/deletions"):
                return self._deletions(body)
            return self._upsert(body)

        return httpx.MockTransport(handle)


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


def _make_rig(session_factory, *, email_required: bool = False):
    """One ACTIVE, watermarked ``sql_db`` customer task pointed at Sorento -
    the debtor table starts EMPTY, each test inserts its own rows."""
    db = session_factory()
    sql_conn = _connection(
        db, "sql_database",
        {"dbType": "postgresql", "host": "db.example.com", "port": "5432",
         "database": DB_NAME, "username": "readonly"},
        {"password": PASSWORD},
    )
    engine = _source_engine()
    RUNTIME.put_engine(sql_conn.id, engine)
    company = _company(db)
    sorento = _connection(
        db, "sorento", {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"}
    )
    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id, sink_impl="sorento",
        sink_connection_id=sorento.id, sorento_company_code=CODE,
    )
    config = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == DEFAULT_TENANT_ID,
            AcEntityConfig.company_id == company.id,
            AcEntityConfig.entity_type == ENTITY_CUSTOMER,
        )
        .one()
    )
    config.source_impl = "sql_db"
    config.source_config = {
        "connectionId": sql_conn.id, "query": QUERY, "keyColumns": ["acc_no"],
        "watermarkColumn": "last_modified", "comparedColumns": [],
        "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
    }
    config.result_columns = list(RESULT_COLUMNS)
    config.etl_status = ETL_STATUS_ACTIVE
    db.commit()
    _map_customer(db, company, email_required=email_required)
    company_id, sql_conn_id = company.id, sql_conn.id
    db.close()
    return company_id, sql_conn_id, engine


def _run(db, company_id: str, mode: str) -> BackgroundJob:
    job = JobService(db).create_and_enqueue(
        type=AUTOCOUNT_SYNC,
        tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company_id, "entityType": ENTITY_CUSTOMER, "mode": mode},
    )
    db.refresh(job)
    return job


def _run_row(db, company_id: str, job_id: str) -> AcSyncRun:
    return (
        db.query(AcSyncRun)
        .filter(AcSyncRun.tenant_id == DEFAULT_TENANT_ID, AcSyncRun.job_id == job_id)
        .one()
    )


def _config_row(db, company_id: str) -> AcEntityConfig:
    return (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == DEFAULT_TENANT_ID,
            AcEntityConfig.company_id == company_id,
            AcEntityConfig.entity_type == ENTITY_CUSTOMER,
        )
        .one()
    )


def _watermark_row(db, company_id: str) -> AcWatermark:
    return (
        db.query(AcWatermark)
        .filter(
            AcWatermark.tenant_id == DEFAULT_TENANT_ID,
            AcWatermark.company_id == company_id,
            AcWatermark.entity_type == ENTITY_CUSTOMER,
        )
        .one()
    )


def _staged_for_ref(db, company_id: str, ref: str) -> List[AcStagedRecord]:
    return (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.source_ref == ref,
        )
        .order_by(AcStagedRecord.created_at.asc())
        .all()
    )


def _hashes(db, company_id: str) -> Dict[str, str]:
    return {
        r.source_ref: r.row_hash
        for r in db.query(AcRowHash).filter(
            AcRowHash.tenant_id == DEFAULT_TENANT_ID,
            AcRowHash.company_id == company_id,
            AcRowHash.entity_type == ENTITY_CUSTOMER,
        )
    }


# ── S1: budget + continuation (AC-03-03/04/08) ──────────────────────────────


def test_the_budget_cuts_a_run_and_the_next_run_resumes_at_the_cursor(
    session_factory, monkeypatch, consumer
):
    monkeypatch.setattr(settings, "autocount_page_size", 2, raising=False)
    monkeypatch.setattr(settings, "autocount_run_time_budget_seconds", 0, raising=False)

    company_id, sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(5))  # 3 pages of 2/2/1 at page_size=2

    db = session_factory()
    job1 = _run(db, company_id, RUN_MODE_MANUAL)
    run1 = _run_row(db, company_id, job1.id)

    assert run1.outcome == RUN_SUCCESS
    assert run1.truncated is True, "a run cut by the budget must still be a SUCCESS"
    assert "page" in (run1.error or "").lower(), (
        f"the truncation message must name the page reached - got {run1.error!r}"
    )
    assert run1.rows_scanned == 2

    watermark = _watermark_row(db, company_id)
    cursor = watermark.cursor_json or {}
    assert cursor.get(CURSOR_MARK) == "2026-08-01 00:02:00", (
        "the cursor must point at the LAST mark taken on the truncated page"
    )

    config = _config_row(db, company_id)
    assert config.next_incremental_at is not None
    assert config.next_incremental_at <= datetime.now(timezone.utc) + timedelta(seconds=5), (
        "next_incremental_at must be armed for ~now so the next sweep tick fires immediately"
    )

    # The next tick resumes at the cursor - it must NOT re-read page 1.
    job2 = _run(db, company_id, RUN_MODE_MANUAL)
    run2 = _run_row(db, company_id, job2.id)
    assert run2.rows_scanned == 2, "run 2 must resume at page 2, not re-read page 1"
    db.close()


def test_a_short_last_page_completes_the_pass_and_the_next_run_is_incremental(
    session_factory, monkeypatch, consumer
):
    monkeypatch.setattr(settings, "autocount_page_size", 2, raising=False)
    monkeypatch.setattr(settings, "autocount_run_time_budget_seconds", 0, raising=False)

    company_id, sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(3))  # pages of 2, then 1 (short - completes)

    db = session_factory()
    job1 = _run(db, company_id, RUN_MODE_MANUAL)
    run1 = _run_row(db, company_id, job1.id)
    assert run1.truncated is True  # page 1 of 2, budget=0 cuts it

    # job1's truncation force-armed next_incremental_at to "now" (the
    # continuation mechanism) - capture that BEFORE job2 so the assertion
    # below proves job2 (which completes the pass) does NOT re-stamp it,
    # rather than the earlier, vacuous "is None or > now - 1s" check (true
    # for almost any timestamp, including the stale one job1 already left).
    before_incremental_at = _config_row(db, company_id).next_incremental_at

    job2 = _run(db, company_id, RUN_MODE_MANUAL)
    run2 = _run_row(db, company_id, job2.id)
    assert run2.rows_scanned == 1
    assert run2.truncated is False, (
        "a page shorter than the page size completes the PASS - it must never "
        "read as truncated even though the budget is exhausted"
    )

    watermark = _watermark_row(db, company_id)
    cursor = watermark.cursor_json or {}
    assert (cursor.get("pass") or {}).get("complete") is True

    config = _config_row(db, company_id)
    assert config.next_incremental_at == before_incremental_at, (
        "a completed (non-truncated) pass must NOT force next_incremental_at "
        "to now the way a truncated run does - job2 must leave the schedule "
        "field exactly as job1's truncation left it, not re-stamp it"
    )

    # A further tick is now an ORDINARY incremental - nothing changed, 0 rows.
    job3 = _run(db, company_id, RUN_MODE_INCREMENTAL)
    run3 = _run_row(db, company_id, job3.id)
    assert run3.rows_scanned == 0
    db.close()


def test_an_abort_stops_after_the_page_in_flight(session_factory, monkeypatch, consumer):
    """AC-03-08. An abort committed on a SEPARATE session while page 2's own
    SELECT is executing must still let page 2 finish and stage, but must stop
    the run before page 3 is ever read - mirrors the real-interleave abort
    test in ``tests/test_autocount_pipeline.py`` (there via the HTTP
    transport hook, here via a SQLAlchemy execute-count hook, since a DB-
    source page is exactly one executed SELECT)."""
    monkeypatch.setattr(settings, "autocount_page_size", 2, raising=False)
    # Generous budget - only the operator abort should stop this run.
    monkeypatch.setattr(settings, "autocount_run_time_budget_seconds", 600, raising=False)

    company_id, sql_id, engine = _make_rig(session_factory)
    _insert_rows(engine, _rows(6))  # 3 pages of 2

    calls = {"n": 0}
    aborting = session_factory()

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if "debtor" not in statement.lower():
            return
        calls["n"] += 1
        if calls["n"] == 2:
            # The SECOND page's SELECT is about to run - commit the abort on a
            # DIFFERENT session before this statement returns.
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
    job = _run(db, company_id, RUN_MODE_MANUAL)
    run = _run_row(db, company_id, job.id)

    assert job.status == JOB_ABORTED
    assert run.outcome == RUN_ABORTED
    assert run.rows_scanned == 4, "pages 1 and 2 (4 rows) were read; page 3 never was"

    staged_refs = {
        r.source_ref
        for r in db.query(AcStagedRecord).filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company_id,
        )
    }
    assert len(staged_refs) == 4, "rows staged before the abort landed must stay staged"

    sa.event.remove(engine, "before_cursor_execute", before_cursor_execute)
    aborting.close()
    db.close()


# ── S2: change-only staging + watermark independent of failures ────────────
# (AC-03-09/10/11/12/13)


def test_unchanged_rows_are_not_staged_and_the_log_counts_them(
    session_factory, monkeypatch, consumer
):
    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(100)
    _insert_rows(engine, rows)

    db = session_factory()
    job1 = _run(db, company_id, RUN_MODE_MANUAL)
    assert job1.status == JOB_DONE

    # Change exactly 3 rows' compared column (company_name); everything else
    # (including its own last_modified) is untouched.
    changed_refs = [f"{DB_NAME}:300-B0003", f"{DB_NAME}:300-B0041", f"{DB_NAME}:300-B0099"]
    with engine.begin() as conn:
        for ref in changed_refs:
            acc_no = ref.split(":")[1]
            conn.exec_driver_sql(
                "UPDATE debtor SET company_name = 'Changed', "
                "last_modified = '2026-09-01 00:00:00' WHERE acc_no = ?",
                (acc_no,),
            )

    job2 = _run(db, company_id, RUN_MODE_RECONCILE)
    assert job2.status == JOB_DONE
    run2 = _run_row(db, company_id, job2.id)

    assert run2.rows_scanned == 100
    assert run2.updated_count == 3
    assert run2.added_count == 0

    staged_for_job2 = (
        db.query(AcStagedRecord)
        .filter(AcStagedRecord.tenant_id == DEFAULT_TENANT_ID, AcStagedRecord.job_id == job2.id)
        .all()
    )
    assert len(staged_for_job2) == 3, (
        f"exactly the 3 changed rows must be staged - got {len(staged_for_job2)}"
    )

    db.refresh(job2)
    log_text = " ".join(entry.get("message", "") for entry in (job2.logs_json or []))
    assert "97 unchanged, skipped" in log_text, log_text
    db.close()


def test_a_new_ref_is_staged_as_an_add(session_factory, monkeypatch, consumer):
    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(20)
    _insert_rows(engine, rows)

    db = session_factory()
    job1 = _run(db, company_id, RUN_MODE_MANUAL)
    assert job1.status == JOB_DONE

    # 3 rows change, 1 brand-new row appears - the addition must still stage
    # and push cleanly alongside change-only filtering of the rest.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE debtor SET company_name = 'Changed', last_modified = '2026-09-01 00:00:00' "
            "WHERE acc_no IN ('300-B0001', '300-B0002', '300-B0003')"
        )
        conn.exec_driver_sql(
            "INSERT INTO debtor VALUES ('300-NEW1', 'Brand New', 'n@x.com', '2026-09-02 00:00:00')"
        )

    job2 = _run(db, company_id, RUN_MODE_RECONCILE)
    assert job2.status == JOB_DONE
    run2 = _run_row(db, company_id, job2.id)

    assert run2.added_count == 1
    assert run2.updated_count == 3

    staged_for_job2 = (
        db.query(AcStagedRecord)
        .filter(AcStagedRecord.tenant_id == DEFAULT_TENANT_ID, AcStagedRecord.job_id == job2.id)
        .all()
    )
    assert len(staged_for_job2) == 4

    new_ref_rows = _staged_for_ref(db, company_id, f"{DB_NAME}:300-NEW1")
    assert len(new_ref_rows) == 1
    assert new_ref_rows[0].status == STAGED_PUSHED
    db.close()


def test_the_watermark_advances_past_mapping_failures(session_factory, monkeypatch, consumer):
    company_id, sql_id, engine = _make_rig(session_factory, email_required=True)
    rows = _rows(10)
    # Blank the email on two rows - a required mapped field, so mapping fails.
    rows[3] = (rows[3][0], rows[3][1], "", rows[3][3])
    rows[7] = (rows[7][0], rows[7][1], "", rows[7][3])
    _insert_rows(engine, rows)

    db = session_factory()
    job = _run(db, company_id, RUN_MODE_MANUAL)
    run = _run_row(db, company_id, job.id)

    assert run.failed_count == 2
    assert run.outcome == RUN_SUCCESS

    watermark = _watermark_row(db, company_id)
    max_mark = rows[-1][3]  # the last row's last_modified - the max seen
    assert (watermark.cursor_json or {}).get(CURSOR_MARK) == max_mark, (
        "the watermark/cursor must advance to the MAX mark seen on the page "
        "even though 2 rows failed to map"
    )
    assert watermark.last_modified_at == datetime.strptime(
        max_mark, "%Y-%m-%d %H:%M:%S"
    ).replace(tzinfo=timezone.utc)
    assert watermark.last_error == "2 record(s) failed to map; see staged records", (
        watermark.last_error
    )
    assert "watermark held" not in (watermark.last_error or "").lower()

    failed_rows = (
        db.query(AcStagedRecord)
        .filter(AcStagedRecord.tenant_id == DEFAULT_TENANT_ID, AcStagedRecord.job_id == job.id,
                 AcStagedRecord.status == STAGED_FAILED)
        .all()
    )
    assert len(failed_rows) == 2
    assert all(r.error for r in failed_rows)
    db.close()


def test_a_failed_row_keeps_no_hash_and_is_retried_by_the_next_full_pass(
    session_factory, monkeypatch, consumer
):
    company_id, sql_id, engine = _make_rig(session_factory, email_required=True)
    rows = _rows(5)
    rows[1] = (rows[1][0], rows[1][1], "", rows[1][3])  # bad - stays bad
    rows[3] = (rows[3][0], rows[3][1], "", rows[3][3])  # bad - gets fixed
    _insert_rows(engine, rows)
    bad_ref = f"{DB_NAME}:{rows[1][0]}"
    fixed_ref = f"{DB_NAME}:{rows[3][0]}"

    db = session_factory()
    job1 = _run(db, company_id, RUN_MODE_MANUAL)
    run1 = _run_row(db, company_id, job1.id)
    assert run1.failed_count == 2

    hashes = _hashes(db, company_id)
    assert bad_ref not in hashes
    assert fixed_ref not in hashes, "a failed row must keep NO hash at all"

    # Source data unchanged, then one is fixed - a reconcile re-fetches both
    # (no watermark filtering) since neither carries a hash to skip on.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE debtor SET email = 'fixed@x.com' WHERE acc_no = ?", (rows[3][0],)
        )

    job2 = _run(db, company_id, RUN_MODE_RECONCILE)
    run2 = _run_row(db, company_id, job2.id)

    assert run2.failed_count == 1, "only the still-bad row fails again"
    fixed_staged = _staged_for_ref(db, company_id, fixed_ref)
    assert fixed_staged[-1].status == STAGED_PUSHED

    bad_staged = _staged_for_ref(db, company_id, bad_ref)
    assert len(bad_staged) == 2, "the bad row gets a FRESH failed record each full pass"
    assert all(r.status == STAGED_FAILED for r in bad_staged)
    db.close()


def test_a_retryable_pending_row_is_offered_again_without_a_refetch(
    session_factory, monkeypatch, consumer
):
    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(2)
    _insert_rows(engine, rows)
    ref_a = f"{DB_NAME}:{rows[0][0]}"
    ref_b = f"{DB_NAME}:{rows[1][0]}"
    consumer.script[ref_a] = ["retryable", "created"]  # only the FIRST offer is retryable

    db = session_factory()
    job1 = _run(db, company_id, RUN_MODE_MANUAL)
    a_after_1 = _staged_for_ref(db, company_id, ref_a)
    assert len(a_after_1) == 1
    assert a_after_1[0].status == STAGED  # stayed pending
    b_after_1 = _staged_for_ref(db, company_id, ref_b)
    assert b_after_1[0].status == STAGED_PUSHED

    # Nothing changes at source - a reconcile re-reads BOTH refs unchanged.
    job2 = _run(db, company_id, RUN_MODE_RECONCILE)
    run2 = _run_row(db, company_id, job2.id)
    assert run2.added_count == 0
    assert run2.updated_count == 0

    a_after_2 = _staged_for_ref(db, company_id, ref_a)
    assert len(a_after_2) == 1, (
        "change-only staging must never duplicate the still-pending row just "
        "because the unchanged ref was re-read"
    )
    assert a_after_2[0].id == a_after_1[0].id
    assert a_after_2[0].job_id == job1.id, (
        "the ORIGINAL row is the one that gets pushed - it is not re-created"
    )
    assert a_after_2[0].status == STAGED_PUSHED, (
        "auto-push re-offers a pending row across jobs regardless of what "
        "this run staged"
    )
    db.close()


# ── S3: reconcile over pages (AC-03-16/17/19) ───────────────────────────────


def _reconcile_paging_rig(session_factory, monkeypatch, consumer, *, known_rows: int = 5):
    """``known_rows`` customers fully synced once (page size default, one
    page), then one is DELETED from the source before paging is turned on -
    the delete intent this leaves behind is what AC-03-16/17 diff against."""
    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(known_rows)
    _insert_rows(engine, rows)
    db = session_factory()
    seed_job = _run(db, company_id, RUN_MODE_MANUAL)
    assert seed_job.status == JOB_DONE
    deleted_ref = f"{DB_NAME}:{rows[-1][0]}"
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM debtor WHERE acc_no = ?", (rows[-1][0],))
    db.close()
    monkeypatch.setattr(settings, "autocount_page_size", 2, raising=False)
    monkeypatch.setattr(settings, "autocount_run_time_budget_seconds", 0, raising=False)
    return company_id, deleted_ref


def _sweep_tick(db, company_id: str, *, reconcile: bool) -> AcSyncRun:
    """Drive ONE tick through the REAL scheduler entry point
    (``scheduler._sweep_one``) rather than the direct ``JobService.
    create_and_enqueue`` helper ``_run`` uses - review-round ask: AC-03-16/17
    must be proven through the scheduler at least once, since that is the
    ACTUAL caller in production (a manual "Run now" is the only caller of
    the direct path)."""
    from modules.autocount.scheduler import _sweep_one

    # Identify the NEW run by id-set difference, never by "newest first"
    # ordering - two runs a fraction of a second apart share a `started_at`
    # SECOND on SQLite, and `AcSyncRun.id` is a random UUID, so an
    # `ORDER BY started_at DESC, id DESC` tiebreak is not actually
    # chronological and flakes exactly the way
    # `test_autocount_etl_task_routes.py`'s own runs-list test already
    # documents.
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


def test_deletes_are_staged_only_when_the_reconcile_pass_completes(
    session_factory, monkeypatch, consumer
):
    company_id, deleted_ref = _reconcile_paging_rig(session_factory, monkeypatch, consumer)
    db = session_factory()

    def delete_intents():
        return (
            db.query(AcStagedRecord)
            .filter(
                AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
                AcStagedRecord.company_id == company_id,
                AcStagedRecord.op == STAGED_OP_DELETE,
            )
            .all()
        )

    # page_size=2, 4 live rows: fetch_page peeks page_size+1 to know
    # completion from its OWN read (round 3) - page 1 (2 of 4 live rows)
    # reads 3 rows and trims the peeked-ahead one back off, so it is NOT
    # complete; page 2 reads the remaining 2 (an exact multiple, no
    # trailing empty page needed) and IS complete.
    job1 = _run(db, company_id, RUN_MODE_RECONCILE)  # page 1/2 (2 of 4 live rows)
    run1 = _run_row(db, company_id, job1.id)
    assert run1.truncated is True
    assert delete_intents() == [], "no delete intent before the pass completes"

    # page 2/2 - the last 2 live rows, completes - driven through the REAL
    # scheduler tick.
    run2 = _sweep_tick(db, company_id, reconcile=True)
    assert run2.truncated is False

    intents = delete_intents()
    assert [r.source_ref for r in intents] == [deleted_ref]
    db.close()


def test_the_pass_start_is_read_from_the_cursor_on_continuation(
    session_factory, monkeypatch, consumer
):
    company_id, _deleted_ref = _reconcile_paging_rig(session_factory, monkeypatch, consumer)
    db = session_factory()

    job1 = _run(db, company_id, RUN_MODE_RECONCILE)
    started_1 = ((_watermark_row(db, company_id).cursor_json or {}).get("pass") or {}).get(
        "startedAt"
    )
    assert started_1, "a truncated reconcile must record its pass start"

    # The continuation tick - driven through the REAL scheduler entry point.
    _sweep_tick(db, company_id, reconcile=True)
    started_2 = ((_watermark_row(db, company_id).cursor_json or {}).get("pass") or {}).get(
        "startedAt"
    )
    assert started_2 == started_1, (
        "the continuation run must read the SAME pass start from the stored "
        "cursor - never re-stamp it to the clock"
    )
    db.close()


def test_a_stale_cursor_missing_sql_key_columns_is_treated_as_unknown_not_a_reshape(
    session_factory, monkeypatch, consumer
):
    """Round 5 (S2) bootstrap rule: a cursor with NO ``sqlKeyColumns``
    fingerprint at all (a pre-round-5 row, never run under this check
    before) must be treated as "unknown, assume unchanged" - never a
    spurious identity reset (``sync.py``'s own comment: "a one-time,
    harmless bootstrap cost the first time a genuinely reshaped task runs
    after this code ships, never a risk to an untouched one").

    After one incremental run establishes a normal cursor (which now
    stamps ``sqlKeyColumns``), ``sqlKeyColumns`` is stripped back off to
    simulate exactly that legacy shape, then a second incremental tick is
    driven for real: every existing hash must survive, the top-level
    ``sqlWatermark``/``lastKey`` must be untouched, this run's own
    ``rows_scanned`` must be 0 (nothing new at source - a spurious reset
    would force a full re-read instead), and ``sqlKeyColumns`` must now be
    stamped with the task's current key columns (the bootstrap)."""
    company_id, sql_id, engine = _make_rig(session_factory)
    rows = _rows(5)
    _insert_rows(engine, rows)
    db = session_factory()

    job1 = _run(db, company_id, RUN_MODE_INCREMENTAL)
    assert job1.status == JOB_DONE
    hashes_before = _hashes(db, company_id)
    assert len(hashes_before) == 5

    watermark = _watermark_row(db, company_id)
    cursor_before = dict(watermark.cursor_json or {})
    assert CURSOR_KEY_COLUMNS in cursor_before, (
        "the seed run must already stamp sqlKeyColumns going forward"
    )
    watermark.cursor_json = {
        k: v for k, v in cursor_before.items() if k != CURSOR_KEY_COLUMNS
    }
    db.commit()

    job2 = _run(db, company_id, RUN_MODE_INCREMENTAL)
    run2 = _run_row(db, company_id, job2.id)
    assert run2.outcome == RUN_SUCCESS
    assert run2.rows_scanned == 0, (
        f"nothing changed at source - a legacy cursor with no sqlKeyColumns "
        f"must never be misread as a reshape (which would clear hashes and "
        f"force a full re-read) - got rows_scanned={run2.rows_scanned}"
    )

    hashes_after = _hashes(db, company_id)
    assert hashes_after == hashes_before, (
        "every existing hash must survive - a spurious identity reset "
        "would have cleared them all"
    )

    cursor_after = (_watermark_row(db, company_id).cursor_json) or {}
    assert cursor_after.get(CURSOR_MARK) == cursor_before.get(CURSOR_MARK), (
        "the top-level sqlWatermark must be unchanged"
    )
    assert cursor_after.get("lastKey") == cursor_before.get("lastKey"), (
        "the top-level lastKey must be unchanged"
    )
    assert cursor_after.get(CURSOR_KEY_COLUMNS) == ["acc_no"], (
        f"the bootstrap must stamp sqlKeyColumns with the task's current "
        f"key columns on the very next run - got "
        f"{cursor_after.get(CURSOR_KEY_COLUMNS)!r}"
    )
    db.close()


def test_a_schedule_only_save_leaves_hashes_and_the_cursor_untouched(
    session_factory, monkeypatch, consumer
):
    """A schedule-only ``update_task`` save (``incrementalMinutes``/
    ``reconcileMode``/``reconcileAt`` changed, everything else - query,
    keyColumns, watermarkColumn, comparedColumns, connectionId -
    byte-identical) is NOT in ``POPULATION_DEFINING_KEYS`` and does not
    touch ``watermarkColumn`` either, so neither the round-2 "clear the
    pass" branch nor the round-5 "keyColumns reshape resets identity"
    branch may fire: ``ac_row_hash`` rows, ``cursor_json`` (mark, lastKey,
    pass) and ``AcWatermark.last_modified_at`` must all survive a pure
    schedule edit byte-for-byte.

    ``update_task`` (unlike a run) re-validates the watermark column
    against a LIVE preview at save time - a plain TEXT sqlite column (this
    file's usual ``_source_engine``) always reads back as ``str``, which
    the watermark check rejects, so this test builds its own typed
    (``sqlite3.PARSE_DECLTYPES``) engine, exactly like
    ``test_autocount_document_mapping.py``'s ``_source_engine_typed``."""
    import sqlite3

    from modules.autocount.services.etl_service import EtlService

    db = session_factory()
    engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False, "detect_types": sqlite3.PARSE_DECLTYPES},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE debtor (acc_no TEXT PRIMARY KEY, company_name TEXT, "
            "email TEXT, last_modified TIMESTAMP)"
        )
    sql_conn = _connection(
        db, "sql_database",
        {"dbType": "postgresql", "host": "db.example.com", "port": "5432",
         "database": DB_NAME, "username": "readonly"},
        {"password": PASSWORD},
    )
    RUNTIME.put_engine(sql_conn.id, engine)
    company = _company(db)
    sorento = _connection(
        db, "sorento", {"baseUrl": "https://sorento.example.com"}, {"apiKey": "k"}
    )
    CompanyService(db).set_sink_target(
        DEFAULT_TENANT_ID, company.id, sink_impl="sorento",
        sink_connection_id=sorento.id, sorento_company_code=CODE,
    )
    config = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == DEFAULT_TENANT_ID,
            AcEntityConfig.company_id == company.id,
            AcEntityConfig.entity_type == ENTITY_CUSTOMER,
        )
        .one()
    )
    config.source_impl = "sql_db"
    config.source_config = {
        "connectionId": sql_conn.id, "query": QUERY, "keyColumns": ["acc_no"],
        "watermarkColumn": "last_modified", "comparedColumns": [],
        "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
    }
    config.result_columns = list(RESULT_COLUMNS)
    config.etl_status = ETL_STATUS_ACTIVE
    db.commit()
    _map_customer(db, company)
    company_id = company.id

    with engine.begin() as conn:
        for i in range(5):
            conn.execute(
                sa.text("INSERT INTO debtor VALUES (:acc, :name, :email, :lm)"),
                {
                    "acc": f"300-B{i:04d}", "name": f"Company {i}", "email": f"c{i}@x.com",
                    "lm": datetime(2026, 8, 1, 0, i + 1, 0),
                },
            )

    job1 = _run(db, company_id, RUN_MODE_INCREMENTAL)
    assert job1.status == JOB_DONE
    hashes_before = _hashes(db, company_id)
    assert len(hashes_before) == 5

    config_before = _config_row(db, company_id)
    source_config_before = dict(config_before.source_config)
    watermark_before = _watermark_row(db, company_id)
    cursor_before = dict(watermark_before.cursor_json or {})
    last_modified_before = watermark_before.last_modified_at

    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company_id, ENTITY_CUSTOMER,
        {
            **source_config_before,
            "incrementalMinutes": 30,
            "reconcileMode": "dailyAt",
            "reconcileAt": "03:00",
        },
    )

    hashes_after = _hashes(db, company_id)
    assert hashes_after == hashes_before, (
        "a schedule-only save must never touch ac_row_hash"
    )

    watermark_after = _watermark_row(db, company_id)
    cursor_after = watermark_after.cursor_json or {}
    assert cursor_after.get(CURSOR_MARK) == cursor_before.get(CURSOR_MARK), (
        "a schedule-only save must never touch the top-level sqlWatermark"
    )
    assert cursor_after.get("lastKey") == cursor_before.get("lastKey"), (
        "a schedule-only save must never touch the top-level lastKey"
    )
    assert cursor_after.get("pass") == cursor_before.get("pass"), (
        "a schedule-only save must never clear/touch cursor_json['pass']"
    )
    assert watermark_after.last_modified_at == last_modified_before, (
        "a schedule-only save must never touch AcWatermark.last_modified_at"
    )

    config_after = _config_row(db, company_id)
    assert config_after.source_config.get("incrementalMinutes") == 30
    assert config_after.source_config.get("reconcileAt") == "03:00"
    db.close()


def test_a_delete_guard_failure_clears_the_pass_for_the_next_reconcile(
    session_factory, monkeypatch, consumer
):
    """Deliberately does NOT touch ``autocount_page_size``/``..._budget`` -
    the precondition (a pass already "in progress" per the cursor) is seeded
    directly on ``AcWatermark.cursor_json`` so this test exercises ONLY the
    guard-failure-clears-the-pass rule (AC-03-19), independent of whether
    paging itself is wired yet."""
    company_id, sql_id, engine = _make_rig(session_factory)
    # A population comfortably over BOTH guard floors (ratio and absolute).
    rows = _rows(200)
    _insert_rows(engine, rows)
    db = session_factory()
    seed = _run(db, company_id, RUN_MODE_MANUAL)
    assert seed.status == JOB_DONE

    watermark = _watermark_row(db, company_id)
    watermark.cursor_json = {
        **(watermark.cursor_json or {}),
        "pass": {
            "kind": "reconcile", "startedAt": "2020-01-01T00:00:00+00:00",
            "pagesDone": 1, "complete": False,
        },
    }
    db.commit()

    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM debtor")  # every row vanishes

    job = _run(db, company_id, RUN_MODE_RECONCILE)
    run = _run_row(db, company_id, job.id)
    assert "threshold" in (run.error or "").lower() or "0 rows" in (run.error or "")

    pass_after_failure = (_watermark_row(db, company_id).cursor_json or {}).get("pass")
    assert not pass_after_failure, (
        "a guard failure must clear the in-progress pass, not leave a stale "
        "one for the next reconcile to wrongly resume"
    )
    db.close()
