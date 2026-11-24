"""Client apps (internal, session-authed): list the caller's tenant's client
apps with their live workspaces, create a new one, rename one, and move a
workspace to another of the tenant's client apps. Same permission as the
partner-key routes. Tenant always from the JWT; every lookup is scoped to it,
so another tenant's client app or workspace reads as 404.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from ..models import ClientApp, Workspace
from ..schemas import (
    ClientAppCreateRequest,
    ClientAppItem,
    ClientAppListResponse,
    ClientAppMoveWorkspaceRequest,
    ClientAppUpdateRequest,
    ClientAppWorkspaceItem,
)
from ..services.client_app_service import (
    ClientAppInvalidName,
    ClientAppNameConflict,
    ClientAppNotFound,
    ClientAppService,
)
from ..services.workspace_service import WorkspaceExternalRefInUse, WorkspaceNotFound

router = APIRouter()

PERMISSION = "partner_keys.manage"


def _item(app: ClientApp, count: int, workspaces: List[Workspace]) -> ClientAppItem:
    return ClientAppItem(
        id=app.id,
        name=app.name,
        slug=app.slug,
        status=app.status,
        isDefault=bool(app.is_default),
        workspaceCount=count,
        workspaces=[
            ClientAppWorkspaceItem(id=ws.id, name=ws.name, isDefault=ws.is_default) for ws in workspaces
        ],
    )


@router.get("", response_model=ClientAppListResponse)
def list_client_apps(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PERMISSION)),
) -> ClientAppListResponse:
    rows = ClientAppService(db).list_with_workspaces(user.tenant_id)
    return ClientAppListResponse(data=[_item(app, count, workspaces) for app, count, workspaces in rows])


@router.post("", response_model=ClientAppItem, status_code=201)
def create_client_app(
    payload: ClientAppCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PERMISSION)),
    actor_id: str = Depends(get_actor_user_id),
) -> ClientAppItem:
    try:
        app = ClientAppService(db).create_named(user.tenant_id, payload.name, created_by=actor_id)
    except ClientAppInvalidName as exc:
        raise HTTPException(422, "Name is required.") from exc
    except ClientAppNameConflict as exc:
        raise HTTPException(409, "A client app with this name already exists.") from exc
    return _item(app, 0, [])


@router.patch("/{client_app_id}", response_model=ClientAppItem)
def rename_client_app(
    client_app_id: str,
    payload: ClientAppUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PERMISSION)),
) -> ClientAppItem:
    service = ClientAppService(db)
    try:
        service.rename(client_app_id, user.tenant_id, payload.name)
    except ClientAppNotFound as exc:
        raise HTTPException(404, "Client app not found.") from exc
    except ClientAppInvalidName as exc:
        raise HTTPException(422, "Name is required.") from exc
    except ClientAppNameConflict as exc:
        raise HTTPException(409, "A client app with this name already exists.") from exc
    app, count, workspaces = service.item_state(client_app_id, user.tenant_id)
    return _item(app, count, workspaces)


@router.post("/{client_app_id}/workspaces/move", response_model=ClientAppItem)
def move_workspace(
    client_app_id: str,
    payload: ClientAppMoveWorkspaceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PERMISSION)),
) -> ClientAppItem:
    service = ClientAppService(db)
    try:
        service.move_workspace(client_app_id, user.tenant_id, payload.workspaceId)
    except ClientAppNotFound as exc:
        raise HTTPException(404, "Client app not found.") from exc
    except WorkspaceNotFound as exc:
        raise HTTPException(404, "Workspace not found.") from exc
    except WorkspaceExternalRefInUse as exc:
        raise HTTPException(
            409, "A workspace with this external reference already exists in the target client app."
        ) from exc
    app, count, workspaces = service.item_state(client_app_id, user.tenant_id)
    return _item(app, count, workspaces)
