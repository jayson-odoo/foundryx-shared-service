"""Per-product delivery mapping (plan 64 AC-64-24/35/61; owner 15 Nov: "the
mapping needs to be configurable ... sorento endpoint and ecohub endpoint sure
different").

- The product publishes its own lead fields (``PUT /fields``): the targets.
- Each source keeps a field map ``{formId | "*": {questionKey: targetKey}}``;
  ``"*"`` applies to every form, a form's own map wins over it. Saving a map
  for a form clears that form's "Map fields" notice.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..mapping import ANY_FORM, DEFAULT_FIELDS, FIELD_TYPES
from ..models import LcConsumerField, LcSource

MAX_FIELDS = 50
MAX_MAP_ENTRIES = 100
_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_QUESTION_RE = re.compile(r"^[^\x00-\x1f]{1,200}$")
_FORM_RE = re.compile(r"^(\*|[0-9A-Za-z_-]{1,64})$")


class FieldError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def list_fields(db: Session, tenant_id: str) -> List[LcConsumerField]:
    return (
        db.query(LcConsumerField)
        .filter(LcConsumerField.tenant_id == tenant_id)
        .order_by(LcConsumerField.sort.asc(), LcConsumerField.key.asc())
        .all()
    )


def targets(db: Session, tenant_id: str) -> List[Tuple[str, str]]:
    """The product's ``(key, type)`` targets, or the defaults."""
    rows = list_fields(db, tenant_id)
    return [(r.key, r.type) for r in rows] if rows else list(DEFAULT_FIELDS)


def set_fields(db: Session, tenant_id: str, items: List[Dict[str, Any]]) -> List[LcConsumerField]:
    """Replace the product's field list. ``[]`` = back to the defaults."""
    if len(items) > MAX_FIELDS:
        raise FieldError(422, "invalid_fields", f"At most {MAX_FIELDS} fields.")
    seen = set()
    clean: List[LcConsumerField] = []
    for n, item in enumerate(items):
        key = str(item.get("key") or "")
        typ = str(item.get("type") or "text")
        label = str(item.get("label") or key).strip()[:200]
        if not _KEY_RE.match(key):
            raise FieldError(422, "invalid_fields", f"Field {n + 1}: key must be letters, digits or _ and start with a letter.")
        if key in seen:
            raise FieldError(422, "invalid_fields", f"Field key {key} is listed twice.")
        if typ not in FIELD_TYPES:
            raise FieldError(422, "invalid_fields", f"Field {key}: type must be one of {', '.join(FIELD_TYPES)}.")
        seen.add(key)
        clean.append(LcConsumerField(tenant_id=tenant_id, key=key, label=label or key, type=typ, sort=n))
    db.query(LcConsumerField).filter(LcConsumerField.tenant_id == tenant_id).delete()
    db.add_all(clean)
    db.flush()
    _prune_field_maps(db, tenant_id, {k for k, _t in targets(db, tenant_id)})
    db.commit()
    return list_fields(db, tenant_id)


def _prune_field_maps(db: Session, tenant_id: str, allowed: set) -> None:
    """Drop map entries whose target is no longer one of the product's fields,
    so a map never points at a removed field (the lead would silently lose that
    answer). A form left with no entry loses its map. Same transaction as the
    field list change."""
    for source in db.query(LcSource).filter(LcSource.tenant_id == tenant_id).all():
        current = source.field_map_json or {}
        pruned = {}
        for form_id, mapping in current.items():
            kept = {q: t for q, t in (mapping or {}).items() if t in allowed}
            if kept:
                pruned[form_id] = kept
        if pruned != current:
            source.field_map_json = pruned  # a fresh dict: in-place JSON edits are not tracked


def _source(db: Session, tenant_id: str, source_id: str) -> LcSource:
    row = db.query(LcSource).filter(LcSource.id == source_id, LcSource.tenant_id == tenant_id).first()
    if row is None:
        raise FieldError(404, "source_not_found", "Source not found.")
    return row


def set_field_map(
    db: Session, tenant_id: str, source_id: str, form_id: str, mapping: Dict[str, Optional[str]]
) -> LcSource:
    """Set one form's map (``formId`` ``"*"`` = every form). A target must be
    one of the product's fields; an empty map removes that form's map."""
    form_id = str(form_id or "")
    if not _FORM_RE.match(form_id):
        raise FieldError(422, "invalid_field_map", "formId must be a form id or \"*\".")
    if not isinstance(mapping, dict) or len(mapping) > MAX_MAP_ENTRIES:
        raise FieldError(422, "invalid_field_map", f"map must be an object of at most {MAX_MAP_ENTRIES} entries.")
    allowed = {k for k, _t in targets(db, tenant_id)}
    clean: Dict[str, str] = {}
    for question, target in mapping.items():
        if not isinstance(question, str) or not _QUESTION_RE.match(question):
            raise FieldError(422, "invalid_field_map", "Question keys must be short text.")
        if target in (None, ""):
            continue
        if target not in allowed:
            raise FieldError(422, "invalid_field_map", f"{target} is not one of your lead fields.")
        clean[question] = target
    row = _source(db, tenant_id, source_id)
    field_map = dict(row.field_map_json or {})
    if clean:
        field_map[form_id] = clean
    else:
        field_map.pop(form_id, None)
    row.field_map_json = field_map
    notices = dict(row.needs_mapping_json or {})
    if form_id == ANY_FORM and clean:
        notices = {}
    else:
        notices.pop(form_id, None)
    row.needs_mapping_json = notices or None
    db.commit()
    db.refresh(row)
    return row
