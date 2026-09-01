"""Form submission persistence (plan sprint-3/01) - pure SQLAlchemy, ALWAYS
tenant + form scoped (a submission only exists within one form, owned by one
tenant). Search spans the answer payload (cast to text) and the respondent's
name; the segment filter narrows by the form's OWN scoped status KEY (the graph
is per-form, so we join ``statuses`` scoped to the form, D4).
"""
from typing import List, Optional, Tuple

from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session

from app.models.form import FormSubmission
from app.models.status import Status
from app.models.user import User


class FormSubmissionRepository:
    def __init__(self, db: Session):
        self.db = db

    def paginate(
        self,
        tenant_id: str,
        form_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "desc",
        segment: Optional[str] = None,
        current_only: bool = True,
        group_id: Optional[str] = None,
    ) -> Tuple[List[FormSubmission], int]:
        query = self.db.query(FormSubmission).filter(
            FormSubmission.tenant_id == tenant_id,
            FormSubmission.form_id == form_id,
        )
        if group_id is not None:
            # The revision chain for ONE group - newest revision first, every
            # revision (not just the current). `current_only` is ignored here.
            query = query.filter(FormSubmission.submission_group_id == group_id)
            total = query.count()
            rows = (
                query.order_by(FormSubmission.revision_number.desc())
                .offset(page * page_size)
                .limit(page_size)
                .all()
            )
            return rows, total
        if current_only:
            # Lists default to one row per group - the live revision (R3).
            query = query.filter(FormSubmission.is_current.is_(True))
        if segment and segment != "all":
            # segment = a scope status KEY → resolve that form's status id(s).
            status_ids = [
                row[0]
                for row in self.db.query(Status.id)
                .filter(
                    Status.entity_type == "form_submission",
                    Status.tenant_id == tenant_id,
                    Status.scope_id == form_id,
                    Status.key == segment,
                )
                .all()
            ]
            query = query.filter(FormSubmission.status_id.in_(status_ids or [""]))
        if search:
            like = f"%{search}%"
            # Search answers payload (cast → text) + the respondent's name via
            # an outer join (anonymous submissions have no user).
            query = query.outerjoin(User, User.id == FormSubmission.user_id).filter(
                or_(
                    cast(FormSubmission.answers_json, String).ilike(like),
                    User.name.ilike(like),
                    User.email.ilike(like),
                )
            )
        total = query.count()
        sort_map = {
            "submittedAt": FormSubmission.submitted_at,
            "createdAt": FormSubmission.created_at,
        }
        column = sort_map.get(sort_by or "createdAt", FormSubmission.created_at)
        query = query.order_by(column.desc() if sort_dir != "asc" else column.asc())
        rows = query.offset(page * page_size).limit(page_size).all()
        return rows, total

    def get_by_id(self, tenant_id: str, submission_id: str) -> Optional[FormSubmission]:
        return (
            self.db.query(FormSubmission)
            .filter(
                FormSubmission.id == submission_id,
                FormSubmission.tenant_id == tenant_id,
            )
            .first()
        )

    def add(self, submission: FormSubmission) -> FormSubmission:
        self.db.add(submission)
        self.db.flush()
        return submission

    def count_for_form(self, tenant_id: str, form_id: str) -> int:
        # Caps count logical submissions - one per group (the current revision),
        # so revising never consumes the form's quota (plan sprint-4/04).
        return (
            self.db.query(func.count(FormSubmission.id))
            .filter(
                FormSubmission.tenant_id == tenant_id,
                FormSubmission.form_id == form_id,
                FormSubmission.is_current.is_(True),
            )
            .scalar()
            or 0
        )

    def count_for_user(self, tenant_id: str, form_id: str, user_id: str) -> int:
        """Submissions a given identity already made to this form (D10
        per-user cap - only meaningful for an authenticated respondent).
        Counts current revisions only (a revision is not a new submission)."""
        return (
            self.db.query(func.count(FormSubmission.id))
            .filter(
                FormSubmission.tenant_id == tenant_id,
                FormSubmission.form_id == form_id,
                FormSubmission.user_id == user_id,
                FormSubmission.is_current.is_(True),
            )
            .scalar()
            or 0
        )

    def max_revision_number(self, tenant_id: str, group_id: str) -> int:
        """Highest revision_number in a group - the authoritative base for the
        next revision (never trust the loaded current row's number alone)."""
        return (
            self.db.query(func.max(FormSubmission.revision_number))
            .filter(
                FormSubmission.tenant_id == tenant_id,
                FormSubmission.submission_group_id == group_id,
            )
            .scalar()
            or 0
        )

    def get_current_in_group(
        self, tenant_id: str, group_id: str
    ) -> Optional[FormSubmission]:
        """The live revision of a group - external refs resolve through here."""
        return (
            self.db.query(FormSubmission)
            .filter(
                FormSubmission.tenant_id == tenant_id,
                FormSubmission.submission_group_id == group_id,
                FormSubmission.is_current.is_(True),
            )
            .first()
        )
