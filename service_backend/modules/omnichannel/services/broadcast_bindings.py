"""Broadcast template-variable bindings (plan 29, roadmap A4). Bindings are
STRUCTURED (`{source: 'static', text}` or `{source: 'contactField', field,
fallback}`, D-A4-4) - never a merge-string render, so the server never
renders a tenant string as a template at all.
`template_engine.merge.collect_tokens` is reused only as the guard that a
`static` text carries no `{{ }}` token syntax (anti-SSTI by construction).

S1 shipped save-time `validate_bindings`. S2 (this slice) adds `resolve()` -
turning a binding + a live `Contact` row into the actual Meta parameter
VALUES, with sanitization + the `missing_variable` skip (AC-BRD-34)."""
import re
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Contact
from ..schemas import (
    BROADCAST_FIELD_BINDING_OPTIONS,
    _CUSTOM_FIELD_BINDING_RE,
    BroadcastBindings,
    TemplateBinding,
    TemplateBindingContactField,
    TemplateBindingStatic,
)
from ..services.contact_field_service import ContactFieldService
from ..services.template_send import TemplateShape


class BindingValidationError(Exception):
    """Carries a `{path: message}` map - the router turns this into a 422
    `{fieldErrors}` body (plan §5.1 paths: `bindings.<group>.<index>.
    text|field|fallback`, or `bindings.<group>` for a count mismatch)."""

    def __init__(self, errors: Dict[str, str]):
        super().__init__("Broadcast binding validation failed")
        self.errors = errors


def _validate_static(text: str) -> Optional[str]:
    from app.template_engine.merge import collect_tokens

    if collect_tokens(text or ""):
        return "Static text cannot contain {{ }} merge syntax."
    return None


def _validate_contact_field(field: str, fallback: str, registered_keys: set) -> Optional[str]:
    if field in BROADCAST_FIELD_BINDING_OPTIONS:
        pass
    elif _CUSTOM_FIELD_BINDING_RE.match(field or ""):
        key = field.split(".", 1)[1]
        if key not in registered_keys:
            return f"Unknown contact field: {field}."
    else:
        return f"Unknown contact field: {field}."
    if not (fallback or "").strip():
        return "A fallback value is required for a contact-field binding."
    return None


def _validate_group(
    group_name: str,
    bindings: List,
    expected_count: int,
    registered_keys: set,
    errors: Dict[str, str],
) -> None:
    if len(bindings) != expected_count:
        errors[f"bindings.{group_name}"] = (
            f"This template's {group_name} needs {expected_count} variable(s); "
            f"{len(bindings)} provided."
        )
        return
    for idx, binding in enumerate(bindings):
        prefix = f"bindings.{group_name}.{idx}"
        if isinstance(binding, TemplateBindingStatic):
            msg = _validate_static(binding.text)
            if msg:
                errors[f"{prefix}.text"] = msg
        elif isinstance(binding, TemplateBindingContactField):
            msg = _validate_contact_field(binding.field, binding.fallback, registered_keys)
            if msg:
                # A missing fallback and an unknown field are distinguishable
                # paths so the frontend can highlight the right input.
                key = "fallback" if "fallback" in msg else "field"
                errors[f"{prefix}.{key}"] = msg


def validate_bindings(
    db: Session,
    tenant_id: str,
    workspace_id: str,
    shape: TemplateShape,
    bindings: BroadcastBindings,
) -> None:
    """Raises `BindingValidationError` naming every offending path at once
    (never stops at the first error - a builder wants the full field-error
    map in one round trip)."""
    registered_keys = {f.key for f in ContactFieldService(db).list(workspace_id, tenant_id)}
    errors: Dict[str, str] = {}
    _validate_group("header", bindings.header, shape.header_text_var_count, registered_keys, errors)
    _validate_group("body", bindings.body, shape.body_var_count, registered_keys, errors)
    _validate_group("buttons", bindings.buttons, shape.button_url_var_count, registered_keys, errors)
    if errors:
        raise BindingValidationError(errors)


# ── send-time resolution (plan 29 S2, AC-BRD-34) ────────────────────────────
class SkipMissingVariable(Exception):
    """A `contactField` binding resolved empty AND its (save-time-required)
    fallback was ALSO empty - a state the save-time gate normally makes
    unreachable (D-A4-5), kept only as defence-in-depth. The send job catches
    this and marks the recipient `skipped/missing_variable` (AC-BRD-34) rather
    than emitting a blank Meta parameter."""

    def __init__(self, field: Optional[str] = None):
        super().__init__(f"Binding resolved empty: {field}")
        self.field = field


# Meta rejects a parameter carrying a newline/tab, a run of 4+ spaces, or an
# excessive length - sanitize EVERY emitted parameter (static text included -
# a tenant can still type a stray newline into a static slot).
_CONTROL_WS_RE = re.compile(r"[\n\r\t]")
_LONG_RUN_RE = re.compile(r" {4,}")
MAX_PARAM_LEN = 1024


def _sanitize_param(value: str) -> str:
    value = _CONTROL_WS_RE.sub(" ", value or "")
    value = _LONG_RUN_RE.sub(" ", value)
    value = value.strip()
    if len(value) > MAX_PARAM_LEN:
        value = value[:MAX_PARAM_LEN].rstrip()
    return value


def _field_value(field: str, contact: Contact, lifecycle_label: Optional[str]) -> Optional[str]:
    if field == "firstName":
        return contact.first_name
    if field == "lastName":
        return contact.last_name
    if field == "phone":
        return contact.phone
    if field == "email":
        return contact.email
    if field == "language":
        return contact.language
    if field == "countryCode":
        return contact.country_code
    if field == "lifecycle":
        return lifecycle_label
    if _CUSTOM_FIELD_BINDING_RE.match(field or ""):
        key = field.split(".", 1)[1]
        return (contact.custom_fields_json or {}).get(key)
    return None


def _resolve_one(binding: TemplateBinding, contact: Contact, lifecycle_label: Optional[str]) -> str:
    if isinstance(binding, TemplateBindingStatic):
        value = binding.text or ""
    else:  # TemplateBindingContactField
        raw = (_field_value(binding.field, contact, lifecycle_label) or "").strip()
        value = raw if raw else (binding.fallback or "")
    sanitized = _sanitize_param(value)
    if not sanitized:
        field = binding.field if isinstance(binding, TemplateBindingContactField) else None
        raise SkipMissingVariable(field)
    return sanitized


def resolve(
    bindings: BroadcastBindings, contact: Contact, *, lifecycle_label: Optional[str] = None
) -> Dict[str, List[str]]:
    """Turn a saved `BroadcastBindings` + a live `Contact` into the actual
    Meta parameter VALUES for header/body/buttons - never a rendered tenant
    string (D-A4-4 holds at send time too: this is a whitelisted-field READ +
    fallback + sanitize, not a template engine). Raises `SkipMissingVariable`
    on the FIRST slot that resolves empty with no fallback (AC-BRD-34) - the
    whole recipient is skipped, never a partially-filled send."""
    return {
        "header": [_resolve_one(b, contact, lifecycle_label) for b in bindings.header],
        "body": [_resolve_one(b, contact, lifecycle_label) for b in bindings.body],
        "buttons": [_resolve_one(b, contact, lifecycle_label) for b in bindings.buttons],
    }
