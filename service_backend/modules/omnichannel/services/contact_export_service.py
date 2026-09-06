"""Contacts CSV export - a `background_jobs` job (plan 26 S3, D-A2-6a).

Keeps the shell's `exporter(query, columns, ids) => Promise<string>` contract
with ONE code path (`register_job_handler`, eager-inline in dev/test, real
Celery in prod). Streams the SAME filter/segment/sort query S1 shipped
(`ContactListService.query_for_export` - never `_decorate`, which pays for a
thread/message join per row this export doesn't need) in bounded batches,
writes ONE CSV to the tenant's active storage connection, and re-reads its own
job status at every batch checkpoint so a concurrent abort is honoured before
the terminal step (AC-CTM-40, mirrors `app/storage_migration/service.py`'s
`_aborted` pattern).
"""
from __future__ import annotations

import codecs
import csv
import io
import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.import_engine.sanitize import sanitize_cell
from app.jobs.registry import JobHandlerDef, register_job_handler
from app.jobs.service import JobService
from app.models.background_job import JOB_ABORTED, JOB_DONE, BackgroundJob
from app.models.status import Status as CoreStatus
from app.schemas.filters import FilterGroup
from app.services.storage import storage_for_tenant

from ..models import Contact
from ..schemas import EXPORT_COLUMN_IDS, ContactExportRequest
from .contact_field_service import ContactFieldService
from .contact_list_service import ContactListService
from .contact_tag_service import ContactTagService
from .conversation_service import ConversationService
from .lifecycle_service import ENTITY_TYPE as LIFECYCLE_ENTITY_TYPE

logger = logging.getLogger("foundryx.omnichannel.export")

EXPORT_JOB_TYPE = "omnichannel.contacts_export"
EXPORT_BATCH_SIZE = 500  # plan §5.4
EXPORT_MAX_ROWS = 50_000  # plan §5.4 "Cap rows (e.g. 50k)"

# id is ALWAYS first (AC-CTM-42 - export → edit → re-import(update) round-trips).
_ID_COLUMN = "id"

_COLUMN_LABELS: Dict[str, str] = {
    "id": "ID",
    "name": "Name",
    "firstName": "First name",
    "lastName": "Last name",
    "phone": "Phone",
    "email": "Email",
    "language": "Language",
    "countryCode": "Country",
    "lifecycle": "Lifecycle",
    "tags": "Tags",
    "assignee": "Assignee",
    "channel": "Channel",
    "lastMessageAt": "Last message",
    "createdAt": "Created",
}
assert set(_COLUMN_LABELS) == EXPORT_COLUMN_IDS  # ONE whitelist (`schemas.py`), never forked


class ExportRowCapExceeded(Exception):
    def __init__(self, count: int, cap: int):
        super().__init__(f"{count} rows exceeds the {cap}-row export cap.")
        self.count = count
        self.cap = cap


class UnknownExportColumn(Exception):
    """Finding 14 - a `customFields.<key>` column that passed the pydantic
    format check but isn't actually registered for THIS workspace (the
    key format is validated at the wire; the registered-key check needs DB
    + workspace context, so it lives here, not in the schema)."""

    def __init__(self, columns: List[str]):
        super().__init__(f"Unknown export column(s): {', '.join(columns)}.")
        self.columns = columns


def _validate_custom_field_columns(
    db: Session, tenant_id: str, workspace_id: str, columns: List[str]
) -> None:
    requested = {c for c in columns if c.startswith("customFields.")}
    if not requested:
        return
    registered = {
        f"customFields.{f.key}" for f in ContactFieldService(db).list(workspace_id, tenant_id)
    }
    unknown = sorted(c for c in requested if c not in registered)
    if unknown:
        raise UnknownExportColumn(unknown)


def create_export_job(
    db: Session, tenant_id: str, workspace_id: str, actor_user_id: Optional[str], req: ContactExportRequest
) -> BackgroundJob:
    """Fails FAST (422, before any job row exists) when the requested query
    exceeds `EXPORT_MAX_ROWS` - the plan's cap, applied synchronously so the
    caller gets an immediate, clear rejection rather than a job that runs for
    a while and then fails (AC-CTM-39's "clear message" choice)."""
    _validate_custom_field_columns(db, tenant_id, workspace_id, req.columns)
    list_service = ContactListService(db)
    query = list_service.query_for_export(
        tenant_id, workspace_id,
        ids=req.ids, search=req.search, filter_group=req.filter,
        segment_id=req.segment, sort_by=req.sortBy, sort_dir=req.sortDir or "desc",
    )
    count = query.count()
    if count > EXPORT_MAX_ROWS:
        raise ExportRowCapExceeded(count, EXPORT_MAX_ROWS)

    columns = [_ID_COLUMN] + [c for c in req.columns if c != _ID_COLUMN]
    payload = {
        "workspaceId": workspace_id,
        "columns": columns,
        "ids": req.ids,
        "search": req.search,
        "filter": req.filter.model_dump() if req.filter is not None else None,
        "segment": req.segment,
        "sortBy": req.sortBy,
        "sortDir": req.sortDir,
    }
    return JobService(db).create_and_enqueue(
        type=EXPORT_JOB_TYPE, tenant_id=tenant_id, actor_user_id=actor_user_id, payload=payload
    )


def _csv_value(value) -> str:
    """Spreadsheet-formula-injection-safe cell (Blocker 1) - `first_name`/
    `last_name` originate from inbound WhatsApp `profile_name`, attacker-
    controlled free text. Every cell we write goes through the SAME sanitizer
    the import engine uses on its own generated files (`phone` gets a leading
    `'` too; `_normalize_phone` on re-import strips non-digits so the quote
    round-trips clean, AC-CTM-42)."""
    return sanitize_cell(value)


def _lifecycle_labels(
    db: Session, contacts: List[Contact], tenant_id: str
) -> Dict[Tuple[str, str], str]:
    """Batched `(workspace_id, lifecycle_status_id) -> label`, tenant +
    entity-type + workspace(scope_id) scoped in ONE query (finding 4 - mirrors
    `conversation_service._lifecycle_map`'s polymorphic-stored-id guard: the
    lifecycle machine is scoped PER WORKSPACE, so a status id belonging to
    another workspace of the same tenant must never resolve here)."""
    pairs = {(c.workspace_id, c.lifecycle_status_id) for c in contacts if c.lifecycle_status_id}
    if not pairs:
        return {}
    status_ids = {sid for _, sid in pairs}
    rows = (
        db.query(CoreStatus)
        .filter(
            CoreStatus.id.in_(status_ids),
            CoreStatus.tenant_id == tenant_id,
            CoreStatus.entity_type == LIFECYCLE_ENTITY_TYPE,
        )
        .all()
    )
    by_id = {s.id: s for s in rows}
    result: Dict[Tuple[str, str], str] = {}
    for workspace_id, status_id in pairs:
        s = by_id.get(status_id)
        if s is None or s.scope_id != workspace_id:
            continue
        result[(workspace_id, status_id)] = s.label
    return result


def _column_value(
    contact: Contact,
    col: str,
    *,
    tags_by_contact: Dict[str, List[dict]],
    channels_by_contact: Dict[str, List[dict]],
    assignee_names: Dict[str, str],
    lifecycle_labels: Dict[Tuple[str, str], str],
) -> str:
    if col == "id":
        return contact.id
    if col == "name":
        return _csv_value(
            " ".join(p for p in (contact.first_name, contact.last_name) if p) or ""
        )
    if col == "firstName":
        return _csv_value(contact.first_name)
    if col == "lastName":
        return _csv_value(contact.last_name)
    if col == "phone":
        return _csv_value(contact.phone)
    if col == "email":
        return _csv_value(contact.email)
    if col == "language":
        return _csv_value(contact.language)
    if col == "countryCode":
        return _csv_value(contact.country_code)
    if col == "lifecycle":
        if not contact.lifecycle_status_id:
            return ""
        return _csv_value(
            lifecycle_labels.get((contact.workspace_id, contact.lifecycle_status_id), "")
        )
    if col == "tags":
        # `,` on BOTH sides of the export<->import round-trip (AC-CTM-42) -
        # the importer splits tags on `,` (`,`-delimited was the promoted
        # review finding; `csv.writer` quotes the joined cell so a literal
        # comma inside a tag name still round-trips).
        return _csv_value(",".join(t["name"] for t in tags_by_contact.get(contact.id, [])))
    if col == "assignee":
        return _csv_value(assignee_names.get(contact.assigned_user_id or "", ""))
    if col == "channel":
        return _csv_value("; ".join(c["name"] for c in channels_by_contact.get(contact.id, [])))
    if col == "lastMessageAt":
        return contact.last_message_at.isoformat().replace("+00:00", "Z") if contact.last_message_at else ""
    if col == "createdAt":
        return contact.created_at.isoformat().replace("+00:00", "Z") if contact.created_at else ""
    if col.startswith("customFields."):
        key = col.split(".", 1)[1]
        cf = contact.custom_fields_json or {}
        return _csv_value(cf.get(key))
    return ""  # unknown column id - never crash the export, just blank


def _aborted(db: Session, job_id: str) -> bool:
    """Re-read the job's status FRESH from the DB - a concurrent abort commits
    JOB_ABORTED on a different session (mirrors `app/storage_migration/
    service.py`'s own `_aborted` helper)."""
    return (
        db.query(BackgroundJob.status).filter(BackgroundJob.id == job_id).scalar() == JOB_ABORTED
    )


def run_contacts_export(db: Session, job: BackgroundJob) -> None:
    """`omnichannel.contacts_export` job handler (AC-CTM-39/40/42)."""
    service = JobService(db)
    payload = job.payload_json or {}
    tenant_id = job.tenant_id
    workspace_id = payload.get("workspaceId")
    columns: List[str] = payload.get("columns") or [_ID_COLUMN]
    filter_group = FilterGroup.model_validate(payload["filter"]) if payload.get("filter") else None

    list_service = ContactListService(db)
    query = list_service.query_for_export(
        tenant_id, workspace_id,
        ids=payload.get("ids"), search=payload.get("search"), filter_group=filter_group,
        segment_id=payload.get("segment"), sort_by=payload.get("sortBy"),
        sort_dir=payload.get("sortDir") or "desc",
    )
    total = query.count()
    service.set_total(job, total)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([sanitize_cell(_COLUMN_LABELS.get(c, c)) for c in columns])

    repo = list_service.repo
    tags_svc = ContactTagService(db)
    conv = ConversationService(db)

    offset = 0
    while offset < total:
        batch = query.offset(offset).limit(EXPORT_BATCH_SIZE).all()
        if not batch:
            break
        ids = [c.id for c in batch]
        tags_by_contact = tags_svc.refs_for_contacts(ids, tenant_id)
        channels_by_contact = repo.channels_for_contacts(ids, tenant_id)
        assignee_names = conv._user_names([c.assigned_user_id for c in batch], tenant_id)
        lifecycle_labels = _lifecycle_labels(db, batch, tenant_id)
        for c in batch:
            writer.writerow(
                [
                    _column_value(
                        c, col,
                        tags_by_contact=tags_by_contact,
                        channels_by_contact=channels_by_contact,
                        assignee_names=assignee_names,
                        lifecycle_labels=lifecycle_labels,
                    )
                    for col in columns
                ]
            )
        offset += len(batch)
        service.advance(job, done=len(batch))
        # Cooperative cancel (AC-CTM-40): re-read status FRESH before the next
        # batch/the terminal write. `advance()` already committed above, so an
        # abort committed on another session is visible here.
        if _aborted(db, job.id):
            logger.info("contacts export %s aborted mid-run at %s/%s rows", job.id, offset, total)
            return

    if _aborted(db, job.id):
        return

    # Nit 20 (review round 1): `codecs.BOM_UTF8` (a real byte constant), not a
    # literal BOM character embedded in the source string - the latter is
    # invisible in a diff/editor and some tools normalize/strip it on save.
    content = codecs.BOM_UTF8 + buf.getvalue().encode("utf-8")  # plan §5.4
    file_key = storage_for_tenant(db, tenant_id).save(
        f"exports/{job.id}/contacts.csv", content, "text/csv"
    )
    service.finish(
        job, status=JOB_DONE,
        result={"fileKey": file_key, "rowCount": total, "columns": columns, "bytes": len(content)},
    )


_HANDLER_DEF = JobHandlerDef(EXPORT_JOB_TYPE, run_contacts_export, "Contacts export")


def register_contacts_export_handler() -> None:
    """Idempotent - the SAME def object re-registers cleanly (mirrors the
    storage-migration handler's own boot registration)."""
    register_job_handler(_HANDLER_DEF)
