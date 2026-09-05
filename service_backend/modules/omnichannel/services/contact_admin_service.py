"""Contact create + bulk actions (plan 26 S2, roadmap A2, D-A2-4/5).

The ONE write seam for manual creation and the three bulk mutations
(assign/tags/lifecycle). Every write reuses the A1 seams
(`ContactProfileService.patch`, `lifecycle_service.move`) or mirrors the
existing single-assign validation (`ConversationService.patch_thread`'s
native-assignee branch) - this module never re-implements a raw `UPDATE`.

Bulk routes resolve every id tenant + workspace scoped in ONE query (a
missing, cross-tenant, or cross-workspace id all land in the SAME
`not_found` bucket - never an existence oracle, AC-CTM-29/32), then iterate
in bounded batches, each record isolated in its own SAVEPOINT
(`Session.begin_nested()`) so one bad id never discards an earlier
success within the same batch, and each batch is committed before the next
starts so a later batch's failure never discards an earlier batch's
successes (AC-CTM-32). Every mutated contact fans out through the ONE
`ConversationService._publish_contact_updated` (realtime + consumer
webhook, AC-CTM-33) after its batch commits.
"""
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.status_machine import (
    TransitionConditionsNotMet,
    TransitionForbidden,
    TransitionNotAllowed,
)
from app.status_engine.scoped import get_scope_status
from app.workflow_engine.entity_events import emit_entity_event

from ..models import Contact
from ..phone import digits_only
from ..repositories.contact_repository import ContactRepository
from ..schemas import BulkFailure, BulkResult, ContactCreate, ContactListItem
from . import statuses
from .contact_field_service import ContactFieldService
from .contact_list_service import ContactListService
from .contact_profile_service import _UNSET, ContactProfileService, ProfilePatchError
from .contact_tag_service import ContactTagService, TagValidationError
from .conversation_service import ConversationService, InvalidPatch
from .lifecycle_service import ENTITY_TYPE as LIFECYCLE_ENTITY_TYPE
from .lifecycle_service import LifecycleStageNotFound, initial_status_id
from .lifecycle_service import move as lifecycle_move

MAX_BULK_IDS = 500
BULK_BATCH_SIZE = 50
NOT_FOUND_REASON = "not_found"


class ContactCreateError(Exception):
    """Carries a `{field: message}` map - the router turns this into a 422
    `{fieldErrors}` body. Raised BEFORE any row is added to the session, so
    nothing is ever written on a violation (AC-CTM-24/25)."""

    def __init__(self, errors: Dict[str, str]):
        super().__init__("Contact create validation failed")
        self.errors = errors


class BulkValidationError(Exception):
    """Request-level 422 for a bulk route whose shared input (not a
    per-record id) is invalid - today only `.../bulk/tags`' `tagIds`
    (AC-CTM-30: validated ONCE up-front, nothing written on a bad id)."""

    def __init__(self, errors: Dict[str, str]):
        super().__init__("Bulk request validation failed")
        self.errors = errors


def _dedupe(ids: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(ids))


def _chunks(items: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class ContactAdminService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ContactRepository(db)
        self.list_service = ContactListService(db)

    # ── Create (AC-CTM-24..27, 33) ──────────────────────────────────────────
    def create(
        self,
        tenant_id: str,
        workspace_id: str,
        payload: ContactCreate,
        *,
        actor: Optional[User] = None,
        actor_id: Optional[str] = None,
    ) -> ContactListItem:
        errors: Dict[str, str] = {}

        raw_phone = (payload.phone or "").strip()
        digits = digits_only(raw_phone)
        if not digits:
            errors["phone"] = "Phone is required."
        elif self.repo.find_by_phone_digits(digits, workspace_id, tenant_id) is not None:
            errors["phone"] = "A contact with this phone number already exists."

        lifecycle_status_id = payload.lifecycleStatusId
        if lifecycle_status_id:
            if (
                get_scope_status(
                    self.db, LIFECYCLE_ENTITY_TYPE, tenant_id, workspace_id, lifecycle_status_id
                )
                is None
            ):
                errors["lifecycleStatusId"] = "Lifecycle stage not found in this workspace."
        else:
            lifecycle_status_id = initial_status_id(self.db, tenant_id, workspace_id)

        # Pre-validate customFields/tagIds against the SAME registries
        # `ContactProfileService.patch` uses below - a 422 here is raised
        # BEFORE the contact row is ever created (nothing written).
        if payload.customFields is not None:
            _, cf_errors = ContactFieldService(self.db).validate_values(
                workspace_id, tenant_id, payload.customFields
            )
            errors.update(cf_errors)

        if payload.tagIds is not None:
            try:
                ContactTagService(self.db).validate_tag_ids(workspace_id, tenant_id, payload.tagIds)
            except TagValidationError as exc:
                errors[exc.field] = exc.message

        if errors:
            raise ContactCreateError(errors)

        contact = Contact(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            first_name=payload.firstName,
            last_name=payload.lastName,
            phone=f"+{digits}",
            phone_digits=digits,
            email=payload.email,
            status_id=statuses.status_id_for(self.db, tenant_id, "THREAD", "OPEN"),
            priority="MEDIUM",
            lifecycle_status_id=lifecycle_status_id,
        )
        self.db.add(contact)
        self.db.flush()

        # language/countryCode/customFields/tagIds route through the ONE
        # profile-validation seam (AC-CTM-24) - `emit=False` because this
        # create fires exactly ONE `created` event below, never a same-call
        # `updated` for the fields the create request itself populated.
        try:
            ContactProfileService(self.db).patch(
                contact,
                language=payload.language,
                country_code=payload.countryCode,
                custom_fields=payload.customFields if payload.customFields is not None else _UNSET,
                tag_ids=payload.tagIds if payload.tagIds is not None else _UNSET,
                actor=actor,
                actor_id=actor_id,
                emit=False,
            )
        except ProfilePatchError as exc:  # pragma: no cover - pre-validated above
            raise ContactCreateError(exc.errors) from exc

        emit_entity_event(
            self.db,
            "omnichannel_contact",
            "created",
            contact,
            tenant_id=tenant_id,
            actor=actor,
            actor_id=actor_id,
        )
        self.db.commit()
        self.db.refresh(contact)
        item = self.list_service._decorate([contact], tenant_id)[0]
        ConversationService(self.db)._publish_contact_updated(contact, item, tenant_id)
        return item

    # ── Shared bulk plumbing ─────────────────────────────────────────────────
    def _resolve_contacts(
        self, ids: List[str], tenant_id: str, workspace_id: str
    ) -> Dict[str, Contact]:
        if not ids:
            return {}
        rows = (
            self.db.query(Contact)
            .filter(
                Contact.id.in_(ids),
                Contact.tenant_id == tenant_id,
                Contact.workspace_id == workspace_id,
            )
            .all()
        )
        return {c.id: c for c in rows}

    def _fan_out(self, contacts: List[Contact], tenant_id: str) -> None:
        if not contacts:
            return
        items = self.list_service._decorate(contacts, tenant_id)
        conv = ConversationService(self.db)
        for c, item in zip(contacts, items):
            conv._publish_contact_updated(c, item, tenant_id)

    # ── Bulk assign (AC-CTM-29, 32, 33) ──────────────────────────────────────
    def bulk_assign(
        self,
        tenant_id: str,
        workspace_id: str,
        ids: List[str],
        assignee_user_id: Optional[str],
        *,
        actor: Optional[User] = None,
        actor_id: Optional[str] = None,
    ) -> BulkResult:
        ids = _dedupe(ids)
        contacts_by_id = self._resolve_contacts(ids, tenant_id, workspace_id)

        # Assignee validated ONCE (mirrors `ConversationService.patch_thread`'s
        # native-assignee branch, tenant-scoped) - an invalid assignee fails
        # EVERY id in this request with the same reason, rather than a bare
        # request-level 422, since the ids themselves already resolved fine.
        assignee_error: Optional[str] = None
        if assignee_user_id is not None:
            user = (
                self.db.query(User)
                .filter(User.id == assignee_user_id, User.tenant_id == tenant_id)
                .first()
            )
            if user is None:
                assignee_error = "Assignee not found in this tenant."

        ok: List[str] = []
        failed: List[BulkFailure] = []
        changed: List[Contact] = []

        for batch in _chunks(ids, BULK_BATCH_SIZE):
            for cid in batch:
                contact = contacts_by_id.get(cid)
                if contact is None:
                    failed.append(BulkFailure(id=cid, error=NOT_FOUND_REASON))
                    continue
                if assignee_error:
                    failed.append(BulkFailure(id=cid, error=assignee_error))
                    continue
                try:
                    with self.db.begin_nested():
                        contact.assigned_user_id = assignee_user_id
                        contact.assigned_external_agent_id = None
                        self.db.flush()
                except InvalidPatch as exc:  # pragma: no cover - guarded above
                    failed.append(BulkFailure(id=cid, error=exc.message))
                    continue
                ok.append(cid)
                changed.append(contact)
            self.db.commit()

        self._fan_out(changed, tenant_id)
        return BulkResult(ok=ok, failed=failed)

    # ── Bulk tags (AC-CTM-30, 32, 33) ────────────────────────────────────────
    def bulk_tags(
        self,
        tenant_id: str,
        workspace_id: str,
        ids: List[str],
        mode: str,
        tag_ids: List[str],
        *,
        actor: Optional[User] = None,
        actor_id: Optional[str] = None,
    ) -> BulkResult:
        # Validated ONCE up-front (AC-CTM-30) - 422 on any foreign id, nothing
        # written (raised before any contact is even resolved).
        try:
            ContactTagService(self.db).validate_tag_ids(workspace_id, tenant_id, tag_ids)
        except TagValidationError as exc:
            raise BulkValidationError({exc.field: exc.message}) from exc

        ids = _dedupe(ids)
        contacts_by_id = self._resolve_contacts(ids, tenant_id, workspace_id)
        tags_svc = ContactTagService(self.db)
        delta = set(tag_ids)

        ok: List[str] = []
        failed: List[BulkFailure] = []
        changed: List[Contact] = []

        for batch in _chunks(ids, BULK_BATCH_SIZE):
            for cid in batch:
                contact = contacts_by_id.get(cid)
                if contact is None:
                    failed.append(BulkFailure(id=cid, error=NOT_FOUND_REASON))
                    continue
                try:
                    with self.db.begin_nested():
                        current = set(tags_svc.ids_for_contact(cid, tenant_id))
                        new_ids = (current | delta) if mode == "add" else (current - delta)
                        ContactProfileService(self.db).patch(
                            contact,
                            tag_ids=sorted(new_ids),
                            actor=actor,
                            actor_id=actor_id,
                        )
                except ProfilePatchError as exc:  # pragma: no cover - ids pre-validated
                    failed.append(
                        BulkFailure(id=cid, error="; ".join(exc.errors.values()))
                    )
                    continue
                ok.append(cid)
                changed.append(contact)
            self.db.commit()

        self._fan_out(changed, tenant_id)
        return BulkResult(ok=ok, failed=failed)

    # ── Bulk lifecycle (AC-CTM-31, 32, 33) ───────────────────────────────────
    def bulk_lifecycle(
        self,
        tenant_id: str,
        workspace_id: str,
        ids: List[str],
        to_status_id: str,
        *,
        actor: Optional[User] = None,
        actor_id: Optional[str] = None,
    ) -> BulkResult:
        ids = _dedupe(ids)
        contacts_by_id = self._resolve_contacts(ids, tenant_id, workspace_id)

        ok: List[str] = []
        failed: List[BulkFailure] = []
        changed: List[Contact] = []

        for batch in _chunks(ids, BULK_BATCH_SIZE):
            for cid in batch:
                contact = contacts_by_id.get(cid)
                if contact is None:
                    failed.append(BulkFailure(id=cid, error=NOT_FOUND_REASON))
                    continue
                try:
                    with self.db.begin_nested():
                        lifecycle_move(self.db, contact, to_status_id, actor=actor)
                except LifecycleStageNotFound:
                    failed.append(
                        BulkFailure(id=cid, error="Lifecycle stage not found in this workspace.")
                    )
                    continue
                except (TransitionNotAllowed, TransitionForbidden, TransitionConditionsNotMet) as exc:
                    failed.append(BulkFailure(id=cid, error=str(exc)))
                    continue
                ok.append(cid)
                changed.append(contact)
            self.db.commit()

        self._fan_out(changed, tenant_id)
        return BulkResult(ok=ok, failed=failed)
