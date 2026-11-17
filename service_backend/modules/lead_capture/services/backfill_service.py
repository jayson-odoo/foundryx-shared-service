"""Backfill: re-read each routing source's forms for leads the webhook missed
(plan 64 AC-64-28, lane L-B).

Runs every 15 minutes for every ``WAITING_FOR_TEST`` / ``LIVE`` source (beat
``lead_capture.backfill_due``) and on demand (``POST /sources/{id}/backfill``,
"Run now"), plus once right after a ``NEEDS_RECONNECT`` source is reconnected.

Per source:
1. The forms to read: in "all" mode the Page's form list is read again each
   run (``GET /{page}/leadgen_forms``), so a form made after setup is
   included; in "pick" mode only the ticked ids.
2. Each form's leads created since the source's cursor (``GET /{form}/leads``,
   ``time_created`` filter), at most 90 days back, never before the form's own
   creation; a form made after the source was connected is read from its own
   creation the first time (then from the cursor), with a 10-minute overlap (Meta lists a lead a little after it is
   made; the store path is idempotent, so the overlap only costs a read).
3. Every lead goes through ``leadgen_service.store_lead`` - the SAME store
   path as the webhook, idempotent on (source, platform lead id).
4. The cursor moves to the run's start only after every lead is committed and
   only when no form was cut short; ``backfill_last_run_at`` /
   ``backfill_last_error`` record the outcome (Scheduled Tasks rule: last run,
   last error, Run now). A token error moves the source to NEEDS_RECONNECT
   (AC-64-29) through ``source_service``.

One source's failure never stops the others. No token or lead data in logs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..mapping import parse_meta_time
from ..meta_leads import MetaLeadClient, MetaLeadError
from ..models import PLATFORM_FACEBOOK, SOURCE_ROUTING_STATES, LcSource
from . import leadgen_service, source_service

logger = logging.getLogger(__name__)

MAX_LOOKBACK = timedelta(days=90)
OVERLAP = timedelta(minutes=10)
ERROR_CAP = 500
# Forms read in full at least once (config_json): only an unseen form made
# after the source was connected is read from its own creation.
SEEN_FORMS_KEY = "backfillForms"
MAX_SEEN_FORMS = 500


def enqueue_backfill(source_id: str) -> None:
    """Hand one source to the worker (inline in eager dev). Never raises."""
    try:
        from app.workflow_engine.worker import lead_capture_backfill_source

        lead_capture_backfill_source.delay(source_id)
    except Exception:  # noqa: BLE001 - the 15-minute tick is the backstop
        logger.exception("lead backfill enqueue failed for %s", source_id)


def request_backfill(db: Session, tenant_id: str, source_id: str) -> str:
    """"Run now" for one source of THIS tenant (AC-64-70)."""
    source = source_service.get_source(db, tenant_id, source_id)
    if source.status not in SOURCE_ROUTING_STATES:
        raise source_service.SourceError(
            409, "source_not_connected", "This source is not receiving leads. Reconnect the Page."
        )
    db.rollback()  # no read transaction held open while the worker runs
    enqueue_backfill(source.id)
    return source.id


def _since(source: LcSource, now: datetime) -> datetime:
    start = _aware(source.cursor_at or source.created_at) or now
    return max(start - OVERLAP, now - MAX_LOOKBACK)


def _forms(meta: MetaLeadClient, source: LcSource, token: str, dev: bool) -> List[Dict[str, Any]]:
    if source_service.forms_mode(source) == source_service.FORMS_PICK:
        return [{"id": form_id, "createdTime": None} for form_id in source_service.picked_forms(source)]
    return meta.leadgen_forms(token, source.account_ref or "", dev=dev)


def backfill_source(db: Session, source_id: str, *, client: Optional[MetaLeadClient] = None) -> int:
    """One backfill run for one source (worker side, resolved by id). Returns
    the number of new leads (for this source only)."""
    source = db.get(LcSource, source_id)
    if (
        source is None
        or source.status not in SOURCE_ROUTING_STATES
        or source.platform != PLATFORM_FACEBOOK
        or not leadgen_service._active(db, source.tenant_id)
    ):
        return 0
    meta = client or MetaLeadClient()
    creds = source_service.page_credentials(source)
    if creds is None or (meta.configured and creds.get("dev")):
        _finish(db, source_id, error="This source has no usable Page token. Reconnect the Page.")
        return 0
    dev = bool(creds.get("dev")) or not meta.configured
    started = datetime.now(timezone.utc)
    since = _since(source, started)
    page_id = source.account_ref or ""
    connected_at = _aware(source.created_at) or started
    seen = set((source.config_json or {}).get(SEEN_FORMS_KEY) or [])
    created = 0
    truncated: List[str] = []
    read: List[str] = []
    try:
        forms = _forms(meta, source, creds["pageToken"], dev)
        for form in forms:
            form_since = since
            made = parse_meta_time(form.get("createdTime"))
            if made is not None:
                if form["id"] not in seen and made > connected_at:
                    # A form made after the source was connected starts at its
                    # own creation on its first read (its early leads may have
                    # come before any run knew the form).
                    form_since = made - timedelta(minutes=1)
                form_since = max(form_since, made - timedelta(minutes=1), started - MAX_LOOKBACK)
            leads, cut = meta.form_leads(creds["pageToken"], form["id"], int(form_since.timestamp()), dev=dev)
            if cut:
                truncated.append(form["id"])
            else:
                read.append(form["id"])
            for raw in leads:
                source = db.get(LcSource, source_id)
                if source is None or source.status not in SOURCE_ROUTING_STATES:
                    return created  # disconnected / flipped while we ran
                if not source_service.accepts_form(source, raw.get("form_id") or form["id"]):
                    continue
                created += len(
                    leadgen_service.store_lead(
                        db, page_id, raw, [source], meta=meta, token=creds, form_id_hint=form["id"]
                    )
                )
    except MetaLeadError as exc:
        db.rollback()
        logger.info("lead backfill for source %s refused (code %s)", source_id, exc.code)
        message = "Facebook no longer accepts this Page's access. Reconnect the Page." if exc.token_invalid else exc.message
        if exc.token_invalid:
            source_service.mark_needs_reconnect(db, source_id)
        _finish(db, source_id, error=message)
        return created
    error = None
    if truncated:
        error = "More leads are waiting than one run reads; the next run continues."
    _finish(db, source_id, error=error, cursor=None if truncated else started, read_forms=read)
    return created


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _finish(
    db: Session,
    source_id: str,
    *,
    error: Optional[str],
    cursor: Optional[datetime] = None,
    read_forms: Optional[List[str]] = None,
) -> None:
    """Record the run (and move the cursor forward only) in its own commit."""
    db.rollback()
    source = db.get(LcSource, source_id)
    if source is None:
        return
    source.backfill_last_run_at = datetime.now(timezone.utc)
    source.backfill_last_error = (error or None) and error[:ERROR_CAP]
    if cursor is not None:
        current = source.cursor_at
        if current is not None and current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if current is None or cursor > current:
            source.cursor_at = cursor
    if read_forms:
        config = dict(source.config_json or {})
        seen = list(config.get(SEEN_FORMS_KEY) or [])
        seen += [f for f in read_forms if f not in seen]
        config[SEEN_FORMS_KEY] = seen[-MAX_SEEN_FORMS:]
        source.config_json = config  # fresh dict: in-place JSON edits are not tracked
    db.commit()


def run_due(db: Session) -> int:
    """The 15-minute tick: one run per routing source, every tenant. Returns
    how many sources were run; a failing source is logged and skipped."""
    ids = [
        sid for (sid,) in db.query(LcSource.id)
        .filter(LcSource.status.in_(SOURCE_ROUTING_STATES), LcSource.platform == PLATFORM_FACEBOOK)
        .order_by(LcSource.created_at.asc(), LcSource.id.asc())
        .all()
    ]
    db.rollback()
    ran = 0
    for source_id in ids:
        try:
            source = db.get(LcSource, source_id)
            if source is None or not leadgen_service._active(db, source.tenant_id):
                continue
            ran += 1
            backfill_source(db, source_id)
        except Exception:  # noqa: BLE001 - one bad source never stops the rest
            logger.exception("lead backfill failed for source %s", source_id)
            db.rollback()
            try:
                _finish(db, source_id, error="The backfill run failed. It runs again in 15 minutes.")
            except Exception:  # noqa: BLE001
                db.rollback()
    return ran
