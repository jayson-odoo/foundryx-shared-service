"""Dashboards gateway ``/api/v1/dashboards`` (contract section 3).

``X-API-Key: fxd_live_...`` (``gateway_auth``); errors are the contract's flat
``{"error", "message", ...}`` body, rendered by ``DashRoute``. HTTP only: the work is in
``services/store_service.py`` and ``services/builder_service.py``. A wire change here is a change
to ``documentation/plans/ai-builder/SS-dashboards-contract.md`` in the same commit (both repos).
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db

from .. import schemas
from ..gateway_auth import DashKey, DashRoute, get_dash_key
from ..services.builder_service import BuilderService
from ..services.store_service import DashboardStore

router = APIRouter(route_class=DashRoute)

_Actor = Query(min_length=1, max_length=64)


@router.post("/builder/turn", response_model=schemas.TurnResponse)
def builder_turn(body: schemas.TurnRequest, key: DashKey = Depends(get_dash_key), db: Session = Depends(get_db)):
    return JSONResponse(BuilderService(db, key).turn(body))


@router.post("/save", response_model=schemas.DashboardOut)
def save(body: schemas.SaveRequest, key: DashKey = Depends(get_dash_key), db: Session = Depends(get_db)):
    return JSONResponse(DashboardStore(db, key).save(body))


@router.get("", response_model=schemas.DashboardList)
def list_dashboards(
    actor_ref: str = _Actor,
    scope: Literal["all", "mine", "shared"] = "all",
    q: Optional[str] = Query(default=None, max_length=200),
    sort: Literal["name", "updated_at", "owner_ref"] = "updated_at",
    dir: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    key: DashKey = Depends(get_dash_key),
    db: Session = Depends(get_db),
):
    return JSONResponse(DashboardStore(db, key).list(actor_ref, scope, q, sort, dir, page, limit))


@router.get("/{dashboard_id}", response_model=schemas.DashboardOut)
def get_dashboard(dashboard_id: str, actor_ref: str = _Actor, key: DashKey = Depends(get_dash_key),
                  db: Session = Depends(get_db)):
    return JSONResponse(DashboardStore(db, key).get(actor_ref, dashboard_id))


@router.post("/{dashboard_id}/share", response_model=schemas.DashboardOut)
def share(dashboard_id: str, body: schemas.ShareRequest, key: DashKey = Depends(get_dash_key),
          db: Session = Depends(get_db)):
    return JSONResponse(DashboardStore(db, key).share(dashboard_id, body))


@router.post("/{dashboard_id}/delete", response_model=schemas.Deleted)
def delete(dashboard_id: str, body: schemas.DeleteRequest, key: DashKey = Depends(get_dash_key),
           db: Session = Depends(get_db)):
    return JSONResponse(DashboardStore(db, key).delete(dashboard_id, body.actor_ref))


@router.get("/{dashboard_id}/versions", response_model=schemas.VersionList)
def versions(dashboard_id: str, actor_ref: str = _Actor, page: int = Query(default=1, ge=1),
             limit: int = Query(default=50, ge=1, le=100), key: DashKey = Depends(get_dash_key),
             db: Session = Depends(get_db)):
    return JSONResponse(DashboardStore(db, key).versions(actor_ref, dashboard_id, page, limit))
