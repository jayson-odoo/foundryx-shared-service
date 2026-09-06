"""Broadcast builder CRUD + validation orchestration (plan 29 S1, roadmap A4).

Router -> Service -> Repository; every write is tenant + workspace scoped.
The audience is stored as CONFIGURATION only (D-A4-2) - resolution/snapshot
lives in `broadcast_audience.py`. Bindings are structured slots (D-A4-4) -
validated here via `broadcast_bindings.validate_bindings`, never rendered.
Sending (`/send`, `/cancel`, `/test-send`) is S2 - this service only manages
the DRAFT builder lifecycle (create/update/delete/duplicate) plus reads.
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.filters import FilterCondition, FilterGroup
from app.services.filter_translator import FilterError
from app.workflow_engine.entity_events import emit_entity_event

from ..models import Broadcast, Channel, Contact, ContactSegment, Status, WhatsappTemplate
from ..repositories.broadcast_repository import BroadcastRepository
from ..schemas import (
    BroadcastAudienceIn,
    BroadcastAudienceOut,
    BroadcastBindings,
    BroadcastCounts,
    BroadcastCreate,
    BroadcastItem,
    BroadcastRecipientItem,
    BroadcastUpdate,
)
from .broadcast_audience import preview_count as _preview_count
from .broadcast_bindings import BindingValidationError, validate_bindings
from .contact_filters import validate_filter_tree
from .contact_segment_service import ContactSegmentService, SegmentNotFound
from .template_send import analyze_template

MAX_NAME_LEN = 200
# Draft is always editable; a schedule-only patch is also allowed while the
# broadcast is already SCHEDULED (AC-BRD-21) - S2 owns the actual transition
# into SCHEDULED/SENDING via `/send`.
_EDITABLE_STATUSES = {"DRAFT"}
_SCHEDULE_ONLY_EDITABLE_STATUSES = {"DRAFT", "SCHEDULED"}


class BroadcastNotFound(Exception):
    pass


class BroadcastValidationError(Exception):
    """Carries a `{path: message}` map - the router turns this into a 422
    `{fieldErrors}` body (plan §5.1 paths)."""

    def __init__(self, errors: Dict[str, str]):
        super().__init__("Broadcast validation failed")
        self.errors = errors


class BroadcastStatusConflict(Exception):
    """Typed 409 reason (plan §5.1): `broadcast_not_editable` |
    `broadcast_not_cancellable` | `broadcast_already_sending`."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class BroadcastService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = BroadcastRepository(db)

    # ── status lookups ───────────────────────────────────────────────────────
    def _status_maps(self, tenant_id: str) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
        rows = (
            self.db.query(Status)
            .filter(Status.tenant_id == tenant_id, Status.scope == "BROADCAST")
            .all()
        )
        key_to_id = {r.key: r.id for r in rows}
        id_to_key = {r.id: r.key for r in rows}
        id_to_label = {r.id: r.label for r in rows}
        return key_to_id, id_to_key, id_to_label

    # ── batched name resolution (polymorphic stored-id rule) ────────────────
    def _user_names(self, user_ids: List[Optional[str]], tenant_id: str) -> Dict[str, str]:
        ids = [u for u in set(user_ids) if u]
        if not ids:
            return {}
        rows = self.db.query(User).filter(User.tenant_id == tenant_id, User.id.in_(ids)).all()
        return {u.id: (u.name or u.email) for u in rows}

    def _hydrate(
        self, rows: List[Broadcast], tenant_id: str, id_to_key: Dict[str, str], id_to_label: Dict[str, str]
    ) -> List[BroadcastItem]:
        if not rows:
            return []
        channel_ids = {r.channel_id for r in rows}
        segment_ids = {r.audience_segment_id for r in rows if r.audience_segment_id}
        user_ids = [r.created_by_user_id for r in rows]

        channel_names = {
            c.id: c.name
            for c in self.db.query(Channel).filter(Channel.tenant_id == tenant_id, Channel.id.in_(channel_ids)).all()
        } if channel_ids else {}
        segment_names = {
            s.id: s.name
            for s in self.db.query(ContactSegment)
            .filter(ContactSegment.tenant_id == tenant_id, ContactSegment.id.in_(segment_ids))
            .all()
        } if segment_ids else {}
        user_names = self._user_names(user_ids, tenant_id)

        items: List[BroadcastItem] = []
        for r in rows:
            audience = BroadcastAudienceOut(
                kind=r.audience_kind,
                segmentId=r.audience_segment_id,
                segmentName=segment_names.get(r.audience_segment_id) if r.audience_segment_id else None,
                filter=FilterGroup.model_validate(r.audience_filter_json) if r.audience_filter_json else None,
                contactIds=r.audience_contact_ids_json,
            )
            bindings_json = r.bindings_json or {"header": [], "body": [], "buttons": []}
            items.append(
                BroadcastItem(
                    id=r.id,
                    workspaceId=r.workspace_id,
                    name=r.name,
                    labels=r.labels_json or [],
                    channelId=r.channel_id,
                    channelName=channel_names.get(r.channel_id, ""),
                    audience=audience,
                    templateId=r.template_id,
                    templateName=r.template_name,
                    templateLanguage=r.template_language,
                    bindings=BroadcastBindings.model_validate(bindings_json),
                    status=id_to_key.get(r.status_id, "DRAFT"),
                    statusLabel=id_to_label.get(r.status_id, "Draft"),
                    scheduledAt=r.scheduled_at,
                    startedAt=r.started_at,
                    finishedAt=r.finished_at,
                    counts=BroadcastCounts(
                        total=r.total_count, sent=r.sent_count, delivered=r.delivered_count,
                        read=r.read_count, failed=r.failed_count, skipped=r.skipped_count,
                    ),
                    jobId=r.job_id,
                    error=r.error,
                    createdByUserId=r.created_by_user_id,
                    createdByName=user_names.get(r.created_by_user_id) if r.created_by_user_id else None,
                    createdAt=r.created_at,
                    updatedAt=r.updated_at,
                )
            )
        return items

    def _row_or_404(self, broadcast_id: str, tenant_id: str, workspace_id: str) -> Broadcast:
        row = self.repo.get(broadcast_id, tenant_id, workspace_id)
        if row is None:
            raise BroadcastNotFound()
        return row

    # ── reads ────────────────────────────────────────────────────────────────
    def list(
        self,
        tenant_id: str,
        workspace_id: str,
        *,
        search: Optional[str] = None,
        filter_group: Optional[FilterGroup] = None,
        segment: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "desc",
        page: int = 0,
        page_size: int = 25,
    ) -> Tuple[List[BroadcastItem], int]:
        """Raises `FilterError` (router -> 422, unknown field/sort key or an
        unknown status segment)."""
        key_to_id, id_to_key, id_to_label = self._status_maps(tenant_id)
        combined = filter_group
        if segment and segment != "all":
            if segment not in key_to_id:
                raise FilterError(f'Unknown segment "{segment}".')
            seg_cond = FilterCondition(kind="condition", field="status", operator="eq", value=segment)
            combined = (
                FilterGroup(kind="group", combinator="and", rules=[seg_cond, filter_group])
                if filter_group is not None
                else FilterGroup(kind="group", combinator="and", rules=[seg_cond])
            )
        rows, total = self.repo.list(
            tenant_id, workspace_id, search=search, filter_group=combined, status_key_to_id=key_to_id,
            sort_by=sort_by, sort_dir=sort_dir, page=page, page_size=page_size,
        )
        return self._hydrate(rows, tenant_id, id_to_key, id_to_label), total

    def get(self, broadcast_id: str, tenant_id: str, workspace_id: str) -> BroadcastItem:
        row = self._row_or_404(broadcast_id, tenant_id, workspace_id)
        _, id_to_key, id_to_label = self._status_maps(tenant_id)
        return self._hydrate([row], tenant_id, id_to_key, id_to_label)[0]

    def recipients(
        self,
        broadcast_id: str,
        tenant_id: str,
        workspace_id: str,
        *,
        state: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 0,
        page_size: int = 25,
    ) -> Tuple[List[BroadcastRecipientItem], int]:
        self._row_or_404(broadcast_id, tenant_id, workspace_id)
        pairs, total = self.repo.recipients_page(
            tenant_id, broadcast_id, state=state, search=search, page=page, page_size=page_size
        )
        items = [
            BroadcastRecipientItem(
                id=r.id,
                contactId=c.id,
                contactName=(f"{c.first_name or ''} {c.last_name or ''}".strip() or c.phone or "Unknown"),
                phone=c.phone,
                state=r.state,
                skipReason=r.skip_reason,
                errorCode=r.error_code,
                errorText=r.error_text,
                messageId=r.message_id,
                attemptedAt=r.attempted_at,
            )
            for r, c in pairs
        ]
        return items, total

    def audience_preview(self, tenant_id: str, workspace_id: str, audience: BroadcastAudienceIn) -> int:
        """Raises `SegmentNotFound` (router -> 404) / `FilterError` (router ->
        422) exactly like every other A2 consumer of `ContactListService`."""
        return _preview_count(
            self.db, tenant_id, workspace_id,
            kind=audience.kind, segment_id=audience.segmentId,
            filter_group=audience.filter, contact_ids=audience.contactIds,
        )

    # ── audience validation (shared by create/update) ───────────────────────
    def _validate_audience(
        self, tenant_id: str, workspace_id: str, audience: BroadcastAudienceIn, errors: Dict[str, str]
    ) -> None:
        kind = audience.kind
        if kind == "segment":
            if not audience.segmentId or audience.filter or audience.contactIds:
                errors["audience"] = "Choose exactly one audience source."
                return
            try:
                ContactSegmentService(self.db).get(audience.segmentId, workspace_id, tenant_id)
            except SegmentNotFound:
                errors["audience.segmentId"] = "Segment not found in this workspace."
        elif kind == "filter":
            if not audience.filter or audience.segmentId or audience.contactIds:
                errors["audience"] = "Choose exactly one audience source."
                return
            try:
                validate_filter_tree(self.db, tenant_id, workspace_id, audience.filter)
            except FilterError as exc:
                errors["audience.filter"] = str(exc)
        elif kind == "contacts":
            if not audience.contactIds or audience.segmentId or audience.filter:
                errors["audience"] = "Choose exactly one audience source."
                return
            ids = list(dict.fromkeys(audience.contactIds))  # de-dupe, preserve order
            found = (
                self.db.query(Contact.id)
                .filter(Contact.tenant_id == tenant_id, Contact.workspace_id == workspace_id, Contact.id.in_(ids))
                .count()
            )
            if found != len(ids):
                errors["audience.contactIds"] = "One or more contacts are not in this workspace."
        else:
            errors["audience"] = "Choose exactly one audience source."

    def _active_channel(self, channel_id: str, tenant_id: str, workspace_id: str) -> Optional[Channel]:
        return (
            self.db.query(Channel)
            .filter(
                Channel.id == channel_id,
                Channel.tenant_id == tenant_id,
                Channel.workspace_id == workspace_id,
                Channel.is_active.is_(True),
                Channel.is_trashed.is_(False),
            )
            .first()
        )

    def _approved_template(self, template_id: str, tenant_id: str, channel_id: str) -> Optional[WhatsappTemplate]:
        return (
            self.db.query(WhatsappTemplate)
            .filter(
                WhatsappTemplate.id == template_id,
                WhatsappTemplate.tenant_id == tenant_id,
                WhatsappTemplate.channel_id == channel_id,
                WhatsappTemplate.status == "APPROVED",
            )
            .first()
        )

    def _validate_schedule(self, scheduled_at: Optional[datetime], errors: Dict[str, str]) -> None:
        if scheduled_at is None:
            return
        aware = scheduled_at if scheduled_at.tzinfo else scheduled_at.replace(tzinfo=timezone.utc)
        if aware <= datetime.now(timezone.utc):
            errors["scheduledAt"] = "Scheduled time must be in the future."

    # ── writes ───────────────────────────────────────────────────────────────
    def create(
        self, tenant_id: str, workspace_id: str, payload: BroadcastCreate, *, actor_user_id: Optional[str]
    ) -> BroadcastItem:
        errors: Dict[str, str] = {}
        name = (payload.name or "").strip()
        if not name:
            errors["name"] = "Name is required."
        elif len(name) > MAX_NAME_LEN:
            errors["name"] = f"Name must be at most {MAX_NAME_LEN} characters."

        channel = self._active_channel(payload.channelId, tenant_id, workspace_id)
        if channel is None:
            errors["channelId"] = "Select an active channel of this workspace."

        self._validate_audience(tenant_id, workspace_id, payload.audience, errors)

        template: Optional[WhatsappTemplate] = None
        if channel is not None:
            template = self._approved_template(payload.templateId, tenant_id, channel.id)
            if template is None:
                errors["templateId"] = "Select an approved template of this channel."
            else:
                shape = analyze_template(template.components_json)
                if shape.has_media_header:
                    errors["templateId"] = "Templates with a media header are not supported for broadcasts."
                else:
                    try:
                        validate_bindings(self.db, tenant_id, workspace_id, shape, payload.bindings)
                    except BindingValidationError as exc:
                        errors.update(exc.errors)

        self._validate_schedule(payload.scheduledAt, errors)

        if errors:
            raise BroadcastValidationError(errors)

        key_to_id, id_to_key, id_to_label = self._status_maps(tenant_id)
        row = Broadcast(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name=name,
            labels_json=payload.labels or [],
            channel_id=channel.id,
            audience_kind=payload.audience.kind,
            audience_segment_id=payload.audience.segmentId if payload.audience.kind == "segment" else None,
            audience_filter_json=(
                payload.audience.filter.model_dump()
                if payload.audience.kind == "filter" and payload.audience.filter
                else None
            ),
            audience_contact_ids_json=(
                payload.audience.contactIds if payload.audience.kind == "contacts" else None
            ),
            template_id=template.id,
            template_name=template.name,
            template_language=template.language,
            bindings_json=payload.bindings.model_dump(),
            status_id=key_to_id["DRAFT"],
            scheduled_at=payload.scheduledAt,
            created_by_user_id=actor_user_id,
        )
        self.repo.add(row)
        self.db.flush()
        emit_entity_event(
            self.db, "omnichannel_broadcast", "created", row, tenant_id=tenant_id, actor_id=actor_user_id
        )
        self.db.commit()
        self.db.refresh(row)
        return self._hydrate([row], tenant_id, id_to_key, id_to_label)[0]

    def update(
        self, broadcast_id: str, tenant_id: str, workspace_id: str, payload: BroadcastUpdate
    ) -> BroadcastItem:
        row = self._row_or_404(broadcast_id, tenant_id, workspace_id)
        key_to_id, id_to_key, id_to_label = self._status_maps(tenant_id)
        current_status = id_to_key.get(row.status_id)
        sent = payload.model_fields_set

        schedule_only = sent and sent <= {"scheduledAt"}
        if current_status not in _EDITABLE_STATUSES:
            if not (current_status in _SCHEDULE_ONLY_EDITABLE_STATUSES and schedule_only):
                raise BroadcastStatusConflict("broadcast_not_editable")

        errors: Dict[str, str] = {}
        channel: Optional[Channel] = None
        if "name" in sent:
            name = (payload.name or "").strip()
            if not name:
                errors["name"] = "Name is required."
            elif len(name) > MAX_NAME_LEN:
                errors["name"] = f"Name must be at most {MAX_NAME_LEN} characters."
        if "channelId" in sent:
            channel = self._active_channel(payload.channelId, tenant_id, workspace_id)
            if channel is None:
                errors["channelId"] = "Select an active channel of this workspace."
        if "audience" in sent and payload.audience is not None:
            self._validate_audience(tenant_id, workspace_id, payload.audience, errors)

        template: Optional[WhatsappTemplate] = None
        effective_channel_id = channel.id if channel is not None else row.channel_id
        if ("templateId" in sent or "bindings" in sent or "channelId" in sent) and "channelId" not in errors:
            template_id = payload.templateId if "templateId" in sent else row.template_id
            template = self._approved_template(template_id, tenant_id, effective_channel_id)
            if template is None:
                errors["templateId"] = "Select an approved template of this channel."
            else:
                shape = analyze_template(template.components_json)
                if shape.has_media_header:
                    errors["templateId"] = "Templates with a media header are not supported for broadcasts."
                else:
                    bindings = (
                        payload.bindings
                        if "bindings" in sent
                        else BroadcastBindings.model_validate(
                            row.bindings_json or {"header": [], "body": [], "buttons": []}
                        )
                    )
                    try:
                        validate_bindings(self.db, tenant_id, workspace_id, shape, bindings)
                    except BindingValidationError as exc:
                        errors.update(exc.errors)

        if "scheduledAt" in sent:
            self._validate_schedule(payload.scheduledAt, errors)

        if errors:
            raise BroadcastValidationError(errors)

        if "name" in sent:
            row.name = payload.name.strip()
        if "labels" in sent:
            row.labels_json = payload.labels or []
        if "channelId" in sent and channel is not None:
            row.channel_id = channel.id
        if "audience" in sent and payload.audience is not None:
            row.audience_kind = payload.audience.kind
            row.audience_segment_id = payload.audience.segmentId if payload.audience.kind == "segment" else None
            row.audience_filter_json = (
                payload.audience.filter.model_dump()
                if payload.audience.kind == "filter" and payload.audience.filter
                else None
            )
            row.audience_contact_ids_json = (
                payload.audience.contactIds if payload.audience.kind == "contacts" else None
            )
        if template is not None:
            row.template_id = template.id
            row.template_name = template.name
            row.template_language = template.language
        if "bindings" in sent:
            row.bindings_json = payload.bindings.model_dump()
        if "scheduledAt" in sent:
            row.scheduled_at = payload.scheduledAt

        self.db.flush()
        emit_entity_event(self.db, "omnichannel_broadcast", "updated", row, tenant_id=tenant_id)
        self.db.commit()
        self.db.refresh(row)
        return self._hydrate([row], tenant_id, id_to_key, id_to_label)[0]

    def delete(self, broadcast_id: str, tenant_id: str, workspace_id: str) -> None:
        row = self._row_or_404(broadcast_id, tenant_id, workspace_id)
        _, id_to_key, _ = self._status_maps(tenant_id)
        if id_to_key.get(row.status_id) != "DRAFT":
            raise BroadcastStatusConflict("broadcast_not_editable")
        self.repo.delete(row)
        self.db.commit()

    def duplicate(self, broadcast_id: str, tenant_id: str, workspace_id: str, *, actor_user_id: Optional[str]) -> BroadcastItem:
        row = self._row_or_404(broadcast_id, tenant_id, workspace_id)
        key_to_id, id_to_key, id_to_label = self._status_maps(tenant_id)
        dup = Broadcast(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name=f"{row.name} (copy)",
            labels_json=row.labels_json,
            channel_id=row.channel_id,
            audience_kind=row.audience_kind,
            audience_segment_id=row.audience_segment_id,
            audience_filter_json=row.audience_filter_json,
            audience_contact_ids_json=row.audience_contact_ids_json,
            template_id=row.template_id,
            template_name=row.template_name,
            template_language=row.template_language,
            bindings_json=row.bindings_json,
            status_id=key_to_id["DRAFT"],
            scheduled_at=None,
            created_by_user_id=actor_user_id,
        )
        self.repo.add(dup)
        self.db.flush()
        emit_entity_event(
            self.db, "omnichannel_broadcast", "created", dup, tenant_id=tenant_id, actor_id=actor_user_id
        )
        self.db.commit()
        self.db.refresh(dup)
        return self._hydrate([dup], tenant_id, id_to_key, id_to_label)[0]
