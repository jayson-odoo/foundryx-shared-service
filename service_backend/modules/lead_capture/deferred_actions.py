"""Lead Capture's deferred (grace-window) actions (lane L-D, AC-64-57).

The Lead Capture screens' destructive row actions (revoke a key, remove a
receiver) park on the CORE grace-window engine instead of a confirm dialog.
Each handler calls the existing service function; registered from
``bootstrap.register_engine_entities()``. Same permissions as the staff routes.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.deferred_actions.registry import DeferredActionDef, register_deferred_action

MODULE_NAME = "lead_capture"
KEYS_MANAGE = "lead_capture.keys.manage"
MANAGE = "lead_capture.manage"


def _key_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from .models import LcApiKey

    return (
        db.query(LcApiKey.id)
        .filter(LcApiKey.id == entity_id, LcApiKey.tenant_id == tenant_id, LcApiKey.revoked_at.is_(None))
        .first()
        is not None
    )


def _key_revoke(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services import key_service

    try:
        key_service.revoke(db, tenant_id, entity_id)
    except key_service.KeyNotFound:
        raise ValueError("Key no longer exists.") from None


def _receiver_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from .services import delivery_service

    try:
        delivery_service.get_endpoint(db, tenant_id, entity_id)
    except delivery_service.DeliveryError:
        return False
    return True


def _receiver_remove(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services import delivery_service

    try:
        delivery_service.delete_endpoint(db, tenant_id, entity_id)
    except delivery_service.DeliveryError as exc:
        raise ValueError(exc.message) from None


# The field list is one per company: the entity id is this fixed name.
FIELD_LIST_ENTITY_ID = "fields"


def _field_list_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    return entity_id == FIELD_LIST_ENTITY_ID


def _fields_reset(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services import field_service

    # The same function as PUT /fields with [] (both doors): the list goes back
    # to the defaults and map lines to removed fields are pruned with it.
    field_service.set_fields(db, tenant_id, [])


KEY_REVOKE = DeferredActionDef(
    key="lead_capture_keys.revoke",
    module=MODULE_NAME,
    entity_type="lead_capture_key",
    permission=KEYS_MANAGE,
    window="destructive",
    label="Revoke",
    execute=_key_revoke,
    exists=_key_exists,
    gone_message="This key was already revoked.",
)
RECEIVER_REMOVE = DeferredActionDef(
    key="lead_capture_receivers.remove",
    module=MODULE_NAME,
    entity_type="lead_capture_receiver",
    permission=MANAGE,
    window="destructive",
    label="Remove",
    execute=_receiver_remove,
    exists=_receiver_exists,
    gone_message="This receiver was already removed.",
)


FIELDS_RESET = DeferredActionDef(
    key="lead_capture_fields.reset",
    module=MODULE_NAME,
    entity_type="lead_capture_fields",
    permission=MANAGE,
    window="destructive",
    label="Use defaults",
    execute=_fields_reset,
    exists=_field_list_exists,
)


def register_lead_capture_deferred_actions() -> None:
    for action_def in (KEY_REVOKE, RECEIVER_REMOVE, FIELDS_RESET):
        register_deferred_action(action_def)
