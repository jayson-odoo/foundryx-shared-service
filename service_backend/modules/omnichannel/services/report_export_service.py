"""Report CSV export - a `background_jobs` job (plan 30 S3, roadmap A9,
D-A9-4). Mirrors `contact_export_service.py`'s shape exactly (`register_job_
handler`, one code path eager-inline in dev/test vs Celery in prod,
cooperative cancellation re-read at every checkpoint, a UTF-8 BOM, every cell
through `sanitize_cell`) - the ONE difference is what a "row" is: the export
NEVER reforks a query. It always calls the SAME `report_service.report()`
every read route calls, and turns whatever THAT returns (`buckets`+`series`
for the two report shapes with no per-record rows, or `rows` verbatim for
the other five/groupings) into CSV rows.

Row cap (`EXPORT_MAX_ROWS`, plan §5.4) is checked synchronously BEFORE any
job row exists (the `ExportRowCapExceeded` precedent) by asking the SAME
builder for its row count - a paginated report's `total` (page 0/size 1,
cheap) or an unpaginated report's `len(rows)`.
"""
from __future__ import annotations

import codecs
import csv
import io
import logging
from datetime import datetime
from datetime import timezone as _utc
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.import_engine.sanitize import sanitize_cell
from app.jobs.registry import JobHandlerDef, register_job_handler
from app.jobs.service import JobService
from app.models.background_job import JOB_ABORTED, JOB_DONE, BackgroundJob
from app.services.storage import storage_for_tenant

from ..schemas import ReportExportRequest, ReportResponse
from . import report_service
from .report_service import descriptor_for

logger = logging.getLogger("foundryx.omnichannel.report_export")

REPORT_EXPORT_JOB_TYPE = "omnichannel.report_export"
EXPORT_MAX_ROWS = 50_000  # plan §5.4
EXPORT_PAGE_SIZE = 200  # plan S3 handoff - "page at 200 for the paginated ones"

# Column key -> the timestamp columns that must render in the requested `tz`
# with the offset appended (plan §5.4) rather than as a raw ISO instant. Every
# other cell is a plain scalar the builder already produced.
_TIMESTAMP_COLUMNS = {"startsAt", "endsAt", "createdAt"}

_USER_COLUMNS: List[Tuple[str, str]] = [
    ("userId", "User ID"),
    ("name", "Name"),
    ("teamName", "Team"),
    ("assignedCount", "Assigned"),
    ("closedCount", "Closed"),
    ("uniqueContacts", "Unique contacts"),
    ("messagesSent", "Messages sent"),
    ("commentsCount", "Comments"),
    ("medianFirstResponseSeconds", "Median first response (s)"),
    ("medianResolutionSeconds", "Median resolution (s)"),
]

_DURATION_BY_USER_COLUMNS: List[Tuple[str, str]] = [
    ("userId", "User ID"),
    ("name", "Name"),
    ("sampleCount", "Samples"),
    ("medianSeconds", "Median (s)"),
    ("p90Seconds", "P90 (s)"),
    ("averageSeconds", "Average (s)"),
]

# Static (reportKey, groupBy) -> ordered (key, label) columns for every report
# shape whose `rows` are already the exportable table (plan §5.2's table).
# `conversations` and ungrouped `messages` have NO per-record `rows` (only a
# bucketed series) - those two are handled separately by `_bucketed_columns`/
# `_bucketed_rows` below, built from `series`/`buckets` so the column labels
# stay the SAME ones the chart legend uses (never a second hardcoded list).
_STATIC_COLUMNS: Dict[Tuple[str, Optional[str]], List[Tuple[str, str]]] = {
    ("messages", "channel"): [
        ("channelId", "Channel ID"),
        ("name", "Channel"),
        ("channelType", "Type"),
        ("incoming", "Incoming"),
        ("outgoing", "Outgoing"),
    ],
    ("responses", None): [
        ("bucket", "Bucket"),
        ("label", "Label"),
        ("count", "Count"),
        ("percent", "Percent"),
    ],
    ("responses", "user"): _DURATION_BY_USER_COLUMNS,
    ("resolutions", None): [
        ("closeReasonId", "Close reason ID"),
        ("name", "Close reason"),
        ("count", "Count"),
        ("percent", "Percent"),
    ],
    ("resolutions", "user"): _DURATION_BY_USER_COLUMNS,
    ("users", None): _USER_COLUMNS,
    ("leaderboard", None): [("rank", "Rank")] + _USER_COLUMNS,
    ("assignments", None): [
        ("id", "Event ID"),
        ("createdAt", "Date"),
        ("contactId", "Contact ID"),
        ("contactName", "Contact"),
        ("eventType", "Event"),
        ("previousAssigneeId", "Previous assignee ID"),
        ("previousAssigneeName", "Previous assignee"),
        ("assignedToId", "Assigned to ID"),
        ("assignedToName", "Assigned to"),
        ("source", "Source"),
        ("actorUserId", "Actor user ID"),
        ("actorName", "Actor"),
    ],
}

# The two report shapes with NO per-record `rows` at all (the client charts
# them from `buckets`+`series` instead) - export turns each bucket into one
# CSV row, one column per series.
_BUCKETED_REPORTS = {"conversations", "messages"}


class ReportExportRowCapExceeded(Exception):
    def __init__(self, count: int, cap: int):
        super().__init__(f"{count} rows exceeds the {cap}-row export cap.")
        self.count = count
        self.cap = cap


def _bucketed_columns(resp: ReportResponse) -> List[Tuple[str, str]]:
    cols: List[Tuple[str, str]] = [("bucket", "Bucket"), ("startsAt", "Start"), ("endsAt", "End")]
    cols += [(s.key, s.label) for s in resp.series]
    return cols


def _bucketed_rows(resp: ReportResponse) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for i, b in enumerate(resp.buckets):
        row: Dict[str, Any] = {"bucket": b.key, "startsAt": b.startsAt, "endsAt": b.endsAt}
        for s in resp.series:
            row[s.key] = s.points[i]
        rows.append(row)
    return rows


def _columns_for(report_key: str, group_by: Optional[str], resp: ReportResponse) -> List[Tuple[str, str]]:
    if report_key in _BUCKETED_REPORTS and group_by is None:
        return _bucketed_columns(resp)
    columns = _STATIC_COLUMNS.get((report_key, group_by))
    if columns is not None:
        return columns
    # Defensive fallback (should never trigger - every (reportKey, groupBy)
    # combination `report_service` accepts is mapped above): derive column
    # ids from whatever the first row actually carries rather than crash.
    return [(k, k) for k in (resp.rows[0].keys() if resp.rows else [])]


def _rows_for(report_key: str, group_by: Optional[str], resp: ReportResponse) -> List[Dict[str, Any]]:
    if report_key in _BUCKETED_REPORTS and group_by is None:
        return _bucketed_rows(resp)
    return resp.rows


def _format_dt_in_tz(value: Any, tz: ZoneInfo) -> str:
    """`YYYY-MM-DD HH:MM:SS +08:00` in the requested tz (plan §5.4) - never a
    raw UTC instant a spreadsheet reader would silently mis-render. `value`
    is either an aware `datetime` (bucket edges) or an already-Z-suffixed ISO
    string (the assignment log's `createdAt` - `ApiModel`'s wildcard
    datetime serializer does not reach values nested inside `rows: List[
    Dict]`, so the service pre-formats it to a string before it lands there;
    this export path must accept BOTH shapes)."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=_utc.utc)
    local = value.astimezone(tz)
    offset = local.strftime("%z") or "+0000"
    offset = f"{offset[:3]}:{offset[3:]}"
    return local.strftime("%Y-%m-%d %H:%M:%S") + f" {offset}"


def _cell(row: Dict[str, Any], key: str, tz: ZoneInfo) -> str:
    value = row.get(key)
    if key in _TIMESTAMP_COLUMNS and value is not None:
        return sanitize_cell(_format_dt_in_tz(value, tz))
    return sanitize_cell(value)


def _report_kwargs(payload: dict) -> dict:
    return dict(
        from_=payload["from"],
        to=payload["to"],
        tz=payload["tz"],
        granularity=payload.get("granularity"),
        user_id=payload.get("userId"),
        channel_id=payload.get("channelId"),
        team_id=payload.get("teamId"),
        group_by=payload.get("groupBy"),
    )


def _row_count(db: Session, tenant_id: str, workspace_id: str, report_key: str, req: ReportExportRequest) -> int:
    """The row count the export would produce, via the SAME builder the
    handler runs - never a second query path (AC-RPT-33's "reuse each
    builder's rows" rule extends to the cap check)."""
    descriptor = descriptor_for(report_key)
    kwargs = dict(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        from_=req.from_,
        to=req.to,
        tz=req.tz,
        granularity=req.granularity,
        user_id=req.userId,
        channel_id=req.channelId,
        team_id=req.teamId,
        group_by=req.groupBy,
    )
    if descriptor.paginated:
        resp = report_service.report(db, report_key, page=0, page_size=1, **kwargs)
        return resp.total or 0
    resp = report_service.report(db, report_key, **kwargs)
    return len(_rows_for(report_key, req.groupBy, resp))


def create_report_export_job(
    db: Session,
    tenant_id: str,
    workspace_id: str,
    actor_user_id: Optional[str],
    report_key: str,
    req: ReportExportRequest,
) -> BackgroundJob:
    """Fails FAST (422, before any job row exists) when the requested report
    would exceed `EXPORT_MAX_ROWS` (AC-RPT-36). May raise `ReportKeyNotFound`,
    `GroupByNotSupported`, `ReportValidationError` or `SampleCapExceeded` -
    the router maps each the SAME way the read route does."""
    count = _row_count(db, tenant_id, workspace_id, report_key, req)
    if count > EXPORT_MAX_ROWS:
        raise ReportExportRowCapExceeded(count, EXPORT_MAX_ROWS)

    payload = {
        "workspaceId": workspace_id,
        "reportKey": report_key,
        "from": req.from_,
        "to": req.to,
        "tz": req.tz,
        "granularity": req.granularity,
        "userId": req.userId,
        "channelId": req.channelId,
        "teamId": req.teamId,
        "groupBy": req.groupBy,
    }
    return JobService(db).create_and_enqueue(
        type=REPORT_EXPORT_JOB_TYPE, tenant_id=tenant_id, actor_user_id=actor_user_id, payload=payload
    )


def _aborted(db: Session, job_id: str) -> bool:
    """Re-read the job's status FRESH from the DB - a concurrent abort commits
    JOB_ABORTED on a different session (mirrors `contact_export_service.py`'s
    own `_aborted` helper, and `app/storage_migration/service.py`'s)."""
    return (
        db.query(BackgroundJob.status).filter(BackgroundJob.id == job_id).scalar() == JOB_ABORTED
    )


def run_report_export(db: Session, job: BackgroundJob) -> None:
    """`omnichannel.report_export` job handler (AC-RPT-33/34/35)."""
    service = JobService(db)
    payload = job.payload_json or {}
    tenant_id = job.tenant_id
    workspace_id = payload["workspaceId"]
    report_key = payload["reportKey"]
    group_by = payload.get("groupBy")
    descriptor = descriptor_for(report_key)
    tz = ZoneInfo(payload["tz"])
    kwargs = _report_kwargs(payload)

    buf = io.StringIO()
    writer = csv.writer(buf)
    total_rows = 0

    if descriptor.paginated:
        page = 0
        resp = report_service.report(
            db, report_key, tenant_id=tenant_id, workspace_id=workspace_id,
            page=page, page_size=EXPORT_PAGE_SIZE, **kwargs,
        )
        columns = _columns_for(report_key, group_by, resp)
        writer.writerow([sanitize_cell(label) for _, label in columns])
        total = resp.total or 0
        service.set_total(job, total)

        while True:
            rows = _rows_for(report_key, group_by, resp)
            for row in rows:
                writer.writerow([_cell(row, key, tz) for key, _ in columns])
                total_rows += 1
            service.advance(job, done=len(rows))
            # Cooperative cancel (mirrors contacts export) - re-read status
            # FRESH before fetching/writing the next page.
            if _aborted(db, job.id):
                logger.info("report export %s aborted mid-run at page %s", job.id, page)
                return
            if (page + 1) * EXPORT_PAGE_SIZE >= total or not rows:
                break
            page += 1
            resp = report_service.report(
                db, report_key, tenant_id=tenant_id, workspace_id=workspace_id,
                page=page, page_size=EXPORT_PAGE_SIZE, **kwargs,
            )
    else:
        resp = report_service.report(
            db, report_key, tenant_id=tenant_id, workspace_id=workspace_id, **kwargs
        )
        columns = _columns_for(report_key, group_by, resp)
        rows = _rows_for(report_key, group_by, resp)
        writer.writerow([sanitize_cell(label) for _, label in columns])
        service.set_total(job, len(rows))
        for row in rows:
            writer.writerow([_cell(row, key, tz) for key, _ in columns])
            total_rows += 1
        service.advance(job, done=total_rows)

    if _aborted(db, job.id):
        return

    # Nit precedent from the contacts export (review round 1): a real BOM
    # byte constant, never a literal BOM character embedded in source.
    content = codecs.BOM_UTF8 + buf.getvalue().encode("utf-8")
    file_key = storage_for_tenant(db, tenant_id).save(
        f"exports/{job.id}/{report_key}.csv", content, "text/csv"
    )
    service.finish(
        job, status=JOB_DONE,
        result={"fileKey": file_key, "rowCount": total_rows, "columns": [label for _, label in columns]},
    )


_HANDLER_DEF = JobHandlerDef(REPORT_EXPORT_JOB_TYPE, run_report_export, "Report export")


def register_report_export_handler() -> None:
    """Idempotent - the SAME def object re-registers cleanly (mirrors
    `contact_export_service.register_contacts_export_handler`)."""
    register_job_handler(_HANDLER_DEF)
