"""Partner-key authentication for ``/api/v1/omnichannel/partner/*``.

``get_partner_tenant`` mirrors ``api_auth.get_api_workspace`` for the
tenant-scoped ``fxp_live_...`` key: Bearer -> (tenant, key). The tenant comes
from the key row, never from the request. Uniform ``401 invalid_api_key`` on any
miss (a workspace key is a miss here, and a partner key is a miss on the
workspace-key routes); per-key limits through the same ``key_limits`` store;
``403 service_not_enabled`` when the tenant may not sign in or the module is not
active for it.

It deliberately does NOT set ``request.state.api_workspace``: the gateway
activity log records request and response summaries for attributed calls, and a
partner response can carry a freshly minted workspace key.
"""
from dataclasses import dataclass
from typing import Iterator, Optional

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db, release_read_transactions
from app.models.tenant import Tenant
from app.repositories.module_repository import ModuleRepository

from .api_auth import MODULE_NAME, _parse_bearer
from .services import key_limits
from .services.partner_key_service import PartnerKeyService


@dataclass
class PartnerTenant:
    tenant_id: str
    key_id: str
    key_name: str


def partner_tenant_enabled(db: Session, tenant_id: str) -> bool:
    """The tenant may sign in and the module is active for it."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or not tenant.signin_allowed:
        return False
    return ModuleRepository(db).is_active(tenant_id, MODULE_NAME)


def get_partner_tenant(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Iterator[PartnerTenant]:
    token = _parse_bearer(authorization)
    if token is None:
        raise ApiError(401, "invalid_api_key", "Missing or malformed API key.")
    service = PartnerKeyService(db)
    row = service.resolve(token)
    if row is None:
        raise ApiError(401, "invalid_api_key", "Invalid API key.")
    partner = PartnerTenant(tenant_id=row.tenant_id, key_id=row.id, key_name=row.name)
    try:
        slot = key_limits.acquire(row.id)
    except key_limits.KeyLimitExceeded as exc:
        route = request.scope.get("route")
        key_limits.log_refusal(row.id, exc, getattr(route, "name", None) or request.url.path)
        raise ApiError(429, "rate_limited", "Too many requests for this key.").with_retry_after(
            exc.retry_after
        )
    try:
        service.touch(row)
        if not partner_tenant_enabled(db, row.tenant_id):
            raise ApiError(
                403, "service_not_enabled", "This service is not enabled for the tenant."
            )
        release_read_transactions()
        yield partner
    finally:
        key_limits.release(slot)
