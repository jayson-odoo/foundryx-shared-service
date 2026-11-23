"""Partner API (``/api/v1/omnichannel/partner/*``, S6).

Partner-key-authenticated (NOT session/JWT, NOT the workspace key): every route
depends on ``get_partner_tenant``, which derives the tenant from the
``fxp_live_...`` Bearer key. Errors use the structured ``{error:{code,message}}``
envelope. Marked ``"public": true`` in the manifest like ``api_v1`` so the
loader skips the JWT gate; tenant and module state are re-checked inside the
dependency. Every query is scoped to the key's tenant and client app (the
key's own, or the tenant's default for a key with no parent); a disabled
client app gets ``403 client_app_disabled`` from the dependency.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db

from .api_keys import _to_item as api_key_item
from ..partner_auth import PartnerTenant, get_partner_tenant
from ..schemas import (
    ApiKeyItem,
    ApiKeyListResponse,
    ApiKeyMintResponse,
    PartnerConnectSessionCompleteResponse,
    PartnerConnectSessionCreateRequest,
    PartnerConnectSessionCreated,
    PartnerConnectSessionItem,
    PartnerMeResponse,
    PartnerWorkspaceKeyCreateRequest,
    PartnerWorkspaceItem,
    PartnerWorkspaceListResponse,
    PartnerWorkspacePutRequest,
    PublicChannelListResponse,
)
from ..services.api_key_service import ApiKeyService
from ..services.partner_connect_service import (
    ConnectNotConfigured,
    ConnectSessionNotAuthorized,
    ConnectSessionNotFound,
    InvalidReturnUrl,
    PartnerConnectService,
)
from ..services.partner_key_service import PartnerKeyService
from ..services.partner_workspace_service import (
    PartnerChannelNotFound,
    PartnerScope,
    PartnerWorkspaceNotFound,
    PartnerWorkspaceService,
)
from ..services.public_gateway_service import PublicGatewayService

router = APIRouter()


@router.get("/me", response_model=PartnerMeResponse)
def partner_me(
    partner: PartnerTenant = Depends(get_partner_tenant),
    db: Session = Depends(get_db),
) -> PartnerMeResponse:
    return PartnerMeResponse(
        tenantId=partner.tenant_id,
        tenantName=PartnerKeyService(db).tenant_name(partner.tenant_id),
        keyId=partner.key_id,
        keyName=partner.key_name,
        clientAppId=partner.client_app_id,
        clientAppName=partner.client_app_name,
    )


# ── Workspaces (S7): one per partner organisation, keyed by externalOrgId ────
EXTERNAL_ORG_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


def _not_found() -> ApiError:
    return ApiError(404, "workspace_not_found", "Workspace not found.")


def _scope(partner: PartnerTenant) -> PartnerScope:
    return PartnerScope(tenant_id=partner.tenant_id, client_app_id=partner.client_app_id)


def _require(db: Session, partner: PartnerTenant, workspace_id: str):
    try:
        return PartnerWorkspaceService(db).require(_scope(partner), workspace_id)
    except PartnerWorkspaceNotFound:
        raise _not_found()


@router.put("/workspaces/{external_org_id}", response_model=PartnerWorkspaceItem)
def put_workspace(
    payload: PartnerWorkspacePutRequest,
    external_org_id: str = Path(pattern=EXTERNAL_ORG_ID_PATTERN),
    partner: PartnerTenant = Depends(get_partner_tenant),
    db: Session = Depends(get_db),
) -> PartnerWorkspaceItem:
    service = PartnerWorkspaceService(db)
    ws = service.upsert(_scope(partner), external_org_id, payload.name)
    return service.item(ws)


@router.get("/workspaces", response_model=PartnerWorkspaceListResponse)
def list_workspaces(
    external_org_id: Optional[str] = Query(
        default=None, alias="externalOrgId", pattern=EXTERNAL_ORG_ID_PATTERN
    ),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=100, alias="pageSize"),
    partner: PartnerTenant = Depends(get_partner_tenant),
    db: Session = Depends(get_db),
) -> PartnerWorkspaceListResponse:
    service = PartnerWorkspaceService(db)
    rows, total = service.list(_scope(partner), external_org_id, page, page_size)
    return PartnerWorkspaceListResponse(
        data=service.items(rows, partner.tenant_id), total=total, page=page, pageSize=page_size
    )


@router.get("/workspaces/{workspace_id}", response_model=PartnerWorkspaceItem)
def get_workspace(
    workspace_id: str,
    partner: PartnerTenant = Depends(get_partner_tenant),
    db: Session = Depends(get_db),
) -> PartnerWorkspaceItem:
    ws = _require(db, partner, workspace_id)
    return PartnerWorkspaceService(db).item(ws)


@router.get("/workspaces/{workspace_id}/channels", response_model=PublicChannelListResponse)
def list_workspace_channels(
    workspace_id: str,
    partner: PartnerTenant = Depends(get_partner_tenant),
    db: Session = Depends(get_db),
) -> PublicChannelListResponse:
    ws = _require(db, partner, workspace_id)
    return PublicChannelListResponse(
        data=PublicGatewayService(db).list_channels(partner.tenant_id, ws.id)
    )


@router.post(
    "/workspaces/{workspace_id}/channels/{channel_id}/disconnect",
    response_model=PublicChannelListResponse,
)
def disconnect_workspace_channel(
    workspace_id: str,
    channel_id: str,
    partner: PartnerTenant = Depends(get_partner_tenant),
    db: Session = Depends(get_db),
) -> PublicChannelListResponse:
    """FSS-3: the dashboard's disconnect for one channel of the workspace;
    answers the workspace's remaining channels."""
    try:
        PartnerWorkspaceService(db).disconnect_channel(_scope(partner), workspace_id, channel_id)
    except PartnerWorkspaceNotFound:
        raise _not_found()
    except PartnerChannelNotFound:
        raise ApiError(404, "channel_not_found", "Channel not found.")
    return PublicChannelListResponse(
        data=PublicGatewayService(db).list_channels(partner.tenant_id, workspace_id)
    )


# ── Per-organisation workspace keys (S8) ─────────────────────────────────────
# An ordinary `fxw_live_` workspace key, minted and revoked by the existing
# `ApiKeyService`; it works on today's public API unchanged.
def _key_not_found() -> ApiError:
    return ApiError(404, "api_key_not_found", "API key not found.")


@router.get("/workspaces/{workspace_id}/api-keys", response_model=ApiKeyListResponse)
def list_workspace_keys(
    workspace_id: str,
    partner: PartnerTenant = Depends(get_partner_tenant),
    db: Session = Depends(get_db),
) -> ApiKeyListResponse:
    ws = _require(db, partner, workspace_id)
    service = ApiKeyService(db)
    rows = service.list_for_workspace(partner.tenant_id, ws.id)
    counts = service.active_endpoint_counts(partner.tenant_id, ws.id)
    return ApiKeyListResponse(data=[api_key_item(r, counts.get(r.id, 0)) for r in rows])


@router.post("/workspaces/{workspace_id}/api-keys", response_model=ApiKeyMintResponse, status_code=201)
def mint_workspace_key(
    workspace_id: str,
    payload: PartnerWorkspaceKeyCreateRequest,
    partner: PartnerTenant = Depends(get_partner_tenant),
    db: Session = Depends(get_db),
) -> ApiKeyMintResponse:
    ws = _require(db, partner, workspace_id)
    row, full_key = ApiKeyService(db).mint(
        partner.tenant_id, ws.id, payload.name, f"partner:{partner.key_id}"
    )
    return ApiKeyMintResponse(key=api_key_item(row), fullKey=full_key)


@router.post("/workspaces/{workspace_id}/api-keys/{key_id}/revoke", response_model=ApiKeyItem)
def revoke_workspace_key(
    workspace_id: str,
    key_id: str,
    partner: PartnerTenant = Depends(get_partner_tenant),
    db: Session = Depends(get_db),
) -> ApiKeyItem:
    ws = _require(db, partner, workspace_id)
    service = ApiKeyService(db)
    try:
        # Same behaviour as the dashboard revoke: the key's webhook endpoints pause.
        row = service.revoke(key_id, partner.tenant_id, ws.id, pause_endpoints=True)
    except ValueError:
        raise _key_not_found()
    counts = service.active_endpoint_counts(partner.tenant_id, ws.id)
    return api_key_item(row, counts.get(row.id, 0))


# ── Connect sessions (FSS-1): hosted WhatsApp connect for one workspace ──────
# Off until configured (503 connect_not_configured). Scoped to the key's tenant
# AND client app; any other session id answers one uniform 404.
def _not_configured() -> ApiError:
    return ApiError(503, "connect_not_configured", "Hosted connect is not configured.")


def _session_not_found() -> ApiError:
    return ApiError(404, "connect_session_not_found", "Connect session not found.")


@router.post(
    "/workspaces/{workspace_id}/connect-sessions",
    response_model=PartnerConnectSessionCreated,
    status_code=201,
)
def create_connect_session(
    workspace_id: str,
    payload: PartnerConnectSessionCreateRequest,
    partner: PartnerTenant = Depends(get_partner_tenant),
    db: Session = Depends(get_db),
) -> PartnerConnectSessionCreated:
    try:
        return PartnerConnectService(db).create(
            _scope(partner),
            partner.key_id,
            workspace_id,
            payload.channelType,
            payload.returnUrl,
            payload.clientState,
        )
    except ConnectNotConfigured:
        raise _not_configured()
    except PartnerWorkspaceNotFound:
        raise _not_found()
    except InvalidReturnUrl:
        raise ApiError(
            422,
            "invalid_return_url",
            "returnUrl must be an absolute URL whose origin is one of this key's allowed return origins.",
        )


@router.get("/connect-sessions/{session_id}", response_model=PartnerConnectSessionItem)
def get_connect_session(
    session_id: str,
    partner: PartnerTenant = Depends(get_partner_tenant),
    db: Session = Depends(get_db),
) -> PartnerConnectSessionItem:
    service = PartnerConnectService(db)
    try:
        return service.item(service.get(_scope(partner), session_id))
    except ConnectNotConfigured:
        raise _not_configured()
    except ConnectSessionNotFound:
        raise _session_not_found()


@router.post(
    "/connect-sessions/{session_id}/complete",
    response_model=PartnerConnectSessionCompleteResponse,
)
def complete_connect_session(
    session_id: str,
    partner: PartnerTenant = Depends(get_partner_tenant),
    db: Session = Depends(get_db),
) -> PartnerConnectSessionCompleteResponse:
    service = PartnerConnectService(db)
    try:
        return service.completion(service.complete(_scope(partner), session_id))
    except ConnectNotConfigured:
        raise _not_configured()
    except ConnectSessionNotFound:
        raise _session_not_found()
    except ConnectSessionNotAuthorized as exc:
        raise ApiError(
            409,
            "connect_session_not_authorized",
            f"The connect session is {exc.status}; it can be completed only when AUTHORIZED.",
        )


@router.post("/connect-sessions/{session_id}/cancel", response_model=PartnerConnectSessionItem)
def cancel_connect_session(
    session_id: str,
    partner: PartnerTenant = Depends(get_partner_tenant),
    db: Session = Depends(get_db),
) -> PartnerConnectSessionItem:
    service = PartnerConnectService(db)
    try:
        return service.item(service.cancel(_scope(partner), session_id))
    except ConnectNotConfigured:
        raise _not_configured()
    except ConnectSessionNotFound:
        raise _session_not_found()
