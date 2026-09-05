"""Contacts list filter + sort column map (plan 26 S1, plan §5.2).

The ONE whitelisted column map for `GET /omnichannel/workspaces/{id}/contacts`
AND for segment save-time validation (`validate_filter_tree`) - both apply the
SAME map, so a segment can never store a tree the list would later reject
(AC-CTM-16/17/20). Future consumers (A3 inbox custom views, A4 broadcast
audiences, A9 report grouping) import `CONTACT_FILTER_COLUMNS`/`build_special`
from here directly - never fork a second map.

`customFields.<key>` is the first place a client value reaches a JSON path -
the key is matched against the workspace's REGISTERED fields before it is ever
used (an unregistered or deleted key is a 422, never silently ignored), and the
accessor is SQLAlchemy's typed JSON comparator (`as_string()`/`as_boolean()`) -
bound parameters, no string SQL, portable across Postgres and the SQLite test
engine (pinned by a golden compile test).
"""
from typing import Any, Dict, List

from sqlalchemy import and_, false as sa_false, func, or_, select
from sqlalchemy.orm import Session

from app.models.status import Status as CoreStatus
from app.schemas.filters import FilterCondition
from app.services.filter_translator import ColumnMap, FilterError, SpecialResolver

from ..models import Channel, Contact, ContactChannelIdentity, ContactTagLink
from ..phone import digits_only
from .contact_field_service import ContactFieldService
from .lifecycle_service import stages_for_workspace

# ── system column map (plain columns only - the rest are `special`) ─────────
CONTACT_FILTER_COLUMNS: ColumnMap = {
    "firstName": Contact.first_name,
    "lastName": Contact.last_name,
    "email": Contact.email,
    "language": Contact.language,
    "countryCode": Contact.country_code,
    "priority": Contact.priority,
    "lastMessageAt": Contact.last_message_at,
    "createdAt": Contact.created_at,
}

# A correlated scalar subquery - "sort by the contact's lifecycle stage's own
# `sort_order`" (plan §5.2), never the stage's label/key (a tenant-editable
# display value would make list order silently reshuffle on a rename).
_LIFECYCLE_SORT_ORDER = (
    select(CoreStatus.sort_order)
    .where(CoreStatus.id == Contact.lifecycle_status_id)
    .correlate(Contact)
    .scalar_subquery()
)

CONTACT_SORT_COLUMNS: Dict[str, Any] = {
    "name": func.coalesce(Contact.first_name, "") + " " + func.coalesce(Contact.last_name, ""),
    "phone": Contact.phone,
    "email": Contact.email,
    # Sorted by the raw stored id (documented simplification - resolving the
    # assignee's display NAME would need a cross-schema subquery into core
    # `public.users`; not required by any AC in this slice).
    "assignee": Contact.assigned_user_id,
    "lifecycle": _LIFECYCLE_SORT_ORDER,
    "lastMessageAt": Contact.last_message_at,
    "createdAt": Contact.created_at,
}


def _values(cond: FilterCondition) -> List[Any]:
    v = cond.value
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _generic_text_clause(expr, cond: FilterCondition, *, name: str):
    op, val = cond.operator, cond.value
    if op == "contains":
        return expr.ilike(f"%{val}%")
    if op == "eq":
        return expr == val
    if op == "neq":
        return expr != val
    if op == "in":
        values = val if isinstance(val, list) else [val]
        return expr.in_(values)
    raise FilterError(f"unsupported operator for {name}: {op}")


def _phone_clause(cond: FilterCondition):
    op = cond.operator
    if op not in ("contains", "eq", "neq"):
        raise FilterError(f"unsupported operator for phone: {op}")
    digits = digits_only(str(cond.value)) if cond.value is not None else ""
    if not digits:
        # An empty-digits search/segment value can never legitimately match a
        # phone (mirrors the stitch's own no-match rule) - never a wildcard.
        return sa_false()
    if op == "contains":
        return Contact.phone_digits.ilike(f"%{digits}%")
    clause = Contact.phone_digits == digits
    return clause if op == "eq" else ~clause


def _assignee_clause(cond: FilterCondition):
    if cond.operator not in ("in", "eq"):
        raise FilterError(f"unsupported operator for assignee: {cond.operator}")
    values = _values(cond)
    wants_unassigned = "unassigned" in values
    user_ids = [v for v in values if v != "unassigned"]
    parts = []
    if wants_unassigned:
        parts.append(
            and_(Contact.assigned_user_id.is_(None), Contact.assigned_external_agent_id.is_(None))
        )
    if user_ids:
        parts.append(Contact.assigned_user_id.in_(user_ids))
    if not parts:
        return sa_false()
    return or_(*parts)


def _custom_field_clause(field, cond: FilterCondition):
    accessor = Contact.custom_fields_json[field.key]
    op = cond.operator
    if op in ("is_true", "is_false"):
        return accessor.as_boolean().is_(op == "is_true")
    as_str = accessor.as_string()
    if op == "contains":
        return as_str.ilike(f"%{cond.value}%")
    if op == "eq":
        return as_str == _stringify(cond.value)
    if op == "neq":
        return as_str != _stringify(cond.value)
    if op == "in":
        values = cond.value if isinstance(cond.value, list) else [cond.value]
        return as_str.in_([_stringify(v) for v in values])
    if op == "before":
        return as_str < _stringify(cond.value)
    if op == "after":
        return as_str > _stringify(cond.value)
    if op == "between":
        if not isinstance(cond.value, list) or len(cond.value) < 2:
            raise FilterError("between requires [from, to]")
        return and_(as_str >= _stringify(cond.value[0]), as_str <= _stringify(cond.value[1]))
    raise FilterError(f"unsupported operator for customFields.{field.key}: {op}")


def build_special(db: Session, tenant_id: str, workspace_id: str) -> SpecialResolver:
    """A `SpecialResolver` closed over this ONE workspace's registries
    (custom fields + lifecycle stages) - resolved ONCE per request/validation
    call, not per condition. `customFields.<key>`/`lifecycle` values are
    checked against these registries before any SQL is built (AC-CTM-16/17)."""
    field_registry = {f.key: f for f in ContactFieldService(db).list(workspace_id, tenant_id)}
    stage_by_key = {s.key: s.id for s in stages_for_workspace(db, tenant_id, workspace_id)}

    def _special(cond: FilterCondition):
        field = cond.field
        if field == "name":
            full_name = func.coalesce(Contact.first_name, "") + " " + func.coalesce(Contact.last_name, "")
            return _generic_text_clause(full_name, cond, name="name")
        if field == "phone":
            return _phone_clause(cond)
        if field == "assignee":
            return _assignee_clause(cond)
        if field == "channelType":
            if cond.operator not in ("in", "eq"):
                raise FilterError(f"unsupported operator for channelType: {cond.operator}")
            values = _values(cond)
            if not values:
                return sa_false()
            return (
                db.query(ContactChannelIdentity.id)
                .join(Channel, Channel.id == ContactChannelIdentity.channel_id)
                .filter(
                    ContactChannelIdentity.contact_id == Contact.id,
                    ContactChannelIdentity.tenant_id == tenant_id,
                    Channel.tenant_id == tenant_id,
                    Channel.channel_type.in_(values),
                )
                .exists()
            )
        if field == "lifecycle":
            if cond.operator not in ("in", "eq"):
                raise FilterError(f"unsupported operator for lifecycle: {cond.operator}")
            values = _values(cond)
            ids = [stage_by_key[v] for v in values if v in stage_by_key]
            if not ids:
                return sa_false()
            return Contact.lifecycle_status_id.in_(ids)
        if field == "tags":
            if cond.operator not in ("in", "eq"):
                raise FilterError(f"unsupported operator for tags: {cond.operator}")
            values = _values(cond)
            if not values:
                return sa_false()
            return (
                db.query(ContactTagLink.id)
                .filter(
                    ContactTagLink.contact_id == Contact.id,
                    ContactTagLink.tenant_id == tenant_id,
                    ContactTagLink.tag_id.in_(values),
                )
                .exists()
            )
        if field.startswith("customFields."):
            key = field.split(".", 1)[1]
            registered = field_registry.get(key)
            if registered is None:
                raise FilterError(f"field not filterable: {field}")
            return _custom_field_clause(registered, cond)
        return None

    return _special


def validate_filter_tree(db: Session, tenant_id: str, workspace_id: str, tree) -> None:
    """Save-time gate for a segment's stored filter (AC-CTM-20): a dry-run
    `translate_filter` over the SAME map + `build_special` this module's list
    query uses. Raises `FilterError` naming the offending field; writes
    nothing (the caller has not touched the DB yet)."""
    from app.services.filter_translator import translate_filter

    translate_filter(tree, CONTACT_FILTER_COLUMNS, build_special(db, tenant_id, workspace_id))
