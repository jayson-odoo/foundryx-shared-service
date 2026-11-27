"""Planner 3D's deferred (grace-window) actions (lane PLANNER-3D-S1).

The Keys and Receivers screens' destructive row actions (revoke a key, remove a
receiver) park on the CORE grace-window engine instead of a confirm dialog, as
Lead Capture's do (``modules/lead_capture/deferred_actions.py``). Each handler
calls the existing service function; registered from
``bootstrap.register_engine_entities()``. Same permissions as the staff routes.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.deferred_actions.registry import DeferredActionDef, register_deferred_action

MODULE_NAME = "planner3d"
KEYS_MANAGE = "planner3d.keys.manage"
HOOKS_MANAGE = "planner3d.webhooks.manage"


def _key_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from .models import P3ApiKey

    return (
        db.query(P3ApiKey.id)
        .filter(P3ApiKey.id == entity_id, P3ApiKey.tenant_id == tenant_id, P3ApiKey.revoked_at.is_(None))
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
    from .models import P3Receiver

    return (
        db.query(P3Receiver.id)
        .filter(P3Receiver.id == entity_id, P3Receiver.tenant_id == tenant_id, P3Receiver.active.is_(True))
        .first()
        is not None
    )


def _receiver_remove(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services import events_service
    from .services.errors import P3Error

    try:
        events_service.delete_receiver(db, tenant_id, entity_id)
    except P3Error as exc:
        raise ValueError(exc.message) from None


KEY_REVOKE = DeferredActionDef(
    key="planner3d_keys.revoke",
    module=MODULE_NAME,
    entity_type="planner3d_key",
    permission=KEYS_MANAGE,
    window="destructive",
    label="Revoke",
    execute=_key_revoke,
    exists=_key_exists,
    gone_message="This key was already revoked.",
)
RECEIVER_REMOVE = DeferredActionDef(
    key="planner3d_receivers.remove",
    module=MODULE_NAME,
    entity_type="planner3d_receiver",
    permission=HOOKS_MANAGE,
    window="destructive",
    label="Remove",
    execute=_receiver_remove,
    exists=_receiver_exists,
    gone_message="This receiver was already removed.",
)


def register_planner3d_deferred_actions() -> None:
    for action_def in (KEY_REVOKE, RECEIVER_REMOVE):
        register_deferred_action(action_def)
