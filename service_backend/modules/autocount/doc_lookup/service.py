"""``DocLookupService`` - find an AutoCount document by number (plan 17 section 4).

Phase A (``stored``): ready snapshot rows + the doc feed ledger, zero vendor
calls. Phase B (``start`` -> the ``autocount_doc_lookup`` job, ``job.py``):
a live scan in a fixed step order - hint days, by-LastModified from today
back N days, by-DocDate from today forward M days - stopping at the first
record whose number matches. Read only (D1).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.jobs.service import JobService
from app.models.background_job import (
    JOB_ABORTED,
    JOB_TERMINAL_STATUSES,
    BackgroundJob,
)

from ..doc_feed.clock import MYT
from ..doc_feed.records import parse_doc_day
from ..models import (
    DOC_LOOKUP_DEFAULT_BACK_DAYS,
    DOC_LOOKUP_DEFAULT_FORWARD_DAYS,
    DOC_LOOKUP_MAX_WINDOW_DAYS,
)
from ..repositories import CompanyRepository
from ..repositories.doc_feed_repository import DocFeedRepository
from ..repositories.doc_lookup_repository import DocLookupRepository
from ..services.company_service import AutocountServiceError
from ..services.pull_gateway_service import _CONTROL_CHARS_RE, DO_MAX_DOC_NO_LEN
from .registry import AcDocType, all_doc_types, detect_doc_type, get_doc_type

DOC_LOOKUP_JOB_TYPE = "autocount_doc_lookup"

DOOR_BY_DOC_DATE = "by_doc_date"
DOOR_BY_LAST_MODIFIED = "by_last_modified"

STEP_PENDING = "pending"
STEP_HIT = "hit"
STEP_MISS = "miss"
STEP_ERROR = "error"
STEP_SKIPPED = "skipped"

AROUND_DAY_RADIUS = 3


class DocLookupError(AutocountServiceError):
    """Operator-safe message + a stable ``code``; the router maps
    ``status_code`` straight onto the HTTP response."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _invalid(message: str) -> DocLookupError:
    return DocLookupError(422, "INVALID_REQUEST", message)


# ── input ────────────────────────────────────────────────────────────────────


def normalize_doc_no(raw: Any) -> str:
    """Trimmed number, 1..64 chars, no control characters. Messages name the
    field and never echo the value (the gateway's own ``parse_do_scope`` rule)."""
    if not isinstance(raw, str):
        raise _invalid("docNo must be a string.")
    if _CONTROL_CHARS_RE.search(raw):
        raise _invalid("docNo must not contain control characters.")
    doc_no = raw.strip()
    if not doc_no:
        raise _invalid("docNo must not be empty.")
    if len(doc_no) > DO_MAX_DOC_NO_LEN:
        raise _invalid(f"docNo must be at most {DO_MAX_DOC_NO_LEN} characters.")
    return doc_no


def norm_key(doc_no: str) -> str:
    return doc_no.strip().casefold()


def resolve_doc_type(key: Optional[str], doc_no: str) -> AcDocType:
    if key is None or key == "":
        return detect_doc_type(doc_no)
    doc_type = get_doc_type(key)
    if doc_type is None:
        raise _invalid("docType is not a known AutoCount document type.")
    return doc_type


def parse_around_day(raw: Optional[str]) -> Optional[date]:
    if raw is None or raw == "":
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise _invalid("aroundDay must be a YYYY-MM-DD date.") from None


def today_myt() -> date:
    return datetime.now(timezone.utc).astimezone(MYT).date()


# ── record views ─────────────────────────────────────────────────────────────


def _cancelled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().upper() in ("T", "TRUE", "Y", "1")


def _doc_key(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    return int(text) if text.lstrip("-").isdigit() else None


def _str_or_none(value: Any) -> Optional[str]:
    return None if value is None or value == "" else str(value)


def record_matches(doc_type: AcDocType, record: Dict[str, Any], wanted_norm: str) -> bool:
    value = record.get(doc_type.doc_no_field)
    return isinstance(value, str) and value.strip().casefold() == wanted_norm


def record_view(doc_type: AcDocType, record: Dict[str, Any]) -> Dict[str, Any]:
    """The current record: curated facts + the header verbatim (lines field
    removed) + the lines verbatim. No field is renamed or retyped."""
    day = parse_doc_day(record.get(doc_type.doc_date_field))
    lines = record.get(doc_type.lines_field)
    return {
        "docKey": _doc_key(record.get(doc_type.doc_key_field)),
        "docNo": _str_or_none(record.get(doc_type.doc_no_field)),
        "docDate": day.isoformat() if day else None,
        "lastModified": _str_or_none(record.get(doc_type.last_modified_field)),
        "lastModifiedBy": _str_or_none(record.get(doc_type.last_modified_user_field)),
        "cancelled": _cancelled(record.get(doc_type.cancelled_field)),
        "header": {k: v for k, v in record.items() if k != doc_type.lines_field},
        "lines": lines if isinstance(lines, list) else [],
    }


def pick_latest(doc_type: AcDocType, records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Several copies of the same number in one day read -> the newest
    LastModified (the vendor's fixed ISO format sorts lexically, plan 08 D7)."""
    return max(records, key=lambda r: str(r.get(doc_type.last_modified_field) or ""))


# ── step plan ────────────────────────────────────────────────────────────────


def build_steps(
    doc_type: AcDocType, *, hint_days: List[date], today: date, back_days: int,
    forward_days: int,
) -> List[Dict[str, Any]]:
    """Hint days (by DocDate) -> by-LastModified today..today-N -> by-DocDate
    today..today+M. A (door, day) already planned is never planned twice."""
    steps: List[Dict[str, Any]] = []
    seen = set()

    def add(door: str, on: date) -> None:
        if (door, on) in seen:
            return
        seen.add((door, on))
        steps.append({"door": door, "day": on.isoformat(), "status": STEP_PENDING, "count": None})

    for on in hint_days:
        add(DOOR_BY_DOC_DATE, on)
    if doc_type.by_last_modified_path:
        for offset in range(back_days + 1):
            add(DOOR_BY_LAST_MODIFIED, today - timedelta(days=offset))
    for offset in range(forward_days + 1):
        add(DOOR_BY_DOC_DATE, today + timedelta(days=offset))
    return steps


def around_days(around: date) -> List[date]:
    days = [around]
    for k in range(1, AROUND_DAY_RADIUS + 1):
        days += [around - timedelta(days=k), around + timedelta(days=k)]
    return days


def searched_windows(doc_type: AcDocType, today: date, back_days: int, forward_days: int):
    return {
        "lastModifiedFrom": (today - timedelta(days=back_days)).isoformat()
        if doc_type.by_last_modified_path else None,
        "lastModifiedTo": today.isoformat() if doc_type.by_last_modified_path else None,
        "docDateFrom": today.isoformat(),
        "docDateTo": (today + timedelta(days=forward_days)).isoformat(),
    }


# ── the service ──────────────────────────────────────────────────────────────


class DocLookupService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = DocLookupRepository(db)

    # ── registry ─────────────────────────────────────────────────────────────

    def types(self, tenant_id: str, company_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """The registry. With ``company_id``, each type also says whether the
        company has an AutoCount connection for it (``connected``) - so the
        page warns before a search instead of after a 409 (foolproof-UI)."""
        connected: Optional[Dict[str, bool]] = None
        if company_id is not None:
            company = self._company(tenant_id, company_id)
            feeds = DocFeedRepository(self.db).list_for_company(tenant_id, company.id)
            wired = {f.feed for f in feeds if f.connection_id}
            connected = {t.key: t.feed in wired for t in all_doc_types()}
        return [
            {
                "key": t.key,
                "label": t.label,
                "prefixes": list(t.doc_no_prefixes),
                "hasLastModified": t.by_last_modified_path is not None,
                "hasByDocNo": t.by_doc_no is not None,
                "connected": None if connected is None else connected[t.key],
            }
            for t in all_doc_types()
        ]

    # ── shared lookups ───────────────────────────────────────────────────────

    def _company(self, tenant_id: str, company_id: str):
        company = CompanyRepository(self.db).get(tenant_id, company_id)
        if company is None:
            raise DocLookupError(404, "COMPANY_NOT_FOUND", "AutoCount company not found.")
        return company

    def stored_history(
        self, tenant_id: str, company_id: str, doc_type: AcDocType, doc_no: str,
    ) -> Dict[str, Any]:
        """Phase A - snapshot sightings + the ledger row. SELECTs only."""
        wanted = norm_key(doc_no)
        sightings: List[Dict[str, Any]] = []
        if doc_type.snapshot_entity_type:
            for snapshot, row in self.repo.snapshot_sightings(
                tenant_id, company_id, doc_type.snapshot_entity_type, wanted,
            ):
                payload = row.payload_json if isinstance(row.payload_json, dict) else {}
                meta = snapshot.metadata_json if isinstance(snapshot.metadata_json, dict) else {}
                day = parse_doc_day(payload.get(doc_type.doc_date_field))
                sightings.append({
                    "snapshotId": snapshot.id,
                    "createdAt": snapshot.created_at,
                    "extractedAt": snapshot.extracted_at,
                    "fromDay": meta.get("fromDay"),
                    "toDay": meta.get("toDay"),
                    "byNumber": bool(meta.get("docNo")),
                    "docKey": _doc_key(payload.get(doc_type.doc_key_field)),
                    "docDate": day.isoformat() if day else None,
                    "lastModified": _str_or_none(payload.get(doc_type.last_modified_field)),
                    "cancelled": _cancelled(payload.get(doc_type.cancelled_field)),
                })
        ledger = None
        if doc_type.ledger_feed:
            row = self.repo.ledger_row(tenant_id, company_id, doc_type.ledger_feed, wanted)
            if row is not None:
                ledger = {
                    "docKey": row.doc_key,
                    "docDate": row.doc_date.isoformat() if row.doc_date else None,
                    "sourceModifiedAt": row.source_modified_at,
                    "lastOutcome": row.last_outcome,
                    "pushedAt": row.pushed_at,
                    "vanishedAt": row.vanished_at,
                }
        return {"docType": doc_type.key, "docNo": doc_no, "snapshots": sightings, "ledger": ledger}

    def stored(
        self, tenant_id: str, company_id: str, doc_no_raw: Any, doc_type_key: Optional[str],
    ) -> Dict[str, Any]:
        doc_no = normalize_doc_no(doc_no_raw)
        doc_type = resolve_doc_type(doc_type_key, doc_no)
        self._company(tenant_id, company_id)
        return self.stored_history(tenant_id, company_id, doc_type, doc_no)

    # ── settings (D7) ────────────────────────────────────────────────────────

    def windows(self, tenant_id: str, company_id: str) -> Tuple[int, int]:
        row = self.repo.get_settings(tenant_id, company_id)
        if row is None:
            return DOC_LOOKUP_DEFAULT_BACK_DAYS, DOC_LOOKUP_DEFAULT_FORWARD_DAYS
        return row.back_days, row.forward_days

    def get_settings(self, tenant_id: str, company_id: str) -> Dict[str, Any]:
        self._company(tenant_id, company_id)
        back, forward = self.windows(tenant_id, company_id)
        return {"companyId": company_id, "lastModifiedBackDays": back, "docDateForwardDays": forward}

    def save_settings(
        self, tenant_id: str, company_id: str, *, back_days: int, forward_days: int,
    ) -> Dict[str, Any]:
        self._company(tenant_id, company_id)
        for name, value in (("lastModifiedBackDays", back_days), ("docDateForwardDays", forward_days)):
            if not 0 <= value <= DOC_LOOKUP_MAX_WINDOW_DAYS:
                raise _invalid(f"{name} must be between 0 and {DOC_LOOKUP_MAX_WINDOW_DAYS}.")
        self.repo.save_settings(tenant_id, company_id, back_days=back_days, forward_days=forward_days)
        self.db.commit()
        return self.get_settings(tenant_id, company_id)

    # ── live lookup job ──────────────────────────────────────────────────────

    def start(
        self, tenant_id: str, actor_id: Optional[str], *, company_id: str, doc_no_raw: Any,
        doc_type_key: Optional[str], around_day_raw: Optional[str],
    ) -> BackgroundJob:
        doc_no = normalize_doc_no(doc_no_raw)
        doc_type = resolve_doc_type(doc_type_key, doc_no)
        around = parse_around_day(around_day_raw)
        company = self._company(tenant_id, company_id)

        feed_row = DocFeedRepository(self.db).get(tenant_id, company.id, doc_type.feed)
        if feed_row is None or not feed_row.connection_id:
            raise DocLookupError(
                409, "NO_CONNECTION",
                f"This company has no AutoCount connection for {doc_type.label.lower()}s. "
                "Set up its document feed connection first.",
            )

        wanted = norm_key(doc_no)
        for open_job in self.repo.open_jobs(tenant_id, DOC_LOOKUP_JOB_TYPE):
            payload = open_job.payload_json or {}
            if payload.get("companyId") != company.id:
                continue
            if payload.get("docType") == doc_type.key and norm_key(str(payload.get("docNo") or "")) == wanted:
                return open_job  # re-attach (AC-17-18)
            raise DocLookupError(
                409, "LOOKUP_IN_FLIGHT",
                "Another document search is running for this company. Wait for it or stop it.",
            )

        jobs = JobService(self.db)
        job = jobs.create(
            type=DOC_LOOKUP_JOB_TYPE, tenant_id=tenant_id, actor_user_id=actor_id,
            payload={
                "companyId": company.id,
                "docNo": doc_no,
                "docType": doc_type.key,
                "aroundDay": around.isoformat() if around else None,
            },
        )
        jobs.enqueue(job.id)
        self.db.refresh(job)
        return job

    def get_job(self, tenant_id: str, job_id: str) -> BackgroundJob:
        job = self.repo.get_job(tenant_id, DOC_LOOKUP_JOB_TYPE, job_id)
        if job is None:
            raise DocLookupError(404, "JOB_NOT_FOUND", "Document search not found.")
        return job

    def stop(self, tenant_id: str, job_id: str) -> BackgroundJob:
        job = self.get_job(tenant_id, job_id)
        if job.status not in JOB_TERMINAL_STATUSES:
            JobService(self.db).finish(job, status=JOB_ABORTED, error="Stopped by the user.")
        self.db.refresh(job)
        return job


def job_view(job: BackgroundJob) -> Dict[str, Any]:
    payload = job.payload_json or {}
    return {
        "jobId": job.id,
        "status": job.status,
        "companyId": payload.get("companyId"),
        "docNo": payload.get("docNo"),
        "docType": payload.get("docType"),
        "progressDone": job.progress_done or 0,
        "progressTotal": job.progress_total or 0,
        "result": job.result_json,
        "error": job.error,
        "createdAt": job.created_at,
        "finishedAt": job.finished_at,
    }
