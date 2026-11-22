"""Partner-key authentication for ``/api/v1/omnichannel/partner/*``.

``get_partner_tenant`` mirrors ``api_auth.get_api_workspace`` for the
tenant-scoped ``fxp_live_...`` key: Bearer -> (tenant, key). The tenant comes
from the key row, never from the request. Uniform ``401 invalid_api_key`` on any
miss (a workspace key is a miss here, and a partner key is a miss on the
workspace-key routes); per-key limits through the same ``key_limits`` store;
``403 service_not_enabled`` when the tenant may not sign in or the module is not
active for it.

The key also resolves its client app (its own, or the tenant's default when its
parent is NULL; NULL parents in the tenant are resolved and persisted first) and ``403 client_app_disabled`` refuses a
DISABLED client app. That status is checked here only: workspace keys, webhooks,
the dashboard and the public gateway never look at it.

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
from .services.client_app_service import STATUS_ACTIVE, ClientAppService
from .services.partner_key_service import PartnerKeyService


@dataclass
class PartnerTenant:
    tenant_id: str
    key_id: str
    key_name: str
    # The client app the key acts for (its own, or the tenant's default when
    # the key's parent is NULL). Every partner route is scoped to it.
    client_app_id: str = ""
    client_app_name: str = ""


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
    try:
        slot = key_limits.acquire(row.id)
    except key_limits.KeyLimitExceeded as exc:
        route = request.scope.get("route")
        key_limits.log_refusal(row.id, exc, getattr(route, "name", None) or request.url.path)
        raise ApiError(429, "rate_limited", "Too many requests for this key.").with_retry_after(
            exc.retry_after
        )
    try:
        # Read fallback before `touch`, so what it resolves commits in the
        # same write: NULL parents in the tenant (rows an older running
        # version wrote during a deploy) are resolved and persisted.
        apps = ClientAppService(db)
        apps.heal_tenant(row.tenant_id)
        client_app = apps.for_partner_key(row)
        partner = PartnerTenant(
            tenant_id=row.tenant_id,
            key_id=row.id,
            key_name=row.name,
            client_app_id=client_app.id,
            client_app_name=client_app.name,
        )
        client_app_active = client_app.status == STATUS_ACTIVE
        service.touch(row)
        if not partner_tenant_enabled(db, row.tenant_id):
            raise ApiError(
                403, "service_not_enabled", "This service is not enabled for the tenant."
            )
        # Partner routes only: workspace keys, webhooks, the dashboard and the
        # public gateway never check a client app's status.
        if not client_app_active:
            raise ApiError(403, "client_app_disabled", "This client app is disabled.")
        release_read_transactions()
        yield partner
    finally:
        key_limits.release(slot)
