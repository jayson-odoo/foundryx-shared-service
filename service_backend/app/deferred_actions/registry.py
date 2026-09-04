"""Code-side registry of deferred (grace-window) actions (AC-DLA-38).

Mirrors `app/jobs/registry.py`: one `DeferredActionDef` per `<entity>.<verb>`
key, registered at boot (`app/deferred_actions/handlers.py`, called from
`app/main.py`'s lifespan and `tests/conftest.py`). Unknown/duplicate keys are
LOUD errors - never a silent no-op (a park against an unregistered key would
otherwise sit forever with nothing to commit it).
"""
from dataclasses import dataclass
from typing import Callable, Dict, List, Literal

from sqlalchemy.orm import Session

# execute(db, tenant_id, entity_id, payload, actor_user_id) -> None. The
# handler owns its own commit (it calls the existing service method, which
# already commits); it must raise on failure so the service can mark the row
# `failed` with the exception text - never swallow an error silently.
DeferredActionExecutor = Callable[[Session, str, str, dict, str], None]

# exists(db, tenant_id, entity_id) -> bool - a tenant-scoped existence check
# run at PARK time (missing target = 404, fix round 1 item 7) so parking an
# action on a record that's already gone (or never existed) fails loudly
# instead of silently sitting until commit.
DeferredActionExistsCheck = Callable[[Session, str, str], bool]

DeferredActionWindow = Literal["destructive", "reversible"]


@dataclass(frozen=True)
class DeferredActionDef:
    """One deferred-action `key` and the handler that commits it.

    `permission` is the SAME permission key the entity's own mutating
    endpoint already gates (AC-DLA-38/D nothing new: "no new permission" -
    every hard-fail list in this repo rejects a permission with no grant
    path, so deferred actions reuse the entity's existing grant instead).
    """

    key: str  # `<entity>.<verb>`, e.g. "users.trash"
    entity_type: str
    permission: str
    window: DeferredActionWindow
    label: str
    execute: DeferredActionExecutor
    #: Tenant-scoped existence check for the target record, run at park time
    #: (fix round 1 item 7). Wired to the entity's own repository `get_by_id`
    #: (or equivalent) - a missing target 404s the park instead of parking a
    #: countdown for a record that isn't there.
    exists: DeferredActionExistsCheck
    #: True for a platform-only action (e.g. tenant archive from the console) -
    #: `PendingActionService.park` additionally requires the actor's OWN
    #: tenant to be the platform tenant, mirroring `require_platform_permission`
    #: (a plain permission-key check alone is not the double lock that
    #: dependency provides).
    platform: bool = False


_REGISTRY: Dict[str, DeferredActionDef] = {}


class UnknownDeferredAction(Exception):
    """Park/execute was asked to run a `key` with no registered handler."""


def register_deferred_action(action_def: DeferredActionDef) -> None:
    """Register a deferred action. Duplicate `key` = loud error (a re-run of
    the SAME def object is tolerated - idempotent boot registration)."""
    existing = _REGISTRY.get(action_def.key)
    if existing is not None and existing is not action_def:
        raise ValueError(f"Duplicate deferred-action registration for key '{action_def.key}'.")
    _REGISTRY[action_def.key] = action_def


def deferred_action_for(key: str) -> DeferredActionDef:
    """Resolve a registered action; unknown `key` raises (never a silent no-op)."""
    action_def = _REGISTRY.get(key)
    if action_def is None:
        raise UnknownDeferredAction(f"No deferred action registered for key '{key}'.")
    return action_def


def list_deferred_actions() -> List[DeferredActionDef]:
    return list(_REGISTRY.values())


def _reset_registry_for_tests() -> None:
    """Test seam - clears the registry (handlers re-register idempotently)."""
    _REGISTRY.clear()
