"""Hub Connector's deferred (grace-window) actions.

The screens' destructive row actions (delete a hub, take a customer off a hub,
revoke a CRM key) park on the CORE grace-window engine instead of a confirm
dialog. Each handler calls the SAME service function as the staff route;
registered from ``bootstrap.register_engine_entities()``. Same permissions as
the staff routes.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.deferred_actions.registry import DeferredActionDef, register_deferred_action

MODULE_NAME = "hub_connector"
MANAGE = "hub_connector.manage"
KEYS_MANAGE = "hub_connector.keys.manage"


def _hub_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from .models import HcHub

    return db.query(HcHub.id).filter(HcHub.id == entity_id, HcHub.tenant_id == tenant_id).first() is not None


def _hub_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services import hub_service

    try:
        hub_service.delete_hub(db, tenant_id, entity_id)
    except hub_service.HubError as exc:
        raise ValueError(exc.message) from None


def _customer_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from .models import HcHubCustomer

    return (
        db.query(HcHubCustomer.id)
        .filter(HcHubCustomer.id == entity_id, HcHubCustomer.tenant_id == tenant_id)
        .first()
        is not None
    )


def _customer_remove(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .models import HcHubCustomer
    from .services import delivery_service
    from .services.hub_service import HubError

    # The hub is read from the stored row (tenant-scoped), never trusted from the payload.
    row = (
        db.query(HcHubCustomer)
        .filter(HcHubCustomer.id == entity_id, HcHubCustomer.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        raise ValueError("This customer was already removed.")
    from .services import history_service

    try:
        delivery_service.remove_customer(
            db, tenant_id, row.hub_id, row.id, actor=history_service.actor_for(db, tenant_id, actor_user_id, actor_user_id)
        )
    except HubError as exc:
        raise ValueError(exc.message) from None


def _key_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from .models import HcApiKey

    return (
        db.query(HcApiKey.id)
        .filter(HcApiKey.id == entity_id, HcApiKey.tenant_id == tenant_id, HcApiKey.revoked_at.is_(None))
        .first()
        is not None
    )


def _key_revoke(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services import history_service, key_service

    try:
        row = key_service.revoke(db, tenant_id, entity_id)
    except key_service.KeyNotFound:
        raise ValueError("Key no longer exists.") from None
    history_service.record(
        db, tenant_id, row.hub_id, history_service.actor_for(db, tenant_id, actor_user_id, actor_user_id),
        "Hub key revoked", row.name, None,
    )
    db.commit()


HUB_DELETE = DeferredActionDef(
    key="hub_connector_hubs.delete",
    module=MODULE_NAME,
    entity_type="hub_connector_hub",
    permission=MANAGE,
    window="destructive",
    label="Delete",
    execute=_hub_delete,
    exists=_hub_exists,
    gone_message="This hub was already deleted.",
)
CUSTOMER_REMOVE = DeferredActionDef(
    key="hub_connector_customers.remove",
    module=MODULE_NAME,
    entity_type="hub_connector_customer",
    permission=MANAGE,
    window="destructive",
    label="Remove",
    execute=_customer_remove,
    exists=_customer_exists,
    gone_message="This customer was already removed.",
)
KEY_REVOKE = DeferredActionDef(
    key="hub_connector_keys.revoke",
    module=MODULE_NAME,
    entity_type="hub_connector_key",
    permission=KEYS_MANAGE,
    window="destructive",
    label="Revoke",
    execute=_key_revoke,
    exists=_key_exists,
    gone_message="This key was already revoked.",
)


def register_hub_connector_deferred_actions() -> None:
    for action_def in (HUB_DELETE, CUSTOMER_REMOVE, KEY_REVOKE):
        register_deferred_action(action_def)
