"""Workflow Celery app (plan sprint-2/08 D1) - reuses the Redis broker. The run
service enqueues ``run_workflow_task``; a worker executes node-by-node. Dev/E2E
set ``CELERY_TASK_ALWAYS_EAGER=true`` → inline, zero extra process.

    celery -A app.workflow_engine.worker worker --loglevel info
"""
import logging
from datetime import datetime, timezone

from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded

from app.config import settings
from app.lazy_registry import lazy_once
from app.ops_liveness import KNOWN_QUEUES

logger = logging.getLogger("foundryx.workflows")

# Review round 1 (B2) - the stable sentence stamped on a run this app's
# `workflows.run_workflow` / `workflows.wake_serialized` tasks stop
# cooperatively at their own soft time limit (`settings.
# workflow_run_soft_time_limit_seconds`), mirroring `JobService.
# SOFT_TIME_LIMIT_ERROR`'s pattern: a clean, expected stop at a configured
# bound, not a crash, so it is worded distinctly from "Run crashed
# unexpectedly."
WORKFLOW_RUN_TIME_LIMIT_ERROR = (
    "Stopped: this run exceeded its soft time limit."
)


def _boot_module_nodes() -> None:
    from app.module_loader import boot_module_hooks

    boot_module_hooks()


_ensure_module_nodes = lazy_once(_boot_module_nodes)

celery_app = Celery(
    "workflows",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=False,  # a failing run is recorded, not raised
    broker_connection_retry_on_startup=True,
    # Dedicated queue - worker_workflow + beat use ONLY this (see omni worker for
    # why). run_workflow / run_due / status.reevaluate / webhooks.retry_due all
    # publish here; worker runs with `-Q workflow`, beat inherits this default.
    task_default_queue="workflow",
    # ── Worker starvation fix (sprint-5/11 S1, incident 2026-09-20/21) ──────
    # `jobs.run` (background_jobs, potentially a 20+ minute AutoCount build)
    # routes onto its OWN `jobs` queue - the dedicated `worker_jobs` compose
    # service - so it can never again starve every beat tick sharing this
    # app's single `workflow` queue. Every OTHER task (a tick,
    # `workflows.run_workflow`, `jobs.sweep_orphaned`, `ops.ping`, ...) keeps
    # the `task_default_queue` above. `jobs.run` stays REGISTERED on this
    # same app (`app.jobs.worker` is imported below) - a message already
    # queued on `workflow` at deploy time still executes; the isolation is
    # queue ROUTING, not a second Celery app (D15/AC-11-80). An explicit
    # `apply_async(queue=...)` override (a `JobHandlerDef.queue` type like
    # `stt`/`bots`) still wins over this routing table.
    task_routes={"jobs.run": {"queue": "jobs"}},
    # Never hold a second message hostage (AC-11-81): the default prefetch
    # of 4 is exactly what let one blocked child hold several beat messages
    # in its buffer during the incident ("received by MainProcess, never
    # executed"). `acks_late` stays the Celery default (False) for every
    # task on this app - see `app/jobs/worker.py`'s own note (D17) for why
    # `jobs.run` in particular must never ack late.
    worker_prefetch_multiplier=1,
    # App-level bound for the tick family (AC-11-82): any task with no OWN
    # declared limit (every beat tick, `jobs.sweep_orphaned`, `ops.ping`)
    # inherits this. `jobs.run` overrides it with its own generous,
    # settings-driven bound (`app/jobs/worker.py`) - a legitimate 25+ minute
    # build must survive where a wedged 5-minute tick must not.
    task_soft_time_limit=300,
    task_time_limit=330,
)

# Single minute-tick draining due scheduled workflows (plan sprint-2/09 D9).
# Needs a `celery -A app.workflow_engine.worker beat` process beside the worker;
# eager dev has no beat, so trigger run_due_workflows directly there.
celery_app.conf.beat_schedule = {
    "run-due-workflows": {"task": "workflows.run_due", "schedule": 60.0},
    # Derived status time sweep (sprint-4/03 G4) - advance time-conditioned auto
    # edges (e.g. invoice Overdue) the event bus can't catch. Same 60s tick.
    "reevaluate-derived-status": {"task": "status.reevaluate_time_based", "schedule": 60.0},
    # Reclaim consumer-webhook deliveries whose backoff elapsed but whose worker
    # self-reschedule was lost to a crash (omnichannel Slice 4). Defined in this
    # worker (the sole beat host); guarded so a missing module is a no-op.
    "retry-due-webhooks": {"task": "webhooks.retry_due", "schedule": 60.0},
    # Resume workflow runs parked by an omnichannel Ask-a-question / Wait step
    # whose deadline passed (plan sprint-4/31 S4, D-A5-10/F8). Module-owned
    # work, defined + scheduled HERE (the sole beat host) and guarded exactly
    # like `webhooks.retry_due` so a missing module is a no-op. A 60s tick means
    # a "1 hour" timeout fires between 60:00 and 61:00 - a deadline sweep, not a
    # precise timer.
    "omnichannel-wait-sweep": {"task": "omnichannel.wait_sweep", "schedule": 60.0},
    # Scheduled-broadcast sweep (plan 29 S2b, AC-BRD-42) - starts every
    # SCHEDULED broadcast whose `scheduledAt` has passed and reconciles any
    # broadcast stuck in SENDING. Same module-absence guard as the webhook
    # retry tick above (this worker is the sole beat host).
    "broadcasts-due": {"task": "omnichannel.broadcasts_due", "schedule": 60.0},
    # Meetings calendar sync (sprint-5 S0) - a new event with a conference link
    # must surface within 60 s, so this is a minute tick like the rest. It only
    # enqueues for tenants that have the module active AND someone opted in.
    "meetings-calendar-sync": {"task": "meetings.calendar_sync_due", "schedule": 60.0},
    # Meetings bot dispatch (sprint-5 S2) - a meeting is joined 2 min before it
    # starts, so the tick has to be finer than that lead. Same minute tick as
    # the sync; it enqueues onto the `bots` queue, which this worker never
    # consumes.
    "meetings-dispatch-bots": {"task": "meetings.bot_dispatch_due", "schedule": 60.0},
    # AutoCount direct-DB ETL sweep (plan 22 S3, AC-22-13) - selects due
    # ACTIVE sql_db tasks and enqueues the SAME `autocount_sync` job the
    # manual Run-now button uses. Same 60s tick; does no extraction itself.
    "autocount-etl-sweep": {"task": "autocount.etl_sweep", "schedule": 60.0},
    # AutoCount pull snapshot prune (sprint-5/10 §2.4, AC-10-25) - deletes
    # every EXPIRED snapshot (+ its rows) and drops any READY snapshot beyond
    # the newest 3 per (tenant, company, entity) triple. Hourly, beside the
    # ETL sweep above - snapshots are held for 24h, so a sub-minute tick
    # would buy nothing.
    "autocount-prune-pull-snapshots": {
        "task": "autocount.prune_pull_snapshots", "schedule": 3600.0,
    },
    # Deferred actions (sprint-4/23, T5, AC-DLA-41) - commits every pending
    # row whose grace window has closed. Under eager dev (no beat process)
    # the frontend's lapse-time `GET current` performs the lazy commit
    # instead; this sweep is the safety net for whoever isn't watching.
    "pending-actions-commit-due": {"task": "pending_actions.commit_due", "schedule": 60.0},
    # ── Worker starvation fix (sprint-5/11 S1, AC-11-56/AC-11-86, D16/D20) ──
    # The orphan sweep's OWN beat tick, decoupled from the AutoCount
    # scheduler: outside app startup, the scheduler tick was the ONLY caller
    # of `fail_orphaned_running_jobs` - itself a tick on the very `workflow`
    # queue the incident starved, so recovery was queued behind the thing it
    # recovers. This tick runs on `workflow` (the app default; deliberately
    # NEVER `jobs` - D16: the sweep must never share a queue with the jobs
    # it sweeps) every 5 minutes and wraps BOTH `sweep_orphaned_jobs(db)`
    # (RUNNING-only) and (sprint-5/11 S2) `sweep_undispatched_pending_jobs(db)`
    # (PENDING-only, incident 2026-09-21).
    "jobs-sweep-orphaned": {"task": "jobs.sweep_orphaned", "schedule": 300.0},
    # A frozen worker is visible within minutes (AC-11-86, D20): beat itself
    # stayed healthy for the whole 8-hour incident, so the signal has to be
    # stamped by the CONSUMING worker, per queue - one beat entry PER known
    # queue, each pinned onto that queue via `options.queue` so the ping
    # actually reaches the worker consuming it (a ping that always landed on
    # `workflow` would never catch a wedged `worker_jobs`).
    **{
        f"ops-ping-{queue}": {
            "task": "ops.ping",
            "schedule": 60.0,
            "kwargs": {"queue": queue},
            "options": {"queue": queue},
        }
        for queue in KNOWN_QUEUES
    },
}


@celery_app.task(name="workflows.run_due")
def run_due_workflows_task() -> dict:
    from app.database import SessionLocal
    from app.workflow_engine.scheduler import prune_runs, run_due_workflows

    db = SessionLocal()
    try:
        fired = run_due_workflows(db)
        # Durable serialized runs are re-woken from Postgres. A Redis outage is
        # isolated here and never converts them to parallel execution.
        redriven = 0
        try:
            from app.workflow_engine.serialization import (
                redrive_pending_serialized_runs,
            )

            redriven = redrive_pending_serialized_runs(db)
        except Exception:  # noqa: BLE001
            logger.exception("serialized workflow recovery failed")
            db.rollback()
        # Housekeeping pass (plan 10 D4) - bound run-history growth. Isolated so
        # a prune failure never masks a successful fire.
        pruned = 0
        try:
            pruned = prune_runs(db)
        except Exception:  # noqa: BLE001
            logger.exception("workflow run prune failed")
            db.rollback()
        # Centralized background_jobs retention (plan sprint-4/10) - same beat
        # tick, isolated so a prune failure never masks a successful fire.
        try:
            from app.jobs.service import prune_jobs

            prune_jobs(db)
        except Exception:  # noqa: BLE001
            logger.exception("background job prune failed")
            db.rollback()
        # Integration-activity retention (plan sprint-4/12 AC-DLC-22) - per-tenant
        # window, same beat tick, isolated.
        try:
            from app.activity_log.retention import prune_integration_activity

            prune_integration_activity(db)
        except Exception:  # noqa: BLE001
            logger.exception("integration-activity prune failed")
            db.rollback()
        # AI trace retention (Phase B-i, AC-BI-10) - `ok` traces prune on a
        # short window, `error`/`flagged` on a longer one. Same beat tick,
        # isolated so a prune failure never breaks the beat.
        try:
            from app.ai.retention import prune_traces

            prune_traces(db)
        except Exception:  # noqa: BLE001
            logger.exception("AI trace prune failed")
            db.rollback()
        return {"fired": fired, "pruned": pruned, "redriven": redriven}
    except Exception:  # noqa: BLE001 - a bad tick never kills the beat loop
        logger.exception("scheduled-workflow tick failed")
        db.rollback()
        return {"fired": 0, "pruned": 0, "redriven": 0}
    finally:
        db.close()


@celery_app.task(name="meetings.calendar_sync_due")
def meetings_calendar_sync_due_task() -> dict:
    """Minute tick enqueuing one calendar-sync job per due tenant (S0 plan §3).
    Failure-isolated; a no-op when the meetings module isn't installed."""
    from app.database import SessionLocal

    try:
        from modules.meetings.jobs import enqueue_due_calendar_syncs
    except ImportError:
        return {"enqueued": 0}

    db = SessionLocal()
    try:
        return {"enqueued": enqueue_due_calendar_syncs(db)}
    except Exception:  # noqa: BLE001 - a bad tick never kills the beat loop
        logger.exception("meetings calendar sync tick failed")
        db.rollback()
        return {"enqueued": 0}
    finally:
        db.close()


@celery_app.task(name="meetings.bot_dispatch_due")
def meetings_bot_dispatch_due_task() -> dict:
    """Minute tick dispatching a bot run for every meeting about to start (S2
    plan §2). Failure-isolated; a no-op when the meetings module isn't
    installed. The runs themselves execute on the `bots` worker, never here."""
    from app.database import SessionLocal

    try:
        from modules.meetings.services.dispatch import dispatch_due_bot_runs
    except ImportError:
        return {"dispatched": 0}

    db = SessionLocal()
    try:
        return {"dispatched": dispatch_due_bot_runs(db)}
    except Exception:  # noqa: BLE001 - a bad tick never kills the beat loop
        logger.exception("meetings bot dispatch tick failed")
        db.rollback()
        return {"dispatched": 0}
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
    except Exception:  # noqa: BLE001 - a bad tick never kills the beat loop
        logger.exception("webhook retry tick failed")
        db.rollback()
        return {"redriven": 0}
    finally:
        db.close()


@celery_app.task(name="omnichannel.wait_sweep")
def omnichannel_wait_sweep_task() -> dict:
    """Resume parked workflow runs whose wait deadline elapsed (plan 31 S4).
    Failure-isolated; a no-op when the omnichannel module isn't installed.
    Needs the module-registered workflow nodes booted - the resumed run
    executes IN THIS PROCESS."""
    from app.database import SessionLocal

    try:
        from modules.omnichannel.services.workflow_waits import sweep_due_waits
    except ImportError:
        return {"resumed": 0, "discarded": 0}

    _ensure_module_nodes()
    db = SessionLocal()
    try:
        return sweep_due_waits(db)
    except Exception:  # noqa: BLE001 - a bad tick never kills the beat loop
        logger.exception("omnichannel wait sweep tick failed")
        db.rollback()
        return {"resumed": 0, "discarded": 0}
    finally:
        db.close()


@celery_app.task(name="omnichannel.broadcasts_due")
def broadcasts_due_task() -> dict:
    """Scheduled-broadcast beat tick (plan 29 S2b, AC-BRD-42). Failure-
    isolated; a no-op when the omnichannel module is absent."""
    from app.database import SessionLocal

    try:
        from modules.omnichannel.services.broadcast_send_service import run_due_broadcasts
    except ImportError:
        return {"started": 0, "reconciled": 0, "finalized": 0}

    db = SessionLocal()
    try:
        return run_due_broadcasts(db)
    except Exception:  # noqa: BLE001 - a bad tick never kills the beat loop
        logger.exception("broadcasts-due tick failed")
        db.rollback()
        return {"started": 0, "reconciled": 0, "finalized": 0}
    finally:
        db.close()


@celery_app.task(name="autocount.etl_sweep")
def autocount_etl_sweep_task() -> dict:
    """The AutoCount ETL beat sweep (plan 22 S3, AC-22-13). Failure-isolated
    like every other tick on this beat - a bad sweep never kills the loop."""
    from app.database import SessionLocal
    from modules.autocount.scheduler import sweep_etl_tasks

    db = SessionLocal()
    try:
        return sweep_etl_tasks(db)
    except Exception:  # noqa: BLE001 - a bad tick never kills the beat loop
        logger.exception("autocount ETL sweep tick failed")
        db.rollback()
        return {"fired": 0, "skipped": 0, "failed": 0}
    finally:
        db.close()


@celery_app.task(name="autocount.prune_pull_snapshots")
def autocount_prune_pull_snapshots_task() -> dict:
    """The pull-snapshot prune beat (sprint-5/10 §2.4, AC-10-25).
    Failure-isolated like every other tick on this beat."""
    from app.database import SessionLocal
    from modules.autocount.services.pull_service import prune_pull_snapshots

    db = SessionLocal()
    try:
        return prune_pull_snapshots(db)
    except Exception:  # noqa: BLE001 - a bad tick never kills the beat loop
        logger.exception("autocount pull-snapshot prune tick failed")
        db.rollback()
        return {"expired": 0, "retentionPruned": 0}
    finally:
        db.close()


@celery_app.task(name="pending_actions.commit_due")
def pending_actions_commit_due_task() -> dict:
    """Deferred-actions beat sweep (sprint-4/23, T5, AC-DLA-41) - commits
    every pending row whose grace window closed. `commit_one` isolates each
    row's own transaction, so a handler failure here never blocks the rest;
    this outer try/except is only the beat-loop safety net."""
    from app.database import SessionLocal
    from app.deferred_actions.service import PendingActionService

    db = SessionLocal()
    try:
        committed = PendingActionService(db).commit_due()
        return {"committed": committed}
    except Exception:  # noqa: BLE001 - a bad tick never kills the beat loop
        logger.exception("pending-actions commit-due tick failed")
        db.rollback()
        return {"committed": 0}
    finally:
        db.close()


@celery_app.task(name="jobs.sweep_orphaned")
def sweep_orphaned_jobs_task() -> dict:
    """The orphan sweep's own 5-minute beat tick (sprint-5/11 S1, AC-11-56,
    D16) - decoupled from the AutoCount scheduler tick that was the only
    caller of this sweep outside app startup (and itself lived on the
    starved `workflow` queue during the 2026-09-20/21 incident). Runs BOTH
    sweeps in one invocation: the ALREADY-EXISTING `sweep_orphaned_jobs(db)`
    (RUNNING-only, every `heartbeats=True` job type) and (sprint-5/11 S2,
    AC-11-56, incident 2026-09-21) `sweep_undispatched_pending_jobs(db)`
    (PENDING-only, every job type - a lost message never gets a chance to
    heartbeat, so the type-declared restriction the running sweep uses does
    not apply here). One beat entry recovers every job type, whether or not
    a scheduler like AutoCount's own overlap guard sits in front of it. Each
    half is independently failure-isolated so a bug in one never blocks the
    other."""
    from app.database import SessionLocal
    from app.jobs.service import sweep_orphaned_jobs, sweep_undispatched_pending_jobs

    db = SessionLocal()
    running = 0
    try:
        running = sweep_orphaned_jobs(db)
    except Exception:  # noqa: BLE001 - a bad tick never kills the beat loop
        logger.exception("jobs.sweep_orphaned tick failed (running sweep)")
        db.rollback()
    undispatched = 0
    try:
        undispatched = sweep_undispatched_pending_jobs(db)
    except Exception:  # noqa: BLE001 - a bad tick never kills the beat loop
        logger.exception("jobs.sweep_orphaned tick failed (undispatched sweep)")
        db.rollback()
    finally:
        db.close()
    return {"running": running, "undispatched": undispatched}


@celery_app.task(name="ops.ping")
def ops_ping_task(queue: str) -> dict:
    """Stamps this queue's liveness key (sprint-5/11 S1, AC-11-86, D20).
    Published by beat onto EACH `KNOWN_QUEUES` entry every 60s, pinned via
    `options.queue` so the ping actually lands on (and is answered by) the
    worker consuming that specific queue - a ping that always landed on
    `workflow` would never catch a wedged `worker_jobs`."""
    from app.ops_liveness import stamp_liveness

    stamp_liveness(queue)
    return {"queue": queue}


@celery_app.task(name="status.reevaluate_time_based")
def reevaluate_time_based_task() -> dict:
    from app.database import SessionLocal
    from app.status_engine.derived import install_derived_status
    from app.workflow_engine.scheduler import reevaluate_time_based

    # The worker process runs no FastAPI lifespan - ensure the derived-status
    # subscriber is registered so cross-entity cascades work here too.
    install_derived_status()
    db = SessionLocal()
    try:
        advanced = reevaluate_time_based(db)
        return {"advanced": advanced}
    except Exception:  # noqa: BLE001 - a bad tick never kills the beat loop
        logger.exception("derived-status time sweep failed")
        db.rollback()
        return {"advanced": 0}
    finally:
        db.close()


@celery_app.task(
    name="workflows.run_workflow",
    soft_time_limit=settings.workflow_run_soft_time_limit_seconds,
    time_limit=settings.workflow_run_soft_time_limit_seconds + 300,
)
def run_workflow_task(run_id: str) -> dict:
    from app.database import SessionLocal
    from app.models.workflow import RUN_FAILED, WorkflowRun
    from app.workflow_engine.executor import run_workflow

    # The worker runs no FastAPI lifespan, so module-registered workflow nodes
    # (omnichannel trigger/actions, plan sprint-4/17; any future module
    # TriggerDef/ActionDef) never got booted here - a prod run failed
    # `Unknown action "omnichannel.send_message"` (invisible in eager dev, which
    # executes inline in the API process where `load_modules` already ran).
    # Task-scoped + lazy_once, NOT module-level: worker.py is imported by the
    # API process too (jobs/import workers share `celery_app`), and booting
    # every module at import would run ahead of lifespan + pollute tests.
    _ensure_module_nodes()
    db = SessionLocal()
    try:
        run = run_workflow(db, run_id)
        return {"runId": run.id, "status": run.status}
    except SoftTimeLimitExceeded:
        # Review round 1 (B2) - caught BEFORE the generic `except Exception`
        # below (it IS an Exception subclass; the generic branch would
        # otherwise stamp it with the wrong "Run crashed unexpectedly." text).
        # Never re-raised: letting it propagate would crash the worker
        # process instead of failing this run cleanly.
        logger.error("workflow run %s hit its soft time limit", run_id)
        db.rollback()
        run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
        if run is not None:
            run.status = RUN_FAILED
            run.error = WORKFLOW_RUN_TIME_LIMIT_ERROR
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        return {"runId": run_id, "status": RUN_FAILED}
    except Exception:  # noqa: BLE001 - never let a run crash the worker silently
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


@celery_app.task(
    name="workflows.wake_serialized",
    soft_time_limit=settings.workflow_run_soft_time_limit_seconds,
    time_limit=settings.workflow_run_soft_time_limit_seconds + 300,
)
def wake_serialized_task(tenant_id: str, workflow_id: str, digest: str) -> dict:
    """Idempotent wakeup for one durable Postgres FIFO scope."""
    from app.database import SessionLocal
    from app.workflow_engine.serialization import (
        SerializedCoordinationUnavailable,
        drain_serialized_runs,
    )

    # Same module-node boot as run_workflow_task: the drain executes runs
    # in THIS process, so module actions must be registered here too.
    _ensure_module_nodes()
    db = SessionLocal()
    try:
        return drain_serialized_runs(db, tenant_id, workflow_id, digest)
    except SerializedCoordinationUnavailable as exc:
        logger.error("serialized workflow coordination unavailable: %s", exc)
        db.rollback()
        return {"admitted": False, "drained": 0, "error": str(exc)}
    except SoftTimeLimitExceeded:
        # Review round 2 (B3) - `drain_serialized_runs` ITSELF now catches
        # `SoftTimeLimitExceeded` before its own inner generic except, fails
        # the EXACT run_id in flight (never a sibling's, never a guess at
        # "whatever is RUNNING for this scope" - the round-1 shape here used
        # to do exactly that, an ownership bug), and re-raises so the drain
        # loop stops immediately instead of continuing to the next pending
        # run past this worker's own soft limit. By the time it reaches
        # here the run row is already closed; this branch only logs and
        # returns.
        logger.error(
            "serialized workflow drain for workflow %s (tenant %s) hit its "
            "soft time limit", workflow_id, tenant_id,
        )
        db.rollback()
        return {"admitted": True, "drained": 0, "error": WORKFLOW_RUN_TIME_LIMIT_ERROR}
    except Exception:  # noqa: BLE001
        # A crash rolls the active transaction back to Pending. Recovery beat or
        # a duplicate wakeup will retry it after the lease is available.
        logger.exception("serialized workflow drain crashed")
        db.rollback()
        return {"admitted": True, "drained": 0, "error": "Drain crashed."}
    finally:
        db.close()


# ── Cross-package task + handler registration (worker has no FastAPI lifespan) ─
# `-A app.workflow_engine.worker` only sees tasks/handlers whose module is
# imported. Without these the worker DISCARDS `jobs.run` as an unregistered task
# (silent stall - the storage-migration job hangs Pending forever).
import app.jobs.worker  # noqa: E402,F401 - registers the `jobs.run` Celery task
import app.storage_migration.service  # noqa: E402,F401 - module-level register_storage_migration_handler()
import modules.autocount.sync  # noqa: E402,F401 - registers the `autocount_sync` AND `autocount_pull_snapshot` job handlers
import modules.meetings.jobs  # noqa: E402,F401 - registers the `meetings.calendar_sync` handler
