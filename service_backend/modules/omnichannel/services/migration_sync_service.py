"""Continuous respond.io sync until cutover (plan 52, lane SS-MIGRATION-SYNC).

One ``migration_syncs`` row per (tenant, workspace); every tick is a
``background_jobs`` row of type ``omnichannel.respondio_sync`` (D1). The tick
reuses the one-off migration's per-contact helpers (identities, messages,
media, events) unchanged, with a ``MigrationWriter(contact_mode="source_wins")``
for the contact row itself (D7).

Parts, top to bottom:
- ``MigrationSyncService``  - lifecycle (create/pause/resume/stop/...) + item
- ``run_due_syncs``         - the 60 s beat body (D4)
- ``record_hint``           - the public webhook body (D5/D6)
- ``run_sync_job``          - the tick handler (poll / hints / final)
"""
import hmac
import html
import json
import logging
import math
import re
import secrets as _secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.jobs.registry import JobHandlerDef, register_job_handler
from app.jobs.service import JobService
from app.models.background_job import (
    JOB_DONE,
    JOB_FAILED,
    JOB_NEEDS_REVIEW,
    JOB_PENDING,
    JOB_RUNNING,
    JOB_TERMINAL_STATUSES,
    BackgroundJob,
)
from app.repositories.module_repository import ModuleRepository
from app.secrets import decrypt_secret, encrypt_secret
from app.services.email_service import email_service
from app.status_engine.scoped import get_scope_status

from ..models import Contact as ContactModel
from ..models import ConversationMessage, MigrationSync
from ..repositories.migration_connection_repository import MigrationConnectionRepository
from ..repositories.migration_ref_repository import MigrationRefRepository
from ..repositories.migration_sync_repository import MigrationSyncRepository
from ..respondio.client import DEFAULT_REQUESTS_PER_SECOND, RespondIoClient, RespondIoError
from ..respondio.shapes import Contact, CustomField, SpaceUser
from ..schemas import MigrationSyncCounters, MigrationSyncItem, MigrationSyncResult
from .lifecycle_service import ENTITY_TYPE as LIFECYCLE_ENTITY_TYPE
from .lifecycle_service import initial_status_id
from .migration_service import (
    MIGRATION_JOB_TYPE,
    RESPONDIO_PROVIDER,
    SYNC_JOB_TYPE,
    CONTACTS_PAGE_LIMIT,
    _decrypt_or_none,
    _failure_reason,
    _process_contact_events,
    _process_contact_identities,
    _process_contact_messages,
    _process_message_media,
    _resolve_channel_map,
    _resolve_team_map,
    _resolve_user_map,
    parse_rows,
)
from .migration_writer import ENTITY_CONTACT, MigrationWriter
from .statuses import status_id_for

logger = logging.getLogger("foundryx.omnichannel.migration_sync")

__all__ = [
    "SYNC_JOB_TYPE",
    "MigrationSyncService",
    "SyncConflict",
    "SyncNotFound",
    "record_hint",
    "register_sync_job_handler",
    "run_due_syncs",
    "run_sync_job",
]

MODULE_NAME = "omnichannel"

STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUS_STOPPING = "stopping"
STATUS_STOPPED = "stopped"

KIND_POLL = "poll"
KIND_HINTS = "hints"
KIND_FINAL = "final"
_KINDS = (KIND_POLL, KIND_HINTS, KIND_FINAL)

INTERVAL_MINUTES = 15
FULL_SWEEP_HOURS = 6
HINT_CAP = 5000
HOOK_MAX_BYTES = 64 * 1024
HINTS_PER_TICK = 1000
CSW_HOURS = 24
FAILURE_SAMPLE = 50
FAILURE_KEEP = 200

# Held in `running_job_id` between the guarded claim and the job row existing.
_CLAIM_PLACEHOLDER = "claiming"
_CLAIM_STALE = timedelta(minutes=5)

_USABLE_ID = re.compile(r"[0-9]{1,20}")

PAUSE_TOKEN_REJECTED = "token_rejected"
PAUSE_CONNECTION_MISSING = "connection_missing"
PAUSE_WORKSPACE_MISSING = "workspace_missing"
PAUSE_MANUAL = "manual"


class SyncConflict(Exception):
    """409 - carries the wire ``reason``."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


class SyncNotFound(Exception):
    """Uniform 404 (unknown, foreign tenant, or a failed webhook check)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _zero_counters() -> Dict[str, int]:
    return {"contactsCreated": 0, "contactsUpdated": 0, "messagesCreated": 0, "messagesSkipped": 0, "errors": 0}


def _counters(raw: Optional[Dict[str, Any]]) -> Dict[str, int]:
    out = _zero_counters()
    for key in out:
        try:
            out[key] = int((raw or {}).get(key) or 0)
        except (TypeError, ValueError):
            out[key] = 0
    return out


def _estimated_minutes(contacts: Optional[int], rps: float) -> Optional[int]:
    if contacts is None:
        return None
    rate = rps if rps and rps > 0 else float(DEFAULT_REQUESTS_PER_SECOND)
    return int(math.ceil(contacts * 3 / rate / 60))


# ── lifecycle + reads ───────────────────────────────────────────────────────


class MigrationSyncService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = MigrationSyncRepository(db)

    # -- resolution (tenant-scoped, uniform 404) ------------------------------

    def _require(self, tenant_id: str, sync_id: str) -> MigrationSync:
        sync = self.repo.get(tenant_id, sync_id)
        if sync is None:
            raise SyncNotFound()
        return sync

    def _source_run(self, tenant_id: str, workspace_id: str) -> Optional[BackgroundJob]:
        """The newest DONE real API-mode run of the workspace (D2)."""
        return self.repo.newest_done_run(
            tenant_id, MIGRATION_JOB_TYPE, workspace_id, mode="run", source="api"
        )

    def _contact_count_hint(self, tenant_id: str, workspace_id: str, run: Optional[BackgroundJob]) -> Optional[int]:
        """D13 - the latest dry run's fetched contacts (else the run's own)."""
        sources = [
            self.repo.newest_done_run(tenant_id, MIGRATION_JOB_TYPE, workspace_id, mode="dry_run", source=None),
            run,
        ]
        for job in sources:
            if job is None:
                continue
            fetched = (
                ((((job.result_json or {}).get("report") or {}).get("entities") or {}).get("contacts") or {})
            ).get("fetched")
            if isinstance(fetched, int):
                return fetched
        return None

    def _rps(self, tenant_id: str, run: Optional[BackgroundJob]) -> float:
        connection_id = ((run.payload_json or {}).get("connectionId") if run is not None else None) or ""
        if not connection_id:
            return float(DEFAULT_REQUESTS_PER_SECOND)
        connection = MigrationConnectionRepository(self.db).get_for_provider(
            tenant_id, connection_id, RESPONDIO_PROVIDER
        )
        if connection is None:
            return float(DEFAULT_REQUESTS_PER_SECOND)
        try:
            return float((connection.config_json or {}).get("requestsPerSecond") or DEFAULT_REQUESTS_PER_SECOND)
        except (TypeError, ValueError):
            return float(DEFAULT_REQUESTS_PER_SECOND)

    def to_item(self, sync: MigrationSync) -> MigrationSyncItem:
        run = self._source_run(sync.tenant_id, sync.workspace_id)
        last = sync.last_result_json
        result = None
        if isinstance(last, dict):
            result = MigrationSyncResult(**_counters(last), failureSample=list(last.get("failureSample") or []))
        totals = MigrationSyncCounters(**_counters(sync.totals_json)) if sync.totals_json else None
        return MigrationSyncItem(
            id=sync.id,
            workspaceId=sync.workspace_id,
            status=sync.status,
            pausedReason=sync.paused_reason,
            intervalMinutes=sync.interval_minutes,
            fullSweepHours=sync.full_sweep_hours,
            lastSyncAt=sync.last_sync_at,
            nextSyncAt=sync.next_sync_at,
            lastFullSweepAt=sync.last_full_sweep_at,
            runningJobId=sync.running_job_id,
            lastError=sync.last_error,
            lastResult=result,
            totals=totals,
            sourceContactCount=sync.source_contact_count,
            estimatedFullSweepMinutes=_estimated_minutes(
                sync.source_contact_count, self._rps(sync.tenant_id, run)
            ),
            sourceJobId=run.id if run is not None else None,
            stoppedAt=sync.stopped_at,
            createdAt=sync.created_at,
        )

    def get_for_workspace(self, tenant_id: str, workspace_id: str) -> Optional[MigrationSyncItem]:
        sync = self.repo.get_by_workspace(tenant_id, workspace_id)
        return self.to_item(sync) if sync is not None else None

    def get(self, tenant_id: str, sync_id: str) -> MigrationSyncItem:
        return self.to_item(self._require(tenant_id, sync_id))

    # -- create / reactivate --------------------------------------------------

    def create(self, tenant_id: str, actor_user_id: Optional[str], workspace_id: str) -> MigrationSyncItem:
        workspace = self.repo.workspace(tenant_id, workspace_id)
        if workspace is None or workspace.is_trashed:
            raise SyncNotFound()
        existing = self.repo.get_by_workspace(tenant_id, workspace_id)
        if existing is not None and existing.status != STATUS_STOPPED:
            raise SyncConflict("sync_exists", "A sync already exists for this workspace.")
        run = self._source_run(tenant_id, workspace_id)
        if run is None:
            raise SyncConflict("no_finished_migration", "Finish a migration for this workspace first.")

        now = _now()
        secret_enc = encrypt_secret({"secret": _secrets.token_urlsafe(32)})
        if existing is not None:
            existing.status = STATUS_ACTIVE
            existing.paused_reason = None
            existing.webhook_secret_enc = secret_enc
            existing.created_by_user_id = actor_user_id
            existing.stopped_at = None
            existing.running_job_id = None
            existing.last_error = None
            existing.next_sync_at = now
            sync = existing
        else:
            sync = self.repo.add(
                MigrationSync(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    status=STATUS_ACTIVE,
                    interval_minutes=INTERVAL_MINUTES,
                    full_sweep_hours=FULL_SWEEP_HOURS,
                    webhook_secret_enc=secret_enc,
                    created_by_user_id=actor_user_id,
                    next_sync_at=now,
                    # the migration itself just read everything: the first
                    # poll must not repeat that as a full sweep
                    last_full_sweep_at=_aware(run.finished_at),
                    source_contact_count=self._contact_count_hint(tenant_id, workspace_id, run),
                )
            )
        self.db.commit()
        return self.to_item(sync)

    # -- tick running? --------------------------------------------------------

    def _tick_running(self, sync: MigrationSync) -> bool:
        rid = sync.running_job_id
        if not rid:
            return False
        if rid == _CLAIM_PLACEHOLDER:
            return True
        job = self.repo.get_job(sync.tenant_id, rid)
        return job is not None and job.status in (JOB_PENDING, JOB_RUNNING)

    # -- actions ----------------------------------------------------------------

    def run_now(self, tenant_id: str, sync_id: str) -> MigrationSyncItem:
        sync = self._require(tenant_id, sync_id)
        if sync.status != STATUS_ACTIVE:
            raise SyncConflict("not_active", "Only an active sync can run now.")
        if self._tick_running(sync):
            raise SyncConflict("tick_running", "A sync is already running.")
        self.repo.update(tenant_id, sync_id, next_sync_at=_now())
        self.db.commit()
        return self.get(tenant_id, sync_id)

    def pause(self, tenant_id: str, sync_id: str) -> MigrationSyncItem:
        sync = self._require(tenant_id, sync_id)
        if sync.status != STATUS_ACTIVE:
            raise SyncConflict("not_active", "Only an active sync can be paused.")
        self.repo.update_if(
            tenant_id, sync_id, [MigrationSync.status == STATUS_ACTIVE],
            status=STATUS_PAUSED, paused_reason=PAUSE_MANUAL,
        )
        self.db.commit()
        return self.get(tenant_id, sync_id)

    def resume(self, tenant_id: str, sync_id: str) -> MigrationSyncItem:
        sync = self._require(tenant_id, sync_id)
        if sync.status != STATUS_PAUSED:
            raise SyncConflict("not_paused", "Only a paused sync can be resumed.")
        self.repo.update_if(
            tenant_id, sync_id, [MigrationSync.status == STATUS_PAUSED],
            status=STATUS_ACTIVE, paused_reason=None, last_error=None, next_sync_at=_now(),
        )
        self.db.commit()
        return self.get(tenant_id, sync_id)

    def stop(self, tenant_id: str, sync_id: str) -> MigrationSyncItem:
        sync = self._require(tenant_id, sync_id)
        if sync.status not in (STATUS_ACTIVE, STATUS_PAUSED):
            raise SyncConflict("not_active", "This sync is already stopping or stopped.")
        self.repo.update_if(
            tenant_id, sync_id, [MigrationSync.status.in_((STATUS_ACTIVE, STATUS_PAUSED))],
            status=STATUS_STOPPING, paused_reason=None,
        )
        self.db.commit()
        # One final tick. When a tick is running right now the claim fails and
        # that tick (or the next sweep) enqueues the final one when it ends;
        # while a migration job runs on the workspace the sweep waits for it.
        if not _workspace_busy(self.db, tenant_id, sync.workspace_id):
            _enqueue_tick(self.db, tenant_id, sync_id, KIND_FINAL)
        return self.get(tenant_id, sync_id)

    # -- webhook ----------------------------------------------------------------

    def _secret_of(self, sync: MigrationSync) -> str:
        try:
            return str(decrypt_secret(sync.webhook_secret_enc).get("secret") or "")
        except (InvalidToken, ValueError):
            raise SyncConflict("webhook_unreadable", "The webhook URL could not be read. Rotate it.")

    def _url(self, sync: MigrationSync, secret: str) -> str:
        base = str(settings.public_base_url or "").rstrip("/")
        return f"{base}/omnichannel/migration-hooks/{sync.id}/{secret}"

    def webhook_url(self, tenant_id: str, sync_id: str) -> str:
        sync = self._require(tenant_id, sync_id)
        return self._url(sync, self._secret_of(sync))

    def rotate_webhook(self, tenant_id: str, sync_id: str) -> str:
        sync = self._require(tenant_id, sync_id)
        secret = _secrets.token_urlsafe(32)
        sync.webhook_secret_enc = encrypt_secret({"secret": secret})
        self.db.commit()
        return self._url(sync, secret)


# ── scheduling: claim + enqueue, and the beat sweep (D4) ────────────────────


def _enqueue_tick(db: Session, tenant_id: str, sync_id: str, kind: str) -> Optional[BackgroundJob]:
    """Guarded claim (`running_job_id IS NULL`) so two beats cannot double
    enqueue, then create + enqueue the tick job. None when the claim lost."""
    repo = MigrationSyncRepository(db)
    claimed = repo.update_if(
        tenant_id, sync_id, [MigrationSync.running_job_id.is_(None)], running_job_id=_CLAIM_PLACEHOLDER
    )
    db.commit()
    if not claimed:
        return None
    sync = repo.get(tenant_id, sync_id)
    try:
        job = JobService(db).create(
            type=SYNC_JOB_TYPE,
            tenant_id=tenant_id,
            payload={
                "syncId": sync_id,
                "kind": kind,
                "workspaceId": sync.workspace_id if sync is not None else None,
            },
        )
        repo.update(tenant_id, sync_id, running_job_id=job.id)
        db.commit()
    except Exception:
        db.rollback()
        repo.update_if(tenant_id, sync_id, [MigrationSync.running_job_id == _CLAIM_PLACEHOLDER], running_job_id=None)
        db.commit()
        raise
    JobService(db).enqueue(job.id)
    return job


def _workspace_busy(db: Session, tenant_id: str, workspace_id: str) -> bool:
    """A pending/running migration job on the workspace blocks the tick (D10)."""
    jobs = JobService(db).repo.active_of_type(
        tenant_id, MIGRATION_JOB_TYPE, (JOB_PENDING, JOB_RUNNING, JOB_NEEDS_REVIEW)
    )
    return any((j.payload_json or {}).get("workspaceId") == workspace_id for j in jobs)


def _reconcile_running(db: Session, sync: MigrationSync) -> bool:
    """Clear a stale `running_job_id`. True when a tick is genuinely live."""
    repo = MigrationSyncRepository(db)
    rid = sync.running_job_id
    if not rid:
        return False
    if rid == _CLAIM_PLACEHOLDER:
        age = _now() - (_aware(sync.updated_at) or _now())
        if age < _CLAIM_STALE:
            return True
    else:
        job = repo.get_job(sync.tenant_id, rid)
        if job is not None and job.status not in JOB_TERMINAL_STATUSES:
            return True
    repo.update_if(sync.tenant_id, sync.id, [MigrationSync.running_job_id == rid], running_job_id=None)
    db.commit()
    return False


def run_due_syncs(db: Session) -> Dict[str, int]:
    """The 60 s beat body. Per active sync: skip when a tick or a migration
    job is live, else enqueue `poll` (due) or `hints` (webhook-flagged), or the
    `final` tick of a `stopping` sync. Failure-isolated per sync."""
    repo = MigrationSyncRepository(db)
    started = 0
    modules = ModuleRepository(db)
    for tenant_id, sync_id in repo.active_refs():
        try:
            sync = repo.get(tenant_id, sync_id)
            if sync is None or sync.status not in (STATUS_ACTIVE, STATUS_STOPPING):
                continue
            if not modules.is_active(tenant_id, MODULE_NAME):
                continue
            if _reconcile_running(db, sync):
                continue
            db.refresh(sync)
            if _workspace_busy(db, tenant_id, sync.workspace_id):
                continue
            kind: Optional[str] = None
            if sync.status == STATUS_STOPPING:
                kind = KIND_FINAL
            else:
                due = sync.next_sync_at is not None and _aware(sync.next_sync_at) <= _now()
                if due:
                    kind = KIND_POLL
                elif repo.count_hints(tenant_id, sync_id) > 0:
                    kind = KIND_HINTS
            if kind is None:
                continue
            if _enqueue_tick(db, tenant_id, sync_id, kind) is not None:
                started += 1
        except Exception:  # noqa: BLE001 - one bad sync never stops the sweep
            logger.exception("migration sync sweep failed for sync %s", sync_id)
            db.rollback()
    return {"started": started}


# ── webhook intake (D5/D6) ──────────────────────────────────────────────────


def _hint_id_from(body: Any) -> Optional[str]:
    """`contact.id`, `contactId` or `data.contact.id`; digits only (1-20)."""
    if not isinstance(body, dict):
        return None
    candidates: List[Any] = []
    contact = body.get("contact")
    if isinstance(contact, dict):
        candidates.append(contact.get("id"))
    candidates.append(body.get("contactId"))
    data = body.get("data")
    if isinstance(data, dict) and isinstance(data.get("contact"), dict):
        candidates.append(data["contact"].get("id"))
    for value in candidates:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            continue
        text = str(value)
        if _USABLE_ID.fullmatch(text):
            return text
    return None


def record_hint(db: Session, sync_id: str, secret: str, body: bytes) -> str:
    """Public webhook: returns `stored` | `ignored` (no usable id / cap or
    duplicate handled) ; raises SyncNotFound for every authorization failure
    (one uniform 404). Only the contact id is ever persisted (D5)."""
    repo = MigrationSyncRepository(db)
    sync = repo.get_unscoped(sync_id)
    expected = ""
    # An unknown sync id still pays one decrypt, so timing does not reveal
    # whether the id exists.
    ciphertext = sync.webhook_secret_enc if sync is not None else encrypt_secret({"secret": "-"})
    try:
        expected = str(decrypt_secret(ciphertext).get("secret") or "")
    except (InvalidToken, ValueError):
        expected = ""
    if sync is None:
        expected = ""
    # constant-time compare, run even when the sync is unknown
    matches = hmac.compare_digest(secret.encode("utf-8"), (expected or "\x00").encode("utf-8"))
    if sync is None or not expected or not matches:
        raise SyncNotFound()
    if not ModuleRepository(db).is_active(sync.tenant_id, MODULE_NAME):
        raise SyncNotFound()
    if sync.status not in (STATUS_ACTIVE, STATUS_PAUSED, STATUS_STOPPING):
        raise SyncNotFound()

    try:
        parsed = json.loads(body.decode("utf-8")) if body else None
    except (ValueError, UnicodeDecodeError, RecursionError):
        return "ignored"
    contact_id = _hint_id_from(parsed)
    if contact_id is None:
        return "ignored"
    # A repeat of a pending hint re-stamps it even at the cap (B1); only a NEW
    # contact is dropped over the cap (the next full sweep covers it).
    if not repo.bump_hint(sync.tenant_id, sync.id, contact_id, _now()):
        if repo.count_hints(sync.tenant_id, sync.id) >= HINT_CAP:
            return "ignored"
        repo.add_hint(sync.tenant_id, sync.id, contact_id, _now())
    db.commit()
    return "stored"


# ── the tick ────────────────────────────────────────────────────────────────


class _AuthRejected(Exception):
    pass


class _Interrupted(Exception):
    """The sync was paused/stopped under a running tick."""


def _pending_media_ids(db: Session, tenant_id: str, contact_id: str) -> Set[str]:
    rows = (
        db.query(ConversationMessage.id)
        .filter(
            ConversationMessage.tenant_id == tenant_id,
            ConversationMessage.contact_id == contact_id,
            ConversationMessage.media_url.isnot(None),
            ConversationMessage.media_key.is_(None),
        )
        .all()
    )
    return {r[0] for r in rows}


@dataclass
class _Mapping:
    channel_map: Dict[str, str]
    channel_type_by_target: Dict[str, str]
    user_map: Dict[str, str]
    lifecycle_map: Dict[str, str]
    team_map: Dict[str, str]
    messages_since: Optional[datetime]
    payload: Dict[str, Any]


class _Tick:
    def __init__(self, db: Session, job: BackgroundJob, sync: MigrationSync, kind: str):
        self.db = db
        self.job = job
        self.kind = kind
        self.tenant_id = job.tenant_id
        self.sync_id = sync.id
        self.workspace_id = sync.workspace_id
        self.sync = sync
        self.repo = MigrationSyncRepository(db)
        self.jobs = JobService(db)
        self.refs = MigrationRefRepository(db)
        self.auth_rejected = False
        self.rate_limited = False
        self.tick_error: Optional[str] = None
        self.paused_reason: Optional[str] = None
        self.failures: List[dict] = []
        self.contacts_created = 0
        self.contacts_updated = 0
        self.contact_errors = 0
        self.identity_counts: Dict[str, int] = {"fetched": 0, "create": 0, "update": 0, "skip": 0, "errors": 0}
        self.message_counts: Dict[str, int] = {"fetched": 0, "create": 0, "skip": 0, "errors": 0}
        self.media_counts: Dict[str, int] = {"fetched": 0, "create": 0, "skip": 0, "errors": 0}
        self.event_counts: Dict[str, int] = {"fetched": 0, "create": 0, "skip": 0, "errors": 0}
        self.walk_complete = False
        self.walked_contacts = 0
        self.processed_hints: Dict[str, datetime] = {}
        self.sweep_completed_at: Optional[datetime] = None

    # -- outcome helpers --------------------------------------------------------

    def _record_failure(self, entity: str, source_id: str, reason: str) -> None:
        if len(self.failures) < FAILURE_KEEP:
            self.failures.append(
                {"entity": entity, "sourceId": source_id, "sourceLabel": "", "reason": reason, "action": "skipped"}
            )

    def _result(self) -> Dict[str, Any]:
        errors = (
            self.contact_errors
            + self.identity_counts.get("errors", 0)
            + self.message_counts.get("errors", 0)
            + self.media_counts.get("errors", 0)
            + self.event_counts.get("errors", 0)
            + (1 if self.tick_error else 0)
        )
        return {
            "contactsCreated": self.contacts_created,
            "contactsUpdated": self.contacts_updated,
            "messagesCreated": self.message_counts.get("create", 0),
            "messagesSkipped": self.message_counts.get("skip", 0),
            "errors": errors,
            "failureSample": self.failures[:FAILURE_SAMPLE],
        }

    # -- the run ------------------------------------------------------------------

    def run(self) -> None:
        sync = self.sync
        if sync.status == STATUS_STOPPED:
            self.jobs.finish(self.job, status=JOB_DONE, result={"skipped": "stopped"})
            return
        if self.kind != KIND_FINAL and sync.status != STATUS_ACTIVE:
            # paused / stopping under a queued poll: nothing to do (the final
            # tick, if any, is its own job)
            self.jobs.finish(self.job, status=JOB_DONE, result={"skipped": sync.status})
            return

        self._beat()
        try:
            self._sync_phase()
        except _AuthRejected:
            self.auth_rejected = True
        except _Interrupted:
            pass
        except RespondIoError as exc:
            if exc.status_code in (401, 403):
                self.auth_rejected = True
            else:
                self.tick_error = exc.message

        if self.kind == KIND_FINAL:
            self._cutover()
        self._finish()

    def _pause_reason(self) -> Optional[str]:
        return self.paused_reason or (PAUSE_TOKEN_REJECTED if self.auth_rejected else None)

    # -- phases -----------------------------------------------------------------

    def _sync_phase(self) -> None:
        source_run = self.repo.newest_done_run(
            self.tenant_id, MIGRATION_JOB_TYPE, self.workspace_id, mode="run", source="api"
        )
        if source_run is None:
            self.tick_error = "No finished migration found for this workspace."
            return
        payload = dict(source_run.payload_json or {})

        workspace = self.repo.workspace(self.tenant_id, self.workspace_id)
        if workspace is None or workspace.is_trashed:
            self.paused_reason = PAUSE_WORKSPACE_MISSING
            return
        connection = MigrationConnectionRepository(self.db).get_for_provider(
            self.tenant_id, str(payload.get("connectionId") or ""), RESPONDIO_PROVIDER
        )
        if connection is None:
            self.paused_reason = PAUSE_CONNECTION_MISSING
            return
        credentials = _decrypt_or_none(connection.credentials_json)
        if credentials is None:
            self.paused_reason = PAUSE_TOKEN_REJECTED
            self.tick_error = "Stored credentials could not be decrypted - re-enter the access token."
            return
        config = connection.config_json or {}
        space_timezone = str(config.get("timezone") or "")

        client = RespondIoClient.from_connection(config, credentials)
        self._watch_auth(client)

        mapping = self._mapping(payload)
        source_field_defs: Dict[str, Dict[str, Any]] = {}
        try:
            fields, _bad = parse_rows(client.list_custom_fields(), CustomField)
            for f in fields:
                source_field_defs[f.name.strip().lower()] = {
                    "dataType": f.dataType, "allowedValues": f.allowedValues,
                }
        except RespondIoError as exc:
            if self.auth_rejected:
                raise _AuthRejected() from exc
            logger.info("sync %s: custom fields unreadable: %s", self.sync_id, exc.message)
        user_team_by_id: Dict[str, str] = {}
        if payload.get("teamMap"):
            try:
                users, _bad = parse_rows(client.list_space_users(), SpaceUser)
                for u in users:
                    if u.team is not None:
                        user_team_by_id[str(u.id)] = str(u.team.id)
            except RespondIoError as exc:
                if self.auth_rejected:
                    raise _AuthRejected() from exc

        self.writer = MigrationWriter(
            self.db,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            thread_open_status_id=status_id_for(self.db, self.tenant_id, "THREAD", "OPEN"),
            thread_closed_status_id=status_id_for(self.db, self.tenant_id, "THREAD", "CLOSED"),
            initial_lifecycle_status_id=initial_status_id(self.db, self.tenant_id, self.workspace_id),
            lifecycle_map=mapping.lifecycle_map,
            source_field_defs=source_field_defs,
            writes_enabled=True,
            team_map=mapping.team_map,
            user_team_by_id=user_team_by_id,
            contact_mode="source_wins",
        )
        self.client = client
        self.mapping = mapping

        hint_rows = self.repo.hint_rows(self.tenant_id, self.sync_id, limit=HINTS_PER_TICK)
        hint_stamp: Dict[str, datetime] = {cid: stamp for cid, stamp in hint_rows}
        hint_ids = [cid for cid, _stamp in hint_rows]
        flagged: Set[str] = set(hint_ids)
        now = _now()
        last_sweep = _aware(self.sync.last_full_sweep_at)
        sweep_due = self.kind == KIND_POLL and (
            last_sweep is None or now - last_sweep >= timedelta(hours=self.sync.full_sweep_hours)
        )

        try:
            seen: Set[str] = set()
            if self.kind in (KIND_POLL, KIND_FINAL):
                for page_items, _next in client.list_contacts_pages(
                    timezone=space_timezone, limit=CONTACTS_PAGE_LIMIT
                ):
                    for raw in page_items:
                        self.walked_contacts += 1
                        external_id = str((raw or {}).get("id", "")) if isinstance(raw, dict) else ""
                        seen.add(external_id)
                        self._contact(raw, flagged=external_id in flagged, sweep=sweep_due)
                        if external_id in flagged:
                            self.processed_hints[external_id] = hint_stamp[external_id]
                        self._checkpoint()
                self.walk_complete = True
            for contact_id in hint_ids:
                if contact_id in seen:
                    continue
                self._hinted(contact_id)
                self.processed_hints[contact_id] = hint_stamp[contact_id]
                self._checkpoint()
            # a sweep that hit rate limits skipped contacts: not complete
            if sweep_due and self.walk_complete and not self.rate_limited:
                self.sweep_completed_at = _now()
        finally:
            if self.processed_hints:
                self.repo.delete_hints(self.tenant_id, self.sync_id, list(self.processed_hints.items()))
                self.db.commit()

    def _watch_auth(self, client: RespondIoClient) -> None:
        """401/403 on ANY request (even inside a helper that swallows the
        error per contact) flags the tick for a token_rejected pause."""
        original = client._request

        def watched(*args: Any, **kwargs: Any) -> Any:
            try:
                return original(*args, **kwargs)
            except RespondIoError as exc:
                if exc.status_code in (401, 403):
                    self.auth_rejected = True
                elif exc.status_code == 429:
                    self.rate_limited = True
                raise

        client._request = watched  # type: ignore[method-assign]

    def _mapping(self, payload: Dict[str, Any]) -> _Mapping:
        lifecycle_map: Dict[str, str] = {}
        for entry in payload.get("lifecycleMap") or []:
            target = entry.get("targetStatusId")
            label = str(entry.get("sourceLabel") or "").strip().lower()
            if not target or not label:
                continue
            if get_scope_status(self.db, LIFECYCLE_ENTITY_TYPE, self.tenant_id, self.workspace_id, target) is not None:
                lifecycle_map[label] = target
        channel_map, channel_type_by_target = _resolve_channel_map(
            self.db, self.tenant_id, self.workspace_id, payload
        )
        user_map, _dropped = _resolve_user_map(self.db, self.tenant_id, payload)
        team_map, _dropped_t = _resolve_team_map(self.db, self.tenant_id, payload)
        floor: Optional[datetime] = None
        raw_floor = payload.get("messagesSince")
        if raw_floor:
            try:
                floor = datetime.fromisoformat(str(raw_floor)).astimezone(timezone.utc)
            except ValueError:
                floor = None
        return _Mapping(
            channel_map=channel_map, channel_type_by_target=channel_type_by_target, user_map=user_map,
            lifecycle_map=lifecycle_map, team_map=team_map, messages_since=floor, payload=payload,
        )

    def _checkpoint(self) -> None:
        """After each contact: beat, surface an auth rejection, honour pause/stop."""
        self._beat()
        if self.auth_rejected:
            raise _AuthRejected()
        if self.kind != KIND_FINAL:
            status = self.repo.fresh_status(self.tenant_id, self.sync_id)
            if status != STATUS_ACTIVE:
                raise _Interrupted()

    def _beat(self) -> None:
        """Liveness (fix/job-lease-orphan-sweep): a tick whose worker died is
        failed by the orphan sweep, which lets `_reconcile_running` clear it."""
        try:
            alive = self.jobs.heartbeat(self.job.id)
        except Exception:  # noqa: BLE001 - best effort, never fails the tick
            logger.warning("sync %s: heartbeat failed", self.sync_id, exc_info=True)
            return
        if not alive and self.jobs.fresh_status(self.job.id) != JOB_RUNNING:
            raise _Interrupted()  # orphan-swept under us: stop writing

    # -- one contact ------------------------------------------------------------

    def _hinted(self, contact_id: str) -> None:
        try:
            raw = self.client.get_contact(f"id:{contact_id}")
        except RespondIoError as exc:
            if exc.status_code in (401, 403):
                raise
            self.contact_errors += 1
            self._record_failure("contacts", contact_id, exc.message)
            if exc.status_code == 429:
                raise
            return
        self._contact(raw, flagged=True, sweep=False)

    def _contact(self, raw: Any, *, flagged: bool, sweep: bool) -> None:
        mapping = self.mapping
        external_id = str((raw or {}).get("id", "")) if isinstance(raw, dict) else ""
        try:
            source_contact = Contact(**raw)
        except Exception as exc:  # noqa: BLE001 - malformed vendor row, never abort the tick
            self.contact_errors += 1
            self._record_failure("contacts", external_id, f"malformed contact payload: {_failure_reason(exc)}")
            return

        had_ref = (
            self.refs.local_for_one(self.tenant_id, self.workspace_id, RESPONDIO_PROVIDER, ENTITY_CONTACT, external_id)
            is not None
        )
        nested = self.db.begin_nested()
        try:
            outcome = self.writer.write_contact(source_contact)
            local = (
                self.db.query(ContactModel)
                .filter(ContactModel.id == outcome.contact_id, ContactModel.tenant_id == self.tenant_id)
                .first()
            )
            if flagged or sweep or not had_ref:
                _process_contact_identities(
                    self.client, self.writer, outcome.contact_id, external_id,
                    mapping.channel_map, mapping.channel_type_by_target, source_contact.phone,
                    self.identity_counts, self.failures,
                )
                before = _pending_media_ids(self.db, self.tenant_id, local.id)
                _process_contact_messages(
                    self.client, self.writer, self.refs, self.tenant_id, self.workspace_id, local, external_id,
                    mapping.channel_map, mapping.user_map, self.message_counts, self.failures, [],
                    messages_since=mapping.messages_since, prefetched_contact=raw,
                )
                for message_id in sorted(_pending_media_ids(self.db, self.tenant_id, local.id) - before):
                    message = (
                        self.db.query(ConversationMessage)
                        .filter(ConversationMessage.id == message_id, ConversationMessage.tenant_id == self.tenant_id)
                        .first()
                    )
                    if message is not None:
                        _process_message_media(
                            self.writer, self.tenant_id, self.workspace_id, message, self.media_counts, self.failures
                        )
                if not had_ref:
                    _process_contact_events(
                        self.client, self.writer, self.refs, self.tenant_id, self.workspace_id, local,
                        external_id, self.event_counts, self.failures, prefetched_contact=raw,
                    )
        except Exception as exc:  # noqa: BLE001 - per-contact isolation (AC-SYNC-19)
            nested.rollback()
            self.contact_errors += 1
            self._record_failure("contacts", external_id, _failure_reason(exc))
            self.db.commit()
            return
        nested.commit()
        self.db.commit()
        if outcome.kind == "create":
            self.contacts_created += 1
        elif not had_ref or outcome.changed:
            self.contacts_updated += 1

    # -- cutover (final tick) ----------------------------------------------------

    def _cutover(self) -> None:
        """D12 - agents can reply free-form straight after cutover: for every
        respond.io-migrated contact set `csw_expires_at` to the last incoming
        message + 24 h when that is still in the future."""
        now = _now()
        after: Optional[str] = None
        while True:
            batch = self.refs.paged(
                self.tenant_id, self.workspace_id, RESPONDIO_PROVIDER, ENTITY_CONTACT, after_id=after, limit=200
            )
            if not batch:
                break
            for ref in batch:
                after = ref.id
                contact = (
                    self.db.query(ContactModel)
                    .filter(
                        ContactModel.id == ref.local_id,
                        ContactModel.tenant_id == self.tenant_id,
                        ContactModel.workspace_id == self.workspace_id,
                    )
                    .first()
                )
                if contact is None or contact.last_incoming_message_at is None:
                    continue
                window_end = _aware(contact.last_incoming_message_at) + timedelta(hours=CSW_HOURS)
                if window_end > now:
                    contact.csw_expires_at = window_end
            self.db.commit()

    # -- finish -----------------------------------------------------------------

    def _finish(self) -> None:
        now = _now()
        result = self._result()
        reason = self._pause_reason()
        cols: Dict[str, Any] = {}

        if self.auth_rejected:
            self.tick_error = "respond.io rejected the access token."
        paused_now = False
        if reason is not None and self.kind != KIND_FINAL:
            # Only an ACTIVE sync pauses: a Stop (stopping) or a manual pause
            # that landed mid-tick is never overwritten.
            paused_now = bool(
                self.repo.update_if(
                    self.tenant_id, self.sync_id, [MigrationSync.status == STATUS_ACTIVE],
                    status=STATUS_PAUSED, paused_reason=reason, last_error=self.tick_error,
                )
            )
            if not paused_now:
                cols["last_error"] = self.tick_error
        else:
            cols["last_error"] = self.tick_error
            if not self.auth_rejected and reason is None:
                cols["last_sync_at"] = now
            cols["last_result_json"] = result
            totals = _counters(self.sync.totals_json)
            for key, value in _counters(result).items():
                totals[key] += value
            cols["totals_json"] = totals
            if self.kind in (KIND_POLL,):
                cols["next_sync_at"] = now + timedelta(minutes=self.sync.interval_minutes)
            if self.sweep_completed_at is not None:
                cols["last_full_sweep_at"] = self.sweep_completed_at
            if self.walk_complete:
                cols["source_contact_count"] = self.walked_contacts
        if self.kind == KIND_FINAL:
            cols.update(status=STATUS_STOPPED, stopped_at=now, next_sync_at=None, paused_reason=None)

        if cols:
            self.repo.update(self.tenant_id, self.sync_id, **cols)
        self.db.commit()

        if paused_now and reason == PAUSE_TOKEN_REJECTED:
            self._email_creator()

        job_result = {"syncId": self.sync_id, "kind": self.kind, "result": result}
        if self.auth_rejected or reason is not None:
            self.jobs.finish(self.job, status=JOB_FAILED, result=job_result, error=self.tick_error or "Sync paused.")
        elif self.tick_error:
            self.jobs.finish(self.job, status=JOB_FAILED, result=job_result, error=self.tick_error)
        else:
            self.jobs.finish(self.job, status=JOB_DONE, result=job_result)

    def _email_creator(self) -> None:
        """D11 - one plain outbox email to the sync's creator."""
        try:
            user = self.repo.user(self.tenant_id, self.sync.created_by_user_id) if self.sync.created_by_user_id else None
            if user is None or not user.email:
                return
            workspace = self.repo.workspace(self.tenant_id, self.workspace_id)
            name = workspace.name if workspace is not None else "your workspace"
            subject = "respond.io sync paused"
            text = (
                f"The respond.io sync for {name} is paused because respond.io rejected the access token. "
                "Update the connection's access token, then resume the sync."
            )
            html_body = (
                f"<p>The respond.io sync for {html.escape(name)} is paused because respond.io rejected "
                "the access token. Update the connection's access token, then resume the sync.</p>"
            )
            email_service.enqueue_raw(
                self.db, self.tenant_id, user.email, subject, html_body, text, template_key="migration_sync_paused"
            )
        except Exception:  # noqa: BLE001 - mail trouble never fails the tick
            logger.exception("sync %s: could not enqueue the paused email", self.sync_id)
            self.db.rollback()


def _release(db: Session, tenant_id: str, sync_id: str, job_id: str) -> None:
    MigrationSyncRepository(db).update_if(
        tenant_id, sync_id, [MigrationSync.running_job_id == job_id], running_job_id=None
    )
    db.commit()


def run_sync_job(db: Session, job: BackgroundJob) -> None:
    """`omnichannel.respondio_sync` handler. Always clears the sync's
    `running_job_id` (any terminal state), then - if a Stop arrived while this
    tick ran - enqueues the final tick."""
    tenant_id = job.tenant_id
    payload = job.payload_json or {}
    sync_id = str(payload.get("syncId") or "")
    kind = str(payload.get("kind") or KIND_POLL)
    repo = MigrationSyncRepository(db)
    sync = repo.get(tenant_id, sync_id) if sync_id else None
    if sync is None or kind not in _KINDS:
        JobService(db).finish(job, status=JOB_FAILED, error="The sync no longer exists.")
        return
    try:
        _Tick(db, job, sync, kind).run()
    except BaseException:
        db.rollback()
        if kind != KIND_FINAL:
            # A crash that is not a respond.io error must not become a 60 s
            # retry loop: back off by one interval, keep the reason fixed text.
            try:
                repo.update(
                    tenant_id, sync_id,
                    next_sync_at=_now() + timedelta(minutes=sync.interval_minutes),
                    last_error="The sync stopped unexpectedly and will try again.",
                )
                db.commit()
            except Exception:  # noqa: BLE001 - best effort
                db.rollback()
        _release(db, tenant_id, sync_id, job.id)
        raise
    _release(db, tenant_id, sync_id, job.id)
    if kind != KIND_FINAL and repo.fresh_status(tenant_id, sync_id) == STATUS_STOPPING:
        _enqueue_tick(db, tenant_id, sync_id, KIND_FINAL)


SYNC_JOB_HANDLER_DEF = JobHandlerDef(
    SYNC_JOB_TYPE, run_sync_job, "respond.io continuous sync", read_permission="omnichannel_migration.read",
    heartbeats=True,
)


def register_sync_job_handler() -> None:
    register_job_handler(SYNC_JOB_HANDLER_DEF)
