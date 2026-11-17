"""Partner API (``/api/v1/omnichannel/partner/*``, S6).

Partner-key-authenticated (NOT session/JWT, NOT the workspace key): every route
depends on ``get_partner_tenant``, which derives the tenant from the
``fxp_live_...`` Bearer key. Errors use the structured ``{error:{code,message}}``
envelope. Marked ``"public": true`` in the manifest like ``api_v1`` so the
loader skips the JWT gate; tenant and module state are re-checked inside the
dependency. Every query is scoped to the key's tenant.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db

from ..partner_auth import PartnerTenant, get_partner_tenant
from ..schemas import (
    PartnerMeResponse,
    PartnerWorkspaceItem,
    PartnerWorkspaceListResponse,
    PartnerWorkspacePutRequest,
    PublicChannelListResponse,
)
from ..services.partner_key_service import PartnerKeyService
from ..services.partner_workspace_service import (
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
    )


# ── Workspaces (S7): one per partner organisation, keyed by externalOrgId ────
EXTERNAL_ORG_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


def _not_found() -> ApiError:
    return ApiError(404, "workspace_not_found", "Workspace not found.")


def _require(db: Session, partner: PartnerTenant, workspace_id: str):
    try:
        return PartnerWorkspaceService(db).require(partner.tenant_id, workspace_id)
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
    ws = service.upsert(partner.tenant_id, external_org_id, payload.name)
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
    rows, total = service.list(partner.tenant_id, external_org_id, page, page_size)
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
