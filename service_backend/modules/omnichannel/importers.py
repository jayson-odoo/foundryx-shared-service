"""Contacts CSV importer (plan 26 S3, roadmap A2) - `ImporterDef("omnichannel_
contacts")` on the core import engine (`app/import_engine`).

Two-phase, all-or-nothing, workspace-scoped (`context_keys=("workspaceId",)`).
Reuses the S1/S2 seams throughout - never a second way to write a contact:

  * `phone.digits_only` (the ONE normalization both the create form and the
    stitch use) for phone dedupe/storage.
  * `lifecycle_service.stages_for_workspace` for the lifecycle key-or-label
    resolver (D-A2-13: an IMPORT sets the stage DIRECTLY - a bulk data load,
    like `migrate_records` - never a status_machine transition; a created row
    has no prior stage to transition FROM, and a set-based import cannot run N
    transitions without losing its set-based property).
  * `ContactTagService.resolve_or_create_by_name` for the tag column (find-
    or-create within the workspace tag cap, batched ONCE for the whole
    create+update set - never per-row).
  * `ContactFieldService`'s registry + `_validate_typed_value` for `cf_<key>`
    columns - the SAME typing rule every other write path uses.
  * `ContactProfileService.patch(emit=False)` for the actual field/tag write
    (silent - the import engine's OWN `trigger_automations` gate owns event
    emission via `entity.created`/`entity.updated`, not this module).

Column-set gap (flagged, see the coder handoff; tracked as BL-SS-080): the
core import engine's ``ImporterDef.columns`` is a STATIC tuple resolved once
at process boot, but `cf_<fieldKey>` columns are per-WORKSPACE data unknown
at boot time. This importer uses the new `ImporterDef.dynamic_columns`/
`effective_columns` extension point (additive to `app/import_engine`, S3) -
resolved from the job's own `context_json` (`workspaceId`) wherever a job
exists (`_prepare`, `preview`, `commit_job`). The pre-upload `GET /config`/
`GET /template` screens have no job yet and so still see only the static 10
columns - a future frontend change threading `?context=` through those two
routes closes that gap (BL-SS-080); until then `cf_<fieldKey>` columns are
fully functional once mapped (Test + Import), just not offered by the
"Download template" column picker.
"""
import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.import_engine.coerce import coerce_boolean
from app.import_engine.registry import ImportColumn, ImporterDef, register_importer

from .db import OMNI_SCHEMA  # noqa: F401 - re-exported for symmetry with sibling modules
from .models import Contact
from .phone import digits_only
from .repositories.workspace_repository import WorkspaceRepository
from .services import statuses
from .services.contact_field_service import ContactFieldService, _validate_typed_value
from .services.contact_profile_service import _UNSET, _COUNTRY_RE, _LANGUAGE_RE, MAX_LANGUAGE_LEN, ContactProfileService
from .services.contact_tag_service import ContactTagService
from .services.lifecycle_service import ENTITY_TYPE as LIFECYCLE_ENTITY_TYPE
from .services.lifecycle_service import initial_status_id, stages_for_workspace

ENTITY_TYPE = "omnichannel_contacts"  # plural (AC-CTM-34) - distinct from the
# singular WORKFLOW entity `omnichannel_contact` (S1); `workflow_entity_type`
# below bridges the two so `trigger_automations` fires the RIGHT triggers.
WORKFLOW_ENTITY_TYPE = "omnichannel_contact"
MODULE_NAME = "omnichannel"
logger = logging.getLogger("foundryx.omnichannel.importer")
_PRIORITY_OPTIONS = [{"value": v, "label": v.title()} for v in ("LOW", "MEDIUM", "HIGH", "URGENT")]

CF_PREFIX = "cf_"


# ── validators (mirror ContactProfileService's own gates - single source) ──


def _valid_language(value):
    if value is None:
        return None
    if not (1 <= len(value) <= MAX_LANGUAGE_LEN) or not _LANGUAGE_RE.match(value):
        return f"must be a BCP-47 tag of {MAX_LANGUAGE_LEN} characters or fewer"
    return None


def _valid_country(value):
    if value is None:
        return None
    if not _COUNTRY_RE.match(value.upper()):
        return "must be a 2-letter ISO-3166 code"
    return None


def _valid_phone_digits(value):
    """Runs AFTER `_normalize_phone` (the column's `transform`) - a value that
    still has no digits (`_normalize_phone` only prepends `+` when digits
    exist) is a "no digits" phone, mirroring the create form's own
    `if not digits: errors["phone"]` gate (`ContactAdminService.create`)."""
    if value is None:
        return None
    if not value.startswith("+") or not value[1:].isdigit():
        return "must contain at least one digit"
    return None


def _normalize_phone(value):
    """Transform (applied at coerce time, D6): raw phone text -> `+<digits>`,
    matching `ContactAdminService.create`'s own normalization exactly so an
    imported contact stitches identically to a manually-created one
    (AC-CTM-27's equivalence contract). A value with no digits at all is left
    as-is (empty after the `+`) so the generic `required` check on `phone`
    still fires "required" rather than a normalization crash."""
    digits = digits_only(value)
    return f"+{digits}" if digits else value


def _match_stage(stages, value: Optional[str]):
    """Resolve a `lifecycle` cell (key or label) against a PRE-FETCHED stage
    list (batched once per import run, never per-row - mirrors
    `lifecycle_service.find_stage_by_key_or_label`, which this duplicates
    rather than calls so the whole importer pays exactly ONE stages query)."""
    value = (value or "").strip()
    if not value:
        return None
    for s in stages:
        if s.key == value:
            return s
    lowered = value.lower()
    for s in stages:
        if s.label.strip().lower() == lowered:
            return s
    return None


def _convert_cf_value(field, raw: str):
    """Raw CSV string -> the python value `_validate_typed_value` (the SAME
    typing rule every other contact write path uses) expects. Returns
    `(value, error)`; `error` is the row's error message when the cell can't
    even be coerced to the field's type shape (before the format check)."""
    t = field.type
    if t == "number":
        try:
            return float(raw), None
        except (TypeError, ValueError):
            return None, "must be a number"
    if t == "checkbox":
        value, err = coerce_boolean(raw)
        if err:
            return None, err
        return bool(value), None
    return raw, None  # text/email/url/date/time/list stay string (regex/membership-checked)


def _distinct_cf_keys(columns: Tuple[ImportColumn, ...]) -> List[str]:
    return [c.key[len(CF_PREFIX) :] for c in columns if c.key.startswith(CF_PREFIX)]


# ── dynamic columns (per-workspace registered custom fields) ───────────────


def _cf_import_type(field) -> Tuple[str, Optional[list]]:
    """Derive the import engine's `ImportColumn.type` from the custom
    field's own registered type (finding 12, review round 1) - every
    `cf_*` column used to be typed `"string"` regardless, which offered no
    in-file dropdown for a `list` field and no boolean/decimal coercion for
    `checkbox`/`number`. Returns `(type, options)`.

    `checkbox` -> `boolean` and `list` -> `enum` (options = the SAME list
    `field.options_json` stores, so the core engine's own membership check
    matches `_validate_typed_value`'s later re-check exactly) are safe
    end-to-end: `_convert_cf_value` downstream re-runs `coerce_boolean` on an
    already-bool value idempotently, and `coerce_enum` returns the SAME
    canonical string `_validate_typed_value`'s `list` branch expects.
    `number` -> `decimal` is safe too (`float(Decimal(...))` downstream).

    `date`/`time`/`email`/`url`/`text` stay `"string"` (documented, not
    silently worked around): the import engine's `"date"` `ColumnType`
    coerces to a python `date` OBJECT, but `custom_fields_json` is a JSON
    column expecting `_validate_typed_value`'s `"date"` branch to see a
    `"YYYY-MM-DD"` STRING - a `date` object neither serializes cleanly nor
    passes that `isinstance(value, str)` check. No `ColumnType` in the
    core registry matches the `time`/`email`/`url` formats either; the
    module's own format-specific validators already re-check the raw
    string cell regardless, so keeping `"string"` here is correct, not a
    stopgap."""
    if field.type == "checkbox":
        return "boolean", None
    if field.type == "list":
        return "enum", list(field.options_json or [])
    if field.type == "number":
        return "decimal", None
    return "string", None


def _dynamic_cf_columns(db: Session, tenant_id: str, context: dict) -> List[ImportColumn]:
    workspace_id = context.get("workspaceId")
    if not workspace_id:
        return []
    columns = []
    for f in ContactFieldService(db).list(workspace_id, tenant_id):
        col_type, options = _cf_import_type(f)
        columns.append(ImportColumn(key=f"{CF_PREFIX}{f.key}", label=f.label, type=col_type, options=options))
    return columns


# ── existing_ids (workspace-scoped, plan 26 S3 extension point) ────────────


def _contact_existing_ids_ctx(db: Session, tenant_id: str, ids: List[str], ctx: dict) -> set:
    """Scoped to the job's OWN workspace (not merely the tenant) - an id
    belonging to ANOTHER workspace of this tenant must never resolve as
    "exists" here (the same isolation the manual create/bulk routes already
    enforce for every other contact write path)."""
    workspace_id = ctx.get("workspaceId")
    q = db.query(Contact.id).filter(Contact.tenant_id == tenant_id, Contact.id.in_(ids))
    if workspace_id:
        q = q.filter(Contact.workspace_id == workspace_id)
    return {r[0] for r in q.all()}


# ── validate_prepared (Test AND commit, zero writes) ─────────────────────


def _validate_contact_prepared(
    db: Session, tenant_id: str, prepared: List[dict], context: dict
) -> List[dict]:
    workspace_id = context.get("workspaceId")
    if not workspace_id:
        return [{"row": None, "column": "workspaceId", "message": "Workspace context is required."}]
    # Finding 5: `context.workspaceId` is caller-authored (the import upload
    # body) and was NEVER checked against the caller's own tenant - a job
    # created against another tenant's workspace id would validate/commit
    # rows into it. Tenant-scoped resolve (the polymorphic stored-id rule).
    if WorkspaceRepository(db).get_by_id(workspace_id, tenant_id) is None:
        return [{"row": None, "column": "workspaceId", "message": "Workspace not found."}]

    errors: List[dict] = []

    # ── phone: in-file dup + table dup, CREATE rows only, workspace-scoped,
    # digit-normalized (D-A2-9) - an UPDATE row's phone is silently dropped at
    # commit (AC-CTM-37), so it must never block Test with a false positive
    # (the export→edit→re-import round-trip carries the row's OWN phone).
    seen: Dict[str, int] = {}
    for pr in prepared:
        if pr.get("__op__") != "create":
            continue
        phone = pr.get("phone")
        if not phone:
            continue
        d = phone.lstrip("+")
        if not d:
            continue
        if d in seen:
            errors.append({"row": pr["row"], "column": "phone", "message": "duplicate phone in file"})
        else:
            seen[d] = pr["row"]
    if seen:
        existing = (
            db.query(Contact.phone_digits)
            .filter(
                Contact.tenant_id == tenant_id,
                Contact.workspace_id == workspace_id,
                Contact.phone_digits.in_(seen.keys()),
            )
            .all()
        )
        existing_set = {r[0] for r in existing}
        # Finding 6: mirror `ContactRepository.find_by_phone_digits`'s legacy
        # fallback - a row inserted before this module stamped `phone_digits`
        # (or a pre-existing test fixture) has `phone_digits IS NULL`, and a
        # bare `.in_()` on the indexed column would miss it, letting the
        # importer create a genuine duplicate the manual-create/stitch paths
        # would have caught. Bounded scan (same shape as the repository).
        legacy = (
            db.query(Contact.phone)
            .filter(
                Contact.tenant_id == tenant_id,
                Contact.workspace_id == workspace_id,
                Contact.phone_digits.is_(None),
                Contact.phone.isnot(None),
            )
            .all()
        )
        existing_set.update(digits_only(r[0]) for r in legacy)
        existing_set.discard("")
        for d, row in seen.items():
            if d in existing_set:
                errors.append(
                    {
                        "row": row,
                        "column": "phone",
                        "message": "a contact with this phone already exists in this workspace",
                    }
                )

    # ── lifecycle: key-or-label must resolve within THIS workspace's graph.
    stages = stages_for_workspace(db, tenant_id, workspace_id)
    for pr in prepared:
        lv = pr.get("lifecycle")
        if lv and _match_stage(stages, lv) is None:
            errors.append(
                {"row": pr["row"], "column": "lifecycle", "message": "Unknown lifecycle stage for this workspace."}
            )

    # ── cf_<key>: unknown key / type-format errors (registry-driven).
    fields = {f.key: f for f in ContactFieldService(db).list(workspace_id, tenant_id)}
    for pr in prepared:
        for key, raw in pr.items():
            if not key.startswith(CF_PREFIX) or raw in (None, ""):
                continue
            field_key = key[len(CF_PREFIX) :]
            field = fields.get(field_key)
            if field is None:
                errors.append({"row": pr["row"], "column": key, "message": "Unknown custom field."})
                continue
            converted, err = _convert_cf_value(field, raw)
            if err:
                errors.append({"row": pr["row"], "column": key, "message": err})
                continue
            err2 = _validate_typed_value(field, converted)
            if err2:
                errors.append({"row": pr["row"], "column": key, "message": err2})

    return errors


# ── create_rows / update_rows (set-based DML, commit-time) ─────────────────


def _build_custom_fields(fields: Dict[str, object], row: dict) -> Optional[dict]:
    out: dict = {}
    for key, raw in row.items():
        if not key.startswith(CF_PREFIX) or raw in (None, ""):
            continue
        field = fields.get(key[len(CF_PREFIX) :])
        if field is None:
            continue
        converted, err = _convert_cf_value(field, raw)
        if err:
            continue  # pre-validated at Test/re-validated by _prepare; defensive only
        out[key[len(CF_PREFIX) :]] = converted
    return out or None


def _resolve_tag_map(db: Session, tenant_id: str, workspace_id: str, rows: List[dict]) -> Dict[str, List[str]]:
    """ONE batched `resolve_or_create_by_name` call for every DISTINCT tag name
    across the whole create+update set (never per-row) - `name -> id` map,
    then each row looks up its own names locally."""
    all_names: List[str] = []
    for r in rows:
        raw = (r.get("tags") or "").strip()
        if not raw:
            continue
        for name in raw.split(","):
            name = name.strip()
            if name:
                all_names.append(name)
    if not all_names:
        return {}
    ids = ContactTagService(db).resolve_or_create_by_name(workspace_id, tenant_id, all_names)
    # `resolve_or_create_by_name` de-dupes case-insensitively preserving first-
    # seen order - zip back onto the de-duped name list it actually returned for.
    deduped: List[str] = []
    seen_lower: set = set()
    for name in all_names:
        if name.lower() not in seen_lower:
            seen_lower.add(name.lower())
            deduped.append(name)
    return {name.lower(): tag_id for name, tag_id in zip(deduped, ids)}


def _row_tag_ids(row: dict, name_to_id: Dict[str, str]) -> Optional[List[str]]:
    raw = (row.get("tags") or "").strip()
    if not raw:
        return None
    ids: List[str] = []
    for name in raw.split(","):
        name = name.strip()
        if not name:
            continue
        tid = name_to_id.get(name.lower())
        if tid and tid not in ids:
            ids.append(tid)
    return ids or None


def _create_contacts(db: Session, tenant_id: str, rows: List[dict], ctx: dict) -> List[str]:
    workspace_id = ctx.get("workspaceId")
    fields = {f.key: f for f in ContactFieldService(db).list(workspace_id, tenant_id)}
    stages = stages_for_workspace(db, tenant_id, workspace_id)
    default_initial_id = initial_status_id(db, tenant_id, workspace_id)
    name_to_id = _resolve_tag_map(db, tenant_id, workspace_id, rows)
    thread_open_id = statuses.status_id_for(db, tenant_id, "THREAD", "OPEN")

    ids: List[str] = []
    for r in rows:
        phone = r.get("phone") or ""
        digits = phone.lstrip("+")
        stage = _match_stage(stages, r.get("lifecycle")) if r.get("lifecycle") else None
        lifecycle_status_id = stage.id if stage is not None else default_initial_id

        contact = Contact(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            first_name=r.get("firstName"),
            last_name=r.get("lastName"),
            phone=phone or None,
            phone_digits=digits or None,
            email=r.get("email"),
            status_id=thread_open_id,
            priority=r.get("priority") or "MEDIUM",
            lifecycle_status_id=lifecycle_status_id,
        )
        db.add(contact)
        db.flush()

        custom_fields = _build_custom_fields(fields, r)
        tag_ids = _row_tag_ids(r, name_to_id)
        ContactProfileService(db).patch(
            contact,
            language=r.get("language") if r.get("language") is not None else _UNSET,
            country_code=r.get("countryCode") if r.get("countryCode") is not None else _UNSET,
            custom_fields=custom_fields if custom_fields is not None else _UNSET,
            tag_ids=tag_ids if tag_ids is not None else _UNSET,
            emit=False,  # the import engine's OWN trigger_automations gate fires events
        )
        ids.append(contact.id)
    return ids


def _update_contacts(db: Session, tenant_id: str, rows: List[dict], ctx: dict) -> List[str]:
    """Partial update, id-matched, WORKSPACE-scoped (never cross-workspace,
    even if `existing_ids_ctx` somehow under-scoped - defense in depth).
    `phone` is NEVER written here (AC-CTM-37) even if the file mapped it."""
    workspace_id = ctx.get("workspaceId")
    fields = {f.key: f for f in ContactFieldService(db).list(workspace_id, tenant_id)}
    stages = stages_for_workspace(db, tenant_id, workspace_id)
    name_to_id = _resolve_tag_map(db, tenant_id, workspace_id, rows)

    ids: List[str] = []
    for r in rows:
        contact = (
            db.query(Contact)
            .filter(Contact.id == r["id"], Contact.tenant_id == tenant_id, Contact.workspace_id == workspace_id)
            .first()
        )
        if contact is None:
            # Nit 15 (review round 1): `update_rows` (`app/import_engine/
            # registry.py`) has NO per-row error-return channel - it's typed
            # `-> List[str]`, and `run_commit`'s `job.errors_json` is fed
            # ONLY from the Test-phase `_prepare` errors, never from this
            # function (the core convention `core_importers._update_users`
            # follows too - it doesn't even check existence). A row reaching
            # here with no matching contact means `existing_ids_ctx` somehow
            # under-scoped (should be unreachable - defense in depth); log
            # loudly rather than a bare silent skip so an ops investigation
            # has a trail, since the job's own summary can't surface it.
            logger.warning(
                "contacts import update: row id %s not found in workspace %s tenant %s - skipped",
                r.get("id"), workspace_id, tenant_id,
            )
            continue
        stage = _match_stage(stages, r.get("lifecycle")) if r.get("lifecycle") else None
        custom_fields = _build_custom_fields(fields, r)
        tag_ids = _row_tag_ids(r, name_to_id)
        # Partial update (D5): a cell absent from the file OR left blank is
        # coerced to `None` by the engine regardless of whether the column was
        # even mapped (`_prepare` sets every declared column key on every
        # row) - so "was this field actually sent" is `value is not None`,
        # the SAME convention `core_importers._update_users` uses, never bare
        # key-presence.
        ContactProfileService(db).patch(
            contact,
            first_name=r.get("firstName") if r.get("firstName") is not None else _UNSET,
            last_name=r.get("lastName") if r.get("lastName") is not None else _UNSET,
            email=r.get("email") if r.get("email") is not None else _UNSET,
            language=r.get("language") if r.get("language") is not None else _UNSET,
            country_code=r.get("countryCode") if r.get("countryCode") is not None else _UNSET,
            custom_fields=custom_fields if custom_fields is not None else _UNSET,
            tag_ids=tag_ids if tag_ids is not None else _UNSET,
            emit=False,
        )
        if r.get("priority"):
            contact.priority = r["priority"]
        if stage is not None:
            contact.lifecycle_status_id = stage.id
        ids.append(contact.id)
    return ids


# ── registration ─────────────────────────────────────────────────────────


def register_contacts_importer() -> None:
    """Idempotent (module boot re-registers on every bootstrap, like the rest
    of `register_engine_entities`)."""
    register_importer(
        ImporterDef(
            entity_type=ENTITY_TYPE,
            label="Contact",
            model=Contact,
            columns=(
                ImportColumn(key="id", label="ID", type="string"),
                ImportColumn(
                    key="phone", label="Phone", type="string", required=True,
                    transform=_normalize_phone, validators=(_valid_phone_digits,),
                ),
                ImportColumn(key="firstName", label="First name", type="string"),
                ImportColumn(key="lastName", label="Last name", type="string"),
                ImportColumn(key="email", label="Email", type="string"),
                ImportColumn(key="language", label="Language", type="string", validators=(_valid_language,)),
                ImportColumn(
                    key="countryCode", label="Country", type="string",
                    transform=lambda v: v.upper() if v else v, validators=(_valid_country,),
                ),
                ImportColumn(key="priority", label="Priority", type="enum", options=_PRIORITY_OPTIONS),
                ImportColumn(key="lifecycle", label="Lifecycle", type="string"),
                # `multi_value` is a no-op without a `resolver` (the generic
                # engine only branches on it inside the resolver machinery,
                # which this column deliberately does not use - see
                # `_resolve_tag_map`); the comma-split happens in this
                # module's own hooks instead.
                ImportColumn(key="tags", label="Tags", type="string"),
            ),
            create_rows=_create_contacts,
            update_rows=_update_contacts,
            existing_ids_ctx=_contact_existing_ids_ctx,
            validate_prepared=_validate_contact_prepared,
            dynamic_columns=_dynamic_cf_columns,
            context_keys=("workspaceId",),
            module=MODULE_NAME,
            write_permission="contacts.import",
            workflow_entity_type=WORKFLOW_ENTITY_TYPE,
        )
    )
