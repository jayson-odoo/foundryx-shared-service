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


KEY_REVOKE = DeferredActionDef(
    key="lead_capture_keys.revoke",
    module=MODULE_NAME,
    entity_type="lead_capture_key",
    permission=KEYS_MANAGE,
    window="destructive",
    label="Revoke",
    execute=_key_revoke,
    exists=_key_exists,
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
)


def register_lead_capture_deferred_actions() -> None:
    for action_def in (KEY_REVOKE, RECEIVER_REMOVE):
        register_deferred_action(action_def)
