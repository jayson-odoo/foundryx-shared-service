"""Gateway auth + error rendering for ``/api/v1/dashboards/*`` (contract 1 and 3.8).

``X-API-Key: fxd_live_...`` resolves to ONE tenant and ONE product; nothing in the path, query or
body ever chooses either. A ``tenant`` / ``product`` echoed in the body or query that disagrees with
the key is refused (403 ``tenant_mismatch`` / ``product_mismatch``). Order: per-IP throttle (counts
401s only) -> key -> tenant may sign in + module ACTIVE -> echo check -> per-key request budget.
Every call with a resolved key is audited (tenant, product, key, method, route, status) by ``DashRoute``;
no payload is stored.

``DashRoute`` also renders every error of this router as the contract's flat body
``{"error", "message", ...}`` (core's ``ApiError`` envelope is untouched) and turns request validation
failures into 422 ``spec_invalid`` with plain problems. Repeats the planner3d gateway shape
(cross-module imports are forbidden, BL-SS-210).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.repositories.module_repository import ModuleRepository
from app.services.throttle import Throttled, ThrottleService, client_ip

from .models import DashApiAudit
from .repositories.key_repository import KeyRepository
from .services import key_service
from .services.errors import DashError

logger = logging.getLogger(__name__)

MODULE_NAME = "dashboards"


@dataclass(frozen=True)
class DashKey:
    tenant_id: str
    product: str
    key_id: str
    tenant_slug: str = ""


def _enabled_tenant(db: Session, tenant_id: str) -> Optional[Tenant]:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or not tenant.signin_allowed:
        return None
    if not ModuleRepository(db).is_active(tenant_id, MODULE_NAME):
        return None
    return tenant


def _json_body(request: Request) -> Any:
    """The JSON body, parsed only here (after the key resolved) from the bytes ``DashRoute`` already read."""
    if not hasattr(request.state, "dash_json"):
        raw = getattr(request.state, "dash_raw", b"")
        try:
            request.state.dash_json = json.loads(raw or b"null")
        except ValueError:
            request.state.dash_json = None
    return request.state.dash_json


def _echoed(request: Request, name: str) -> List[str]:
    """EVERY non-empty ``tenant`` / ``product`` the caller echoed in the query or JSON body (never trusted,
    only compared): one matching value must not hide a mismatching one."""
    values: List[Any] = [request.query_params.get(name)]
    body = _json_body(request)
    if isinstance(body, dict):
        values.append(body.get(name))
    return [str(v) for v in values if v not in (None, "")]


def authenticate(request: Request, db: Session) -> DashKey:
    """Per-IP throttle -> key -> tenant + module -> echo check -> per-key budget. Runs on the raw request
    (headers, query, the already-read body BYTES) before anything is parsed."""
    ip = client_ip(request)
    throttle = ThrottleService(db)
    try:
        throttle.enforce_dashboards_gateway(ip=ip)
    except Throttled as exc:
        raise DashError(429, "rate_limited", "Too many failed attempts. Try again shortly.",
                        headers={"Retry-After": str(int(exc.retry_after_seconds))})
    row = key_service.resolve(db, (request.headers.get("x-api-key") or "").strip() or None)
    if row is None:
        throttle.record_dashboards_gateway_failure(ip=ip)
        raise DashError(401, "invalid_api_key", "Missing, malformed, unknown or revoked key.")
    key = DashKey(tenant_id=row.tenant_id, product=row.product, key_id=row.id)
    request.state.dash_key = key
    tenant = _enabled_tenant(db, row.tenant_id)
    if tenant is None:
        raise DashError(403, "service_not_enabled", "Dashboards is not enabled for this tenant.")
    key = DashKey(tenant_id=row.tenant_id, product=row.product, key_id=row.id, tenant_slug=tenant.slug)
    request.state.dash_key = key
    if any(v not in (key.tenant_id, key.tenant_slug) for v in _echoed(request, "tenant")):
        raise DashError(403, "tenant_mismatch", "This key belongs to a different tenant.")
    if any(v != key.product for v in _echoed(request, "product")):
        raise DashError(403, "product_mismatch", "This key belongs to a different product.")
    try:
        throttle.enforce_dashboards_gateway_key(key_id=row.id)
    except Throttled as exc:
        raise DashError(429, "rate_limited", "Too many requests for this key.",
                        headers={"Retry-After": str(int(exc.retry_after_seconds))})
    throttle.record_dashboards_gateway_key_request(key_id=row.id)
    key_service.mark_used(db, row)
    request.state.dash_authenticated = key
    return key


def get_dash_key(request: Request, db: Session = Depends(get_db)) -> DashKey:
    """The key ``DashRoute`` already resolved BEFORE the body was parsed (authenticates here only if a
    route is ever mounted without ``DashRoute``)."""
    return getattr(request.state, "dash_authenticated", None) or authenticate(request, db)


# -- audit ---------------------------------------------------------------------------------------------

def _audit_session() -> Session:
    """Looked up at call time so tests bind it to their engine."""
    import app.database as database

    return database.SessionLocal()


def _audit(key: DashKey, method: str, route: str, status: int) -> None:
    """Own short session: an audit write never joins (or breaks) the request's."""
    db = _audit_session()
    try:
        KeyRepository(db).add_audit(DashApiAudit(
            tenant_id=key.tenant_id, product=key.product, key_id=key.key_id,
            method=method[:8], route=route[:200], status_code=status))
        db.commit()
    except Exception:  # noqa: BLE001 - auditing never breaks the call
        logger.exception("dashboards gateway audit write failed")
        db.rollback()
    finally:
        db.close()


# -- plain request-validation problems -------------------------------------------------------------------

def _request_problems(exc: RequestValidationError) -> List[Dict[str, str]]:
    from .spec import _plain  # same plain-words translation as the spec validator

    problems = []
    for err in exc.errors():
        loc = [p for p in err.get("loc", ()) if p not in ("body", "query", "path")]
        path = ""
        for part in loc:
            path += f"[{part}]" if isinstance(part, int) else (("." if path else "") + str(part))
        problems.append({"path": path, "reason": _plain({**err, "loc": tuple(loc)})})
    return problems


def _authenticate_first(request: Request) -> None:
    """Resolve the key and run both throttles on the raw request, in a session of their own, before FastAPI
    parses the body (it decodes a JSON body before it solves dependencies, so a dependency alone is too late)."""
    from app.database import get_db as core_get_db

    provider = request.app.dependency_overrides.get(core_get_db, core_get_db)
    gen = provider()
    db = next(gen)
    try:
        authenticate(request, db)
    finally:
        gen.close()


class DashRoute(APIRoute):
    """Audits every call whose key resolved and renders every error as the contract's flat body."""

    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()
        path = self.path

        async def wrapped(request: Request) -> Response:
            if request.method in ("POST", "PUT", "PATCH"):
                request.state.dash_raw = await request.body()  # bytes only (the body cap bounds them); parsed after the key is resolved
            try:
                _authenticate_first(request)
                response = await handler(request)
            except DashError as exc:
                response = JSONResponse(exc.body(), status_code=exc.status_code, headers=exc.headers)
            except RequestValidationError as exc:
                response = JSONResponse(
                    {"error": "spec_invalid", "message": "Some values are not valid.", "problems": _request_problems(exc)},
                    status_code=422,
                )
            status = response.status_code
            key = getattr(request.state, "dash_key", None)
            if key is not None:
                _audit(key, request.method, path, status)
            return response

        return wrapped
