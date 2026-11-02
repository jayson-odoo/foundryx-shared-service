"""API-key authentication for the public gateway (`/api/v1/omnichannel/*`).

`get_api_workspace` is the public-route sibling of core `get_current_user`: it
resolves an `Authorization: Bearer fxw_live_…` key to (tenant, workspace,
service) - never trusting the request body/query for tenancy. Uniform 401 on any
miss (no enumeration); 403 `service_not_enabled` if the key's service is not
active for its tenant (the workspace→service binding, AC-01-15).
"""
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db, release_read_transactions
from app.models.tenant import Tenant
from app.repositories.module_repository import ModuleRepository

from .repositories.workspace_repository import WorkspaceRepository
from .services.api_key_service import ApiKeyService

MODULE_NAME = "omnichannel"
SERVICE = "omnichannel"


@dataclass
class ApiWorkspace:
    tenant_id: str
    workspace_id: str
    key_id: str
    service: str = SERVICE


def _parse_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def gateway_key_enabled(db: Session, tenant_id: str, workspace_id: str) -> bool:
    """True while a resolved gateway key may be used: its tenant may sign in
    (not suspended or archived), the module is active for the tenant, and the
    key's workspace exists and is not trashed. Every lookup is tenant-scoped.
    One predicate shared by every API-key entry point of this module, and by
    webhook delivery (fan-out and dispatch)."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or not tenant.signin_allowed:
        return False
    if not ModuleRepository(db).is_active(tenant_id, MODULE_NAME):
        return False
    workspace = WorkspaceRepository(db).get_by_id(workspace_id, tenant_id)
    return workspace is not None and not workspace.is_trashed


def get_api_workspace(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> ApiWorkspace:
    token = _parse_bearer(authorization)
    if token is None:
        raise ApiError(401, "invalid_api_key", "Missing or malformed API key.")
    row = ApiKeyService(db).resolve(token)
    if row is None:
        raise ApiError(401, "invalid_api_key", "Invalid API key.")
    workspace = ApiWorkspace(
        tenant_id=row.tenant_id, workspace_id=row.workspace_id, key_id=row.id
    )
    # Stash for the activity-log middleware (sprint-4/12) - set as soon as the
    # key resolves so even a 403 service_not_enabled below is attributable.
    request.state.api_workspace = workspace
    # Service binding (AC-01-15): the tenant may sign in, the service is ACTIVE
    # for it and the key's workspace is not trashed.
    if not gateway_key_enabled(db, row.tenant_id, row.workspace_id):
        raise ApiError(
            403, "service_not_enabled", "This service is not enabled for the workspace."
        )
    # The key is fully checked and `workspace` holds plain strings: end the
    # read-only transaction so it is not held through the endpoint's slow work.
    release_read_transactions()
    return workspace
