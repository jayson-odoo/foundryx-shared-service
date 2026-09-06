"""``MigrationWriter`` - THE ONE service that writes rows migrated from an
external source (plan 33 §2, D-A6-8). Deliberately NOT `MessageService`, not
`InboundService`, not `ContactAdminService` - those paths publish to Redis,
emit entity events, recompute the customer-service window and bump unread,
every one of which is wrong for a backfill of years-old history. Every write
this class makes is a READ-ONLY-HISTORY row: no `realtime.publish`, no
`emit_entity_event`/`notify_entity_event`, no consumer-webhook fan-out
(D-A6-8) - it reuses `ContactProfileService.patch(emit=False)` (the SAME
`emit=False` seam the contacts importer already uses, plan 26 S3) for exactly
this reason.

S2 only implements `write_contact` (the contacts phase). S3 adds
`write_identity`/`write_message`, S4 adds media + derived events, onto this
SAME class - never a parallel writer.
"""
import logging
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from sqlalchemy.exc import IntegrityError

from ..models import Contact as ContactModel
from ..models import ContactField
from ..phone import digits_only
from ..repositories.contact_repository import ContactRepository
from ..repositories.migration_ref_repository import MigrationRefRepository
from ..respondio.shapes import Contact as SourceContact
from .contact_field_service import (
    FIELD_KEY_RE,
    FIELD_TYPES,
    MAX_FIELDS_PER_WORKSPACE,
    RESERVED_FIELD_KEYS,
    ContactFieldService,
    FieldValidationError,
    _validate_typed_value,
)
from .contact_profile_service import _UNSET, ContactProfileService, ProfilePatchError
from .contact_tag_service import ContactTagService, TagValidationError

logger = logging.getLogger("foundryx.omnichannel.migration")

ENTITY_CONTACT = "contact"


@dataclass
class ContactWriteResult:
    kind: str  # "create" | "update" (merge, D-A6-11)
    contact_id: str
    source_label: str
    fields_created: int = 0
    fields_matched: int = 0
    field_errors: int = 0
    tags_created: int = 0
    tags_matched: int = 0
    assignee_unmatched: bool = False
    lifecycle_unmapped: bool = False
    warnings: List[str] = dataclass_field(default_factory=list)


def _slugify_key(name: str, taken: set) -> str:
    """`ContactField.key` must match `FIELD_KEY_RE` (lowercase-start,
    alnum+underscore, <=40 chars) and avoid `RESERVED_FIELD_KEYS` - a source
    custom-field NAME (free text, e.g. "Plan Tier") is neither. Deterministic,
    collision-avoiding (checked against `taken`, which the caller refreshes
    with every key it creates this run PLUS every key already on the
    workspace's registry - never just this run's cache)."""
    raw = "".join(ch if ch.isalnum() else "_" for ch in name.strip().lower())
    raw = raw.strip("_") or "field"
    if not raw[0].isalpha():
        raw = f"f_{raw}"
    raw = raw[:40]
    candidate = raw
    if candidate in RESERVED_FIELD_KEYS or candidate in taken or not FIELD_KEY_RE.match(candidate):
        suffix = 1
        while True:
            candidate = f"{raw[: 40 - len(str(suffix)) - 1]}_{suffix}"
            if candidate not in RESERVED_FIELD_KEYS and candidate not in taken and FIELD_KEY_RE.match(candidate):
                break
            suffix += 1
            if suffix > 50:  # pragma: no cover - defensive, unreachable in practice
                raise FieldValidationError({"key": "Could not derive a unique field id."})
    return candidate


def _coerce_value(field_type: str, raw: Any) -> Tuple[Any, Optional[str]]:
    """Vendor JSON value -> the python shape `_validate_typed_value` expects
    for `field_type`. respond.io's `custom_fields` values arrive already
    JSON-typed (unlike the CSV importer's raw strings), so this is a much
    lighter coercion than `importers.py _convert_cf_value` - reused where the
    JSON type already matches, stringified otherwise."""
    if field_type == "number":
        if isinstance(raw, bool):
            return None, "must be a number"
        if isinstance(raw, (int, float)):
            return raw, None
        try:
            return float(raw), None
        except (TypeError, ValueError):
            return None, "must be a number"
    if field_type == "checkbox":
        if isinstance(raw, bool):
            return raw, None
        if isinstance(raw, str) and raw.strip().lower() in ("true", "false", "1", "0", "yes", "no"):
            return raw.strip().lower() in ("true", "1", "yes"), None
        return None, "must be true or false"
    # text/email/url/date/time/list all stay string (regex/membership-checked
    # by `_validate_typed_value` itself, same as every other write path).
    return (raw if isinstance(raw, str) else str(raw)), None


class MigrationWriter:
    def __init__(
        self,
        db: Session,
        *,
        tenant_id: str,
        workspace_id: str,
        thread_open_status_id: Optional[str],
        initial_lifecycle_status_id: Optional[str],
        lifecycle_map: Dict[str, str],
        source_field_defs: Dict[str, Dict[str, Any]],
        source: str = "respondio",
        writes_enabled: bool = True,
    ):
        self.db = db
        self.tenant_id = tenant_id
        self.workspace_id = workspace_id
        self.source = source
        # Defensive documentation flag only (plan §2.1) - S2 has no media/
        # realtime/event side effect to gate; the actual "nothing persists"
        # guarantee for a dry run comes from the job handler's per-contact
        # SAVEPOINT rollback (migration_service.py), not a branch in here -
        # keeping ONE write code path for both modes is the whole point of
        # D-A6-14 ("the SAME handler").
        self.writes_enabled = writes_enabled
        self.thread_open_status_id = thread_open_status_id
        self.initial_lifecycle_status_id = initial_lifecycle_status_id
        # sourceLabel(lower) -> targetStatusId, precomputed once by the
        # service from the job's `lifecycleMap` payload (D-A6-12: lifecycle
        # stages are MAPPED, never auto-created).
        self.lifecycle_map = lifecycle_map
        # sourceFieldName(lower) -> {dataType, allowedValues}, precomputed
        # once by the service from `GET /space/custom_field` (AC-MIG-24).
        self.source_field_defs = source_field_defs

        self.refs = MigrationRefRepository(db)
        self.contacts = ContactRepository(db)
        self.fields_service = ContactFieldService(db)
        self.tags_service = ContactTagService(db)
        self.profile = ContactProfileService(db)

        self._field_cache: Optional[Dict[str, Any]] = None  # label(lower) -> ContactField
        self._field_keys_taken: Optional[set] = None

    # ── field registry (lazy, cached for the whole run) ─────────────────────

    def _fields(self) -> Dict[str, Any]:
        if self._field_cache is None:
            rows = self.fields_service.list(self.workspace_id, self.tenant_id)
            self._field_cache = {f.label.strip().lower(): f for f in rows}
            self._field_keys_taken = {f.key for f in rows}
        return self._field_cache

    def _resolve_field(self, name: str, sample_value: Any) -> Tuple[Optional[Any], bool]:
        """Find-or-create a `ContactField` (AC-MIG-24). Deliberately does
        NOT call `ContactFieldService.create` - that method calls
        `self.db.commit()` internally (its normal single-write-per-request
        convention), which would end the per-contact SAVEPOINT the job
        handler wraps around every `write_contact` call and break BOTH the
        dry-run rollback AND the real-mode "one row's failure never touches
        another" isolation. This mirrors the field's own uniqueness/cap/
        list-needs-options rules, add()+flush() only - the caller's own
        transaction boundary decides whether this survives."""
        cache = self._fields()
        existing = cache.get(name.strip().lower())
        if existing is not None:
            return existing, False
        taken = self._field_keys_taken if self._field_keys_taken is not None else set()
        if len(taken) >= MAX_FIELDS_PER_WORKSPACE:
            return None, False
        source_def = self.source_field_defs.get(name.strip().lower()) or {}
        source_type = source_def.get("dataType")
        field_type = source_type if source_type in FIELD_TYPES else "text"
        key = _slugify_key(name, taken)
        if field_type == "list":
            # Prefer the source registry's REAL allowed-values set
            # (AC-MIG-24); fall back to a single-value seed only when the
            # vendor registry carries none (rare - `allowedValues` is
            # optional on `CustomField`) so the field is still creatable.
            allowed = source_def.get("allowedValues")
            options = list(allowed) if allowed else ([str(sample_value)] if sample_value is not None else None)
            if not options:
                return None, False  # a `list` field needs at least one option
        else:
            options = None

        row = ContactField(
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            key=key,
            label=name.strip()[:200] or key,
            type=field_type,
            options_json=options,
            visibility="always",
            sort_order=len(taken),
        )
        try:
            # A SAVEPOINT scoped to just THIS insert (not the caller's own
            # per-contact one) - an IntegrityError recovery must never roll
            # back further than this single field, or it would silently wipe
            # out the rest of the contact's already-flushed work too.
            with self.db.begin_nested():
                self.db.add(row)
                self.db.flush()
        except IntegrityError:
            # A concurrent create landed on the same key first (the DB
            # backstop, same race the real service guards against) - skip
            # this custom field for this contact rather than crash the row.
            return None, False
        cache[name.strip().lower()] = row
        taken.add(row.key)
        self._field_keys_taken = taken
        return row, True

    # ── tags ─────────────────────────────────────────────────────────────────

    def _apply_tags(
        self, contact: ContactModel, source_tags: Optional[List[str]]
    ) -> Tuple[Optional[List[str]], int, int, bool]:
        """Find-or-create via the real `ContactTagService.resolve_or_create_
        by_name` (its own docstring: flush-only, never commits, so it is safe
        inside the job handler's per-contact SAVEPOINT - unlike
        `ContactFieldService.create`, see `_resolve_field`). KNOWN GAP
        (documented, not engineered around - the effort/likelihood tradeoff
        did not justify it for this slice): that method's OWN internal race
        recovery calls a bare `self.db.rollback()` on a genuine concurrent-
        insert IntegrityError, which - like the field bug this class works
        around - would unwind the WHOLE per-contact SAVEPOINT, not just the
        tag insert. Only reachable if two migration jobs (different
        workspaces of the same tenant - `migration_in_progress` already
        forbids two jobs on the SAME workspace) create the identical brand-
        new tag NAME in the same instant; tracked as a backlog follow-up if
        it ever bites in practice."""
        names = [t.strip() for t in (source_tags or []) if t and t.strip()]
        if not names:
            return None, 0, 0, False
        try:
            found = self.tags_service._find_all_by_names(self.workspace_id, self.tenant_id, names)
            resolved_ids = self.tags_service.resolve_or_create_by_name(
                self.workspace_id, self.tenant_id, names
            )
        except TagValidationError as exc:
            logger.info(
                "migration write_contact: tag resolution skipped for contact (tenant=%s ws=%s): %s",
                self.tenant_id, self.workspace_id, exc.message,
            )
            return None, 0, 0, True
        distinct_lower = {n.lower() for n in names}
        matched = len(found)
        created = max(len(distinct_lower) - matched, 0)
        existing_ids = set(self.tags_service.ids_for_contact(contact.id, self.tenant_id))
        union_ids = sorted(existing_ids | set(resolved_ids))
        return union_ids, created, matched, False

    # ── contacts (AC-MIG-23..26) ─────────────────────────────────────────────

    def _find_existing(self, source: SourceContact) -> Tuple[Optional[ContactModel], Optional[str]]:
        """The match ladder (D-A6-11): migration_refs hit, then phone_digits,
        then lowercased email. Returns `(contact_or_None, existing_ref_local_id)`
        - the second value tells the caller whether a NEW ref still needs
        recording (None = no ref existed yet, even if a contact matched via
        phone/email)."""
        external_id = str(source.id)
        local_id = self.refs.local_for_one(
            self.tenant_id, self.workspace_id, self.source, ENTITY_CONTACT, external_id
        )
        if local_id:
            contact = (
                self.db.query(ContactModel)
                .filter(
                    ContactModel.id == local_id,
                    ContactModel.tenant_id == self.tenant_id,
                    ContactModel.workspace_id == self.workspace_id,
                )
                .first()
            )
            if contact is not None:
                return contact, local_id
        digits = digits_only(source.phone) if source.phone else ""
        if digits:
            contact = self.contacts.find_by_phone_digits(digits, self.workspace_id, self.tenant_id)
            if contact is not None:
                return contact, None
        if source.email:
            contact = (
                self.db.query(ContactModel)
                .filter(
                    ContactModel.tenant_id == self.tenant_id,
                    ContactModel.workspace_id == self.workspace_id,
                    func.lower(ContactModel.email) == source.email.strip().lower(),
                )
                .first()
            )
            if contact is not None:
                return contact, None
        return None, None

    def write_contact(self, source: SourceContact) -> ContactWriteResult:
        contact, existing_ref = self._find_existing(source)
        kind = "update" if contact is not None else "create"
        source_label = " ".join(p for p in (source.firstName, source.lastName) if p) or (
            source.phone or source.email or f"contact {source.id}"
        )

        if contact is None:
            contact = ContactModel(
                tenant_id=self.tenant_id,
                workspace_id=self.workspace_id,
                status_id=self.thread_open_status_id,
                priority="MEDIUM",
                migrated_from=self.source,
            )
            self.db.add(contact)
            self.db.flush()

        if existing_ref is None:
            self.refs.record(
                self.tenant_id, self.workspace_id, self.source, ENTITY_CONTACT, str(source.id), contact.id
            )

        result = ContactWriteResult(kind=kind, contact_id=contact.id, source_label=source_label)

        # ── system fields: fill-if-empty (D-A6-11) - ONE rule covers both a
        # brand-new (all-NULL) contact and a merge target's still-empty
        # fields, so create and merge share this exact code path. ─────────
        digits = digits_only(source.phone) if source.phone else ""
        patch_kwargs: Dict[str, Any] = {}
        if not contact.first_name and source.firstName:
            patch_kwargs["first_name"] = source.firstName
        if not contact.last_name and source.lastName:
            patch_kwargs["last_name"] = source.lastName
        if not contact.phone and digits:
            patch_kwargs["phone"] = f"+{digits}"
        if not contact.email and source.email:
            patch_kwargs["email"] = source.email
        if not contact.language and source.language:
            patch_kwargs["language"] = source.language
        if not contact.country_code and source.countryCode:
            patch_kwargs["country_code"] = source.countryCode.upper()

        # ── custom fields (AC-MIG-24): find-or-create the FIELD, then only
        # fill a value the contact does not already carry (merge rule). ────
        clean_custom: Dict[str, Any] = {}
        current_custom = contact.custom_fields_json or {}
        for entry in source.custom_fields or []:
            name = str((entry or {}).get("name") or "").strip()
            raw_value = (entry or {}).get("value")
            if not name or raw_value is None or raw_value == "":
                continue
            cfield, created = self._resolve_field(name, raw_value)
            if cfield is None:
                result.field_errors += 1
                continue
            if created:
                result.fields_created += 1
            else:
                result.fields_matched += 1
            if current_custom.get(cfield.key) is not None:
                continue  # merge rule: never overwrite an existing value
            coerced, err = _coerce_value(cfield.type, raw_value)
            if err:
                result.field_errors += 1
                continue
            err2 = _validate_typed_value(cfield, coerced)
            if err2:
                result.field_errors += 1
                continue
            clean_custom[cfield.key] = coerced

        # ── tags (AC-MIG-25): find-or-create, UNION with whatever the
        # contact already carries - never a replace. ───────────────────────
        union_tag_ids, tags_created, tags_matched, tag_error = self._apply_tags(contact, source.tags)
        result.tags_created = tags_created
        result.tags_matched = tags_matched
        if tag_error:
            result.warnings.append("Tag resolution failed for this contact (workspace tag cap reached).")

        try:
            self.profile.patch(
                contact,
                custom_fields=clean_custom if clean_custom else _UNSET,
                tag_ids=union_tag_ids if union_tag_ids is not None else _UNSET,
                emit=False,  # D-A6-8: this writer never fires an entity event
                **patch_kwargs,
            )
        except ProfilePatchError as exc:  # pragma: no cover - values are pre-validated above
            result.warnings.append(f"Some fields could not be written: {exc.errors}")

        # ── lifecycle (D-A6-12): MAPPED only, direct assignment (never
        # `status_machine.transition` - a bulk backfill has no prior edge to
        # transition FROM, mirrors the contacts importer's D-A2-13 rule), and
        # NEVER moved once the contact already carries a stage. ────────────
        if contact.lifecycle_status_id is None:
            source_label_lc = (source.lifecycle or "").strip().lower()
            mapped = self.lifecycle_map.get(source_label_lc) if source_label_lc else None
            if source_label_lc and mapped is None:
                result.lifecycle_unmapped = True
            contact.lifecycle_status_id = mapped or self.initial_lifecycle_status_id

        # ── assignee (AC-MIG-26): email lookup ONLY, never `userMap`, never
        # creates a user/role/team; never overwrites an existing assignment.
        if contact.assigned_user_id is None and source.assignee and source.assignee.email:
            from app.models.user import User

            row = (
                self.db.query(User.id)
                .filter(
                    User.tenant_id == self.tenant_id,
                    func.lower(User.email) == source.assignee.email.strip().lower(),
                )
                .first()
            )
            if row:
                contact.assigned_user_id = row[0]
            else:
                result.assignee_unmatched = True

        self.db.flush()
        return result
