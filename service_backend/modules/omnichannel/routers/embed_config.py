"""Embed-access config router — plan 11H (tenant-level embed connection admin).

Gated (NOT public): every endpoint requires ``workspaces.manage`` (reused — no
new permission, so no grant sweep) AND the omnichannel module active for the
caller's tenant. HTTP + Pydantic only; the service owns all DB logic. The
``embedSecret`` is write-only — GET never returns it; rotate returns it once.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import (
    EmbedConfigResponse,
    EmbedOriginsUpdate,
    EmbedRotateSecretResponse,
)
from ..services.embed_config_service import (
    EmbedConfigService,
    EmbedNotEnabled,
    InvalidOrigin,
)

router = APIRouter()

_MANAGE = require_permission("workspaces.manage")


@router.get("", response_model=EmbedConfigResponse)
def get_embed_config(
    current_user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> EmbedConfigResponse:
    return EmbedConfigResponse(**EmbedConfigService(db).get_config(current_user.tenant_id))


@router.post("/enable", response_model=EmbedConfigResponse)
def enable_embed(
    current_user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> EmbedConfigResponse:
    return EmbedConfigResponse(**EmbedConfigService(db).enable(current_user.tenant_id))


@router.post("/rotate-secret", response_model=EmbedRotateSecretResponse)
def rotate_embed_secret(
    current_user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> EmbedRotateSecretResponse:
    try:
        result = EmbedConfigService(db).rotate_secret(current_user.tenant_id)
    except EmbedNotEnabled:
        raise HTTPException(status_code=409, detail="Enable embed access first.")
    return EmbedRotateSecretResponse(**result)


@router.put("/origins", response_model=EmbedConfigResponse)
def set_embed_origins(
    payload: EmbedOriginsUpdate,
    current_user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> EmbedConfigResponse:
    try:
        result = EmbedConfigService(db).set_origins(
            current_user.tenant_id, payload.allowedOrigins
        )
    except EmbedNotEnabled:
        raise HTTPException(status_code=409, detail="Enable embed access first.")
    except InvalidOrigin as exc:
        raise HTTPException(status_code=422, detail=exc.message)
    return EmbedConfigResponse(**result)
