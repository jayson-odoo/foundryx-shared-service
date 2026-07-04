"""Email outbox dispatcher (plan 09 §5).

A daemon thread drains `email_outbox`:

- claims due rows with `FOR UPDATE SKIP LOCKED` (multi-worker claim safety on
  Postgres; SQLite ignores the hint — tests drive `dispatch_pending` directly)
  under a **lease**: claimed rows go SENDING with `next_attempt_at` = now +
  lease, so a worker that crashes mid-send leaves rows that simply get
  re-claimed once the lease expires (no stuck-SENDING orphans);
- enforces the per-connection `rate_limit_per_minute` (low-spec SMTP guard) —
  the sent-window is counted once per connection per pass, not per row;
- retries with backoff (1m → 5m → 25m, max 3 attempts per connection);
- exhausted tenant connection → re-resolves to the PLATFORM default
  (`used_fallback`, attempts reset once) → exhausted again = failed;
- housekeeping: prunes `sent` rows older than the retention window.

Any exception is logged and the loop survives — the dispatcher must never
take the app down. Gated by `settings.email_dispatcher_enabled` (tests and
one-off scripts turn it off).
"""
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.integrations import get_provider
from app.models.connection import (
    CONNECTION_STATUS_ACTIVE,
    CONNECTION_STATUS_ERROR,
    Connection,
)
from app.models.email_outbox import (
    MAX_ATTEMPTS,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OUTBOX_SENDING,
    OUTBOX_SENT,
    RETRY_BACKOFF_SECONDS,
    EmailOutbox,
)
from app.models.tenant import PLATFORM_TENANT_ID
from app.repositories.connection_repository import ConnectionRepository
from app.secrets import decrypt_secret
from app.services.throttle import prune_stale as prune_stale_throttle_rows
from app.services.email_service import EMAIL_PROVIDER

logger = logging.getLogger("dreamz.email.dispatcher")

# Re-check delay when a connection is at its rate limit.
_THROTTLE_RETRY_SECONDS = 5
_CLAIM_BATCH = 20
# Claim lease: a SENDING row whose next_attempt_at passed is considered
# abandoned by a crashed worker and becomes claimable again.
_CLAIM_LEASE_SECONDS = 600
# Idle backoff: poll fast while work flows, slow right down when the outbox
# is empty (saves ~constant idle claim queries).
_IDLE_INTERVAL_SECONDS = 30.0


def _now() -> datetime:
    # House convention since plan sprint-2/05: AWARE UTC everywhere (columns are timestamptz).
    return datetime.now(timezone.utc)


def _window_count(db: Session, connection_id: str) -> int:
    """Emails sent over this connection in the last 60s (durable rate window)."""
    cutoff = _now() - timedelta(seconds=60)
    return (
        db.query(EmailOutbox)
        .filter(
            EmailOutbox.connection_id == connection_id,
            EmailOutbox.status == OUTBOX_SENT,
            EmailOutbox.sent_at >= cutoff,
        )
        .count()
    )


def _fail_or_retry(db: Session, row: EmailOutbox, conn: Connection, error: str) -> None:
    """Retry with backoff; exhausted → platform fallback once → failed."""
    row.attempts += 1
    row.last_error = error
    conn.status = CONNECTION_STATUS_ERROR
    conn.last_error = error

    if row.attempts < MAX_ATTEMPTS:
        backoff = RETRY_BACKOFF_SECONDS[min(row.attempts - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
        row.status = OUTBOX_PENDING
        row.next_attempt_at = _now() + timedelta(seconds=backoff)
        return

    # Attempts exhausted on a TENANT connection → fall back to the platform
    # default once (plan 09 D6).
    if not row.used_fallback and conn.tenant_id != PLATFORM_TENANT_ID:
        platform = ConnectionRepository(db).get_by_provider(PLATFORM_TENANT_ID, EMAIL_PROVIDER)
        if platform is not None and platform.id != conn.id:
            row.connection_id = platform.id
            row.used_fallback = True
            row.attempts = 0
            row.status = OUTBOX_PENDING
            row.next_attempt_at = _now()
            return

    row.status = OUTBOX_FAILED


class _PassCache:
    """Per-pass caches: resolved connections + remaining rate budget."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = ConnectionRepository(db)
        self.connections: Dict[str, Optional[Connection]] = {}
        self.budget: Dict[str, int] = {}

    def resolve(self, row: EmailOutbox) -> Optional[Connection]:
        key = row.connection_id or f"tenant:{row.tenant_id}"
        if key not in self.connections:
            if row.connection_id:
                conn = self.db.get(Connection, row.connection_id)
                if conn is None:
                    conn = self.repo.resolve_for_send(row.tenant_id, EMAIL_PROVIDER)
            else:
                conn = self.repo.resolve_for_send(row.tenant_id, EMAIL_PROVIDER)
            self.connections[key] = conn
        return self.connections[key]

    def has_budget(self, conn: Connection) -> bool:
        if conn.id not in self.budget:
            limit = max(conn.rate_limit_per_minute, 1)  # clamp: 0/neg can't starve a row
            self.budget[conn.id] = limit - _window_count(self.db, conn.id)
        return self.budget[conn.id] > 0

    def consume(self, conn: Connection) -> None:
        self.budget[conn.id] -= 1


def dispatch_pending(db: Session, limit: int = _CLAIM_BATCH) -> int:
    """One dispatcher pass — claim due rows, send, settle. Returns sent count."""
    return _dispatch(db, limit)[1]


def _dispatch(db: Session, limit: int = _CLAIM_BATCH) -> tuple:
    """Returns (claimed, sent) — the loop idles only when nothing was claimed."""
    now = _now()
    rows = (
        db.query(EmailOutbox)
        .filter(
            # Due pending rows, plus SENDING rows whose claim lease expired
            # (a worker crashed mid-send — reclaim instead of orphaning).
            EmailOutbox.status.in_((OUTBOX_PENDING, OUTBOX_SENDING)),
            EmailOutbox.next_attempt_at <= now,
        )
        .order_by(EmailOutbox.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .all()
    )
    for row in rows:
        row.status = OUTBOX_SENDING
        row.next_attempt_at = now + timedelta(seconds=_CLAIM_LEASE_SECONDS)  # the lease
    db.commit()

    cache = _PassCache(db)
    sent = 0
    for row in rows:
        conn = cache.resolve(row)
        if conn is None:
            # No connection anywhere — dev-log the audit row as sent.
            logger.info("[email:%s] to=%s (no connection — dev log)", row.template_key, row.to_email)
            row.status = OUTBOX_SENT
            row.sent_at = _now()
            db.commit()
            continue

        row.connection_id = conn.id

        # Per-connection throttle (plan 09 D5 — low-spec SMTP guard).
        if not cache.has_budget(conn):
            row.status = OUTBOX_PENDING
            row.next_attempt_at = _now() + timedelta(seconds=_THROTTLE_RETRY_SECONDS)
            db.commit()
            continue

        provider = get_provider(conn.provider)
        if provider is None:
            _fail_or_retry(db, row, conn, f'Provider "{conn.provider}" is not available.')
            db.commit()
            continue

        try:
            credentials = decrypt_secret(conn.credentials_json) if conn.credentials_json else {}
            provider.send(
                conn.config_json or {},
                credentials,
                row.to_email,
                row.subject,
                row.html_body,
                row.text_body,
            )
            row.status = OUTBOX_SENT
            row.sent_at = _now()
            row.last_error = None
            conn.status = CONNECTION_STATUS_ACTIVE
            conn.last_error = None
            cache.consume(conn)
            sent += 1
        except Exception as e:  # noqa: BLE001 — transport failures drive retry
            logger.warning("email send failed (outbox=%s): %s", row.id, e)
            _fail_or_retry(db, row, conn, str(e))
        # Per-row commit is deliberate: each send is durably settled the moment
        # it happens (a crash later in the batch can't un-send or re-send it).
        db.commit()
    return len(rows), sent


def prune_sent(db: Session) -> int:
    """Housekeeping — delete terminal rows older than the retention window.

    SENT prunes on sent_at; FAILED/CANCELLED prune on created_at (plan 07
    D14 — the Email log shows history inside the window, nothing lives
    forever). PENDING is never pruned.
    """
    from app.models.email_outbox import OUTBOX_CANCELLED, OUTBOX_FAILED

    cutoff = _now() - timedelta(days=settings.email_outbox_retention_days)
    deleted = (
        db.query(EmailOutbox)
        .filter(EmailOutbox.status == OUTBOX_SENT, EmailOutbox.sent_at < cutoff)
        .delete(synchronize_session=False)
    )
    deleted += (
        db.query(EmailOutbox)
        .filter(
            EmailOutbox.status.in_((OUTBOX_FAILED, OUTBOX_CANCELLED)),
            EmailOutbox.created_at < cutoff,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


# ── daemon thread (started from the FastAPI lifespan) ────────────────────────

_stop = threading.Event()
_thread: Optional[threading.Thread] = None
_PRUNE_EVERY = 300  # passes between housekeeping runs


def _run() -> None:
    from app.database import SessionLocal

    passes = 0
    while not _stop.is_set():
        interval = settings.email_dispatch_interval_seconds
        try:
            db = SessionLocal()
            try:
                claimed, _ = _dispatch(db)
                if claimed == 0:
                    # Idle backoff — nothing claimable, don't hammer the DB.
                    interval = _IDLE_INTERVAL_SECONDS
                passes += 1
                if passes % _PRUNE_EVERY == 0:
                    prune_sent(db)
                    # Auth-throttle stale rows ride the same housekeeping
                    # cadence (plan 10 §5).
                    prune_stale_throttle_rows(db)
            finally:
                db.close()
        except Exception as e:  # noqa: BLE001 — the loop must survive anything
            logger.exception("dispatcher pass failed: %s", e)
        _stop.wait(interval)


def start_dispatcher() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, name="email-dispatcher", daemon=True)
    _thread.start()
    logger.info("email dispatcher started")


def stop_dispatcher() -> None:
    _stop.set()
