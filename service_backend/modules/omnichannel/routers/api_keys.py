"""Workspace API-key management (internal, session-authed).

Mint / list / revoke the public-gateway keys for a workspace. Gated by the
module `api_keys.read` / `api_keys.manage` permissions (and the loader's
`require_module` gate). The full plaintext key is returned ONCE at mint.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, get_current_user, require_permission
from app.models.user import User

from ..models import WorkspaceApiKey
from ..schemas import (
    ApiKeyCreateRequest,
    ApiKeyItem,
    ApiKeyListResponse,
    ApiKeyMintResponse,
)
from ..services.api_key_service import KEY_SCHEME, ApiKeyService

router = APIRouter()


def _to_item(row: WorkspaceApiKey) -> ApiKeyItem:
    return ApiKeyItem(
        id=row.id,
        workspaceId=row.workspace_id,
        name=row.name,
        keyPrefix=row.key_prefix,
        maskedKey=f"{KEY_SCHEME}{row.key_prefix}••••",
        status="REVOKED" if row.revoked_at is not None else "ACTIVE",
        lastUsedAt=row.last_used_at,
        revokedAt=row.revoked_at,
        createdAt=row.created_at,
    )


@router.get("/{workspace_id}/api-keys", response_model=ApiKeyListResponse)
def list_api_keys(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("api_keys.read")),
) -> ApiKeyListResponse:
    rows = ApiKeyService(db).list_for_workspace(user.tenant_id, workspace_id)
    return ApiKeyListResponse(data=[_to_item(r) for r in rows])


@router.post("/{workspace_id}/api-keys", response_model=ApiKeyMintResponse, status_code=201)
def mint_api_key(
    workspace_id: str,
    payload: ApiKeyCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("api_keys.manage")),
    actor_id: str = Depends(get_actor_user_id),
) -> ApiKeyMintResponse:
    try:
        row, full_key = ApiKeyService(db).mint(
            user.tenant_id, workspace_id, payload.name, actor_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApiKeyMintResponse(key=_to_item(row), fullKey=full_key)


@router.post("/{workspace_id}/api-keys/{key_id}/revoke", response_model=ApiKeyItem)
def revoke_api_key(
    workspace_id: str,
    key_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("api_keys.manage")),
) -> ApiKeyItem:
    try:
        row = ApiKeyService(db).revoke(key_id, user.tenant_id, workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_item(row)
