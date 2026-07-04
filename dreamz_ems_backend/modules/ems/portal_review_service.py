"""Profile-portal review surfaces (plan sprint-4/06 slice 2) — the EMS thin
layer that drives the CORE review engine for ``profile``-kind actors.

Router (``modules/ems/routers/portal_review.py``) → THIS → core
``ReviewSurfaceService`` / ``ReviewConfigService`` / ``FormService``. The portal
router does NO DB/SQL (Service-Repository).

Everything here is for a PROFILE actor: the actor ref is always
``('profile', profile.id)``. Identity routing (AC-06-10/47) follows for free —
the surface service filters by actor_kind, so a user-kind assignment 404s here.

Cluster-E gates layered on top of the generic engine:
- ``may_submit`` (AC-06-31) + the submission window (AC-06-43) + the tier-1
  ``blocks_access`` profile-status gate (AC-06-51) on submit;
- author capture as ``subject_type='profile'`` (AC-06-41) on submit;
- author-only revise, window-gated (AC-06-09).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.review import ReviewConfiguration
from app.models.status import Status
from app.review_engine.service import ReviewConfigService
from app.review_engine.surfaces import (
    ReviewSurfaceService,
    SurfaceClosed,
    SurfaceForbidden,
    SurfaceNotFound,
)
from modules.ems.models import Profile


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- service exceptions (router maps to HTTP) ----


class PortalReviewError(Exception):
    pass


class PortalReviewNotFound(PortalReviewError):
    """404."""


class PortalReviewForbidden(PortalReviewError):
    """403 — actor lacks the capability / isn't the author."""


class PortalReviewClosed(PortalReviewError):
    """409 — window closed / not in a revisable state."""


class PortalReviewService:
    def __init__(self, db: Session):
        self.db = db
        self.surfaces = ReviewSurfaceService(db)
        self.configs = ReviewConfigService(db)

    # ---- config helpers (tenant-scoped) ----

    def _config(self, profile: Profile, config_id: str) -> ReviewConfiguration:
        config = self.configs.repo.get_config(profile.tenant_id, config_id)
        if config is None:
            raise PortalReviewNotFound()
        return config

    def _window_open(self, config: ReviewConfiguration) -> bool:
        now = _now()
        if config.window_start is not None and now < config.window_start:
            return False
        if config.window_end is not None and now > config.window_end:
            return False
        return True

    def _profile_blocked(self, profile: Profile) -> bool:
        """True when the profile's tier-1 status ``blocks_access`` (AC-06-51 — a
        suspended/blacklisted profile can't submit). Tenant-scoped."""
        if not profile.status_id:
            return False
        status = (
            self.db.query(Status)
            .filter(Status.id == profile.status_id, Status.tenant_id == profile.tenant_id)
            .first()
        )
        return bool(status and status.blocks_access)

    # ---- My Submissions (AC-06-43/52/08) ----

    def my_submissions(
        self, profile: Profile, context_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        return self.surfaces.my_submissions(
            profile.tenant_id, "profile", profile.id, context_id=context_id
        )

    def submit_options(
        self, profile: Profile, context_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """The review configurations the CURRENT profile may submit to (AC-06-03) —
        independent of any existing submissions. One entry per config where the
        profile holds a ``can_submit`` role (resolved via persona memberships →
        ``may_submit``); each carries the window state + a ``can_submit_now`` flag
        (window open AND the profile not ``blocks_access``) so the surface renders a
        window-gated Submit action even for a brand-new participant (AC-06-52 keeps
        it available after submitting too). ``context_id`` narrows to one event
        (AC-06-25). Tenant-scoped throughout."""
        blocked = self._profile_blocked(profile)
        out: List[Dict[str, Any]] = []
        for config in self.configs.repo.list_configs(profile.tenant_id):
            if context_id is not None and config.context_id != context_id:
                continue
            if not self.configs.may_submit(
                profile.tenant_id, config, "profile", profile.id
            ):
                continue
            window_state = self._window_state(config)
            out.append(
                {
                    "config_id": config.id,
                    "name": config.name,
                    "context_id": config.context_id,
                    "context_label": self.surfaces._context_label(config),
                    "submission_form_id": config.form_id,
                    "window_state": window_state,
                    "window_start": config.window_start,
                    "window_end": config.window_end,
                    "can_submit_now": window_state == "open" and not blocked,
                }
            )
        return out

    def _window_state(self, config: ReviewConfiguration) -> str:
        """``open`` | ``closed`` | ``not_yet_open`` for the config's submission
        window (AC-06-43). A None bound is unbounded on that side."""
        now = _now()
        if config.window_start is not None and now < config.window_start:
            return "not_yet_open"
        if config.window_end is not None and now > config.window_end:
            return "closed"
        return "open"

    def submission_detail(self, profile: Profile, group_id: str) -> Dict[str, Any]:
        """The author's view of a submission group's CURRENT revision INCLUDING its
        answers (AC-06-09) — so the author can prefill the revise form. Author-only:
        the current revision's subject must be THIS profile (404 otherwise — a
        non-author / cross-tenant group is invisible). Reuses
        ``FormService.get_submission`` (already returns answers) + the
        author-visible group view for status/decision/can_revise; raw reviews/scores
        are NEVER exposed (AC-06-08)."""
        from app.services.form_service import FormService

        current = self.surfaces._current_submission(profile.tenant_id, group_id)
        if current is None:
            raise PortalReviewNotFound()
        # Author-only guard (tenant-scoped — current is already tenant-scoped).
        if not (current.subject_type == "profile" and current.subject_id == profile.id):
            raise PortalReviewNotFound()
        config = self.surfaces._config_for_form(profile.tenant_id, current.form_id)
        if config is None:
            raise PortalReviewNotFound()
        view = self.surfaces.author_visible_group(profile.tenant_id, config, current)
        # FormService.get_submission carries the answers + form/version refs; the
        # user arg is only used for fireable-edge buttons (ignored here), so a
        # synthetic actor is safe — the row is already author-guarded above.
        sub = FormService(self.db).get_submission(profile.tenant_id, current.id, None)
        view["answers"] = sub.get("answers") or {}
        view["form_id"] = current.form_id
        view["version_id"] = current.version_id
        return view

    def submit_form_view(self, profile: Profile, config_id: str) -> Dict[str, Any]:
        """The submission form's fill view (AC-06-43) — only if the window is open
        AND the profile holds a can_submit role. Returns a friendly ``state`` shape
        otherwise (foolproof-UI; backend is the real boundary)."""
        from app.services.form_service import FormService

        config = self._config(profile, config_id)
        if not self.configs.may_submit(profile.tenant_id, config, "profile", profile.id):
            return {"state": "not_eligible", "message": "You are not a submitter for this process."}
        if self._profile_blocked(profile):
            return {"state": "blocked", "message": "Your account cannot submit at this time."}
        if not self._window_open(config):
            return {"state": "closed", "message": "The submission window is closed."}
        fill = FormService(self.db).fill(profile.tenant_id, config.form_id)
        if fill is None:
            return {"state": "closed", "message": "The submission form is not available."}
        return {"state": "open", "config_id": config.id, "form": fill}

    def submit(
        self, profile: Profile, config_id: str, answers: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Submit the submission form as the profile (author=profile). Enforces
        may_submit (AC-06-31) + window (AC-06-43) + the blocks_access gate
        (AC-06-51), then drives Draft→Submitted (which fires the seeded allocate
        workflow). Author captured as ``subject_type='profile'`` (AC-06-41).
        ``FormClosed``/``FormSubmitInvalid`` from the engine propagate to the
        router (which maps them to 409/422)."""
        from app.services.form_service import FormService

        config = self._config(profile, config_id)
        if not self.configs.may_submit(profile.tenant_id, config, "profile", profile.id):
            raise PortalReviewForbidden()
        if self._profile_blocked(profile):
            raise PortalReviewForbidden()
        if not self._window_open(config):
            raise PortalReviewClosed("The submission window is closed.")
        # Validate the profile belongs to the tenant at save (polymorphic-target_id
        # rule) — current_profile already resolved it tenant-scoped, so the author
        # ref is safe.
        submission = FormService(self.db).submit(
            profile.tenant_id,
            config.form_id,
            None,
            answers,
            subject_type="profile",
            subject_id=profile.id,
        )
        return self.surfaces.author_visible_group(profile.tenant_id, config, submission)

    def revise(self, profile: Profile, group_id: str) -> Dict[str, Any]:
        """Revise the group's current revision (AC-06-09) — author-only,
        window-gated. ``FormService.revise`` enforces the revisions-state
        (frozen-at-revisions) + published-version guards; we add the author + window
        guards (the form engine doesn't know the profile author)."""
        from app.services.form_service import (
            FormRevisionBlocked,
            FormService,
            SubmissionNotFound,
        )

        current = self.surfaces._current_submission(profile.tenant_id, group_id)
        if current is None:
            raise PortalReviewNotFound()
        # Author-only: the current revision's subject must be THIS profile.
        if not (current.subject_type == "profile" and current.subject_id == profile.id):
            raise PortalReviewForbidden()
        config = self.surfaces._config_for_form(profile.tenant_id, current.form_id)
        if config is None:
            raise PortalReviewNotFound()
        # Revise ONLY when the current revision is at the config's revisions
        # status (AC-06-09) — a submission still under review / accepted / rejected
        # is not revisable.
        if not config.revisions_status_id or current.status_id != config.revisions_status_id:
            raise PortalReviewClosed("This submission is not awaiting revisions.")
        if not self._window_open(config):
            raise PortalReviewClosed("The submission window is closed.")
        try:
            # can_manage=True — we already proved the profile is the author (the
            # form engine's own ownership check is User-only).
            draft = FormService(self.db).revise(
                profile.tenant_id, current.id, None, can_manage=True
            )
        except SubmissionNotFound:
            raise PortalReviewNotFound()
        except FormRevisionBlocked as exc:
            raise PortalReviewClosed(str(exc))
        return {"submission_id": draft.id, "group_id": draft.submission_group_id,
                "revision_number": draft.revision_number}

    def resubmit(
        self, profile: Profile, submission_id: str, answers: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Save + re-submit a Draft revision (AC-06-09) — author-only. Re-enters
        review_start → re-allocate (prior-reviewer preference is in allocate)."""
        from app.services.form_service import (
            FormRevisionBlocked,
            FormService,
            SubmissionNotFound,
        )

        submission = self.surfaces._submission_by_id(profile.tenant_id, submission_id)
        if submission is None:
            raise PortalReviewNotFound()
        if not (submission.subject_type == "profile" and submission.subject_id == profile.id):
            raise PortalReviewForbidden()
        config = self.surfaces._config_for_form(profile.tenant_id, submission.form_id)
        if config is None:
            raise PortalReviewNotFound()
        if not self._window_open(config):
            raise PortalReviewClosed("The submission window is closed.")
        try:
            row = FormService(self.db).resubmit_revision(
                profile.tenant_id, submission_id, None, answers, can_manage=True
            )
        except SubmissionNotFound:
            raise PortalReviewNotFound()
        except FormRevisionBlocked as exc:
            raise PortalReviewClosed(str(exc))
        return self.surfaces.author_visible_group(profile.tenant_id, config, row)

    # ---- My Reviews (AC-06-44/05/48) ----

    def my_reviews(
        self, profile: Profile, context_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        return self.surfaces.my_reviews(
            profile.tenant_id, "profile", profile.id, context_id=context_id
        )

    def review_two_pane(self, profile: Profile, assignment_id: str) -> Dict[str, Any]:
        try:
            return self.surfaces.review_two_pane(
                profile.tenant_id, assignment_id, "profile", profile.id
            )
        except SurfaceNotFound:
            raise PortalReviewNotFound()

    def save_review_draft(
        self, profile: Profile, assignment_id: str, answers: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            return self.surfaces.save_review_draft(
                profile.tenant_id, assignment_id, "profile", profile.id, answers
            )
        except SurfaceNotFound:
            raise PortalReviewNotFound()
        except SurfaceClosed as exc:
            raise PortalReviewClosed(str(exc))

    def submit_review(
        self, profile: Profile, assignment_id: str, answers: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        try:
            return self.surfaces.submit_review(
                profile.tenant_id, assignment_id, "profile", profile.id, answers
            )
        except SurfaceNotFound:
            raise PortalReviewNotFound()
        except SurfaceClosed as exc:
            raise PortalReviewClosed(str(exc))

    # ---- Decisions (AC-06-45/07) ----

    def decisions(
        self, profile: Profile, context_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        return self.surfaces.decisions_queue(
            profile.tenant_id, "profile", profile.id, context_id=context_id
        )

    def decide(
        self, profile: Profile, group_id: str, decision: str, feedback: Optional[str]
    ) -> Dict[str, Any]:
        try:
            return self.surfaces.decide(
                profile.tenant_id, group_id, "profile", profile.id, decision, feedback
            )
        except SurfaceNotFound:
            raise PortalReviewNotFound()
        except SurfaceForbidden:
            raise PortalReviewForbidden()
