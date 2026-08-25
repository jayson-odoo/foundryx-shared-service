"""Omnichannel workspace settings - per-workspace media caps (plan 12 AC-12-12/23).

``GET/PUT /omnichannel/settings?workspaceId=`` gated by ``channels.manage``.
``workspaceId`` omitted = the tenant-wide default row. Accepted mimes are fixed
(Meta's set) and returned read-only; only per-type size caps are editable and are
always clamped ≤ the Meta ceiling at enforcement.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import OmnichannelSettingsResponse, OmnichannelSettingsUpdate
from ..services.media_settings_service import MediaSettingsService

router = APIRouter()


def _response(svc: MediaSettingsService, tenant_id: str, workspace_id: Optional[str]) -> OmnichannelSettingsResponse:
    return OmnichannelSettingsResponse(
        workspaceId=workspace_id,
        overrides=svc.get_overrides(tenant_id, workspace_id),
        effective=svc.effective(tenant_id, workspace_id),
    )


@router.get("", response_model=OmnichannelSettingsResponse)
def get_settings(
    workspace_id: Optional[str] = Query(None, alias="workspaceId"),
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> OmnichannelSettingsResponse:
    svc = MediaSettingsService(db)
    return _response(svc, current_user.tenant_id, workspace_id)


@router.put("", response_model=OmnichannelSettingsResponse)
def update_settings(
    payload: OmnichannelSettingsUpdate,
    workspace_id: Optional[str] = Query(None, alias="workspaceId"),
    current_user: User = Depends(require_permission("channels.manage")),
    db: Session = Depends(get_db),
) -> OmnichannelSettingsResponse:
    svc = MediaSettingsService(db)
    # Only explicitly-sent fields are applied (omitted = keep; null = clear).
    overrides = {k: getattr(payload, k) for k in payload.model_fields_set}
    svc.set_overrides(current_user.tenant_id, workspace_id, overrides)
    return _response(svc, current_user.tenant_id, workspace_id)
