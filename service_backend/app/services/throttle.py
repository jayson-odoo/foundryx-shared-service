"""Brute-force throttling for the public auth endpoints (plan 10 §5).

Dual counters (D6):
  - email: N fails per account per window → TEMP lock (never permanent — a
    hard lockout is an attacker DoS on victims). Success resets the counter.
  - ip:    N fails per client address per window → throttled until the window
    rolls over.

`ThrottleStore` is the small interface a future Redis adapter (BL-040)
implements; `DbThrottleStore` is the Postgres-backed default — auth traffic is
low-QPS and on-prem stays one-service (D5). Atomicity via row upsert + row
lock (`with_for_update`, a no-op on SQLite under tests).

The guard runs BEFORE any credential work (cheap rejection under attack) and
the 429 is deliberately distinct from the uniform 401 — locking is observable
anyway; clarity beats theater.
"""
import math
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.auth_throttle import (
    THROTTLE_SCOPE_DOC_SHARE,
    THROTTLE_SCOPE_EMAIL,
    THROTTLE_SCOPE_FORM_PUBLIC,
    THROTTLE_SCOPE_IP,
    THROTTLE_SCOPE_PORTAL,
    AuthThrottle,
)


class Throttled(Exception):
    """Over the limit — the router translates to 429 + Retry-After."""

    def __init__(self, retry_after_seconds: int):
        super().__init__(f"throttled for {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


def _now() -> datetime:
    # House convention since plan sprint-2/05: AWARE UTC everywhere (columns are timestamptz).
    return datetime.now(timezone.utc)


def _scope_policy(scope: str) -> tuple[int, timedelta, Optional[timedelta]]:
    """(max_fails, window, lock) for a scope — read at call time so tests and
    ops tune Settings without restarts."""
    if scope == THROTTLE_SCOPE_EMAIL:
        return (
            settings.throttle_email_max_fails,
            timedelta(minutes=settings.throttle_email_window_minutes),
            timedelta(minutes=settings.throttle_email_lock_minutes),
        )
    if scope == THROTTLE_SCOPE_FORM_PUBLIC:
        return (
            settings.throttle_form_public_max_fails,
            timedelta(minutes=settings.throttle_form_public_window_minutes),
            None,  # over-limit throttles until the window rolls over (like IP)
        )
    if scope == THROTTLE_SCOPE_DOC_SHARE:
        return (
            settings.throttle_doc_share_max_fails,
            timedelta(minutes=settings.throttle_doc_share_window_minutes),
            None,  # over-limit throttles until the window rolls over (like IP)
        )
    if scope == THROTTLE_SCOPE_PORTAL:
        return (
            settings.throttle_portal_max_fails,
            timedelta(minutes=settings.throttle_portal_window_minutes),
            None,  # over-limit throttles until the window rolls over (like IP)
        )
    return (
        settings.throttle_ip_max_fails,
        timedelta(minutes=settings.throttle_ip_window_minutes),
        None,  # IP over-limit throttles until the window rolls over
    )


class ThrottleStore(Protocol):
    """Counter backend. Small on purpose — the Redis impl (BL-040) is one file."""

    def check(self, scope: str, key: str) -> Optional[int]:
        """None = allowed; int = seconds until the caller may retry."""
        ...

    def record_failure(self, scope: str, key: str) -> None: ...

    def reset(self, scope: str, key: str) -> None: ...


class DbThrottleStore:
    def __init__(self, db: Session):
        self.db = db

    def _get(self, scope: str, key: str, *, for_update: bool = False) -> Optional[AuthThrottle]:
        q = self.db.query(AuthThrottle).filter(
            AuthThrottle.scope == scope, AuthThrottle.key == key
        )
        if for_update:
            q = q.with_for_update()
        return q.first()

    def check(self, scope: str, key: str) -> Optional[int]:
        now = _now()
        row = self._get(scope, key)
        if row is None:
            return None
        if row.locked_until is not None and row.locked_until > now:
            return math.ceil((row.locked_until - now).total_seconds())
        max_fails, window, _lock = _scope_policy(scope)
        window_end = row.window_start + window
        if window_end <= now:
            return None  # stale window — counters no longer apply
        if row.fail_count >= max_fails:
            return math.ceil((window_end - now).total_seconds())
        return None

    def record_failure(self, scope: str, key: str) -> None:
        now = _now()
        max_fails, window, lock = _scope_policy(scope)
        row = self._get(scope, key, for_update=True)
        if row is None:
            row = AuthThrottle(scope=scope, key=key, window_start=now, fail_count=1)
            self.db.add(row)
            try:
                self.db.commit()
            except IntegrityError:
                # Concurrent first-failure race — retry against the winner's row.
                self.db.rollback()
                row = self._get(scope, key, for_update=True)
                if row is None:  # pragma: no cover — row vanished between statements
                    return
                self._bump(row, now, max_fails, window, lock)
            else:
                return
        else:
            self._bump(row, now, max_fails, window, lock)

    def _bump(
        self,
        row: AuthThrottle,
        now: datetime,
        max_fails: int,
        window: timedelta,
        lock: Optional[timedelta],
    ) -> None:
        if row.window_start + window <= now:
            # New window — start over (also clears an expired lock).
            row.window_start = now
            row.fail_count = 1
            row.locked_until = None
        else:
            row.fail_count += 1
        if lock is not None and row.fail_count >= max_fails:
            row.locked_until = now + lock
        self.db.add(row)
        self.db.commit()

    def reset(self, scope: str, key: str) -> None:
        self.db.query(AuthThrottle).filter(
            AuthThrottle.scope == scope, AuthThrottle.key == key
        ).delete(synchronize_session=False)
        self.db.commit()


def prune_stale(db: Session) -> int:
    """Housekeeping — drop rows whose window AND lock are long past. Piggybacks
    the email-dispatcher housekeeping pass (plan 10 §5)."""
    horizon = _now() - timedelta(
        minutes=2
        * max(
            settings.throttle_email_window_minutes,
            settings.throttle_ip_window_minutes,
            settings.throttle_email_lock_minutes,
        )
    )
    deleted = (
        db.query(AuthThrottle)
        .filter(
            AuthThrottle.window_start < horizon,
            (AuthThrottle.locked_until.is_(None)) | (AuthThrottle.locked_until < horizon),
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


# ── request-level helpers (used by the auth router) ──────────────────────────


def client_ip(request: Request) -> str:
    """The throttle key for the caller's address. X-Forwarded-For (first hop)
    is honored ONLY behind the known proxy (`trust_proxy_headers`) — otherwise
    attackers mint fresh counters per spoofed header."""
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first_hop = forwarded.split(",")[0].strip()
            if first_hop:
                return first_hop
    return request.client.host if request.client else "unknown"


def normalize_email(email: str) -> str:
    return email.strip().lower()


class ThrottleService:
    """Orchestrates the dual check for the auth endpoints. Check order: IP
    first (cheapest, broadest), then email (login only)."""

    def __init__(self, db: Session, store: Optional[ThrottleStore] = None):
        self.store: ThrottleStore = store or DbThrottleStore(db)

    def enforce(self, *, ip: str, email: Optional[str] = None) -> None:
        retry = self.store.check(THROTTLE_SCOPE_IP, ip)
        if retry is None and email is not None:
            retry = self.store.check(THROTTLE_SCOPE_EMAIL, normalize_email(email))
        if retry is not None:
            raise Throttled(retry)

    def record_login_failure(self, *, ip: str, email: str) -> None:
        self.store.record_failure(THROTTLE_SCOPE_IP, ip)
        self.store.record_failure(THROTTLE_SCOPE_EMAIL, normalize_email(email))

    def record_ip_attempt(self, *, ip: str) -> None:
        self.store.record_failure(THROTTLE_SCOPE_IP, ip)

    def reset_email(self, email: str) -> None:
        self.store.reset(THROTTLE_SCOPE_EMAIL, normalize_email(email))

    # ---- public form submissions (own bucket, plan sprint-3/02 D12) ----

    def enforce_form_public(self, *, ip: str) -> None:
        retry = self.store.check(THROTTLE_SCOPE_FORM_PUBLIC, ip)
        if retry is not None:
            raise Throttled(retry)

    def record_form_public(self, *, ip: str) -> None:
        self.store.record_failure(THROTTLE_SCOPE_FORM_PUBLIC, ip)

    # ---- public document-share access (own bucket, plan sprint-3/05 D6) ----

    def enforce_doc_share(self, *, ip: str) -> None:
        retry = self.store.check(THROTTLE_SCOPE_DOC_SHARE, ip)
        if retry is not None:
            raise Throttled(retry)

    def record_doc_share(self, *, ip: str) -> None:
        self.store.record_failure(THROTTLE_SCOPE_DOC_SHARE, ip)

    # ---- Profile Portal auth (own bucket, sprint-4/06 slice 0a, AC-06-16) ----

    def enforce_portal(self, *, ip: str) -> None:
        retry = self.store.check(THROTTLE_SCOPE_PORTAL, ip)
        if retry is not None:
            raise Throttled(retry)

    def record_portal(self, *, ip: str) -> None:
        self.store.record_failure(THROTTLE_SCOPE_PORTAL, ip)
