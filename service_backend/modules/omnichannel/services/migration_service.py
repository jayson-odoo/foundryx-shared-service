"""respond.io migration - S1 owns ``MigrationPreflightService`` (the
read-only preflight, AC-MIG-14). S2 adds ``MigrationService`` (phase
orchestration, cursor writes, cooperative abort, dry-run gate, mapping hash,
report assembly, plan §2.1) to this SAME file - kept together because S2's
service reuses this one's connection/workspace resolution helpers.
"""
import base64
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
from app.secrets import decrypt_secret
from app.status_engine.scoped import get_scope_status

from ..models import Channel, ConversationMessage
from ..models import Contact as ContactModel
from ..repositories.migration_connection_repository import MigrationConnectionRepository
from ..repositories.migration_ref_repository import MigrationRefRepository
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
    WorkspaceItem,
)
from . import migration_media
from .lifecycle_service import ENTITY_TYPE as LIFECYCLE_ENTITY_TYPE
from .lifecycle_service import initial_status_id, stages_for_workspace
from .migration_writer import (
    ENTITY_CONTACT,
    ENTITY_EVENT,
    ENTITY_MESSAGE,
    MigrationWriter,
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


def _build_report(
    counts: Dict[str, Any],
    samples: List[dict],
    lifecycle_unmapped: int,
    *,
    messages_with_inferred: int = 0,
    message_samples: Optional[List[dict]] = None,
    messages_skipped_before_floor: int = 0,
) -> dict:
    contacts_c = counts.get("contacts") or {}
    fields_c = counts.get("fields") or {}
    tags_c = counts.get("tags") or {}
    identities_c = counts.get("identities") or {}
    messages_c = counts.get("messages") or {}
    media_c = counts.get("media") or {}
    events_c = counts.get("events") or {}
    quick_replies_c = counts.get("quickReplies") or {}
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


def _resolve_user_map(db: Session, tenant_id: str, payload: Dict[str, Any]) -> Dict[str, str]:
    """``sourceUserId(str) -> targetUserId(str)``, re-validated tenant-scoped
    at USE time (AC-MIG-51/32) - consumed ONLY by the messages phase's sender
    mapping; the contacts phase's assignee resolution is email-only and never
    touches this map (D-A6-26)."""
    target_ids = {
        str(entry.get("targetUserId")) for entry in payload.get("userMap") or [] if entry.get("targetUserId")
    }
    valid_ids: set = set()
    if target_ids:
        valid_ids = {
            r[0] for r in db.query(User.id).filter(User.tenant_id == tenant_id, User.id.in_(target_ids)).all()
        }
    user_map: Dict[str, str] = {}
    for entry in payload.get("userMap") or []:
        source_id = str(entry.get("sourceUserId") or "")
        target_id = entry.get("targetUserId")
        if source_id and target_id and target_id in valid_ids:
            user_map[source_id] = target_id
    return user_map


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
            # S4 (AC-MIG-44) - carried through verbatim; empty/absent means
            # "no snippets CSV supplied", a legitimate no-op for the
            # quick_replies phase, not a validation error.
            "snippetsCsvBase64": payload.snippetsCsvBase64,
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
        messages_counts = counts.get("messages") or {}
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
) -> Tuple[int, int]:
    """One contact's FULL message-history walk - buffered, sorted by
    `messageId`, timestamp-resolved as ONE unit (D-A6-9 needs the whole
    contact's history bracketed together). Shared by the real per-ref
    "messages" phase AND the dry-run inline preview. Returns
    `(newly_inferred, newly_skipped_before_floor)` - plain ints, not shared
    counters (the caller accumulates both).

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
            fallback_dt = datetime.fromtimestamp(int(source_created_at), tz=timezone.utc)
    except (RespondIoError, TypeError, ValueError) as exc:
        failures.append(
            {
                "entity": "messages", "sourceId": contact_external_id, "sourceLabel": "",
                "reason": f"could not re-fetch source contact for its created_at fallback: {exc}",
                "action": "used local contact.created_at instead",
            }
        )

    buffered_raw: List[dict] = []
    try:
        for page_items, _next in client.list_messages_pages(identifier, limit=MESSAGES_PAGE_LIMIT):
            buffered_raw.extend(page_items)
    except RespondIoError as exc:
        message_counts["errors"] = message_counts.get("errors", 0) + 1
        failures.append(
            {
                "entity": "messages", "sourceId": contact_external_id, "sourceLabel": "",
                "reason": exc.message, "action": "skipped",
            }
        )
        return 0, 0

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
    resolved = resolve_message_timestamps(parsed_items, fallback_dt)

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
    return newly_inferred, skipped_before_floor


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
    writer: MigrationWriter, csv_base64: Optional[str], qr_counts: Dict[str, int], failures: List[dict]
) -> None:
    """Respond.io exposes no snippets endpoint (D-A6-19/F3) - this reads the
    2-column (`shortcut`, `body`) CSV the operator uploaded alongside the job
    (base64 in the payload, see `MigrationJobCreate.snippetsCsvBase64`'s own
    docstring) through the SAME `app/import_engine/readers.py` sniff/cap the
    rest of the platform's imports use. A no-op (zero counts) when no CSV was
    supplied - not a failure, a legitimate "API-only, no snippets" run."""
    if not csv_base64:
        return
    try:
        content = base64.b64decode(csv_base64, validate=True)
    except Exception:  # noqa: BLE001 - bad upload, never abort the job
        failures.append(
            {
                "entity": "quickReplies", "sourceId": "", "sourceLabel": "",
                "reason": "Could not decode the snippets CSV upload.", "action": "skipped",
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
    fetched" during a dry run is therefore structural, not a branch)."""
    service = JobService(db)
    tenant_id = job.tenant_id
    payload = job.payload_json or {}
    workspace_id = payload.get("workspaceId")
    connection_id = payload.get("connectionId")
    dry_run = payload.get("mode") == "dry_run"
    contacts_only = bool(payload.get("contactsOnly"))

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
    user_map = _resolve_user_map(db, tenant_id, payload)

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
        thread_closed_status_id=thread_closed_id,
        initial_lifecycle_status_id=initial_lifecycle_id,
        lifecycle_map=lifecycle_map,
        source_field_defs=source_field_defs,
        writes_enabled=not dry_run,
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
        )
        result = {
            "report": report,
            "failures": {"rowCount": len(failures), "rows": failures[:MAX_FAILURE_ROWS_KEPT]},
        }
        service.finish(job, status=JOB_DONE, result=result)

    # ── phase 1 - contacts (S2, unchanged) ──────────────────────────────────
    if phase == "contacts":
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
                            newly_inferred, newly_skipped = _process_contact_messages(
                                client, writer, refs, tenant_id, workspace_id, preview_contact, external_id,
                                channel_map, user_map, message_counts, failures, message_samples,
                                messages_since=messages_since_dt,
                            )
                            messages_inferred += newly_inferred
                            messages_skipped_before_floor += newly_skipped
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
                newly_inferred, newly_skipped = _process_contact_messages(
                    client, writer, refs, tenant_id, workspace_id, local_contact, ref.external_id,
                    channel_map, user_map, message_counts, failures, message_samples,
                    messages_since=messages_since_dt,
                )
                messages_inferred += newly_inferred
                messages_skipped_before_floor += newly_skipped
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
        _process_quick_replies_csv(writer, payload.get("snippetsCsvBase64"), quick_reply_counts, failures)
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
