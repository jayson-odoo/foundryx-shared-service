"""SS-SO-FAST-QUEUE - document incrementals ride their own queue + worker.

Owner probe 1-8 Nov: SO incrementals waited 231 s p90 on the shared `jobs`
queue behind stock_balance / product, and 38% of SO ticks were skipped
because a QUEUED job counts as in flight. These tests pin:

* per-JOB queue routing (`JobHandlerDef.queue_for`) - an `autocount_sync`
  incremental of a document entity goes to `jobs_docs`, everything else
  (masters, product, stock, reconcile, manual) stays on `jobs`;
* the compose side (a `worker_jobs_docs` service consuming that queue) and
  the per-queue liveness ping;
* an explicit skip reason when the in-flight job is only QUEUED;
* the run's queue wait recorded on the run row and the wire;
* the reconcile daily-at time read in the task's own timezone (MYT for new
  tasks, UTC for a task saved before the key existed).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_PENDING, BackgroundJob
from modules.autocount.canonical.documents import (
    ENTITY_AR_OUTSTANDING,
    ENTITY_CANCEL_SALES_ORDER,
    ENTITY_CREDIT_NOTE,
    ENTITY_INVOICE,
    ENTITY_SALES_ORDER,
)
from modules.autocount.canonical.masters import (
    ENTITY_CUSTOMER,
    ENTITY_PRODUCT,
    ENTITY_STOCK_BALANCE,
)
from modules.autocount.models import AcSyncRun
from modules.autocount.sync import AUTOCOUNT_SYNC

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 8, 4, 0, 0, tzinfo=timezone.utc)


def _job(entity_type: str, mode: str = "incremental") -> BackgroundJob:
    return BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID,
        type=AUTOCOUNT_SYNC,
        status=JOB_PENDING,
        payload_json={"companyId": "c1", "entityType": entity_type, "mode": mode},
    )


# ── routing ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "entity_type",
    [ENTITY_SALES_ORDER, ENTITY_INVOICE, ENTITY_CREDIT_NOTE, ENTITY_CANCEL_SALES_ORDER],
)
def test_a_document_incremental_routes_to_the_docs_queue(entity_type):
    from app.jobs.registry import queue_for_job

    assert queue_for_job(_job(entity_type)) == "jobs_docs"


@pytest.mark.parametrize(
    "entity_type,mode",
    [
        (ENTITY_STOCK_BALANCE, "incremental"),
        (ENTITY_PRODUCT, "incremental"),
        (ENTITY_CUSTOMER, "incremental"),
        (ENTITY_AR_OUTSTANDING, "incremental"),
        (ENTITY_SALES_ORDER, "reconcile"),
        (ENTITY_SALES_ORDER, "manual"),
    ],
)
def test_everything_else_keeps_the_shared_jobs_queue(entity_type, mode):
    from app.jobs.registry import queue_for_job

    assert queue_for_job(_job(entity_type, mode)) is None


def test_an_empty_docs_queue_setting_turns_the_split_off(monkeypatch):
    """Rollback lever: AUTOCOUNT_DOCS_QUEUE='' routes documents back onto
    `jobs` without a code change."""
    from app.jobs.registry import queue_for_job

    monkeypatch.setattr(settings, "autocount_docs_queue", "")
    assert queue_for_job(_job(ENTITY_SALES_ORDER)) is None


def test_enqueue_publishes_a_document_incremental_on_the_docs_queue(session_factory, monkeypatch):
    from app.jobs import worker as jobs_worker
    from app.jobs.service import JobService

    calls = []
    monkeypatch.setattr(settings, "celery_task_always_eager", False)
    monkeypatch.setattr(
        jobs_worker.run_job_task, "apply_async",
        lambda args=None, queue=None, **kw: calls.append(("apply_async", queue)),
    )
    monkeypatch.setattr(
        jobs_worker.run_job_task, "delay", lambda *a, **kw: calls.append(("delay", None))
    )
    db = session_factory()
    service = JobService(db)
    so = service.create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": "c1", "entityType": ENTITY_SALES_ORDER, "mode": "incremental"},
    )
    stock = service.create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": "c1", "entityType": ENTITY_STOCK_BALANCE, "mode": "incremental"},
    )
    service.enqueue(so.id)
    service.enqueue(stock.id)

    # SO -> its own queue; stock -> the type's default route (`jobs` via
    # task_routes), exactly as before.
    assert calls == [("apply_async", "jobs_docs"), ("delay", None)]


# ── compose + liveness ───────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def compose():
    with open(REPO_ROOT / "docker-compose.yml") as f:
        return yaml.safe_load(f)


def test_a_worker_jobs_docs_service_consumes_the_docs_queue(compose):
    service = compose["services"].get("worker_jobs_docs")
    assert service is not None, "docker-compose.yml needs a worker_jobs_docs service"
    command = service["command"]
    assert command[command.index("-Q") + 1] == "jobs_docs"
    assert command[command.index("-c") + 1] == "2"
    env = service.get("environment") or {}
    for key in (
        "WORKER_DB_STATEMENT_TIMEOUT_SECONDS",
        "WORKER_DB_LOCK_TIMEOUT_SECONDS",
        "WORKER_DB_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_SECONDS",
    ):
        assert key in env, f"worker_jobs_docs is missing {key}"


def test_worker_jobs_still_consumes_only_jobs(compose):
    command = compose["services"]["worker_jobs"]["command"]
    assert command[command.index("-Q") + 1] == "jobs"


def test_the_docs_queue_has_its_own_liveness_ping():
    from app.ops_liveness import KNOWN_QUEUES
    from app.workflow_engine.worker import celery_app

    assert "jobs_docs" in KNOWN_QUEUES
    assert "ops-ping-jobs_docs" in celery_app.conf.beat_schedule


# ── overlap guard: queued vs running ────────────────────────────────────────


def _skip_reason_for(session_factory, *, started: bool) -> str:
    from tests.test_autocount_scheduler import _company, _task
    from modules.autocount.scheduler import sweep_etl_tasks

    db = session_factory()
    company = _company(db)
    _task(db, company, next_incremental_at=NOW - timedelta(minutes=1))
    db.add(
        BackgroundJob(
            tenant_id=DEFAULT_TENANT_ID, type=AUTOCOUNT_SYNC,
            status="running" if started else JOB_PENDING,
            payload_json={"companyId": company.id, "entityType": ENTITY_CUSTOMER},
            created_at=NOW - timedelta(seconds=90),
            started_at=(NOW - timedelta(seconds=30)) if started else None,
            heartbeat_at=(NOW - timedelta(seconds=10)) if started else None,
        )
    )
    db.commit()
    assert sweep_etl_tasks(db, now=NOW)["skipped"] == 1
    run = db.query(AcSyncRun).filter(AcSyncRun.company_id == company.id).one()
    return run.skip_reason


def test_a_tick_behind_a_queued_job_says_it_is_queued(session_factory):
    reason = _skip_reason_for(session_factory, started=False)
    assert "queued" in reason.lower()
    assert "90 s" in reason


def test_a_tick_behind_a_running_job_keeps_the_running_reason(session_factory):
    reason = _skip_reason_for(session_factory, started=True)
    assert "still in progress" in reason
    assert "queued" not in reason.lower()


# ── queue wait on the run ───────────────────────────────────────────────────


def test_the_run_records_how_long_its_job_waited_in_the_queue():
    from modules.autocount.sync import queue_wait_ms

    job = _job(ENTITY_SALES_ORDER)
    job.created_at = NOW
    job.started_at = NOW + timedelta(seconds=231, milliseconds=500)
    assert queue_wait_ms(job) == 231500
    job.started_at = None
    assert queue_wait_ms(job) is None


def test_the_run_history_wire_carries_queue_wait():
    from modules.autocount.schemas import SyncRunItem

    run = AcSyncRun(
        id="r1", tenant_id=DEFAULT_TENANT_ID, company_id="c1", entity_type="sales_order",
        mode="incremental", queue_wait_ms=1200,
    )
    assert SyncRunItem.model_validate(run).model_dump()["queueWaitMs"] == 1200


# ── reconcile timezone ──────────────────────────────────────────────────────


def test_a_myt_daily_reconcile_arms_at_the_right_utc_instant():
    from modules.autocount.services.etl_service import EtlService

    _, reconcile = EtlService.next_run_times(
        {"reconcileMode": "dailyAt", "reconcileAt": "02:00",
         "reconcileTimezone": "Asia/Kuala_Lumpur", "incrementalMinutes": 1,
         "watermarkColumn": "LastModified"},
        now=NOW,  # 12:00 MYT
    )
    # 02:00 MYT next day = 18:00 UTC today.
    assert reconcile == datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)


def test_a_task_saved_before_the_timezone_key_keeps_utc():
    from modules.autocount.services.etl_service import EtlService

    _, reconcile = EtlService.next_run_times(
        {"reconcileMode": "dailyAt", "reconcileAt": "02:00"}, now=NOW
    )
    assert reconcile == datetime(2026, 11, 9, 2, 0, tzinfo=timezone.utc)


def test_an_unknown_timezone_falls_back_to_utc_not_a_crash():
    from modules.autocount.services.etl_service import EtlService

    _, reconcile = EtlService.next_run_times(
        {"reconcileMode": "dailyAt", "reconcileAt": "02:00", "reconcileTimezone": "Mars/Base"},
        now=NOW,
    )
    assert reconcile == datetime(2026, 11, 9, 2, 0, tzinfo=timezone.utc)


def test_the_schedule_cleaner_keeps_a_valid_timezone_and_rejects_a_bad_one():
    from modules.autocount.services.etl_service import validate_schedule

    cleaned, errors = validate_schedule(
        {"incrementalMinutes": 1, "reconcileMode": "dailyAt", "reconcileAt": "03:00",
         "reconcileTimezone": "Asia/Kuala_Lumpur"},
        has_watermark=True,
    )
    assert not errors
    assert cleaned["reconcileTimezone"] == "Asia/Kuala_Lumpur"

    _, errors = validate_schedule(
        {"incrementalMinutes": 1, "reconcileMode": "dailyAt", "reconcileAt": "03:00",
         "reconcileTimezone": "Mars/Base"},
        has_watermark=True,
    )
    assert "reconcileTimezone" in errors


def test_new_document_tasks_default_to_one_minute_and_myt():
    from modules.autocount.services.etl_service import default_source_config

    doc = default_source_config(ENTITY_SALES_ORDER)
    assert doc["incrementalMinutes"] == 1
    assert doc["reconcileTimezone"] == "Asia/Kuala_Lumpur"
