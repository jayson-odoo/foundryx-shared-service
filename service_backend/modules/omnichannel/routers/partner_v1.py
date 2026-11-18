"""Partner API (``/api/v1/omnichannel/partner/*``, S6).

Partner-key-authenticated (NOT session/JWT, NOT the workspace key): every route
depends on ``get_partner_tenant``, which derives the tenant from the
``fxp_live_...`` Bearer key. Errors use the structured ``{error:{code,message}}``
envelope. Marked ``"public": true`` in the manifest like ``api_v1`` so the
loader skips the JWT gate; tenant and module state are re-checked inside the
dependency. Every query is scoped to the key's tenant.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db

from ..partner_auth import PartnerTenant, get_partner_tenant
from ..schemas import PartnerMeResponse
from ..services.partner_key_service import PartnerKeyService

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
