"""Contact field registry - typed custom fields per omnichannel workspace
(plan 25 S1).

CRUD + validation ceremony (AC-CDM-01..05): reserved-key + regex + workspace-
scoped case-insensitive uniqueness + cap (100 fields) + list-needs-options at
create; label/description/options/visibility/sort_order editable, key + type
immutable at update (422 if a changed value is sent). Delete strips the key
from every contact's `custom_fields_json` in the SAME workspace (AC-CDM-04) -
Postgres does it in ONE statement (jsonb `-` operator), SQLite (the pytest
suite) falls back to a Python loop; both paths are covered by tests.

`validate_values` (AC-CDM-06) is the seam `ContactProfileService` calls on
every contact write that carries `customFields` - the single place a value is
checked against its field's type.
"""
import re
from datetime import date as date_cls
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import Contact, ContactField

FIELD_KEY_RE = re.compile(r"^[a-z][a-zA-Z0-9_]{0,39}$")
FIELD_TYPES = ("text", "list", "checkbox", "email", "number", "url", "date", "time")
# Mirrors `service_frontend/types/omnichannel.ts RESERVED_CONTACT_FIELD_KEYS`
# plus a few structural wire keys that would otherwise collide.
RESERVED_FIELD_KEYS = {
    "firstName",
    "lastName",
    "phone",
    "email",
    "language",
    "countryCode",
    "tags",
    "lifecycle",
    "profilePic",
    "id",
    "workspaceId",
    "customFields",
}
MAX_FIELDS_PER_WORKSPACE = 100
MAX_TEXT_LEN = 2000

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


class FieldNotFound(Exception):
    pass


class FieldValidationError(Exception):
    """Carries a `{field: message}` map - the router turns this into a 422
    `{fieldErrors}` body."""

    def __init__(self, errors: Dict[str, str]):
        super().__init__("Contact field validation failed")
        self.errors = errors


class ContactFieldService:
    def __init__(self, db: Session):
        self.db = db

    # ── reads ────────────────────────────────────────────────────────────────
    def list(self, workspace_id: str, tenant_id: str) -> List[ContactField]:
        return (
            self.db.query(ContactField)
            .filter(ContactField.tenant_id == tenant_id, ContactField.workspace_id == workspace_id)
            .order_by(ContactField.sort_order.asc(), ContactField.created_at.asc())
            .all()
        )

    def get(self, field_id: str, workspace_id: str, tenant_id: str) -> ContactField:
        row = (
            self.db.query(ContactField)
            .filter(
                ContactField.id == field_id,
                ContactField.workspace_id == workspace_id,
                ContactField.tenant_id == tenant_id,
            )
            .first()
        )
        if row is None:
            raise FieldNotFound()
        return row

    def value_counts(self, workspace_id: str, tenant_id: str) -> Dict[str, int]:
        """`field.key -> number of contacts holding a non-null value` - ONE pass
        over the workspace's contacts regardless of field count (used for the
        list view + the delete-confirmation copy, AC-CDM-31)."""
        rows = (
            self.db.query(Contact.custom_fields_json)
            .filter(Contact.tenant_id == tenant_id, Contact.workspace_id == workspace_id)
            .all()
        )
        counts: Dict[str, int] = {}
        for (cf,) in rows:
            if not isinstance(cf, dict):
                continue
            for key, value in cf.items():
                if value is not None:
                    counts[key] = counts.get(key, 0) + 1
        return counts

    def _find_by_key(self, workspace_id: str, tenant_id: str, key: str) -> Optional[ContactField]:
        from sqlalchemy import func

        return (
            self.db.query(ContactField)
            .filter(
                ContactField.tenant_id == tenant_id,
                ContactField.workspace_id == workspace_id,
                func.lower(ContactField.key) == key.lower(),
            )
            .first()
        )

    # ── writes ───────────────────────────────────────────────────────────────
    def create(self, workspace_id: str, tenant_id: str, payload) -> ContactField:
        errors: Dict[str, str] = {}
        key = (payload.key or "").strip()
        field_type = (payload.type or "").strip()
        label = (payload.label or "").strip()

        if not FIELD_KEY_RE.match(key):
            errors["key"] = (
                "Field ID must start with a lowercase letter and contain only "
                "letters, numbers, and underscores (max 40 characters)."
            )
        elif key in RESERVED_FIELD_KEYS:
            errors["key"] = f"'{key}' is a reserved system field."
        elif self._find_by_key(workspace_id, tenant_id, key) is not None:
            errors["key"] = "A field with this ID already exists."

        if field_type not in FIELD_TYPES:
            errors["type"] = f"type must be one of: {', '.join(FIELD_TYPES)}."

        options = [o for o in (payload.options or []) if isinstance(o, str) and o.strip()]
        if field_type == "list" and not options:
            errors["options"] = "Add at least one option for a list field."

        if not label:
            errors["label"] = "Label is required."

        if errors:
            raise FieldValidationError(errors)

        count = (
            self.db.query(ContactField.id)
            .filter(ContactField.tenant_id == tenant_id, ContactField.workspace_id == workspace_id)
            .count()
        )
        if count >= MAX_FIELDS_PER_WORKSPACE:
            raise FieldValidationError(
                {"key": f"This workspace already has {MAX_FIELDS_PER_WORKSPACE} fields (the maximum)."}
            )

        row = ContactField(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            key=key,
            label=label,
            description=(payload.description or None),
            type=field_type,
            options_json=options if field_type == "list" else None,
            visibility=payload.visibility or "always",
            sort_order=count,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update(self, field_id: str, workspace_id: str, tenant_id: str, payload) -> ContactField:
        row = self.get(field_id, workspace_id, tenant_id)
        sent = payload.model_fields_set
        errors: Dict[str, str] = {}

        if "key" in sent and payload.key is not None and payload.key != row.key:
            errors["key"] = "Field ID cannot be changed after creation."
        if "type" in sent and payload.type is not None and payload.type != row.type:
            errors["type"] = "Field type cannot be changed after creation."

        clean_options: Optional[List[str]] = None
        if "options" in sent:
            clean_options = [o for o in (payload.options or []) if isinstance(o, str) and o.strip()]
            if row.type == "list" and not clean_options:
                errors["options"] = "Add at least one option for a list field."

        if "label" in sent and not (payload.label or "").strip():
            errors["label"] = "Label is required."

        if errors:
            raise FieldValidationError(errors)

        if "label" in sent:
            row.label = payload.label.strip()
        if "description" in sent:
            row.description = payload.description or None
        if "options" in sent:
            row.options_json = clean_options if row.type == "list" else None
        if "visibility" in sent and payload.visibility is not None:
            row.visibility = payload.visibility
        if "sortOrder" in sent and payload.sortOrder is not None:
            row.sort_order = payload.sortOrder

        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, field_id: str, workspace_id: str, tenant_id: str) -> None:
        row = self.get(field_id, workspace_id, tenant_id)
        key = row.key
        self._strip_values(workspace_id, tenant_id, key)
        self.db.delete(row)
        self.db.commit()

    def _strip_values(self, workspace_id: str, tenant_id: str, key: str) -> None:
        """Strip `key` from every contact's `custom_fields_json` in this
        workspace (AC-CDM-04), other workspaces/tenants untouched."""
        if self.db.get_bind().dialect.name == "postgresql":
            self.db.execute(
                text(
                    'UPDATE "app_omnichannel".contacts '
                    "SET custom_fields_json = (custom_fields_json::jsonb - :key)::json "
                    "WHERE tenant_id = :tenant_id AND workspace_id = :workspace_id "
                    "AND custom_fields_json IS NOT NULL "
                    "AND custom_fields_json::jsonb ? :key"
                ),
                {"key": key, "tenant_id": tenant_id, "workspace_id": workspace_id},
            )
            return
        contacts = (
            self.db.query(Contact)
            .filter(Contact.tenant_id == tenant_id, Contact.workspace_id == workspace_id)
            .all()
        )
        for c in contacts:
            if isinstance(c.custom_fields_json, dict) and key in c.custom_fields_json:
                clean = dict(c.custom_fields_json)
                clean.pop(key, None)
                c.custom_fields_json = clean

    # ── value validation (AC-CDM-06) ────────────────────────────────────────
    def validate_values(
        self, workspace_id: str, tenant_id: str, partial: Optional[dict]
    ) -> Tuple[dict, Dict[str, str]]:
        """Validate a partial `{key: value}` patch against the workspace's
        registered fields. Returns `(clean, errors)` - `clean` carries ONLY the
        keys that passed (`None` = clear that key); an unknown key or a value
        that fails its field's type check lands in `errors` keyed
        `customFields.<key>`, and is never written."""
        if partial is None:
            return {}, {}
        if not isinstance(partial, dict):
            return {}, {"customFields": "customFields must be an object."}
        registry = {f.key: f for f in self.list(workspace_id, tenant_id)}
        clean: dict = {}
        errors: Dict[str, str] = {}
        for key, value in partial.items():
            field = registry.get(key)
            if field is None:
                errors[f"customFields.{key}"] = "Unknown custom field."
                continue
            if value is None:
                clean[key] = None
                continue
            err = _validate_typed_value(field, value)
            if err:
                errors[f"customFields.{key}"] = err
            else:
                clean[key] = value
        return clean, errors


def _validate_typed_value(field: ContactField, value) -> Optional[str]:
    t = field.type
    if t == "text":
        if not isinstance(value, str):
            return "Must be text."
        if len(value) > MAX_TEXT_LEN:
            return f"Must be {MAX_TEXT_LEN} characters or fewer."
        return None
    if t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "Must be a number."
        return None
    if t == "checkbox":
        if not isinstance(value, bool):
            return "Must be true or false."
        return None
    if t == "email":
        if not isinstance(value, str) or not _EMAIL_RE.match(value):
            return "Must be a valid email address."
        return None
    if t == "url":
        if not isinstance(value, str) or not _URL_RE.match(value):
            return "Must be a valid URL."
        return None
    if t == "date":
        if not isinstance(value, str) or not _DATE_RE.match(value):
            return "Must be a date in YYYY-MM-DD format."
        try:
            y, m, d = (int(p) for p in value.split("-"))
            date_cls(y, m, d)
        except ValueError:
            return "Must be a valid date."
        return None
    if t == "time":
        if not isinstance(value, str) or not _TIME_RE.match(value):
            return "Must be a time in HH:MM format."
        return None
    if t == "list":
        options = field.options_json or []
        if value not in options:
            return "Must be one of the field's options."
        return None
    return None
