"""Hosted connect wizard API ``/public/lead-capture`` (plan 64 L-C,
AC-64-06/07/08/12-18/20-22).

Mounted ``"public": true`` (no staff JWT): ``POST /connect/redeem`` takes the
URL secret; every ``/wizard/*`` route takes ``Authorization: Bearer`` with the
scoped ``lead_capture_embed`` token it returned, which reaches this session's
tenant and this session's source only. A staff token or another Service's
scoped token is refused here, and this token is refused on every staff and
gateway route (``assert_staff_token`` refuses any typed token).

Each step calls the SAME service function the gateway calls, so a product's
own wizard (the documented gateway API) and this hosted one never drift.
Errors use core's ``{"error": {"code", "message"}}`` envelope.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.api_errors import ApiError
from app.database import get_db
from app.services.throttle import Throttled, ThrottleService, client_ip

from .. import schemas
from ..services import (
    connect_service,
    connect_session_service as sessions,
    field_service,
    form_service,
    google_signin_service,
    google_source_service,
    read_service,
    source_service,
)
from ..services.connect_session_service import WizardPrincipal

router = APIRouter()


def _api(exc) -> ApiError:
    err = ApiError(exc.status_code, exc.code, exc.message)
    retry_after = getattr(exc, "retry_after", None)
    return err.with_retry_after(retry_after) if retry_after else err


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def get_wizard(
    authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)
) -> WizardPrincipal:
    try:
        return sessions.resolve_wizard(db, _bearer(authorization))
    except sessions.SessionError as exc:
        raise _api(exc)


def _source(db: Session, principal: WizardPrincipal, source_id: str):
    try:
        return principal.require_source(db, source_id)
    except sessions.SessionError as exc:
        raise _api(exc)


@router.post("/in/{source_key}")
async def google_inbound(source_key: str, request: Request, db: Session = Depends(get_db)) -> dict:
    """Google Ads lead form webhook (card 68a R2). No auth header: the path's
    source key picks the source and the body's ``google_key`` proves it."""
    raw = bytearray()
    async for chunk in request.stream():  # capped read: an oversize body is never buffered
        raw += chunk
        if len(raw) > google_source_service.MAX_BODY_BYTES:
            break
    try:
        google_source_service.receive(db, source_key, bytes(raw), ip=client_ip(request))
    except google_source_service.ReceiveError as exc:
        raise _api(exc)
    return {}


@router.post("/connect/redeem", response_model=schemas.WizardSession)
def redeem(body: schemas.ConnectSessionRedeem, request: Request, db: Session = Depends(get_db)) -> schemas.WizardSession:
    """Open the hosted URL once (AC-64-06). A failed open counts against the
    caller's IP (same bucket as failed gateway keys)."""
    ip = client_ip(request)
    throttle = ThrottleService(db)
    try:
        throttle.enforce_lead_gateway(ip=ip)
    except Throttled as exc:
        raise ApiError(429, "rate_limited", "Too many attempts. Try again shortly.").with_retry_after(
            exc.retry_after_seconds
        )
    try:
        return schemas.WizardSession(**sessions.redeem(db, body.token))
    except sessions.SessionError as exc:
        throttle.record_lead_gateway_failure(ip=ip)
        raise _api(exc)


@router.get("/wizard/context", response_model=schemas.WizardContext)
def context(principal: WizardPrincipal = Depends(get_wizard), db: Session = Depends(get_db)) -> schemas.WizardContext:
    source = None
    if principal.session.source_id:
        source = read_service.source_item(_source(db, principal, principal.session.source_id))
    return schemas.WizardContext(
        branding=schemas.WizardBranding(**sessions.wizard_branding(db, principal.tenant_id)),
        channels=[schemas.Channel(**c) for c in sessions.channels()],
        login=schemas.LoginConfig(**sessions.login_config()),
        googleLogin=schemas.GoogleLoginConfig(**google_signin_service.login_config()),
        returnOrigin=principal.session.return_origin,
        source=source,
    )


@router.post("/wizard/facebook/login", response_model=schemas.FacebookPageList)
def facebook_login(
    body: schemas.FacebookLoginRequest,
    principal: WizardPrincipal = Depends(get_wizard),
    db: Session = Depends(get_db),
) -> schemas.FacebookPageList:
    try:
        pages = sessions.wizard_login(db, principal, body.code, body.redirectUri)
    except sessions.SessionError as exc:
        raise _api(exc)
    return schemas.FacebookPageList(data=[schemas.FacebookPage(**p) for p in pages])


@router.post("/wizard/google/source", response_model=schemas.GuidedSourceCreated, status_code=201)
def google_source(principal: WizardPrincipal = Depends(get_wizard), db: Session = Depends(get_db)) -> schemas.GuidedSourceCreated:
    try:
        row, url, key = sessions.wizard_google_source(db, principal)
    except sessions.SessionError as exc:
        raise _api(exc)
    return schemas.GuidedSourceCreated(source=read_service.source_item(row), url=url, key=key)


@router.post("/wizard/google/login", response_model=schemas.GoogleAccountList)
def google_login(
    body: schemas.GoogleLoginRequest,
    principal: WizardPrincipal = Depends(get_wizard),
    db: Session = Depends(get_db),
) -> schemas.GoogleAccountList:
    try:
        rows = google_signin_service.wizard_login(db, principal, body.code, body.redirectUri)
    except sessions.SessionError as exc:
        raise _api(exc)
    return schemas.GoogleAccountList(data=[schemas.GoogleAccount(**a) for a in rows])


@router.get("/wizard/google/accounts", response_model=schemas.GoogleAccountList)
def google_accounts(principal: WizardPrincipal = Depends(get_wizard)) -> schemas.GoogleAccountList:
    try:
        rows = google_signin_service.accounts(principal)
    except sessions.SessionError as exc:
        raise _api(exc)
    return schemas.GoogleAccountList(data=[schemas.GoogleAccount(**a) for a in rows])


@router.get("/wizard/google/accounts/{account_id}/forms", response_model=schemas.GoogleLeadFormList)
def google_forms(account_id: str, principal: WizardPrincipal = Depends(get_wizard)) -> schemas.GoogleLeadFormList:
    try:
        rows = google_signin_service.forms(principal, account_id)
    except sessions.SessionError as exc:
        raise _api(exc)
    return schemas.GoogleLeadFormList(data=[schemas.GoogleLeadForm(**f) for f in rows])


@router.post("/wizard/google/connect", response_model=schemas.GoogleConnectResult)
def google_connect(
    body: schemas.GoogleConnectRequest,
    principal: WizardPrincipal = Depends(get_wizard),
    db: Session = Depends(get_db),
) -> schemas.GoogleConnectResult:
    try:
        row, results = google_signin_service.connect(db, principal, body.accountId, body.formIds)
    except sessions.SessionError as exc:
        raise _api(exc)
    except source_service.SourceError as exc:
        raise _api(exc)
    return schemas.GoogleConnectResult(
        source=read_service.source_item(row), forms=[schemas.GoogleFormResult(**r) for r in results]
    )


@router.get("/wizard/facebook/pages", response_model=schemas.FacebookPageList)
def facebook_pages(principal: WizardPrincipal = Depends(get_wizard)) -> schemas.FacebookPageList:
    try:
        pages = sessions.wizard_pages(principal)
    except sessions.SessionError as exc:
        raise _api(exc)
    return schemas.FacebookPageList(data=[schemas.FacebookPage(**p) for p in pages])


@router.post("/wizard/facebook/connect", response_model=schemas.SourceItem)
def facebook_connect(
    body: schemas.WizardConnect,
    principal: WizardPrincipal = Depends(get_wizard),
    db: Session = Depends(get_db),
) -> schemas.SourceItem:
    try:
        row = sessions.wizard_connect(db, principal, body.pageId)
    except sessions.SessionError as exc:
        raise _api(exc)
    except connect_service.ConnectError as exc:
        raise _api(exc)
    except source_service.SourceError as exc:
        raise _api(exc)
    return read_service.source_item(row)


@router.get("/wizard/sources/{source_id}", response_model=schemas.SourceItem)
def get_source(
    source_id: str, principal: WizardPrincipal = Depends(get_wizard), db: Session = Depends(get_db)
) -> schemas.SourceItem:
    return read_service.source_item(_source(db, principal, source_id))


@router.get("/wizard/sources/{source_id}/forms", response_model=schemas.FormList)
def list_forms(
    source_id: str, principal: WizardPrincipal = Depends(get_wizard), db: Session = Depends(get_db)
) -> schemas.FormList:
    _source(db, principal, source_id)
    try:
        return source_service.list_forms(db, principal.tenant_id, source_id)
    except source_service.SourceError as exc:
        raise _api(exc)


@router.put("/wizard/sources/{source_id}/forms", response_model=schemas.SourceItem)
def put_forms(
    source_id: str,
    body: schemas.FormsUpdate,
    principal: WizardPrincipal = Depends(get_wizard),
    db: Session = Depends(get_db),
) -> schemas.SourceItem:
    _source(db, principal, source_id)
    try:
        row = source_service.set_forms(
            db, principal.tenant_id, source_id, body.formsMode, body.formIds, principal.actor
        )
    except source_service.SourceError as exc:
        raise _api(exc)
    return read_service.source_item(row)


@router.get("/wizard/fields", response_model=schemas.ConsumerFieldList)
def get_fields(principal: WizardPrincipal = Depends(get_wizard), db: Session = Depends(get_db)) -> schemas.ConsumerFieldList:
    return read_service.fields_item(db, principal.tenant_id)


@router.get("/wizard/sources/{source_id}/forms/{form_id}/questions", response_model=schemas.FormQuestionList)
def form_questions(
    source_id: str,
    form_id: str,
    principal: WizardPrincipal = Depends(get_wizard),
    db: Session = Depends(get_db),
) -> schemas.FormQuestionList:
    _source(db, principal, source_id)
    try:
        return schemas.FormQuestionList(**form_service.form_questions(db, principal.tenant_id, source_id, form_id))
    except form_service.FormError as exc:
        raise _api(exc)


@router.put("/wizard/sources/{source_id}/field-map", response_model=schemas.SourceItem)
def put_field_map(
    source_id: str,
    body: schemas.FieldMapUpdate,
    principal: WizardPrincipal = Depends(get_wizard),
    db: Session = Depends(get_db),
) -> schemas.SourceItem:
    _source(db, principal, source_id)
    try:
        row = field_service.set_field_map(db, principal.tenant_id, source_id, body.formId, body.map)
    except field_service.FieldError as exc:
        raise _api(exc)
    return read_service.source_item(row)


@router.get("/wizard/sources/{source_id}/test-lead", response_model=schemas.WizardTestLead)
def last_test_lead(
    source_id: str, principal: WizardPrincipal = Depends(get_wizard), db: Session = Depends(get_db)
) -> schemas.WizardTestLead:
    try:
        return schemas.WizardTestLead(**sessions.last_test_lead(db, principal, source_id))
    except sessions.SessionError as exc:
        raise _api(exc)


@router.post("/wizard/sources/{source_id}/test-lead", response_model=schemas.TestLeadAccepted, status_code=202)
def send_test_lead(
    source_id: str,
    body: schemas.TestLeadRequest,
    principal: WizardPrincipal = Depends(get_wizard),
    db: Session = Depends(get_db),
) -> schemas.TestLeadAccepted:
    _source(db, principal, source_id)
    try:
        return schemas.TestLeadAccepted(**form_service.send_test_lead(db, principal.tenant_id, source_id, body.formId))
    except form_service.FormError as exc:
        raise _api(exc)


@router.post("/wizard/finish", response_model=schemas.WizardDone)
def finish(principal: WizardPrincipal = Depends(get_wizard), db: Session = Depends(get_db)) -> schemas.WizardDone:
    try:
        done = sessions.finish(db, principal)
    except sessions.SessionError as exc:
        raise _api(exc)
    return schemas.WizardDone(**{**done, "source": read_service.source_item(done["source"])})

