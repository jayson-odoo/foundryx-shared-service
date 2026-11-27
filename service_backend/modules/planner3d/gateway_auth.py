"""Gateway auth for ``/api/v1/planner3d/*`` (contract 2.1).

``Authorization: Bearer fx3_live_...`` resolves to ONE tenant; nothing in the path,
query or body ever chooses the tenant. Order: per-IP throttle (counts 401s only) ->
key -> tenant may sign in + module ACTIVE -> per-key request budget. Every call
with a resolved key is audited (tenant, key, method, route, status) by
``AuditedRoute``; no payload is stored. Repeats ``modules/lead_capture/gateway_auth.py``
(cross-module imports are forbidden, BL-SS-210).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from fastapi import Depends, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db
from app.models.tenant import Tenant
from app.repositories.module_repository import ModuleRepository
from app.services.throttle import Throttled, ThrottleService, client_ip

from .models import P3ApiAudit
from .services import key_service

logger = logging.getLogger(__name__)

MODULE_NAME = "planner3d"


@dataclass(frozen=True)
class Planner3dGatewayKey:
    tenant_id: str
    key_id: str


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def module_enabled(db: Session, tenant_id: str) -> bool:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or not tenant.signin_allowed:
        return False
    return ModuleRepository(db).is_active(tenant_id, MODULE_NAME)


def get_planner3d_gateway_key(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Planner3dGatewayKey:
    ip = client_ip(request)
    throttle = ThrottleService(db)
    try:
        throttle.enforce_planner3d_gateway(ip=ip)
    except Throttled as exc:
        raise ApiError(429, "rate_limited", "Too many failed attempts. Try again shortly.").with_retry_after(
            exc.retry_after_seconds
        )
    row = key_service.resolve(db, _bearer(authorization))
    if row is None:
        throttle.record_planner3d_gateway_failure(ip=ip)
        raise ApiError(401, "invalid_api_key", "Missing, malformed, unknown or revoked key.")
    key = Planner3dGatewayKey(tenant_id=row.tenant_id, key_id=row.id)
    request.state.planner3d_gateway_key = key
    if not module_enabled(db, row.tenant_id):
        raise ApiError(403, "service_not_enabled", "3D Planner is not enabled for this tenant.")
    try:
        throttle.enforce_planner3d_gateway_key(key_id=row.id)
    except Throttled as exc:
        raise ApiError(429, "rate_limited", "Too many requests for this key.").with_retry_after(
            exc.retry_after_seconds
        )
    throttle.record_planner3d_gateway_key_request(key_id=row.id)
    key_service.mark_used(db, row)
    return key


def _audit(key: Planner3dGatewayKey, method: str, route: str, status: int) -> None:
    """Own short session: an audit write never joins (or breaks) the request's."""
    db = _audit_session()
    try:
        db.add(P3ApiAudit(tenant_id=key.tenant_id, key_id=key.key_id, method=method[:8], route=route[:200], status_code=status))
        db.commit()
    except Exception:  # noqa: BLE001 - auditing never breaks the call
        logger.exception("planner3d gateway audit write failed")
        db.rollback()
    finally:
        db.close()


def _audit_session() -> Session:
    """Looked up at call time so tests bind it to their engine."""
    import app.database as database

    return database.SessionLocal()


class AuditedRoute(APIRoute):
    """Records one ``p3_api_audit`` row per call whose key resolved."""

    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()
        path = self.path

        async def audited(request: Request) -> Response:
            status = 500
            try:
                response = await handler(request)
                status = response.status_code
                return response
            except ApiError as exc:
                status = exc.status_code
                raise
            except HTTPException as exc:
                status = exc.status_code
                raise
            except RequestValidationError:
                status = 422
                raise
            finally:
                key = getattr(request.state, "planner3d_gateway_key", None)
                if key is not None:
                    _audit(key, request.method, path, status)

        return audited
