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

S2 implements `write_contact` (the contacts phase). S3 adds
`write_identity`/`write_message` (+ the timestamp-inference helper and the
per-contact recompute) onto this SAME class. S4 adds media + derived events -
never a parallel writer.
"""
import logging
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from sqlalchemy.exc import IntegrityError

from ..models import Contact as ContactModel
from ..models import ContactChannelIdentity, ContactField, ConversationMessage, QuickReply
from ..phone import digits_only
from ..repositories.contact_repository import ContactRepository
from ..repositories.migration_ref_repository import MigrationRefRepository
from ..respondio.channel_map import derive_external_user_id
from ..respondio.shapes import Contact as SourceContact
from ..respondio.shapes import ContactChannel as SourceContactChannel
from ..respondio.shapes import MessageItem as SourceMessageItem
from . import event_service
from .lifecycle_service import find_stage_by_key_or_label
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
from .migration_media import MediaFetchResult

logger = logging.getLogger("foundryx.omnichannel.migration")

ENTITY_CONTACT = "contact"
ENTITY_IDENTITY = "identity"
ENTITY_MESSAGE = "message"
# S4 additions (AC-MIG-41/44) - `event` is keyed PER CONTACT (one ref covers
# the whole derived-events set for that contact, D-A6-13); `quick_reply` is
# keyed by the LOWERCASED shortcut (there is no vendor id - a CSV row IS the
# record, D-A6-19).
ENTITY_EVENT = "event"
ENTITY_QUICK_REPLY = "quick_reply"

# §5.4 - an unrecognised `attachment.type` still lands as a message (never
# dropped, AC-MIG-35); DOCUMENT covers the vendor's own `file` value.
_ATTACHMENT_TYPE_MAP = {
    "image": "IMAGE",
    "video": "VIDEO",
    "audio": "AUDIO",
    "file": "DOCUMENT",
}

# §5.4 - last `status[].value` -> our `delivery_status` vocabulary.
_DELIVERY_STATUS_MAP = {
    "pending": "QUEUED",
    "sent": "SENT",
    "delivered": "DELIVERED",
    "read": "READ",
    "failed": "FAILED",
}


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


# Review round 1, finding S2 - bounds every vendor epoch this module ever
# converts. Floor: a two-year-old export predates respond.io itself by a
# wide margin - any timestamp before this is treated as garbage, never a
# literal epoch-1970 message sorted to the very top of a contact's history.
# Ceiling is computed fresh (`now() + 24h`) at call time - a corrupt or
# maliciously huge vendor value must never land in `conversation_messages.
# created_at`/`contacts.last_message_at` and reorder the live inbox forever.
_EPOCH_FLOOR = datetime(2009, 1, 1, tzinfo=timezone.utc)
# A value at/above this magnitude is almost certainly MILLISECONDS since
# epoch (a common vendor variation) - seconds-since-1970 does not reach 13
# digits until the year 33658.
_MS_EPOCH_THRESHOLD = 1_000_000_000_000


def epoch_to_dt(epoch_value: Any) -> datetime:
    """Vendor epoch (seconds OR milliseconds, any numeric-ish type) -> an
    aware-UTC `datetime`, NEVER raising (review round 1, finding S2).
    `datetime.fromtimestamp` on a millisecond epoch or a garbage/huge/
    negative value raises `ValueError`/`OverflowError`/`OSError` - every
    caller in this module used to let that propagate straight out of the
    per-contact message phase, failing the WHOLE job over one bad
    timestamp. Detects the millisecond magnitude and divides down; clamps
    the result to `[_EPOCH_FLOOR, now + 24h]` - a value outside that range
    is clamped to the nearer bound rather than rejected, so a contact with
    one bad status timestamp still migrates (with an honest, bounded
    date) instead of erroring out."""
    try:
        seconds = float(epoch_value)
    except (TypeError, ValueError, OverflowError):
        return _EPOCH_FLOOR
    if abs(seconds) >= _MS_EPOCH_THRESHOLD:
        seconds = seconds / 1000.0
    ceiling = datetime.now(timezone.utc) + timedelta(hours=24)
    try:
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return _EPOCH_FLOOR if seconds < 0 else ceiling
    if dt < _EPOCH_FLOOR:
        return _EPOCH_FLOOR
    if dt > ceiling:
        return ceiling
    return dt


def resolve_message_timestamps(
    items: List[SourceMessageItem], fallback: datetime
) -> List[Tuple[datetime, bool]]:
    """D-A6-9 / AC-MIG-34's 3-branch ladder, over ``items`` ALREADY sorted
    ascending by ``messageId`` (thread order always follows the source id,
    never the resolved timestamp - the caller sorts before calling this).
    Returns ``(created_at, inferred)`` aligned 1:1 with ``items``.

    1. explicit - ``min(status[].timestamp)`` when a status array exists.
    2. interpolated - ONLY when there is a nearest EXPLICIT anchor on BOTH
       sides (never a one-sided extrapolation - that is not a "bracket"),
       linear over the anchors' INDEX distance (messageId values are not
       evenly spaced in real time, so index position is the least-wrong
       proxy available with no other signal).
    3. fallback - the source `contact.created_at` (passed in by the caller;
       it is the VENDOR contact's own value, not any local row's).

    A pure function (no DB/IO) so the three branches are unit-testable in
    isolation without a stubbed transport or a session."""
    n = len(items)
    explicit: List[Optional[datetime]] = [None] * n
    for i, item in enumerate(items):
        stamps = [s.timestamp for s in (item.status or []) if s.timestamp is not None]
        if stamps:
            explicit[i] = epoch_to_dt(min(stamps))

    left_idx: List[Optional[int]] = [None] * n
    last_seen: Optional[int] = None
    for i in range(n):
        if explicit[i] is not None:
            last_seen = i
        left_idx[i] = last_seen

    right_idx: List[Optional[int]] = [None] * n
    next_seen: Optional[int] = None
    for i in range(n - 1, -1, -1):
        if explicit[i] is not None:
            next_seen = i
        right_idx[i] = next_seen

    results: List[Tuple[datetime, bool]] = []
    for i in range(n):
        if explicit[i] is not None:
            results.append((explicit[i], False))
            continue
        li, ri = left_idx[i], right_idx[i]
        if li is not None and ri is not None and li != ri:
            lt, rt = explicit[li], explicit[ri]
            frac = (i - li) / (ri - li)
            results.append((lt + (rt - lt) * frac, True))
        else:
            results.append((fallback, True))
    return results


def _map_message_content(item: SourceMessageItem) -> Tuple[str, Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """§5.4's message-type mapping table (AC-MIG-35). Returns
    ``(message_type, body, payload_extra, pending_media)`` - ``pending_media``
    is ``{"url", "attachmentType"}`` when a blob is owed to S4 (D-A6-7: the
    row is written NOW with its caption/text, the blob follows later; no
    fetch happens in S3, plan brief). An unrecognised ``type`` is written as
    TEXT with `payload_json.migration.unmappedType` - never dropped."""
    msg = item.message
    kind = (msg.type or "").strip().lower()

    if kind == "text":
        return "TEXT", msg.text, None, None

    if kind == "attachment":
        attachment = msg.attachment or {}
        attachment_type = str(attachment.get("type") or "").strip().lower()
        message_type = _ATTACHMENT_TYPE_MAP.get(attachment_type, "DOCUMENT")
        url = attachment.get("url")
        pending = {"url": url, "attachmentType": attachment_type} if url else None
        return message_type, None, None, pending

    if kind == "quick_reply":
        payload = {"buttons": msg.replies or []}
        return "INTERACTIVE", msg.title, payload, None

    if kind == "whatsapp_template":
        template = msg.template or {}
        body_text = None
        for component in template.get("components") or []:
            if str((component or {}).get("type") or "").upper() == "BODY":
                body_text = (component or {}).get("text")
                break
        return "TEXT", body_text or template.get("name"), {"template": template}, None

    if kind == "email":
        payload = {
            "email": {
                "subject": msg.subject,
                "cc": msg.cc or [],
                "bcc": msg.bcc or [],
                "attachments": msg.attachments or [],
            }
        }
        # Only the FIRST email attachment is treated as "pending media" (mirrors
        # the whatsapp_template header-only fetch note, §5.4) - S4's own media
        # phase is what actually walks `attachments[]`; documented rather than
        # engineered around for S3, which fetches nothing either way.
        return "TEXT", msg.text, payload, None

    if kind == "custom_payload":
        raw = msg.model_dump(exclude_none=True, exclude={"type"})
        return "TEXT", None, {"custom": raw}, None

    return "TEXT", None, {"migration": {"unmappedType": msg.type}}, None


def _map_delivery_status(item: SourceMessageItem) -> Optional[str]:
    """§5.4 - the LAST element of `status[]` as returned by the vendor (not a
    max-by-timestamp scan - the plan's own wording is positional); no status
    array (the common INBOUND case, F2) leaves this NULL (AC-MIG-36)."""
    if not item.status:
        return None
    return _DELIVERY_STATUS_MAP.get((item.status[-1].value or "").strip().lower())


@dataclass
class IdentityWriteResult:
    kind: str  # "create" | "update" (an existing identity row matched) | "skip"
    reason: Optional[str] = None


@dataclass
class MessageWriteResult:
    message_id: str = ""
    timestamp_inferred: bool = False
    sender_type: str = "CONTACT"


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
        thread_closed_status_id: Optional[str] = None,
        team_map: Optional[Dict[str, str]] = None,
        user_team_by_id: Optional[Dict[str, str]] = None,
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
        # S4 (AC-MIG-41) - the derived `closed` event's `to_value`. Optional
        # only so an existing S2/S3 caller that never reaches the events
        # phase (a contactsOnly run) need not resolve it.
        self.thread_closed_status_id = thread_closed_status_id
        self.initial_lifecycle_status_id = initial_lifecycle_status_id
        # sourceLabel(lower) -> targetStatusId, precomputed once by the
        # service from the job's `lifecycleMap` payload (D-A6-12: lifecycle
        # stages are MAPPED, never auto-created).
        self.lifecycle_map = lifecycle_map
        # sourceFieldName(lower) -> {dataType, allowedValues}, precomputed
        # once by the service from `GET /space/custom_field` (AC-MIG-24).
        self.source_field_defs = source_field_defs
        # S5 (review round 1, finding S5, A8 on `main`) - sourceTeamId(str)
        # -> targetTeamId(str), tenant re-validated by the service
        # (`_resolve_team_map`), and sourceUserId(str) -> sourceTeamId(str)
        # off the space's own user roster (respond.io's `Contact` shape
        # carries no team of its own - only its ASSIGNEE does). Both default
        # to `{}` so an existing caller with no team mapping configured pays
        # nothing extra in `write_contact`.
        self.team_map = team_map or {}
        self.user_team_by_id = user_team_by_id or {}

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
            if mapped is None and source.lifecycle:
                # Fallback resolver (Defect 2 fix, test report round 1) - the
                # SAME canonical key/label matcher the gateway PATCH uses
                # (`find_stage_by_key_or_label`, `lifecycle_service.py`), not
                # a parallel one - map-only, never creates a stage. CSV
                # mode's setup form has no Lifecycle-mapping section at all,
                # so `self.lifecycle_map` is always `{}` for a CSV job; this
                # is the plan's own stated fallback (§5.6: "resolver matches
                # an existing stage by key or label"). Applies to API mode
                # too (a source label that exactly matches a stage but was
                # never explicitly mapped now also resolves) - strictly more
                # correct, not a behavior change any existing test relies on.
                stage = find_stage_by_key_or_label(
                    self.db, self.tenant_id, self.workspace_id, source.lifecycle
                )
                mapped = stage.id if stage is not None else None
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

        # ── team (S5, review round 1 finding S5, A8 on `main`): via the
        # MAPPED source team of the contact's ASSIGNEE - respond.io's
        # contact object carries no team of its own, only its assignee does
        # (`self.user_team_by_id`, built once by the service from `GET
        # /space/user`). Never overwrites an existing assignment; CSV mode's
        # `assignee` is always `None` so this simply no-ops there. ─────────
        if contact.assigned_team_id is None and source.assignee is not None:
            source_team_id = self.user_team_by_id.get(str(source.assignee.id))
            mapped_team_id = self.team_map.get(source_team_id) if source_team_id else None
            if mapped_team_id:
                contact.assigned_team_id = mapped_team_id

        self.db.flush()
        return result

    # ── S3 - channel identities (AC-MIG-30) ─────────────────────────────────

    def write_identity(
        self,
        contact_id: str,
        contact_external_id: str,
        source_channel: SourceContactChannel,
        target_channel_id: str,
        target_channel_type: str,
        contact_phone: Optional[str],
    ) -> IdentityWriteResult:
        """Writes one `contact_channel_identities` row for `contact_id` on
        `target_channel_id` (the job's `channelMap`-resolved target - the
        caller is what decides "no compatible target -> skip", this method
        assumes a real target). SKIPS (never fabricates) when the real
        external id cannot be derived (D-A6-10).

        The `migration_refs` external id is a COMPOSITE
        `<contactExternalId>:<sourceChannel.id>` - NOT `source_channel.id`
        alone. The vendor's own shape (§5.1) makes `ContactChannel.id` look
        identical in structure to `SpaceChannel.id` (same channel, contact-
        scoped metadata attached), which would make a bare channel id
        collide across every contact that has touched that channel and
        silently skip every contact after the first on a re-run. The
        composite key is safe either way (unique per contact regardless of
        whether channel ids turn out to be contact-scoped or space-wide)."""
        external_user_id = derive_external_user_id(target_channel_type, source_channel.meta, contact_phone)
        if not external_user_id:
            return IdentityWriteResult(
                kind="skip",
                reason=f'Could not derive a real identity for channel "{source_channel.name or source_channel.id}" '
                "- skipped rather than write a fabricated id.",
            )

        ref_external_id = f"{contact_external_id}:{source_channel.id}"
        existing_ref = self.refs.local_for_one(
            self.tenant_id, self.workspace_id, self.source, ENTITY_IDENTITY, ref_external_id
        )
        if existing_ref is not None:
            row = (
                self.db.query(ContactChannelIdentity)
                .filter(
                    ContactChannelIdentity.id == existing_ref,
                    ContactChannelIdentity.tenant_id == self.tenant_id,
                )
                .first()
            )
            if row is not None:
                return IdentityWriteResult(kind="update")

        # A LIVE identity may already exist on this exact (channel, external
        # id) pair (e.g. the contact already messaged in through the real
        # channel before this migration ran) - the `uq_identity_channel_
        # external` constraint would reject a second row, so match first and
        # record the ref against the EXISTING row rather than insert.
        # `tenant_id` explicit (review round 1, finding S3) even though the
        # channel itself was tenant-validated upstream - the polymorphic-
        # stored-id pattern this codebase has been bitten by twice already.
        matched = (
            self.db.query(ContactChannelIdentity)
            .filter(
                ContactChannelIdentity.tenant_id == self.tenant_id,
                ContactChannelIdentity.channel_id == target_channel_id,
                ContactChannelIdentity.external_user_id == external_user_id,
            )
            .first()
        )
        if matched is not None:
            if existing_ref is None:
                self.refs.record(
                    self.tenant_id, self.workspace_id, self.source, ENTITY_IDENTITY,
                    ref_external_id, matched.id,
                )
            return IdentityWriteResult(kind="update")

        row = ContactChannelIdentity(
            tenant_id=self.tenant_id,
            contact_id=contact_id,
            channel_id=target_channel_id,
            external_user_id=external_user_id,
            profile_name=source_channel.name,
        )
        try:
            with self.db.begin_nested():
                self.db.add(row)
                self.db.flush()
        except IntegrityError:
            # A concurrent write landed on the same (channel, external id)
            # first (the DB backstop) - re-select and record against it,
            # mirroring `_resolve_field`'s own race recovery.
            self.db.expire_all()
            winner = (
                self.db.query(ContactChannelIdentity)
                .filter(
                    ContactChannelIdentity.tenant_id == self.tenant_id,
                    ContactChannelIdentity.channel_id == target_channel_id,
                    ContactChannelIdentity.external_user_id == external_user_id,
                )
                .first()
            )
            if winner is None:  # pragma: no cover - defensive, should be unreachable
                return IdentityWriteResult(kind="skip", reason="Identity write raced and could not be recovered.")
            self.refs.record(
                self.tenant_id, self.workspace_id, self.source, ENTITY_IDENTITY,
                ref_external_id, winner.id,
            )
            return IdentityWriteResult(kind="update")

        self.refs.record(
            self.tenant_id, self.workspace_id, self.source, ENTITY_IDENTITY, ref_external_id, row.id
        )
        return IdentityWriteResult(kind="create")

    # ── S3 - message history (AC-MIG-32..37) ────────────────────────────────

    def write_message(
        self,
        contact_id: str,
        item: SourceMessageItem,
        created_at: datetime,
        *,
        timestamp_inferred: bool,
        channel_id: Optional[str],
        user_map: Dict[str, str],
    ) -> MessageWriteResult:
        """Writes ONE read-only-history `conversation_messages` row (D-A6-8):
        `external_message_id` stays NULL (D-A6-3 - never the wamid-dedupe
        column), no realtime publish, no entity event, no webhook fan-out -
        this method (like every other write in this class) only ever
        `db.add()`s + `db.flush()`s, it never calls a live-seam function.
        Idempotency (skip-if-already-migrated) is the CALLER's job (a batched
        `already_migrated` check over a whole page/contact, not a per-row DB
        hit here - mirrors the contacts phase's own division of labour)."""
        message_type, body, payload_extra, pending_media = _map_message_content(item)

        payload_json: Dict[str, Any] = dict(payload_extra or {})
        migration_meta: Dict[str, Any] = {}
        if timestamp_inferred:
            migration_meta["timestampInferred"] = True
        if pending_media is not None:
            migration_meta["pendingMedia"] = True
        if migration_meta:
            payload_json["migration"] = {**migration_meta, **(payload_json.get("migration") or {})}

        sender = item.sender
        sender_type = "CONTACT" if item.traffic == "incoming" else "AGENT"
        sender_id: Optional[str] = None
        if sender_type == "AGENT" and sender is not None:
            if sender.source == "user" and sender.userId is not None:
                sender_id = user_map.get(str(sender.userId))
            if sender_id is None:
                # Every OTHER outgoing source (ai_agent/workflow/api/echo/
                # broadcast) - or a `user` whose id did not map - keeps
                # `sender_id` NULL and records which source it really was
                # (AC-MIG-32) so the report/history stays honest.
                migration_source = sender.source if sender is not None else None
                if migration_source:
                    payload_json.setdefault("migration", {})["senderSource"] = migration_source

        row = ConversationMessage(
            tenant_id=self.tenant_id,
            contact_id=contact_id,
            channel_id=channel_id,
            sender_type=sender_type,
            sender_id=sender_id,
            message_type=message_type,
            body=body,
            media_url=(pending_media or {}).get("url"),
            payload_json=payload_json or None,
            external_message_id=None,  # D-A6-3, NEVER the wamid-dedupe column
            delivery_status=_map_delivery_status(item),
            migrated_from=self.source,
            created_at=created_at,
        )
        self.db.add(row)
        self.db.flush()

        self.refs.record(
            self.tenant_id, self.workspace_id, self.source, ENTITY_MESSAGE, str(item.messageId), row.id
        )
        return MessageWriteResult(message_id=row.id, timestamp_inferred=timestamp_inferred, sender_type=sender_type)

    def recompute_contact_timestamps(self, contact: ContactModel) -> None:
        """AC-MIG-37 - exactly ONE recompute per contact, after its ENTIRE
        message phase (all pages) is written. Queries the maxima over
        EXISTING plus migrated rows (a plain aggregate over every
        `conversation_messages` row this contact now has - live rows +
        whatever this run just wrote), never an incremental Python running
        max (which would not survive a crash-resume mid-contact the same
        way). `agent_last_read_at` is set to `last_message_at` so a backfilled
        thread never arrives as a wall of unread; `csw_expires_at` is
        deliberately left untouched (D-A6-8)."""
        last_message_at, last_incoming_at, last_agent_at = (
            self.db.query(
                func.max(ConversationMessage.created_at),
                func.max(
                    case((ConversationMessage.sender_type == "CONTACT", ConversationMessage.created_at))
                ),
                func.max(
                    case((ConversationMessage.sender_type == "AGENT", ConversationMessage.created_at))
                ),
            )
            .filter(
                ConversationMessage.tenant_id == self.tenant_id,
                ConversationMessage.contact_id == contact.id,
            )
            .first()
        )
        contact.last_message_at = last_message_at
        contact.last_incoming_message_at = last_incoming_at
        contact.last_agent_message_at = last_agent_at
        contact.agent_last_read_at = last_message_at
        self.db.flush()

    # ── S4 - media (AC-MIG-39/40) ────────────────────────────────────────────

    def apply_media(self, message: ConversationMessage, result: MediaFetchResult) -> None:
        """A successful `migration_media.fetch_and_store_media` result lands
        on the ALREADY-WRITTEN message row (S3 staged it with `media_url` +
        `payload_json.migration.pendingMedia`) - clears the pending/error
        markers and sets the real `media_key`/`media_mime`/`media_size`.
        Reassigns a FRESH dict for `payload_json` (the JSON-mutation house
        gotcha - an in-place `dict.pop` on the same object is not tracked)."""
        payload = dict(message.payload_json or {})
        migration_meta = dict(payload.get("migration") or {})
        migration_meta.pop("pendingMedia", None)
        migration_meta.pop("mediaError", None)
        if migration_meta:
            payload["migration"] = migration_meta
        else:
            payload.pop("migration", None)
        message.payload_json = payload or None
        message.media_key = result.key
        message.media_mime = result.mime
        message.media_size = result.size
        if result.filename:
            message.media_filename = result.filename
        self.db.flush()

    def record_media_failure(self, message: ConversationMessage, reason: str) -> None:
        """D-A6-7 - the message row survives with its caption/text and the
        ORIGINAL `media_url` untouched; only the failure reason is recorded.
        Deliberately does NOT clear `pendingMedia` - a future re-run of the
        whole migration retries the fetch (BL-SS-124 is the standalone-retry
        follow-up; this slice has no partial-retry mechanism)."""
        payload = dict(message.payload_json or {})
        migration_meta = dict(payload.get("migration") or {})
        migration_meta["mediaError"] = reason
        payload["migration"] = migration_meta
        message.payload_json = payload
        self.db.flush()

    # ── S4 - derived conversation_events (AC-MIG-41/42) ─────────────────────

    def write_derived_events(self, contact: ContactModel, source_contact: SourceContact) -> int:
        """Derives up to 5 `conversation_events` rows from `contact`'s ALREADY
        -migrated message history (never fetched - respond.io has no event/
        assignment-log endpoint, D-A6-13), each carrying the SOURCE timestamp
        (never `now()`, AC-MIG-42) and `payload_json.migration.derived = true`.
        Returns the number of events actually written (0 when this contact
        has no migrated messages at all - nothing to derive a timeline from).

        `reopened`/`snoozed`/`unsnoozed`/`comment_added` are NEVER written -
        the source exposes no data for them (D-A6-13/AC-MIG-42) - which is
        also why there is only ever ONE `first_agent_reply` candidate per
        contact (a single continuous cycle, not the live multi-cycle rule
        `is_first_reply_pending` governs).

        Both aggregates below filter on `ConversationMessage.migrated_from ==
        self.source` (review round 1, finding S7) - the ORIGINAL aggregate
        ran over EVERY message the contact has, migrated or not. On a MERGE
        target with existing live history, that stamped `opened` at the
        live thread's first message (a second, spurious `opened` on a
        thread that already has real events) and could derive
        `first_agent_reply` from live traffic instead of the migrated
        history AC-MIG-41 asks for ("at the first migrated message")."""
        first_at, last_at, first_contact_at = (
            self.db.query(
                func.min(ConversationMessage.created_at),
                func.max(ConversationMessage.created_at),
                func.min(
                    case((ConversationMessage.sender_type == "CONTACT", ConversationMessage.created_at))
                ),
            )
            .filter(
                ConversationMessage.tenant_id == self.tenant_id,
                ConversationMessage.contact_id == contact.id,
                ConversationMessage.migrated_from == self.source,
            )
            .first()
        )
        if first_at is None:
            return 0

        written = 0
        derived_payload = {"migration": {"derived": True}}

        event_service.record(
            self.db, contact, "opened",
            to_value=self.thread_open_status_id, created_at=first_at, payload=dict(derived_payload),
            suppress_workflow_event=True,
        )
        written += 1

        # first_agent_reply: the first AGENT message AT OR AFTER the first
        # CONTACT message - never fabricated when the agent spoke first (no
        # CONTACT message precedes it), which is not a "reply" to anything.
        if first_contact_at is not None:
            first_agent_at = (
                self.db.query(func.min(ConversationMessage.created_at))
                .filter(
                    ConversationMessage.tenant_id == self.tenant_id,
                    ConversationMessage.contact_id == contact.id,
                    ConversationMessage.migrated_from == self.source,
                    ConversationMessage.sender_type == "AGENT",
                    ConversationMessage.created_at >= first_contact_at,
                )
                .scalar()
            )
            if first_agent_at is not None:
                seconds = int((first_agent_at - first_contact_at).total_seconds())
                event_service.record(
                    self.db, contact, "first_agent_reply",
                    created_at=first_agent_at,
                    payload={**derived_payload, "responseSeconds": seconds},
                    suppress_workflow_event=True,
                )
                written += 1

        if (source_contact.status or "").strip().lower() == "close":
            event_service.record(
                self.db, contact, "closed",
                to_value=self.thread_closed_status_id, created_at=last_at, payload=dict(derived_payload),
                suppress_workflow_event=True,
            )
            written += 1

        if contact.assigned_user_id:
            event_service.record(
                self.db, contact, "assigned",
                to_value=contact.assigned_user_id, created_at=last_at, payload=dict(derived_payload),
                suppress_workflow_event=True,
            )
            written += 1

        # lifecycle_changed: only when THIS run's lifecycleMap is what set the
        # contact's CURRENT stage (an equality check against the mapped value
        # - `write_contact` never moves an existing stage, so a stage that
        # does not match what this mapping would produce belongs to an
        # earlier merge/live edit, not this migration).
        source_label_lc = (source_contact.lifecycle or "").strip().lower()
        mapped_status_id = self.lifecycle_map.get(source_label_lc) if source_label_lc else None
        if mapped_status_id is None and source_contact.lifecycle:
            # Defect 2 fix - same fallback resolver as `write_contact` above.
            stage = find_stage_by_key_or_label(
                self.db, self.tenant_id, self.workspace_id, source_contact.lifecycle
            )
            mapped_status_id = stage.id if stage is not None else None
        if mapped_status_id and contact.lifecycle_status_id == mapped_status_id:
            event_service.record(
                self.db, contact, "lifecycle_changed",
                to_value=mapped_status_id, created_at=last_at, payload=dict(derived_payload),
                suppress_workflow_event=True,
            )
            written += 1

        self.db.flush()
        return written

    # ── S4 - quick replies (AC-MIG-44) ───────────────────────────────────────

    def write_quick_reply(self, shortcut: str, body: str) -> str:
        """Find-or-create by SHORTCUT, case-insensitive, within the target
        workspace - `migration_refs` is still the idempotency index (D-A6-3),
        keyed by the lowercased shortcut (there is no vendor id to key on; a
        CSV row IS the record, D-A6-19/AC-MIG-44). Returns "create" | "update"
        (a live quick reply with the same shortcut already existed) |
        "skip" (already migrated on a prior run)."""
        key = shortcut.strip().lower()
        existing_ref = self.refs.local_for_one(
            self.tenant_id, self.workspace_id, self.source, ENTITY_QUICK_REPLY, key
        )
        if existing_ref is not None:
            return "skip"

        matched = (
            self.db.query(QuickReply)
            .filter(
                QuickReply.tenant_id == self.tenant_id,
                QuickReply.workspace_id == self.workspace_id,
                func.lower(QuickReply.shortcut) == key,
            )
            .first()
        )
        if matched is not None:
            self.refs.record(
                self.tenant_id, self.workspace_id, self.source, ENTITY_QUICK_REPLY, key, matched.id
            )
            return "update"

        row = QuickReply(
            tenant_id=self.tenant_id, workspace_id=self.workspace_id,
            shortcut=shortcut.strip(), body=body,
        )
        try:
            with self.db.begin_nested():
                self.db.add(row)
                self.db.flush()
        except IntegrityError:
            self.db.expire_all()
            winner = (
                self.db.query(QuickReply)
                .filter(
                    QuickReply.tenant_id == self.tenant_id,
                    QuickReply.workspace_id == self.workspace_id,
                    func.lower(QuickReply.shortcut) == key,
                )
                .first()
            )
            if winner is None:  # pragma: no cover - defensive, should be unreachable
                return "skip"
            self.refs.record(
                self.tenant_id, self.workspace_id, self.source, ENTITY_QUICK_REPLY, key, winner.id
            )
            return "update"

        self.refs.record(self.tenant_id, self.workspace_id, self.source, ENTITY_QUICK_REPLY, key, row.id)
        return "create"
