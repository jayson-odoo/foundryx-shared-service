"""Plan 71 - AutoCount project registrations on the write gateway (``/api/v1/autocount``).

Same frame as the quotation / sales order write routes (``write_v1._frame``): ``X-API-Key`` with the
``write_back`` scope, ``companyCode`` resolution, ``Idempotency-Key`` (required on create),
``X-Request-ID`` and the acting-user headers, the flat error body, ``no-store``. The router parses
and shapes; ``ProjectRegistrationService`` decides.

- ``POST  /project-registrations``                    -> wrapper ``POST /NewProjectReg``
- ``PATCH /project-registrations/{projNo}``           -> wrapper ``PUT /EditProjectRegbyProjNo``
- ``GET   /project-registrations/{projNo}?companyCode=`` -> wrapper ``GET /ProjectRegbyProjNo``
- ``GET   /project-registrations?companyCode=&date=``    -> wrapper ``GET /ProjectRegbyDate``

The body speaks camelCase (``projectTitle``, ``typeofBuilding``); each name maps to AutoCount's by
upper-casing its first letter. The answer's ``registration`` is AutoCount's record as read back, in
AutoCount's own field names (as ``document`` on the document routes).
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
from ..write_back.project_registration import ProjectRegistrationService, RegResult
from .pull_v1 import WriteBody, _read_request_body_bytes, _safe_echo
from .write_v1 import _bad, _frame, _status_of

router = APIRouter()

PROJ_NO_MAX = 64
FIELD_MAX = 4000
FIELDS_MAX = 100
_FIELD_NAME = re.compile(r"[a-z][A-Za-z0-9]{0,63}")
_PROJ_NO = re.compile(r"[\x21-\x7e](?:[\x20-\x7e]*[\x21-\x7e])?")
_DAY = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")
_CREATE_KEYS = frozenset({"companyCode", "projNo", "registration"})
_EDIT_KEYS = frozenset({"companyCode", "registration"})


def _proj_no(value: Any, name: str = "projNo") -> str:
    """A ProjNo: 1..64 printable ASCII characters, no leading / trailing space. Absent or blank =
    ``FIELD_REQUIRED``; anything else malformed = ``INVALID_REQUEST``."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise _bad("FIELD_REQUIRED", f"FIELD_REQUIRED: {name}")
    if not isinstance(value, str) or len(value) > PROJ_NO_MAX or not _PROJ_NO.fullmatch(value):
        raise _bad("INVALID_REQUEST", f"{name} must be 1..{PROJ_NO_MAX} printable characters.")
    return value


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


def _registration(raw: WriteBody, proj_no: str) -> Dict[str, Any]:
    """``registration`` as AutoCount's record (``projectTitle`` -> ``ProjectTitle``). A ``projNo``
    inside it must equal the ProjNo being written (it is the key, never renamed)."""
    value = raw.get("registration")
    if value is None:
        raise _bad("FIELD_REQUIRED", "FIELD_REQUIRED: registration")
    if not isinstance(value, dict):
        raise _bad("INVALID_REQUEST", "registration must be an object.")
    if len(value) > FIELDS_MAX:
        raise _bad("INVALID_REQUEST", f"registration has more than {FIELDS_MAX} fields.")
    out: Dict[str, Any] = {}
    for name, item in value.items():
        if not isinstance(name, str) or not _FIELD_NAME.fullmatch(name):
            raise _bad("INVALID_REQUEST", f"registration.{_safe_echo(name)} is not a valid field name.")
        if name == "projNo":
            if item != proj_no:
                raise _bad("INVALID_REQUEST", "registration.projNo must equal the projNo being written.")
            continue
        out[name[:1].upper() + name[1:]] = _value(name, item)
    return out


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
        _only(raw, _CREATE_KEYS)
        proj_no = _proj_no(raw.get("projNo"))
        record = _registration(raw, proj_no)
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
        _only(raw, _EDIT_KEYS)
        proj_no = _proj_no(projNo)
        record = _registration(raw, proj_no)
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

