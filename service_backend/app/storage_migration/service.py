"""Storage migration engine (sprint-4/10 Slice 2) — the first ``background_jobs``
type.

Transient **A → B** model (plan D1/D7/D10): starting a migration atomically
creates connection **B** (active), retires **A** (``is_active=false``) and
enqueues a ``storage_migration`` job. Because ``resolve_for_type`` filters
``is_active`` (D10), the retire/promote flip IS the write-target flip — new
uploads land on B immediately while A's historical blobs keep serving by KEY.

The job (``run_storage_migration``) DRAINS A: it enumerates every ``conn:A:``
blob across the registered StorageKeyLocations, path-preservingly copies each
into B (``put_raw`` — NO uuid re-mint, D2), and on a CLEAN copy auto-cutovers
(``rewrite_keys`` value-checked, only the successfully-copied set → D3/D5). A
missing/unreadable source blob is recorded + skipped, never aborts (D4); ≥1
failure HOLDS the job at ``needs_review`` for an explicit Complete/Retry (D5).
**Bucket A's contents are NEVER deleted by us** (D13) — the copy path issues
zero destructive calls on the source adapter.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session

from app.integrations import get_provider
from app.integrations.s3_provider import S3CompatibleAdapter
from app.jobs.registry import JobHandlerDef, handler_for, register_job_handler
from app.jobs.service import JobService
from app.models.background_job import (
    JOB_ABORTED,
    JOB_DONE,
    JOB_FAILED,
    JOB_NEEDS_REVIEW,
    JOB_PENDING,
    JOB_RUNNING,
    JOB_TERMINAL_STATUSES,
    BackgroundJob,
)
from app.models.connection import (
    CONNECTION_STATUS_ACTIVE,
    Connection,
)
from app.jobs.repository import BackgroundJobRepository
from app.repositories.connection_repository import ConnectionRepository
from app.secrets import encrypt_secret
from app.storage_migration.core_locations import (
    ensure_all_storage_locations,
    missing_declared_location_modules,
)
from app.storage_migration.registry import enumerate_keys, list_locations, rewrite_keys

logger = logging.getLogger("foundryx.storage_migration")

STORAGE_MIGRATION = "storage_migration"
STORAGE_TYPE = "storage"

# Non-terminal statuses = a live migration holds the connection (D14 lock).
_ACTIVE_JOB_STATUSES = (JOB_PENDING, JOB_RUNNING, JOB_NEEDS_REVIEW)

# How often the copy loop persists its cursor/progress (a crash between commits
# only re-copies idempotent work — resume is safe, so we needn't commit each).
_CURSOR_COMMIT_EVERY = 25


def _raw_of(key: str) -> str:
    """``conn:<id>:<raw>`` → ``<raw>``."""
    return key.split(":", 2)[2]


def _adapter_for(connection: Connection):
    """Raw storage adapter for a connection. Indirected through the storage
    module so tests can monkeypatch ``app.services.storage._adapter_for`` with
    an in-memory fake (offline-deterministic, and a spy for the no-delete
    assertion, AC-10-13)."""
    from app.services import storage as storage_module

    return storage_module._adapter_for(connection)


class StorageMigrationService:
    def __init__(self, db: Session):
        self.db = db
        self.conns = ConnectionRepository(db)
        self.jobs = BackgroundJobRepository(db)

    # ── start ────────────────────────────────────────────────────────────────

    def start(
        self,
        tenant_id: str,
        actor_user_id: Optional[str],
        *,
        provider: str,
        name: str,
        new_config: Dict[str, Any],
        new_credentials: Dict[str, str],
    ) -> BackgroundJob:
        """Atomic create-B + retire-A + enqueue (AC-10-09).

        Ownership is INHERENT (D11): ``get_by_type`` is tenant-scoped, so a
        tenant can only migrate its OWN active storage connection; the platform
        tenant (which holds the platform connection row) migrates the platform
        connection — the same code path, the double-lock built in.
        """
        register_storage_migration_handler()  # idempotent — belt-and-suspenders

        # 1. resolve the tenant's OWN active storage connection A.
        a = self.conns.get_by_type(tenant_id, STORAGE_TYPE)
        if a is None:
            raise HTTPException(
                http_status.HTTP_400_BAD_REQUEST,
                "No active storage connection to migrate from — connect a storage "
                "bucket first.",
            )

        # 2. one active migration per connection (AC-10-14).
        if self._active_migration_for(tenant_id, a.id) is not None:
            raise HTTPException(
                http_status.HTTP_409_CONFLICT,
                "A storage migration for this connection is already in progress.",
            )

        # 3. validate provider + TEST the new bucket B before committing to it
        #    (the SAME probe the non-destructive wizard Test step runs).
        ok, message = self._probe_bucket(provider, new_config, new_credentials)
        if not ok:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"The new storage bucket could not be verified: {message}",
            )

        # 4. ONE transaction: retire A (so the partial-unique index permits a
        #    second active row), create B active, create the job row.
        self.conns.mark_active(a.id, False)  # flush inside
        b = Connection(
            tenant_id=tenant_id,
            provider=provider,
            type=STORAGE_TYPE,
            name=name,
            config_json=dict(new_config),
            credentials_json=encrypt_secret(dict(new_credentials)),
            status=CONNECTION_STATUS_ACTIVE,
            last_tested_at=datetime.now(timezone.utc),
            is_active=True,
        )
        self.conns.create(b)  # add + flush

        handler_for(STORAGE_MIGRATION)  # loud if somehow unregistered
        job = BackgroundJob(
            tenant_id=tenant_id,
            type=STORAGE_MIGRATION,
            status=JOB_PENDING,
            actor_user_id=actor_user_id,
            payload_json={"fromConnectionId": a.id, "toConnectionId": b.id},
        )
        self.jobs.add(job)  # flush
        self.db.commit()

        JobService(self.db).enqueue(job.id)
        return self.jobs.get_unscoped(job.id) or job

    def test_bucket(
        self,
        *,
        provider: str,
        config: Dict[str, Any],
        credentials: Dict[str, str],
    ) -> tuple[bool, str]:
        """Non-destructive pre-create probe of a candidate new bucket B — the
        SAME ``run_probe`` (head_bucket + round-trip) that ``start`` runs and
        that the connect wizard's Test uses. Backs the wizard's Test step so
        Start is disabled until a bucket verifies (foolproof-UI, AC-10-18)."""
        return self._probe_bucket(provider, config, credentials)

    def _probe_bucket(
        self, provider: str, config: Dict[str, Any], credentials: Dict[str, str]
    ) -> tuple[bool, str]:
        prov = get_provider(provider)
        if prov is None or getattr(prov, "type", None) != STORAGE_TYPE:
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                f'Unknown or non-storage provider "{provider}".',
            )
        probe = S3CompatibleAdapter.from_connection(
            provider, dict(config), dict(credentials)
        ).run_probe()
        return probe.ok, probe.message

    # ── job control ──────────────────────────────────────────────────────────

    def abort(self, tenant_id: str, job_id: str) -> BackgroundJob:
        """Stop, rewrite NOTHING, KEEP B (its new uploads are live data), and
        restore A as the active write-target (AC-10-14). Stragglers already on B
        keep resolving by-key — we don't reverse them."""
        job = self._require_job(tenant_id, job_id, STORAGE_MIGRATION)
        if job.status in JOB_TERMINAL_STATUSES:
            raise HTTPException(
                http_status.HTTP_409_CONFLICT, "This migration is already finished."
            )
        from_id, to_id = self._conn_ids(job)
        # B inactive FIRST, then A active — avoids two active storage rows
        # tripping the partial-unique index.
        self.conns.mark_active(to_id, False)
        self.conns.mark_active(from_id, True)
        JobService(self.db).finish(job, status=JOB_ABORTED, result=job.result_json)
        return job

    def retry(self, tenant_id: str, job_id: str) -> BackgroundJob:
        """Re-run the copy over the remaining/failed blobs, then cutover when
        clean (AC-10-14). Already-copied keys skip (idempotent)."""
        job = self._require_job(tenant_id, job_id, STORAGE_MIGRATION)
        if job.status not in (JOB_FAILED, JOB_NEEDS_REVIEW):
            raise HTTPException(
                http_status.HTTP_409_CONFLICT,
                "Only a failed or needs-review migration can be retried.",
            )
        # Re-attempt failures: reset the cursor to the head, drop the failure
        # list, KEEP the copied set (those skip). A None cursor re-enumerates.
        cursor = dict(job.cursor_json or {})
        if cursor.get("keys"):
            cursor["index"] = 0
            cursor["failures"] = []
        job.cursor_json = cursor or None
        # Back to PENDING so the enqueue path re-claims it (running → handler),
        # keeping the worker's failure-isolation wrapper on the retry too.
        job.status = JOB_PENDING
        job.finished_at = None
        job.progress_done = len(cursor.get("copied", []))
        job.progress_failed = 0
        self.db.commit()
        JobService(self.db).enqueue(job.id)
        return self.jobs.get_unscoped(job_id) or job

    def complete(self, tenant_id: str, job_id: str) -> BackgroundJob:
        """From ``needs_review`` only: accept the failures list as-is and
        cutover the successfully-copied keys (AC-10-12)."""
        job = self._require_job(tenant_id, job_id, STORAGE_MIGRATION)
        if job.status != JOB_NEEDS_REVIEW:
            raise HTTPException(
                http_status.HTTP_409_CONFLICT,
                "Only a needs-review migration can be completed.",
            )
        from_id, to_id = self._conn_ids(job)
        copied = set((job.cursor_json or {}).get("copied", []))
        _cutover(self.db, job, from_id, to_id, copied)
        return job

    # ── reads ────────────────────────────────────────────────────────────────

    def is_connection_locked(self, tenant_id: str, connection_id: str) -> bool:
        """True while a non-terminal migration references this connection (as A
        or B) — the connection service refuses edit/delete then (AC-10-14)."""
        for job in self.jobs.active_of_type(tenant_id, STORAGE_MIGRATION, _ACTIVE_JOB_STATUSES):
            payload = job.payload_json or {}
            if connection_id in (payload.get("fromConnectionId"), payload.get("toConnectionId")):
                return True
        return False

    # ── helpers ──────────────────────────────────────────────────────────────

    def _active_migration_for(self, tenant_id: str, connection_id: str) -> Optional[BackgroundJob]:
        for job in self.jobs.active_of_type(tenant_id, STORAGE_MIGRATION, _ACTIVE_JOB_STATUSES):
            if (job.payload_json or {}).get("fromConnectionId") == connection_id:
                return job
        return None

    def _require_job(self, tenant_id: str, job_id: str, job_type: str) -> BackgroundJob:
        job = self.jobs.get(tenant_id, job_id)
        if job is None or job.type != job_type:
            raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Migration not found.")
        return job

    @staticmethod
    def _conn_ids(job: BackgroundJob) -> tuple[str, str]:
        payload = job.payload_json or {}
        return payload.get("fromConnectionId"), payload.get("toConnectionId")


# ── the registered job handler ────────────────────────────────────────────────


def _cutover(
    db: Session, job: BackgroundJob, from_id: str, to_id: str, only_keys: Set[str]
) -> None:
    """Batch-rewrite the successfully-copied ``conn:A:`` keys → ``conn:B:``
    (value-checked, only-keys-checked), then mark the job done. A is already
    ``is_active=false`` from start — no bucket deletes, ever (D13)."""
    n = rewrite_keys(db, from_id, to_id, only_keys=only_keys)
    result = _result_from_cursor(job)
    svc = JobService(db)
    svc.log(
        job,
        f"Cutover complete — rewrote {n} key column(s) conn:{from_id}: → "
        f"conn:{to_id}:. Old connection retired (serves stragglers by key).",
    )
    svc.finish(job, status=JOB_DONE, result=result)


def _result_from_cursor(job: BackgroundJob) -> Dict[str, Any]:
    cursor = job.cursor_json or {}
    failures = cursor.get("failures", [])
    return {
        "copied": len(cursor.get("copied", [])),
        "failed": len(failures),
        "orphaned": 0,
        "failures": failures,
    }


def run_storage_migration(db: Session, job: BackgroundJob) -> None:
    """``storage_migration`` job handler (AC-10-10..13). Enumerate → path-
    preserving copy (idempotent, continue-on-bad) → auto-cutover on clean else
    HOLD at ``needs_review``. Failure-isolated by the worker.

    Resumable: the cursor carries ``{keys, index, copied, failures}`` so a
    restart continues where it stopped (already-copied keys skip)."""
    from_id, to_id = StorageMigrationService._conn_ids(job)
    service = JobService(db)
    conns = ConnectionRepository(db)
    a_conn = conns.get_by_id(from_id)
    b_conn = conns.get_by_id(to_id)
    if a_conn is None or b_conn is None:
        service.log(job, "Migration connection missing — cannot start.", level="error")
        JobService(db).finish(
            db_job_reload(db, job), status=JOB_FAILED, error="Migration connection missing."
        )
        return

    # CRITICAL — register every storage-key location BEFORE enumerating. The job
    # may run in the Celery worker, which never boots the FastAPI app; without
    # this, ``_LOCATIONS`` is empty and enumeration silently finds 0 keys (the
    # sprint-4/12 no-op bug). Idempotent. Surfaces per-module registration
    # failures into the job log so a partially-registered run (e.g. omnichannel
    # skipped → its media never migrated) is VISIBLE, never a silent undercount.
    reg_failures = ensure_all_storage_locations()
    for mod, err in reg_failures:
        service.log(
            job,
            f"Module '{mod}' failed to register its storage-key locations: {err}. "
            f"Its blobs will NOT be migrated — fix and retry before retiring the "
            f"old connection.",
            level="error",
        )

    # Completeness gate (sprint-4/12 round 3): a module that DECLARES storage
    # locations in its manifest but registered FEWER than declared = a partial
    # registration (typically a stale/mis-booted worker that couldn't import the
    # module). Enumeration would then miss that module's blobs and, on cutover,
    # RETIRE the source with those blobs stranded on it — the exact prod bug
    # (omnichannel media left on the old connection). HOLD at needs_review BEFORE
    # any enumerate/cutover — reversible via Abort. Fix the worker (restart onto
    # the current image) and Retry. This catches the PARTIAL undercount the
    # zero-locations guard below cannot.
    incomplete = missing_declared_location_modules()
    if incomplete:
        service.log(
            job,
            "Incomplete storage-key registration — module(s) "
            f"{', '.join(incomplete)} declare storage locations that did NOT all "
            "register in this process (a stale or mis-booted worker). Holding "
            "WITHOUT cutover so no blob is stranded — restart the worker onto the "
            "current image, then Retry.",
            level="error",
        )
        service.finish(
            db_job_reload(db, job),
            status=JOB_NEEDS_REVIEW,
            error="Incomplete storage-key registration — held before cutover.",
        )
        return

    # Hard guard: no registered locations = a boot/deploy problem, not an empty
    # bucket. Enumeration would find 0 keys and auto-cutover to "done" having
    # migrated nothing — the exact silent no-op that stranded prod media. Fail
    # loudly instead (the connection flip is reversible via Abort).
    if not list_locations():
        service.log(
            job,
            "No storage-key locations are registered — cannot enumerate. This is a "
            "boot/deploy problem (the worker did not load the modules).",
            level="error",
        )
        service.finish(
            db_job_reload(db, job),
            status=JOB_FAILED,
            error="No storage-key locations registered — nothing could be enumerated.",
        )
        return

    a_adapter = _adapter_for(a_conn)
    b_adapter = _adapter_for(b_conn)

    cursor = dict(job.cursor_json or {})
    if not cursor.get("keys"):
        # Fresh start — enumerate the DISTINCT conn:A: blobs across ALL
        # registered locations (connection-scoped, so the platform connection
        # naturally sweeps every fallback tenant's rows — D11).
        service.log(
            job,
            f"Registered {len(list_locations())} storage-key locations; "
            f"enumerating conn:{from_id}: blobs.",
        )
        keys = sorted(enumerate_keys(db, from_id))
        cursor = {"keys": keys, "index": 0, "copied": [], "failures": []}
        job.progress_total = len(keys)
        job.progress_done = 0
        job.progress_failed = 0
        job.cursor_json = cursor
        db.commit()
        service.log(
            job,
            f"Enumerated {len(keys)} blob(s) to copy from {from_id} → {to_id}."
            + ("" if keys else " Nothing to migrate."),
        )
        # 0-keys guard: do NOT silently auto-cutover on an empty enumeration.
        # Either the source bucket is genuinely empty (fine — the operator
        # Completes) OR something is misconfigured and blobs were missed (the
        # prod bug). HOLD at needs_review so a human confirms rather than a
        # "done" that migrated nothing.
        if not keys:
            service.log(
                job,
                "Nothing enumerated — holding for review instead of auto-cutover. "
                "If bucket A truly has no assets, Complete to finish; otherwise "
                "investigate before cutting over.",
                level="warning",
            )
            service.finish(
                job, status=JOB_NEEDS_REVIEW, result=_result_from_cursor(job)
            )
            return

    keys: List[str] = cursor["keys"]
    copied: Set[str] = set(cursor.get("copied", []))
    failures: List[dict] = list(cursor.get("failures", []))
    index: int = cursor.get("index", 0)

    while index < len(keys):
        key = keys[index]
        index += 1
        if key in copied:
            continue
        raw = _raw_of(key)
        try:
            # Idempotent skip: already present in B (resume / prior run).
            b_adapter.fetch(raw)
            copied.add(key)
        except FileNotFoundError:
            try:
                content, mime = a_adapter.fetch(raw)
            except Exception as exc:  # noqa: BLE001 — missing/unreadable source
                failures.append({"key": key, "reason": f"source unreadable: {exc}"})
                job.progress_failed = len(failures)
                cursor.update(index=index, copied=list(copied), failures=failures)
                job.cursor_json = dict(cursor)
                continue
            b_adapter.put_raw(raw, content, mime or "application/octet-stream")
            copied.add(key)
        except Exception as exc:  # noqa: BLE001 — B read error → treat as failure
            failures.append({"key": key, "reason": f"target check failed: {exc}"})
            job.progress_failed = len(failures)
            cursor.update(index=index, copied=list(copied), failures=failures)
            job.cursor_json = dict(cursor)
            continue

        job.progress_done = len(copied)
        cursor.update(index=index, copied=list(copied), failures=failures)
        job.cursor_json = dict(cursor)
        if index % _CURSOR_COMMIT_EVERY == 0:
            db.commit()
            # Cooperative cancel: a concurrent abort (real Celery path) set
            # JOB_ABORTED + restored the connection flags on another session.
            # Bail BEFORE cutover so an aborted migration never rewrites keys
            # (AC-10-14). Progress persisted above → resume-safe if retried.
            if _aborted(db, job.id):
                return

    cursor.update(index=index, copied=list(copied), failures=failures)
    job.cursor_json = dict(cursor)
    job.progress_done = len(copied)
    job.progress_failed = len(failures)
    db.commit()
    if _aborted(db, job.id):
        return

    if failures:
        # Assets keep serving (A active-by-key / B) until the user Completes or
        # Retries — never a silent partial cutover (D5).
        service.log(
            job,
            f"Copied {len(copied)} blob(s), {len(failures)} failed — holding for "
            "review (no cutover). Complete or Retry to proceed.",
            level="warning",
        )
        service.finish(job, status=JOB_NEEDS_REVIEW, result=_result_from_cursor(job))
        return
    service.log(job, f"Copied {len(copied)} blob(s) cleanly — cutting over.")
    _cutover(db, job, from_id, to_id, copied)


def db_job_reload(db: Session, job: BackgroundJob) -> BackgroundJob:
    return BackgroundJobRepository(db).get_unscoped(job.id) or job


def _aborted(db: Session, job_id: str) -> bool:
    """Re-read the job's status FRESH from the DB (a concurrent abort commits
    JOB_ABORTED on a different session). Eager mode has no interleave — this
    guards the real Celery worker path so the copy loop stops before cutover."""
    return (
        db.query(BackgroundJob.status).filter(BackgroundJob.id == job_id).scalar()
        == JOB_ABORTED
    )


# ── boot registration (idempotent) ────────────────────────────────────────────

_HANDLER_DEF = JobHandlerDef(STORAGE_MIGRATION, run_storage_migration, "Storage migration")


def register_storage_migration_handler() -> None:
    """Register the ``storage_migration`` handler (idempotent — the SAME def
    object re-registers cleanly). Called at import, from the app lifespan, and
    defensively in ``start`` so every entry path has it."""
    register_job_handler(_HANDLER_DEF)


register_storage_migration_handler()
