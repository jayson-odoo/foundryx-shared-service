"""Partner-key management (internal, session-authed, S6).

A tenant admin holding ``partner_keys.manage`` mints, lists and revokes the
tenant's ``fxp_live_`` partner keys and edits each key's return-origin
allow-list. Never self-serve by the partner. The full plaintext key is
returned ONCE at mint. Tenant always from the JWT.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from ..models import PartnerApiKey
from ..origins import InvalidOrigin
from ..schemas import (
    PartnerKeyCreateRequest,
    PartnerKeyItem,
    PartnerKeyListResponse,
    PartnerKeyMintResponse,
    PartnerKeyUpdateRequest,
)
from ..services.partner_key_service import KEY_SCHEME, PartnerKeyNotFound, PartnerKeyService

router = APIRouter()

PERMISSION = "partner_keys.manage"


def _to_item(row: PartnerApiKey) -> PartnerKeyItem:
    return PartnerKeyItem(
        id=row.id,
        name=row.name,
        keyPrefix=row.key_prefix,
        maskedKey=f"{KEY_SCHEME}{row.key_prefix}••••",
        status="REVOKED" if row.revoked_at is not None else "ACTIVE",
        allowedReturnOrigins=list(row.allowed_return_origins or []),
        lastUsedAt=row.last_used_at,
        revokedAt=row.revoked_at,
        createdAt=row.created_at,
    )


@router.get("", response_model=PartnerKeyListResponse)
def list_partner_keys(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PERMISSION)),
) -> PartnerKeyListResponse:
    rows = PartnerKeyService(db).list_for_tenant(user.tenant_id)
    return PartnerKeyListResponse(data=[_to_item(r) for r in rows])


@router.post("", response_model=PartnerKeyMintResponse, status_code=201)
def mint_partner_key(
    payload: PartnerKeyCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PERMISSION)),
    actor_id: str = Depends(get_actor_user_id),
) -> PartnerKeyMintResponse:
    try:
        row, full_key = PartnerKeyService(db).mint(
            user.tenant_id, payload.name, actor_id, payload.allowedReturnOrigins
        )
    except InvalidOrigin as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    return PartnerKeyMintResponse(key=_to_item(row), fullKey=full_key)


@router.patch("/{key_id}", response_model=PartnerKeyItem)
def update_partner_key(
    key_id: str,
    payload: PartnerKeyUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PERMISSION)),
) -> PartnerKeyItem:
    try:
        row = PartnerKeyService(db).set_return_origins(
            key_id, user.tenant_id, payload.allowedReturnOrigins
        )
    except InvalidOrigin as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except PartnerKeyNotFound as exc:
        raise HTTPException(status_code=404, detail="Partner key not found.") from exc
    return _to_item(row)


@router.post("/{key_id}/revoke", response_model=PartnerKeyItem)
def revoke_partner_key(
    key_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PERMISSION)),
) -> PartnerKeyItem:
    try:
        row = PartnerKeyService(db).revoke(key_id, user.tenant_id)
    except PartnerKeyNotFound as exc:
        raise HTTPException(status_code=404, detail="Partner key not found.") from exc
    return _to_item(row)
