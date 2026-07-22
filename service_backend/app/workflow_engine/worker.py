"""Workflow Celery app (plan sprint-2/08 D1) — reuses the Redis broker. The run
service enqueues ``run_workflow_task``; a worker executes node-by-node. Dev/E2E
set ``CELERY_TASK_ALWAYS_EAGER=true`` → inline, zero extra process.

    celery -A app.workflow_engine.worker worker --loglevel info
"""
import logging

from celery import Celery

from app.config import settings

logger = logging.getLogger("foundryx.workflows")

celery_app = Celery(
    "workflows",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=False,  # a failing run is recorded, not raised
    broker_connection_retry_on_startup=True,
    # Dedicated queue — worker_workflow + beat use ONLY this (see omni worker for
    # why). run_workflow / run_due / status.reevaluate / webhooks.retry_due all
    # publish here; worker runs with `-Q workflow`, beat inherits this default.
    task_default_queue="workflow",
)

# Single minute-tick draining due scheduled workflows (plan sprint-2/09 D9).
# Needs a `celery -A app.workflow_engine.worker beat` process beside the worker;
# eager dev has no beat, so trigger run_due_workflows directly there.
celery_app.conf.beat_schedule = {
    "run-due-workflows": {"task": "workflows.run_due", "schedule": 60.0},
    # Derived status time sweep (sprint-4/03 G4) — advance time-conditioned auto
    # edges (e.g. invoice Overdue) the event bus can't catch. Same 60s tick.
    "reevaluate-derived-status": {"task": "status.reevaluate_time_based", "schedule": 60.0},
    # Reclaim consumer-webhook deliveries whose backoff elapsed but whose worker
    # self-reschedule was lost to a crash (omnichannel Slice 4). Defined in this
    # worker (the sole beat host); guarded so a missing module is a no-op.
    "retry-due-webhooks": {"task": "webhooks.retry_due", "schedule": 60.0},
}


@celery_app.task(name="workflows.run_due")
def run_due_workflows_task() -> dict:
    from app.database import SessionLocal
    from app.workflow_engine.scheduler import prune_runs, run_due_workflows

    db = SessionLocal()
    try:
        fired = run_due_workflows(db)
        # Housekeeping pass (plan 10 D4) — bound run-history growth. Isolated so
        # a prune failure never masks a successful fire.
        pruned = 0
        try:
            pruned = prune_runs(db)
        except Exception:  # noqa: BLE001
            logger.exception("workflow run prune failed")
            db.rollback()
        # Centralized background_jobs retention (plan sprint-4/10) — same beat
        # tick, isolated so a prune failure never masks a successful fire.
        try:
            from app.jobs.service import prune_jobs

            prune_jobs(db)
        except Exception:  # noqa: BLE001
            logger.exception("background job prune failed")
            db.rollback()
        # Integration-activity retention (plan sprint-4/12 AC-DLC-22) — per-tenant
        # window, same beat tick, isolated.
        try:
            from app.activity_log.retention import prune_integration_activity

            prune_integration_activity(db)
        except Exception:  # noqa: BLE001
            logger.exception("integration-activity prune failed")
            db.rollback()
        # AI trace retention (Phase B-i, AC-BI-10) — `ok` traces prune on a
        # short window, `error`/`flagged` on a longer one. Same beat tick,
        # isolated so a prune failure never breaks the beat.
        try:
            from app.ai.retention import prune_traces

            prune_traces(db)
        except Exception:  # noqa: BLE001
            logger.exception("AI trace prune failed")
            db.rollback()
        return {"fired": fired, "pruned": pruned}
    except Exception:  # noqa: BLE001 — a bad tick never kills the beat loop
        logger.exception("scheduled-workflow tick failed")
        db.rollback()
        return {"fired": 0, "pruned": 0}
    finally:
        db.close()


@celery_app.task(name="webhooks.retry_due")
def retry_due_webhooks_task() -> dict:
    """Backstop re-driver for consumer-webhook deliveries (omnichannel Slice 4).
    Failure-isolated; a no-op when the omnichannel module isn't installed."""
    from app.database import SessionLocal

    try:
        from modules.omnichannel.services.webhook_delivery import run_due_deliveries
    except ImportError:
        return {"redriven": 0}

    db = SessionLocal()
    try:
        return {"redriven": run_due_deliveries(db)}
    except Exception:  # noqa: BLE001 — a bad tick never kills the beat loop
        logger.exception("webhook retry tick failed")
        db.rollback()
        return {"redriven": 0}
    finally:
        db.close()


@celery_app.task(name="status.reevaluate_time_based")
def reevaluate_time_based_task() -> dict:
    from app.database import SessionLocal
    from app.status_engine.derived import install_derived_status
    from app.workflow_engine.scheduler import reevaluate_time_based

    # The worker process runs no FastAPI lifespan — ensure the derived-status
    # subscriber is registered so cross-entity cascades work here too.
    install_derived_status()
    db = SessionLocal()
    try:
        advanced = reevaluate_time_based(db)
        return {"advanced": advanced}
    except Exception:  # noqa: BLE001 — a bad tick never kills the beat loop
        logger.exception("derived-status time sweep failed")
        db.rollback()
        return {"advanced": 0}
    finally:
        db.close()


@celery_app.task(name="workflows.run_workflow")
def run_workflow_task(run_id: str) -> dict:
    from app.database import SessionLocal
    from app.models.workflow import RUN_FAILED, WorkflowRun
    from app.workflow_engine.executor import run_workflow

    db = SessionLocal()
    try:
        run = run_workflow(db, run_id)
        return {"runId": run.id, "status": run.status}
    except Exception:  # noqa: BLE001 — never let a run crash the worker silently
        logger.exception("workflow run %s crashed", run_id)
        db.rollback()
        run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
        if run is not None:
            run.status = RUN_FAILED
            run.error = "Run crashed unexpectedly."
            db.commit()
        return {"runId": run_id, "status": RUN_FAILED}
    finally:
        db.close()


# ── Cross-package task + handler registration (worker has no FastAPI lifespan) ─
# `-A app.workflow_engine.worker` only sees tasks/handlers whose module is
# imported. Without these the worker DISCARDS `jobs.run` as an unregistered task
# (silent stall — the storage-migration job hangs Pending forever).
import app.jobs.worker  # noqa: E402,F401 — registers the `jobs.run` Celery task
import app.storage_migration.service  # noqa: E402,F401 — module-level register_storage_migration_handler()
import modules.autocount.sync  # noqa: E402,F401 — registers the `autocount_sync` job handler
