"""Parked-run wait rows (plan sprint-4/31 S4, D-A5-6/D-A5-9, §5.4).

Core owns the park (`workflow_runs.status='waiting'` + `resume_state_json`);
this module owns the INDEX from a contact - or from a bare deadline - back to
that parked run, plus the answer spec and retry counters. Core never imports
this file: the module registers `delete_for_run` as a core parked-run cleanup
and calls `executor.resume_run(...)` itself.

Every query here is tenant-scoped. `run_id`/`workflow_id` are core `public` row
ids stored in a module table (BL-030, plain columns) - resolved tenant-scoped at
use time, never with a bare `get_by_id` (the polymorphic stored-id house rule).
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Contact, WorkflowWait

logger = logging.getLogger(__name__)

# Module caps (§5.3 "Caps") - not tenant-configurable in v1.
MAX_WAIT_DAYS = 30
MAX_RETRY_LIMIT = 3
MAX_CHOICES = 10
SWEEP_BATCH = 200

KIND_QUESTION = "question"
KIND_DELAY = "delay"

ANSWER_TYPES = ("text", "choice", "number", "email", "phone")

# Ports the Ask node branches on (mirrors the catalog entry's `ports`).
PORT_ANSWER = "answer"
PORT_TIMEOUT = "timeout"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


class WaitError(Exception):
    """A wait could not be opened (surfaced by the action as a node failure)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def duration_to_delta(value: Any, unit: Any) -> timedelta:
    """`{value, unit}` -> a bounded timedelta. Raises `WaitError` on anything a
    node could not actually wait for (AC-WFP-43/50)."""
    try:
        amount = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise WaitError("Duration must be a number.") from exc
    if amount <= 0:
        raise WaitError("Duration must be greater than zero.")
    unit_key = str(unit or "minutes").strip().lower()
    if unit_key == "minutes":
        delta = timedelta(minutes=amount)
    elif unit_key == "hours":
        delta = timedelta(hours=amount)
    elif unit_key == "days":
        delta = timedelta(days=amount)
    else:
        raise WaitError("Duration unit must be minutes, hours or days.")
    if delta > timedelta(days=MAX_WAIT_DAYS):
        raise WaitError(f"Duration cannot exceed {MAX_WAIT_DAYS} days.")
    return delta


def find_open_question(
    db: Session, tenant_id: str, contact_id: str, workspace_id: Optional[str] = None
) -> Optional[WorkflowWait]:
    """Tenant + contact scoped lookup. ``workspace_id`` is optional
    defence-in-depth (plan 31 review nit) - contact ids are already
    workspace-unique so it changes nothing today, but a caller that has the
    workspace on hand should pass it."""
    query = db.query(WorkflowWait).filter(
        WorkflowWait.tenant_id == tenant_id,
        WorkflowWait.contact_id == contact_id,
        WorkflowWait.kind == KIND_QUESTION,
    )
    if workspace_id is not None:
        query = query.filter(WorkflowWait.workspace_id == workspace_id)
    return query.first()


def open_wait(
    db: Session,
    *,
    tenant_id: str,
    run_id: str,
    workflow_id: str,
    node_id: str,
    kind: str,
    deadline_at: datetime,
    contact: Optional[Contact] = None,
    answer_spec: Optional[Dict[str, Any]] = None,
    is_test: bool = False,
) -> WorkflowWait:
    """Insert one wait row. A second QUESTION for a contact that already has an
    open one is refused (D-A5-9, AC-WFP-44) - checked, then backed by the
    unique constraint for the concurrent case."""
    if kind == KIND_QUESTION:
        if contact is None:
            raise WaitError("A question wait needs a contact.")
        if find_open_question(db, tenant_id, contact.id, contact.workspace_id) is not None:
            raise WaitError("This contact already has an open question.")
    row = WorkflowWait(
        tenant_id=tenant_id,
        workspace_id=contact.workspace_id if (contact is not None and kind == KIND_QUESTION) else None,
        contact_id=contact.id if (contact is not None and kind == KIND_QUESTION) else None,
        run_id=run_id,
        workflow_id=workflow_id,
        node_id=node_id,
        kind=kind,
        answer_spec_json=answer_spec,
        retry_count=0,
        deadline_at=deadline_at,
        is_test=is_test,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as exc:
        raise WaitError("This contact already has an open question.") from exc
    return row


# ── answer validation (AC-WFP-46/47/48) ─────────────────────────────────────


def _choice_labels(spec: Dict[str, Any]) -> List[str]:
    return [str(c) for c in (spec.get("choices") or []) if str(c).strip()]


def validate_answer(spec: Dict[str, Any], text: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
    """Normalize an inbound message against the wait's answer spec.

    Returns ``(ok, output)`` where ``output`` carries ``answer`` (the normalized
    value), ``answerRaw`` (the message text) and, for ``choice``, ``answerKey``
    (the matched choice's 1-based position as a string)."""
    raw = (text or "").strip()
    answer_type = str(spec.get("answerType") or "text").lower()
    if not raw:
        return False, {}
    if answer_type == "choice":
        labels = _choice_labels(spec)
        folded = raw.casefold()
        for index, label in enumerate(labels, start=1):
            if folded == label.strip().casefold() or raw == str(index):
                return True, {
                    "answer": label,
                    "answerRaw": raw,
                    "answerKey": str(index),
                }
        return False, {}
    if answer_type == "number":
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            return False, {}
        normalized: Any = int(value) if value.is_integer() else value
        return True, {"answer": normalized, "answerRaw": raw}
    if answer_type == "email":
        if _EMAIL_RE.match(raw) is None:
            return False, {}
        return True, {"answer": raw, "answerRaw": raw}
    if answer_type == "phone":
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 6:
            return False, {}
        return True, {"answer": f"+{digits}" if raw.strip().startswith("+") else digits,
                      "answerRaw": raw}
    # text - any non-empty message
    return True, {"answer": raw, "answerRaw": raw}


def question_text(spec: Dict[str, Any]) -> str:
    """The message actually sent for an Ask node - the author's text plus, for
    `choice`, the numbered option list (AC-WFP-48: "the sent message lists the
    choices"); a contact can answer with the label or its number."""
    base = str(spec.get("question") or "").strip()
    if str(spec.get("answerType") or "") != "choice":
        return base
    labels = _choice_labels(spec)
    if not labels:
        return base
    listing = "\n".join(f"{i}. {label}" for i, label in enumerate(labels, start=1))
    return f"{base}\n{listing}".strip()


# ── resume paths ────────────────────────────────────────────────────────────


def _snapshot(wait: WorkflowWait) -> Dict[str, Any]:
    """Plain-value copy of everything a claim needs AFTER the row is gone.

    A claim COMMITS, which expires the ORM instance; touching an attribute
    afterwards re-SELECTs a deleted row and raises ``ObjectDeletedError``. Read
    once, up front, and never touch the instance again."""
    return {
        "id": wait.id,
        "tenant_id": wait.tenant_id,
        "contact_id": wait.contact_id,
        "run_id": wait.run_id,
        "node_id": wait.node_id,
        "kind": wait.kind,
        "is_test": bool(wait.is_test),
        "retry_count": int(wait.retry_count or 0),
        "spec": dict(wait.answer_spec_json or {}),
    }


def _claim_delete(db: Session, snap: Dict[str, Any]) -> bool:
    """Atomically claim a wait by deleting its row. Only the caller whose
    DELETE matched a row may resume - two concurrent inbound messages (or a
    sweep racing a reply) can never both resume one run (AC-WFP-49)."""
    deleted = (
        db.query(WorkflowWait)
        .filter(WorkflowWait.id == snap["id"], WorkflowWait.tenant_id == snap["tenant_id"])
        .delete(synchronize_session=False)
    )
    db.commit()
    return bool(deleted)


def _claim_retry(db: Session, snap: Dict[str, Any], seen: int) -> bool:
    """Atomically claim ONE re-ask (guarded on the retry counter we read).

    Deliberately asymmetric vs ``_claim_delete`` on a lost race (plan 31
    review nit): losing HERE means the wait row is still OPEN - another
    delivery already advanced the retry counter for this same event, so the
    caller reports the message consumed (``return True``) rather than
    re-sending a duplicate retry. ``_claim_delete`` losing its race means the
    wait row is GONE - already resolved by someone else - so that caller
    reports NOT consumed (``return False``) and lets the message flow on as
    ordinary inbound content instead of being silently swallowed."""
    updated = (
        db.query(WorkflowWait)
        .filter(
            WorkflowWait.id == snap["id"],
            WorkflowWait.tenant_id == snap["tenant_id"],
            WorkflowWait.retry_count == seen,
        )
        .update({WorkflowWait.retry_count: seen + 1}, synchronize_session=False)
    )
    db.commit()
    return bool(updated)


def _send(db: Session, snap: Dict[str, Any], body: str) -> None:
    """Send a plain text message on the wait's own channel. Best-effort: a send
    failure must never strand the resume decision that is already committed."""
    if not body.strip() or snap["contact_id"] is None:
        return
    from ..schemas import SendMessageRequest
    from .message_service import MessageService

    spec = snap["spec"]
    try:
        MessageService(db).send_message(
            snap["contact_id"],
            snap["tenant_id"],
            actor_user_id=None,
            payload=SendMessageRequest(messageType="TEXT", body=body),
            channel_id_override=spec.get("channelId") or None,
            sandbox_only=bool(spec.get("sandboxOnly")) or snap["is_test"],
        )
    except Exception:  # noqa: BLE001 - a failed re-ask never breaks the pipeline
        logger.exception("workflow wait %s: re-ask send failed", snap["id"])


def _resume(db: Session, snap: Dict[str, Any], *, branch: Optional[str], output: Dict[str, Any]) -> None:
    from app.workflow_engine.executor import resume_run

    resume_run(
        db, snap["run_id"], snap["tenant_id"],
        node_id=snap["node_id"], output=output, branch=branch,
    )


def resume_from_inbound(
    db: Session, *, contact: Contact, tenant_id: str, text: Optional[str]
) -> bool:
    """The inbound hook (AC-WFP-45/46/47). Returns True when the message was
    CONSUMED by an open question - the caller then skips its
    `omnichannel.message_received` dispatch entirely (D-A5-8 / F2).

    A message that is not an answer (no open wait) returns False and flows on
    unchanged."""
    wait = find_open_question(db, tenant_id, contact.id, contact.workspace_id)
    if wait is None:
        return False
    snap = _snapshot(wait)
    spec = snap["spec"]
    ok, output = validate_answer(spec, text)
    if ok:
        if not _claim_delete(db, snap):
            return False  # lost the race - another worker resumed it
        _resume(db, snap, branch=PORT_ANSWER, output={**output, "timedOut": False, "reason": ""})
        return True

    retry_limit = int(spec.get("retryLimit") or 0)
    seen = snap["retry_count"]
    if seen < retry_limit:
        if not _claim_retry(db, snap, seen):
            return True  # someone else already handled this message's slot
        _send(db, snap, str(spec.get("retryMessage") or "").strip() or question_text(spec))
        return True

    # Retry cap reached - close the wait and take the timeout port.
    if not _claim_delete(db, snap):
        return False
    _resume(
        db,
        snap,
        branch=PORT_TIMEOUT,
        output={
            "answer": None,
            "answerRaw": (text or "").strip(),
            "answerKey": None,
            "timedOut": True,
            "reason": "invalid",
        },
    )
    return True


def sweep_due_waits(
    db: Session, *, now: Optional[datetime] = None, limit: int = SWEEP_BATCH
) -> Dict[str, int]:
    """Beat sweep (AC-WFP-49/50, D-A5-10). Idempotent, bounded, tenant-scoped
    per row: a question times out on its `timeout` port, a plain wait resumes on
    its single out port. A row whose run is gone (or is no longer parked) is
    discarded with a log - never resumed twice."""
    current = now or _now()
    rows = (
        db.query(WorkflowWait)
        .filter(WorkflowWait.deadline_at <= current)
        .order_by(WorkflowWait.deadline_at.asc())
        .limit(max(1, min(limit, SWEEP_BATCH)))
        .all()
    )
    # Snapshot EVERY row up front (plan 31 review S2), before any claim commits.
    # A claim commit expires the whole session's ORM instances, so touching a
    # later row in `rows` after an earlier claim would re-SELECT it - and if a
    # concurrent inbound resume deleted that row in the meantime, the re-SELECT
    # raises `ObjectDeletedError` OUTSIDE this function's own try/except,
    # aborting the whole tick and losing the counts of work already done.
    # Snapshotting here means every row's plain-value copy is taken before any
    # commit can expire anything.
    snaps = [_snapshot(wait) for wait in rows]
    resumed = 0
    discarded = 0
    for snap in snaps:
        kind = snap["kind"]
        run_id = snap["run_id"]
        node_id = snap["node_id"]
        tenant_id = snap["tenant_id"]
        if not _claim_delete(db, snap):
            continue
        try:
            from app.models.workflow import RUN_WAITING, WorkflowRun
            from app.workflow_engine.executor import resume_run

            run = (
                db.query(WorkflowRun)
                .filter(
                    WorkflowRun.id == run_id,
                    WorkflowRun.tenant_id == tenant_id,
                    WorkflowRun.status == RUN_WAITING,
                )
                .first()
            )
            if run is None:
                logger.info(
                    "workflow wait for run %s discarded: run missing or no longer parked", run_id
                )
                discarded += 1
                continue
            if kind == KIND_DELAY:
                resume_run(
                    db, run_id, tenant_id, node_id=node_id,
                    output={"resumedAt": current.isoformat().replace("+00:00", "Z")},
                    branch=None,
                )
            else:
                resume_run(
                    db, run_id, tenant_id, node_id=node_id,
                    output={
                        "answer": None,
                        "answerRaw": "",
                        "answerKey": None,
                        "timedOut": True,
                        "reason": "timeout",
                    },
                    branch=PORT_TIMEOUT,
                )
            resumed += 1
        except Exception:  # noqa: BLE001 - one bad row never kills the sweep
            logger.exception("workflow wait sweep failed for run %s", run_id)
            db.rollback()
    return {"resumed": resumed, "discarded": discarded}


# ── lifecycle cleanup ───────────────────────────────────────────────────────


def delete_for_run(db: Session, run: Any) -> None:
    """Core parked-run cleanup hook (registered via `register_wait_cleanup`) -
    cancelling a `waiting` run drops its wait row (AC-WFP-52)."""
    db.query(WorkflowWait).filter(
        WorkflowWait.tenant_id == run.tenant_id, WorkflowWait.run_id == run.id
    ).delete(synchronize_session=False)


def delete_for_workflow(db: Session, tenant_id: str, workflow_id: str) -> None:
    """Every wait of a permanently-deleted workflow (its runs cascade away with
    it, so the index rows must go too - AC-WFP-52)."""
    db.query(WorkflowWait).filter(
        WorkflowWait.tenant_id == tenant_id, WorkflowWait.workflow_id == workflow_id
    ).delete(synchronize_session=False)


def cancel_parked_runs_for_tenant(db: Session, tenant_id: str) -> int:
    """Uninstall path (AC-WFP-54): cancel every run this tenant has parked on an
    omnichannel wait, through the CORE seam (a module never writes a core row
    behind the engine's back). The wait rows themselves are wiped by
    `uninstall_tenant`'s generic per-table tenant sweep."""
    from app.workflow_engine.parking import cancel_parked_run

    cancelled = 0
    for wait in db.query(WorkflowWait).filter(WorkflowWait.tenant_id == tenant_id).all():
        run = cancel_parked_run(
            db, wait.run_id, tenant_id, reason="The omnichannel service was uninstalled."
        )
        if run is not None:
            cancelled += 1
    return cancelled
