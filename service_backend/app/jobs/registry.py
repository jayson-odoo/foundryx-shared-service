"""Background-job handler registry (sprint-4/10) — code-side, ``type``-keyed.

Mirrors the engine registries (status entities / rule facts / importers): a
``JobHandlerDef`` per job ``type`` registered at boot. Dispatch of an unknown
``type`` is a LOUD error (never a silent no-op), and a duplicate registration
for the same ``type`` is a loud error too (mirrors the capability registry).
"""
from dataclasses import dataclass
from typing import Callable, Dict, List

from sqlalchemy.orm import Session

from app.models.background_job import BackgroundJob

# handler(db, job) -> None. The handler owns its own progress/cursor writes and
# marks the job's terminal status via JobService helpers; it must be
# failure-isolated by the worker, never propagate.
JobHandler = Callable[[Session, BackgroundJob], None]


@dataclass(frozen=True)
class JobHandlerDef:
    """One job ``type`` and the callable that executes it."""

    type: str
    handler: JobHandler
    label: str


_REGISTRY: Dict[str, JobHandlerDef] = {}


class UnknownJobType(Exception):
    """Dispatch was asked to run a ``type`` with no registered handler."""


def register_job_handler(handler_def: JobHandlerDef) -> None:
    """Register a job handler. Duplicate ``type`` = loud error (a re-run of the
    SAME def object is tolerated — idempotent boot registration)."""
    existing = _REGISTRY.get(handler_def.type)
    if existing is not None and existing is not handler_def:
        raise ValueError(f"Duplicate job handler registration for type '{handler_def.type}'.")
    _REGISTRY[handler_def.type] = handler_def


def handler_for(job_type: str) -> JobHandlerDef:
    """Resolve a handler; unknown ``type`` raises (never a silent no-op)."""
    handler_def = _REGISTRY.get(job_type)
    if handler_def is None:
        raise UnknownJobType(f"No background-job handler registered for type '{job_type}'.")
    return handler_def


def list_job_handlers() -> List[JobHandlerDef]:
    return list(_REGISTRY.values())


def _reset_registry_for_tests() -> None:
    """Test seam — clears the registry (handlers re-register idempotently)."""
    _REGISTRY.clear()
