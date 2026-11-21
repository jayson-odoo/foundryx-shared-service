"""Plan 71 - AutoCount project registrations on the write gateway (``/api/v1/autocount``).

Same frame as the quotation / sales order write routes (``write_v1._frame``): ``X-API-Key`` with the
``write_back`` scope, ``companyCode`` resolution, ``Idempotency-Key`` (required on create),
``X-Request-ID`` and the acting-user headers, the flat error body, ``no-store``. The router parses
and shapes; ``ProjectRegistrationService`` decides.

- ``POST  /project-registrations``                    -> wrapper ``POST /NewProjectReg``
- ``PATCH /project-registrations/{projNo}``           -> wrapper ``PUT /EditProjectRegbyProjNo``
- ``GET   /project-registrations/{projNo}?companyCode=`` -> wrapper ``GET /ProjectRegbyProjNo``
- ``GET   /project-registrations?companyCode=&date=``    -> wrapper ``GET /ProjectRegbyDate``

Body (CRM plan Part A): ``{companyCode, registration: {projNo, projectTitle, distributorName, salesAgent,
customerName, date, typeOfBuilding, state, mukim, developer, architect, mainContractor, status}}``, the
whole record every time; each name maps to AutoCount's through ``project_registration.FIELDS`` (an
allowlist: any other name is ``422 INVALID_REQUEST``). The answer's ``registration`` is AutoCount's
record as read back, in AutoCount's own field names (as ``document`` on the document routes).
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db

from ..models import AcCompany, AcPullApiKey
from ..write_back.deps import get_project_registration_service
from ..write_back.project_registration import DATE_FIELDS, FIELDS, ProjectRegistrationService, RegResult
from .pull_v1 import WriteBody, _read_request_body_bytes, _safe_echo
from .write_v1 import _bad, _frame, _status_of

router = APIRouter()

PROJ_NO_MAX = 64
FIELD_MAX = 4000
_PROJ_NO = re.compile(r"[\x21-\x7e](?:[\x20-\x7e]*[\x21-\x7e])?")
_DAY = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")
_BODY_KEYS = frozenset({"companyCode", "registration"})
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _proj_no(value: Any, name: str = "projNo") -> str:
    """A ProjNo: 1..64 printable ASCII characters, no leading / trailing space. Absent or blank =
    ``FIELD_REQUIRED``; anything else malformed = ``INVALID_REQUEST``."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise _bad("FIELD_REQUIRED", f"FIELD_REQUIRED: {name}")
    if not isinstance(value, str) or len(value) > PROJ_NO_MAX or not _PROJ_NO.fullmatch(value):
        raise _bad("INVALID_REQUEST", f"{name} must be 1..{PROJ_NO_MAX} printable characters.")
    return value


def _date_value(name: str, value: Any) -> Any:
    """``YYYY-MM-DD`` (or AutoCount's own ``YYYY-MM-DDT00:00:00``) as AutoCount's form; blank / null
    passes as sent."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return value
    text = value[:10] if isinstance(value, str) else ""
    if not _DATE.fullmatch(text) or (len(value) > 10 and value[10] != "T"):
        raise _bad("INVALID_REQUEST", f"registration.{name} must be a date (YYYY-MM-DD).")
    try:
        day = date.fromisoformat(text)
    except ValueError:
        raise _bad("INVALID_REQUEST", f"registration.{name} must be a date (YYYY-MM-DD).") from None
    return f"{day.isoformat()}T00:00:00"


def _value(name: str, value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _bad("INVALID_REQUEST", f"registration.{name} must be a finite number.")
        return value
    if isinstance(value, str):
        if len(value) > FIELD_MAX:
            raise _bad("INVALID_REQUEST", f"registration.{name} is longer than {FIELD_MAX} characters.")
        return value
    raise _bad("INVALID_REQUEST", f"registration.{name} must be text, a number, true / false or null.")


def _registration(raw: WriteBody, proj_no: Optional[str] = None) -> "tuple[str, Dict[str, Any]]":
    """``(projNo, AutoCount's record)`` from ``registration``. On a create ``proj_no`` is None and
    ``registration.projNo`` is required; on an edit it is the path's and a ``registration.projNo``
    must equal it (the key is never renamed)."""
    value = raw.get("registration")
    if value is None:
        raise _bad("FIELD_REQUIRED", "FIELD_REQUIRED: registration")
    if not isinstance(value, dict):
        raise _bad("INVALID_REQUEST", "registration must be an object.")
    out: Dict[str, Any] = {}
    for name, item in value.items():
        vendor = FIELDS.get(name) if isinstance(name, str) else None
        if vendor is None:
            raise _bad("INVALID_REQUEST", f"registration.{_safe_echo(name)} is not a known field.")
        if name == "projNo":
            continue
        out[vendor] = _date_value(name, item) if vendor in DATE_FIELDS else _value(name, item)
    if proj_no is None:
        proj_no = _proj_no(value.get("projNo"))
    elif "projNo" in value and value.get("projNo") != proj_no:
        raise _bad("INVALID_REQUEST", "registration.projNo must equal the projNo being written.")
    return proj_no, out


def _only(raw: WriteBody, allowed: frozenset) -> None:
    for name in raw:
        if name not in allowed:
            raise _bad("INVALID_REQUEST", f"{_safe_echo(name)} is not a known field.")


def _day(request: Request) -> date:
    text = request.query_params.get("date") or ""
    match = _DAY.fullmatch(text)
    if not match:
        raise _bad("INVALID_REQUEST", "date must be a date (YYYY-MM-DD).")
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        raise _bad("INVALID_REQUEST", "date must be a date (YYYY-MM-DD).") from None


def _respond(result: RegResult) -> tuple:
    return _status_of(result.outcome, result.error_code), result.answer()


@router.post("/project-registrations")
def create_project_registration(
    request: Request, db: Session = Depends(get_db),
    raw_body: bytes = Depends(_read_request_body_bytes),
    svc: ProjectRegistrationService = Depends(get_project_registration_service),
) -> JSONResponse:
    def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
        _only(raw, _BODY_KEYS)
        proj_no, record = _registration(raw)
        return _respond(svc.create(
            tenant_id=key.tenant_id, company_id=company.id, key_id=key.id, idempotency_key=idem or "",
            proj_no=proj_no, record=record, params=raw,
        ))

    return _frame(request, db, raw_body, "write_projreg_create", run, key_required=True, services=(svc,))


@router.patch("/project-registrations/{projNo}")
def edit_project_registration(
    projNo: str, request: Request, db: Session = Depends(get_db),
    raw_body: bytes = Depends(_read_request_body_bytes),
    svc: ProjectRegistrationService = Depends(get_project_registration_service),
) -> JSONResponse:
    def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
        _only(raw, _BODY_KEYS)
        proj_no, record = _registration(raw, _proj_no(projNo))
        return _respond(svc.edit(
            tenant_id=key.tenant_id, company_id=company.id, key_id=key.id, idempotency_key=idem,
            proj_no=proj_no, record=record, params={"projNo": proj_no, **raw},
        ))

    return _frame(request, db, raw_body, "write_projreg_edit", run, services=(svc,))


@router.get("/project-registrations/{projNo}")
def read_project_registration(
    projNo: str, request: Request, db: Session = Depends(get_db),
    svc: ProjectRegistrationService = Depends(get_project_registration_service),
) -> JSONResponse:
    def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
        proj_no = _proj_no(projNo)
        return _respond(svc.read(tenant_id=key.tenant_id, company_id=company.id, key_id=key.id, proj_no=proj_no))

    return _frame(request, db, b"", "write_projreg_read", run, with_body=False, services=(svc,))


@router.get("/project-registrations")
def list_project_registrations_of_day(
    request: Request, db: Session = Depends(get_db),
    svc: ProjectRegistrationService = Depends(get_project_registration_service),
) -> JSONResponse:
    def run(raw: WriteBody, key: AcPullApiKey, company: AcCompany, idem: Optional[str]):
        day = _day(request)
        return _respond(svc.read_day(tenant_id=key.tenant_id, company_id=company.id, key_id=key.id, day=day))

    return _frame(request, db, b"", "write_projreg_by_date", run, with_body=False, services=(svc,))

