"""Review-surface read/write logic (plan sprint-4/06 slice 2) — the
actor-agnostic engine behind BOTH worlds:

- the PORTAL surfaces (EMS ``PortalReviewService`` for ``profile``-kind actors),
- the STAFF surfaces (``app/api/v1/reviews.py`` for ``user``-kind actors).

CORE — never imports the EMS module. Every method takes an explicit
``(actor_kind, actor_id)`` and is fully tenant-scoped; identity routing
(AC-06-10/47) is the CALLER's concern — a portal router only ever passes
``actor_kind='profile'``, a staff router ``'user'``, and a surface method 404s an
assignment/decision whose ``actor_kind`` doesn't match (so a user-kind assignment
is invisible on the portal and vice versa).

Router → THIS → ReviewRepository / FormService. Service-Repository layered; the
routers do NO DB/SQL.

The four surface concerns:

- **My Submissions** (AC-06-43/08/52) — the AUTHOR's view of their submission
  groups: lifecycle status + decision + feedback ONLY (``author_visible_group``;
  raw reviews/scores are NEVER in the payload).
- **My Reviews** (AC-06-44/05/48) — the reviewer's assignments + the two-pane
  grade payload (submission at its pinned version ‖ the review form) with
  **reviewer isolation**: only THIS assignment's own review draft, never another
  reviewer's content.
- **Decisions** (AC-06-45/07) — the decider's groups with the live partial
  average + a ready flag + the individual completed reviews (the decider MAY see
  them — distinct from reviewer isolation) + first-wins decide.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.form import FORM_SUBMISSION_ENTITY, Form, FormSubmission
from app.models.review import (
    ASSIGNMENT_COMPLETED,
    ReviewAssignment,
    ReviewConfiguration,
)
from app.models.status import Status
from app.repositories.review_repository import ReviewRepository
from app.review_engine.service import ReviewConfigService, ReviewValidationError


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReviewSurfaceError(Exception):
    pass


class SurfaceNotFound(ReviewSurfaceError):
    """No such assignment/group for THIS actor/kind/tenant → 404."""


class SurfaceForbidden(ReviewSurfaceError):
    """The actor lacks the capability (may_submit / may_decide) → 403."""


class SurfaceClosed(ReviewSurfaceError):
    """The submission window is closed → 409."""


class ReviewSurfaceService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ReviewRepository(db)
        self.configs = ReviewConfigService(db)

    # ---- tenant-scoped submission/form helpers (polymorphic-target_id rule) ----

    def _current_submission(self, tenant_id: str, group_id: str) -> Optional[FormSubmission]:
        return (
            self.db.query(FormSubmission)
            .filter(
                FormSubmission.tenant_id == tenant_id,
                FormSubmission.submission_group_id == group_id,
                FormSubmission.is_current.is_(True),
            )
            .first()
        )

    def _submission_by_id(self, tenant_id: str, submission_id: str) -> Optional[FormSubmission]:
        return (
            self.db.query(FormSubmission)
            .filter(
                FormSubmission.tenant_id == tenant_id,
                FormSubmission.id == submission_id,
            )
            .first()
        )

    def _form_name(self, tenant_id: str, form_id: str) -> str:
        form = (
            self.db.query(Form.name)
            .filter(Form.tenant_id == tenant_id, Form.id == form_id)
            .first()
        )
        return form[0] if form else ""

    def _context_label(self, config: ReviewConfiguration) -> Optional[str]:
        """The human label of the config's bound event/context (AC-06-25) — the
        event name for a ``project`` context, resolved tenant-scoped through the
        injectable context-label resolver (keeps core EMS-free). None when the
        config is context-less or the id is unresolvable; the surface then has no
        per-row event label."""
        from app.review_engine.resolvers import resolve_context_label

        return resolve_context_label(
            self.db, config.tenant_id, config.context_type, config.context_id
        )

    def _status(self, tenant_id: str, form_id: str, status_id: str) -> Optional[Status]:
        return (
            self.db.query(Status)
            .filter(
                Status.entity_type == FORM_SUBMISSION_ENTITY,
                Status.tenant_id == tenant_id,
                Status.scope_id == form_id,
                Status.id == status_id,
            )
            .first()
        )

    def _submission_title(self, submission: FormSubmission) -> str:
        """A friendly title for a submission — the first textual answer, else the
        form name. Never exposes review content (this is author/queue metadata)."""
        answers = submission.answers_json or {}
        for value in answers.values():
            if isinstance(value, str) and value.strip():
                return value.strip()[:120]
        return self._form_name(submission.tenant_id, submission.form_id) or "Submission"

    def _window_open(self, config: ReviewConfiguration) -> bool:
        now = _now()
        if config.window_start is not None and now < config.window_start:
            return False
        if config.window_end is not None and now > config.window_end:
            return False
        return True

    # ---- Cluster-G referenceability (AC-06-53, minimal) ----

    def resolve_accepted_submission(
        self, tenant_id: str, group_id: str
    ) -> Optional[Dict[str, Any]]:
        """Resolve an ACCEPTED submission group to its CURRENT revision (AC-06-53 —
        agenda binding by ``submission_group_id`` lives in Cluster G; this is the
        minimal tenant-scoped lookup). Returns the current revision's id + author
        actor + status only when the group is at the config's ``accepted_status_id``;
        None otherwise (or for a foreign/cross-tenant group)."""
        submission = self._current_submission(tenant_id, group_id)
        if submission is None:
            return None
        config = self._config_for_form(tenant_id, submission.form_id)
        if config is None or config.accepted_status_id is None:
            return None
        if submission.status_id != config.accepted_status_id:
            return None
        author = self.configs.submission_author_actor(submission)
        return {
            "group_id": group_id,
            "submission_id": submission.id,
            "revision_number": submission.revision_number or 1,
            "form_id": submission.form_id,
            "author_kind": author[0] if author else None,
            "author_id": author[1] if author else None,
            "title": self._submission_title(submission),
        }

    # ---- author visibility (AC-06-08/42) ----

    def author_visible_group(
        self,
        tenant_id: str,
        config: ReviewConfiguration,
        submission: FormSubmission,
    ) -> Dict[str, Any]:
        """The AUTHOR's view of a submission group: lifecycle status + (if decided)
        the decision + feedback ONLY. Raw reviews/scores are NEVER included — this
        is the single function My Submissions renders, so the contract can't leak
        (AC-06-08). ``submission`` is the group's CURRENT revision."""
        status = self._status(tenant_id, submission.form_id, submission.status_id)
        revision = submission.revision_number or 1
        decision = self.repo.get_decision(
            tenant_id, config.id, submission.submission_group_id, revision
        )
        revisable = bool(
            config.revisions_status_id
            and submission.status_id == config.revisions_status_id
            and self._window_open(config)
        )
        return {
            "group_id": submission.submission_group_id,
            "submission_id": submission.id,
            "review_configuration_id": config.id,
            "review_configuration_name": config.name,
            "context_id": config.context_id,
            "context_label": self._context_label(config),
            "form_id": submission.form_id,
            "title": self._submission_title(submission),
            "revision_number": revision,
            "status_id": submission.status_id,
            "status_label": status.label if status else "",
            "status_color": status.color if status else "gray",
            "decision": decision.decision if decision else None,
            "feedback_text": decision.feedback_text if decision else None,
            "decided_at": decision.decided_at if decision else None,
            "can_revise": revisable,
            "submitted_at": submission.submitted_at,
            "created_at": submission.created_at,
        }

    @staticmethod
    def _config_in_context(config: ReviewConfiguration, context_id: Optional[str]) -> bool:
        """True when ``config`` belongs to the active event/context filter
        (AC-06-25). ``context_id=None`` = unfiltered (every config matches);
        otherwise only configs whose own ``context_id`` equals it. A config
        without a ``context_id`` (a generic, context-less process) is hidden while
        a specific event is selected — it isn't part of that event's surface."""
        if context_id is None:
            return True
        return config.context_id == context_id

    def my_submissions(
        self,
        tenant_id: str,
        actor_kind: str,
        actor_id: str,
        context_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Every submission GROUP authored by this actor (AC-06-43/52). One entry
        per group (each its own group — multiple per author allowed), showing the
        CURRENT revision's author-visible view. Never raw reviews/scores.
        ``context_id`` (AC-06-25) narrows to a single event's configs; None = all
        contexts (the per-row config carries its event so the surface can label
        the context per row when unfiltered)."""
        rows = (
            self.db.query(FormSubmission)
            .filter(
                FormSubmission.tenant_id == tenant_id,
                FormSubmission.is_current.is_(True),
                self._author_clause(actor_kind, actor_id),
            )
            .order_by(FormSubmission.created_at.desc())
            .all()
        )
        out: List[Dict[str, Any]] = []
        for sub in rows:
            config = self._config_for_form(tenant_id, sub.form_id)
            if config is None:
                continue  # a submission outside any review process → not a review surface item
            if not self._config_in_context(config, context_id):
                continue
            out.append(self.author_visible_group(tenant_id, config, sub))
        return out

    @staticmethod
    def _author_clause(actor_kind: str, actor_id: str):
        if actor_kind == "profile":
            return (FormSubmission.subject_type == "profile") & (
                FormSubmission.subject_id == actor_id
            )
        return FormSubmission.user_id == actor_id

    def _config_for_form(self, tenant_id: str, form_id: str) -> Optional[ReviewConfiguration]:
        """The review configuration whose SUBMISSION form is ``form_id`` (the
        first active one — v1 is one config per submission form)."""
        return (
            self.db.query(ReviewConfiguration)
            .filter(
                ReviewConfiguration.tenant_id == tenant_id,
                ReviewConfiguration.form_id == form_id,
            )
            .order_by(ReviewConfiguration.created_at.asc())
            .first()
        )

    # ---- My Reviews (AC-06-44/05/48) ----

    def my_reviews(
        self,
        tenant_id: str,
        actor_kind: str,
        actor_id: str,
        context_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """The actor's review assignments (PENDING/COMPLETED), newest first. Only
        assignments of THIS actor-kind are returned — identity routing
        (AC-06-10/47): a user-kind actor never sees profile-kind assignments.
        ``context_id`` (AC-06-25) narrows to a single event's configs; None = all
        contexts (each row carries its config's event for per-row labelling)."""
        rows = self.repo.list_assignments_for_actor(tenant_id, actor_kind, actor_id)
        out: List[Dict[str, Any]] = []
        for a in rows:
            config = self.configs.repo.get_config(tenant_id, a.review_configuration_id)
            if config is None:
                continue
            if not self._config_in_context(config, context_id):
                continue
            submission = self._current_submission(tenant_id, a.reviewed_submission_group_id)
            out.append(
                {
                    "assignment_id": a.id,
                    "review_configuration_id": config.id,
                    "review_configuration_name": config.name,
                    "context_id": config.context_id,
                    "context_label": self._context_label(config),
                    "group_id": a.reviewed_submission_group_id,
                    "revision_number": a.revision_number,
                    "status": a.status,
                    "due_at": config.window_end,
                    "assigned_at": a.assigned_at,
                    "completed_at": a.completed_at,
                    "title": self._submission_title(submission) if submission else "",
                }
            )
        return out

    def _owned_assignment(
        self, tenant_id: str, assignment_id: str, actor_kind: str, actor_id: str
    ) -> ReviewAssignment:
        """The assignment, asserting it belongs to THIS actor (tenant + kind + id).
        Anything else 404s — reviewer isolation + identity routing (AC-06-47/48)."""
        a = self.repo.get_assignment(tenant_id, assignment_id)
        if a is None or a.actor_kind != actor_kind or a.actor_id != actor_id:
            raise SurfaceNotFound()
        return a

    def review_two_pane(
        self, tenant_id: str, assignment_id: str, actor_kind: str, actor_id: str
    ) -> Dict[str, Any]:
        """The two-pane grade payload (AC-06-05/48): the read-only SUBMISSION at
        the assignment-revision's pinned version ‖ the review-form fill view, plus
        THIS reviewer's in-progress review draft answers (if any). Reviewer
        isolation: only the assignment's own ``review_submission_id`` draft —
        NEVER another reviewer's review."""
        from app.services.form_service import FormService

        a = self._owned_assignment(tenant_id, assignment_id, actor_kind, actor_id)
        config = self.configs.repo.get_config(tenant_id, a.review_configuration_id)
        if config is None:
            raise SurfaceNotFound()

        # The reviewed submission = the group's revision the assignment targets.
        submission = (
            self.db.query(FormSubmission)
            .filter(
                FormSubmission.tenant_id == tenant_id,
                FormSubmission.submission_group_id == a.reviewed_submission_group_id,
                FormSubmission.revision_number == a.revision_number,
            )
            .first()
        )
        if submission is None:
            raise SurfaceNotFound()

        form_service = FormService(self.db)
        # Read-only submission at its pinned version (the engine resolves
        # version-pinned answers tenant-scoped). Reuse a synthetic-actor read —
        # get_submission only uses the user for fireable-edge buttons, which this
        # read-only view ignores.
        version = form_service.get_version(tenant_id, submission.form_id, submission.version_id)
        submission_view = {
            "id": submission.id,
            "form_id": submission.form_id,
            "version_id": submission.version_id,
            "answers": submission.answers_json or {},
            "definition": version.definition_json if version else None,
            "revision_number": submission.revision_number,
        }

        # The review form fill view (the rubric).
        review_form_view = form_service.fill(tenant_id, config.review_form_id)

        # This reviewer's own review draft (if a Draft review submission exists).
        review_draft = None
        if a.review_submission_id:
            draft = self._submission_by_id(tenant_id, a.review_submission_id)
            if draft is not None:
                review_draft = {
                    "submission_id": draft.id,
                    "answers": draft.answers_json or {},
                    "status": a.status,
                }
        return {
            "assignment_id": a.id,
            "status": a.status,
            "review_configuration_id": config.id,
            "review_configuration_name": config.name,
            "submission": submission_view,
            "review_form": review_form_view,
            "review_draft": review_draft,
        }

    def save_review_draft(
        self,
        tenant_id: str,
        assignment_id: str,
        actor_kind: str,
        actor_id: str,
        answers: Dict[str, Any],
        author_user=None,
    ) -> Dict[str, Any]:
        """Save-draft the review answers (AC-06-44). Creates the review-form
        submission in Draft on first save (linked as the assignment's
        ``review_submission_id`` while still Draft); subsequent saves UPDATE the
        same Draft. Idempotent resume. The review IS a form_submission of the
        review form — created via the form engine so it pins the review form's
        current version + materializes on the scoped graph. ``author_user`` is the
        staff User when a user-kind actor saves (so file uploads etc. attribute
        correctly); profile-kind passes None + the subject author ref."""
        a = self._owned_assignment(tenant_id, assignment_id, actor_kind, actor_id)
        if a.status == ASSIGNMENT_COMPLETED:
            raise SurfaceClosed("This review is already submitted.")
        config = self.configs.repo.get_config(tenant_id, a.review_configuration_id)
        if config is None:
            raise SurfaceNotFound()

        if a.review_submission_id:
            draft = self._submission_by_id(tenant_id, a.review_submission_id)
            if draft is not None:
                import json

                draft.answers_json = json.loads(json.dumps(answers))
                self.db.commit()
                self.db.refresh(draft)
                return {"submission_id": draft.id, "answers": draft.answers_json or {}}

        # First save → create the review form submission at Draft (no transition).
        draft = self._create_review_draft(tenant_id, config, actor_kind, actor_id, answers)
        a.review_submission_id = draft.id
        self.db.commit()
        self.db.refresh(draft)
        return {"submission_id": draft.id, "answers": draft.answers_json or {}}

    def _create_review_draft(
        self,
        tenant_id: str,
        config: ReviewConfiguration,
        actor_kind: str,
        actor_id: str,
        answers: Dict[str, Any],
    ) -> FormSubmission:
        """Create a review-form submission at the review form's INITIAL (Draft)
        scoped status (no Submitted transition yet). The reviewer is captured as
        the author actor (user_id for staff, subject for profile) so the review's
        own author ref is faithful."""
        import json
        import uuid

        from app.status_engine.scoped import initial_scope_status

        review_form = (
            self.db.query(Form)
            .filter(Form.tenant_id == tenant_id, Form.id == config.review_form_id)
            .first()
        )
        if review_form is None or not review_form.current_version_id:
            raise SurfaceNotFound()
        initial = initial_scope_status(
            self.db, FORM_SUBMISSION_ENTITY, tenant_id, config.review_form_id
        )
        if initial is None:
            raise SurfaceNotFound()
        sub_id = str(uuid.uuid4())
        draft = FormSubmission(
            id=sub_id,
            tenant_id=tenant_id,
            form_id=config.review_form_id,
            submission_group_id=sub_id,
            revision_number=1,
            is_current=True,
            version_id=review_form.current_version_id,
            status_id=initial.id,
            user_id=actor_id if actor_kind == "user" else None,
            subject_type="profile" if actor_kind == "profile" else None,
            subject_id=actor_id if actor_kind == "profile" else None,
            answers_json=json.loads(json.dumps(answers)),
            submitted_at=None,
        )
        self.db.add(draft)
        self.db.flush()
        return draft

    def submit_review(
        self,
        tenant_id: str,
        assignment_id: str,
        actor_kind: str,
        actor_id: str,
        answers: Optional[Dict[str, Any]],
        author_user=None,
    ) -> Dict[str, Any]:
        """Submit the review (AC-06-05): persist the (final) answers, drive the
        review submission Draft→Submitted through the ONE status executor, then set
        ``review_assignment.review_submission_id`` + status=COMPLETED + completed_at.
        After this the live average updates (AC-06-06). Validates the review-form
        answers via the form-engine submit pipeline (never trust the client)."""
        from app.services.form_service import (
            FormClosed,
            FormService,
            FormSubmitInvalid,
        )

        a = self._owned_assignment(tenant_id, assignment_id, actor_kind, actor_id)
        if a.status == ASSIGNMENT_COMPLETED:
            raise SurfaceClosed("This review is already submitted.")
        config = self.configs.repo.get_config(tenant_id, a.review_configuration_id)
        if config is None:
            raise SurfaceNotFound()

        # Resolve / create the review draft, then write the final answers into it.
        if answers is not None:
            saved = self.save_review_draft(
                tenant_id, assignment_id, actor_kind, actor_id, answers, author_user
            )
            review_submission_id = saved["submission_id"]
        elif a.review_submission_id:
            review_submission_id = a.review_submission_id
        else:
            raise ReviewValidationError("There is no review draft to submit.")
        self.db.refresh(a)

        draft = self._submission_by_id(tenant_id, review_submission_id)
        if draft is None:
            raise SurfaceNotFound()

        # Drive Draft→Submitted on the review submission through the form engine's
        # shared fire helper (validates against the pinned version + fires the
        # form.submitted event). We reuse the public submit path: re-submit the
        # SAME row's answers via resubmit pipeline semantics. The review draft is
        # at the review form's initial (active) status, so fire its Submit edge.
        form_service = FormService(self.db)
        form = form_service.get(tenant_id, config.review_form_id)
        try:
            fired = form_service._fire_submit_and_emit(
                tenant_id, form, draft, draft.answers_json or {}, author_user
            )
        except (FormClosed, FormSubmitInvalid):
            raise
        if not fired:
            raise SurfaceClosed("The review could not be submitted — the Submit step is restricted.")

        a.review_submission_id = draft.id
        a.status = ASSIGNMENT_COMPLETED
        a.completed_at = _now()
        self.db.commit()
        self.db.refresh(a)
        return {
            "assignment_id": a.id,
            "status": a.status,
            "review_submission_id": a.review_submission_id,
            "completed_at": a.completed_at,
        }

    # ---- Decisions (AC-06-45/07) ----

    def decisions_queue(
        self,
        tenant_id: str,
        actor_kind: str,
        actor_id: str,
        context_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """The decider's groups (AC-06-45/07): for every config the actor can
        decide, each submission group with the live partial average, a ready flag
        (completed ≥ required_review_count), the individual completed reviews (the
        decider MAY see them), and current status + any existing decision.
        ``context_id`` (AC-06-25) narrows to a single event's configs; None = all
        contexts."""
        out: List[Dict[str, Any]] = []
        for config in self.configs.configs_for_decider(tenant_id, actor_kind, actor_id):
            if not self._config_in_context(config, context_id):
                continue
            for group_id in self.repo.list_groups_for_config(tenant_id, config.id):
                submission = self._current_submission(tenant_id, group_id)
                if submission is None:
                    continue
                out.append(self._decision_view(tenant_id, config, submission))
        out.sort(key=lambda d: d.get("submitted_at") or d.get("created_at") or _now(), reverse=True)
        return out

    def _decision_view(
        self, tenant_id: str, config: ReviewConfiguration, submission: FormSubmission
    ) -> Dict[str, Any]:
        revision = submission.revision_number or 1
        group_id = submission.submission_group_id
        assignments = self.repo.list_assignments_for_revision(
            tenant_id, config.id, group_id, revision
        )
        completed = [a for a in assignments if a.status == ASSIGNMENT_COMPLETED]
        average = self.configs.average_score(tenant_id, config, group_id, revision)
        ready = len(completed) >= (config.required_review_count or 1)
        status = self._status(tenant_id, submission.form_id, submission.status_id)
        decision = self.repo.get_decision(tenant_id, config.id, group_id, revision)
        return {
            "group_id": group_id,
            "submission_id": submission.id,
            "review_configuration_id": config.id,
            "review_configuration_name": config.name,
            "context_id": config.context_id,
            "context_label": self._context_label(config),
            "title": self._submission_title(submission),
            "revision_number": revision,
            "status_id": submission.status_id,
            "status_label": status.label if status else "",
            "status_color": status.color if status else "gray",
            "average_score": average,
            "completed_count": len(completed),
            "required_review_count": config.required_review_count or 1,
            "ready": ready,
            "decision": decision.decision if decision else None,
            "feedback_text": decision.feedback_text if decision else None,
            "reviews": self._completed_reviews(tenant_id, config, completed),
            "submitted_at": submission.submitted_at,
            "created_at": submission.created_at,
        }

    def _completed_reviews(
        self, tenant_id: str, config: ReviewConfiguration, completed: List[ReviewAssignment]
    ) -> List[Dict[str, Any]]:
        """The completed reviews' answers for the DECIDER surface (AC-06-07 — the
        decider expands individual reviews; this is intentionally NOT used on the
        reviewer surface, which is isolated)."""
        review_ids = [a.review_submission_id for a in completed if a.review_submission_id]
        if not review_ids:
            return []
        rows = (
            self.db.query(FormSubmission)
            .filter(
                FormSubmission.tenant_id == tenant_id,
                FormSubmission.id.in_(review_ids),
            )
            .all()
        )
        by_id = {r.id: r for r in rows}
        out: List[Dict[str, Any]] = []
        for a in completed:
            review = by_id.get(a.review_submission_id) if a.review_submission_id else None
            if review is None:
                continue
            answers = review.answers_json or {}
            score = None
            if config.score_field_key:
                from app.review_engine.service import _as_number

                score = _as_number(answers.get(config.score_field_key))
            out.append(
                {
                    "assignment_id": a.id,
                    "review_submission_id": review.id,
                    "answers": answers,
                    "score": score,
                    "completed_at": a.completed_at,
                }
            )
        return out

    # ---- admin overview (AC-06, §10 deferred — the staff god-view) ----

    def admin_submissions(
        self, tenant_id: str, config_id: str
    ) -> List[Dict[str, Any]]:
        """The ADMIN overview of a Review process (``reviews.read``): EVERY
        submission group bound to the config's submission form, with its current
        status, author, each individual review (reviewer name + score +
        PENDING/COMPLETED/ESCALATED), the live average, and the decision (+
        feedback + decider + decided-at). Read-only.

        Unlike the AUTHOR's My Submissions (which never leaks reviews/scores) this
        is a STAFF view and MAY surface raw reviews/scores. Tenant-scoped
        throughout; names resolve through the contact resolver (returns
        (email, name)), falling back to email/id.

        Iterates every CURRENT-revision submission of the config's submission form
        (not just allocated groups) so a submitted-but-not-yet-allocated group is
        still visible. Reuses ``_decision_view``'s building blocks
        (average + per-revision assignments) — factored, not duplicated."""
        config = self.configs.repo.get_config(tenant_id, config_id)
        if config is None:
            raise SurfaceNotFound()
        rows = (
            self.db.query(FormSubmission)
            .filter(
                FormSubmission.tenant_id == tenant_id,
                FormSubmission.form_id == config.form_id,
                FormSubmission.is_current.is_(True),
            )
            .order_by(FormSubmission.created_at.desc())
            .all()
        )
        return [self._admin_submission_view(tenant_id, config, sub) for sub in rows]

    def _admin_submission_view(
        self, tenant_id: str, config: ReviewConfiguration, submission: FormSubmission
    ) -> Dict[str, Any]:
        from app.review_engine.resolvers import resolve_actor_contact

        revision = submission.revision_number or 1
        group_id = submission.submission_group_id
        status = self._status(tenant_id, submission.form_id, submission.status_id)

        author = self.configs.submission_author_actor(submission)
        author_view: Optional[Dict[str, Any]] = None
        if author is not None:
            kind, actor_id = author
            contact = resolve_actor_contact(self.db, tenant_id, kind, actor_id)
            author_view = {
                "kind": kind,
                "id": actor_id,
                "name": (contact[1] if contact else None) or actor_id,
            }

        assignments = self.repo.list_assignments_for_revision(
            tenant_id, config.id, group_id, revision
        )
        completed = [a for a in assignments if a.status == ASSIGNMENT_COMPLETED]
        review_ids = [a.review_submission_id for a in completed if a.review_submission_id]
        reviews_by_id: Dict[str, FormSubmission] = {}
        if review_ids:
            for r in (
                self.db.query(FormSubmission)
                .filter(
                    FormSubmission.tenant_id == tenant_id,
                    FormSubmission.id.in_(review_ids),
                )
                .all()
            ):
                reviews_by_id[r.id] = r

        reviews: List[Dict[str, Any]] = []
        for a in assignments:
            contact = resolve_actor_contact(self.db, tenant_id, a.actor_kind, a.actor_id)
            score = None
            if a.status == ASSIGNMENT_COMPLETED and a.review_submission_id:
                review = reviews_by_id.get(a.review_submission_id)
                if review is not None and config.score_field_key:
                    from app.review_engine.service import _as_number

                    score = _as_number((review.answers_json or {}).get(config.score_field_key))
            reviews.append(
                {
                    "assignment_id": a.id,
                    "reviewer_kind": a.actor_kind,
                    "reviewer_id": a.actor_id,
                    "reviewer_name": (contact[1] if contact else None) or a.actor_id,
                    "status": a.status,
                    "score": score,
                }
            )

        average = self.configs.average_score(tenant_id, config, group_id, revision)
        required = config.required_review_count or 1
        decision = self.repo.get_decision(tenant_id, config.id, group_id, revision)
        decision_view: Optional[Dict[str, Any]] = None
        if decision is not None:
            d_contact = resolve_actor_contact(
                self.db, tenant_id, decision.decider_kind, decision.decider_id
            )
            decision_view = {
                "decision": decision.decision,
                "feedback_text": decision.feedback_text,
                "decider_kind": decision.decider_kind,
                "decider_id": decision.decider_id,
                "decider_name": (d_contact[1] if d_contact else None) or decision.decider_id,
                "decided_at": decision.decided_at,
            }

        return {
            "group_id": group_id,
            "submission_id": submission.id,
            "revision_number": revision,
            "title": self._submission_title(submission),
            "status_id": submission.status_id,
            "status_label": status.label if status else "",
            "status_color": status.color if status else "gray",
            "author": author_view,
            "submitted_at": submission.submitted_at,
            "created_at": submission.created_at,
            "reviews": reviews,
            "average_score": average,
            "required_review_count": required,
            "completed_count": len(completed),
            "ready": len(completed) >= required,
            "decision": decision_view,
        }

    def decide(
        self,
        tenant_id: str,
        group_id: str,
        actor_kind: str,
        actor_id: str,
        decision: str,
        feedback: Optional[str],
        actor=None,
    ) -> Dict[str, Any]:
        """First-wins decide + the mapped status transition (AC-06-07/34). The
        actor must hold a ``can_decide`` role for the group's config (403 else). A
        concurrent second decide raises ReviewDecisionConflict (→ 409). Early
        decision allowed (no required-count gate, AC-06-45)."""
        submission = self._current_submission(tenant_id, group_id)
        if submission is None:
            raise SurfaceNotFound()
        config = self._config_for_form(tenant_id, submission.form_id)
        if config is None:
            raise SurfaceNotFound()
        if not self.configs.may_decide(tenant_id, config, actor_kind, actor_id):
            raise SurfaceForbidden()
        revision = submission.revision_number or 1
        self.configs.decide_and_transition(
            tenant_id,
            config,
            group_id,
            revision,
            actor_kind,
            actor_id,
            decision,
            feedback,
            actor=actor,
        )
        self.db.refresh(submission)
        return self._decision_view(tenant_id, config, submission)
