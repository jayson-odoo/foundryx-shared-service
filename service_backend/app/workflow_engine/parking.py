"""Run parking primitives (plan sprint-4/31 S4, D-A5-6).

An action that needs to wait for something outside the run (a contact's reply,
a wall-clock delay) raises :class:`WorkflowPaused`. The executor catches it,
snapshots the walk on ``workflow_runs.resume_state_json`` and leaves the run
``waiting``; a later :func:`app.workflow_engine.executor.resume_run` re-enters
the SAME walk.

Everything here is generic - core never learns what a "contact" or a "wait row"
is. The module that parked a run registers a cleanup callback
(:func:`register_wait_cleanup`) so cancelling / discarding a parked run also
drops whatever index the module keeps pointing at it.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.workflow import RUN_CANCELLED, RUN_WAITING, WorkflowRun

logger = logging.getLogger("foundryx.workflows.parking")


class WorkflowPaused(Exception):
    """An action asks the engine to suspend this run at the current node.

    Control flow, not a failure: the node's trace row is written SUCCESSFUL with
    ``output_json = {"parked": True, **output}``, downstream nodes are left
    untouched (never "skipped"), and the run goes ``waiting``.
    """

    def __init__(self, *, output: Optional[Dict[str, Any]] = None):
        super().__init__("Workflow paused.")
        self.output: Dict[str, Any] = dict(output or {})


# A cleanup callback: (db, run) -> None. Registered by whichever module parked
# the run; called when a parked run is cancelled or otherwise abandoned so the
# module's own index row (omnichannel's ``workflow_waits``) never outlives it.
WaitCleanupFn = Callable[[Session, WorkflowRun], None]

_wait_cleanups: List[WaitCleanupFn] = []


def register_wait_cleanup(fn: WaitCleanupFn) -> None:
    """Register a parked-run cleanup callback. Idempotent."""
    if fn not in _wait_cleanups:
        _wait_cleanups.append(fn)


def unregister_wait_cleanup(fn: WaitCleanupFn) -> None:
    if fn in _wait_cleanups:
        _wait_cleanups.remove(fn)


def run_wait_cleanup(db: Session, run: WorkflowRun) -> None:
    """Fan a parked run's abandonment out to every registered cleanup, each
    isolated - a failing module cleanup never blocks the cancel it rides on."""
    for fn in list(_wait_cleanups):
        try:
            fn(db, run)
        except Exception:  # noqa: BLE001 - cleanup is best-effort by design
            logger.exception("parked-run wait cleanup failed for run %s", run.id)


def cancel_parked_run(
    db: Session, run_id: str, tenant_id: str, *, reason: str
) -> Optional[WorkflowRun]:
    """Cancel a ``waiting`` run TENANT-SCOPED (AC-WFP-52/54) and drop its
    module wait rows. Returns the run, or ``None`` when it is not this
    tenant's / no longer parked. Never commits on behalf of the caller's own
    unit of work beyond this row - it flushes and lets the caller commit."""
    run = (
        db.query(WorkflowRun)
        .filter(WorkflowRun.id == run_id, WorkflowRun.tenant_id == tenant_id)
        .first()
    )
    if run is None or run.status != RUN_WAITING:
        return None
    run_wait_cleanup(db, run)
    run.status = RUN_CANCELLED
    run.error = reason
    run.finished_at = datetime.now(timezone.utc)
    run.paused_node_id = None
    run.resume_state_json = None
    db.flush()
    return run
