"""Inbound auth for ``/api/v1/hub-connector/*`` (AC-17).

``Authorization: Bearer fxh_live_...`` resolves to ONE tenant; nothing in the
request body or query ever chooses the tenant. Order: per-IP throttle (counts
401s only) -> key -> tenant may sign in + module ACTIVE -> per-key request
budget (a valid or leaked key cannot hammer the push).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db
from app.models.tenant import Tenant
from app.models.auth_throttle import THROTTLE_SCOPE_HUB_PUSH, THROTTLE_SCOPE_HUB_PUSH_KEY
from app.repositories.module_repository import ModuleRepository
from app.services.throttle import ThrottleService, client_ip

from .services import key_service

MODULE_NAME = "hub_connector"


@dataclass(frozen=True)
class HubPushKey:
    tenant_id: str
    key_id: str


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _enabled(db: Session, tenant_id: str) -> bool:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or not tenant.signin_allowed:
        return False
    return ModuleRepository(db).is_active(tenant_id, MODULE_NAME)


def get_hub_push_key(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> HubPushKey:
    ip = client_ip(request)
    store = ThrottleService(db).store
    retry = store.check(THROTTLE_SCOPE_HUB_PUSH, ip)
    if retry is not None:
        raise ApiError(429, "rate_limited", "Too many failed attempts. Try again shortly.").with_retry_after(retry)
    row = key_service.resolve(db, _bearer(authorization))
    if row is None:
        store.record_failure(THROTTLE_SCOPE_HUB_PUSH, ip)
        raise ApiError(401, "invalid_api_key", "Missing, malformed, unknown or revoked key.")
    if not _enabled(db, row.tenant_id):
        raise ApiError(403, "service_not_enabled", "Hub Connector is not enabled for this tenant.")
    retry = store.check(THROTTLE_SCOPE_HUB_PUSH_KEY, row.id)
    if retry is not None:
        raise ApiError(429, "rate_limited", "Too many requests for this key.").with_retry_after(retry)
    store.record_failure(THROTTLE_SCOPE_HUB_PUSH_KEY, row.id)
    key_service.mark_used(db, row)
    return HubPushKey(tenant_id=row.tenant_id, key_id=row.id)
