"""Bearer-key authentication for the public BR build write-back route.

The public-route sibling of core ``get_current_user``: resolves
``Authorization: Bearer fxb_live_...`` to a tenant-scoped ``BrBuildKey`` - never
trusting the body/query for tenancy. Uniform 401 (core ``ApiError`` envelope) on
any miss. The per-IP ``build`` throttle is checked BEFORE resolution; only a 401
records a failure.
"""
from typing import Optional

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db
from app.models.tenant import Tenant
from app.repositories.module_repository import ModuleRepository
from app.services.throttle import Throttled, ThrottleService, client_ip

from .bootstrap import MODULE_NAME
from .models import BrBuildKey
from .services.build_keys import BuildKeyService


def _parse_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def get_build_key(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> BrBuildKey:
    ip = client_ip(request)
    throttle = ThrottleService(db)
    try:
        throttle.enforce_build(ip=ip)
    except Throttled as exc:
        raise ApiError(
            429, "too_many_requests", "Too many failed attempts. Try again shortly."
        ).with_retry_after(exc.retry_after_seconds)

    token = _parse_bearer(authorization)
    service = BuildKeyService(db)
    row = service.resolve(token) if token else None
    if row is None:
        throttle.record_build_failure(ip=ip)
        raise ApiError(401, "invalid_api_key", "Missing or invalid API key.")
    # Same predicate as the AutoCount pull gateway: the tenant's lifecycle
    # chokepoint (not blocked, not archived) AND the module active for it. A
    # refused key records NO throttle failure and stamps NO usage.
    tenant = db.get(Tenant, row.tenant_id)
    if (
        tenant is None
        or not tenant.signin_allowed
        or not ModuleRepository(db).is_active(row.tenant_id, MODULE_NAME)
    ):
        raise ApiError(
            403, "service_not_enabled", "This service is not enabled for this tenant."
        )
    service.mark_used(row)
    request.state.build_key = row
    return row
