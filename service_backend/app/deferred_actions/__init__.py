"""Deferred actions - the grace-window engine (sprint-4/23, T5, D2).

Small and new (this repo has no prior form-SLA engine to generalise), modeled
on the repo's own registry idiom (`app/jobs/registry.py`): a code-side
`DeferredActionDef` per `<entity>.<verb>` key, a service that parks/cancels/
commits `PendingAction` rows, and a thin HTTP router. See
`app/deferred_actions/registry.py`, `service.py`, `handlers.py`.
"""
from app.deferred_actions.registry import (
    DeferredActionDef,
    UnknownDeferredAction,
    deferred_action_for,
    list_deferred_actions,
    register_deferred_action,
)

__all__ = [
    "DeferredActionDef",
    "UnknownDeferredAction",
    "deferred_action_for",
    "list_deferred_actions",
    "register_deferred_action",
]
