"""AutoCount's own deferred (grace-window) action registration (sprint-5/07
review round - "Re-push all" is a destructive action and D2/D13 reserve the
typed-confirm `AlertDialog` to the four named carve-outs
(`confirm-carve-outs.inventory.test.ts`), none of which this is. Registered
from `bootstrap.register_engine_entities()` (mirrors how `omnichannel`/
`ideation` extend the SAME core grace-window engine - never a fork).

    !!  THE POST /etl-task/repush ROUTE STAYS - THIS IS A SECOND CALLER.  !!

The API-path route (`routers/companies.py::repush_etl_task`) is untouched -
existing API callers/tests keep working exactly as before. This module wires
the SAME `EtlService.repush_task` into the deferred-actions engine as a
SECOND entry point, the one the "Re-push all" tab button now uses
(`useDeferredAction`/`pendingActionsService.park`) instead of calling the
route directly.

Entity id: `ac_entity_config.id` (the one per-(company, entityType) TASK row
already has a globally-unique PK) - `entity_type="autocount_etl_task"` is a
deferred-actions catalog label, NOT an AutoCount sync entity type (which the
task's OWN `entity_type` column already names, e.g. `sales_order`) - the two
are deliberately distinct vocabularies to avoid a confusing collision.
"""
from sqlalchemy.orm import Session

from app.deferred_actions.registry import DeferredActionDef, register_deferred_action

AC_COMPANIES_MANAGE = "autocount.companies.manage"


def _etl_task_config(db: Session, tenant_id: str, entity_id: str):
    """The `ac_entity_config` row for `entity_id`, tenant-scoped - never a
    bare id lookup (the polymorphic-target_id rule: a stored/caller-supplied
    id is only ever resolved WITH the caller's own tenant)."""
    from .models import AcEntityConfig

    return (
        db.query(AcEntityConfig)
        .filter(AcEntityConfig.id == entity_id, AcEntityConfig.tenant_id == tenant_id)
        .first()
    )


def _etl_task_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    return _etl_task_config(db, tenant_id, entity_id) is not None


def _etl_task_repush(
    db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str
) -> None:
    """The commit-time handler. `company_id`/`entity_type` (the ETL task's
    OWN compound key) are resolved FROM the `ac_entity_config` row itself -
    the deferred-actions engine's executor signature carries only a single
    `entity_id`, not the task's compound key.

    `EtlService.repush_task` already commits on success and raises
    `EtlStateError` on every refusal (draft / not a database task / a run in
    flight); `PendingActionService.commit_one` catches ANY exception here,
    rolls back, and marks the row `failed` with `str(exc)` (which for
    `EtlStateError` is exactly its `.message` - `Exception.__init__` was
    called with it) - no special-casing needed, the SAME failed-commit path
    every other deferred action's handler uses.
    """
    from .services.etl_service import EtlService

    config = _etl_task_config(db, tenant_id, entity_id)
    if config is None:
        # The row vanished between park and commit (e.g. the company was
        # removed mid-window) - `exists` already guarded park time, so this
        # is the same "target vanished before commit" class every other
        # deferred handler's own re-check guards against.
        raise ValueError("This task no longer exists.")
    EtlService(db).repush_task(
        tenant_id, config.company_id, config.entity_type, actor_user_id=actor_user_id or None,
    )


ETL_TASK_REPUSH = DeferredActionDef(
    key="autocount_etl_task.repush",
    module="autocount",
    entity_type="autocount_etl_task",
    permission=AC_COMPANIES_MANAGE,
    window="destructive",
    label="Re-push all",
    execute=_etl_task_repush,
    exists=_etl_task_exists,
)

_ALL = (ETL_TASK_REPUSH,)


def register_autocount_deferred_actions() -> None:
    for action_def in _ALL:
        register_deferred_action(action_def)
