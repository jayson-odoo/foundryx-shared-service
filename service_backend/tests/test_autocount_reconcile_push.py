"""Reconcile staging + delete push, end to end (plan 22 S3, AC-22-16/21/22).

Reuses the ``test_autocount_etl_task_routes.py`` rig shape (in-process SQLite
source through ``RUNTIME.put_engine``, ``httpx.MockTransport`` consumer) but
drives a RECONCILE run directly through ``JobService`` - there is no HTTP
affordance to force reconcile mode this slice (only the beat sweep and Run now
exist on the wire, and Run now is always ``manual``).

What this pins:

* a reconcile stages new refs as adds, changed refs as updates, absent refs as
  delete intents (no canonical payload);
* an ACTIVE task auto-pushes deletes through ``SorentoSink.delete_batch`` with
  per-record verdicts folded into the run row's ``deletedCount``;
* a delivered delete removes the row-hash so a later re-appearance stages as a
  fresh add, never a phantom update;
* a ``failed`` delete verdict quarantines the row (D13's rule, mirrored);
* the delete guard fails the WHOLE run - nothing staged, nothing pushed.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.jobs.service import JobService
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE, JOB_FAILED, JOB_NEEDS_REVIEW, BackgroundJob
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import (
    ETL_STATUS_ACTIVE,
    RUN_MODE_RECONCILE,
    STAGED,
    STAGED_DISCARDED,
    STAGED_FAILED,
    STAGED_OP_DELETE,
    STAGED_PUSHED,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
    AcRowHash,
    AcStagedRecord,
    AcSyncRun,
)
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sql_source.runtime import RUNTIME
from modules.autocount.sync import AUTOCOUNT_SYNC

PASSWORD = "S3cret!Pa55"
DB_NAME = "AED_2024"
CODE = "SRT"

QUERY = "SELECT acc_no, company_name, email, last_modified FROM debtor"
RESULT_COLUMNS = ["acc_no", "company_name", "email", "last_modified"]

ROWS = [
    ("300-A001", "Acme", "a@x.com", "2026-08-01 09:00:00"),
    ("300-A002", "Bolt", "b@x.com", "2026-08-02 09:00:00"),
    ("300-A003", "Cog", "c@x.com", "2026-08-03 09:00:00"),
]


def _source_engine() -> sa.engine.Engine:
    engine = sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE debtor (acc_no TEXT PRIMARY KEY, company_name TEXT, "
            "email TEXT, last_modified TEXT)"
        )
        for row in ROWS:
            conn.exec_driver_sql("INSERT INTO debtor VALUES (?, ?, ?, ?)", row)
    return engine


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
        company_name="AED Sdn Bhd", name="AED", is_active=True,
    )
    db.add(company)
    db.flush()
    CompanyService(db).seed_company_defaults(DEFAULT_TENANT_ID, company.id)
    db.commit()
    db.refresh(company)
    return company


def _map_customer(db, company) -> None:
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
        else:
            row.is_enabled = False
    db.commit()


class Consumer:
    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []
        self.responder = self.ok

    @staticmethod
    def ok(path: str, body: Dict[str, Any]) -> httpx.Response:
        if path.endswith("/deletions"):
            refs = body.get("source_refs") or []
            return httpx.Response(
                200,
                json={
                    "summary": {
                        "total": len(refs), "deleted": len(refs),
                        "deactivated": 0, "not_found": 0, "failed": 0,
                    },
                    "records": [
                        {"source_ref": r, "outcome": "deleted", "entity_id": "x"}
                        for r in refs
                    ],
                },
            )
        records = body.get("records") or []
        return httpx.Response(
            200,
            json={
                "summary": {
                    "total": len(records), "created": len(records),
                    "updated": 0, "failed": 0, "retryable": 0,
                },
                "records": [
                    {"source_ref": r["source_ref"], "outcome": "created", "entity_id": "x"}
                    for r in records
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
            return self.responder(request.url.path, body)

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


@pytest.fixture
def rig(session_factory):
    """An ACTIVE DB task, pointed at Sorento, whose initial load already ran
    (so ``ac_row_hash`` carries the 3 seed rows as its known population)."""
    db = session_factory()
    sql_conn = _connection(
        db, "sql_database",
        {"dbType": "postgresql", "host": "db.example.com", "port": "5432",
         "database": DB_NAME, "username": "readonly"},
        {"password": PASSWORD},
    )
    RUNTIME.put_engine(sql_conn.id, _source_engine())
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
    db.close()
    yield company_id
    RUNTIME.dispose_all()


def _reconcile(db, company_id: str) -> BackgroundJob:
    """Enqueue ONE reconcile run through the SAME pipeline the sweep uses -
    eager dev/test runs it inline, so the job is terminal on return."""
    job = JobService(db).create_and_enqueue(
        type=AUTOCOUNT_SYNC,
        tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company_id, "entityType": ENTITY_CUSTOMER, "mode": RUN_MODE_RECONCILE},
    )
    db.refresh(job)
    return job


def _run_row(db, company_id: str, job_id: str) -> AcSyncRun:
    return (
        db.query(AcSyncRun)
        .filter(AcSyncRun.tenant_id == DEFAULT_TENANT_ID, AcSyncRun.job_id == job_id)
        .one()
    )


def _seed(db, company_id: str) -> None:
    """One clean reconcile over the untouched 3-row fixture table - the
    ``ac_row_hash`` baseline every delete-detection test diffs against (a
    reconcile with NO known population reports zero deletes by design, since
    absence-from-nothing proves nothing)."""
    job = _reconcile(db, company_id)
    assert job.status == JOB_DONE


def _known_refs(db, company_id: str) -> set[str]:
    return {
        r.source_ref
        for r in db.query(AcRowHash).filter(
            AcRowHash.tenant_id == DEFAULT_TENANT_ID,
            AcRowHash.company_id == company_id,
            AcRowHash.entity_type == ENTITY_CUSTOMER,
        )
    }


# ── staging (AC-22-16) ────────────────────────────────────────────────────────


def _conn_for(db, company_id):
    from modules.autocount.models import AcEntityConfig as _C

    row = (
        db.query(_C)
        .filter(_C.tenant_id == DEFAULT_TENANT_ID, _C.company_id == company_id, _C.entity_type == ENTITY_CUSTOMER)
        .one()
    )
    return row.source_config["connectionId"]


def test_reconcile_stages_a_delete_and_it_pushes_with_a_deleted_verdict(
    session_factory, rig, consumer
):
    company_id = rig
    db = session_factory()
    conn_id = _conn_for(db, company_id)
    engine = RUNTIME.engine_for(conn_id, {}, {})
    _seed(db, company_id)
    consumer.requests.clear()
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM debtor WHERE acc_no = '300-A003'")

    job = _reconcile(db, company_id)
    assert job.status == JOB_DONE

    run = _run_row(db, company_id, job.id)
    assert run.mode == RUN_MODE_RECONCILE
    assert run.deleted_count == 1

    delete_row = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.op == STAGED_OP_DELETE,
        )
        .one()
    )
    assert delete_row.source_ref == f"{DB_NAME}:300-A003"
    assert delete_row.canonical_json is None
    assert delete_row.status == STAGED_PUSHED

    delete_calls = [r for r in consumer.requests if r["path"].endswith("/deletions")]
    assert len(delete_calls) == 1
    assert delete_calls[0]["json"]["source_refs"] == [f"{DB_NAME}:300-A003"]
    assert delete_calls[0]["json"]["companyCode"] == CODE
    db.close()


def test_a_delivered_delete_removes_the_row_hash_so_reappearance_stages_as_an_add(
    session_factory, rig, consumer
):
    """AC-22-21 - the whole point of removing the hash on a confirmed delete."""
    company_id = rig
    db = session_factory()
    conn_id = _conn_for(db, company_id)
    engine = RUNTIME.engine_for(conn_id, {}, {})
    _seed(db, company_id)
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM debtor WHERE acc_no = '300-A003'")
    _reconcile(db, company_id)
    assert f"{DB_NAME}:300-A003" not in _known_refs(db, company_id)

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO debtor VALUES ('300-A003', 'Cog', 'c@x.com', '2026-08-30 09:00:00')"
        )
    job = _reconcile(db, company_id)
    run = _run_row(db, company_id, job.id)
    assert run.added_count == 1  # NOT an update - it re-appeared as a fresh add
    db.close()


def test_a_failed_delete_verdict_quarantines_the_row(session_factory, rig, consumer):
    company_id = rig
    db = session_factory()
    conn_id = _conn_for(db, company_id)
    engine = RUNTIME.engine_for(conn_id, {}, {})
    _seed(db, company_id)
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM debtor WHERE acc_no = '300-A003'")

    def rejects_deletes(path, body):
        if path.endswith("/deletions"):
            refs = body.get("source_refs") or []
            return httpx.Response(
                200,
                json={
                    "summary": {"total": len(refs), "deleted": 0, "deactivated": 0,
                                "not_found": 0, "failed": len(refs)},
                    "records": [{"source_ref": r, "outcome": "failed",
                                 "errors": {"source_ref": "linked elsewhere"}} for r in refs],
                },
            )
        return Consumer.ok(path, body)

    consumer.responder = rejects_deletes
    job = _reconcile(db, company_id)

    delete_row = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.op == STAGED_OP_DELETE,
        )
        .one()
    )
    assert delete_row.status == STAGED_FAILED
    run = _run_row(db, company_id, job.id)
    assert run.deleted_count == 0
    assert run.failed_count >= 1
    # The hash was NOT removed - a quarantined delete is not a confirmed one.
    assert f"{DB_NAME}:300-A003" in _known_refs(db, company_id)
    db.close()


def test_a_retryable_ie_no_verdict_delete_stays_staged(session_factory, rig, consumer):
    company_id = rig
    db = session_factory()
    conn_id = _conn_for(db, company_id)
    engine = RUNTIME.engine_for(conn_id, {}, {})
    _seed(db, company_id)
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM debtor WHERE acc_no = '300-A003'")

    def silent_on_deletes(path, body):
        if path.endswith("/deletions"):
            return httpx.Response(200, json={"summary": {}, "records": []})
        return Consumer.ok(path, body)

    consumer.responder = silent_on_deletes
    _reconcile(db, company_id)

    delete_row = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.op == STAGED_OP_DELETE,
        )
        .one()
    )
    assert delete_row.status == STAGED  # unresolved - retried next run
    assert f"{DB_NAME}:300-A003" in _known_refs(db, company_id)
    db.close()


# ── stale delete intents (S3 review BLOCKER 1) ────────────────────────────────


def test_a_reappearing_ref_cancels_its_own_stale_parked_delete_intent(
    session_factory, rig, consumer
):
    """A delete intent must not outlive the evidence that produced it: the ref
    is deleted (parks a STAGED delete intent), then REAPPEARS at source with
    the SAME data (unchanged hash - nothing new is staged for it). The stale
    intent must be discarded, never pushed - a live record must never be
    deleted just because it once looked absent."""
    company_id = rig
    db = session_factory()
    conn_id = _conn_for(db, company_id)
    engine = RUNTIME.engine_for(conn_id, {}, {})
    _seed(db, company_id)

    # Silence the consumer's delete endpoint so the intent stays STAGED
    # (unresolved) rather than resolving away before we can inspect it.
    def silent_on_deletes(path, body):
        if path.endswith("/deletions"):
            return httpx.Response(200, json={"summary": {}, "records": []})
        return Consumer.ok(path, body)

    consumer.responder = silent_on_deletes
    with engine.begin() as conn:
        row = conn.exec_driver_sql(
            "SELECT acc_no, company_name, email, last_modified FROM debtor "
            "WHERE acc_no = '300-A003'"
        ).fetchone()
        conn.exec_driver_sql("DELETE FROM debtor WHERE acc_no = '300-A003'")

    _reconcile(db, company_id)
    parked = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.op == STAGED_OP_DELETE,
        )
        .one()
    )
    assert parked.status == STAGED

    # The ref REAPPEARS with the exact same data.
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO debtor VALUES (?, ?, ?, ?)", tuple(row))
    consumer.requests.clear()
    _reconcile(db, company_id)

    db.refresh(parked)
    assert parked.status == STAGED_DISCARDED
    # And nothing took its place.
    assert (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.op == STAGED_OP_DELETE,
            AcStagedRecord.status == STAGED,
        )
        .count()
        == 0
    )
    # The reappearance was never pushed as a delete either.
    assert not any(r["path"].endswith("/deletions") for r in consumer.requests)
    db.close()


def test_a_draft_tasks_parked_delete_is_discarded_before_it_can_fire_at_activation(
    session_factory, rig, consumer
):
    """A draft/paused task's push is gated, but reconcile still runs and can
    still park a delete intent (e.g. a dry-run reconcile before Activate).
    That intent must be cancelled the same way once its ref reappears - it
    must never survive to fire the instant the task is later activated."""
    from modules.autocount.models import ETL_STATUS_DRAFT

    company_id = rig
    db = session_factory()
    conn_id = _conn_for(db, company_id)
    engine = RUNTIME.engine_for(conn_id, {}, {})
    _seed(db, company_id)

    config = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == DEFAULT_TENANT_ID,
            AcEntityConfig.company_id == company_id,
            AcEntityConfig.entity_type == ENTITY_CUSTOMER,
        )
        .one()
    )
    config.etl_status = ETL_STATUS_DRAFT
    db.commit()

    with engine.begin() as conn:
        row = conn.exec_driver_sql(
            "SELECT acc_no, company_name, email, last_modified FROM debtor "
            "WHERE acc_no = '300-A003'"
        ).fetchone()
        conn.exec_driver_sql("DELETE FROM debtor WHERE acc_no = '300-A003'")

    job = _reconcile(db, company_id)
    # A draft task never auto-pushes - the batch parks for review instead.
    assert job.status == JOB_NEEDS_REVIEW
    parked = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.op == STAGED_OP_DELETE,
        )
        .one()
    )
    assert parked.status == STAGED

    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO debtor VALUES (?, ?, ?, ?)", tuple(row))
    _reconcile(db, company_id)
    db.refresh(parked)
    assert parked.status == STAGED_DISCARDED

    # Activate the task and run again - the stale intent must never fire.
    config.etl_status = ETL_STATUS_ACTIVE
    db.commit()
    consumer.requests.clear()
    _reconcile(db, company_id)
    assert not any(r["path"].endswith("/deletions") for r in consumer.requests)
    db.close()


def test_two_reconciles_with_the_same_missing_ref_stage_only_one_delete_row(
    session_factory, rig, consumer
):
    """S6 - a reconcile that runs again before the first delete intent
    resolves must not pile up a second row for the same ref."""
    company_id = rig
    db = session_factory()
    conn_id = _conn_for(db, company_id)
    engine = RUNTIME.engine_for(conn_id, {}, {})
    _seed(db, company_id)

    def silent_on_deletes(path, body):
        if path.endswith("/deletions"):
            return httpx.Response(200, json={"summary": {}, "records": []})
        return Consumer.ok(path, body)

    consumer.responder = silent_on_deletes
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM debtor WHERE acc_no = '300-A003'")

    _reconcile(db, company_id)
    _reconcile(db, company_id)

    rows = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company_id,
            AcStagedRecord.op == STAGED_OP_DELETE,
        )
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == STAGED
    db.close()


# ── delete guard (AC-22-22) ───────────────────────────────────────────────────


def test_the_delete_guard_fails_the_whole_run_and_pushes_nothing(
    session_factory, rig, consumer
):
    """A broken query returning almost nothing must never read as "everything
    else was deleted" - the guard fails the run BEFORE any staging or push,
    adds/updates in the same extract included."""
    company_id = rig
    db = session_factory()
    # Seed a much larger known population than the 3-row fixture table so a
    # full extract of just those 3 blows the 20%/50 guard.
    from modules.autocount.repositories import RowHashRepository
    from datetime import datetime, timezone

    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company_id, ENTITY_CUSTOMER,
        {f"K{i}": "h" for i in range(200)}, seen_at=datetime.now(timezone.utc),
    )
    db.commit()

    job = _reconcile(db, company_id)
    assert job.status == JOB_FAILED
    # N2: was a tautology (`X or job.error` is truthy whenever job.error is
    # truthy, regardless of X) - assert the message content for real.
    assert "safety threshold" in (job.error or "").lower()

    # Nothing pushed, nothing staged for this job - fail-safe means NOTHING
    # propagates, not just the deletes.
    staged = db.query(AcStagedRecord).filter(AcStagedRecord.job_id == job.id).all()
    assert staged == []
    # The known population is untouched (no hash writes happened either).
    assert len(_known_refs(db, company_id)) == 200
    db.close()


def test_a_zero_row_full_extract_trips_the_guard_even_under_50_known(
    session_factory, rig, consumer
):
    """S3 review BLOCKER 2 - the ratio/absolute guard (max(20%, 50)) is INERT
    on a small known population: known=20 gives a threshold of 50, so a
    zero-row extract's 20 delete refs sail straight through the ratio check.
    The absolute zero-row rule must catch this regardless of population
    size."""
    from datetime import datetime, timezone

    from modules.autocount.repositories import RowHashRepository

    company_id = rig
    db = session_factory()
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company_id, ENTITY_CUSTOMER,
        {f"K{i}": "h" for i in range(20)}, seen_at=datetime.now(timezone.utc),
    )
    db.commit()
    # Empty the fixture table so the full extract genuinely returns 0 rows.
    conn_id = _conn_for(db, company_id)
    engine = RUNTIME.engine_for(conn_id, {}, {})
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM debtor")

    job = _reconcile(db, company_id)
    assert job.status == JOB_FAILED
    assert "0 rows" in (job.error or "")
    staged = db.query(AcStagedRecord).filter(AcStagedRecord.job_id == job.id).all()
    assert staged == []
    assert len(_known_refs(db, company_id)) == 20
    db.close()


def test_delete_guard_trip_is_a_distinct_error_code_unprefixed_and_no_stack(
    session_factory, rig, consumer, caplog
):
    """S5: a guard TRIP is not a generic fetch fault - distinct error code,
    the message carried verbatim (no "Fetch failed:" noise), and a WARNING
    log (no stack trace, unlike the generic exception branch)."""
    import logging

    from datetime import datetime, timezone

    from modules.autocount.repositories import RowHashRepository

    company_id = rig
    db = session_factory()
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company_id, ENTITY_CUSTOMER,
        {f"K{i}": "h" for i in range(200)}, seen_at=datetime.now(timezone.utc),
    )
    db.commit()

    with caplog.at_level(logging.WARNING, logger="foundryx.autocount"):
        job = _reconcile(db, company_id)

    assert job.status == JOB_FAILED
    assert not (job.error or "").startswith("Fetch failed:")
    assert "safety threshold" in (job.error or "").lower()
    config = (
        db.query(AcEntityConfig)
        .filter(
            AcEntityConfig.tenant_id == DEFAULT_TENANT_ID,
            AcEntityConfig.company_id == company_id,
            AcEntityConfig.entity_type == ENTITY_CUSTOMER,
        )
        .one()
    )
    assert config.last_run_error_code == "DELETE_GUARD"
    assert any(
        r.levelno == logging.WARNING and "delete guard" in r.message.lower()
        for r in caplog.records
    )
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)
    db.close()
