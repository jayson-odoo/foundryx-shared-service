"""Backfill: re-read each routing source's forms for leads the webhook missed
(plan 64 AC-64-28, lane L-B).

Runs every 15 minutes for every ``WAITING_FOR_TEST`` / ``LIVE`` source (beat
``lead_capture.backfill_due``) and on demand (``POST /sources/{id}/backfill``,
"Run now"), plus once right after a ``NEEDS_RECONNECT`` source is reconnected.

Per source:
1. Claim the run (``backfill_started_at``, guarded UPDATE): a run already in
   flight is skipped; a claim older than ``STALE_CLAIM`` (a crashed worker) is
   taken over.
2. The forms to read: in "all" mode the Page's form list is read again each
   run (``GET /{page}/leadgen_forms``), so a form made after setup is
   included; in "pick" mode only the ticked ids.
3. Each form is read from ITS OWN cursor (``config_json.formCursors``) in
   time windows (``GET /{form}/leads`` with ``time_created`` GREATER_THAN /
   LESS_THAN). A window too full for one capped read is halved; a window
   fully stored moves that form's cursor. So a busy form, or a run cut by
   the page budget, continues next run where it stopped and never holds back
   the other forms. A form with no cursor yet starts at the source's cursor
   (or connect time), or at its own creation when it was made after the
   source was connected; never more than 90 days back.
4. Every lead goes through ``leadgen_service.store_lead`` - the SAME store
   path as the webhook, idempotent on (source, platform lead id).
5. One form's error is recorded and the run carries on with the others; only
   a dead token (or a refused Page-level form list) stops the run and moves
   the source to NEEDS_RECONNECT (AC-64-29) through ``source_service``.
6. ``backfill_last_run_at`` / ``backfill_last_error`` record the outcome
   (Scheduled Tasks rule: last run, last error, Run now).

No token or lead data in logs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import meta_leads
from ..mapping import parse_meta_time
from ..meta_leads import MetaLeadClient, MetaLeadError
from ..models import PLATFORM_FACEBOOK, SOURCE_ROUTING_STATES, LcSource
from . import leadgen_service, source_service

logger = logging.getLogger(__name__)

MAX_LOOKBACK = timedelta(days=90)
OVERLAP = timedelta(minutes=10)
WINDOW = timedelta(days=1)
MIN_WINDOW = timedelta(minutes=1)
RUN_PAGE_BUDGET = 200  # lead-list pages per source per run
STALE_CLAIM = timedelta(minutes=30)
RUN_NOW_COOLDOWN_SECONDS = 60
ERROR_CAP = 500
FORM_CURSORS_KEY = "formCursors"
MAX_FORM_CURSORS = 500


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def enqueue_backfill(source_id: str) -> None:
    """Hand one source to the worker (inline in eager dev). Never raises."""
    try:
        from app.workflow_engine.worker import lead_capture_backfill_source

        lead_capture_backfill_source.delay(source_id)
    except Exception:  # noqa: BLE001 - the 15-minute tick is the backstop
        logger.exception("lead backfill enqueue failed for %s", source_id)


def request_backfill(db: Session, tenant_id: str, source_id: str) -> str:
    """"Run now" for one source of THIS tenant (AC-64-70). One per minute,
    and never while a run is in flight."""
    source = source_service.get_source(db, tenant_id, source_id)
    if source.status not in SOURCE_ROUTING_STATES:
        raise source_service.SourceError(
            409, "source_not_connected", "This source is not receiving leads. Reconnect the Page."
        )
    now = datetime.now(timezone.utc)
    last = _aware(source.backfill_last_run_at)
    started = _aware(source.backfill_started_at)
    wait = 0
    if started is not None and now - started < STALE_CLAIM:
        wait = RUN_NOW_COOLDOWN_SECONDS
    elif last is not None:
        wait = RUN_NOW_COOLDOWN_SECONDS - int((now - last).total_seconds())
    if 0 < wait <= RUN_NOW_COOLDOWN_SECONDS:
        raise source_service.SourceError(
            429, "backfill_cooldown", f"A backfill ran a moment ago. Try again in {wait} seconds.", retry_after=wait
        )
    db.rollback()  # no read transaction held open while the worker runs
    enqueue_backfill(source.id)
    return source.id


# ── run claim ───────────────────────────────────────────────────────────────

def _claim(db: Session, source_id: str, now: datetime) -> bool:
    claimed = (
        db.query(LcSource)
        .filter(
            LcSource.id == source_id,
            LcSource.status.in_(SOURCE_ROUTING_STATES),
            or_(LcSource.backfill_started_at.is_(None), LcSource.backfill_started_at < now - STALE_CLAIM),
        )
        .update({"backfill_started_at": now}, synchronize_session=False)
    )
    db.commit()
    return claimed == 1


def _finish(db: Session, source_id: str, *, error: Optional[str], cursor: Optional[datetime] = None) -> None:
    """Record the run, release the claim, move the source cursor forward
    only - in its own commit."""
    db.rollback()
    source = source_service.locked_source(db, source_id)
    if source is None:
        return
    source.backfill_last_run_at = datetime.now(timezone.utc)
    source.backfill_last_error = (error or None) and error[:ERROR_CAP]
    source.backfill_started_at = None
    current = _aware(source.cursor_at)
    if cursor is not None and (current is None or cursor > current):
        source.cursor_at = cursor
    db.commit()


# ── one run ─────────────────────────────────────────────────────────────────

@dataclass
class _Budget:
    pages: int
    notes: List[str]


def _forms(meta: MetaLeadClient, source: LcSource, token: str, dev: bool) -> List[Dict[str, Any]]:
    if source_service.forms_mode(source) == source_service.FORMS_PICK:
        return [{"id": form_id, "createdTime": None} for form_id in source_service.picked_forms(source)]
    return meta.leadgen_forms(token, source.account_ref or "", dev=dev)


def _form_since(source: LcSource, form: Dict[str, Any], started: datetime) -> datetime:
    cursors = (source.config_json or {}).get(FORM_CURSORS_KEY) or {}
    made = parse_meta_time(form.get("createdTime"))
    own = cursors.get(form["id"])
    own_at = None
    if isinstance(own, str):
        try:
            own_at = _aware(datetime.fromisoformat(own))
        except ValueError:
            own_at = None
    connected_at = _aware(source.created_at) or started
    if own_at is not None:
        since = own_at - OVERLAP
    elif made is not None and made > connected_at:
        since = made - timedelta(minutes=1)  # a form made after connect starts at its own creation
    else:
        since = (_aware(source.cursor_at) or connected_at) - OVERLAP
    since = max(since, started - MAX_LOOKBACK)
    if made is not None:
        since = max(since, made - timedelta(minutes=1))
    return since


def _save_form_cursor(db: Session, source_id: str, form_id: str, at: datetime) -> None:
    source = source_service.locked_source(db, source_id)
    if source is None:
        return
    config = dict(source.config_json or {})
    cursors = dict(config.get(FORM_CURSORS_KEY) or {})
    cursors.pop(form_id, None)
    cursors[form_id] = at.isoformat()
    config[FORM_CURSORS_KEY] = dict(list(cursors.items())[-MAX_FORM_CURSORS:])
    source.config_json = config  # fresh dict: in-place JSON edits are not tracked
    db.commit()


class _Stop(Exception):
    """The source left routing while the run went on."""


def _read_form(
    db: Session,
    meta: MetaLeadClient,
    source_id: str,
    page_id: str,
    creds: Dict[str, Any],
    dev: bool,
    form_id: str,
    since: datetime,
    until: datetime,
    budget: _Budget,
    test_ids: Dict[str, Any],
) -> tuple:
    """Read one form's window ``(since, until]`` in pieces. Returns
    ``(created, complete)``; ``complete`` False = the page budget ran out."""
    created = 0
    cursor = since
    window = WINDOW
    while cursor < until:
        if budget.pages <= 0:
            return created, False
        end = min(cursor + window, until)
        leads, cut = meta.form_leads(
            creds["pageToken"], form_id, int(cursor.timestamp()), int(end.timestamp()) + 1, dev=dev
        )
        budget.pages -= meta_leads.MAX_PAGES if cut else max(1, -(-len(leads) // max(1, meta_leads.PAGE_SIZE)))
        if cut and end - cursor > MIN_WINDOW:
            # Too full for one capped read: at least halve the window, and
            # since Meta lists newest first (the leads not read are older than
            # the oldest one returned) end it there when that is sooner. Every
            # piece read in full moves the form's cursor, so the next run
            # continues from it.
            oldest = min(
                (t for t in (parse_meta_time(r.get("created_time")) for r in leads) if t is not None),
                default=None,
            )
            narrow = (end - cursor) / 2
            if oldest is not None and cursor < oldest < cursor + narrow:
                narrow = oldest - cursor
            window = max(narrow, MIN_WINDOW)
            continue
        if cut:
            budget.notes.append(
                f"Form {form_id}: more leads in one minute than one read takes; some of them could not be read."
            )
        for raw in leads:
            source = db.get(LcSource, source_id)
            if source is None or source.status not in SOURCE_ROUTING_STATES:
                raise _Stop()
            created += len(
                leadgen_service.store_lead(
                    db, page_id, raw, [source], meta=meta, token=creds, form_id_hint=form_id, test_ids_cache=test_ids
                )
            )
        _save_form_cursor(db, source_id, form_id, end)
        cursor = end
        window = min(window * 2, WINDOW)
    return created, True


def backfill_source(db: Session, source_id: str, *, client: Optional[MetaLeadClient] = None) -> int:
    """One backfill run for one source (worker side, resolved by id). Returns
    the number of new leads for this source."""
    source = db.get(LcSource, source_id)
    if (
        source is None
        or source.status not in SOURCE_ROUTING_STATES
        or source.platform != PLATFORM_FACEBOOK
        or not leadgen_service._active(db, source.tenant_id)
    ):
        return 0
    started = datetime.now(timezone.utc)
    if not _claim(db, source_id, started):
        return 0  # a run is already in flight
    try:
        return _run(db, source_id, started, client or MetaLeadClient())
    except Exception:
        db.rollback()
        _finish(db, source_id, error="The backfill run failed. It runs again in 15 minutes.")
        raise


def _run(db: Session, source_id: str, started: datetime, meta: MetaLeadClient) -> int:
    source = db.get(LcSource, source_id)
    creds = source_service.page_credentials(source) if source is not None else None
    if source is None or creds is None or (meta.configured and creds.get("dev")):
        _finish(db, source_id, error="This source has no usable Page token. Reconnect the Page.")
        return 0
    dev = bool(creds.get("dev")) or not meta.configured
    page_id = source.account_ref or ""
    try:
        forms = _forms(meta, source, creds["pageToken"], dev)
    except MetaLeadError as exc:
        # The Page-level list: any token / permission answer means the Page.
        return _fail(db, source_id, exc, flip=exc.token_invalid)
    budget = _Budget(RUN_PAGE_BUDGET, [])
    # The forms read longest ago go first, so a page budget used up by a few
    # busy forms never starves the same forms run after run.
    cursors = (source.config_json or {}).get(FORM_CURSORS_KEY) or {}
    forms = sorted(forms, key=lambda f: (f["id"] in cursors, str(cursors.get(f["id"]) or "")))
    test_ids: Dict[str, Any] = {}
    created = 0
    errors: List[str] = []
    complete = True
    for form in forms:
        source = db.get(LcSource, source_id)
        if source is None or source.status not in SOURCE_ROUTING_STATES:
            _finish(db, source_id, error=None)
            return created
        since = _form_since(source, form, started)
        try:
            count, done = _read_form(
                db, meta, source_id, page_id, creds, dev, form["id"], since, started, budget, test_ids
            )
        except _Stop:
            _finish(db, source_id, error=None)
            return created
        except MetaLeadError as exc:
            db.rollback()
            if exc.token_dead:
                return created + _fail(db, source_id, exc, flip=True)
            # One form refused (deleted, form-level access): note it, go on.
            logger.info("lead backfill: one form of source %s refused (code %s)", source_id, exc.code)
            errors.append(f"Form {form['id']}: {exc.message}")
            complete = False
            continue
        created += count
        if not done:
            complete = False
            errors.append("More leads are waiting than one run reads; the next run continues.")
            break
    errors += budget.notes
    _finish(db, source_id, error=" ".join(errors) or None, cursor=started if complete else None)
    return created


def _fail(db: Session, source_id: str, exc: MetaLeadError, *, flip: bool) -> int:
    db.rollback()
    logger.info("lead backfill for source %s refused (code %s)", source_id, exc.code)
    if flip:
        source_service.mark_needs_reconnect(db, source_id)
        message = "Facebook no longer accepts this Page's access. Reconnect the Page."
    else:
        message = exc.message
    _finish(db, source_id, error=message)
    return 0


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
    return ran
