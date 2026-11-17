"""Lead Capture staff API (session JWT, module-gated, permission-gated).
HTTP only; every call is tenant-scoped from the signed-in user."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_actor_user_id, require_permission
from app.models.user import User

from .. import schemas
from ..services import (
    backfill_service,
    connect_service,
    connect_session_service,
    staff_list_service,
    delivery_service,
    field_service,
    form_service,
    key_service,
    read_service,
    source_service,
)

router = APIRouter()


def _http(exc) -> HTTPException:
    retry_after = getattr(exc, "retry_after", None)
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
        headers={"Retry-After": str(int(retry_after))} if retry_after else None,
    )

_VIEW = require_permission("lead_capture.view")
_MANAGE = require_permission("lead_capture.manage")
_KEYS = require_permission("lead_capture.keys.manage")


@router.post("/sources/facebook", response_model=schemas.SourceItem, status_code=201)
def connect_facebook(
    body: schemas.ConnectFacebookRequest,
    user: User = Depends(_MANAGE),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> schemas.SourceItem:
    try:
        row = connect_service.connect_facebook(
            db,
            user.tenant_id,
            page_id=body.pageId,
            system_user_token=body.systemUserToken or "",
            forms_mode=body.formsMode,
            user_id=actor_id,
            actor=source_service.Actor.user(actor_id, user.id),
        )
    except connect_service.ConnectError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})
    return read_service.source_item(row)


@router.get("/sources", response_model=schemas.SourceList)
def list_sources(user: User = Depends(_VIEW), db: Session = Depends(get_db)) -> schemas.SourceList:
    rows = connect_service.list_sources(db, user.tenant_id)
    return schemas.SourceList(data=[read_service.source_item(r) for r in rows])


@router.get("/settings", response_model=schemas.SettingsItem)
def get_settings(user: User = Depends(_VIEW), db: Session = Depends(get_db)) -> schemas.SettingsItem:
    return read_service.settings_item(db, user.tenant_id)


@router.put("/settings", response_model=schemas.SettingsItem)
def put_settings(
    body: schemas.SettingsUpdate,
    user: User = Depends(_MANAGE),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> schemas.SettingsItem:
    connect_service.set_allow_shared_pages(db, user.tenant_id, body.allowSharedPages, actor_id)
    return read_service.settings_item(db, user.tenant_id)


@router.post("/keys", response_model=schemas.KeyCreated, status_code=201)
def create_key(
    body: schemas.KeyCreate,
    user: User = Depends(_KEYS),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> schemas.KeyCreated:
    try:
        origins = connect_session_service.clean_origins(body.allowedOrigins)
    except connect_session_service.SessionError as exc:
        raise _http(exc)
    row, full_key = key_service.issue(db, user.tenant_id, name=body.name, created_by=actor_id)
    if origins:
        row = connect_session_service.set_key_origins(db, user.tenant_id, row.id, origins)
    return schemas.KeyCreated(**read_service.key_item(row).model_dump(), key=full_key)


@router.put("/keys/{key_id}/origins", response_model=schemas.KeyItem)
def set_key_origins(
    key_id: str, body: schemas.KeyOriginsUpdate, user: User = Depends(_KEYS), db: Session = Depends(get_db)
) -> schemas.KeyItem:
    """Origins a connect session may post back to (AC-64-06)."""
    try:
        row = connect_session_service.set_key_origins(db, user.tenant_id, key_id, body.allowedOrigins)
    except connect_session_service.SessionError as exc:
        raise _http(exc)
    return read_service.key_item(row)


@router.get("/keys", response_model=schemas.KeyList)
def list_keys(user: User = Depends(_KEYS), db: Session = Depends(get_db)) -> schemas.KeyList:
    return schemas.KeyList(data=[read_service.key_item(r) for r in key_service.list_keys(db, user.tenant_id)])


@router.delete("/keys/{key_id}", status_code=204)
def revoke_key(key_id: str, user: User = Depends(_KEYS), db: Session = Depends(get_db)) -> Response:
    try:
        key_service.revoke(db, user.tenant_id, key_id)
    except key_service.KeyNotFound:
        raise HTTPException(status_code=404, detail="Key not found.")
    return Response(status_code=204)


@router.post("/deliveries/{delivery_id}/redeliver", response_model=schemas.DeliveryItem)
def redeliver(delivery_id: str, user: User = Depends(_MANAGE), db: Session = Depends(get_db)) -> schemas.DeliveryItem:
    try:
        row = delivery_service.redeliver(db, user.tenant_id, delivery_id)
    except delivery_service.DeliveryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return read_service.delivery_item(row)


@router.get("/fields", response_model=schemas.ConsumerFieldList)
def get_fields(user: User = Depends(_VIEW), db: Session = Depends(get_db)) -> schemas.ConsumerFieldList:
    return read_service.fields_item(db, user.tenant_id)


@router.put("/fields", response_model=schemas.ConsumerFieldList)
def put_fields(
    body: List[schemas.ConsumerField],
    user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> schemas.ConsumerFieldList:
    try:
        field_service.set_fields(db, user.tenant_id, [f.model_dump() for f in body])
    except field_service.FieldError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})
    return read_service.fields_item(db, user.tenant_id)


@router.put("/sources/{source_id}/field-map", response_model=schemas.SourceItem)
def put_field_map(
    source_id: str,
    body: schemas.FieldMapUpdate,
    user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> schemas.SourceItem:
    try:
        row = field_service.set_field_map(db, user.tenant_id, source_id, body.formId, body.map)
    except field_service.FieldError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})
    return read_service.source_item(row)


@router.get("/sources/{source_id}/forms/{form_id}/questions", response_model=schemas.FormQuestionList)
def form_questions(
    source_id: str, form_id: str, user: User = Depends(_VIEW), db: Session = Depends(get_db)
) -> schemas.FormQuestionList:
    try:
        return schemas.FormQuestionList(**form_service.form_questions(db, user.tenant_id, source_id, form_id))
    except form_service.FormError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


@router.post("/sources/{source_id}/test-lead", response_model=schemas.TestLeadAccepted, status_code=202)
def send_test_lead(
    source_id: str,
    body: schemas.TestLeadRequest,
    user: User = Depends(_MANAGE),
    db: Session = Depends(get_db),
) -> schemas.TestLeadAccepted:
    try:
        return schemas.TestLeadAccepted(**form_service.send_test_lead(db, user.tenant_id, source_id, body.formId))
    except form_service.FormError as exc:
        raise _http(exc)


# ── lane L-B: forms, backfill, history, disconnect ──────────────────────────

@router.get("/sources/{source_id}/forms", response_model=schemas.FormList)
def list_forms(source_id: str, user: User = Depends(_VIEW), db: Session = Depends(get_db)) -> schemas.FormList:
    try:
        return source_service.list_forms(db, user.tenant_id, source_id)
    except source_service.SourceError as exc:
        raise _http(exc)


@router.put("/sources/{source_id}/forms", response_model=schemas.SourceItem)
def put_forms(
    source_id: str,
    body: schemas.FormsUpdate,
    user: User = Depends(_MANAGE),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> schemas.SourceItem:
    try:
        row = source_service.set_forms(
            db, user.tenant_id, source_id, body.formsMode, body.formIds, source_service.Actor.user(actor_id, user.id)
        )
    except source_service.SourceError as exc:
        raise _http(exc)
    return read_service.source_item(row)


@router.post("/sources/{source_id}/backfill", response_model=schemas.BackfillAccepted, status_code=202)
def run_backfill(source_id: str, user: User = Depends(_MANAGE), db: Session = Depends(get_db)) -> schemas.BackfillAccepted:
    try:
        return schemas.BackfillAccepted(sourceId=backfill_service.request_backfill(db, user.tenant_id, source_id))
    except source_service.SourceError as exc:
        raise _http(exc)


@router.get("/sources/{source_id}/history", response_model=schemas.SourceEventList, response_model_by_alias=True)
def source_history(source_id: str, user: User = Depends(_VIEW), db: Session = Depends(get_db)) -> schemas.SourceEventList:
    try:
        return source_service.history(db, user.tenant_id, source_id)
    except source_service.SourceError as exc:
        raise _http(exc)


@router.delete("/sources/{source_id}", status_code=204)
def disconnect_source(
    source_id: str,
    user: User = Depends(_MANAGE),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> Response:
    try:
        source_service.disconnect(db, user.tenant_id, source_id, actor=source_service.Actor.user(actor_id, user.id))
    except source_service.SourceError as exc:
        raise _http(exc)
    return Response(status_code=204)



# ── lane L-C: connect sessions, Sources + Leads lists (AC-64-05/06/53) ──────

@router.post("/connect-sessions", response_model=schemas.ConnectSessionCreated, status_code=201)
def create_connect_session(
    body: schemas.ConnectSessionCreate,
    user: User = Depends(_MANAGE),
    actor_id: str = Depends(get_actor_user_id),
    db: Session = Depends(get_db),
) -> schemas.ConnectSessionCreated:
    """The staff door to the hosted wizard ("Connect a source", Reconnect)."""
    try:
        row, url = connect_session_service.create_session(
            db, user.tenant_id, return_origin=body.returnOrigin, user_id=actor_id, source_id=body.sourceId
        )
    except (connect_session_service.SessionError, source_service.SourceError) as exc:
        raise _http(exc)
    return schemas.ConnectSessionCreated(url=url, expiresAt=row.expires_at)


@router.get("/sources/list", response_model=schemas.StaffSourcePage)
def list_sources_page(
    search: Optional[str] = Query(default=None, max_length=200),
    status: Optional[List[str]] = Query(default=None),
    platform: Optional[List[str]] = Query(default=None),
    sort: Optional[str] = Query(default=None, max_length=32),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=0, ge=0),
    pageSize: int = Query(default=25, ge=1, le=staff_list_service.MAX_PAGE_SIZE),
    user: User = Depends(_VIEW),
    db: Session = Depends(get_db),
) -> schemas.StaffSourcePage:
    return staff_list_service.list_sources(
        db, user.tenant_id, search=search, statuses=status, platforms=platform,
        sort=sort, order=order, page=page, page_size=pageSize,
    )


@router.get("/leads", response_model=schemas.StaffLeadPage)
def list_leads(
    search: Optional[str] = Query(default=None, max_length=200),
    source: Optional[List[str]] = Query(default=None),
    platform: Optional[List[str]] = Query(default=None),
    isTest: Optional[bool] = Query(default=None),
    receivedFrom: Optional[str] = Query(default=None, max_length=40),
    receivedTo: Optional[str] = Query(default=None, max_length=40),
    sort: Optional[str] = Query(default=None, max_length=32),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=0, ge=0),
    pageSize: int = Query(default=25, ge=1, le=staff_list_service.MAX_PAGE_SIZE),
    user: User = Depends(_VIEW),
    db: Session = Depends(get_db),
) -> schemas.StaffLeadPage:
    try:
        return staff_list_service.list_leads(
            db, user.tenant_id, search=search, source_ids=source, platforms=platform, is_test=isTest,
            received_from=receivedFrom, received_to=receivedTo, sort=sort, order=order,
            page=page, page_size=pageSize,
        )
    except read_service.ReadError as exc:
        raise _http(exc)


@router.get("/leads/{lead_id}", response_model=schemas.StaffLeadDetail)
def lead_detail(lead_id: str, user: User = Depends(_VIEW), db: Session = Depends(get_db)) -> schemas.StaffLeadDetail:
    try:
        return staff_list_service.lead_detail(db, user.tenant_id, lead_id)
    except read_service.ReadError as exc:
        raise _http(exc)
