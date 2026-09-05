"""Contact profile service (plan 25 D5/D11) - the ONE write seam for a
contact's system fields, typed custom fields, and tag set.

Both the internal thread PATCH (`ConversationService.patch_thread`) and the
public gateway PATCH (which itself calls `patch_thread`) route through
`ContactProfileService.patch`, so `customFields`/`tagIds` validation
(AC-CDM-06/07/10) applies identically on every write path - a future importer
(A2) and the workflow `entity.update` whitelist (A5) adopt the same seam.

Validates EVERYTHING first (accumulates a `{field: message}` error map) before
applying any mutation, so a 422 leaves the record untouched. Emits ONE
`omnichannel_contact` `updated` entity event per call with a `changes` diff
keyed `firstName` / `customFields.<key>` / `tags` (AC-CDM-23) - buffered via
`emit_entity_event` (the caller's own `db.commit()` drains it through the
global after-commit hook, so a broken/slow workflow can never fail this
request).
"""
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Contact
from .contact_field_service import ContactFieldService
from .contact_tag_service import ContactTagService, TagValidationError

_UNSET = object()

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
# B8 (plan-25 round-3 codex triage): a cheap BCP-47-SHAPED gate (2-3 letter
# primary subtag + optional hyphenated subtags), NOT full IANA subtag-registry
# validation - that's a backlog item (BL-SS-049). Still bounded by
# MAX_LANGUAGE_LEN below (the regex's repeated group is otherwise unbounded).
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$")
MAX_LANGUAGE_LEN = 16

_WIRE_KEY = {
    "first_name": "firstName",
    "last_name": "lastName",
    "phone": "phone",
    "email": "email",
    "language": "language",
    "country_code": "countryCode",
}


class ProfilePatchError(Exception):
    """Carries a `{field: message}` map - the router turns this into a 422
    `{fieldErrors}` body."""

    def __init__(self, errors: Dict[str, str]):
        super().__init__("Contact profile validation failed")
        self.errors = errors


class ContactProfileService:
    def __init__(self, db: Session):
        self.db = db
        self.fields = ContactFieldService(db)
        self.tags = ContactTagService(db)

    def patch(
        self,
        contact: Contact,
        *,
        first_name: Any = _UNSET,
        last_name: Any = _UNSET,
        phone: Any = _UNSET,
        email: Any = _UNSET,
        language: Any = _UNSET,
        country_code: Any = _UNSET,
        custom_fields: Any = _UNSET,
        tag_ids: Any = _UNSET,
        actor: Optional[Any] = None,
        actor_id: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Validate + apply every provided field. Returns the `changes` diff
        (`{wireKey: {from, to}}`) actually written (empty if nothing changed).
        Raises `ProfilePatchError` with NOTHING written on any violation."""
        errors: Dict[str, str] = {}

        clean_custom: Optional[dict] = None
        if custom_fields is not _UNSET:
            clean_custom, cf_errors = self.fields.validate_values(
                contact.workspace_id, contact.tenant_id, custom_fields
            )
            errors.update(cf_errors)

        clean_tag_ids: Optional[List[str]] = None
        if tag_ids is not _UNSET:
            try:
                clean_tag_ids = self.tags.validate_tag_ids(
                    contact.workspace_id, contact.tenant_id, tag_ids or []
                )
            except TagValidationError as exc:
                errors["tagIds"] = exc.message

        if language is not _UNSET and language is not None:
            if (
                not isinstance(language, str)
                or not (1 <= len(language) <= MAX_LANGUAGE_LEN)
                or not _LANGUAGE_RE.match(language)
            ):
                errors["language"] = (
                    f"language must be a BCP-47 tag of {MAX_LANGUAGE_LEN} characters or fewer."
                )

        if country_code is not _UNSET and country_code is not None:
            if not isinstance(country_code, str) or not _COUNTRY_RE.match(country_code.upper()):
                errors["countryCode"] = "countryCode must be a 2-letter ISO-3166 code."

        if errors:
            raise ProfilePatchError(errors)

        changes: Dict[str, Dict[str, Any]] = {}

        def _apply(attr: str, wire_key: str, new_value: Any) -> None:
            old_value = getattr(contact, attr)
            if new_value != old_value:
                changes[wire_key] = {"from": old_value, "to": new_value}
                setattr(contact, attr, new_value)

        if first_name is not _UNSET:
            _apply("first_name", _WIRE_KEY["first_name"], first_name)
        if last_name is not _UNSET:
            _apply("last_name", _WIRE_KEY["last_name"], last_name)
        if phone is not _UNSET:
            _apply("phone", _WIRE_KEY["phone"], phone)
        if email is not _UNSET:
            _apply("email", _WIRE_KEY["email"], email)
        if language is not _UNSET:
            _apply("language", _WIRE_KEY["language"], language)
        if country_code is not _UNSET:
            normalized = country_code.upper() if country_code else country_code
            _apply("country_code", _WIRE_KEY["country_code"], normalized)

        if clean_custom is not None:
            current = dict(contact.custom_fields_json or {})
            for key, value in clean_custom.items():
                old = current.get(key)
                if value is None:
                    if key in current:
                        changes[f"customFields.{key}"] = {"from": old, "to": None}
                        current.pop(key, None)
                elif old != value:
                    changes[f"customFields.{key}"] = {"from": old, "to": value}
                    current[key] = value
            if any(k.startswith("customFields.") for k in changes):
                contact.custom_fields_json = current

        if clean_tag_ids is not None:
            before_ids = sorted(self.tags.ids_for_contact(contact.id, contact.tenant_id))
            after_ids = sorted(set(clean_tag_ids))
            if before_ids != after_ids:
                self.tags.replace_links(contact, clean_tag_ids)
                changes["tags"] = {"from": before_ids, "to": after_ids}

        if changes:
            from app.workflow_engine.entity_events import emit_entity_event

            emit_entity_event(
                self.db,
                "omnichannel_contact",
                "updated",
                contact,
                tenant_id=contact.tenant_id,
                actor=actor,
                actor_id=actor_id,
                changes=changes,
            )
        return changes
