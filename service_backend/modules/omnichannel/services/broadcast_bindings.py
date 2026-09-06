"""Broadcast template-variable bindings - SAVE-TIME validation only (plan 29
S1). Bindings are STRUCTURED (`{source: 'static', text}` or
`{source: 'contactField', field, fallback}`, D-A4-4) - never a merge-string
render, so the server never renders a tenant string as a template at all.
`template_engine.merge.collect_tokens` is reused only as the guard that a
`static` text carries no `{{ }}` token syntax (anti-SSTI by construction).

`resolve()` (turning a binding + a live `Contact` row into the actual Meta
parameter values, with sanitization + the `missing_variable` skip) is S2's
job (the send path) - this module intentionally stops at validation.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..schemas import (
    BROADCAST_FIELD_BINDING_OPTIONS,
    _CUSTOM_FIELD_BINDING_RE,
    BroadcastBindings,
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
