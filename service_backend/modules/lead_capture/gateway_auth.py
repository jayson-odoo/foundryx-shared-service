"""Gateway auth for ``/api/v1/lead-capture/*`` (AC-64-70/72).

``Authorization: Bearer fxl_live_...`` resolves to ONE tenant; nothing in the
request body or query ever chooses the tenant. Order: per-IP throttle (counts
401s only) -> key -> tenant may sign in + module ACTIVE -> per-key request
budget. Every call with a resolved key is audited (tenant, key, method, route,
status) by ``AuditedRoute``; no payload is stored.
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
from app.database import SessionLocal, get_db
from app.models.tenant import Tenant
from app.repositories.module_repository import ModuleRepository
from app.services.throttle import Throttled, ThrottleService, client_ip

from .models import LcApiAudit
from .services import key_service

logger = logging.getLogger(__name__)

MODULE_NAME = "lead_capture"


@dataclass(frozen=True)
class LeadGatewayKey:
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


def get_lead_gateway_key(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> LeadGatewayKey:
    ip = client_ip(request)
    throttle = ThrottleService(db)
    try:
        throttle.enforce_lead_gateway(ip=ip)
    except Throttled as exc:
        raise ApiError(429, "rate_limited", "Too many failed attempts. Try again shortly.").with_retry_after(
            exc.retry_after_seconds
        )
    row = key_service.resolve(db, _bearer(authorization))
    if row is None:
        throttle.record_lead_gateway_failure(ip=ip)
        raise ApiError(401, "invalid_api_key", "Missing, malformed, unknown or revoked key.")
    key = LeadGatewayKey(tenant_id=row.tenant_id, key_id=row.id)
    request.state.lead_gateway_key = key
    if not _enabled(db, row.tenant_id):
        raise ApiError(403, "service_not_enabled", "Lead Capture is not enabled for this tenant.")
    try:
        throttle.enforce_lead_gateway_key(key_id=row.id)
    except Throttled as exc:
        raise ApiError(429, "rate_limited", "Too many requests for this key.").with_retry_after(
            exc.retry_after_seconds
        )
    throttle.record_lead_gateway_key_request(key_id=row.id)
    key_service.mark_used(db, row)
    return key


def _audit(key: LeadGatewayKey, method: str, route: str, status: int) -> None:
    """Own short session: an audit write never joins (or breaks) the request's."""
    db = _audit_session()
    try:
        db.add(LcApiAudit(tenant_id=key.tenant_id, key_id=key.key_id, method=method[:8], route=route[:200], status_code=status))
        db.commit()
    except Exception:  # noqa: BLE001 - auditing never breaks the call
        logger.exception("lead gateway audit write failed")
        db.rollback()
    finally:
        db.close()


def _audit_session() -> Session:
    """Module-level so tests bind it to their engine."""
    return SessionLocal()


class AuditedRoute(APIRoute):
    """Records one ``lc_api_audit`` row per call whose key resolved."""

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
                key = getattr(request.state, "lead_gateway_key", None)
                if key is not None:
                    _audit(key, request.method, path, status)

        return audited
