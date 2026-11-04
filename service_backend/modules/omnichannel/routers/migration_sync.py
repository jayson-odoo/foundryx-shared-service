"""Continuous respond.io sync routes - thin, HTTP + Pydantic only (plan 52).
Reads gated ``omnichannel_migration.read``, writes ``.manage`` (D14: no new
permission). A foreign tenant's sync id is a uniform 404."""
from typing import Callable, Optional, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from ..schemas import MigrationSyncCreate, MigrationSyncItem, MigrationSyncWebhook
from ..services.migration_sync_service import MigrationSyncService, SyncConflict, SyncNotFound

router = APIRouter()

T = TypeVar("T")


def _guard(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except SyncNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sync not found.")
    except SyncConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"reason": exc.reason})


@router.get("", response_model=Optional[MigrationSyncItem])
def get_workspace_sync(
    workspaceId: str = Query(...),
    current_user: User = Depends(require_permission("omnichannel_migration.read")),
    db: Session = Depends(get_db),
) -> Optional[MigrationSyncItem]:
    return MigrationSyncService(db).get_for_workspace(current_user.tenant_id, workspaceId)


@router.post("", response_model=MigrationSyncItem, status_code=status.HTTP_201_CREATED)
def create_sync(
    payload: MigrationSyncCreate,
    current_user: User = Depends(require_permission("omnichannel_migration.manage")),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> MigrationSyncItem:
    return _guard(lambda: MigrationSyncService(db).create(current_user.tenant_id, actor_id, payload.workspaceId))


@router.get("/{sync_id}", response_model=MigrationSyncItem)
def get_sync(
    sync_id: str,
    current_user: User = Depends(require_permission("omnichannel_migration.read")),
    db: Session = Depends(get_db),
) -> MigrationSyncItem:
    return _guard(lambda: MigrationSyncService(db).get(current_user.tenant_id, sync_id))


@router.post("/{sync_id}/run-now", response_model=MigrationSyncItem)
def run_now(
    sync_id: str,
    current_user: User = Depends(require_permission("omnichannel_migration.manage")),
    db: Session = Depends(get_db),
) -> MigrationSyncItem:
    return _guard(lambda: MigrationSyncService(db).run_now(current_user.tenant_id, sync_id))


@router.post("/{sync_id}/pause", response_model=MigrationSyncItem)
def pause(
    sync_id: str,
    current_user: User = Depends(require_permission("omnichannel_migration.manage")),
    db: Session = Depends(get_db),
) -> MigrationSyncItem:
    return _guard(lambda: MigrationSyncService(db).pause(current_user.tenant_id, sync_id))


@router.post("/{sync_id}/resume", response_model=MigrationSyncItem)
def resume(
    sync_id: str,
    current_user: User = Depends(require_permission("omnichannel_migration.manage")),
    db: Session = Depends(get_db),
) -> MigrationSyncItem:
    return _guard(lambda: MigrationSyncService(db).resume(current_user.tenant_id, sync_id))


@router.post("/{sync_id}/stop", response_model=MigrationSyncItem)
def stop(
    sync_id: str,
    current_user: User = Depends(require_permission("omnichannel_migration.manage")),
    db: Session = Depends(get_db),
) -> MigrationSyncItem:
    return _guard(lambda: MigrationSyncService(db).stop(current_user.tenant_id, sync_id))


@router.get("/{sync_id}/webhook", response_model=MigrationSyncWebhook)
def get_webhook(
    sync_id: str,
    current_user: User = Depends(require_permission("omnichannel_migration.manage")),
    db: Session = Depends(get_db),
) -> MigrationSyncWebhook:
    return _guard(lambda: MigrationSyncWebhook(url=MigrationSyncService(db).webhook_url(current_user.tenant_id, sync_id)))


@router.post("/{sync_id}/webhook/rotate", response_model=MigrationSyncWebhook)
def rotate_webhook(
    sync_id: str,
    current_user: User = Depends(require_permission("omnichannel_migration.manage")),
    db: Session = Depends(get_db),
) -> MigrationSyncWebhook:
    return _guard(
        lambda: MigrationSyncWebhook(url=MigrationSyncService(db).rotate_webhook(current_user.tenant_id, sync_id))
    )
