"""Integration failure alerts (plan 33, AC-33-01..11).

A scheduled AutoCount integration (one ``AcEntityConfig`` row) that keeps
failing - or stops producing clean runs at all - opens ONE incident, tells the
tenant's integration admins by email (outbox only) and shows on the screen
until a clean run closes it.

**Time-based evaluator, not a run hook.** A run reaches its terminal state
through ~20 exits (``_fail``, ``_abort``, two success blocks, the orphan
sweep), so the watcher reads the run history instead, once per ETL sweep tick
(``scheduler.sweep_etl_tasks`` calls ``evaluate_integration_alerts`` last).
That also catches a wedged run that never finishes: no clean run for the stale
window opens a ``stale`` incident.

Rules (per ACTIVE, enabled, push-mode integration):
  * consecutive - the last N scheduled runs since the later of the last clean
    run and the last activation all failed (FAILED, or SUCCESS carrying a push
    ``error``). Manual failures, skipped ticks, aborted and snapshot runs
    neither count nor reset; any clean run (scheduled or manual) resets.
  * stale - no clean run finished for ``max(M x incrementalMinutes, 60 min)``,
    measured from the later of the last clean run and the last activation.

Settings live in ``source_config`` beside the schedule; an absent key is the
default, so every existing integration is covered with no backfill.
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.models import User, UserStatus
from app.services.email_service import email_service

from .models import (
    DELIVERY_MODE_PUSH,
    ETL_STATUS_ACTIVE,
    INCIDENT_CLOSE_DISABLED,
    INCIDENT_CLOSE_PAUSED,
    INCIDENT_CLOSE_RECOVERED,
    INCIDENT_REASON_CONSECUTIVE,
    INCIDENT_REASON_STALE,
    RUN_MODE_INCREMENTAL,
    RUN_MODE_MANUAL,
    RUN_MODE_RECONCILE,
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcTaskIncident,
)
from .repositories import CompanyRepository, SyncRunRepository, TaskIncidentRepository

logger = logging.getLogger("foundryx.autocount")

DEFAULT_ALERT_AFTER_FAILED_RUNS = 2
DEFAULT_ALERT_STALE_MULTIPLE = 3
STALE_FLOOR_MINUTES = 60
REMINDER_INTERVAL = timedelta(hours=4)
MAX_ALERT_EMAILS = 10

MIN_ALERT_AFTER_FAILED_RUNS = 1
MAX_ALERT_AFTER_FAILED_RUNS = 20
MIN_ALERT_STALE_MULTIPLE = 2
MAX_ALERT_STALE_MULTIPLE = 48

MANAGE_PERMISSION = "autocount.companies.manage"
DEFAULT_INCREMENTAL_MINUTES = 15

# Scheduled modes that can fail an integration; every mode a user can read as
# "this integration ran fine" (a skipped tick or a snapshot says nothing).
FAILED_RUN_MODES = (RUN_MODE_INCREMENTAL, RUN_MODE_RECONCILE)
CLEAN_RUN_MODES = (RUN_MODE_MANUAL, RUN_MODE_INCREMENTAL, RUN_MODE_RECONCILE)

ALERT_SETTING_KEYS = ("alertsEnabled", "alertAfterFailedRuns", "alertStaleMultiple", "alertEmails")

_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
_ERROR_LINE_MAX = 500


# ── settings ─────────────────────────────────────────────────────────────────


def resolve_alert_settings(source_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The four settings with defaults filled in. A stored value of the wrong
    shape reads as the default - never trust a JSON blob a tenant could edit."""
    stored = source_config if isinstance(source_config, dict) else {}
    enabled = stored.get("alertsEnabled")
    after = stored.get("alertAfterFailedRuns")
    multiple = stored.get("alertStaleMultiple")
    emails = stored.get("alertEmails")
    return {
        "alertsEnabled": enabled if isinstance(enabled, bool) else True,
        "alertAfterFailedRuns": (
            after
            if isinstance(after, int) and not isinstance(after, bool)
            and MIN_ALERT_AFTER_FAILED_RUNS <= after <= MAX_ALERT_AFTER_FAILED_RUNS
            else DEFAULT_ALERT_AFTER_FAILED_RUNS
        ),
        "alertStaleMultiple": (
            multiple
            if isinstance(multiple, int) and not isinstance(multiple, bool)
            and MIN_ALERT_STALE_MULTIPLE <= multiple <= MAX_ALERT_STALE_MULTIPLE
            else DEFAULT_ALERT_STALE_MULTIPLE
        ),
        "alertEmails": (
            [e for e in emails if isinstance(e, str) and _EMAIL_RE.match(e)]
            if isinstance(emails, list)
            else []
        ),
    }


def _bounded_int(value: Any, low: int, high: int) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if low <= value <= high else None


def validate_alert_settings(
    updates: Dict[str, Any], stored_source_config: Optional[Dict[str, Any]]
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Merge a save's alert fields (``None`` = keep) over the stored keys.

    Returns the alert keys to write into the new ``source_config`` (only keys
    that were stored before or sent now - an untouched integration stays
    key-free) plus a per-field error map in the house ``fieldErrors`` shape."""
    stored = stored_source_config if isinstance(stored_source_config, dict) else {}
    merged: Dict[str, Any] = {k: stored[k] for k in ALERT_SETTING_KEYS if k in stored}
    errors: Dict[str, str] = {}

    enabled = updates.get("alertsEnabled")
    if enabled is not None:
        if isinstance(enabled, bool):
            merged["alertsEnabled"] = enabled
        else:
            errors["alertsEnabled"] = "Choose on or off."

    after = updates.get("alertAfterFailedRuns")
    if after is not None:
        clean = _bounded_int(after, MIN_ALERT_AFTER_FAILED_RUNS, MAX_ALERT_AFTER_FAILED_RUNS)
        if clean is None:
            errors["alertAfterFailedRuns"] = (
                f"Between {MIN_ALERT_AFTER_FAILED_RUNS} and {MAX_ALERT_AFTER_FAILED_RUNS} runs."
            )
        else:
            merged["alertAfterFailedRuns"] = clean

    multiple = updates.get("alertStaleMultiple")
    if multiple is not None:
        clean = _bounded_int(multiple, MIN_ALERT_STALE_MULTIPLE, MAX_ALERT_STALE_MULTIPLE)
        if clean is None:
            errors["alertStaleMultiple"] = (
                f"Between {MIN_ALERT_STALE_MULTIPLE} and {MAX_ALERT_STALE_MULTIPLE} intervals."
            )
        else:
            merged["alertStaleMultiple"] = clean

    emails = updates.get("alertEmails")
    if emails is not None:
        if not isinstance(emails, list) or not all(isinstance(e, str) for e in emails):
            errors["alertEmails"] = "Enter email addresses."
        else:
            cleaned: List[str] = []
            seen = set()
            for address in (e.strip() for e in emails):
                if not _EMAIL_RE.match(address):
                    errors["alertEmails"] = f"'{address}' is not a valid email address."
                    break
                if address.lower() not in seen:
                    seen.add(address.lower())
                    cleaned.append(address)
            else:
                if len(cleaned) > MAX_ALERT_EMAILS:
                    errors["alertEmails"] = f"At most {MAX_ALERT_EMAILS} addresses."
                else:
                    merged["alertEmails"] = cleaned
    return merged, errors


# ── evaluator ────────────────────────────────────────────────────────────────


def _first_line(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    return line[:_ERROR_LINE_MAX] or None


def _interval_minutes(source_config: Optional[Dict[str, Any]]) -> int:
    value = (source_config or {}).get("incrementalMinutes")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return DEFAULT_INCREMENTAL_MINUTES
    return value


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def evaluate_integration_alerts(db: Session, *, now: Optional[datetime] = None) -> Dict[str, int]:
    """One pass over every integration of every tenant where the AutoCount
    Service is active. One integration's error is logged and isolated: it
    rolls back only its own unit of work and the rest are still checked."""
    from .scheduler import active_tenant_service_join  # scheduler imports etl_service

    now = now or datetime.now(timezone.utc)
    counts = {"opened": 0, "reminded": 0, "recovered": 0, "closed": 0, "failed": 0}
    open_ids = TaskIncidentRepository(db).all_open_config_ids()
    # Same tenant lifecycle + module-active predicate as the sweep itself. An
    # integration that stopped being alertable is still loaded when it holds an
    # open incident, so the incident can be closed.
    configs = (
        active_tenant_service_join(db.query(AcEntityConfig), AcEntityConfig.tenant_id)
        .filter(
            or_(
                and_(
                    AcEntityConfig.etl_status == ETL_STATUS_ACTIVE,
                    AcEntityConfig.source_impl.in_((SOURCE_IMPL_SQL_DB, SOURCE_IMPL_AUTOCOUNT_HTTP)),
                    AcEntityConfig.delivery_mode == DELIVERY_MODE_PUSH,
                ),
                AcEntityConfig.id.in_(open_ids),
            )
        )
        .all()
    )
    keys = [(config.tenant_id, config.id) for config in configs]
    for tenant_id, config_id in keys:
        try:
            config = db.get(AcEntityConfig, config_id)
            if config is None or config.tenant_id != tenant_id:
                continue
            _evaluate_one(db, config, now, counts)
            db.commit()
        except Exception:  # noqa: BLE001 - one integration never stops the check
            logger.exception("autocount failure-alert check failed for %s/%s", tenant_id, config_id)
            db.rollback()
            counts["failed"] += 1
    return counts


def _alertable(config: AcEntityConfig) -> bool:
    return bool(
        config.etl_status == ETL_STATUS_ACTIVE
        and config.enabled
        and config.delivery_mode == DELIVERY_MODE_PUSH
        and config.source_impl in (SOURCE_IMPL_SQL_DB, SOURCE_IMPL_AUTOCOUNT_HTTP)
    )


def _close(incident: AcTaskIncident, now: datetime, reason: str) -> None:
    incident.closed_at = now
    incident.close_reason = reason


def _evaluate_one(
    db: Session, config: AcEntityConfig, now: datetime, counts: Dict[str, int]
) -> None:
    incidents = TaskIncidentRepository(db)
    incident = incidents.get_open(config.tenant_id, config.id)
    alert_settings = resolve_alert_settings(config.source_config)

    # Paused / deactivated / alerts off: close silently, never open.
    if not _alertable(config) or not alert_settings["alertsEnabled"]:
        if incident is not None:
            if config.etl_status != ETL_STATUS_ACTIVE:
                reason = INCIDENT_CLOSE_PAUSED
            else:
                reason = INCIDENT_CLOSE_DISABLED
            _close(incident, now, reason)
            counts["closed"] += 1
        return

    company = CompanyRepository(db).get(config.tenant_id, config.company_id)
    if company is None:
        return

    runs = SyncRunRepository(db)
    last_clean = _aware(
        runs.last_clean_finished_at(
            config.tenant_id, config.company_id, config.entity_type, CLEAN_RUN_MODES
        )
    )
    started = max(
        (t for t in (_aware(config.activated_at), _aware(config.resumed_at)) if t is not None),
        default=None,
    )
    anchor = max((t for t in (last_clean, started) if t is not None), default=None)
    failed = runs.failed_runs_since(
        config.tenant_id, config.company_id, config.entity_type, anchor, FAILED_RUN_MODES
    )
    last_error = _first_line(failed[-1].error) if failed else None

    if incident is not None:
        if last_clean is not None and last_clean > _aware(incident.opened_at):
            _close(incident, now, INCIDENT_CLOSE_RECOVERED)
            counts["recovered"] += 1
            _notify(db, config, company, incident, "recovered", now, alert_settings)
            return
        incident.failed_runs = len(failed) if failed else incident.failed_runs
        if last_error:
            incident.last_error = last_error
        since = _aware(incident.last_notified_at) or _aware(incident.opened_at)
        if now - since >= REMINDER_INTERVAL:
            _notify(db, config, company, incident, "reminder", now, alert_settings)
            counts["reminded"] += 1
        return

    reason: Optional[str] = None
    first_failure: Optional[datetime] = None
    if len(failed) >= alert_settings["alertAfterFailedRuns"]:
        reason = INCIDENT_REASON_CONSECUTIVE
        first_failure = _aware(failed[0].finished_at)
    elif anchor is not None:
        window = max(
            timedelta(minutes=alert_settings["alertStaleMultiple"] * _interval_minutes(config.source_config)),
            timedelta(minutes=STALE_FLOOR_MINUTES),
        )
        if now - anchor >= window:
            reason = INCIDENT_REASON_STALE
            first_failure = anchor
    if reason is None:
        return

    incident = incidents.add(
        AcTaskIncident(
            tenant_id=config.tenant_id,
            company_id=config.company_id,
            entity_config_id=config.id,
            entity_type=config.entity_type,
            reason=reason,
            opened_at=now,
            first_failure_at=first_failure,
            failed_runs=len(failed),
            last_error=last_error,
            notices_sent=0,
        )
    )
    counts["opened"] += 1
    _notify(db, config, company, incident, "alert", now, alert_settings)


# ── recipients + emails ──────────────────────────────────────────────────────


def alert_recipients(
    db: Session, tenant_id: str, also_email: List[str]
) -> List[Tuple[str, Optional[str]]]:
    """``(address, timezone)`` pairs: ACTIVE users of THIS tenant holding the
    manage permission, then the integration's "Also email" addresses, de-duplicated
    case-insensitively (a user wins over a typed address, keeping their zone)."""
    users = TaskIncidentRepository(db).users_with_permission(tenant_id, MANAGE_PERMISSION)
    seen: Dict[str, Tuple[str, Optional[str]]] = {}
    for user in users:
        if user.status == UserStatus.ACTIVE.value and user.email:
            seen.setdefault(user.email.strip().lower(), (user.email.strip(), user.timezone))
    for address in also_email:
        seen.setdefault(address.strip().lower(), (address.strip(), None))
    return list(seen.values())


def _zone(name: Optional[str]) -> tzinfo:
    if name:
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - an unknown stored zone reads as UTC
            return timezone.utc
    return timezone.utc


def _local(value: datetime, zone: tzinfo) -> str:
    """``30 Aug 2026, 19:40 +08`` - the zone is always shown."""
    local = _aware(value).astimezone(zone)
    return f"{local.day} {local:%b %Y, %H:%M} {local.tzname() or 'UTC'}"


def _short(value: datetime, zone: tzinfo) -> str:
    local = _aware(value).astimezone(zone)
    return f"{local.day} {local:%b %H:%M} {local.tzname() or 'UTC'}"


def _runs_word(count: int) -> str:
    return f"{count} run" if count == 1 else f"{count} runs"


def _duration(start: datetime, end: datetime) -> str:
    minutes = max(int((_aware(end) - _aware(start)).total_seconds() // 60), 0)
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {rest} min"
    days, hours = divmod(hours, 24)
    return f"{days} d {hours} h"


def _runs_link(config: AcEntityConfig) -> str:
    base = app_settings.frontend_url.rstrip("/")
    return f"{base}/autocount/companies/{config.company_id}/entities/{config.entity_type}?tab=runs"


def _label(config: AcEntityConfig) -> str:
    """The integration's display name: the entity type, title-cased (the same
    words the screen shows)."""
    return config.entity_type.replace("_", " ").capitalize()


def _compose(
    kind: str,
    config: AcEntityConfig,
    company: AcCompany,
    incident: AcTaskIncident,
    now: datetime,
    zone: tzinfo,
) -> Tuple[str, List[Tuple[str, str]], str]:
    """``(subject, [(label, value)] rows, lead sentence)`` for one recipient."""
    name = f"{_label(config)} ({company.company_name or company.name})"
    since = incident.first_failure_at or incident.opened_at
    stale = incident.reason == INCIDENT_REASON_STALE and not incident.failed_runs
    rows: List[Tuple[str, str]] = [
        ("Integration", _label(config)),
        ("Company", f"{company.company_name or company.name} ({company.database_name})"),
    ]
    if kind == "recovered":
        subject = f"{name} is running again"
        rows += [
            ("Recovered at", _local(now, zone)),
            ("Failed runs during the incident", str(incident.failed_runs)),
            ("Lasted", _duration(incident.opened_at, now)),
        ]
        return subject, rows, f"{name} completed a successful run."
    if kind == "reminder":
        if stale:
            subject = f"Still failing: {name}, no successful run since {_short(since, zone)}"
        else:
            subject = (
                f"Still failing: {name}, {incident.failed_runs} failed "
                f"runs since {_short(since, zone)}"
            )
    elif stale:
        subject = f"{name} has had no successful run since {_short(since, zone)}"
    else:
        subject = f"{name} has failed {_runs_word(incident.failed_runs)} in a row"
    rows += [
        ("No successful run since" if stale else "Failing since", _local(since, zone)),
        ("Failed runs", str(incident.failed_runs)),
    ]
    if incident.last_error:
        rows.append(("Last error", incident.last_error))
    lead = (
        f"{name} has not completed a successful run."
        if stale
        else f"{name} keeps failing."
    )
    return subject, rows, lead


def _render(lead: str, rows: List[Tuple[str, str]], link: str) -> Tuple[str, str]:
    text = "\n".join([lead, "", *[f"{label}: {value}" for label, value in rows], "", f"Open runs: {link}"])
    cells = "".join(
        f'<tr><td style="padding:4px 16px 4px 0;color:#6b7280">{html.escape(label)}</td>'
        f'<td style="padding:4px 0">{html.escape(value)}</td></tr>'
        for label, value in rows
    )
    body = (
        '<div style="font-family:Arial,sans-serif;font-size:14px;color:#111827">'
        f"<p>{html.escape(lead)}</p>"
        f'<table style="border-collapse:collapse">{cells}</table>'
        f'<p style="margin-top:20px"><a href="{html.escape(link, quote=True)}" '
        'style="background:#2563eb;color:#ffffff;padding:10px 18px;border-radius:6px;'
        'text-decoration:none">Open runs</a></p></div>'
    )
    return body, text


def _notify(
    db: Session,
    config: AcEntityConfig,
    company: AcCompany,
    incident: AcTaskIncident,
    kind: str,
    now: datetime,
    alert_settings: Dict[str, Any],
) -> None:
    """Enqueue one outbox email per recipient (tenant + permission scoped) and
    stamp the notice. No recipients is fine: the banner still shows."""
    link = _runs_link(config)
    for address, tz_name in alert_recipients(db, config.tenant_id, alert_settings["alertEmails"]):
        subject, rows, lead = _compose(kind, config, company, incident, now, _zone(tz_name))
        html_body, text_body = _render(lead, rows, link)
        row = email_service.enqueue_raw(
            db, config.tenant_id, address, subject, html_body, text_body,
            template_key=f"autocount_incident_{kind}", commit=False,
        )
        # Stamped with the check's own clock (sub-second ordering of notices).
        row.created_at = now
    incident.last_notified_at = now
    if kind != "recovered":
        incident.notices_sent = (incident.notices_sent or 0) + 1
