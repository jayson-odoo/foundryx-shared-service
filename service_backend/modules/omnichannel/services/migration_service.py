"""respond.io migration - S1 owns ``MigrationPreflightService`` (the
read-only preflight, AC-MIG-14). S2 adds ``MigrationService`` (phase
orchestration, cursor writes, cooperative abort, dry-run gate, mapping hash,
report assembly, plan §2.1) to this SAME file - kept together because S2's
service reuses this one's connection/workspace resolution helpers.
"""
import csv
import hashlib
import io
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from cryptography.fernet import InvalidToken
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.import_engine import readers as csv_readers
from app.import_engine.sanitize import sanitize_cell
from app.jobs.registry import JobHandlerDef, register_job_handler
from app.jobs.service import JobService
from app.models.background_job import (
    JOB_ABORTED,
    JOB_DONE,
    JOB_FAILED,
    JOB_NEEDS_REVIEW,
    JOB_PENDING,
    JOB_RUNNING,
    BackgroundJob,
)
from app.models.connection import Connection
from app.models.user import User
from app.schemas.filters import FilterCondition, FilterGroup, FilterRule
from app.secrets import decrypt_secret
from app.services.storage import storage_for_tenant
from app.status_engine.scoped import get_scope_status

from ..models import Channel, ConversationMessage
from ..models import Contact as ContactModel
from ..models import MigrationUpload
from ..repositories.migration_connection_repository import MigrationConnectionRepository
from ..repositories.migration_ref_repository import MigrationRefRepository
from ..repositories.migration_upload_repository import MigrationUploadRepository
from ..respondio.channel_map import target_channel_type_for
from ..respondio.client import RespondIoClient, RespondIoError
from ..respondio.shapes import Contact, CustomField, SpaceChannel, SpaceUser
from ..respondio.shapes import ContactChannel as SourceContactChannel
from ..respondio.shapes import MessageItem as SourceMessageItem
from ..schemas import (
    MigrationJobCreate,
    MigrationJobItem,
    MigrationJobListResponse,
    MigrationPreflight,
    MigrationSourceChannel,
    MigrationSourceField,
    MigrationSourceTeam,
    MigrationSourceUser,
    MigrationTargetChannel,
    MigrationTargetStage,
    MigrationUploadResult,
    WorkspaceItem,
)
from . import migration_media, team_directory
from .lifecycle_service import ENTITY_TYPE as LIFECYCLE_ENTITY_TYPE
from .lifecycle_service import initial_status_id, stages_for_workspace
from .migration_writer import (
    ENTITY_CONTACT,
    ENTITY_EVENT,
    ENTITY_MESSAGE,
    MigrationWriter,
    epoch_to_dt,
    resolve_message_timestamps,
)
from .statuses import status_id_for
from .workspace_service import WorkspaceNotFound, WorkspaceService

logger = logging.getLogger(__name__)

RESPONDIO_PROVIDER = "respondio"
MIGRATION_JOB_TYPE = "omnichannel.respondio_migration"
# 24h + mapping-hash gate (D-A6-14, AC-MIG-20) - a `run` needs a successful
# `dry_run` of the SAME mapping inside this window.
DRY_RUN_TTL_HOURS = 24
CONTACTS_PAGE_LIMIT = 100
MESSAGES_PAGE_LIMIT = 100
# S3's identities/messages phases checkpoint PER CONTACT (D-A6-9's timestamp
# interpolation needs a whole contact's message history bracketed together,
# so buffering per-contact is a deliberate deviation from the plan's
# suggested per-API-page granularity for THESE two phases only - the contacts
# phase above still checkpoints per respond.io page). This constant is only
# how many `migration_refs` rows are pulled per DB round-trip while walking
# that per-contact loop, not the checkpoint unit itself.
CONTACT_REF_BATCH = 25
# S4's media phase walks EVERY migrated-message ref (most carry no media at
# all) purely to check `payload_json.migration.pendingMedia`/media_key - a
# smaller batch than `CONTACT_REF_BATCH` because each row that DOES owe media
# costs a real network fetch, unlike the identities/messages phases' DB-only
# per-contact work.
MEDIA_REF_BATCH = 50
MAX_REPORT_SAMPLES = 10
# Review round 1, finding S11 - `_process_contact_messages` buffers a whole
# contact's message history in memory before any write (D-A6-9's bracketing
# genuinely needs that). A cap bounds the worst case (a runaway/malformed
# vendor thread, or a genuinely enormous single-contact history) to a fixed
# memory ceiling instead of an unbounded spike; the contact itself still
# migrates (its own row + prior pages already written are untouched) - only
# its messages are skipped, reported as a blocker, never an abort.
MAX_MESSAGES_PER_CONTACT = 20000
# S3/S4 originally bounded `background_jobs.result_json` size by truncating
# the failure list inline to this many rows; S5 moves the FULL set to
# storage (`_write_failures_csv`) and keeps only a 50-row `sample` inline
# instead, so this cap no longer applies - `failures_csv()` still reads a
# pre-S5/hand-built job's inline `rows` unbounded for backward compatibility.

# S5 (AC-MIG-46..49, D-A6-25) - the CSV fallback. respond.io's own Contacts
# module export caps at 2500 rows (plan §5.1 sources, F1) - a file at or over
# that count MAY be truncated, so it is a REPORTED blocker, never a limit we
# ourselves enforce (a customer with fewer than 2500 contacts never sees it).
CSV_CONTACTS_ROW_CAP = 2500
# respond.io's own contacts-IMPORT doc (plan §5.1 sources) states a 20 MB
# ceiling on its side; reused here as OUR ceiling too for the same class of
# file (a customer's own export), rather than inventing an unrelated number.
MIGRATION_UPLOAD_MAX_BYTES = 20 * 1024 * 1024
# Abort/checkpoint cadence for the CSV contacts phase (D-A6-25) - a CSV this
# small (capped in practice around CSV_CONTACTS_ROW_CAP) does not need a
# true resumable cursor (mirrors S4's own quick_replies-phase precedent, "a
# single bounded pass... no separate resumability is needed beyond re-running
# the same CSV, which write_contact's own migration_refs check already makes
# idempotent") - this constant only paces how often a cooperative abort is
# honoured mid-file, not a resume point.
CSV_CONTACTS_CHECKPOINT_BATCH = 100

# S6 (AC-MIG-02/56) - the job-history list's search/sort/filter run IN PYTHON
# over every one of the tenant's migration-type rows rather than a SQL
# WHERE/ORDER BY: `spaceLabel`/`workspaceName`/`mode` live inside
# `payload_json`, and a portable cross-dialect JSON-path clause (this suite
# runs on in-memory SQLite, production on Postgres) is not worth building for
# a list that is bounded by construction - `migration_in_progress` (AC-MIG-21)
# already forbids more than one non-terminal job per workspace, so a tenant's
# lifetime migration-job count stays small. This cap is a defensive ceiling,
# not an expected size.
MAX_LIST_SCAN_JOBS = 5000
# Fields the job-history list's Filter popover/column sort may address
# (`use-migration-list-config.tsx` `FILTER_FIELDS` + the sortable columns) -
# whitelisted exactly like `filter_translator.py`'s `ColumnMap`, just resolved
# against a plain per-row dict instead of a SQLAlchemy column.
_LIST_TEXT_FIELDS = ("spaceLabel", "workspaceName")
_LIST_SORT_FIELDS = ("spaceLabel", "workspaceName", "mode", "status", "createdAt", "startedAt", "finishedAt")

# A workspace with more contacts than this skips the rest of the preflight's
# distinct-lifecycle pass and reports a warning instead of walking the whole
# contact base on every "New migration" screen load - the pass is read-only
# and resumes no cursor of its own, so an unbounded walk here (unlike the real
# S2 contacts phase, which IS resumable) would make preflight itself the slow
# path on a two-year workspace. Far more than enough contacts to observe
# every DISTINCT lifecycle label a workspace actually uses in practice.
_MAX_LIFECYCLE_SCAN_CONTACTS = 2000


def _decrypt_or_none(ciphertext: str) -> Optional[Dict[str, str]]:
    if not ciphertext:
        return {}
    try:
        return decrypt_secret(ciphertext)
    except InvalidToken:
        return None


class MigrationPreflightService:
    def __init__(self, db: Session, *, client_factory=None):
        self.db = db
        self.connections = MigrationConnectionRepository(db)
        # Resolved at CALL time (never bound as a default-argument value,
        # which would capture the original classmethod at import time and
        # ignore a later `monkeypatch.setattr(migration_service,
        # "RespondIoClient", ...)`) - a test can swap the module-level
        # `RespondIoClient` name wholesale and this still picks it up.
        self._client_factory = client_factory or RespondIoClient.from_connection

    def preflight(self, tenant_id: str, connection_id: str, workspace_id: str) -> MigrationPreflight:
        connection = self._connection(tenant_id, connection_id)
        workspace = self._workspace(tenant_id, workspace_id)
        target_channels = self._target_channels(tenant_id, workspace.id)
        target_stages = self._target_stages(tenant_id, workspace.id)

        config = connection.config_json or {}
        space_label = str(config.get("spaceLabel") or "")
        warnings: List[str] = []

        credentials = _decrypt_or_none(connection.credentials_json)
        if credentials is None:
            warnings.append(
                "This connection's stored credentials can no longer be decrypted - "
                "re-enter the access token and save before running preflight again."
            )
            return self._unavailable(space_label, target_channels, target_stages, warnings)

        client = self._client_factory(config, credentials)

        try:
            raw_channels = client.list_space_channels()
        except RespondIoError as exc:
            warnings.append(self._api_unavailable_message(exc))
            return self._unavailable(space_label, target_channels, target_stages, warnings)

        channels = [
            MigrationSourceChannel(id=str(c.id), name=c.name, source=c.source)
            for c in (SpaceChannel(**row) for row in raw_channels)
        ]
        self._warn_no_compatible_target(channels, target_channels, warnings)

        try:
            raw_users = [SpaceUser(**row) for row in client.list_space_users()]
        except RespondIoError as exc:
            warnings.append(f"Could not read space users: {exc.message}")
            raw_users = []
        users = [
            MigrationSourceUser(
                id=str(u.id),
                firstName=u.firstName,
                lastName=u.lastName or "",
                email=u.email,
                role=u.role or "",
                teamId=str(u.team.id) if u.team else None,
                teamName=u.team.name if u.team else None,
            )
            for u in raw_users
        ]
        teams_by_id: Dict[str, MigrationSourceTeam] = {}
        for u in raw_users:
            if u.team is not None:
                teams_by_id.setdefault(str(u.team.id), MigrationSourceTeam(id=str(u.team.id), name=u.team.name))
        teams = sorted(teams_by_id.values(), key=lambda t: t.name.lower())

        try:
            raw_fields = [CustomField(**row) for row in client.list_custom_fields()]
        except RespondIoError as exc:
            warnings.append(f"Could not read custom fields: {exc.message}")
            raw_fields = []
        fields = [
            MigrationSourceField(id=str(f.id), name=f.name, dataType=f.dataType)
            for f in raw_fields
        ]

        lifecycles = self._distinct_lifecycles(client, config, warnings)

        return MigrationPreflight(
            apiAvailable=True,
            spaceLabel=space_label,
            channels=channels,
            users=users,
            teams=teams,
            fields=fields,
            lifecycles=lifecycles,
            targetChannels=target_channels,
            targetStages=target_stages,
            warnings=warnings,
        )

    # ── helpers ──────────────────────────────────────────────────────────

    def _connection(self, tenant_id: str, connection_id: str) -> Connection:
        connection = self.connections.get_for_provider(tenant_id, connection_id, RESPONDIO_PROVIDER)
        if connection is None:
            # Uniform 404 for a missing OR foreign-tenant id (AC-MIG-52) -
            # never distinguish "doesn't exist" from "isn't yours".
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found.")
        return connection

    def _workspace(self, tenant_id: str, workspace_id: str) -> WorkspaceItem:
        try:
            return WorkspaceService(self.db).get(workspace_id, tenant_id)
        except WorkspaceNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.") from exc

    def _target_channels(self, tenant_id: str, workspace_id: str) -> List[MigrationTargetChannel]:
        rows = (
            self.db.query(Channel)
            .filter(
                Channel.tenant_id == tenant_id,
                Channel.workspace_id == workspace_id,
                Channel.is_trashed.is_(False),
            )
            .order_by(Channel.name.asc())
            .all()
        )
        return [
            MigrationTargetChannel(id=c.id, name=c.name, channelType=c.channel_type)
            for c in rows
        ]

    def _target_stages(self, tenant_id: str, workspace_id: str) -> List[MigrationTargetStage]:
        return [
            MigrationTargetStage(statusId=s.id, label=s.label)
            for s in stages_for_workspace(self.db, tenant_id, workspace_id)
        ]

    def _unavailable(
        self,
        space_label: str,
        target_channels: List[MigrationTargetChannel],
        target_stages: List[MigrationTargetStage],
        warnings: List[str],
    ) -> MigrationPreflight:
        return MigrationPreflight(
            apiAvailable=False,
            spaceLabel=space_label,
            channels=[],
            users=[],
            teams=[],
            fields=[],
            lifecycles=[],
            targetChannels=target_channels,
            targetStages=target_stages,
            warnings=warnings,
        )

    @staticmethod
    def _api_unavailable_message(exc: RespondIoError) -> str:
        if exc.status_code == 401:
            return "respond.io rejected this access token."
        if exc.status_code == 403:
            return (
                "This workspace's respond.io plan does not include the Developer "
                "API (Growth plan or above required) - use the CSV import path instead."
            )
        return f"Could not reach respond.io ({exc.message})."

    @staticmethod
    def _warn_no_compatible_target(
        channels: List[MigrationSourceChannel],
        target_channels: List[MigrationTargetChannel],
        warnings: List[str],
    ) -> None:
        target_types = {c.channelType for c in target_channels}
        for c in channels:
            mapped = target_channel_type_for(c.source)
            if mapped is None or mapped not in target_types:
                warnings.append(
                    f'No connected channel in the target workspace matches source '
                    f'channel "{c.name}" ({c.source}) - it will be skipped.'
                )

    def _distinct_lifecycles(
        self, client: RespondIoClient, config: Dict[str, Any], warnings: List[str]
    ) -> List[str]:
        timezone = str(config.get("timezone") or "")
        seen: Dict[str, None] = {}
        try:
            for contact_index, row in enumerate(client.list_contacts(timezone=timezone)):
                if contact_index >= _MAX_LIFECYCLE_SCAN_CONTACTS:
                    warnings.append(
                        "Lifecycle preview stopped early after scanning the first "
                        f"{_MAX_LIFECYCLE_SCAN_CONTACTS} contacts - unmapped labels "
                        "found on a later contact are still allowed and reported as a "
                        "blocker on that contact's dry run."
                    )
                    break
                contact = Contact(**row)
                if contact.lifecycle:
                    seen.setdefault(contact.lifecycle, None)
        except RespondIoError as exc:
            warnings.append(f"Could not preview source lifecycle labels: {exc.message}")
            return []
        return sorted(seen.keys())


# ═══════════════════════════════════════════════════════════════════════════
# S5 - CSV fallback (AC-MIG-46..49, D-A6-18/25). `source="csv"` reads an
# uploaded respond.io Contacts export through the SAME core `read_rows` the
# rest of the platform's imports use (never a bespoke parser), maps it
# through an operator-chosen header map, and writes it via the SAME
# `MigrationWriter.write_contact` the API path uses - one writer, one set of
# merge rules, one `migration_refs` idempotency index, regardless of source.
#
# D-A6-25 (taken where the plan/UAC were ambiguous - see the commit body for
# the full reasoning): AC-MIG-46 hands CONTACTS to the EXISTING
# `ImporterDef("omnichannel_contacts")` wizard (zero new parsing code, no
# `migration_refs` row); THIS module ADDITIONALLY offers a parallel
# migration-writer-backed contacts ingestion for the CSV path, because only
# THIS path gives a CSV-sourced contact the SAME `migration_refs` idempotency
# an API-sourced contact gets (so re-uploading the same export never
# duplicates, and a later API-mode top-up run correctly recognises a
# CSV-migrated contact by its respond.io id). The two paths are not mutually
# exclusive; the setup form (S0/S6) still links to the wizard as the
# lower-friction default. Custom fields and tags are DELIBERATELY NOT
# automated here (D-A6-1/F1's own framing: CSV mode is contacts identity
# fields + snippets; fields/tags are the plan §7 prerequisite-6 screenshot
# path, or the separate wizard import, which already finds-or-creates them
# from a `cf_<fieldKey>` column) - `CsvSourceContact` below carries no
# `custom_fields`/`tags`/`assignee` at all, so `write_contact`'s own
# find-or-create/union logic simply never runs for them on this path.
CSV_HEADER_KEYS: Tuple[str, ...] = (
    "externalId", "firstName", "lastName", "phone", "email", "language", "countryCode", "lifecycle",
)

# Case-insensitive fallback guesses (plan §5.6's own column names) - the
# OPERATOR's `csvHeaderMap` always wins; this only fills in what they left
# unmapped, so a vendor header rename is still a mapping click, never a code
# change (plan §5.6's own stated invariant).
_HEADER_ALIASES: Dict[str, Tuple[str, ...]] = {
    "externalId": ("contact id", "id", "external id"),
    "firstName": ("first name", "firstname"),
    "lastName": ("last name", "lastname"),
    "phone": ("phone", "phone number"),
    "email": ("email", "email address"),
    "language": ("language",),
    "countryCode": ("country", "country code"),
    "lifecycle": ("lifecycle", "lifecycle stage"),
}


def _resolve_csv_header_map(
    headers: List[str], operator_map: Dict[str, str]
) -> Tuple[Dict[str, str], List[str]]:
    """``systemKey -> actualFileHeader`` for every key this path understands,
    resolved OPERATOR-choice-first then alias-guessed; returns the second
    list of file headers that matched NEITHER (AC-MIG-47's "unknown headers
    reported" - never silently dropped)."""
    header_by_lower = {h.strip().lower(): h for h in headers}
    resolved: Dict[str, str] = {}
    for key in CSV_HEADER_KEYS:
        choice = (operator_map or {}).get(key)
        if choice and choice in headers:
            resolved[key] = choice
            continue
        for alias in _HEADER_ALIASES.get(key, ()):
            if alias in header_by_lower:
                resolved[key] = header_by_lower[alias]
                break
    mapped_headers = set(resolved.values())
    unmapped = [h for h in headers if h not in mapped_headers]
    return resolved, unmapped


@dataclass
class CsvSourceContact:
    """Duck-types `respondio.shapes.Contact` closely enough for
    `MigrationWriter.write_contact` (a plain method - Python does not enforce
    the `SourceContact` type hint at the call site), WITHOUT reusing that
    pydantic model directly: `Contact.id` is a strict vendor `int`, and a
    CSV row's id is either the export's own string "Contact ID" column or a
    STABLE HASH of the row when that column is absent/blank (D-A6-25) -
    neither fits an `int` field. `custom_fields`/`tags`/`assignee`/`status`
    are left at their `None` defaults (see the module-docstring decision
    above) so `write_contact`'s field/tag/assignee logic no-ops for them."""

    id: str
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    language: Optional[str] = None
    countryCode: Optional[str] = None
    lifecycle: Optional[str] = None
    custom_fields: Optional[List[Dict[str, Any]]] = None
    tags: Optional[List[str]] = None
    assignee: Optional[Any] = None
    status: Optional[str] = None


def _stable_row_id(header_map: Dict[str, str], record: Dict[str, Any]) -> str:
    """A deterministic id over the MAPPED values only (never the raw record,
    whose extra/unmapped columns or key order would make an otherwise
    identical logical row hash differently run to run) - used ONLY when the
    file carries no "Contact ID"-mapped column (D-A6-25)."""
    basis = {k: record.get(v) for k, v in sorted(header_map.items()) if k != "externalId"}
    blob = json.dumps(basis, sort_keys=True, default=str)
    return "row:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _write_failures_csv(db: Session, tenant_id: str, job_id: str, failures: List[dict]) -> str:
    """Writes the FULL failure set to the tenant's active storage connection
    (D-A6-23/plan §2.1 "S5 owns the proper upload UX/contract" note extended
    to the failure export too) - `result_json` keeps only a small capped
    `sample` for the detail-page table (`MigrationService._to_item`), which
    is what bounds `background_jobs.result_json` size now instead of
    `MAX_FAILURE_ROWS_KEPT` truncating the SOURCE of truth. Always writes a
    file, even with zero failures (a header-only CSV), so a finished job's
    download route never has to special-case "no file yet"."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["entity", "sourceId", "sourceLabel", "reason", "action"])
    for r in failures:
        writer.writerow(
            [
                sanitize_cell(r.get("entity")),
                sanitize_cell(r.get("sourceId")),
                sanitize_cell(r.get("sourceLabel")),
                sanitize_cell(r.get("reason")),
                sanitize_cell(r.get("action")),
            ]
        )
    content = buf.getvalue().encode("utf-8")
    return storage_for_tenant(db, tenant_id).save(f"omnichannel/migration/{job_id}/failures.csv", content, "text/csv")


def _process_csv_contacts(
    db: Session,
    tenant_id: str,
    workspace_id: str,
    writer: MigrationWriter,
    payload: Dict[str, Any],
    contact_counts: Dict[str, int],
    field_counts: Dict[str, int],
    tag_counts: Dict[str, int],
    samples: List[dict],
    failures: List[dict],
    csv_blockers: List[str],
    csv_lifecycle_unmapped: Dict[str, int],
    *,
    dry_run: bool,
    service: JobService,
    job: BackgroundJob,
) -> None:
    """The `source="csv"` contacts phase (AC-MIG-47/48) - reads
    `payload["contactsCsvKey"]` through the SAME core reader/writer every
    other CSV path in this file uses, per-row SAVEPOINT + dry-run
    rollback/real-mode commit exactly mirroring the API contacts loop
    (`run_migration_job`'s own comment block documents why: D-A6-14, one
    code path for both modes). Mutates every collection it is given IN
    PLACE (mirrors `failures`/`samples` elsewhere in this module) rather than
    returning a new report - `csv_blockers` in particular must survive a
    crash-resume that picks the job back up in a LATER phase (persisted via
    `counts["csvBlockers"]` in the caller's `checkpoint()`)."""
    key = payload.get("contactsCsvKey")
    if not key:
        failures.append(
            {
                "entity": "contacts", "sourceId": "", "sourceLabel": "",
                "reason": "No contacts CSV was uploaded for this CSV-mode migration.",
                "action": "skipped",
            }
        )
        return
    try:
        content, _mime = storage_for_tenant(db, tenant_id).fetch(key)
    except Exception as exc:  # noqa: BLE001 - storage gone/misconfigured, never abort the job
        failures.append(
            {
                "entity": "contacts", "sourceId": "", "sourceLabel": "",
                "reason": f"Could not read the uploaded contacts CSV: {exc}", "action": "skipped",
            }
        )
        return

    fmt = csv_readers.sniff_format(content)
    if fmt is None:
        failures.append(
            {
                "entity": "contacts", "sourceId": "", "sourceLabel": "",
                "reason": "Unsupported file format for the contacts CSV.", "action": "skipped",
            }
        )
        return

    headers, records = csv_readers.read_rows(content, fmt, None, settings.import_max_rows)
    row_count = len(records)
    if row_count >= CSV_CONTACTS_ROW_CAP:
        csv_blockers.append(
            f"This contacts file has {row_count} rows, at or over respond.io's own "
            f"{CSV_CONTACTS_ROW_CAP}-row Contacts-module export cap - it may be truncated. "
            "Re-export in narrower batches if this workspace has more contacts than that."
        )

    header_map, unmapped_headers = _resolve_csv_header_map(headers, payload.get("csvHeaderMap") or {})
    if unmapped_headers:
        csv_blockers.append(
            "Unmapped CSV column(s), values not imported: " + ", ".join(unmapped_headers)
        )

    for i, record in enumerate(records):
        external_id = None
        ext_header = header_map.get("externalId")
        if ext_header:
            external_id = str(record.get(ext_header) or "").strip() or None
        if not external_id:
            external_id = _stable_row_id(header_map, record)

        def _val(system_key: str) -> Optional[str]:
            header = header_map.get(system_key)
            if not header:
                return None
            raw = record.get(header)
            text = str(raw).strip() if raw is not None else ""
            return text or None

        country_code = _val("countryCode")
        source = CsvSourceContact(
            id=external_id,
            firstName=_val("firstName"),
            lastName=_val("lastName"),
            phone=_val("phone"),
            email=_val("email"),
            language=_val("language"),
            countryCode=country_code.upper() if country_code else None,
            lifecycle=_val("lifecycle"),
        )

        nested = db.begin_nested()
        try:
            outcome = writer.write_contact(source)
        except Exception as exc:  # noqa: BLE001 - per-row isolation (AC-MIG-29's own pattern)
            nested.rollback()
            contact_counts["fetched"] += 1
            contact_counts["errors"] = contact_counts.get("errors", 0) + 1
            failures.append(
                {
                    "entity": "contacts", "sourceId": external_id, "sourceLabel": "",
                    "reason": str(exc), "action": "skipped",
                }
            )
        else:
            if dry_run:
                nested.rollback()  # D-A6-14: zero rows written anywhere
            else:
                nested.commit()
            contact_counts["fetched"] += 1
            contact_counts[outcome.kind] = contact_counts.get(outcome.kind, 0) + 1
            field_counts["fetched"] = field_counts.get("fetched", 0) + outcome.fields_created + outcome.fields_matched
            field_counts["create"] = field_counts.get("create", 0) + outcome.fields_created
            field_counts["matched"] = field_counts.get("matched", 0) + outcome.fields_matched
            field_counts["errors"] = field_counts.get("errors", 0) + outcome.field_errors
            tag_counts["fetched"] = tag_counts.get("fetched", 0) + outcome.tags_created + outcome.tags_matched
            tag_counts["create"] = tag_counts.get("create", 0) + outcome.tags_created
            tag_counts["matched"] = tag_counts.get("matched", 0) + outcome.tags_matched
            if outcome.lifecycle_unmapped:
                # Defect 2 fix - the SEPARATE CSV-mode contacts loop used to
                # never check `outcome.lifecycle_unmapped` at all (only the
                # API-mode loop did, below), so an unresolvable CSV Lifecycle
                # value silently landed on the initial stage with zero
                # operator-visible signal. Tallied by the RAW value so the
                # report can name it, not just a bare count.
                label = source.lifecycle or ""
                csv_lifecycle_unmapped[label] = csv_lifecycle_unmapped.get(label, 0) + 1
            if len(samples) < MAX_REPORT_SAMPLES:
                samples.append({"name": outcome.source_label, "action": outcome.kind})

        service.advance(job, done=1)
        if (i + 1) % CSV_CONTACTS_CHECKPOINT_BATCH == 0 and _aborted(db, job.id):
            # Cooperative abort mid-file (AC-MIG-28's own rule, extended to
            # CSV mode) - the caller's own checkpoint/abort-check right after
            # this function returns catches anything past the last checked
            # row; migration_refs makes a later re-run pick up cleanly either
            # way (D-A6-25's own "no true resume cursor needed" note above).
            return


# ═══════════════════════════════════════════════════════════════════════════
# S2 - MigrationService (job create/list/get/cancel, phase orchestration,
# cooperative abort, dry-run gate, mapping hash, report assembly)
# ═══════════════════════════════════════════════════════════════════════════


class MigrationJobValidationError(Exception):
    """Carries a `{field: message}` map - the router turns this into a 422
    `{fieldErrors}` body (the `ContactCreateError` convention, plan 26)."""

    def __init__(self, errors: Dict[str, str]):
        super().__init__("Migration job validation failed")
        self.errors = errors


class MigrationJobConflict(Exception):
    """Carries a machine-readable `reason` - the router turns this into a 409
    `{reason}` body (AC-MIG-20/21's `dry_run_required` / `migration_in_progress`
    / `not_in_progress`)."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def _mapping_hash(payload: MigrationJobCreate) -> str:
    """Deterministic hash over the fields that define "the exact mapping"
    (D-A6-14/AC-MIG-07/20) - `mode` is deliberately excluded so a `dry_run`
    and its matching `run` share one hash (mirrors the frontend's own
    `computeMappingHash`, `types/respondio-migration.ts` - the two do NOT need
    to agree bit-for-bit since the frontend never sends its hash to the
    backend; this is a purely server-side gate)."""
    canonical = {
        "connectionId": payload.connectionId,
        "workspaceId": payload.workspaceId,
        "channelMap": sorted(
            ([e.sourceChannelId, e.targetChannelId] for e in payload.channelMap),
            key=lambda pair: pair[0],
        ),
        "userMap": sorted(
            ([e.sourceUserId, e.targetUserId] for e in payload.userMap), key=lambda pair: pair[0]
        ),
        "teamMap": sorted(
            ([e.sourceTeamId, e.targetTeamId] for e in payload.teamMap), key=lambda pair: pair[0]
        ),
        "lifecycleMap": sorted(
            ([e.sourceLabel, e.targetStatusId] for e in payload.lifecycleMap),
            key=lambda pair: pair[0],
        ),
        "contactsOnly": bool(payload.contactsOnly),
        "messagesSince": payload.messagesSince or None,
        # S5 (D-A6-25) - a differently-uploaded contacts CSV or a changed
        # header map IS a different mapping for CSV mode (mirrors channelMap/
        # userMap above); `snippetsUploadId` stays EXCLUDED (S4's own
        # rationale, unchanged: quick replies are independent of "the
        # mapping"). Hashes the WIRE id (review round 1, finding B2), not the
        # resolved storage key - a fresh upload of byte-identical content
        # already mints a new id/key pair either way, so this is equivalent
        # and never resolves an upload just to hash it.
        "contactsUploadId": payload.contactsUploadId or None,
        "csvHeaderMap": sorted((payload.csvHeaderMap or {}).items()),
    }
    blob = json.dumps(canonical, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _zero_counts() -> Dict[str, int]:
    return {"fetched": 0, "wouldCreate": 0, "wouldUpdate": 0, "wouldSkip": 0, "errors": 0}


def _build_report(
    counts: Dict[str, Any],
    samples: List[dict],
    lifecycle_unmapped: int,
    *,
    messages_with_inferred: int = 0,
    message_samples: Optional[List[dict]] = None,
    messages_skipped_before_floor: int = 0,
    messages_skipped_over_cap: int = 0,
    user_map_dropped: int = 0,
    team_map_dropped: int = 0,
    lifecycle_unmapped_csv: Optional[Dict[str, int]] = None,
    pagination_blockers: Optional[List[str]] = None,
) -> dict:
    contacts_c = counts.get("contacts") or {}
    fields_c = counts.get("fields") or {}
    tags_c = counts.get("tags") or {}
    identities_c = counts.get("identities") or {}
    messages_c = counts.get("messages") or {}
    media_c = counts.get("media") or {}
    events_c = counts.get("events") or {}
    quick_replies_c = counts.get("quickReplies") or {}
    # Review round 2, R1 - the pagination-guard blockers come FIRST: they
    # mean the walk stopped before it finished, which is more consequential
    # than "N contacts have no lifecycle mapping" and the like below.
    blockers: List[str] = list(pagination_blockers or [])
    if lifecycle_unmapped_csv:
        # Defect 2 fix - CSV mode names the actual unmapped VALUE(s) and
        # their count, rather than the API-mode aggregate-only line below
        # (a CSV job never populates the scalar `lifecycle_unmapped` counter
        # at all, so this branch and the `elif` below are mutually exclusive
        # in practice, not just in wording).
        for label, count in sorted(lifecycle_unmapped_csv.items()):
            display = label or "(blank)"
            blockers.append(
                f'{count} contact(s) had a CSV Lifecycle value of "{display}" that does not '
                "match a mapped value or an existing stage in this workspace - landed on the "
                "initial stage instead."
            )
    elif lifecycle_unmapped:
        blockers.append(
            f"{lifecycle_unmapped} contact(s) have no lifecycle mapping and will land "
            "with no lifecycle stage."
        )
    if messages_skipped_over_cap:
        # S11 (review round 1) - contacts whose whole message history
        # exceeded `MAX_MESSAGES_PER_CONTACT` and were skipped entirely
        # (never partially written, never fabricated).
        blockers.append(
            f"{messages_skipped_over_cap} contact(s) had more messages than this migration "
            "tool will buffer for one contact - their message history was skipped."
        )
    # S4 (review round 1) - an agent/team target that validated at CREATE
    # time but no longer validates at USE time (deleted between create and
    # run) used to drop silently; now reported so the operator learns their
    # mapping did not fully apply.
    if user_map_dropped:
        blockers.append(
            f"{user_map_dropped} agent mapping(s) no longer resolve to a valid user "
            "and were skipped."
        )
    if team_map_dropped:
        blockers.append(
            f"{team_map_dropped} team mapping(s) no longer resolve to a valid team "
            "and were skipped."
        )
    return {
        "entities": {
            "contacts": {
                "fetched": contacts_c.get("fetched", 0),
                "wouldCreate": contacts_c.get("create", 0),
                "wouldUpdate": contacts_c.get("update", 0),
                "wouldSkip": 0,
                "errors": contacts_c.get("errors", 0),
            },
            "fields": {
                "fetched": fields_c.get("fetched", 0),
                "wouldCreate": fields_c.get("create", 0),
                "wouldUpdate": 0,
                "wouldSkip": fields_c.get("matched", 0),
                "errors": fields_c.get("errors", 0),
            },
            "tags": {
                "fetched": tags_c.get("fetched", 0),
                "wouldCreate": tags_c.get("create", 0),
                "wouldUpdate": 0,
                "wouldSkip": tags_c.get("matched", 0),
                "errors": 0,
            },
            # S3 - real counts when the identities/messages phases ran this
            # job (contactsOnly=False); genuinely zero for a contacts-only run
            # (S2's own shape, never walked).
            "identities": {
                "fetched": identities_c.get("fetched", 0),
                "wouldCreate": identities_c.get("create", 0),
                "wouldUpdate": identities_c.get("update", 0),
                "wouldSkip": identities_c.get("skip", 0),
                "errors": identities_c.get("errors", 0),
            },
            "messages": {
                "fetched": messages_c.get("fetched", 0),
                "wouldCreate": messages_c.get("create", 0),
                "wouldUpdate": 0,
                "wouldSkip": messages_c.get("skip", 0),
                "errors": messages_c.get("errors", 0),
            },
            # S4 phases (AC-MIG-39..45) - genuinely zero for a dry run or a
            # contactsOnly run (neither ever reaches these phases, mirroring
            # S3's own identities/messages honesty note above); real counts
            # once the media/events/quickReplies phases actually walk.
            "media": {
                "fetched": media_c.get("fetched", 0),
                "wouldCreate": media_c.get("create", 0),
                "wouldUpdate": 0,
                "wouldSkip": media_c.get("skip", 0),
                "errors": media_c.get("errors", 0),
            },
            "events": {
                "fetched": events_c.get("fetched", 0),
                "wouldCreate": events_c.get("create", 0),
                "wouldUpdate": 0,
                "wouldSkip": events_c.get("skip", 0),
                "errors": events_c.get("errors", 0),
            },
            "quickReplies": {
                "fetched": quick_replies_c.get("fetched", 0),
                "wouldCreate": quick_replies_c.get("create", 0),
                "wouldUpdate": quick_replies_c.get("update", 0),
                "wouldSkip": quick_replies_c.get("skip", 0),
                "errors": quick_replies_c.get("errors", 0),
            },
        },
        "messagesWithInferredTimestamp": messages_with_inferred,
        "messagesSkippedBeforeFloor": messages_skipped_before_floor,
        "messagesSkippedOverCap": messages_skipped_over_cap,
        "lifecycleUnmappedByValue": lifecycle_unmapped_csv or {},
        "blockers": blockers,
        "samples": {"contacts": samples, "messages": message_samples or []},
    }


def _resolve_channel_map(
    db: Session, tenant_id: str, workspace_id: str, payload: Dict[str, Any]
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """``sourceChannelId(str) -> targetChannelId(str)``, re-validated tenant +
    workspace scoped AT USE TIME (AC-MIG-51) - a channel deleted or moved
    between save and run silently drops out of the map rather than crashing
    the run. Also returns ``targetChannelId -> channel_type`` - the identity
    deriver (D-A6-10) keys off the TARGET's real, current type, not whatever
    the source declared at setup time."""
    target_ids = {
        str(entry.get("targetChannelId"))
        for entry in payload.get("channelMap") or []
        if entry.get("targetChannelId")
    }
    channel_type_by_target: Dict[str, str] = {}
    if target_ids:
        rows = (
            db.query(Channel.id, Channel.channel_type)
            .filter(
                Channel.tenant_id == tenant_id,
                Channel.workspace_id == workspace_id,
                Channel.id.in_(target_ids),
                Channel.is_trashed.is_(False),
            )
            .all()
        )
        channel_type_by_target = {r[0]: r[1] for r in rows}
    channel_map: Dict[str, str] = {}
    for entry in payload.get("channelMap") or []:
        source_id = str(entry.get("sourceChannelId") or "")
        target_id = entry.get("targetChannelId")
        if source_id and target_id and target_id in channel_type_by_target:
            channel_map[source_id] = target_id
    return channel_map, channel_type_by_target


def _resolve_user_map(db: Session, tenant_id: str, payload: Dict[str, Any]) -> Tuple[Dict[str, str], int]:
    """``sourceUserId(str) -> targetUserId(str)``, re-validated tenant-scoped
    at USE time (AC-MIG-51/32) - consumed ONLY by the messages phase's sender
    mapping; the contacts phase's assignee resolution is email-only and never
    touches this map (D-A6-26). Returns the number of mapped entries DROPPED
    because their target no longer validates (review round 1, finding S4) -
    `_validate_mapping` already rejects a foreign/unknown target at CREATE
    time, so a drop HERE only happens when the target was deleted between
    create and run; the caller reports it as a report blocker rather than
    silently discarding the operator's mapping choice."""
    target_ids = {
        str(entry.get("targetUserId")) for entry in payload.get("userMap") or [] if entry.get("targetUserId")
    }
    valid_ids: set = set()
    if target_ids:
        valid_ids = {
            r[0] for r in db.query(User.id).filter(User.tenant_id == tenant_id, User.id.in_(target_ids)).all()
        }
    user_map: Dict[str, str] = {}
    dropped = 0
    for entry in payload.get("userMap") or []:
        source_id = str(entry.get("sourceUserId") or "")
        target_id = entry.get("targetUserId")
        if not source_id or not target_id:
            continue
        if target_id in valid_ids:
            user_map[source_id] = target_id
        else:
            dropped += 1
    return user_map, dropped


def _resolve_team_map(db: Session, tenant_id: str, payload: Dict[str, Any]) -> Tuple[Dict[str, str], int]:
    """``sourceTeamId(str) -> targetTeamId(str)``, re-validated tenant-scoped
    at USE time (mirrors `_resolve_user_map` exactly) via the `team_directory`
    soft-ref gateway - core teams live outside this module's schema (D-A8-3),
    never a raw cross-schema query. Consumed by `MigrationWriter.write_contact`
    to set `assigned_team_id` from the mapped source team of the contact's
    ASSIGNEE (plan 33 review round 1, finding S5 - A8/`Contact.
    assigned_team_id` merged to `main` after this slice was originally cut)."""
    team_map: Dict[str, str] = {}
    dropped = 0
    for entry in payload.get("teamMap") or []:
        source_id = str(entry.get("sourceTeamId") or "")
        target_id = entry.get("targetTeamId")
        if not source_id or not target_id:
            continue
        if team_directory.validate_assignable(db, tenant_id, target_id):
            team_map[source_id] = target_id
        else:
            dropped += 1
    return team_map, dropped


def _aborted(db: Session, job_id: str) -> bool:
    """Re-read the job's status FRESH from the DB - a concurrent cancel
    commits `aborted` on a DIFFERENT session (mirrors `contact_export_
    service._aborted` / `app/storage_migration/service.py`'s own helper)."""
    return db.query(BackgroundJob.status).filter(BackgroundJob.id == job_id).scalar() == JOB_ABORTED


def _list_row_fields(job: BackgroundJob) -> Dict[str, Any]:
    """The subset of a job's fields the S6 list search/sort/filter can
    address - `spaceLabel`/`workspaceName`/`mode` come from `payload_json`
    (there is no native column for them), the rest are native `BackgroundJob`
    columns."""
    payload = job.payload_json or {}
    return {
        "spaceLabel": str(payload.get("spaceLabel") or ""),
        "workspaceName": str(payload.get("workspaceName") or ""),
        "mode": str(payload.get("mode") or ""),
        "status": job.status,
        "createdAt": job.created_at,
        "startedAt": job.started_at,
        "finishedAt": job.finished_at,
    }


def _parse_filter_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        raw = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _filter_condition_matches(cond: FilterCondition, values: Dict[str, Any]) -> bool:
    """Evaluates ONE whitelisted leaf against a job's `_list_row_fields()`
    dict - the in-memory sibling of `app/services/filter_translator.py`'s SQL
    clause builder, used here because `spaceLabel`/`workspaceName`/`mode` have
    no native column to build a portable (SQLite-testable, Postgres-real)
    clause over (see `MAX_LIST_SCAN_JOBS`'s own comment). An unwhitelisted
    field or an unknown operator matches everything (never 500s a list read
    over a stray query param)."""
    if cond.field not in _LIST_SORT_FIELDS:
        return True
    value = values.get(cond.field)
    op = cond.operator
    if cond.field in _LIST_TEXT_FIELDS:
        if op == "contains":
            return str(cond.value or "").lower() in str(value or "").lower()
        if op == "eq":
            return str(value or "") == str(cond.value or "")
        if op == "neq":
            return str(value or "") != str(cond.value or "")
        return True
    if cond.field == "mode" or cond.field == "status":
        if op == "eq":
            return value == cond.value
        if op == "neq":
            return value != cond.value
        if op == "in":
            options = cond.value if isinstance(cond.value, list) else [cond.value]
            return value in options
        return True
    # createdAt / startedAt / finishedAt - date comparisons.
    if not isinstance(value, datetime):
        return op not in ("before", "after", "between")
    if op == "before":
        parsed = _parse_filter_datetime(cond.value)
        return parsed is not None and value < parsed
    if op == "after":
        parsed = _parse_filter_datetime(cond.value)
        return parsed is not None and value > parsed
    if op == "between" and isinstance(cond.value, list) and len(cond.value) >= 2:
        lo, hi = _parse_filter_datetime(cond.value[0]), _parse_filter_datetime(cond.value[1])
        return lo is not None and hi is not None and lo <= value <= hi
    return True


def _filter_rule_matches(rule: FilterRule, values: Dict[str, Any]) -> bool:
    if rule.kind == "group":
        if not rule.rules:
            return True
        results = [_filter_rule_matches(r, values) for r in rule.rules]
        return all(results) if rule.combinator == "and" else any(results)
    return _filter_condition_matches(rule, values)


def _parse_list_filter(filter_raw: Optional[str]) -> Optional[FilterGroup]:
    """A malformed/foreign filter payload is ignored (falls back to
    "unfiltered") rather than 422ing a plain list read - this list has no
    save-time contract to protect (unlike a saved broadcast audience filter,
    plan 29 D-4)."""
    if not filter_raw:
        return None
    try:
        return FilterGroup.model_validate_json(filter_raw)
    except Exception:  # noqa: BLE001 - defensive, never break the list read
        return None


class MigrationService:
    def __init__(self, db: Session):
        self.db = db
        self.jobs = JobService(db)

    # ── resolution helpers (tenant-scoped, uniform 404 - AC-MIG-51/52) ──────

    def _require_connection(self, tenant_id: str, connection_id: str) -> Connection:
        connection = MigrationConnectionRepository(self.db).get_for_provider(
            tenant_id, connection_id, RESPONDIO_PROVIDER
        )
        if connection is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found.")
        return connection

    def _require_workspace(self, tenant_id: str, workspace_id: str) -> WorkspaceItem:
        try:
            return WorkspaceService(self.db).get(workspace_id, tenant_id)
        except WorkspaceNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.") from exc

    def _require_upload(self, tenant_id: str, upload_id: str, kind: str) -> MigrationUpload:
        """Review round 1, finding B2 - resolves a `contactsUploadId`/
        `snippetsUploadId` tenant-scoped, mirroring `_require_connection`/
        `_require_workspace` exactly: a foreign, unknown OR wrong-`kind`
        (e.g. a snippets receipt supplied as `contactsUploadId`) id all read
        back as the SAME uniform 404, never distinguishing "doesn't exist"
        from "isn't yours" or "is the wrong kind"."""
        upload = MigrationUploadRepository(self.db).get_for_tenant(tenant_id, upload_id, kind=kind)
        if upload is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Uploaded file not found.")
        return upload

    def _require_job(self, tenant_id: str, job_id: str) -> BackgroundJob:
        job = self.jobs.get(tenant_id, job_id)
        # Type-scoped too (never a bare tenant+id match) - a DIFFERENT job
        # type belonging to this same tenant (e.g. `omnichannel.contacts_
        # export`) must read back as a plain 404 here, identically to a
        # missing id (the core `/jobs/{id}` route is generic; this route is
        # migration-specific and must not leak a foreign job's existence).
        if job is None or job.type != MIGRATION_JOB_TYPE:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Migration job not found.")
        return job

    # ── create (AC-MIG-19..21) ───────────────────────────────────────────────

    def _validate_mapping(
        self, tenant_id: str, workspace_id: str, payload: MigrationJobCreate
    ) -> Tuple[Dict[str, str], Optional[str]]:
        """Returns `(errors, parsed_messages_since)` - `messagesSince` is
        parsed here (not by pydantic) so a malformed value lands in the SAME
        house `{fieldErrors}` map as every other create-time check, never
        FastAPI's own un-housed pydantic-datetime 422 shape."""
        errors: Dict[str, str] = {}

        target_channel_ids = {e.targetChannelId for e in payload.channelMap if e.targetChannelId}
        if target_channel_ids:
            found = {
                r[0]
                for r in self.db.query(Channel.id)
                .filter(
                    Channel.tenant_id == tenant_id,
                    Channel.workspace_id == workspace_id,
                    Channel.id.in_(target_channel_ids),
                    Channel.is_trashed.is_(False),
                )
                .all()
            }
            for i, entry in enumerate(payload.channelMap):
                if entry.targetChannelId and entry.targetChannelId not in found:
                    errors[f"channelMap.{i}"] = (
                        "This target channel does not belong to the selected workspace."
                    )

        target_status_ids = {e.targetStatusId for e in payload.lifecycleMap if e.targetStatusId}
        if target_status_ids:
            valid_status_ids = {
                sid
                for sid in target_status_ids
                if get_scope_status(self.db, LIFECYCLE_ENTITY_TYPE, tenant_id, workspace_id, sid)
                is not None
            }
            for i, entry in enumerate(payload.lifecycleMap):
                if entry.targetStatusId and entry.targetStatusId not in valid_status_ids:
                    errors[f"lifecycleMap.{i}"] = (
                        "This lifecycle stage does not belong to the selected workspace."
                    )

        # S4 (review round 1) - `userMap`/`teamMap` targets used to be
        # accepted with no save-time check at all, then silently dropped at
        # USE time (`_resolve_user_map`/`_resolve_team_map`'s own tenant
        # re-validation) - an operator never learned their mapping did not
        # apply. Tenant-scoped here too (AC-MIG-51's use-time check stays as
        # the second gate for an id deleted between create and run).
        target_user_ids = {e.targetUserId for e in payload.userMap if e.targetUserId}
        if target_user_ids:
            valid_user_ids = {
                r[0]
                for r in self.db.query(User.id)
                .filter(User.tenant_id == tenant_id, User.id.in_(target_user_ids))
                .all()
            }
            for i, entry in enumerate(payload.userMap):
                if entry.targetUserId and entry.targetUserId not in valid_user_ids:
                    errors[f"userMap.{i}"] = "This target user does not belong to this tenant."

        # Core teams live outside this module's schema - resolved through the
        # `team_directory` soft-ref gateway (D-A8-3), never a raw cross-schema
        # query (mirrors `write_contact`'s own assignee/team conventions).
        for i, entry in enumerate(payload.teamMap):
            if entry.targetTeamId and not team_directory.validate_assignable(
                self.db, tenant_id, entry.targetTeamId
            ):
                errors[f"teamMap.{i}"] = "This target team does not belong to this tenant."

        parsed_messages_since: Optional[str] = None
        if payload.messagesSince:
            try:
                raw = payload.messagesSince.replace("Z", "+00:00")
                parsed_messages_since = datetime.fromisoformat(raw).astimezone(timezone.utc).isoformat()
            except ValueError:
                errors["messagesSince"] = "messagesSince must be an ISO-8601 date/time."

        # S5 (AC-MIG-47) - a CSV-mode job needs an uploaded contacts file;
        # never discovered only once the job is already running.
        if payload.source == "csv" and not payload.contactsUploadId:
            errors["contactsUploadId"] = "Upload a contacts CSV before running a CSV-mode migration."

        return errors, parsed_messages_since

    def _in_progress_job(self, tenant_id: str, workspace_id: str) -> Optional[BackgroundJob]:
        for job in self.jobs.repo.active_of_type(
            tenant_id, MIGRATION_JOB_TYPE, (JOB_PENDING, JOB_RUNNING, JOB_NEEDS_REVIEW)
        ):
            if (job.payload_json or {}).get("workspaceId") == workspace_id:
                return job
        return None

    def _has_fresh_dry_run(self, tenant_id: str, workspace_id: str, mapping_hash: str) -> bool:
        """S10 (review round 1) - the ORIGINAL implementation loaded EVERY
        `DONE` migration job for the tenant with no `finished_at` filter and
        no `.limit()`, on the create-path (unlike `list_jobs`, which at least
        caps its own scan at `MAX_LIST_SCAN_JOBS`). `workspaceId`/`mode` live
        inside `payload_json` (no native column, same reason `list_jobs`'
        own search/sort stays in Python - see `MAX_LIST_SCAN_JOBS`'s own
        comment) so they still filter in Python, but `finished_at >= cutoff`
        DOES have a native column and now runs in SQL, and `.limit(1)` stops
        the scan the instant a match is found rather than always walking the
        tenant's full history."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=DRY_RUN_TTL_HOURS)
        q = (
            self.db.query(BackgroundJob)
            .filter(
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.type == MIGRATION_JOB_TYPE,
                BackgroundJob.status == JOB_DONE,
                BackgroundJob.finished_at >= cutoff,
            )
            .order_by(BackgroundJob.finished_at.desc())
        )
        for job in q.yield_per(50):
            p = job.payload_json or {}
            if p.get("mode") == "dry_run" and p.get("workspaceId") == workspace_id and p.get("mappingHash") == mapping_hash:
                return True
        return False

    def create_job(
        self, tenant_id: str, actor_user_id: Optional[str], payload: MigrationJobCreate
    ) -> MigrationJobItem:
        # S5 (D-A6-25) - `connectionId` is required for an API-mode job (the
        # only source of a client/token) but OPTIONAL for CSV mode, where a
        # customer with zero API access may never have created a connection
        # row at all. When one IS supplied (even in CSV mode, purely to carry
        # `spaceLabel` for display), it is still resolved tenant-scoped
        # (AC-MIG-51/52) - never a bare lookup either way.
        connection: Optional[Connection] = None
        space_label = ""
        if payload.connectionId:
            connection = self._require_connection(tenant_id, payload.connectionId)
            space_label = str((connection.config_json or {}).get("spaceLabel") or "")
        elif payload.source == "api":
            raise MigrationJobValidationError(
                {"connectionId": "A respond.io connection is required for an API-mode migration."}
            )
        workspace = self._require_workspace(tenant_id, payload.workspaceId)

        # Review round 1, finding B2 - `contactsUploadId`/`snippetsUploadId`
        # resolve tenant-scoped to their RECEIPT row (never a client-supplied
        # storage key); a foreign/unknown/wrong-kind id 404s here, before any
        # mapping validation runs. The RESOLVED storage key is what actually
        # lands in `job_payload` below - the phase-processing code keeps
        # reading it off the SAME internal `contactsCsvKey`/`snippetsCsvKey`
        # names it always has.
        contacts_storage_key: Optional[str] = None
        if payload.contactsUploadId:
            contacts_storage_key = self._require_upload(
                tenant_id, payload.contactsUploadId, "contacts"
            ).storage_key
        snippets_storage_key: Optional[str] = None
        if payload.snippetsUploadId:
            snippets_storage_key = self._require_upload(
                tenant_id, payload.snippetsUploadId, "snippets"
            ).storage_key

        errors, parsed_messages_since = self._validate_mapping(tenant_id, payload.workspaceId, payload)
        if errors:
            raise MigrationJobValidationError(errors)

        if self._in_progress_job(tenant_id, payload.workspaceId) is not None:
            raise MigrationJobConflict(
                "migration_in_progress", "A migration is already running for this workspace."
            )

        mapping_hash = _mapping_hash(payload)
        if payload.mode == "run" and not self._has_fresh_dry_run(
            tenant_id, payload.workspaceId, mapping_hash
        ):
            raise MigrationJobConflict(
                "dry_run_required", "Run a dry run for this exact mapping first."
            )

        job_payload = {
            "mode": payload.mode,
            "source": payload.source,
            "connectionId": payload.connectionId or "",
            "workspaceId": payload.workspaceId,
            "channelMap": [e.model_dump() for e in payload.channelMap],
            "userMap": [e.model_dump() for e in payload.userMap],
            "teamMap": [e.model_dump() for e in payload.teamMap],
            "lifecycleMap": [e.model_dump() for e in payload.lifecycleMap],
            "messagesSince": parsed_messages_since,
            "contactsOnly": bool(payload.contactsOnly),
            "mappingHash": mapping_hash,
            # S5 (AC-MIG-47) - the RESOLVED storage key (review round 1,
            # finding B2 - resolved above, tenant-scoped, from
            # `contactsUploadId`), required for `source="csv"`, ignored for
            # `source="api"`. `snippetsCsvKey` (S4's `snippetsCsvBase64`
            # renamed onto the real upload route, D-A6-25) stays optional in
            # BOTH modes - empty/absent means "no snippets CSV supplied", a
            # legitimate no-op for the quick_replies phase, not an error.
            "contactsCsvKey": contacts_storage_key,
            "csvHeaderMap": payload.csvHeaderMap or {},
            "snippetsCsvKey": snippets_storage_key,
            # Denormalized (the Broadcast-model convention, `models.py
            # template_name`) - a renamed/retired connection or workspace must
            # not blank out this job's history row.
            "spaceLabel": space_label,
            "workspaceName": workspace.name,
        }
        job = self.jobs.create_and_enqueue(
            type=MIGRATION_JOB_TYPE, tenant_id=tenant_id, actor_user_id=actor_user_id, payload=job_payload
        )
        return self._to_item(job, tenant_id)

    # ── S5 - CSV upload (AC-MIG-46/47, D-A6-25) ─────────────────────────────

    def upload_csv(
        self, tenant_id: str, kind: str, content: bytes, *, actor_user_id: Optional[str] = None
    ) -> MigrationUploadResult:
        """Stores an uploaded contacts/snippets CSV through the tenant's
        active storage connection (the SAME `storage_for_tenant(...).save`
        seam every other upload in this codebase uses), persists a tenant-
        scoped `MigrationUpload` receipt row for it (review round 1, finding
        B2 - `MigrationJobCreate` now carries this receipt's OPAQUE `id`,
        never the raw storage key), and returns that id - the real-upload-
        route replacement for S4's `snippetsCsvBase64` JSON stopgap,
        generalized to also cover the CSV-mode contacts file. Sniff-gated
        (never trusts the filename/declared content type): a PNG named
        `contacts.csv` is rejected here, before a single byte reaches
        storage or a receipt row is created."""
        fmt = csv_readers.sniff_format(content)
        if fmt is None:
            raise MigrationJobValidationError({"file": "Unsupported file - upload a CSV (or xlsx/xls)."})
        headers, records = csv_readers.read_rows(content, fmt, None, settings.import_max_rows)
        key = storage_for_tenant(self.db, tenant_id).save(
            f"omnichannel/migration/uploads/{uuid4()}/{kind}.csv", content, "text/csv"
        )
        upload = MigrationUploadRepository(self.db).create(
            tenant_id=tenant_id,
            workspace_id=None,  # not yet chosen at upload time - tenant scope alone gates resolution
            kind=kind,
            storage_key=key,
            row_count=len(records),
            headers=headers,
            created_by=actor_user_id,
        )
        self.db.commit()
        return MigrationUploadResult(id=upload.id, rowCount=len(records), headers=headers)

    # ── reads ────────────────────────────────────────────────────────────────

    def list_jobs(
        self,
        tenant_id: str,
        *,
        page: int,
        page_size: int,
        status_filter: Optional[str],
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_desc: bool = True,
        filter_raw: Optional[str] = None,
    ) -> MigrationJobListResponse:
        """S2 shipped pagination + the status segment only; S6 (AC-MIG-02/56)
        adds the list's free-text search, column sort and Filter popover -
        all evaluated IN PYTHON over this tenant's full migration-job set
        (`MAX_LIST_SCAN_JOBS`'s own comment explains why: `spaceLabel`/
        `workspaceName`/`mode` have no native column to sort/filter
        portably)."""
        q = self.db.query(BackgroundJob).filter(
            BackgroundJob.tenant_id == tenant_id, BackgroundJob.type == MIGRATION_JOB_TYPE
        )
        if status_filter:
            q = q.filter(BackgroundJob.status == status_filter)
        rows = q.order_by(BackgroundJob.created_at.desc()).limit(MAX_LIST_SCAN_JOBS).all()

        filter_group = _parse_list_filter(filter_raw)
        row_fields = {r.id: _list_row_fields(r) for r in rows}
        if search:
            needle = search.strip().lower()
            if needle:
                rows = [r for r in rows if needle in row_fields[r.id]["spaceLabel"].lower() or needle in row_fields[r.id]["workspaceName"].lower()]
        if filter_group is not None:
            rows = [r for r in rows if _filter_rule_matches(filter_group, row_fields[r.id])]

        sort_field = sort_by if sort_by in _LIST_SORT_FIELDS else "createdAt"

        _MIN_DT = datetime.min.replace(tzinfo=timezone.utc)

        def sort_key(job: BackgroundJob):
            value = row_fields[job.id][sort_field]
            if isinstance(value, str):
                return value.lower()
            if value is None:
                return _MIN_DT
            return value

        rows.sort(key=sort_key, reverse=sort_desc)

        total = len(rows)
        page_rows = rows[page * page_size : page * page_size + page_size]

        actor_ids = {r.actor_user_id for r in page_rows if r.actor_user_id}
        actor_names: Dict[str, str] = {}
        if actor_ids:
            for u in self.db.query(User).filter(User.tenant_id == tenant_id, User.id.in_(actor_ids)).all():
                actor_names[u.id] = u.name or u.email
        items = [self._to_item(r, tenant_id, actor_names=actor_names) for r in page_rows]
        return MigrationJobListResponse(data=items, total=total, page=page)

    def get_job(self, tenant_id: str, job_id: str) -> MigrationJobItem:
        job = self._require_job(tenant_id, job_id)
        return self._to_item(job, tenant_id, include_logs=True)

    def failures_csv(self, tenant_id: str, job_id: str) -> str:
        """S5 (D-A6-23/25) - `finish_done()` now writes the FULL failure set
        to storage (`_write_failures_csv`) and this reads it straight back,
        an AUTHED server-side fetch (never a redirect to a presigned URL -
        D-A6-23 forbids a bearer-less capability link for a file of contact
        names/phones/emails). Falls back to any INLINE `failures.rows` (the
        pre-S5 shape, and still what a hand-built test/job row carries) or
        `failures.sample` (a DRY RUN, review round 1 finding S1 - `fileKey`
        is deliberately `None` there, AC-MIG-27) when no `fileKey` is
        present - never a hard failure either way."""
        job = self._require_job(tenant_id, job_id)
        failures_meta = (job.result_json or {}).get("failures") or {}
        file_key = failures_meta.get("fileKey")
        if file_key:
            try:
                content, _mime = storage_for_tenant(self.db, tenant_id).fetch(file_key)
                return content.decode("utf-8-sig")
            except Exception:  # noqa: BLE001 - unresolvable key (connection gone) - fall back below
                pass
        rows = failures_meta.get("rows") or failures_meta.get("sample") or []
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["entity", "sourceId", "sourceLabel", "reason", "action"])
        for r in rows:
            writer.writerow(
                [
                    sanitize_cell(r.get("entity")),
                    sanitize_cell(r.get("sourceId")),
                    sanitize_cell(r.get("sourceLabel")),
                    sanitize_cell(r.get("reason")),
                    sanitize_cell(r.get("action")),
                ]
            )
        return buf.getvalue()

    def _to_item(
        self,
        job: BackgroundJob,
        tenant_id: str,
        *,
        actor_names: Optional[Dict[str, str]] = None,
        include_logs: bool = False,
    ) -> MigrationJobItem:
        payload = job.payload_json or {}
        cursor = job.cursor_json or {}
        counts = cursor.get("counts") or {}
        contacts_counts = counts.get("contacts") or {}
        messages_counts = counts.get("messages") or {}
        result = job.result_json or {}
        report = result.get("report")
        failures = result.get("failures") or {}
        # S5 - `finish_done()` now keeps only a capped `sample` inline
        # (the FULL set moved to storage, `_write_failures_csv`); a pre-S5 or
        # hand-built job row (tests) still carries the old inline `rows`.
        failure_rows = failures.get("sample") or failures.get("rows") or []

        actor_name = None
        if job.actor_user_id:
            if actor_names is not None:
                actor_name = actor_names.get(job.actor_user_id)
            else:
                u = (
                    self.db.query(User)
                    .filter(User.tenant_id == tenant_id, User.id == job.actor_user_id)
                    .first()
                )
                actor_name = (u.name or u.email) if u else None

        return MigrationJobItem(
            id=job.id,
            mode=payload.get("mode", ""),
            source=payload.get("source", "api"),
            connectionId=payload.get("connectionId", ""),
            spaceLabel=payload.get("spaceLabel", ""),
            workspaceId=payload.get("workspaceId", ""),
            workspaceName=payload.get("workspaceName", ""),
            status=job.status,
            progressTotal=job.progress_total,
            progressDone=job.progress_done,
            progressFailed=job.progress_failed,
            entityCounts={
                "contacts": contacts_counts.get("fetched", 0),
                "messages": messages_counts.get("fetched", 0),
            },
            report=report,
            failureCount=failures.get("rowCount", len(failure_rows)),
            failureSample=failure_rows[:50],
            startedAt=job.started_at,
            finishedAt=job.finished_at,
            createdAt=job.created_at,
            actorUserName=actor_name,
            logs=list(job.logs_json or []) if include_logs else [],
        )

    # ── cancel (AC-MIG-28) ───────────────────────────────────────────────────

    def cancel_job(self, tenant_id: str, job_id: str) -> MigrationJobItem:
        job = self._require_job(tenant_id, job_id)
        if job.status not in (JOB_PENDING, JOB_RUNNING):
            raise MigrationJobConflict("not_in_progress", "This migration is not in progress.")
        self.jobs.finish(job, status=JOB_ABORTED, result=job.result_json)
        return self._to_item(job, tenant_id)


# ── job handler (registered via register_job_handler, plan §5.2/§2.1) ──────


def _process_contact_identities(
    client: RespondIoClient,
    writer: MigrationWriter,
    contact_local_id: str,
    contact_external_id: str,
    channel_map: Dict[str, str],
    channel_type_by_target: Dict[str, str],
    contact_phone: Optional[str],
    identity_counts: Dict[str, int],
    failures: List[dict],
) -> None:
    """One contact's channel-identity walk (AC-MIG-30). Shared by the real
    per-ref "identities" phase (walks `migration_refs`, resumable across a
    crash) AND the dry-run inline preview inside the contacts loop (D-A6-14:
    ONE code path - only the caller's transaction scope and iteration source
    differ, never the write logic itself)."""
    try:
        raw_channels = client.get_contact_channels(f"id:{contact_external_id}")
    except RespondIoError as exc:
        identity_counts["errors"] = identity_counts.get("errors", 0) + 1
        failures.append(
            {
                "entity": "identities", "sourceId": contact_external_id, "sourceLabel": "",
                "reason": exc.message, "action": "skipped",
            }
        )
        return
    for raw_channel in raw_channels:
        try:
            source_channel = SourceContactChannel(**raw_channel)
        except Exception as exc:  # noqa: BLE001 - malformed vendor row, never abort the job
            identity_counts["fetched"] += 1
            identity_counts["errors"] = identity_counts.get("errors", 0) + 1
            failures.append(
                {
                    "entity": "identities", "sourceId": contact_external_id, "sourceLabel": "",
                    "reason": f"malformed channel payload: {exc}", "action": "skipped",
                }
            )
            continue
        target_channel_id = channel_map.get(str(source_channel.id))
        if target_channel_id is None:
            continue  # unmapped source channel - not counted (an operator choice, not a failure)
        identity_counts["fetched"] += 1
        outcome = writer.write_identity(
            contact_local_id, contact_external_id, source_channel, target_channel_id,
            channel_type_by_target.get(target_channel_id, ""), contact_phone,
        )
        if outcome.kind == "skip":
            identity_counts["skip"] = identity_counts.get("skip", 0) + 1
            failures.append(
                {
                    "entity": "identities", "sourceId": contact_external_id,
                    "sourceLabel": source_channel.name or "", "reason": outcome.reason or "",
                    "action": "skipped",
                }
            )
        else:
            identity_counts[outcome.kind] = identity_counts.get(outcome.kind, 0) + 1


def _process_contact_messages(
    client: RespondIoClient,
    writer: MigrationWriter,
    refs: MigrationRefRepository,
    tenant_id: str,
    workspace_id: str,
    local_contact: ContactModel,
    contact_external_id: str,
    channel_map: Dict[str, str],
    user_map: Dict[str, str],
    message_counts: Dict[str, int],
    failures: List[dict],
    message_samples: List[dict],
    messages_since: Optional[datetime] = None,
) -> Tuple[int, int, int]:
    """One contact's FULL message-history walk - buffered, sorted by
    `messageId`, timestamp-resolved as ONE unit (D-A6-9 needs the whole
    contact's history bracketed together). Shared by the real per-ref
    "messages" phase AND the dry-run inline preview. Returns
    `(newly_inferred, newly_skipped_before_floor, skipped_over_cap)` - plain
    ints, not shared counters (the caller accumulates all three).
    `skipped_over_cap` is 1 when this contact's history exceeded
    `MAX_MESSAGES_PER_CONTACT` (review round 1, finding S11) and its whole
    message set was skipped (reported, never an abort), 0 otherwise.

    `messages_since` (D-A6-22) is applied AFTER `resolve_message_timestamps`
    runs on the FULL unfiltered set - the interpolation branch needs every
    bracketing anchor regardless of the floor, so filtering first would let a
    floored-out message silently change another message's inferred timestamp.
    A message whose RESOLVED `created_at` falls before the floor is neither
    written nor error-reported (an operator choice, not a failure) and is
    never considered for `already_migrated` (a floored-out id has no ref
    either way, so a re-run with the SAME floor floors it again identically -
    the plan's own suggested "cheap early stop over a newest-first page" is
    NOT implemented as a network-level short-circuit here, since the vendor
    documents no page ordering guarantee to rely on for that; this filters
    the fully-resolved, already-buffered set instead - equally correct,
    slightly more network calls on a very old floor)."""
    identifier = f"id:{contact_external_id}"
    # D-A6-9's third fallback branch needs the SOURCE contact's own
    # `created_at` (a targeted re-fetch, plan §5.1) - falls back to the LOCAL
    # row's `created_at` only if even that call fails, rather than skipping
    # the contact's history outright.
    fallback_dt = local_contact.created_at
    try:
        raw_contact = client.get_contact(identifier)
        source_created_at = raw_contact.get("created_at")
        if source_created_at is not None:
            # `epoch_to_dt` (review round 1, finding S2) never raises - a
            # garbage/ms-magnitude/out-of-range value clamps rather than
            # propagating out of this per-contact phase.
            fallback_dt = epoch_to_dt(source_created_at)
    except RespondIoError as exc:
        failures.append(
            {
                "entity": "messages", "sourceId": contact_external_id, "sourceLabel": "",
                "reason": f"could not re-fetch source contact for its created_at fallback: {exc}",
                "action": "used local contact.created_at instead",
            }
        )

    buffered_raw: List[dict] = []
    over_cap = False
    try:
        for page_items, _next in client.list_messages_pages(identifier, limit=MESSAGES_PAGE_LIMIT):
            buffered_raw.extend(page_items)
            if len(buffered_raw) > MAX_MESSAGES_PER_CONTACT:
                # S11 - stop paging THIS contact immediately (no further
                # network calls or memory growth); its whole message set is
                # skipped below, never partially written.
                over_cap = True
                break
    except RespondIoError as exc:
        message_counts["errors"] = message_counts.get("errors", 0) + 1
        failures.append(
            {
                "entity": "messages", "sourceId": contact_external_id, "sourceLabel": "",
                "reason": exc.message, "action": "skipped",
            }
        )
        return 0, 0, 0

    if over_cap:
        message_counts["errors"] = message_counts.get("errors", 0) + 1
        failures.append(
            {
                "entity": "messages", "sourceId": contact_external_id, "sourceLabel": "",
                "reason": (
                    f"This contact has more than {MAX_MESSAGES_PER_CONTACT} messages - its "
                    "message history was skipped to protect the migration job."
                ),
                "action": "skipped",
            }
        )
        return 0, 0, 1

    parsed_items: List[SourceMessageItem] = []
    for raw in buffered_raw:
        try:
            parsed_items.append(SourceMessageItem(**raw))
        except Exception as exc:  # noqa: BLE001 - malformed vendor row, never abort the job
            message_counts["fetched"] = message_counts.get("fetched", 0) + 1
            message_counts["errors"] = message_counts.get("errors", 0) + 1
            failures.append(
                {
                    "entity": "messages", "sourceId": contact_external_id, "sourceLabel": "",
                    "reason": f"malformed message payload: {exc}", "action": "skipped",
                }
            )

    # Thread order ALWAYS follows the source messageId (D-A6-9) - never the
    # resolved timestamp, which is derived FROM this order in the first place.
    parsed_items.sort(key=lambda m: m.messageId)
    try:
        resolved = resolve_message_timestamps(parsed_items, fallback_dt)
    except Exception as exc:  # noqa: BLE001 - per-contact isolation (review round 1, finding S2)
        message_counts["errors"] = message_counts.get("errors", 0) + 1
        failures.append(
            {
                "entity": "messages", "sourceId": contact_external_id, "sourceLabel": "",
                "reason": f"could not resolve message timestamps: {exc}", "action": "skipped",
            }
        )
        return 0, 0, 0

    skipped_before_floor = 0
    if messages_since is not None:
        kept_items: List[SourceMessageItem] = []
        kept_resolved: List[Tuple[datetime, bool]] = []
        for item, (created_at, inferred) in zip(parsed_items, resolved):
            if created_at < messages_since:
                skipped_before_floor += 1
                continue
            kept_items.append(item)
            kept_resolved.append((created_at, inferred))
        parsed_items, resolved = kept_items, kept_resolved

    already = refs.already_migrated(
        tenant_id, workspace_id, RESPONDIO_PROVIDER, ENTITY_MESSAGE,
        [str(m.messageId) for m in parsed_items],
    )

    newly_inferred = 0
    for item, (created_at, inferred) in zip(parsed_items, resolved):
        message_counts["fetched"] = message_counts.get("fetched", 0) + 1
        if str(item.messageId) in already:
            message_counts["skip"] = message_counts.get("skip", 0) + 1
            continue
        target_channel_id = channel_map.get(str(item.channelId)) if item.channelId is not None else None
        try:
            writer.write_message(
                local_contact.id, item, created_at,
                timestamp_inferred=inferred, channel_id=target_channel_id, user_map=user_map,
            )
        except Exception as exc:  # noqa: BLE001 - per-row isolation (AC-MIG-29's pattern)
            message_counts["errors"] = message_counts.get("errors", 0) + 1
            failures.append(
                {
                    "entity": "messages", "sourceId": str(item.messageId), "sourceLabel": "",
                    "reason": str(exc), "action": "skipped",
                }
            )
            continue
        message_counts["create"] = message_counts.get("create", 0) + 1
        if inferred:
            newly_inferred += 1
        if len(message_samples) < MAX_REPORT_SAMPLES:
            message_samples.append({"type": item.message.type, "action": "create"})

    # AC-MIG-37 - exactly ONE recompute per contact, after its WHOLE message
    # phase (this call covers every page for this contact - buffered above).
    writer.recompute_contact_timestamps(local_contact)
    return newly_inferred, skipped_before_floor, 0


# ── S4 - media (AC-MIG-39/40) ────────────────────────────────────────────────

_MEDIA_KINDS = ("IMAGE", "VIDEO", "AUDIO", "DOCUMENT")


def _requires_media_fetch(message: ConversationMessage) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Returns `(url, declared_kind, filename_hint)`, or `(None, None, None)`
    when this message owes no media fetch at all. Three sources, in order:

    1. the PRIMARY `attachment` case - S3 flagged it with `payload_json.
       migration.pendingMedia` and staged the URL on the LEGACY `media_url`
       column; `declared_kind` is the message's own `message_type` (already
       known - IMAGE/VIDEO/AUDIO/DOCUMENT).
    2. a nested `email` attachment - S3 deliberately left this UNFLAGGED (see
       `migration_writer._map_message_content`'s own comment): only the
       FIRST attachment is fetched (mirrors the template header-only rule
       below); `declared_kind` is None (resolved from the sniffed mime).
    3. a nested `whatsapp_template` HEADER component carrying a media link -
       also unflagged by S3, also kind-less up front.

    `media_key` already set = already fetched on a prior run (idempotent,
    AC-MIG-45) - checked FIRST so a re-run never re-derives a URL at all."""
    if message.media_key:
        return None, None, None
    payload = message.payload_json or {}
    migration_meta = payload.get("migration") or {}
    if migration_meta.get("pendingMedia") and message.media_url:
        declared_kind = message.message_type if message.message_type in _MEDIA_KINDS else None
        return message.media_url, declared_kind, message.media_filename

    email_attachments = (payload.get("email") or {}).get("attachments") or []
    if email_attachments:
        first = email_attachments[0] or {}
        url = first.get("url")
        if url:
            return url, None, first.get("filename")

    template = payload.get("template") or {}
    for component in template.get("components") or []:
        if str((component or {}).get("type") or "").upper() == "HEADER":
            link = component.get("link") or component.get("url")
            if link:
                return link, None, None

    return None, None, None


def _process_message_media(
    writer: MigrationWriter,
    tenant_id: str,
    workspace_id: str,
    message: ConversationMessage,
    media_counts: Dict[str, int],
    failures: List[dict],
    *,
    http_client=None,
) -> None:
    """One message's media fetch (AC-MIG-39/40) - NEVER raises; a failure
    keeps the message row exactly as written (D-A6-7) and is reported."""
    url, declared_kind, filename_hint = _requires_media_fetch(message)
    if not url:
        # Nothing owed - not counted at all (mirrors the "unmapped source
        # channel" pattern in the identities phase).
        return
    media_counts["fetched"] = media_counts.get("fetched", 0) + 1
    result = migration_media.fetch_and_store_media(
        writer.db, tenant_id=tenant_id, workspace_id=workspace_id, message_id=message.id,
        url=url, filename=filename_hint, declared_kind=declared_kind, http_client=http_client,
    )
    if not result.ok:
        media_counts["errors"] = media_counts.get("errors", 0) + 1
        writer.record_media_failure(message, result.reason or "Media fetch failed.")
        failures.append(
            {
                "entity": "media", "sourceId": message.id, "sourceLabel": message.media_filename or "",
                "reason": result.reason or "Media fetch failed.", "action": "kept the message, skipped media",
            }
        )
        return
    media_counts["create"] = media_counts.get("create", 0) + 1
    writer.apply_media(message, result)


# ── S4 - derived conversation_events (AC-MIG-41/42) ─────────────────────────


def _process_contact_events(
    client: RespondIoClient,
    writer: MigrationWriter,
    refs: MigrationRefRepository,
    tenant_id: str,
    workspace_id: str,
    local_contact: ContactModel,
    contact_external_id: str,
    event_counts: Dict[str, int],
    failures: List[dict],
) -> None:
    """One contact's derived-events pass (AC-MIG-41). Idempotent via
    `migration_refs` keyed PER CONTACT (D-A6-13) - a re-run skips the whole
    set for a contact that already has a ref, never re-deriving (and never
    re-fetching the source contact, which the ref check happens BEFORE)."""
    existing_ref = refs.local_for_one(
        tenant_id, workspace_id, RESPONDIO_PROVIDER, ENTITY_EVENT, contact_external_id
    )
    if existing_ref is not None:
        event_counts["skip"] = event_counts.get("skip", 0) + 1
        return

    try:
        raw_contact = client.get_contact(f"id:{contact_external_id}")
        source_contact = Contact(**raw_contact)
    except Exception as exc:  # noqa: BLE001 - never abort the job (RespondIoError or a malformed row)
        event_counts["errors"] = event_counts.get("errors", 0) + 1
        failures.append(
            {
                "entity": "events", "sourceId": contact_external_id, "sourceLabel": "",
                "reason": f"could not re-fetch source contact for event derivation: {exc}",
                "action": "skipped",
            }
        )
        return

    event_counts["fetched"] = event_counts.get("fetched", 0) + 1
    written = writer.write_derived_events(local_contact, source_contact)
    event_counts["create"] = event_counts.get("create", 0) + written
    refs.record(tenant_id, workspace_id, RESPONDIO_PROVIDER, ENTITY_EVENT, contact_external_id, local_contact.id)


# ── S4 - quick replies from a snippets CSV (AC-MIG-44) ──────────────────────


def _process_quick_replies_csv(
    db: Session,
    tenant_id: str,
    writer: MigrationWriter,
    csv_key: Optional[str],
    qr_counts: Dict[str, int],
    failures: List[dict],
) -> None:
    """Respond.io exposes no snippets endpoint (D-A6-19/F3) - this reads the
    2-column (`shortcut`, `body`) CSV the operator uploaded alongside the job
    through the SAME `app/import_engine/readers.py` sniff/cap the rest of the
    platform's imports use. S5 (D-A6-25) reads it from STORAGE via `csv_key`
    (`POST /omnichannel/migration/uploads`'s own key) - the real-upload-route
    replacement for S4's `snippetsCsvBase64` JSON-payload stopgap, whose own
    docstring named this slice as the one that would do it. A no-op (zero
    counts) when no CSV was supplied - not a failure, a legitimate
    "no snippets" run."""
    if not csv_key:
        return
    try:
        content, _mime = storage_for_tenant(db, tenant_id).fetch(csv_key)
    except Exception as exc:  # noqa: BLE001 - storage gone/misconfigured, never abort the job
        failures.append(
            {
                "entity": "quickReplies", "sourceId": "", "sourceLabel": "",
                "reason": f"Could not read the uploaded snippets CSV: {exc}", "action": "skipped",
            }
        )
        return

    fmt = csv_readers.sniff_format(content)
    if fmt is None:
        failures.append(
            {
                "entity": "quickReplies", "sourceId": "", "sourceLabel": "",
                "reason": "Unsupported file format for the snippets CSV.", "action": "skipped",
            }
        )
        return

    headers, records = csv_readers.read_rows(content, fmt, None, settings.import_max_rows)
    header_by_lower = {h.strip().lower(): h for h in headers}
    shortcut_header = header_by_lower.get("shortcut")
    body_header = header_by_lower.get("body")
    if not shortcut_header or not body_header:
        failures.append(
            {
                "entity": "quickReplies", "sourceId": "", "sourceLabel": "",
                "reason": "The snippets CSV needs 'shortcut' and 'body' columns.", "action": "skipped",
            }
        )
        return

    for i, record in enumerate(records):
        qr_counts["fetched"] = qr_counts.get("fetched", 0) + 1
        shortcut = str(record.get(shortcut_header) or "").strip()
        body = str(record.get(body_header) or "").strip()
        if not shortcut or not body:
            qr_counts["errors"] = qr_counts.get("errors", 0) + 1
            failures.append(
                {
                    "entity": "quickReplies", "sourceId": str(i), "sourceLabel": shortcut or body,
                    "reason": "Missing shortcut or body.", "action": "skipped",
                }
            )
            continue
        outcome = writer.write_quick_reply(shortcut, body)
        qr_counts[outcome] = qr_counts.get(outcome, 0) + 1


def run_migration_job(db: Session, job: BackgroundJob) -> None:
    """`omnichannel.respondio_migration` job handler. Phase order (D-A6-4):
    contacts (S2) -> identities -> messages (S3) -> media -> events ->
    quick_replies (S4). Dry run and real run share this ONE code path
    throughout (D-A6-14): every phase's per-unit write happens inside its OWN
    SAVEPOINT (`db.begin_nested()`), COMMITTED (released into the session's
    pending transaction) on a real run or unconditionally ROLLED BACK on a
    dry run.

    The contacts phase checkpoints per respond.io PAGE (AC-MIG-22, unchanged
    from S2). The identities/messages/media/events phases checkpoint per
    CONTACT or per MESSAGE ref instead (a deliberate S3 deviation, documented
    on `CONTACT_REF_BATCH`/`MEDIA_REF_BATCH` above) - D-A6-9's timestamp
    interpolation needs a whole contact's message history bracketed together,
    so a contact's full message set is buffered, sorted by `messageId` and
    timestamp-resolved as ONE unit before any row is written; re-processing a
    contact from scratch after a crash is safe because `migration_refs` makes
    every write idempotent.

    Like the identities/messages phases before them, media/events/quick_
    replies (S4) are reached ONLY for a real, non-`contactsOnly` run - a dry
    run and a `contactsOnly` run both `finish_done()` right after the
    contacts loop below, so these three phases' report entities stay
    genuinely zero (never walked) in either mode, exactly like S3 left
    identities/messages zero for S2's dry runs (AC-MIG-27's "no media URL is
    fetched" during a dry run is therefore structural, not a branch).

    S5 (D-A6-25) - `source="csv"` skips the whole API surface: no
    connection/client/credentials are required, `source_field_defs` stays
    empty (this path automates no custom fields, see the S5 module-docstring
    decision above the CSV helpers), and the phase machine goes straight
    from `contacts` to `quick_replies` - `identities`/`messages`/`media`/
    `events` never run (an API-less export carries none of that data,
    AC-MIG-48) so those four report entities stay genuinely zero, exactly
    like a `contactsOnly` API run leaves media/events/quick_replies zero."""
    service = JobService(db)
    tenant_id = job.tenant_id
    payload = job.payload_json or {}
    workspace_id = payload.get("workspaceId")
    connection_id = payload.get("connectionId")
    source_mode = payload.get("source", "api")
    csv_mode = source_mode == "csv"
    dry_run = payload.get("mode") == "dry_run"
    contacts_only = bool(payload.get("contactsOnly"))

    client: Optional[RespondIoClient] = None
    space_timezone = ""

    def milestone(msg: str) -> None:
        service.log(job, msg)

    # Review round 2, R1 - a SECOND callback, wired only for the client's
    # three pagination termination guards (`_on_blocker` in
    # `respondio/client.py`), NOT the rate-halving milestone (that one is
    # informational, not a data-loss signal). `pagination_blockers` is
    # declared further down this function; a nested function only needs the
    # name bound by the time it is actually CALLED, and every page walk
    # happens after that assignment runs.
    def blocker(msg: str) -> None:
        pagination_blockers.append(msg)

    if not csv_mode:
        connection = MigrationConnectionRepository(db).get_for_provider(
            tenant_id, connection_id, RESPONDIO_PROVIDER
        )
        if connection is None:
            service.finish(job, status=JOB_FAILED, error="The respond.io connection no longer exists.")
            return
        credentials = _decrypt_or_none(connection.credentials_json)
        if credentials is None:
            service.finish(
                job, status=JOB_FAILED,
                error="Stored credentials could not be decrypted - re-enter the access token.",
            )
            return
        config = connection.config_json or {}
        space_timezone = str(config.get("timezone") or "")
        client = RespondIoClient.from_connection(
            config, credentials, on_milestone=milestone, on_blocker=blocker
        )

    # Re-validate every mapped id AT USE TIME, never trust save-time
    # validation alone (AC-MIG-51) - a stage/channel/user deleted between
    # create and run silently drops out of the map rather than crashing the
    # run.
    lifecycle_map: Dict[str, str] = {}
    for entry in payload.get("lifecycleMap") or []:
        target = entry.get("targetStatusId")
        source_label = str(entry.get("sourceLabel") or "").strip().lower()
        if not target or not source_label:
            continue
        if get_scope_status(db, LIFECYCLE_ENTITY_TYPE, tenant_id, workspace_id, target) is not None:
            lifecycle_map[source_label] = target

    channel_map, channel_type_by_target = _resolve_channel_map(db, tenant_id, workspace_id, payload)
    user_map, user_map_dropped = _resolve_user_map(db, tenant_id, payload)
    team_map, team_map_dropped = _resolve_team_map(db, tenant_id, payload)

    # S5 (review round 1, A8 merged to `main`) - a source contact's team
    # comes from its ASSIGNEE's team (respond.io's own `Contact` shape
    # carries no team of its own) - only fetched when a team mapping was
    # actually configured, so a job with an empty `teamMap` (the common
    # case) never pays for this extra `/space/user` call.
    user_team_by_id: Dict[str, str] = {}
    if client is not None and payload.get("teamMap"):
        try:
            for raw_user in client.list_space_users():
                parsed_user = SpaceUser(**raw_user)
                if parsed_user.team is not None:
                    user_team_by_id[str(parsed_user.id)] = str(parsed_user.team.id)
        except RespondIoError as exc:
            service.log(job, f"Could not read source space users for team mapping: {exc.message}", level="warning")

    thread_open_id = status_id_for(db, tenant_id, "THREAD", "OPEN")
    thread_closed_id = status_id_for(db, tenant_id, "THREAD", "CLOSED")
    initial_lifecycle_id = initial_status_id(db, tenant_id, workspace_id)

    # D-A6-22 - the message-phase date floor (contacts are NEVER floored).
    # Already parsed to an ISO string at create time (`_validate_mapping`);
    # re-parsed to an aware-UTC `datetime` here once, not per message.
    messages_since_raw = payload.get("messagesSince")
    messages_since_dt: Optional[datetime] = None
    if messages_since_raw:
        try:
            messages_since_dt = datetime.fromisoformat(str(messages_since_raw)).astimezone(timezone.utc)
        except ValueError:
            messages_since_dt = None

    source_field_defs: Dict[str, Dict[str, Any]] = {}
    if client is not None:
        try:
            for raw_field in client.list_custom_fields():
                parsed = CustomField(**raw_field)
                source_field_defs[parsed.name.strip().lower()] = {
                    "dataType": parsed.dataType,
                    "allowedValues": parsed.allowedValues,
                }
        except RespondIoError as exc:
            service.log(job, f"Could not read source custom fields: {exc.message}", level="warning")
            source_field_defs = {}

    writer = MigrationWriter(
        db,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        thread_open_status_id=thread_open_id,
        thread_closed_status_id=thread_closed_id,
        initial_lifecycle_status_id=initial_lifecycle_id,
        lifecycle_map=lifecycle_map,
        source_field_defs=source_field_defs,
        writes_enabled=not dry_run,
        team_map=team_map,
        user_team_by_id=user_team_by_id,
    )
    refs = MigrationRefRepository(db)

    cursor = job.cursor_json or {}
    counts: Dict[str, Any] = dict(cursor.get("counts") or {})
    contact_counts = dict(counts.get("contacts") or {"fetched": 0, "create": 0, "update": 0, "errors": 0})
    field_counts = dict(counts.get("fields") or {"fetched": 0, "create": 0, "matched": 0, "errors": 0})
    tag_counts = dict(counts.get("tags") or {"fetched": 0, "create": 0, "matched": 0})
    identity_counts = dict(
        counts.get("identities") or {"fetched": 0, "create": 0, "update": 0, "skip": 0, "errors": 0}
    )
    message_counts = dict(counts.get("messages") or {"fetched": 0, "create": 0, "skip": 0, "errors": 0})
    media_counts = dict(counts.get("media") or {"fetched": 0, "create": 0, "skip": 0, "errors": 0})
    event_counts = dict(counts.get("events") or {"fetched": 0, "create": 0, "skip": 0, "errors": 0})
    quick_reply_counts = dict(
        counts.get("quickReplies") or {"fetched": 0, "create": 0, "update": 0, "skip": 0, "errors": 0}
    )
    lifecycle_unmapped = int(counts.get("lifecycleUnmappedCount") or 0)
    assignee_unmatched = int(counts.get("assigneeUnmatchedCount") or 0)
    messages_inferred = int(counts.get("messagesWithInferredTimestamp") or 0)
    messages_skipped_before_floor = int(counts.get("messagesSkippedBeforeFloor") or 0)
    # S11 (review round 1) - contacts whose whole message history exceeded
    # `MAX_MESSAGES_PER_CONTACT` and were skipped, never fabricated/partially
    # written; persisted through `checkpoint()` like every other counter.
    messages_skipped_over_cap = int(counts.get("messagesSkippedOverCap") or 0)
    # S5 - persisted through `checkpoint()` (like every other counter here) so
    # a crash-resumed invocation that picks the job back up in a LATER phase
    # (e.g. `quick_replies`) still reports the row-cap/unmapped-header facts
    # the earlier `contacts` phase found (D-A6-25).
    csv_blockers: List[str] = list(counts.get("csvBlockers") or [])
    # Defect 2 fix (test report round 1) - CSV mode's own per-VALUE unmapped
    # lifecycle tally (`rawLabel -> count`), persisted through `checkpoint()`
    # exactly like `csv_blockers` above. The API-mode `lifecycle_unmapped`
    # scalar counter above stays as-is; CSV mode's contacts loop increments
    # THIS dict instead so the report can name the actual value(s), not just
    # a bare count.
    csv_lifecycle_unmapped: Dict[str, int] = dict(counts.get("csvLifecycleUnmapped") or {})
    # Review round 2, R1 - the client's three pagination TERMINATION guards
    # (same cursor twice, an empty page that still carries a cursor, the
    # `MAX_PAGES` ceiling) used to only reach `service.log()` (the job's
    # milestone log, easy to miss on the detail page). Each guard firing
    # means the walk stopped EARLY - some records were not migrated - so it
    # now ALSO lands in `report.blockers` (the surface the operator actually
    # reads before deciding the run is complete). Persisted through
    # `checkpoint()` like every other counter/list here so a crash-resumed
    # invocation does not lose a guard that fired in an earlier phase.
    pagination_blockers: List[str] = list(counts.get("paginationBlockers") or [])

    prior_result = job.result_json or {}
    failures: List[dict] = list((prior_result.get("failures") or {}).get("rows") or [])
    samples: List[dict] = list((prior_result.get("report") or {}).get("samples", {}).get("contacts") or [])
    message_samples: List[dict] = list(
        (prior_result.get("report") or {}).get("samples", {}).get("messages") or []
    )

    contact_list_cursor = cursor.get("contactCursorId")
    identity_ref_cursor = cursor.get("identityCursorId")
    message_ref_cursor = cursor.get("messageCursorId")
    media_ref_cursor = cursor.get("mediaCursorId")
    event_ref_cursor = cursor.get("eventCursorId")
    phase = cursor.get("phase") or "contacts"

    def checkpoint(new_phase: str) -> None:
        counts["contacts"] = contact_counts
        counts["fields"] = field_counts
        counts["tags"] = tag_counts
        counts["identities"] = identity_counts
        counts["messages"] = message_counts
        counts["media"] = media_counts
        counts["events"] = event_counts
        counts["quickReplies"] = quick_reply_counts
        counts["lifecycleUnmappedCount"] = lifecycle_unmapped
        counts["assigneeUnmatchedCount"] = assignee_unmatched
        counts["messagesWithInferredTimestamp"] = messages_inferred
        counts["messagesSkippedBeforeFloor"] = messages_skipped_before_floor
        counts["messagesSkippedOverCap"] = messages_skipped_over_cap
        counts["csvBlockers"] = csv_blockers
        counts["csvLifecycleUnmapped"] = csv_lifecycle_unmapped
        counts["paginationBlockers"] = pagination_blockers
        # Review round 1, finding S6 - `set_total` used to be called ONLY
        # inside `finish_done`, so `progressTotal` read 0 for the ENTIRE run
        # (the detail page's Progress bar stalled at 0% throughout, jumping
        # straight to 100% at the terminal state). A RUNNING total, refined
        # every checkpoint (i.e. every page in the contacts phase, every
        # contact/message ref afterwards) using the SAME formula
        # `finish_done` already used - monotonic (`max` against whatever is
        # already stored) so it only ever grows, converging on the true
        # total by the time `finish_done` sets it exactly.
        #
        # Review round 2 - `job.progress_done` joins the `max(...)` set. The
        # fetched-sum formula above is a running ESTIMATE (it does not yet
        # know about later phases' own fetches), and `service.advance()`
        # bumps `progress_done` independently per row/contact/message; on a
        # long run the two can transiently disagree in either direction. A
        # total that ever reads BELOW `progress_done` is what makes the
        # detail page's progress bar/pct read over 100% before the terminal
        # `finish_done()` call reconciles it - folding `progress_done` into
        # the same monotonic `max()` here keeps `progressTotal >=
        # progressDone` at every checkpoint, not only at the end.
        #
        # Review round 2, R4 - `set_total` + `set_cursor` used to be two
        # separate `JobService` calls, each committing on its own (a
        # checkpoint = two commits). `JobService.set_total` is shared with
        # other job handlers (autocount, broadcasts, exports) so its
        # signature/commit behaviour stays untouched; here the field is set
        # directly on the ORM object and `set_cursor` below does the single
        # commit that persists both fields together.
        job.progress_total = max(
            job.progress_total or 0,
            job.progress_done or 0,
            contact_counts.get("fetched", 0)
            + identity_counts.get("fetched", 0)
            + message_counts.get("fetched", 0),
        )
        service.set_cursor(
            job,
            {
                "phase": new_phase,
                "contactCursorId": contact_list_cursor,
                "identityCursorId": identity_ref_cursor,
                "messageCursorId": message_ref_cursor,
                "mediaCursorId": media_ref_cursor,
                "eventCursorId": event_ref_cursor,
                "counts": counts,
            },
        )

    def finish_done() -> None:
        service.set_total(
            job,
            contact_counts.get("fetched", 0) + identity_counts.get("fetched", 0) + message_counts.get("fetched", 0),
        )
        report = _build_report(
            counts, samples, lifecycle_unmapped,
            messages_with_inferred=messages_inferred, message_samples=message_samples,
            messages_skipped_before_floor=messages_skipped_before_floor,
            messages_skipped_over_cap=messages_skipped_over_cap,
            user_map_dropped=user_map_dropped, team_map_dropped=team_map_dropped,
            lifecycle_unmapped_csv=csv_lifecycle_unmapped if csv_mode else None,
            pagination_blockers=pagination_blockers,
        )
        if csv_mode:
            # AC-MIG-48 - stated UP FRONT (every CSV-mode report, dry run or
            # real), never discovered mid-run: an API-less export carries no
            # media and no per-channel identity, and this slice's CSV path
            # migrates contacts (+ quick replies, if supplied) only - message
            # history stays out of scope (D-A6-25's own reasoning, commit
            # body). `csv_blockers` (row cap / unmapped headers) come first -
            # they are FILE-specific and more actionable than the three
            # static facts below.
            report["blockers"] = [
                *csv_blockers,
                "CSV mode migrates contacts (and quick replies, if a snippets "
                "CSV was supplied) only - message history is not migrated "
                "through this path.",
                "CSV mode creates no channel identity rows - the export "
                "carries no per-channel identifiers, so a future inbound "
                "message stitches to a migrated contact by phone/email only.",
                "CSV mode migrates no media - the export carries no media URLs.",
                *report["blockers"],
            ]
        # S5 (D-A6-25) - the FULL failure set moves to storage; only a small
        # capped sample stays inline for the detail page's failure table.
        # Review round 1, finding S1 - a DRY RUN must write ZERO rows
        # anywhere, storage blobs included (AC-MIG-27's own wording); the
        # inline `sample` (capped, same as the real-mode shape) is all a dry
        # run ever gets, `fileKey` stays `None` and `failures_csv()` falls
        # back to that sample for the download route.
        failures_key = None if dry_run else _write_failures_csv(db, tenant_id, job.id, failures)
        result = {
            "report": report,
            "failures": {"fileKey": failures_key, "rowCount": len(failures), "sample": failures[:50]},
        }
        service.finish(job, status=JOB_DONE, result=result)

    # ── phase 1 - contacts (S2 API path unchanged; S5 CSV path, AC-MIG-47) ──
    if phase == "contacts" and csv_mode:
        _process_csv_contacts(
            db, tenant_id, workspace_id, writer, payload,
            contact_counts, field_counts, tag_counts, samples, failures, csv_blockers,
            csv_lifecycle_unmapped,
            dry_run=dry_run, service=service, job=job,
        )
        checkpoint("contacts")
        if _aborted(db, job.id):
            service.log(job, f"Aborted after {contact_counts.get('fetched', 0)} contacts.")
            return

        if contacts_only or dry_run:
            # CSV mode's dry run never previews quick_replies inline (S4's
            # own gap: contactsOnly already skips it for the API path too,
            # see S4's docstring note the same block references below) - a
            # dry-run report's `quickReplies` entity stays genuinely zero,
            # consistent with `identities`/`messages`/`media`/`events`.
            finish_done()
            return

        # No identities/messages/media/events phases exist for CSV mode (an
        # API-less export carries none of that data, AC-MIG-48) - straight to
        # quick_replies (still optional; a no-op when no snippets CSV was
        # supplied, D-A6-19).
        phase = "quick_replies"
        checkpoint("quick_replies")
        if _aborted(db, job.id):
            service.log(job, "Aborted before the quick_replies phase.")
            return

    elif phase == "contacts":
        try:
            for page_items, next_cursor in client.list_contacts_pages(
                timezone=space_timezone, limit=CONTACTS_PAGE_LIMIT, start_cursor=contact_list_cursor
            ):
                for raw in page_items:
                    external_id = str(raw.get("id", ""))
                    try:
                        source_contact = Contact(**raw)
                    except Exception as exc:  # noqa: BLE001 - malformed vendor row, never abort the job
                        contact_counts["fetched"] += 1
                        contact_counts["errors"] = contact_counts.get("errors", 0) + 1
                        failures.append(
                            {
                                "entity": "contacts", "sourceId": external_id, "sourceLabel": "",
                                "reason": f"malformed contact payload: {exc}", "action": "skipped",
                            }
                        )
                        service.advance(job, failed=1)
                        continue

                    nested = db.begin_nested()
                    try:
                        outcome = writer.write_contact(source_contact)
                        # A dry run's per-contact SAVEPOINT is rolled back
                        # unconditionally below, which means `migration_refs`
                        # for "contact" never persists (AC-MIG-27's own
                        # requirement) - so the SEPARATE identities/messages
                        # phases (which walk that table) would have literally
                        # nothing to iterate. For a dry run only, this SAME
                        # per-contact savepoint ALSO previews this contact's
                        # identities + messages inline (D-A6-14: still one
                        # code path - `_process_contact_identities`/
                        # `_process_contact_messages` are the exact same
                        # functions the real phases below call), and the
                        # whole thing rolls back together at the end.
                        if dry_run and not contacts_only:
                            _process_contact_identities(
                                client, writer, outcome.contact_id, external_id,
                                channel_map, channel_type_by_target, source_contact.phone,
                                identity_counts, failures,
                            )
                            preview_contact = (
                                db.query(ContactModel).filter(ContactModel.id == outcome.contact_id).first()
                            )
                            newly_inferred, newly_skipped, newly_over_cap = _process_contact_messages(
                                client, writer, refs, tenant_id, workspace_id, preview_contact, external_id,
                                channel_map, user_map, message_counts, failures, message_samples,
                                messages_since=messages_since_dt,
                            )
                            messages_inferred += newly_inferred
                            messages_skipped_before_floor += newly_skipped
                            messages_skipped_over_cap += newly_over_cap
                    except Exception as exc:  # noqa: BLE001 - per-row isolation (AC-MIG-27/29)
                        nested.rollback()
                        contact_counts["fetched"] += 1
                        contact_counts["errors"] = contact_counts.get("errors", 0) + 1
                        failures.append(
                            {
                                "entity": "contacts", "sourceId": external_id, "sourceLabel": "",
                                "reason": str(exc), "action": "skipped",
                            }
                        )
                        service.advance(job, failed=1)
                        continue

                    if dry_run:
                        nested.rollback()  # D-A6-14: zero rows written anywhere
                    else:
                        nested.commit()  # releases the savepoint into the page's txn

                    contact_counts["fetched"] += 1
                    contact_counts[outcome.kind] = contact_counts.get(outcome.kind, 0) + 1
                    field_counts["fetched"] = field_counts.get("fetched", 0) + outcome.fields_created + outcome.fields_matched
                    field_counts["create"] = field_counts.get("create", 0) + outcome.fields_created
                    field_counts["matched"] = field_counts.get("matched", 0) + outcome.fields_matched
                    field_counts["errors"] = field_counts.get("errors", 0) + outcome.field_errors
                    tag_counts["fetched"] = tag_counts.get("fetched", 0) + outcome.tags_created + outcome.tags_matched
                    tag_counts["create"] = tag_counts.get("create", 0) + outcome.tags_created
                    tag_counts["matched"] = tag_counts.get("matched", 0) + outcome.tags_matched
                    if outcome.lifecycle_unmapped:
                        lifecycle_unmapped += 1
                    if outcome.assignee_unmatched:
                        assignee_unmatched += 1
                    if len(samples) < MAX_REPORT_SAMPLES:
                        samples.append({"name": outcome.source_label, "action": outcome.kind})
                    service.advance(job, done=1)

                # Checkpoint cursor + running counts AFTER EVERY PAGE (AC-MIG-22).
                contact_list_cursor = next_cursor
                checkpoint("contacts")

                # Cooperative abort (AC-MIG-28): re-read status FRESH before the
                # next page/the terminal step - `set_cursor` already committed
                # above, so a cancel committed on another session is visible here.
                if _aborted(db, job.id):
                    service.log(job, f"Aborted after {contact_counts.get('fetched', 0)} contacts.")
                    return
        except RespondIoError as exc:
            service.log(job, f"respond.io error: {exc.message}", level="error")
            service.finish(job, status=JOB_FAILED, error=f"respond.io error: {exc.message}")
            return

        if contacts_only or dry_run:
            # A dry run never reaches the separate identities/messages phases
            # below (their whole design depends on persisted `migration_refs`
            # rows, which a dry run's per-contact rollback never leaves
            # behind) - its identities/messages counts were already gathered
            # INLINE above, per contact, in the SAME rolled-back savepoint.
            finish_done()
            return

        phase = "identities"
        checkpoint("identities")
        if _aborted(db, job.id):
            service.log(job, "Aborted before the identities phase.")
            return

    # ── phase 2 - channel identities (S3, AC-MIG-30/31) ─────────────────────
    if phase == "identities":
        while True:
            ref_batch = refs.paged(
                tenant_id, workspace_id, RESPONDIO_PROVIDER, ENTITY_CONTACT,
                after_id=identity_ref_cursor, limit=CONTACT_REF_BATCH,
            )
            if not ref_batch:
                break
            for ref in ref_batch:
                identity_ref_cursor = ref.id
                local_contact = (
                    db.query(ContactModel)
                    .filter(
                        ContactModel.id == ref.local_id,
                        ContactModel.tenant_id == tenant_id,
                        ContactModel.workspace_id == workspace_id,
                    )
                    .first()
                )
                if local_contact is None:  # contact row vanished after being migrated
                    checkpoint("identities")
                    if _aborted(db, job.id):
                        service.log(job, "Aborted during the identities phase.")
                        return
                    continue

                nested = db.begin_nested()
                _process_contact_identities(
                    client, writer, local_contact.id, ref.external_id,
                    channel_map, channel_type_by_target, local_contact.phone,
                    identity_counts, failures,
                )
                # This phase only runs for a REAL (non-dry) run (a dry run
                # finishes right after the contacts loop, above) - `commit`
                # unconditionally, `rollback` is dead code kept only as a
                # defensive mirror of every other phase's own pattern.
                if dry_run:  # pragma: no cover - unreachable, see the comment above
                    nested.rollback()
                else:
                    nested.commit()
                service.advance(job, done=1)
                checkpoint("identities")
                if _aborted(db, job.id):
                    service.log(job, "Aborted during the identities phase.")
                    return

        phase = "messages"
        identity_ref_cursor = None
        checkpoint("messages")
        if _aborted(db, job.id):
            service.log(job, "Aborted before the messages phase.")
            return

    # ── phase 3 - message history (S3, AC-MIG-32..37) ───────────────────────
    if phase == "messages":
        while True:
            ref_batch = refs.paged(
                tenant_id, workspace_id, RESPONDIO_PROVIDER, ENTITY_CONTACT,
                after_id=message_ref_cursor, limit=CONTACT_REF_BATCH,
            )
            if not ref_batch:
                break
            for ref in ref_batch:
                message_ref_cursor = ref.id
                local_contact = (
                    db.query(ContactModel)
                    .filter(
                        ContactModel.id == ref.local_id,
                        ContactModel.tenant_id == tenant_id,
                        ContactModel.workspace_id == workspace_id,
                    )
                    .first()
                )
                if local_contact is None:
                    checkpoint("messages")
                    if _aborted(db, job.id):
                        service.log(job, "Aborted during the messages phase.")
                        return
                    continue

                nested = db.begin_nested()
                newly_inferred, newly_skipped, newly_over_cap = _process_contact_messages(
                    client, writer, refs, tenant_id, workspace_id, local_contact, ref.external_id,
                    channel_map, user_map, message_counts, failures, message_samples,
                    messages_since=messages_since_dt,
                )
                messages_inferred += newly_inferred
                messages_skipped_before_floor += newly_skipped
                messages_skipped_over_cap += newly_over_cap
                # This phase only runs for a REAL (non-dry) run - see the
                # identities phase's identical comment above.
                if dry_run:  # pragma: no cover - unreachable, see the comment above
                    nested.rollback()
                else:
                    nested.commit()
                service.advance(job, done=1)
                checkpoint("messages")
                if _aborted(db, job.id):
                    service.log(job, "Aborted during the messages phase.")
                    return

        phase = "media"
        message_ref_cursor = None
        checkpoint("media")
        if _aborted(db, job.id):
            service.log(job, "Aborted before the media phase.")
            return

    # ── phase 4 - media (S4, AC-MIG-39/40) ──────────────────────────────────
    if phase == "media":
        while True:
            ref_batch = refs.paged(
                tenant_id, workspace_id, RESPONDIO_PROVIDER, ENTITY_MESSAGE,
                after_id=media_ref_cursor, limit=MEDIA_REF_BATCH,
            )
            if not ref_batch:
                break
            for ref in ref_batch:
                media_ref_cursor = ref.id
                message = (
                    db.query(ConversationMessage)
                    .filter(
                        ConversationMessage.id == ref.local_id,
                        ConversationMessage.tenant_id == tenant_id,
                    )
                    .first()
                )
                if message is None:  # the migrated row vanished after being written
                    checkpoint("media")
                    if _aborted(db, job.id):
                        service.log(job, "Aborted during the media phase.")
                        return
                    continue

                nested = db.begin_nested()
                _process_message_media(writer, tenant_id, workspace_id, message, media_counts, failures)
                # Media, like identities/messages, only runs for a REAL
                # (non-dry) run - a dry run finishes right after the contacts
                # loop, above (AC-MIG-27: no media URL is ever fetched there).
                if dry_run:  # pragma: no cover - unreachable, see the comment above
                    nested.rollback()
                else:
                    nested.commit()
                service.advance(job, done=1)
                checkpoint("media")
                if _aborted(db, job.id):
                    service.log(job, "Aborted during the media phase.")
                    return

        phase = "events"
        media_ref_cursor = None
        checkpoint("events")
        if _aborted(db, job.id):
            service.log(job, "Aborted before the events phase.")
            return

    # ── phase 5 - derived conversation_events (S4, AC-MIG-41/42) ────────────
    if phase == "events":
        while True:
            ref_batch = refs.paged(
                tenant_id, workspace_id, RESPONDIO_PROVIDER, ENTITY_CONTACT,
                after_id=event_ref_cursor, limit=CONTACT_REF_BATCH,
            )
            if not ref_batch:
                break
            for ref in ref_batch:
                event_ref_cursor = ref.id
                local_contact = (
                    db.query(ContactModel)
                    .filter(
                        ContactModel.id == ref.local_id,
                        ContactModel.tenant_id == tenant_id,
                        ContactModel.workspace_id == workspace_id,
                    )
                    .first()
                )
                if local_contact is None:
                    checkpoint("events")
                    if _aborted(db, job.id):
                        service.log(job, "Aborted during the events phase.")
                        return
                    continue

                nested = db.begin_nested()
                _process_contact_events(
                    client, writer, refs, tenant_id, workspace_id, local_contact, ref.external_id,
                    event_counts, failures,
                )
                if dry_run:  # pragma: no cover - unreachable, see the comment above
                    nested.rollback()
                else:
                    nested.commit()
                service.advance(job, done=1)
                checkpoint("events")
                if _aborted(db, job.id):
                    service.log(job, "Aborted during the events phase.")
                    return

        phase = "quick_replies"
        event_ref_cursor = None
        checkpoint("quick_replies")
        if _aborted(db, job.id):
            service.log(job, "Aborted before the quick_replies phase.")
            return

    # ── phase 6 - quick replies from a snippets CSV (S4, AC-MIG-44) ─────────
    if phase == "quick_replies":
        # A single bounded pass (`settings.import_max_rows`, not a paginated
        # walk) - the whole point of a snippets CSV is that it is small; no
        # separate resumability is needed beyond re-running the same CSV,
        # which `write_quick_reply`'s own migration_refs check already makes
        # idempotent (AC-MIG-44/45).
        nested = db.begin_nested()
        _process_quick_replies_csv(
            db, tenant_id, writer, payload.get("snippetsCsvKey"), quick_reply_counts, failures
        )
        if dry_run:  # pragma: no cover - unreachable, see the comment above
            nested.rollback()
        else:
            nested.commit()
        checkpoint("quick_replies")
        if _aborted(db, job.id):
            service.log(job, "Aborted during the quick_replies phase.")
            return

    finish_done()


MIGRATION_JOB_HANDLER_DEF = JobHandlerDef(MIGRATION_JOB_TYPE, run_migration_job, "respond.io migration")


def register_migration_job_handler() -> None:
    """Idempotent - the SAME def object re-registers cleanly (mirrors every
    other job handler's own boot registration, e.g. `contact_export_service.
    register_contacts_export_handler`)."""
    register_job_handler(MIGRATION_JOB_HANDLER_DEF)
