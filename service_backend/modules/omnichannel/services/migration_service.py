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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from cryptography.fernet import InvalidToken
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

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
from app.secrets import decrypt_secret
from app.status_engine.scoped import get_scope_status

from ..models import Channel
from ..repositories.migration_connection_repository import MigrationConnectionRepository
from ..respondio.channel_map import target_channel_type_for
from ..respondio.client import RespondIoClient, RespondIoError
from ..respondio.shapes import Contact, CustomField, SpaceChannel, SpaceUser
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
    WorkspaceItem,
)
from .lifecycle_service import ENTITY_TYPE as LIFECYCLE_ENTITY_TYPE
from .lifecycle_service import initial_status_id, stages_for_workspace
from .migration_writer import MigrationWriter
from .statuses import status_id_for
from .workspace_service import WorkspaceNotFound, WorkspaceService

logger = logging.getLogger(__name__)

RESPONDIO_PROVIDER = "respondio"
MIGRATION_JOB_TYPE = "omnichannel.respondio_migration"
# 24h + mapping-hash gate (D-A6-14, AC-MIG-20) - a `run` needs a successful
# `dry_run` of the SAME mapping inside this window.
DRY_RUN_TTL_HOURS = 24
CONTACTS_PAGE_LIMIT = 100
MAX_REPORT_SAMPLES = 10
MAX_FAILURE_ROWS_KEPT = 5000  # bounds background_jobs.result_json size (S3+ note below)

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
    }
    blob = json.dumps(canonical, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _zero_counts() -> Dict[str, int]:
    return {"fetched": 0, "wouldCreate": 0, "wouldUpdate": 0, "wouldSkip": 0, "errors": 0}


def _build_report(counts: Dict[str, Any], samples: List[dict], lifecycle_unmapped: int) -> dict:
    contacts_c = counts.get("contacts") or {}
    fields_c = counts.get("fields") or {}
    tags_c = counts.get("tags") or {}
    blockers: List[str] = []
    if lifecycle_unmapped:
        blockers.append(
            f"{lifecycle_unmapped} contact(s) have no lifecycle mapping and will land "
            "with no lifecycle stage."
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
            # S3/S4 phases - genuinely zero in S2 (never walked this run).
            "identities": _zero_counts(),
            "messages": _zero_counts(),
            "media": _zero_counts(),
            "events": _zero_counts(),
            "quickReplies": _zero_counts(),
        },
        "messagesWithInferredTimestamp": 0,
        "blockers": blockers,
        "samples": {"contacts": samples, "messages": []},
    }


def _aborted(db: Session, job_id: str) -> bool:
    """Re-read the job's status FRESH from the DB - a concurrent cancel
    commits `aborted` on a DIFFERENT session (mirrors `contact_export_
    service._aborted` / `app/storage_migration/service.py`'s own helper)."""
    return db.query(BackgroundJob.status).filter(BackgroundJob.id == job_id).scalar() == JOB_ABORTED


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

        parsed_messages_since: Optional[str] = None
        if payload.messagesSince:
            try:
                raw = payload.messagesSince.replace("Z", "+00:00")
                parsed_messages_since = datetime.fromisoformat(raw).astimezone(timezone.utc).isoformat()
            except ValueError:
                errors["messagesSince"] = "messagesSince must be an ISO-8601 date/time."

        return errors, parsed_messages_since

    def _in_progress_job(self, tenant_id: str, workspace_id: str) -> Optional[BackgroundJob]:
        for job in self.jobs.repo.active_of_type(
            tenant_id, MIGRATION_JOB_TYPE, (JOB_PENDING, JOB_RUNNING, JOB_NEEDS_REVIEW)
        ):
            if (job.payload_json or {}).get("workspaceId") == workspace_id:
                return job
        return None

    def _has_fresh_dry_run(self, tenant_id: str, workspace_id: str, mapping_hash: str) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=DRY_RUN_TTL_HOURS)
        rows = (
            self.db.query(BackgroundJob)
            .filter(
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.type == MIGRATION_JOB_TYPE,
                BackgroundJob.status == JOB_DONE,
            )
            .order_by(BackgroundJob.finished_at.desc())
            .all()
        )
        for job in rows:
            p = job.payload_json or {}
            if (
                p.get("mode") == "dry_run"
                and p.get("workspaceId") == workspace_id
                and p.get("mappingHash") == mapping_hash
                and job.finished_at is not None
                and job.finished_at >= cutoff
            ):
                return True
        return False

    def create_job(
        self, tenant_id: str, actor_user_id: Optional[str], payload: MigrationJobCreate
    ) -> MigrationJobItem:
        connection = self._require_connection(tenant_id, payload.connectionId)
        workspace = self._require_workspace(tenant_id, payload.workspaceId)

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
            "connectionId": payload.connectionId,
            "workspaceId": payload.workspaceId,
            "channelMap": [e.model_dump() for e in payload.channelMap],
            "userMap": [e.model_dump() for e in payload.userMap],
            "teamMap": [e.model_dump() for e in payload.teamMap],
            "lifecycleMap": [e.model_dump() for e in payload.lifecycleMap],
            "messagesSince": parsed_messages_since,
            "contactsOnly": bool(payload.contactsOnly),
            "mappingHash": mapping_hash,
            # Denormalized (the Broadcast-model convention, `models.py
            # template_name`) - a renamed/retired connection or workspace must
            # not blank out this job's history row.
            "spaceLabel": str((connection.config_json or {}).get("spaceLabel") or ""),
            "workspaceName": workspace.name,
        }
        job = self.jobs.create_and_enqueue(
            type=MIGRATION_JOB_TYPE, tenant_id=tenant_id, actor_user_id=actor_user_id, payload=job_payload
        )
        return self._to_item(job, tenant_id)

    # ── reads ────────────────────────────────────────────────────────────────

    def list_jobs(
        self, tenant_id: str, *, page: int, page_size: int, status_filter: Optional[str]
    ) -> MigrationJobListResponse:
        rows, total = self.jobs.list(
            tenant_id, job_type=MIGRATION_JOB_TYPE, status=status_filter, page=page, page_size=page_size
        )
        actor_ids = {r.actor_user_id for r in rows if r.actor_user_id}
        actor_names: Dict[str, str] = {}
        if actor_ids:
            for u in self.db.query(User).filter(User.tenant_id == tenant_id, User.id.in_(actor_ids)).all():
                actor_names[u.id] = u.name or u.email
        items = [self._to_item(r, tenant_id, actor_names=actor_names) for r in rows]
        return MigrationJobListResponse(data=items, total=total, page=page)

    def get_job(self, tenant_id: str, job_id: str) -> MigrationJobItem:
        job = self._require_job(tenant_id, job_id)
        return self._to_item(job, tenant_id)

    def failures_csv(self, tenant_id: str, job_id: str) -> str:
        job = self._require_job(tenant_id, job_id)
        rows = ((job.result_json or {}).get("failures") or {}).get("rows") or []
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
        self, job: BackgroundJob, tenant_id: str, *, actor_names: Optional[Dict[str, str]] = None
    ) -> MigrationJobItem:
        payload = job.payload_json or {}
        cursor = job.cursor_json or {}
        counts = cursor.get("counts") or {}
        contacts_counts = counts.get("contacts") or {}
        result = job.result_json or {}
        report = result.get("report")
        failures = result.get("failures") or {}
        failure_rows = failures.get("rows") or []

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
            entityCounts={"contacts": contacts_counts.get("fetched", 0), "messages": 0},
            report=report,
            failureCount=failures.get("rowCount", len(failure_rows)),
            failureSample=failure_rows[:50],
            startedAt=job.started_at,
            finishedAt=job.finished_at,
            createdAt=job.created_at,
            actorUserName=actor_name,
        )

    # ── cancel (AC-MIG-28) ───────────────────────────────────────────────────

    def cancel_job(self, tenant_id: str, job_id: str) -> MigrationJobItem:
        job = self._require_job(tenant_id, job_id)
        if job.status not in (JOB_PENDING, JOB_RUNNING):
            raise MigrationJobConflict("not_in_progress", "This migration is not in progress.")
        self.jobs.finish(job, status=JOB_ABORTED, result=job.result_json)
        return self._to_item(job, tenant_id)


# ── job handler (registered via register_job_handler, plan §5.2/§2.1) ──────


def run_migration_job(db: Session, job: BackgroundJob) -> None:
    """`omnichannel.respondio_migration` job handler - S2 implements the
    CONTACTS phase only (§2.1's later phases land in S3/S4 on this SAME
    handler/writer). Dry run and real run share this ONE code path
    (D-A6-14): each contact's write happens inside its OWN SAVEPOINT
    (`db.begin_nested()`) which is COMMITTED (released into the page's
    pending transaction) on a real run or unconditionally ROLLED BACK on a
    dry run - the per-contact scope also isolates one bad row's failure from
    the rest of an in-flight page (a flush error would otherwise poison the
    whole session)."""
    service = JobService(db)
    tenant_id = job.tenant_id
    payload = job.payload_json or {}
    workspace_id = payload.get("workspaceId")
    connection_id = payload.get("connectionId")
    dry_run = payload.get("mode") == "dry_run"

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

    def milestone(msg: str) -> None:
        service.log(job, msg)

    client = RespondIoClient.from_connection(config, credentials, on_milestone=milestone)

    # Re-validate every mapped id AT USE TIME, never trust save-time
    # validation alone (AC-MIG-51) - a stage/channel deleted between create
    # and run silently drops out of the map rather than crashing the run.
    lifecycle_map: Dict[str, str] = {}
    for entry in payload.get("lifecycleMap") or []:
        target = entry.get("targetStatusId")
        source_label = str(entry.get("sourceLabel") or "").strip().lower()
        if not target or not source_label:
            continue
        if get_scope_status(db, LIFECYCLE_ENTITY_TYPE, tenant_id, workspace_id, target) is not None:
            lifecycle_map[source_label] = target

    thread_open_id = status_id_for(db, tenant_id, "THREAD", "OPEN")
    initial_lifecycle_id = initial_status_id(db, tenant_id, workspace_id)

    try:
        source_field_defs: Dict[str, Dict[str, Any]] = {}
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
        initial_lifecycle_status_id=initial_lifecycle_id,
        lifecycle_map=lifecycle_map,
        source_field_defs=source_field_defs,
        writes_enabled=not dry_run,
    )

    cursor = job.cursor_json or {}
    counts: Dict[str, Any] = dict(cursor.get("counts") or {})
    contact_counts = dict(counts.get("contacts") or {"fetched": 0, "create": 0, "update": 0, "errors": 0})
    field_counts = dict(counts.get("fields") or {"fetched": 0, "create": 0, "matched": 0, "errors": 0})
    tag_counts = dict(counts.get("tags") or {"fetched": 0, "create": 0, "matched": 0})
    lifecycle_unmapped = int(counts.get("lifecycleUnmappedCount") or 0)
    assignee_unmatched = int(counts.get("assigneeUnmatchedCount") or 0)

    prior_result = job.result_json or {}
    failures: List[dict] = list((prior_result.get("failures") or {}).get("rows") or [])
    samples: List[dict] = list((prior_result.get("report") or {}).get("samples", {}).get("contacts") or [])

    start_cursor = cursor.get("contactCursorId")

    try:
        for page_items, next_cursor in client.list_contacts_pages(
            timezone=space_timezone, limit=CONTACTS_PAGE_LIMIT, start_cursor=start_cursor
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
            counts["contacts"] = contact_counts
            counts["fields"] = field_counts
            counts["tags"] = tag_counts
            counts["lifecycleUnmappedCount"] = lifecycle_unmapped
            counts["assigneeUnmatchedCount"] = assignee_unmatched
            service.set_cursor(job, {"phase": "contacts", "contactCursorId": next_cursor, "counts": counts})

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

    service.set_total(job, contact_counts.get("fetched", 0))
    report = _build_report(counts, samples, lifecycle_unmapped)
    result = {
        "report": report,
        "failures": {"rowCount": len(failures), "rows": failures[:MAX_FAILURE_ROWS_KEPT]},
    }
    service.finish(job, status=JOB_DONE, result=result)


MIGRATION_JOB_HANDLER_DEF = JobHandlerDef(MIGRATION_JOB_TYPE, run_migration_job, "respond.io migration")


def register_migration_job_handler() -> None:
    """Idempotent - the SAME def object re-registers cleanly (mirrors every
    other job handler's own boot registration, e.g. `contact_export_service.
    register_contacts_export_handler`)."""
    register_job_handler(MIGRATION_JOB_HANDLER_DEF)
