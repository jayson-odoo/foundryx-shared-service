"""Form engine business logic (plan sprint-3/01) - Router → THIS → Repository.

Owns the whole form lifecycle and the submission pipeline:

- CREATE materializes the form's OWN scoped status machine in the SAME
  transaction (D4) - a minimal Draft→Submitted seed; tenants add review states
  per scope afterwards. Deleting the form drops that graph (delete_scope) then
  cascades versions + submissions.
- PUBLISH runs the ``validate_form_doc`` gate (D9), snapshots the draft into an
  immutable ``FormVersion`` and points ``current_version_id`` at it. Fill
  surfaces serve ONLY the published version; preview renders the live draft.
- SUBMIT (D14) is the never-trust-the-client boundary: window/cap guards →
  ``validate_submission`` (drops hidden answers, recomputes computed fields,
  per-field 422 map) → create the submission at the scope's initial status →
  move it to "Submitted" through the ONE status executor (notifications + the
  workflow ``status_changed`` event ride that transition).

Errors are SERVICE exceptions the router maps to HTTP (workflow_service
precedent): ``FormNotFound`` 404, ``FormPublishBlocked`` 422 {problems},
``FormSubmitInvalid`` 422 {fieldErrors}, ``FormClosed`` 409.
"""
import base64
import csv
import io
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.form_engine.schemas import FormDocument, FormField, validate_form_doc
from app.form_engine.validation import validate_submission
from app.uploads import detect_upload_mime
from app.models.form import (
    ACCESS_INTERNAL,
    ACCESS_PUBLIC,
    FORM_ACCESS_VALUES,
    FORM_ARCHIVED,
    FORM_DRAFT,
    FORM_HONEYPOT_FIELD,
    FORM_PUBLISHED,
    FORM_SUBMISSION_ENTITY,
    PUBLIC_STATE_CLOSED,
    PUBLIC_STATE_FULL,
    PUBLIC_STATE_OPEN,
    Form,
    FormSubmission,
    FormVersion,
)
from app.models.status import Status
from app.models.user import User
from app.repositories.form_repository import FormRepository
from app.repositories.form_submission_repository import FormSubmissionRepository
from app.repositories.status_repository import StatusRepository
from app.repositories.status_transition_repository import StatusTransitionRepository
from app.schemas.filters import FilterGroup
from app.services import status_machine
from app.services.filter_translator import translate_filter
from app.workflow_engine.entity_events import emit_entity_event
from app.services.status_machine import (
    TransitionConditionsNotMet,
    TransitionForbidden,
    TransitionNotAllowed,
)
from app.status_engine.scoped import (
    ScopeSeedEdge,
    ScopeSeedStatus,
    delete_scope,
    get_scope_status,
    initial_scope_status,
    materialize_scope,
)

# The minimal seed graph every new form's submissions start on (D4). Flag
# semantics, never labels: ``is_active`` on a SCOPED status means "the
# respondent may still edit answers" - so Submitted is intentionally inactive.
SUBMISSION_SEED_STATUSES = [
    ScopeSeedStatus(
        key="draft",
        label="Draft",
        color="gray",
        sort_order=1,
        flags={"is_initial": True, "is_active": True, "is_default": True},
    ),
    ScopeSeedStatus(
        key="submitted",
        label="Submitted",
        color="blue",
        sort_order=2,
        flags={"is_active": False},
    ),
]
SUBMISSION_SEED_EDGES = [
    ScopeSeedEdge(from_key="draft", to_key="submitted", label="Submit", sort_order=1),
]

_DISPLAY_MODES = ("paged", "single")

# Filter translator whitelist (entity-agnostic translator; never arbitrary cols).
_FILTER_COLUMNS = {
    "name": Form.name,
    "status": Form.status,
    "access": Form.access,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return base or "form"


# ---- service exceptions ----


class FormError(Exception):
    pass


class FormNotFound(FormError):
    pass


class FormValidationError(FormError):
    """Bad input value (e.g. unknown access/displayMode/garbage draft doc) → 422."""


class FormPublishBlocked(FormError):
    """The publish gate found problems (D9) - 422 detail={'problems': [...]}."""

    def __init__(self, problems: List[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class FormSubmitInvalid(FormError):
    """Per-field validation failed (D14) - 422 detail={'fieldErrors': {...}}."""

    def __init__(self, field_errors: Dict[str, str]):
        super().__init__("Some answers need attention.")
        self.field_errors = field_errors


class FormClosed(FormError):
    """The form is not accepting submissions (unpublished / window / cap) → 409."""


class SubmissionNotFound(FormError):
    pass


class FormRevisionBlocked(FormError):
    """Revise refused - revisions off / not current / not frozen / no published
    version (plan sprint-4/04) → 409."""


class FormRevisionForbidden(FormError):
    """The caller is neither the submission owner nor a manager → 403."""


@dataclass
class UploadedFormFile:
    """One multipart file part bound to a field key (plan sprint-3/02 D12). The
    router reads the bytes with a capped read; the service sniff-gates + stores."""

    field_key: str
    filename: str
    content: bytes


def _decode_data_url(value: str) -> Optional[bytes]:
    """Decode a ``data:<mime>;base64,<...>`` signature payload → raw bytes."""
    try:
        header, _, b64 = value.partition(",")
        if "base64" not in header or not b64:
            return None
        return base64.b64decode(b64, validate=True)
    except Exception:  # noqa: BLE001
        return None


class FormService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = FormRepository(db)
        self.subs = FormSubmissionRepository(db)

    # ---- helpers ----

    def _user_name(self, user_id: Optional[str]) -> Optional[str]:
        if not user_id:
            return None
        user = self.db.query(User).filter(User.id == user_id).first()
        return (user.name or user.email) if user else None

    def _current_version(self, tenant_id: str, form: Form) -> Optional[FormVersion]:
        if not form.current_version_id:
            return None
        return self.repo.get_version(tenant_id, form.current_version_id)

    def _has_unpublished(self, tenant_id: str, form: Form) -> bool:
        """Draft differs from the published snapshot (toolbar marker, D9). With
        no published version: any non-empty draft counts as unpublished."""
        version = self._current_version(tenant_id, form)
        if version is None:
            doc = form.draft_definition_json or {}
            return bool(doc.get("pages"))
        return json.dumps(version.definition_json, sort_keys=True) != json.dumps(
            form.draft_definition_json, sort_keys=True
        )

    def _unique_slug(self, tenant_id: str, name: str) -> str:
        base = _slugify(name)
        slug = base
        n = 2
        while self.repo.slug_taken(tenant_id, slug):
            slug = f"{base}-{n}"
            n += 1
        return slug

    # ---- row mapping ----

    def to_row(self, tenant_id: str, form: Form, *, submission_count: Optional[int] = None) -> Dict[str, Any]:
        if submission_count is None:
            submission_count = self.repo.submission_count(tenant_id, form.id)
        version = self._current_version(tenant_id, form)
        return {
            "id": form.id,
            "name": form.name,
            "slug": form.slug,
            "description": form.description,
            "status": form.status,
            "access": form.access,
            "is_trashed": form.status == FORM_ARCHIVED,
            "current_version_id": form.current_version_id,
            "current_version_number": version.version_number if version else None,
            "has_unpublished_changes": self._has_unpublished(tenant_id, form),
            "opens_at": form.opens_at,
            "closes_at": form.closes_at,
            "max_submissions": form.max_submissions,
            "submission_limit_per_user": form.submission_limit_per_user,
            "pinned_columns": form.pinned_columns_json or [],
            "display_mode": form.display_mode,
            "allow_revisions": form.allow_revisions,
            "submission_count": submission_count,
            "created_at": form.created_at,
            "updated_at": form.updated_at,
        }

    def to_detail(self, tenant_id: str, form: Form) -> Dict[str, Any]:
        row = self.to_row(tenant_id, form)
        row["draft_definition"] = form.draft_definition_json or {}
        return row

    # ---- list ----

    def list(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        status_view: Optional[str] = None,
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        clause = translate_filter(filter_group, _FILTER_COLUMNS)
        rows, total = self.repo.paginate(
            tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            status_view=status_view,
            filter_clause=clause,
        )
        counts = self.repo.submission_counts(tenant_id, [f.id for f in rows])
        return [self.to_row(tenant_id, f, submission_count=counts.get(f.id, 0)) for f in rows], total

    def get_at(self, index: int, tenant_id: str, **kwargs) -> Tuple[Optional[Dict[str, Any]], int]:
        rows, total = self.list(tenant_id, page=max(index, 0), page_size=1, **kwargs)
        return (rows[0] if rows else None), total

    # ---- detail ----

    def get(self, tenant_id: str, form_id: str) -> Form:
        form = self.repo.get_by_id(tenant_id, form_id)
        if form is None:
            raise FormNotFound()
        return form

    # ---- writes ----

    def create(self, tenant_id: str, user: User, *, name: str, description: str = "", access: str = ACCESS_INTERNAL) -> Form:
        name = (name or "").strip()
        if not name:
            raise FormValidationError("A name is required.")
        if access not in FORM_ACCESS_VALUES:
            raise FormValidationError(f"Unknown access '{access}'.")
        form = Form(
            tenant_id=tenant_id,
            name=name,
            slug=self._unique_slug(tenant_id, name),
            description=(description or "").strip(),
            status=FORM_DRAFT,
            access=access,
            draft_definition_json={"schemaVersion": 1, "pages": []},
            created_by=user.id,
        )
        self.repo.add(form)
        # Materialize the form's own scoped submission machine IN THIS txn (D4).
        materialize_scope(
            self.db,
            FORM_SUBMISSION_ENTITY,
            tenant_id,
            form.id,
            SUBMISSION_SEED_STATUSES,
            SUBMISSION_SEED_EDGES,
        )
        self.db.commit()
        self.db.refresh(form)
        return form

    def update(self, tenant_id: str, form_id: str, *, fields_set: set, **values) -> Form:
        """PATCH - only keys present in ``fields_set`` are applied (so an absent
        field is untouched and an explicit null clears nullable columns)."""
        form = self.get(tenant_id, form_id)

        if "name" in fields_set and values.get("name") is not None:
            form.name = values["name"].strip()
        if "description" in fields_set:
            form.description = (values.get("description") or "").strip()
        if "access" in fields_set and values.get("access") is not None:
            if values["access"] not in FORM_ACCESS_VALUES:
                raise FormValidationError(f"Unknown access '{values['access']}'.")
            form.access = values["access"]
        if "displayMode" in fields_set and values.get("displayMode") is not None:
            if values["displayMode"] not in _DISPLAY_MODES:
                raise FormValidationError(f"Unknown display mode '{values['displayMode']}'.")
            form.display_mode = values["displayMode"]
        if "draftDefinition" in fields_set and values.get("draftDefinition") is not None:
            draft = values["draftDefinition"]
            try:
                # Structural validation only (forever-contract shape); the
                # PUBLISH gate runs the stricter completeness rules.
                FormDocument.model_validate(draft)
            except Exception as exc:  # noqa: BLE001
                raise FormValidationError(f"The form document is malformed: {exc}")
            form.draft_definition_json = draft
        if "opensAt" in fields_set:
            form.opens_at = values.get("opensAt")
        if "closesAt" in fields_set:
            form.closes_at = values.get("closesAt")
        if "maxSubmissions" in fields_set:
            form.max_submissions = values.get("maxSubmissions")
        if "submissionLimitPerUser" in fields_set:
            form.submission_limit_per_user = values.get("submissionLimitPerUser")
        if "pinnedColumns" in fields_set:
            form.pinned_columns_json = values.get("pinnedColumns")
        if "allowRevisions" in fields_set and values.get("allowRevisions") is not None:
            form.allow_revisions = bool(values["allowRevisions"])

        self.db.commit()
        self.db.refresh(form)
        return form

    def publish(self, tenant_id: str, form_id: str, user: User) -> Form:
        form = self.get(tenant_id, form_id)
        problems = validate_form_doc(form.draft_definition_json or {})
        if problems:
            raise FormPublishBlocked(problems)
        # Review-engine guard (plan sprint-4/06 AC-06-36): if this form is used as
        # a review (rubric) form by any review configuration, publishing a
        # revision that DROPS or non-numeric-RETYPES a referenced score field
        # would break the average forever. Block it. Tenant-scoped; failure-safe
        # (a missing/empty review table never blocks an ordinary form's publish).
        review_problems = self._review_score_field_problems(tenant_id, form)
        if review_problems:
            raise FormPublishBlocked(review_problems)
        version = FormVersion(
            form_id=form.id,
            version_number=self.repo.next_version_number(form.id),
            definition_json=json.loads(json.dumps(form.draft_definition_json)),
            published_by=user.id,
        )
        self.repo.add_version(version)
        form.current_version_id = version.id
        form.status = FORM_PUBLISHED
        self.db.commit()
        self.db.refresh(form)
        return form

    def _review_score_field_problems(self, tenant_id: str, form: Form) -> List[str]:
        """Problems blocking publish because this form is a review-engine rubric
        form whose new DRAFT would drop / non-numeric-retype a score field that a
        review configuration references (AC-06-36). Empty list when the form isn't
        a review form. Local import keeps the form engine independent of the
        review engine's models (no import cycle)."""
        from app.models.review import ReviewConfiguration
        from app.form_engine.schemas import NUMERIC_FIELD_TYPES

        configs = (
            self.db.query(ReviewConfiguration)
            .filter(
                ReviewConfiguration.tenant_id == tenant_id,
                ReviewConfiguration.review_form_id == form.id,
                ReviewConfiguration.score_field_key.isnot(None),
            )
            .all()
        )
        if not configs:
            return []
        try:
            doc = FormDocument.model_validate(form.draft_definition_json or {})
        except Exception:  # noqa: BLE001 - already validated above; defensive
            return []
        numeric = {
            f.key for f in doc.input_fields() if f.key and f.type in NUMERIC_FIELD_TYPES
        }
        problems: List[str] = []
        seen: set = set()
        for config in configs:
            key = config.score_field_key
            if key in seen or key in numeric:
                seen.add(key)
                continue
            seen.add(key)
            problems.append(
                f'Cannot publish: score field "{key}" used by a review process '
                "must remain a numeric field."
            )
        return problems

    def unpublish(self, tenant_id: str, form_id: str) -> Form:
        # Keep ``current_version_id`` so re-publishing an unchanged draft is
        # possible; fill() refuses while status != published (D9).
        form = self.get(tenant_id, form_id)
        form.status = FORM_DRAFT
        self.db.commit()
        self.db.refresh(form)
        return form

    def archive(self, tenant_id: str, form_id: str) -> Form:
        form = self.get(tenant_id, form_id)
        form.status = FORM_ARCHIVED
        self.db.commit()
        self.db.refresh(form)
        return form

    def restore(self, tenant_id: str, form_id: str) -> Form:
        # Restore to published when a snapshot exists, else back to draft.
        form = self.get(tenant_id, form_id)
        form.status = FORM_PUBLISHED if form.current_version_id else FORM_DRAFT
        self.db.commit()
        self.db.refresh(form)
        return form

    def delete(self, tenant_id: str, form_id: str) -> None:
        form = self.get(tenant_id, form_id)
        # Drop the scoped status graph first (submissions reference its rows),
        # then the form - versions + submissions cascade via FK.
        delete_scope(self.db, FORM_SUBMISSION_ENTITY, tenant_id, form.id)
        self.repo.delete(form)
        self.db.commit()

    # ---- versions ----

    def list_versions(
        self, tenant_id: str, form_id: str, *, page: int = 0, page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        self.get(tenant_id, form_id)  # tenant ownership check
        rows, total = self.repo.versions_paginate(tenant_id, form_id, page=page, page_size=page_size)
        return [
            {
                "id": v.id,
                "version_number": v.version_number,
                "published_by": v.published_by,
                "published_by_name": self._user_name(v.published_by),
                "created_at": v.created_at,
            }
            for v in rows
        ], total

    def get_version(self, tenant_id: str, form_id: str, version_id: str):
        """ONE version, tenant-scoped AND owner-checked (the submission detail
        page re-renders against its pinned version, D9). None on any mismatch."""
        version = self.repo.get_version(tenant_id, version_id)
        if version is None or version.form_id != form_id:
            return None
        return version

    # ---- fill / preview (D9) ----

    def _fill_view(self, form: Form, version: FormVersion) -> Dict[str, Any]:
        return {
            "form_id": form.id,
            "version_id": version.id,
            "version_number": version.version_number,
            "name": form.name,
            "description": form.description,
            "definition": version.definition_json,
            "paged": form.display_mode == "paged",
        }

    def preview(self, tenant_id: str, form_id: str) -> Dict[str, Any]:
        """Author preview - renders the live DRAFT (D9). version 0 / no real id
        because the draft is unsnapshotted."""
        form = self.get(tenant_id, form_id)
        return {
            "form_id": form.id,
            "version_id": "",
            "version_number": 0,
            "name": form.name,
            "description": form.description,
            "definition": form.draft_definition_json or {"schemaVersion": 1, "pages": []},
            "paged": form.display_mode == "paged",
        }

    def fill(self, tenant_id: str, form_id: str) -> Optional[Dict[str, Any]]:
        """Fill surface - serves the PUBLISHED current version only (D9).
        Returns None when the form is not currently published."""
        form = self.get(tenant_id, form_id)
        if form.status != FORM_PUBLISHED or not form.current_version_id:
            return None
        version = self._current_version(tenant_id, form)
        if version is None:
            return None
        return self._fill_view(form, version)

    # ---- public surface (plan sprint-3/02, D11/D12) ----

    def _resolve_public(self, tenant_slug: str, form_slug: str) -> Optional[Tuple[Form, FormVersion]]:
        """Resolve a SERVABLE public form by (tenant slug, form slug). Returns
        None for every non-servable case - unknown/suspended tenant, unknown
        form, non-public access, or not currently published - so the router can
        answer a UNIFORM 404 (no enumeration, D11). A published-but-window-closed
        or full form IS servable here (the caller decides open vs closed/full)."""
        from app.repositories.tenant_repository import TenantRepository

        tenant = TenantRepository(self.db).get_by_slug(tenant_slug)
        if tenant is None or not tenant.signin_allowed:
            return None
        form = self.repo.get_by_slug(tenant.id, form_slug)
        if form is None or form.access != ACCESS_PUBLIC:
            return None
        if form.status != FORM_PUBLISHED or not form.current_version_id:
            return None
        version = self._current_version(tenant.id, form)
        if version is None:
            return None
        return form, version

    def _public_state(self, form: Form) -> Tuple[str, Optional[str]]:
        """(state, friendly message) for a servable public form."""
        now = _now()
        if form.opens_at is not None and now < form.opens_at:
            return PUBLIC_STATE_CLOSED, "This form is not open yet."
        if form.closes_at is not None and now > form.closes_at:
            return PUBLIC_STATE_CLOSED, "This form is closed."
        if (
            form.max_submissions is not None
            and self.subs.count_for_form(form.tenant_id, form.id) >= form.max_submissions
        ):
            return PUBLIC_STATE_FULL, "This form has reached its submission limit."
        return PUBLIC_STATE_OPEN, None

    def public_view(self, tenant_slug: str, form_slug: str) -> Optional[Dict[str, Any]]:
        """The anonymous fill view, or None for a uniform 404."""
        resolved = self._resolve_public(tenant_slug, form_slug)
        if resolved is None:
            return None
        form, version = resolved
        state, message = self._public_state(form)
        return {
            "state": state,
            "form_id": form.id,
            "version_id": version.id,
            "name": form.name,
            "description": form.description,
            "definition": version.definition_json if state == PUBLIC_STATE_OPEN else None,
            "paged": form.display_mode == "paged",
            "honeypot_field": FORM_HONEYPOT_FIELD,
            "message": message,
        }

    def public_submit(
        self,
        tenant_slug: str,
        form_slug: str,
        answers: Dict[str, Any],
        honeypot: str,
        uploads: Optional[List[UploadedFormFile]] = None,
    ) -> Optional[FormSubmission]:
        """Anonymous submit. Returns None when the honeypot is tripped (silently
        dropped - never tip off the bot, D12). Raises FormNotFound (→404) for a
        non-servable form; FormClosed (→409) / FormSubmitInvalid (→422) ride the
        shared submit pipeline. user=None → anonymous; per-user cap is unenforced
        for public forms (D10)."""
        resolved = self._resolve_public(tenant_slug, form_slug)
        if resolved is None:
            raise FormNotFound()
        form, _version = resolved
        # Honeypot: a non-empty value = a bot. Pretend success, store nothing.
        if honeypot and honeypot.strip():
            return None
        return self.submit(form.tenant_id, form.id, None, answers, uploads)

    # ---- submit (D14) ----

    def submit(
        self,
        tenant_id: str,
        form_id: str,
        user: Optional[User],
        answers: Dict[str, Any],
        uploads: Optional[List[UploadedFormFile]] = None,
        *,
        subject_type: Optional[str] = None,
        subject_id: Optional[str] = None,
    ) -> FormSubmission:
        """Capture a submission. ``subject_type``/``subject_id`` record an
        inbound polymorphic AUTHOR ref (plan sprint-4/06 AC-06-41): the portal
        passes ``user=None, subject_type='profile', subject_id=<profile_id>`` so
        the review engine resolves the author as ``('profile', id)``; staff submit
        keeps ``user`` (author ``('user', id)``). The caller (PortalReviewService)
        validates the profile belongs to the tenant at save; resolution at read is
        tenant-scoped (the polymorphic-target_id rule)."""
        form = self.get(tenant_id, form_id)

        # 1. The form must be currently accepting submissions.
        if form.status != FORM_PUBLISHED or not form.current_version_id:
            raise FormClosed("Form is not accepting submissions.")

        # 2. Submission window (aware-UTC comparisons, BL-012).
        now = _now()
        if form.opens_at is not None and now < form.opens_at:
            raise FormClosed("This form is not open yet.")
        if form.closes_at is not None and now > form.closes_at:
            raise FormClosed("This form is closed.")

        # 3. Total cap. v1 is check-then-insert in one transaction; a tiny race
        # window can overshoot by one under concurrency (acceptable for v1 - the
        # same pattern as the email-outbox cancel claim; a DB-level atomic guard
        # is the hardening follow-up).
        if form.max_submissions is not None:
            if self.subs.count_for_form(tenant_id, form_id) >= form.max_submissions:
                raise FormClosed("This form has reached its submission limit.")

        # 4. Per-user cap - enforceable only with an authenticated identity on an
        # internal form (public/anonymous ignore it, D10).
        if (
            form.access == ACCESS_INTERNAL
            and user is not None
            and form.submission_limit_per_user is not None
            and self.subs.count_for_user(tenant_id, form_id, user.id)
            >= form.submission_limit_per_user
        ):
            raise FormClosed("You have reached the submission limit for this form.")

        # 5. Never trust the client (D14): re-derive visible set, drop hidden
        # answers, recompute computed fields, per-field 422 map.
        version = self._current_version(tenant_id, form)
        if version is None:
            raise FormClosed("Form is not accepting submissions.")

        # 5a. Sniff-gate uploads + signatures BEFORE validation, replacing client
        # file placeholders with provisional answers (real name/size/sniffed
        # mime). Bytes are stored ONLY after the row exists (the quarantine key
        # needs the submission id) - so a validation failure leaves NO orphan
        # blobs (D12). ``staged`` = field_key → list of (mime, bytes, filename).
        field_map = self._field_map(version.definition_json)
        staged, staged_sig, file_errors = self._stage_uploads(field_map, answers, uploads or [])

        clean, errors = validate_submission(version.definition_json, answers)
        # Only surface upload errors for fields in the VISIBLE set (clean keys) -
        # a file field hidden by a condition is dropped by validation and must
        # NEVER 422 (the hidden-fields-never-error contract; code-review).
        visible_file_errors = {k: v for k, v in file_errors.items() if k in clean}
        errors = {**visible_file_errors, **errors}
        if errors:
            raise FormSubmitInvalid(errors)

        # 6. Create at the scope's initial status, then move to "Submitted"
        # through the ONE status executor (D4) - notifications + the workflow
        # status_changed event ride that transition.
        initial = initial_scope_status(self.db, FORM_SUBMISSION_ENTITY, tenant_id, form.id)
        if initial is None:
            raise FormError("This form's submission machine is misconfigured.")
        # An original's group id == its own id (R1) - generate it explicitly so
        # external refs to the group resolve to this row from day one.
        sub_id = str(uuid.uuid4())
        submission = FormSubmission(
            id=sub_id,
            tenant_id=tenant_id,
            form_id=form.id,
            submission_group_id=sub_id,
            revision_number=1,
            is_current=True,
            version_id=form.current_version_id,
            status_id=initial.id,
            user_id=user.id if user else None,
            subject_type=subject_type,
            subject_id=subject_id,
            # Deep copy so the column's change-tracking baseline is INDEPENDENT
            # of ``clean`` - _store_uploads mutates ``clean`` in place, and a
            # plain JSON column would otherwise see the post-mutation baseline
            # and miss the swap (so the placeholder would persist).
            answers_json=json.loads(json.dumps(clean)),
            submitted_at=None,
        )
        self.subs.add(submission)

        # 6a. Store uploaded bytes under quarantine keys now the row exists, and
        # swap the provisional placeholders in ``clean`` for real storage keys.
        # Hidden file/signature fields were dropped by validation → never stored.
        if staged or staged_sig:
            self._store_uploads(tenant_id, form.id, submission, clean, staged, staged_sig)
            submission.answers_json = json.loads(json.dumps(clean))

        # Move Draft→Submitted + fire the form.submitted event. A tenant that
        # restricted the Submit edge leaves the record at Draft (lenient - the
        # initial submit doesn't fail; a revision resubmit does, see below).
        self._fire_submit_and_emit(tenant_id, form, submission, clean, user)
        self.db.commit()
        self.db.refresh(submission)
        return submission

    def _fire_submit_and_emit(
        self,
        tenant_id: str,
        form: Form,
        submission: FormSubmission,
        clean: Dict[str, Any],
        user: Optional[User],
    ) -> bool:
        """Move a captured submission Draft→Submitted through the ONE status
        executor (D4) and fire the form.submitted workflow trigger. Returns
        whether the move happened (False = no Submitted target, or the tenant
        restricted the Submit edge - the record stays at Draft, submitted_at
        unstamped: a record at Draft is NOT "submitted"). The event is buffered
        on the session → drained failure-isolated on the SAME commit's
        after_commit hook (the status_changed event rides along) - a broken
        workflow can NEVER 500 the submit/resubmit. Shared by submit() +
        resubmit_revision() so the invariants live in ONE place."""
        submitted = self._submitted_status(tenant_id, form.id)
        if submitted is None:
            return False
        try:
            status_machine.transition(
                self.db,
                FORM_SUBMISSION_ENTITY,
                submission,
                submitted.id,
                user,
                tenant_id=tenant_id,
                commit=False,
            )
        except (TransitionNotAllowed, TransitionForbidden, TransitionConditionsNotMet):
            return False
        submission.submitted_at = _now()
        self.db.flush()
        emit_entity_event(
            self.db,
            FORM_SUBMISSION_ENTITY,
            "submitted",
            submission,
            tenant_id=tenant_id,
            actor=user,
            extra={"formId": form.id, "submissionId": submission.id, "answers": clean},
        )
        return True

    # ---- upload pipeline (D12) ----

    def _field_map(self, definition: Dict[str, Any]) -> Dict[str, FormField]:
        """{answer key → FormField} for the version (uploads need the per-field
        file caps + which fields are signatures)."""
        doc = FormDocument.model_validate(definition)
        return {
            field.key: field
            for page in doc.pages
            for section in page.sections
            for field in section.fields
            if field.key
        }

    def _stage_uploads(
        self,
        field_map: Dict[str, FormField],
        answers: Dict[str, Any],
        uploads: List[UploadedFormFile],
    ) -> Tuple[Dict[str, List], Dict[str, bytes], Dict[str, str]]:
        """Sniff-gate the multipart parts + signature data-URLs, MUTATING
        ``answers`` to carry provisional file answers (so validation sees real
        count/size). Returns (staged files, staged signatures, per-field errors).
        Parts whose field is unknown/not-a-file are ignored (like hidden answers
        - curl can't force-feed them). Total per-submission cap enforced here."""
        staged: Dict[str, List] = {}
        staged_sig: Dict[str, bytes] = {}
        errors: Dict[str, str] = {}
        total = 0
        max_total = int(settings.form_upload_max_total_mb * 1024 * 1024)

        for up in uploads:
            field = field_map.get(up.field_key)
            if field is None or field.type != "file":
                continue  # stray/unknown part - drop silently
            mime = detect_upload_mime(up.content, up.filename)
            if mime is None:
                errors[up.field_key] = "Unsupported file type."
                continue
            allowed = field.file.allowed_mimes if field.file else None
            if allowed and mime not in allowed:
                errors[up.field_key] = "This file type is not allowed."
                continue
            max_mb = field.file.max_size_mb if field.file else None
            if max_mb is not None and len(up.content) > max_mb * 1024 * 1024:
                errors[up.field_key] = f"Each file must be under {max_mb:g} MB."
                continue
            total += len(up.content)
            if total > max_total:
                errors[up.field_key] = "The total upload size is too large."
                continue
            staged.setdefault(up.field_key, []).append((mime, up.content, up.filename))

        # Provisional file answers (replace the client's `local:` placeholders).
        for key, items in staged.items():
            answers[key] = [
                {"key": f"pending:{i}", "name": fn, "size": len(content), "mime": mime}
                for i, (mime, content, fn) in enumerate(items)
            ]

        # Signatures arrive as data-URL strings; decode + sniff (PNG only), stage
        # like a file, leave a placeholder string for validation to pass through.
        for key, field in field_map.items():
            if field.type != "signature":
                continue
            value = answers.get(key)
            if not isinstance(value, str) or not value.startswith("data:"):
                continue
            content = _decode_data_url(value)
            if content is None or detect_upload_mime(content) != "image/png":
                errors[key] = "The signature could not be read."
                continue
            staged_sig[key] = content
            answers[key] = "pending:signature"

        return staged, staged_sig, errors

    def _store_uploads(
        self,
        tenant_id: str,
        form_id: str,
        submission: FormSubmission,
        clean: Dict[str, Any],
        staged: Dict[str, List],
        staged_sig: Dict[str, bytes],
    ) -> None:
        """Persist staged bytes under quarantine keys and swap the placeholders
        in ``clean`` for real storage keys. Key scheme (D12):
        ``forms/{form_id}/{submission_id}/{field_key}/{n}``."""
        from app.services.storage import storage_for_tenant

        storage = storage_for_tenant(self.db, tenant_id)
        base = f"forms/{form_id}/{submission.id}"

        for key, items in staged.items():
            if not isinstance(clean.get(key), list):
                continue  # field was hidden → dropped by validation, never store
            stored = []
            for i, (mime, content, filename) in enumerate(items):
                storage_key = storage.save(f"{base}/{key}/{i}", content, mime)
                stored.append({"key": storage_key, "name": filename, "size": len(content), "mime": mime})
            clean[key] = stored

        for key, content in staged_sig.items():
            if key not in clean:
                continue  # hidden → dropped
            clean[key] = storage.save(f"{base}/{key}/0", content, "image/png")

    def _submitted_status(self, tenant_id: str, form_id: str) -> Optional[Status]:
        """Resolve the scope's "Submitted" target. Prefer the seed key; if the
        tenant renamed/deleted it, fall back to the single outgoing edge from
        the initial status (a one-way Draft→? graph still works)."""
        status_repo = StatusRepository(self.db)
        row = status_repo.get_by_key(
            FORM_SUBMISSION_ENTITY, "submitted", tenant_id, scope_id=form_id
        )
        if row is not None:
            return row
        initial = initial_scope_status(self.db, FORM_SUBMISSION_ENTITY, tenant_id, form_id)
        if initial is None:
            return None
        edges = StatusTransitionRepository(self.db).outgoing(initial.id, tenant_id)
        if len(edges) == 1:
            return status_repo.get_by_id(edges[0].to_status_id)
        return None

    # ---- submissions list ----

    def list_submissions(
        self,
        tenant_id: str,
        form_id: str,
        user: User,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "desc",
        segment: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        self.get(tenant_id, form_id)  # tenant ownership check
        rows, total = self.subs.paginate(
            tenant_id,
            form_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            segment=segment,
        )
        fireable = self._fireable_map(tenant_id, form_id, rows, user)
        # Status rows for the page (label/color) - one query over the page's ids.
        status_by_id = self._status_map(tenant_id, form_id, {r.status_id for r in rows})
        return [
            self._submission_row(r, status_by_id, fireable.get(r.id))
            for r in rows
        ], total

    def _status_map(self, tenant_id: str, form_id: str, status_ids: set) -> Dict[str, Status]:
        if not status_ids:
            return {}
        rows = (
            self.db.query(Status)
            .filter(
                Status.entity_type == FORM_SUBMISSION_ENTITY,
                Status.tenant_id == tenant_id,
                Status.scope_id == form_id,
                Status.id.in_(status_ids),
            )
            .all()
        )
        return {s.id: s for s in rows}

    def _fireable_map(
        self, tenant_id: str, form_id: str, rows: List[FormSubmission], user: User
    ) -> Dict[str, List[str]]:
        """Per-record fireable edge ids for the list buttons (D15). The generic
        ``fireable_edge_ids`` only returns a map when conditioned edges exist;
        for list surfaces the buttons need the fireable edges even unconditioned,
        so we compute outgoing-from-current per DISTINCT status (cached - records
        sharing a status reuse the same edge set; role/condition check via
        ``available_transitions``)."""
        conditioned = status_machine.fireable_edge_ids(
            self.db, FORM_SUBMISSION_ENTITY, rows, actor=user, tenant_id=tenant_id
        )
        if conditioned is not None:
            return conditioned
        cache: Dict[str, List[str]] = {}
        result: Dict[str, List[str]] = {}
        for row in rows:
            if row.status_id not in cache:
                edges = status_machine.available_transitions(
                    self.db, FORM_SUBMISSION_ENTITY, row, actor=user, tenant_id=tenant_id
                )
                cache[row.status_id] = [e.id for e in edges]
            result[row.id] = cache[row.status_id]
        return result

    def _submission_row(
        self,
        submission: FormSubmission,
        status_by_id: Dict[str, Status],
        fireable: Optional[List[str]],
    ) -> Dict[str, Any]:
        status = status_by_id.get(submission.status_id)
        return {
            "id": submission.id,
            "form_id": submission.form_id,
            "submission_group_id": submission.submission_group_id,
            "revision_number": submission.revision_number,
            "is_current": submission.is_current,
            "version_id": submission.version_id,
            "version_number": self._version_number(submission),
            "status_id": submission.status_id,
            "status_key": status.key if status else "",
            "status_label": status.label if status else "",
            "status_color": status.color if status else "gray",
            "user_id": submission.user_id,
            "user_name": self._user_name(submission.user_id),
            "subject_type": submission.subject_type,
            "subject_id": submission.subject_id,
            "answers": submission.answers_json or {},
            "submitted_at": submission.submitted_at,
            "created_at": submission.created_at,
            "updated_at": submission.updated_at,
            "available_transition_ids": fireable,
        }

    def _version_number(self, submission: FormSubmission) -> int:
        # Tenant-scoped via the join to forms - never resolve a stored id
        # unscoped (the polymorphic target_id rule; code-review finding).
        version = (
            self.db.query(FormVersion.version_number)
            .join(Form, Form.id == FormVersion.form_id)
            .filter(
                FormVersion.id == submission.version_id,
                Form.tenant_id == submission.tenant_id,
            )
            .first()
        )
        return version[0] if version else 0

    # ---- single submission + transition ----

    def get_submission(self, tenant_id: str, submission_id: str, user: User) -> Dict[str, Any]:
        submission = self.subs.get_by_id(tenant_id, submission_id)
        if submission is None:
            raise SubmissionNotFound()
        status_by_id = self._status_map(tenant_id, submission.form_id, {submission.status_id})
        fireable = self._fireable_map(tenant_id, submission.form_id, [submission], user)
        return self._submission_row(submission, status_by_id, fireable.get(submission.id))

    def transition_submission(self, tenant_id: str, submission_id: str, transition_id: str, user: User) -> Dict[str, Any]:
        submission = self.subs.get_by_id(tenant_id, submission_id)
        if submission is None:
            raise SubmissionNotFound()
        # Resolve the edge - it must exist AND belong to this submission's own
        # scope (both endpoints carry the form's scope_id; the executor's scope
        # guard re-checks, but resolving here gives a clean 404 for a foreign id).
        edge = StatusTransitionRepository(self.db).get_by_id(transition_id)
        if edge is None or edge.entity_type != FORM_SUBMISSION_ENTITY:
            raise SubmissionNotFound()
        from_status = edge.from_status
        to_status = edge.to_status
        if (
            from_status is None
            or to_status is None
            or from_status.scope_id != submission.form_id
            or to_status.scope_id != submission.form_id
            or from_status.tenant_id != tenant_id
        ):
            # Cross-form / cross-tenant edge id - refuse (polymorphic guard).
            raise SubmissionNotFound()
        status_machine.transition(
            self.db,
            FORM_SUBMISSION_ENTITY,
            submission,
            edge.to_status_id,
            user,
            tenant_id=tenant_id,
        )
        self.db.refresh(submission)
        status_by_id = self._status_map(tenant_id, submission.form_id, {submission.status_id})
        fireable = self._fireable_map(tenant_id, submission.form_id, [submission], user)
        return self._submission_row(submission, status_by_id, fireable.get(submission.id))

    # ---- revisions (plan sprint-4/04) ----

    def _scoped_status_active(self, tenant_id: str, form_id: str, status_id: str) -> bool:
        """True only when ``status_id`` RESOLVES within this form's own scope AND
        is active (editable). An unresolvable/foreign id → False (refuse), never
        fail-open - the polymorphic target_id rule via ``get_scope_status``."""
        status = get_scope_status(self.db, FORM_SUBMISSION_ENTITY, tenant_id, form_id, status_id)
        return bool(status and status.is_active)

    def revise(
        self, tenant_id: str, submission_id: str, user: User, *, can_manage: bool
    ) -> FormSubmission:
        """Clone a frozen CURRENT submission into a new Draft revision (R2). The
        prior revision is frozen verbatim (``is_current=False``, status kept);
        the new row shares the ``submission_group_id``, increments
        ``revision_number``, pins the form's CURRENT published version and
        re-enters the scoped graph at its initial (Draft) status. The author
        then edits + resubmits via ``resubmit_revision``."""
        current = self.subs.get_by_id(tenant_id, submission_id)
        if current is None:
            raise SubmissionNotFound()
        # Owner OR submissions.manage (the backend is the real boundary, D19).
        if not (can_manage or (current.user_id and current.user_id == user.id)):
            raise FormRevisionForbidden()
        form = self.get(tenant_id, current.form_id)
        if not form.allow_revisions:
            raise FormRevisionBlocked("Revisions are not enabled for this form.")
        if not current.is_current:
            raise FormRevisionBlocked("Only the current revision can be revised.")
        # Frozen = the current status is NOT active. A status that fails to
        # resolve in-scope is refused (not treated as frozen) - never fail-open.
        if self._scoped_status_active(tenant_id, form.id, current.status_id):
            raise FormRevisionBlocked(
                "This submission is still editable - edit it instead of revising."
            )
        # A revision pins the CURRENT published version + the author re-fills it
        # - both require the form to be live now (an unpublished form's fill
        # surface is offline, so there is nothing to revise against).
        if form.status != FORM_PUBLISHED or not form.current_version_id:
            raise FormRevisionBlocked("This form has no published version to revise against.")
        initial = initial_scope_status(self.db, FORM_SUBMISSION_ENTITY, tenant_id, form.id)
        if initial is None:
            raise FormError("This form's submission machine is misconfigured.")

        # Base the next number on the group's MAX (authoritative), not the loaded
        # row alone, and let the partial-UNIQUE index on (group_id) WHERE
        # is_current reject a concurrent double-revise (→ a clean 409).
        next_rev = self.subs.max_revision_number(tenant_id, current.submission_group_id) + 1
        current.is_current = False
        draft = FormSubmission(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            form_id=form.id,
            submission_group_id=current.submission_group_id,
            revision_number=next_rev,
            is_current=True,
            # Pin the version published NOW - faithful re-render of what the
            # author actually edits this time (R2).
            version_id=form.current_version_id,
            status_id=initial.id,
            user_id=current.user_id,
            subject_type=current.subject_type,
            subject_id=current.subject_id,
            # Deep copy the prior clean answers (file refs by reference - blobs
            # are immutable; changing a file uploads a new key, R4).
            answers_json=json.loads(json.dumps(current.answers_json or {})),
            submitted_at=None,
        )
        self.subs.add(draft)
        try:
            self.db.commit()
        except IntegrityError:
            # The partial-unique index fired - another revise already produced
            # the next current revision for this group (concurrent click/race).
            self.db.rollback()
            raise FormRevisionBlocked("A newer revision already exists for this submission.")
        self.db.refresh(draft)
        return draft

    def resubmit_revision(
        self,
        tenant_id: str,
        submission_id: str,
        user: User,
        answers: Dict[str, Any],
        uploads: Optional[List[UploadedFormFile]] = None,
        *,
        can_manage: bool,
    ) -> FormSubmission:
        """Save edited answers into a Draft revision and fire its Submit edge -
        rides the EXISTING submit/transition pipeline (R3, via the shared
        ``_fire_submit_and_emit``). The row stays the same (one row per
        revision); only the current Draft of a group is editable."""
        submission = self.subs.get_by_id(tenant_id, submission_id)
        if submission is None:
            raise SubmissionNotFound()
        if not (can_manage or (submission.user_id and submission.user_id == user.id)):
            raise FormRevisionForbidden()
        form = self.get(tenant_id, submission.form_id)
        if not submission.is_current or not self._scoped_status_active(
            tenant_id, form.id, submission.status_id
        ):
            raise FormRevisionBlocked("This revision is not open for editing.")

        # Validate against the revision's OWN pinned version (faithful, D9).
        version = self.get_version(tenant_id, form.id, submission.version_id)
        if version is None:
            raise FormRevisionBlocked("The revision's form version is unavailable.")

        field_map = self._field_map(version.definition_json)
        staged, staged_sig, file_errors = self._stage_uploads(field_map, answers, uploads or [])
        clean, errors = validate_submission(version.definition_json, answers)
        visible_file_errors = {k: v for k, v in file_errors.items() if k in clean}
        errors = {**visible_file_errors, **errors}
        if errors:
            raise FormSubmitInvalid(errors)

        if staged or staged_sig:
            self._store_uploads(tenant_id, form.id, submission, clean, staged, staged_sig)
        # Reassign a NEW dict so a plain JSON column tracks the swap (the
        # in-place-mutation gotcha - same as submit()).
        submission.answers_json = json.loads(json.dumps(clean))

        # Unlike the initial submit, a resubmit is an EXPLICIT "submit" action -
        # if the tenant restricted the Submit edge so the move can't happen, the
        # revision would silently stay editable; surface that as a 409 instead.
        if not self._fire_submit_and_emit(tenant_id, form, submission, clean, user):
            self.db.rollback()
            raise FormRevisionBlocked("This revision could not be submitted - the Submit step is restricted.")
        self.db.commit()
        self.db.refresh(submission)
        return submission

    def list_revisions(
        self, tenant_id: str, form_id: str, group_id: str, user: User
    ) -> List[Dict[str, Any]]:
        """The full revision chain for a group, newest first (R3 history)."""
        self.get(tenant_id, form_id)  # tenant ownership check
        rows, _ = self.subs.paginate(
            tenant_id, form_id, page=0, page_size=200, group_id=group_id
        )
        fireable = self._fireable_map(tenant_id, form_id, rows, user)
        status_by_id = self._status_map(tenant_id, form_id, {r.status_id for r in rows})
        return [self._submission_row(r, status_by_id, fireable.get(r.id)) for r in rows]

    def submission_file_key(
        self, tenant_id: str, submission_id: str, field_key: str, index: int
    ) -> Optional[Tuple[str, str, str]]:
        """Resolve (storage_key, mime, filename) for the nth file of a field on a
        submission - tenant-scoped (never resolve a stored id unscoped). None on
        any miss. Files are objects {key,name,mime}; a signature is a bare key
        string (index 0). The route serves these CSP-sandboxed (D12)."""
        submission = self.subs.get_by_id(tenant_id, submission_id)
        if submission is None:
            return None
        value = (submission.answers_json or {}).get(field_key)
        if isinstance(value, list):
            if index < 0 or index >= len(value):
                return None
            entry = value[index]
            if not isinstance(entry, dict) or not entry.get("key"):
                return None
            return entry["key"], entry.get("mime") or "application/octet-stream", entry.get("name") or "file"
        if isinstance(value, str) and value and index == 0:
            # A signature key string.
            return value, "image/png", "signature.png"
        return None

    # ---- scope graph (D15) ----

    def submission_graph(self, tenant_id: str, form_id: str) -> Dict[str, Any]:
        self.get(tenant_id, form_id)  # tenant ownership check
        status_repo = StatusRepository(self.db)
        statuses = status_repo.list_for_entity(
            FORM_SUBMISSION_ENTITY, tenant_id, scope_id=form_id
        )
        edges = StatusTransitionRepository(self.db).list_for_statuses(
            [s.id for s in statuses], tenant_id
        )
        return {
            "statuses": [
                {
                    "id": s.id,
                    "key": s.key,
                    "label": s.label,
                    "color": s.color,
                    "is_initial": s.is_initial,
                    "is_active": s.is_active,
                    "is_terminal": s.is_terminal,
                }
                for s in statuses
            ],
            "transitions": [
                {
                    "id": e.id,
                    "label": e.label,
                    "from_status_id": e.from_status_id,
                    "to_status_id": e.to_status_id,
                }
                for e in edges
            ],
        }

    # ---- CSV exports ----

    def export_forms_csv(
        self,
        tenant_id: str,
        columns: List[str],
        *,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        status_view: Optional[str] = None,
        filter_group: Optional[FilterGroup] = None,
    ) -> str:
        rows, _ = self.list(
            tenant_id,
            page=0,
            page_size=100_000,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            status_view=status_view,
            filter_group=filter_group,
        )
        return _write_csv(columns, rows, lambda r, c: _camel_value(r, c))

    def export_submissions_csv(
        self,
        tenant_id: str,
        form_id: str,
        user: User,
        columns: List[str],
        *,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "desc",
        segment: Optional[str] = None,
    ) -> str:
        rows, _ = self.list_submissions(
            tenant_id,
            form_id,
            user,
            page=0,
            page_size=100_000,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            segment=segment,
        )
        return _write_csv(columns, rows, _submission_column_value)


# ---- CSV helpers (mirror UserService.export_csv shape) ----


def _write_csv(columns: List[str], rows: List[Dict[str, Any]], cell) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([cell(row, c) for c in columns])
    return buffer.getvalue()


def _camel_value(row: Dict[str, Any], column: str) -> str:
    """Map a camelCase export column to its snake row key (the row dict here
    uses snake keys - the schema aliases to camel only at serialization)."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", column).lower()
    value = row.get(snake, row.get(column, ""))
    return "" if value is None else str(value)


def _submission_column_value(row: Dict[str, Any], column: str) -> str:
    """Submissions export: ``answers.<key>`` flattens the answer (objects →
    JSON string), ``respondent`` → user name or Anonymous, else a base column."""
    if column.startswith("answers."):
        key = column[len("answers."):]
        value = (row.get("answers") or {}).get(key)
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return str(value)
    if column == "respondent":
        return row.get("user_name") or "Anonymous"
    return _camel_value(row, column)
