"""AutoCount project registration (plan 71, lane AUTOCOUNT-PROJREG-SPO-SS).

The CRM numbers a project (ProjNo ``PPF`` + yy + mm + 4 digits) and registers it in AutoCount through
four wrapper doors: ``POST /NewProjectReg``, ``PUT /EditProjectRegbyProjNo`` (the whole record, ProjNo
in the body), ``GET /ProjectRegbyProjNo?ProjNo=`` and ``GET /ProjectRegbyDate?Date=yyyymmdd``.

Same frame as the quotation / sales order writes (``WriteFrame``): the company's write connection
resolved WITH tenant_id, the db3 write guard and the test-company check before any request, every
request (reads too) through the logged client (``ac_api_call_log``, ``X-Request-ID`` and the acting
user), one ``ac_write_action`` row per write and one ``ac_write_operation`` row per idempotency key.
Behind ``settings.autocount_project_registration_enabled`` (OFF by default): off = ``VENDOR_UNSUPPORTED``
with no request at all.

Rules (owner, 11 Nov / 21 Nov):
- a create reads the ProjNo first; one AutoCount already holds is refused ``REGISTRATION_EXISTS`` with
  AutoCount's record (it is linked back by the caller, never written over);
- every create / edit is read back by ProjNo and compared with what was sent (trimmed,
  case-insensitive, newline-normalised, a date by its day: AutoCount upper-cases agent / state / mukim /
  building type); a real difference is a ``FIELD_CHANGED`` warning on ``done`` with AutoCount's value;
- an unclear create (timeout, connection drop, unreadable read-back) answers ``pending_verification``;
  a same-key resend looks the ProjNo up BEFORE any re-send: found = checked and ``done``, absent =
  sent again (found with other fields = ``REGISTRATION_EXISTS``, for a person to link). A refusal
  (AutoCount's own reason) releases the key; only a confirmed success locks it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from app.config import settings
from modules.autocount.http_source.client import USER_AGENT
from modules.autocount.models import AcCompany, AcWriteAction, AcWriteOperation
from modules.autocount.repositories import CompanyRepository
from modules.autocount.write_back import frame, guard
from modules.autocount.write_back.client import WriteTransportError
from modules.autocount.write_back.guard import WriteConnectionError
from modules.autocount.write_back.frame import (
    DOC_BUSY,
    INTERNAL_ERROR,
    OUTCOME_DONE,
    OUTCOME_PENDING,
    OUTCOME_REFUSED,
    OUTCOME_VENDOR_ERROR,
    VENDOR_UNSUPPORTED,
    WRITE_DISABLED,
    WriteActionResult,
    WriteFrame,
    _Stop,
)
from modules.autocount.write_back.primitives import is_business_refusal, vendor_message
from modules.autocount.write_back.reader import READ_FAILED, DocReadError
from modules.autocount.write_back.repository import OUTCOME_IN_FLIGHT, OperationRepository

logger = logging.getLogger(__name__)

KIND = "PROJREG"
WIRE_KIND = "project-registrations"
PRIMITIVES = ("create_doc", "edit_doc")

NEW_PATH = "/NewProjectReg"
EDIT_PATH = "/EditProjectRegbyProjNo"
BY_PROJ_NO_PATH = "/ProjectRegbyProjNo"
BY_DATE_PATH = "/ProjectRegbyDate"

REGISTRATION_EXISTS = "REGISTRATION_EXISTS"
REGISTRATION_NOT_FOUND = "REGISTRATION_NOT_FOUND"
REGISTRATION_AMBIGUOUS = "REGISTRATION_AMBIGUOUS"
# done, but AutoCount holds a different value for a field sent (``changedFields`` names them)
FIELD_CHANGED = "FIELD_CHANGED"
VENDOR_REFUSED = "VENDOR_REFUSED"
VENDOR_ERROR = "VENDOR_ERROR"
IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
OPERATION_IN_PROGRESS = "OPERATION_IN_PROGRESS"

IN_PROGRESS = "in_progress"
IN_PROGRESS_MESSAGE = "This change is still being saved in AutoCount. Please check again in a moment."

Record = Dict[str, Any]


def enabled() -> bool:
    """The admin switch, read per call."""
    return bool(getattr(settings, "autocount_project_registration_enabled", False))


# The registration fields (CRM plan Part A, 21 Nov): the caller's camelCase name -> AutoCount's field
# name. The CRM always sends the whole record; SS never merges fields itself.
FIELDS: Dict[str, str] = {
    "projNo": "ProjNo", "projectTitle": "ProjectTitle", "distributorName": "DistributorName",
    "salesAgent": "SalesAgent", "customerName": "CustomerName", "date": "Date",
    "typeOfBuilding": "TypeofBuilding", "state": "State", "mukim": "Mukim", "developer": "Developer",
    "architect": "Architect", "mainContractor": "MainContractor", "status": "Status",
}
DATE_FIELDS = frozenset({"Date"})
_CAMEL = {v: k for k, v in FIELDS.items()}


def camel(name: str) -> str:
    """AutoCount's field name as the caller's name (``TypeofBuilding`` -> ``typeOfBuilding``)."""
    return _CAMEL.get(name) or name[:1].lower() + name[1:]


@dataclass
class RegResult:
    """What one project registration call answered (the gateway shapes it)."""

    outcome: str
    error_code: Optional[str] = None
    message: str = ""
    warnings: List[str] = field(default_factory=list)
    proj_no: Optional[str] = None
    registration: Optional[Record] = None
    registrations: Optional[List[Record]] = None
    operation_id: Optional[str] = None
    action_id: Optional[str] = None
    changed: List[Dict[str, Any]] = field(default_factory=list)
    found: Optional[bool] = None  # set by the read by ProjNo only

    def answer(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "operationId": self.operation_id, "actionId": self.action_id, "outcome": self.outcome,
            "errorCode": self.error_code, "message": self.message, "warnings": list(self.warnings),
            "projNo": self.proj_no, "registration": self.registration, "changedFields": list(self.changed),
        }
        if self.found is not None:
            out["found"] = self.found
        if self.registrations is not None:
            out["registrations"] = self.registrations
        return out


# ── comparison (read-back) ───────────────────────────────────────────────────

def _norm(value: Any) -> Any:
    """A value as compared: numbers by value, text trimmed per line + case-folded with ``\\r\\n`` as
    ``\\n``, ``None`` as empty text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value)).normalize()
        except InvalidOperation:
            return str(value)
    if isinstance(value, str):
        text = value.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.strip() for line in text.split("\n")]
        while lines and not lines[-1]:
            lines.pop()
        while lines and not lines[0]:
            lines.pop(0)
        return "\n".join(lines).casefold()
    return value


def _same(sent: Any, read: Any, *, is_date: bool = False) -> bool:
    if is_date and isinstance(sent, str) and isinstance(read, str):
        return sent.strip()[:10] == read.strip()[:10]
    a, b = _norm(sent), _norm(read)
    if isinstance(a, Decimal) and isinstance(b, str):
        try:
            return a == Decimal(b).normalize()
        except InvalidOperation:
            return False
    if isinstance(b, Decimal) and isinstance(a, str):
        return _same(read, sent)
    return a == b


def changed_fields(sent: Record, read: Record) -> List[str]:
    """AutoCount field names whose read-back differs from what was sent (trimmed, case-insensitive,
    newline-normalised; a date by its day)."""
    return sorted(k for k, v in sent.items() if not _same(v, read.get(k), is_date=k in DATE_FIELDS))


def lock_key(proj_no: str) -> int:
    """The per-ProjNo lock number on the operation and action rows (their ``doc_key``), so the
    existing partial unique indexes (one ``in_progress`` operation, one ``in_flight`` action per
    document) serialise two writes of the same ProjNo. Always in [2**62, 2**63): never a real DocKey."""
    digest = hashlib.sha256(f"{KIND}:{proj_no.strip().upper()}".encode()).hexdigest()
    return 2**62 + int(digest[:16], 16) % 2**62


def _hash(label: str, params: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps({"op": label, "params": params}, sort_keys=True, default=str).encode()
    ).hexdigest()


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


class ProjectRegistrationService(WriteFrame):
    """Create, edit and read AutoCount project registrations for one company."""

    def __init__(self, db: Any, **kwargs: Any) -> None:
        super().__init__(db, **kwargs)
        self.ops = OperationRepository(db)
        self._lock: Optional[int] = None  # ``lock_key`` of the ProjNo being written

    # ── public ───────────────────────────────────────────────────────────────

    def capabilities(self, off_reason: Optional[str]) -> List[Dict[str, Any]]:
        """The capability feed entries (``off_reason`` = no usable write connection)."""
        reason = off_reason or (None if enabled() else VENDOR_UNSUPPORTED)
        return [{"op": p, "kind": WIRE_KIND, "enabled": reason is None, "reasonCode": reason} for p in PRIMITIVES]

    def create(
        self, *, tenant_id: str, company_id: str, key_id: Optional[str], idempotency_key: str,
        proj_no: str, record: Record, params: Dict[str, Any],
    ) -> RegResult:
        return self._idempotent(
            tenant_id=tenant_id, company_id=company_id, key_id=key_id, idempotency_key=idempotency_key,
            name="create_doc", proj_no=proj_no, params=params,
            run=lambda company, op_id, look_up: self._create(company, key_id, op_id, proj_no, record, look_up),
        )

    def edit(
        self, *, tenant_id: str, company_id: str, key_id: Optional[str], idempotency_key: Optional[str],
        proj_no: str, record: Record, params: Dict[str, Any],
    ) -> RegResult:
        run = lambda company, op_id, look_up: self._edit(company, key_id, op_id, proj_no, record)  # noqa: E731
        if not idempotency_key:  # a whole-record PUT is safe to send again: no key, no lock
            return self._plain(tenant_id, company_id, run)
        return self._idempotent(
            tenant_id=tenant_id, company_id=company_id, key_id=key_id, idempotency_key=idempotency_key,
            name="edit_doc", proj_no=proj_no, params=params, run=run,
        )

    def read(self, *, tenant_id: str, company_id: str, key_id: Optional[str], proj_no: str) -> RegResult:
        def run(company: AcCompany, op_id: Optional[str], look_up: bool) -> RegResult:
            base_url = self._open(company, key_id, proj_no)
            reader = self._reader_for(base_url)
            try:
                found = self._find(reader, proj_no)
            except DocReadError as exc:
                return RegResult(OUTCOME_REFUSED, exc.code, proj_no=proj_no)
            if found is None:
                return RegResult(OUTCOME_DONE, proj_no=proj_no, found=False)
            return RegResult(OUTCOME_DONE, proj_no=proj_no, registration=found, found=True)

        return self._plain(tenant_id, company_id, run)

    def read_day(self, *, tenant_id: str, company_id: str, key_id: Optional[str], day: date) -> RegResult:
        def run(company: AcCompany, op_id: Optional[str], look_up: bool) -> RegResult:
            base_url = self._open(company, key_id, None)
            reader = self._reader_for(base_url)
            try:
                rows = reader.fetch_records(BY_DATE_PATH, {"Date": day.strftime("%Y%m%d")})
            except DocReadError as exc:
                return RegResult(OUTCOME_REFUSED, exc.code)
            return RegResult(OUTCOME_DONE, registrations=rows)

        return self._plain(tenant_id, company_id, run)

    # ── frame pieces ─────────────────────────────────────────────────────────

    def _company(self, tenant_id: str, company_id: str) -> Optional[AcCompany]:
        return CompanyRepository(self.db).get(tenant_id, company_id)

    def _plain(self, tenant_id: str, company_id: str,
               run: Callable[[AcCompany, Optional[str], bool], RegResult]) -> RegResult:
        """A call without an idempotency row: switch, company, then ``run`` (refusals as answers)."""
        if not enabled():
            return RegResult(OUTCOME_REFUSED, VENDOR_UNSUPPORTED)
        company = self._company(tenant_id, company_id)
        if company is None:
            return RegResult(OUTCOME_REFUSED, WRITE_DISABLED)
        try:
            return run(company, None, False)
        except _Stop as stop:
            return _from_stop(stop.result)
        finally:
            self.db.rollback()

    def _open(self, company: AcCompany, key_id: Optional[str], proj_no: Optional[str],
              row: Optional[AcWriteAction] = None, operation_id: Optional[str] = None) -> str:
        """The write URL after the guard and the test-company check, and the call log wired up;
        a refusal is a ``_Stop`` (no request was made)."""
        base_url, refusal = self._resolve_write_base_url(company)
        if base_url is None:
            code, message = refusal  # type: ignore[misc]
            self._log_refused_connection(company, code, kind=KIND, action_id=row.id if row else None)
            if row is not None:
                raise self._refuse(row, code, message)
            raise _Stop(WriteActionResult(None, OUTCOME_REFUSED, code, message))
        try:
            guard.assert_test_company(self.db, company.tenant_id, company.id, book=self._company_book(company))
        except WriteConnectionError as exc:
            if row is not None:
                raise self._refuse(row, exc.code) from None
            raise _Stop(WriteActionResult(None, OUTCOME_REFUSED, exc.code)) from None
        self._call_log = self.new_call_log(
            company, kind=KIND, doc_no=proj_no, key_id=key_id, operation_id=operation_id,
            action_id=row.id if row else None,
        )
        return base_url

    def _reader_for(self, base_url: str, log: Any = None) -> Any:
        reader = super()._reader_for(base_url, log)
        setter = getattr(reader, "set_user_agent", None)
        if callable(setter):
            setter(USER_AGENT)
        return reader

    def _client_for(self, base_url: str, log: Any = None) -> Any:
        client = super()._client_for(base_url, log)
        setter = getattr(client, "set_user_agent", None)
        if callable(setter):
            setter(USER_AGENT)
        return client

    @staticmethod
    def _find(reader: Any, proj_no: str) -> Optional[Record]:
        """AutoCount's record for exactly ``proj_no`` (trimmed match), None when absent; more than one
        is ``REGISTRATION_AMBIGUOUS``, a failed read ``READ_FAILED``."""
        rows = reader.fetch_records(BY_PROJ_NO_PATH, {"ProjNo": proj_no}, not_found_404=True)
        matches = [r for r in rows if str(r.get("ProjNo") or "").strip() == proj_no.strip()]
        if len(matches) > 1:
            raise DocReadError(REGISTRATION_AMBIGUOUS)
        return matches[0] if matches else None

    def _new_row(self, company: AcCompany, name: str, key_id: Optional[str], op_id: Optional[str]) -> AcWriteAction:
        return self.actions.add(AcWriteAction(
            tenant_id=company.tenant_id, company_id=company.id, action=name, doc_type=KIND, doc_key=self._lock,
            outcome=OUTCOME_REFUSED, key_id=key_id, operation_id=op_id, created_at=datetime.now(timezone.utc),
            **self._trace_columns(),
        ))

    def _done(self, row: AcWriteAction, sent: Record, read: Record, proj_no: str) -> RegResult:
        """Compare the read-back with what was sent: ``done``; a difference is a ``FIELD_CHANGED``
        warning carrying AutoCount's value (``changedFields``)."""
        row.after_json = read
        self._finish(row, OUTCOME_DONE)
        changed = changed_fields(sent, read)
        if not changed:
            return RegResult(OUTCOME_DONE, proj_no=proj_no, registration=read, action_id=row.id)
        names = [camel(n) for n in changed]
        return RegResult(
            OUTCOME_DONE, None, "AutoCount kept a different value for: " + ", ".join(names) + ".",
            [FIELD_CHANGED], proj_no, read, action_id=row.id,
            changed=[{"field": camel(n), "sent": sent.get(n), "autocount": read.get(n)} for n in changed],
        )

    def _write(
        self, company: AcCompany, key_id: Optional[str], op_id: Optional[str], name: str, proj_no: str,
        method: str, path: str, body: Record, *, must_exist: bool, look_up: bool,
    ) -> RegResult:
        """One create or edit: read first, send, read back, compare."""
        self._lock = lock_key(proj_no)
        row = self._new_row(company, name, key_id, op_id)
        self._put_sent = False
        try:
            base_url = self._open(company, key_id, proj_no, row, op_id)
            reader = self._reader_for(base_url)
            try:
                before = self._find(reader, proj_no)
            except DocReadError as exc:
                if look_up:  # an unclear earlier create: still unknown
                    return _of(self._finish(row, OUTCOME_PENDING, exc.code), proj_no)
                return _of(self._finish(row, OUTCOME_REFUSED, exc.code), proj_no)
            row.before_json = before
            if look_up and before is not None:  # never re-sent: the earlier create landed, or another did
                if changed_fields(body, before):
                    res = self._finish(row, OUTCOME_REFUSED, REGISTRATION_EXISTS, message=_exists(proj_no))
                    return _of(res, proj_no, registration=before)
                return self._done(row, body, before, proj_no)
            if must_exist and before is None:
                res = self._finish(row, OUTCOME_REFUSED, REGISTRATION_NOT_FOUND, message=_not_found(proj_no))
                return _of(res, proj_no)
            if not must_exist and before is not None:
                res = self._finish(row, OUTCOME_REFUSED, REGISTRATION_EXISTS, message=_exists(proj_no))
                return _of(res, proj_no, registration=before)
            row.request_method, row.request_path, row.request_json = method, path, body
            window = datetime.now(timezone.utc) - timedelta(seconds=frame.BUSY_WINDOW_SECONDS)
            self.actions.expire_stale_in_flight(company.tenant_id, company.id, self._lock, window)
            row.outcome = OUTCOME_IN_FLIGHT
            try:
                self.db.commit()  # in_flight + the exact body committed before the call
            except IntegrityError:  # another write of this ProjNo is in flight (one per ProjNo)
                self.db.rollback()
                busy = self._new_row(company, name, key_id, op_id)
                return _of(self._finish(busy, OUTCOME_REFUSED, DOC_BUSY, message=IN_PROGRESS_MESSAGE), proj_no)
            client = self._client_for(base_url)
            self._put_sent = True
            try:
                response = client.post(path, body) if method == "POST" else client.put(path, body)
            except WriteTransportError as exc:  # may or may not have landed: look it up now
                return self._check_unclear(row, reader, body, proj_no, exc.code)
            row.response_status, row.response_json = response.status_code, _json_safe(response.stored)
            if not response.ok:
                if is_business_refusal(response.status_code, response.body):
                    res = self._finish(row, OUTCOME_REFUSED, VENDOR_REFUSED,  # nothing applied: key released
                                       message=vendor_message(response.stored, base_url))  # API key masked
                    return _of(res, proj_no)
                if response.status_code >= 500:  # a bare fault: it may have landed
                    return self._check_unclear(row, reader, body, proj_no, VENDOR_ERROR)
                return _of(self._finish(row, OUTCOME_VENDOR_ERROR, VENDOR_ERROR), proj_no)
            return self._check_unclear(row, reader, body, proj_no, READ_FAILED, sent_ok=True)
        except _Stop as stop:
            return _of(stop.result, proj_no)
        except Exception:  # noqa: BLE001 - the in_flight row must never be stranded
            logger.exception("autocount project registration failed (action %s)", row.id)
            self.db.rollback()
            outcome = OUTCOME_PENDING if self._put_sent else OUTCOME_REFUSED
            return _of(self._finish(row, outcome, INTERNAL_ERROR), proj_no)

    def _check_unclear(self, row: AcWriteAction, reader: Any, body: Record, proj_no: str, code: str, *,
                       sent_ok: bool = False) -> RegResult:
        """Read the ProjNo back after a send: found = compared (``done``, differences as warnings);
        absent or unreadable = ``pending_verification`` (with ``code`` after an unclear send; a resend
        looks the ProjNo up before sending again)."""
        try:
            after = self._find(reader, proj_no)
        except DocReadError as exc:
            return _of(self._finish(row, OUTCOME_PENDING, exc.code if sent_ok else code), proj_no)
        if after is None:
            return _of(self._finish(row, OUTCOME_PENDING, REGISTRATION_NOT_FOUND if sent_ok else code), proj_no)
        if not sent_ok and row.action == "edit_doc" and changed_fields(body, after):
            return _of(self._finish(row, OUTCOME_PENDING, code), proj_no, registration=after)
        return self._done(row, body, after, proj_no)

    def _create(self, company: AcCompany, key_id: Optional[str], op_id: Optional[str], proj_no: str,
                record: Record, look_up: bool) -> RegResult:
        body = dict(record, ProjNo=proj_no)
        return self._write(company, key_id, op_id, "create_doc", proj_no, "POST", NEW_PATH, body,
                           must_exist=False, look_up=look_up)

    def _edit(self, company: AcCompany, key_id: Optional[str], op_id: Optional[str], proj_no: str,
              record: Record) -> RegResult:
        body = dict(record, ProjNo=proj_no)
        return self._write(company, key_id, op_id, "edit_doc", proj_no, "PUT", EDIT_PATH, body,
                           must_exist=True, look_up=False)

    # ── idempotency (one ac_write_operation row per key) ─────────────────────

    def _idempotent(
        self, *, tenant_id: str, company_id: str, key_id: Optional[str], idempotency_key: str, name: str,
        proj_no: str, params: Dict[str, Any],
        run: Callable[[AcCompany, Optional[str], bool], RegResult],
    ) -> RegResult:
        """The stored answer on a same-key replay, ``IDEMPOTENCY_CONFLICT`` for another body, else run.
        A stored refusal / vendor refusal releases the key (runs fresh); an unknown create outcome is
        looked up by ProjNo before anything is sent again; only done stays locked."""
        if not enabled():
            return RegResult(OUTCOME_REFUSED, VENDOR_UNSUPPORTED, proj_no=proj_no)
        company = self._company(tenant_id, company_id)
        if company is None:
            return RegResult(OUTCOME_REFUSED, WRITE_DISABLED, proj_no=proj_no)
        label = f"{name}:{KIND}"
        request_hash = _hash(label, params)
        look_up = False
        existing = self.ops.by_key(tenant_id, company_id, key_id, idempotency_key)
        if existing is not None:
            if existing.op != label or existing.request_hash != request_hash:
                return RegResult(OUTCOME_REFUSED, IDEMPOTENCY_CONFLICT, proj_no=proj_no)
            window = datetime.now(timezone.utc) - timedelta(seconds=frame.BUSY_WINDOW_SECONDS)
            if existing.status == IN_PROGRESS:
                if not self.ops.expire_stale_operation(tenant_id, company_id, existing.id, window):
                    return RegResult(OUTCOME_REFUSED, OPERATION_IN_PROGRESS, IN_PROGRESS_MESSAGE, proj_no=proj_no)
                self.db.commit()
                self.db.refresh(existing)
            if existing.status == OUTCOME_DONE and existing.result_json:
                return _stored(existing.result_json)
            # refused / vendor error / pending: release the key and run again (a pending create
            # looks its ProjNo up first, so it is never sent twice)
            look_up = name == "create_doc" and existing.status == OUTCOME_PENDING
            self.ops.delete(existing)
            self.db.commit()
        lock = lock_key(proj_no)
        window = datetime.now(timezone.utc) - timedelta(seconds=frame.BUSY_WINDOW_SECONDS)
        if self.ops.expire_stale_in_progress(tenant_id, company_id, KIND, lock, window):
            self.db.commit()  # a crashed run no longer holds the ProjNo
        row = AcWriteOperation(
            tenant_id=tenant_id, company_id=company_id, key_id=key_id, idempotency_key=idempotency_key,
            request_hash=request_hash, op=label, doc_type=KIND, doc_key=lock, status=IN_PROGRESS,
            snapshot_json={"projNo": proj_no},
        )
        try:  # the partial unique index allows one in_progress operation per ProjNo
            self.ops.add(row)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            if self.ops.by_key(tenant_id, company_id, key_id, idempotency_key) is not None:
                return RegResult(OUTCOME_REFUSED, OPERATION_IN_PROGRESS, IN_PROGRESS_MESSAGE, proj_no=proj_no)
            return RegResult(OUTCOME_REFUSED, DOC_BUSY, IN_PROGRESS_MESSAGE, proj_no=proj_no)
        op_id = row.id
        result = RegResult(OUTCOME_PENDING, INTERNAL_ERROR, proj_no=proj_no)
        try:
            result = run(company, op_id, look_up)
        except Exception:  # noqa: BLE001 - the in_progress lock must never be stranded
            logger.exception("autocount project registration failed (operation %s)", op_id)
            self.db.rollback()
        finally:
            result.operation_id = op_id
            stored = self.ops.get(tenant_id, company_id, op_id)
            if stored is not None:
                stored.status, stored.error_code = result.outcome, result.error_code
                stored.result_json = _json_safe(result.answer())
            self.db.commit()
        return result


def _not_found(proj_no: str) -> str:
    return f"AutoCount has no registration {proj_no}."


def _exists(proj_no: str) -> str:
    return f"AutoCount already has {proj_no}."


def _of(res: WriteActionResult, proj_no: str, registration: Optional[Record] = None) -> RegResult:
    return RegResult(res.outcome, res.error_code, res.message, list(res.warnings), proj_no,
                     registration if registration is not None else res.document, action_id=res.action_id)


def _from_stop(res: WriteActionResult) -> RegResult:
    return RegResult(res.outcome, res.error_code, res.message, action_id=res.action_id)


def _stored(answer: Dict[str, Any]) -> RegResult:
    return RegResult(
        answer.get("outcome") or OUTCOME_PENDING, answer.get("errorCode"), answer.get("message") or "",
        list(answer.get("warnings") or []), answer.get("projNo"), answer.get("registration"),
        answer.get("registrations"), answer.get("operationId"), answer.get("actionId"),
        list(answer.get("changedFields") or []), answer.get("found"),
    )

