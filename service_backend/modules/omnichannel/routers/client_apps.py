"""Client apps (internal, session-authed): a READ-ONLY list of the caller's
tenant's client apps, so an admin can see the ids to pass as ``clientAppId``
when minting a partner key. Same permission as the partner-key routes. No
create, rename or move here. Tenant always from the JWT.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User

from ..schemas import ClientAppItem, ClientAppListResponse
from ..services.client_app_service import ClientAppService

router = APIRouter()

PERMISSION = "partner_keys.manage"


@router.get("", response_model=ClientAppListResponse)
def list_client_apps(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PERMISSION)),
) -> ClientAppListResponse:
    rows = ClientAppService(db).list_with_counts(user.tenant_id)
    return ClientAppListResponse(
        data=[
            ClientAppItem(
                id=app.id,
                name=app.name,
                slug=app.slug,
                status=app.status,
                isDefault=bool(app.is_default),
                workspaceCount=count,
            )
            for app, count in rows
        ]
    )
