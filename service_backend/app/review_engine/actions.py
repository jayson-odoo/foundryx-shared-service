"""Review/Approval workflow ActionDefs (plan sprint-4/06 Part B) — ``review.allocate``
and ``review.escalate``.

These are CORE workflow actions (the review engine is core). They run inside the
workflow executor, which is already failure-isolated relative to the triggering
request (a broken/slow allocate can never 500 the submit/transition — AC-06-40).
We additionally wrap the per-assignee notify so one bad contact never aborts the
whole allocation.

Trigger contract (AC-06-04/32): the canonical allocate workflow is wired to the
``entity.status_changed`` trigger on the ``form_submission`` entity with
``toStatus = review_start_status_id``. So the triggering record is the SUBMISSION
that just moved into review-start, and the flat run-context carries:

- ``trigger.record.id`` — the submission id (``status_machine.transition`` emits
  the record id; the executor maps ``recordId`` → ``trigger.record.id``);
- ``trigger.toStatus`` / ``trigger.fromStatus`` — the status edge.

The submission's ``reviewed_submission_group_id`` + ``revision_number`` derive
from the submission row (loaded tenant-scoped). The action MUST NOT transition
the submission (that would re-emit ``status_changed`` and loop).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.models.form import FormSubmission
from app.models.review import (
    ASSIGNMENT_ESCALATED,
    ASSIGNMENT_PENDING,
    ReviewAssignment,
    ReviewConfiguration,
)
from app.review_engine.resolvers import grant_actor_surface, resolve_actor_contact
from app.review_engine.service import ReviewConfigService

logger = logging.getLogger("foundryx.reviews.actions")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_submission(db: Session, tenant_id: str, ctx: Dict[str, Any]) -> Optional[FormSubmission]:
    """Resolve the triggering submission from the run-context, TENANT-SCOPED
    (never resolve a stored/contextual id unscoped — the polymorphic-target_id
    rule). The status_changed trigger seeds ``trigger.record.id`` with the
    submission id."""
    sub_id = ctx.get("trigger.record.id") or ctx.get("trigger.submissionId")
    if not sub_id:
        return None
    return (
        db.query(FormSubmission)
        .filter(FormSubmission.id == sub_id, FormSubmission.tenant_id == tenant_id)
        .first()
    )


def _config(db: Session, tenant_id: str, config_id: Optional[str]) -> Optional[ReviewConfiguration]:
    if not config_id:
        return None
    return (
        db.query(ReviewConfiguration)
        .filter(
            ReviewConfiguration.id == config_id,
            ReviewConfiguration.tenant_id == tenant_id,
        )
        .first()
    )


def _notify_assignee(
    db: Session, tenant_id: str, config: ReviewConfiguration, actor_kind: str, actor_id: str
) -> None:
    """Best-effort review-assignment notification (failure-isolated per assignee).
    Resolves the actor's (email, name) via the contact-resolver hook (core 'user',
    EMS 'profile'); a missing resolver/contact = silent skip (never tip a broken
    notify into a failed allocation)."""
    try:
        contact = resolve_actor_contact(db, tenant_id, actor_kind, actor_id)
        if contact is None:
            return
        email, name = contact
        from app.services.email_service import email_service

        subject = f"You have a new review assignment: {config.name}"
        body = (
            f"Hello {name},\n\n"
            f"You have been assigned a review for \"{config.name}\". "
            f"Please open your reviews to grade it."
        )
        email_service.enqueue_raw(
            db,
            tenant_id,
            email,
            subject,
            f"<p>{body.replace(chr(10), '<br>')}</p>",
            body,
            template_key="review.assignment",
            commit=False,
        )
    except Exception:  # noqa: BLE001 — a notify failure never breaks allocation
        logger.exception("review assignment notify failed for %s:%s", actor_kind, actor_id)


def _existing_for_revision(
    db: Session, tenant_id: str, config_id: str, group_id: str, revision: int
) -> List[ReviewAssignment]:
    return (
        db.query(ReviewAssignment)
        .filter(
            ReviewAssignment.tenant_id == tenant_id,
            ReviewAssignment.review_configuration_id == config_id,
            ReviewAssignment.reviewed_submission_group_id == group_id,
            ReviewAssignment.revision_number == revision,
        )
        .all()
    )


def _prior_reviewers(
    db: Session, tenant_id: str, config_id: str, group_id: str, revision: int
) -> List[Tuple[str, str]]:
    """The (actor_kind, actor_id) reviewers of the IMMEDIATELY PRIOR revision, in
    assignment order — preferred when re-allocating a revision (AC-06-09/32)."""
    if revision <= 1:
        return []
    rows = (
        db.query(ReviewAssignment)
        .filter(
            ReviewAssignment.tenant_id == tenant_id,
            ReviewAssignment.review_configuration_id == config_id,
            ReviewAssignment.reviewed_submission_group_id == group_id,
            ReviewAssignment.revision_number == revision - 1,
        )
        .order_by(ReviewAssignment.assigned_at.asc())
        .all()
    )
    seen: Set[Tuple[str, str]] = set()
    ordered: List[Tuple[str, str]] = []
    for r in rows:
        pair = (r.actor_kind, r.actor_id)
        if pair not in seen:
            seen.add(pair)
            ordered.append(pair)
    return ordered


def _allocate(
    db: Session,
    tenant_id: str,
    config: ReviewConfiguration,
    submission: FormSubmission,
    *,
    exclude: Optional[Set[Tuple[str, str]]] = None,
) -> int:
    """The shared allocation pass (used by allocate + escalate top-up).

    For each ``can_review`` role, resolve candidates (author-excluded, ordered,
    source-resolved) and create PENDING assignments up to ``required_review_count``
    counting EXISTING (non-withdrawn, non-escalated → still-counting) assignments.
    Idempotent: an actor already assigned for THIS (config, group, revision) is
    skipped. On ``revision_number > 1`` the prior revision's reviewers are
    preferred (re-assigned first when still in the candidate pool), then topped up
    in candidate order. ``exclude`` drops actors from the candidate pool (escalate
    excludes non-responders). Returns the count of NEW assignments."""
    group_id = submission.submission_group_id
    revision = submission.revision_number or 1
    exclude = exclude or set()

    svc = ReviewConfigService(db)

    existing = _existing_for_revision(db, tenant_id, config.id, group_id, revision)
    # Actors already holding an assignment this revision (any status) — never
    # double-assign (UNIQUE backstops, but we want a clean idempotent skip).
    already: Set[Tuple[str, str]] = {(a.actor_kind, a.actor_id) for a in existing}
    # Slots still filled = PENDING or COMPLETED assignments (an ESCALATED or
    # WITHDRAWN slot no longer counts and must be refilled).
    from app.models.review import ASSIGNMENT_COMPLETED

    counting = sum(
        1 for a in existing if a.status in (ASSIGNMENT_PENDING, ASSIGNMENT_COMPLETED)
    )

    new_count = 0
    prior_pref = _prior_reviewers(db, tenant_id, config.id, group_id, revision)

    for role in svc.repo.list_roles(tenant_id, config.id):
        if not role.can_review:
            continue
        needed = config.required_review_count - counting
        if needed <= 0:
            break

        candidates = svc.resolve_role_candidates(
            tenant_id, config, role, submission, revision
        )
        candidates = [c for c in candidates if c not in exclude]

        # AC-06-09/32: prefer the prior revision's reviewers (only those still in
        # this candidate pool), then top up via the candidate order.
        if prior_pref:
            cand_set = set(candidates)
            preferred = [c for c in prior_pref if c in cand_set]
            rest = [c for c in candidates if c not in set(preferred)]
            candidates = preferred + rest

        for pair in candidates:
            if needed <= 0:
                break
            if pair in already:
                continue
            actor_kind, actor_id = pair
            db.add(
                ReviewAssignment(
                    tenant_id=tenant_id,
                    review_configuration_id=config.id,
                    reviewed_submission_group_id=group_id,
                    revision_number=revision,
                    role_id=role.id,
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    status=ASSIGNMENT_PENDING,
                    assigned_at=_now(),
                )
            )
            already.add(pair)
            counting += 1
            needed -= 1
            new_count += 1
            _notify_assignee(db, tenant_id, config, actor_kind, actor_id)
            # AC-06-22 — a freshly-assigned PROFILE reviewer auto-acquires the
            # reviewer persona (→ my_reviews.read), so an EXPLICIT/RULE/PERSONA
            # profile reviewer can see the assignment in their portal. user-kind
            # actors use the staff surface (core perms) — never persona-granted.
            if actor_kind == "profile":
                grant_actor_surface(
                    db,
                    tenant_id,
                    profile_id=actor_id,
                    capability="review",
                    context_type=config.context_type,
                    context_id=config.context_id,
                )

    if new_count:
        db.flush()
    return new_count


# ── ActionDef executors ──────────────────────────────────────────────────────


def review_allocate(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    """``review.allocate`` executor (AC-06-04/32). Resolves the triggering
    submission + config from the run-context and allocates reviewers. MUST NOT
    transition the submission (no loop). Returns ``{assigned: n}``."""
    cfg = _config(db, tenant_id, config.get("reviewConfigurationId"))
    if cfg is None:
        return {"assigned": 0, "reason": "config-not-found"}
    submission = _load_submission(db, tenant_id, ctx)
    if submission is None:
        return {"assigned": 0, "reason": "submission-not-found"}
    n = _allocate(db, tenant_id, cfg, submission)
    return {"assigned": n}


def review_escalate(
    db: Session, tenant_id: str, config: Dict[str, Any], ctx: Dict[str, Any]
) -> Dict[str, Any]:
    """``review.escalate`` executor (AC-06-33). Marks PENDING assignments past the
    config's ``window_end`` as ESCALATED, then re-runs allocation EXCLUDING those
    non-responders to top up. Idempotent + failure-isolated.

    The submission group is resolved from the run-context the same way as allocate
    (the escalate workflow is typically a schedule.cron that sweeps; here we
    support the per-submission trigger path — a scheduled sweep variant would loop
    over open groups, slice-2 surface)."""
    cfg = _config(db, tenant_id, config.get("reviewConfigurationId"))
    if cfg is None:
        return {"escalated": 0, "assigned": 0, "reason": "config-not-found"}
    submission = _load_submission(db, tenant_id, ctx)
    if submission is None:
        return {"escalated": 0, "assigned": 0, "reason": "submission-not-found"}

    group_id = submission.submission_group_id
    revision = submission.revision_number or 1
    window_end = cfg.window_end
    if window_end is None:
        # No deadline configured → nothing escalates.
        return {"escalated": 0, "assigned": 0}

    now = _now()
    if now < window_end:
        return {"escalated": 0, "assigned": 0}

    pending = (
        db.query(ReviewAssignment)
        .filter(
            ReviewAssignment.tenant_id == tenant_id,
            ReviewAssignment.review_configuration_id == cfg.id,
            ReviewAssignment.reviewed_submission_group_id == group_id,
            ReviewAssignment.revision_number == revision,
            ReviewAssignment.status == ASSIGNMENT_PENDING,
        )
        .all()
    )
    non_responders: Set[Tuple[str, str]] = set()
    for a in pending:
        a.status = ASSIGNMENT_ESCALATED
        non_responders.add((a.actor_kind, a.actor_id))
    if non_responders:
        db.flush()

    # Re-allocate to top up, excluding the non-responders we just escalated.
    assigned = _allocate(db, tenant_id, cfg, submission, exclude=non_responders)
    return {"escalated": len(non_responders), "assigned": assigned}


def register_review_actions() -> None:
    """Register the review ActionDefs into the workflow registry. Called at core
    boot (idempotent — register_action overwrites by key)."""
    from app.workflow_engine.registry import ActionDef, NodeField, NodeOutput, register_action

    register_action(
        ActionDef(
            key="review.allocate",
            label="Allocate reviewers",
            description="Assign reviewers to the triggering submission per a review configuration.",
            icon="UsersRound",
            category="Actions",
            executor=review_allocate,
            fields=[
                NodeField(
                    key="reviewConfigurationId",
                    label="Review configuration",
                    type="select",
                    required=True,
                ),
            ],
            outputs=[NodeOutput("assigned", "Reviewers assigned")],
        )
    )
    register_action(
        ActionDef(
            key="review.escalate",
            label="Escalate stale reviews",
            description="Escalate overdue pending reviews and re-allocate to other reviewers.",
            icon="AlarmClock",
            category="Actions",
            executor=review_escalate,
            fields=[
                NodeField(
                    key="reviewConfigurationId",
                    label="Review configuration",
                    type="select",
                    required=True,
                ),
            ],
            outputs=[
                NodeOutput("escalated", "Reviews escalated"),
                NodeOutput("assigned", "Replacements assigned"),
            ],
        )
    )
